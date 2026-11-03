"""用 check_page1 对真实库逐库验证参数是否成立。

    python verify_key.py <passphrase_hex> [--xor-key <hex>] [--data-root <dir>]
"""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wxchat_export.page import PAGE_SIZE, check_page1, derive_keys, decrypt_page  # noqa: E402

DEFAULT_ROOT = os.path.expanduser(
    r"~\xwechat_files"
)


def find_dbs(root: str) -> list[str]:
    out = []
    for path in glob.glob(os.path.join(root, "**", "*.db"), recursive=True):
        if path.endswith(("-wal", "-shm")):
            continue
        if os.path.getsize(path) >= PAGE_SIZE:
            out.append(path)
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("passphrase")
    ap.add_argument("--xor-key")
    ap.add_argument("--data-root", default=DEFAULT_ROOT)
    ap.add_argument("--decrypt-smallest", action="store_true",
                    help="顺带解密最小的库做端到端验证")
    args = ap.parse_args()

    phrase = bytes.fromhex(args.passphrase.replace(" ", ""))
    xor_key = bytes.fromhex(args.xor_key.replace(" ", "")) if args.xor_key else None

    accts = [d for d in glob.glob(os.path.join(args.data_root, "*"))
             if os.path.isdir(os.path.join(d, "db_storage"))]
    if not accts:
        print(f"未找到账号目录: {args.data_root}")
        return 1

    total = ok = 0
    smallest = None
    for acct in accts:
        print(f"\n账号 {os.path.basename(acct)}")
        for db in find_dbs(os.path.join(acct, "db_storage")):
            total += 1
            with open(db, "rb") as f:
                head = f.read(PAGE_SIZE)
            keys = check_page1(head, phrase, xor_key)
            size = os.path.getsize(db) / 1024 / 1024
            salt = head[:16].hex()
            if keys:
                ok += 1
                print(f"  PASS  {os.path.basename(db):<24} {size:>7.1f}MB  salt={salt}")
                if smallest is None or os.path.getsize(db) < smallest[0]:
                    smallest = (os.path.getsize(db), db, keys)
            else:
                print(f"  FAIL  {os.path.basename(db):<24} {size:>7.1f}MB  salt={salt}")

    print(f"\n{ok}/{total} 个库 HMAC 校验通过")

    if args.decrypt_smallest and smallest:
        _, db, keys = smallest
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "selftest_" + os.path.basename(db))
        print(f"\n端到端解密 {os.path.basename(db)} -> {out}")
        with open(db, "rb") as fin, open(out, "wb") as fout:
            page_no = 1
            while True:
                page = fin.read(PAGE_SIZE)
                if len(page) < PAGE_SIZE:
                    break
                fout.write(decrypt_page(page, keys, page_no))
                page_no += 1
        import sqlite3
        con = sqlite3.connect(out)
        verdict = con.execute("pragma integrity_check").fetchone()[0]
        tables = con.execute(
            "select count(*) from sqlite_master where type='table'").fetchone()[0]
        print(f"  integrity_check = {verdict}, 表数量 = {tables}")
        con.close()
        return 0 if verdict == "ok" else 3

    return 0 if ok == total else 2


if __name__ == "__main__":
    raise SystemExit(main())
