"""明文库勘探 + 导出。

4.x 的表结构随版本变，所以不自带字段映射，先看 schema 再导。

    python -m wxchat_export.export --db plain.db --schema
    python -m wxchat_export.export --db plain.db --table message --out msgs.jsonl
    python -m wxchat_export.export --db plain.db --sql "select * from message limit 5"
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys


def print_schema(db: str) -> None:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    tables = con.execute(
        "select name, type from sqlite_master where type in ('table','view') "
        "and name not like 'sqlite_%' order by name"
    ).fetchall()
    print(f"共 {len(tables)} 个表/视图\n")
    for name, kind in tables:
        try:
            rows = con.execute(f'select count(*) from "{name}"').fetchone()[0]
        except sqlite3.DatabaseError:
            rows = -1
        print(f"[{kind}] {name}  ({rows} 行)")
        try:
            cols = con.execute(f'pragma table_info("{name}")').fetchall()
            print("    " + ", ".join(f"{c[1]}:{c[2]}" for c in cols))
        except sqlite3.DatabaseError as exc:
            print(f"    (读列失败: {exc})")
        print()
    con.close()


def export_table(db: str, table: str, out: str, limit: int | None = None) -> int:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.text_factory = bytes  # 有些字段是 blob，避免 decode 崩掉
    sql = f'select * from "{table}"'
    if limit:
        sql += f" limit {limit}"
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    n = 0
    with open(out, "w", encoding="utf-8") as f:
        for row in cur:
            rec = {}
            for k, v in zip(cols, row):
                if isinstance(v, (bytes, bytearray)):
                    try:
                        rec[k] = v.decode("utf-8")
                    except UnicodeDecodeError:
                        rec[k] = "hex:" + v.hex()
                else:
                    rec[k] = v
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    con.close()
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="明文库勘探与导出")
    ap.add_argument("--db", required=True, help="已解密的 .db")
    ap.add_argument("--schema", action="store_true", help="打印全部表和列")
    ap.add_argument("--table", help="导出该表为 JSONL")
    ap.add_argument("--out", help="输出 JSONL 路径")
    ap.add_argument("--limit", type=int, help="限制行数（调试用）")
    ap.add_argument("--sql", help="直接执行一条查询并打印前 20 行")
    args = ap.parse_args(argv)

    if args.schema:
        print_schema(args.db)
        return 0

    if args.sql:
        con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        cur = con.execute(args.sql)
        cols = [d[0] for d in cur.description or []]
        print("\t".join(cols))
        for i, row in enumerate(cur):
            if i >= 20:
                print("...")
                break
            print("\t".join("" if v is None else str(v)[:120] for v in row))
        con.close()
        return 0

    if args.table:
        if not args.out:
            raise SystemExit("--table 需要配合 --out")
        n = export_table(args.db, args.table, args.out, args.limit)
        print(f"导出 {n} 行 -> {args.out}", file=sys.stderr)
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
