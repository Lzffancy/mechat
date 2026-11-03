"""自洽性测试：按 SQLCipher 4 规则造一个加密页，再用 wxchat_export 解回来。

注意：本测试证明的是加解密实现互逆、页布局理解一致，
不证明参数与微信实际格式匹配 —— 后者靠真实库的 page-1 HMAC 校验。

    python -m tests.test_roundtrip
    python -m tests.test_roundtrip --db <真实加密库>   # 额外跑容错测试
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

from Crypto.Cipher import AES
from Crypto.Hash import SHA512
from Crypto.Protocol.KDF import PBKDF2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wxchat_export.page import (  # noqa: E402
    HMAC_SIZE,
    IV_SIZE,
    KEY_SIZE,
    PAGE_SIZE,
    RESERVE,
    SALT_SIZE,
    SQLITE_HEADER,
    check_page1,
    decrypt_page,
    derive_keys,
)

MAC_OFFSET = PAGE_SIZE - RESERVE + IV_SIZE  # 4032
IV_OFFSET = MAC_OFFSET - IV_SIZE            # 4016


def build_encrypted_page(plain_page1: bytes, passphrase: bytes) -> tuple[bytes, bytes]:
    """按 SQLCipher 4 规则加密 page 1，返回 (加密页, salt)。"""
    import hmac as _hmac

    salt = os.urandom(SALT_SIZE)
    dek = PBKDF2(passphrase, salt, dkLen=KEY_SIZE, count=256_000, hmac_hash_module=SHA512)
    mac_key = PBKDF2(dek, bytes(b ^ 0x3A for b in salt), dkLen=KEY_SIZE, count=2,
                     hmac_hash_module=SHA512)
    iv = os.urandom(IV_SIZE)
    # page 1 只加密明文的 [16:4016]
    ct = AES.new(dek, AES.MODE_CBC, iv).encrypt(plain_page1[SALT_SIZE:PAGE_SIZE - RESERVE])
    assert len(ct) == PAGE_SIZE - SALT_SIZE - RESERVE == 4000

    page = salt + ct + iv
    mac = _hmac.new(mac_key, page[SALT_SIZE:MAC_OFFSET], SHA512)
    mac.update(struct.pack("<I", 1))
    page += mac.digest()
    assert len(page) == PAGE_SIZE
    return page, salt


def make_fake_plain_page1() -> bytes:
    """构造一个结构合法的明文 page 1（header offset 16..18 = 4096 大端）。"""
    body = bytearray(os.urandom(PAGE_SIZE))
    body[:16] = SQLITE_HEADER
    body[16:18] = b"\x10\x00"        # page size 4096
    body[18] = 1                     # write version
    body[19] = 1                     # read version
    body[20] = RESERVE               # reserved bytes per page = 80
    body[21] = 64
    body[22] = 32
    body[23] = 32
    return bytes(body)


def test_roundtrip() -> bool:
    passphrase = os.urandom(KEY_SIZE)
    plain = make_fake_plain_page1()
    enc, salt = build_encrypted_page(plain, passphrase)

    keys = check_page1(enc, passphrase)
    if keys is None:
        print("FAIL check_page1 未识别正确密钥")
        return False
    if keys.salt != salt:
        print("FAIL salt 不一致")
        return False

    out = decrypt_page(enc, keys, 1)
    if out[:16] != SQLITE_HEADER:
        print("FAIL 头部不匹配")
        return False
    if out[16:PAGE_SIZE - RESERVE] != plain[16:PAGE_SIZE - RESERVE]:
        print("FAIL 正文不匹配")
        return False
    if out[PAGE_SIZE - RESERVE:] != b"\x00" * RESERVE:
        print("FAIL 尾部未补零")
        return False

    # 错误密钥必须拒绝，而不是"解出垃圾"
    if check_page1(enc, os.urandom(KEY_SIZE)) is not None:
        print("FAIL 错误密钥被接受")
        return False

    # xor_key 混淆路径
    xor_key = os.urandom(KEY_SIZE)
    real = os.urandom(KEY_SIZE)
    scrambled = bytes(a ^ b for a, b in zip(real, xor_key))
    enc2, _ = build_encrypted_page(plain, real)
    if check_page1(enc2, scrambled, xor_key) is None:
        print("FAIL xor_key 还原路径失败")
        return False

    print("PASS 往返 + 错误密钥拒绝 + xor_key 还原")
    return True


def test_tamper() -> bool:
    """改一个字节必须让 HMAC 失败。"""
    passphrase = os.urandom(KEY_SIZE)
    enc, _ = build_encrypted_page(make_fake_plain_page1(), passphrase)
    bad = bytearray(enc)
    bad[100] ^= 0x01
    keys = derive_keys(passphrase, bytes(enc[:SALT_SIZE]))
    try:
        decrypt_page(bytes(bad), keys, 1)
    except Exception as exc:  # noqa: BLE001
        print(f"PASS 篡改被检出 ({type(exc).__name__})")
        return True
    print("FAIL 篡改未被检出")
    return False


def test_real_db_tolerance(db: str) -> bool:
    """拿真实库的前 4096 字节，喂随机密钥，必须返回 None 且不抛异常。"""
    if not os.path.exists(db):
        print(f"SKIP 找不到 {db}")
        return True
    with open(db, "rb") as f:
        head = f.read(PAGE_SIZE)
    if len(head) != PAGE_SIZE:
        print("SKIP 文件太短")
        return True
    print(f"     真实库 salt = {head[:16].hex()}")
    try:
        for _ in range(3):
            if check_page1(head, os.urandom(KEY_SIZE)) is not None:
                print("FAIL 随机密钥意外通过")
                return False
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL 容错失败: {exc}")
        return False
    print("PASS 真实库对错误密钥稳定返回 None")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="真实加密库路径，做容错测试")
    args = ap.parse_args()

    ok = True
    ok &= test_roundtrip()
    ok &= test_tamper()
    if args.db:
        ok &= test_real_db_tolerance(args.db)
    print("\n全部通过" if ok else "\n有用例失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
