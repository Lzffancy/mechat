"""把微信 4.x 的加密库解成明文 SQLite。

用法：
    python -m wxchat_export.dump --db <加密库> --key <64位hex> --out <输出库>
    python -m wxchat_export.dump --db ... --key-file key.txt --xor-key <64位hex> --out ...
    python -m wxchat_export.dump --db ... --key-stdin --out ...

只读源文件，不修改原库。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from .page import (
    PAGE_SIZE,
    DecryptError,
    Keys,
    check_page1,
    decrypt_page,
    derive_keys,
    load_salt,
)


def _read_key(args) -> bytes:
    if args.key_file:
        with open(args.key_file, "r", encoding="utf-8") as f:
            text = f.read()
    elif args.key_stdin:
        print("粘贴密钥（32 字节 hex，或直接粘贴二进制），然后 Ctrl+Z 回车：", file=sys.stderr)
        text = sys.stdin.read()
    elif args.key:
        text = args.key
    else:
        raise SystemExit("必须提供 --key / --key-file / --key-stdin 之一")

    text = text.strip().strip("'\"")
    if text.startswith("x'") and text.endswith("'"):
        text = text[2:-1]
    text = "".join(text.split())
    try:
        raw = bytes.fromhex(text)
    except ValueError:
        raw = text.encode("utf-8", "surrogateescape")
    if len(raw) != 32:
        raise SystemExit(f"密钥长度应为 32 字节，实际 {len(raw)}")
    return raw


def _read_xor_key(args) -> bytes | None:
    if not args.xor_key:
        return None
    raw = bytes.fromhex("".join(args.xor_key.split()))
    if len(raw) != 32:
        raise SystemExit(f"xor_key 长度应为 32 字节，实际 {len(raw)}")
    return raw


def decrypt_file(src: str, dst: str, keys: Keys, *, quiet: bool = False) -> int:
    total = os.path.getsize(src)
    n_pages, tail = divmod(total, PAGE_SIZE)
    if tail:
        raise DecryptError(f"文件大小 {total} 不是 {PAGE_SIZE} 的整数倍，不是标准库文件")

    written = 0
    t0 = time.time()
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        for page_no in range(1, n_pages + 1):
            page = fin.read(PAGE_SIZE)
            if len(page) != PAGE_SIZE:
                raise DecryptError(f"读取 page {page_no} 时文件提前结束")
            fout.write(decrypt_page(page, keys, page_no))
            written += PAGE_SIZE
            if not quiet and page_no % 5000 == 0:
                pct = page_no * 100 // n_pages
                print(f"  {page_no}/{n_pages} 页 ({pct}%)", file=sys.stderr)
    if not quiet:
        dt = time.time() - t0
        print(f"  完成 {n_pages} 页 / {written/1024/1024:.1f} MB，耗时 {dt:.1f}s",
              file=sys.stderr)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="微信 4.x SQLCipher 库解密")
    ap.add_argument("--db", required=True, help="加密的 .db 路径")
    ap.add_argument("--out", required=True, help="输出明文 .db 路径")
    ap.add_argument("--key", help="32 字节密钥（64 位 hex）")
    ap.add_argument("--key-file", help="从文件读密钥")
    ap.add_argument("--key-stdin", action="store_true", help="从标准输入读密钥")
    ap.add_argument("--xor-key", help="Weixin.dll 中提取的 32 字节 XOR key（64 位 hex）")
    ap.add_argument("--skip-verify", action="store_true",
                    help="跳过全库 HMAC 校验（不推荐）")
    args = ap.parse_args(argv)

    if not os.path.exists(args.db):
        raise SystemExit(f"找不到文件: {args.db}")

    passphrase = _read_key(args)
    xor_key = _read_xor_key(args)

    # 先用 page 1 验证密钥，再全量解。省得解一半才发现密钥错。
    with open(args.db, "rb") as f:
        head = f.read(PAGE_SIZE)
    keys = check_page1(head, passphrase, xor_key)
    if keys is None:
        print("page 1 校验失败。可能原因：密钥错 / xor_key 错 / 该库不是 SQLCipher4 格式",
              file=sys.stderr)
        return 2

    # 单独确认 salt 与文件一致（防止 check_page1 的输入被复用错）
    if keys.salt != load_salt(args.db):
        raise DecryptError("salt 不一致，请重试")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    print(f"解密 {args.db} -> {args.out}", file=sys.stderr)
    decrypt_file(args.db, args.out, keys)

    # 尝试用标准 sqlite3 自检，失败不影响输出文件
    try:
        import sqlite3
        con = sqlite3.connect(args.out)
        ok = con.execute("pragma integrity_check").fetchone()[0]
        con.close()
        print(f"integrity_check: {ok}", file=sys.stderr)
        if ok != "ok":
            return 3
    except Exception as exc:  # noqa: BLE001
        print(f"（未做 sqlite 自检: {exc}）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
