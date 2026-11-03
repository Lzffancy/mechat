"""SQLCipher 4 页级解密 —— 微信 4.x 本地库格式。

参数来源（两处独立结论一致）：
  - LifeArchiveProject/WeChatDataAnalysis :: tools/key_v4.py  (4.1.13.12 实测)
  - labazhou2024/chatlog-keeper            (4.1.10.31+ 支持)

页布局：
  page 1: [ salt 16 ][ ciphertext 4000 ][ IV 16 ][ HMAC 64 ] = 4096
  others: [ ciphertext 4016            ][ IV 16 ][ HMAC 64 ] = 4096

HMAC 覆盖 ciphertext || IV，再追加 4 字节小端页码（encrypt-then-MAC）。
"""

from __future__ import annotations

import hmac as _hmac
import struct
from dataclasses import dataclass

from Crypto.Cipher import AES
from Crypto.Hash import SHA512
from Crypto.Protocol.KDF import PBKDF2

# ---- SQLCipher 4 固定参数 ----
PAGE_SIZE = 4096
SALT_SIZE = 16
KEY_SIZE = 32
IV_SIZE = 16
HMAC_SIZE = 64
RESERVE = IV_SIZE + HMAC_SIZE          # 80
KDF_ITER = 256_000
MAC_KDF_ITER = 2
MAC_SALT_XOR = 0x3A

SQLITE_HEADER = b"SQLite format 3\x00"

# 单页内各段偏移
_MAC_OFFSET = PAGE_SIZE - RESERVE + IV_SIZE   # 4032
_IV_OFFSET = _MAC_OFFSET - IV_SIZE            # 4016


class DecryptError(Exception):
    pass


@dataclass(frozen=True)
class Keys:
    dek: bytes       # 数据密钥，AES-256 用
    mac_key: bytes   # HMAC 密钥
    salt: bytes      # 该库自己的 salt


def load_salt(db_path: str) -> bytes:
    """读库文件前 16 字节。每个库的 salt 都不同。"""
    with open(db_path, "rb") as f:
        salt = f.read(SALT_SIZE)
    if len(salt) != SALT_SIZE:
        raise DecryptError(f"文件不足 {SALT_SIZE} 字节: {db_path}")
    return salt


def xor_passphrase(passphrase: bytes, xor_key: bytes | None) -> bytes:
    """内存里取到的 32 字节通常是被 XOR 混淆的，用 Weixin.dll 里的 key 还原。"""
    if xor_key is None:
        return passphrase
    if len(passphrase) != KEY_SIZE:
        raise DecryptError(f"passphrase 长度应为 {KEY_SIZE}，实际 {len(passphrase)}")
    if len(xor_key) != KEY_SIZE:
        raise DecryptError(f"xor_key 长度应为 {KEY_SIZE}，实际 {len(xor_key)}")
    return bytes(a ^ b for a, b in zip(passphrase, xor_key))


def derive_keys(passphrase: bytes, salt: bytes, xor_key: bytes | None = None) -> Keys:
    """passphrase + 库 salt -> (dek, mac_key)。"""
    raw = xor_passphrase(passphrase, xor_key)
    dek = PBKDF2(raw, salt, dkLen=KEY_SIZE, count=KDF_ITER, hmac_hash_module=SHA512)
    mac_salt = bytes(b ^ MAC_SALT_XOR for b in salt)
    mac_key = PBKDF2(dek, mac_salt, dkLen=KEY_SIZE, count=MAC_KDF_ITER,
                     hmac_hash_module=SHA512)
    return Keys(dek=dek, mac_key=mac_key, salt=salt)


def page_span(page_no: int) -> tuple[int, int]:
    """返回 (密文起始偏移, 密文长度)。page 1 前面被 salt 占了 16 字节。"""
    if page_no == 1:
        return SALT_SIZE, PAGE_SIZE - SALT_SIZE - RESERVE
    return 0, PAGE_SIZE - RESERVE


def _page_mac(keys: Keys, page: bytes, page_no: int) -> bytes:
    start, _ = page_span(page_no)
    mac = _hmac.new(keys.mac_key, page[start:_MAC_OFFSET], SHA512)
    mac.update(struct.pack("<I", page_no))
    return mac.digest()


def verify_page(page: bytes, keys: Keys, page_no: int) -> None:
    """校验单页完整性，不通过就抛。不要静默跳过 —— 失败即参数或密钥错。"""
    if len(page) != PAGE_SIZE:
        raise DecryptError(f"page {page_no} 长度 {len(page)} != {PAGE_SIZE}")
    expected = _page_mac(keys, page, page_no)
    actual = page[_MAC_OFFSET:_MAC_OFFSET + HMAC_SIZE]
    if not _hmac.compare_digest(expected, actual):
        raise DecryptError(
            f"page {page_no} HMAC 校验失败：密钥错、xor_key 错，或该库不是 4.x 格式"
        )


def decrypt_page(page: bytes, keys: Keys, page_no: int) -> bytes:
    """解密单页，输出 4096 字节明文页（末尾 80 字节补零，属 SQLite reserved 区）。"""
    verify_page(page, keys, page_no)
    start, ct_len = page_span(page_no)
    iv = page[_IV_OFFSET:_MAC_OFFSET]
    plain = AES.new(keys.dek, AES.MODE_CBC, iv).decrypt(page[start:start + ct_len])
    if page_no == 1:
        # plain 对应原 header 的 [16:4016]。header offset 16..18 是 page size
        # 的大端表示，4096 == 0x1000，所以这里必须是 b"\x10\x00"。
        # HMAC 已通过的前提下，再加一道结构自检，防参数组合错位时"解得出但解错"。
        if plain[:2] != b"\x10\x00":
            raise DecryptError(
                f"page 1 结构自检失败：page size 标记 {plain[:2].hex()} != 1000"
            )
        return SQLITE_HEADER + plain + b"\x00" * RESERVE
    return plain + b"\x00" * RESERVE


def check_page1(page: bytes, passphrase: bytes, xor_key: bytes | None = None) -> Keys | None:
    """候选密钥快速验证：只用 page 1 的 HMAC 判断对错。

    内存扫描会产出成百上千候选，这是唯一可靠的判别依据。
    """
    if len(page) < PAGE_SIZE:
        return None
    page = page[:PAGE_SIZE]
    try:
        keys = derive_keys(passphrase, page[:SALT_SIZE], xor_key)
    except (DecryptError, ValueError):
        return None
    try:
        verify_page(page, keys, 1)
    except DecryptError:
        return None
    return keys
