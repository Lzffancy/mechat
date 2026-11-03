"""把解密后的 message_*.db 导成 JSONL。

4.x 的存储结构（实测 4.1.15.55）：

  Name2Id(rowid, user_name, is_session)   rowid 就是消息里的 real_sender_id
  每个会话一张表 Msg_<md5(user_name)>      表名 = "Msg_" + md5(utf-8 字符串)
  消息列固定一套 local_id/server_id/local_type/real_sender_id/create_time/
  message_content/compress_content/WCDB_CT_message_content...
  WCDB_CT_message_content == 4 表示 message_content 是 zstd 压缩（魔数 28 b5 2f fd）

    python -m wxchat_export.export_messages --db message_1.db --out msgs.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys

TYPE_MAP = {
    1: "text", 3: "image", 34: "voice", 37: "friend_request", 42: "card",
    43: "video", 47: "sticker", 48: "location", 49: "app", 50: "call",
    51: "status", 10000: "system", 10002: "recall",
}

# local_type 是 64 位复合值：高 32 位 sub_type，低 32 位主类型。
# 例：244813135921 == (57 << 32) | 49 -> app 消息，sub_type 57（引用）
APP_SUB = {
    5: "link", 6: "file", 19: "merged_forward", 33: "miniprogram",
    36: "miniprogram", 40: "channels", 51: "channels_live", 57: "quote",
    62: "channels_video", 63: "channels_video", 74: "file", 87: "group_announce",
    2000: "transfer", 2001: "redpacket",
}


def type_label(local_type: int) -> str:
    base = local_type & 0xFFFFFFFF
    sub = local_type >> 32
    name = TYPE_MAP.get(base, f"type_{base}")
    if sub:
        return f"{name}:{APP_SUB.get(sub, sub)}"
    return name


ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def _maybe_zstd(raw: bytes, ctype: int) -> bytes:
    """ctype==4 或魔数命中则解压。失败就原样返回，不中断导出。"""
    if not raw:
        return raw
    if ctype != 4 and not raw.startswith(ZSTD_MAGIC):
        return raw
    try:
        import zstandard
        return zstandard.ZstdDecompressor().decompress(raw, max_output_size=16 << 20)
    except Exception:  # noqa: BLE001
        try:
            import zstandard
            return zstandard.ZstdDecompressor().stream_reader(_BytesReader(raw)).read()
        except Exception:  # noqa: BLE001
            return raw


class _BytesReader:
    """zstd 流式解压需要 read 接口，未知长度时用这个顶一下。"""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._data) - self._pos
        chunk = self._data[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk


def _text(v) -> str:
    """text_factory=bytes 下所有字符串都是 bytes，统一转回来。"""
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).decode("utf-8", "replace")
    return v or ""


def build_maps(con: sqlite3.Connection) -> tuple[dict[int, str], dict[str, str]]:
    """id -> user_name，以及 md5(user_name) -> user_name。"""
    id2name: dict[int, str] = {}
    hash2name: dict[str, str] = {}
    for rowid, name in con.execute("select rowid, user_name from Name2Id"):
        name = _text(name)
        if not name:
            continue
        id2name[rowid] = name
        hash2name[hashlib.md5(name.encode("utf-8")).hexdigest()] = name
    return id2name, hash2name


def list_msg_tables(con: sqlite3.Connection) -> list[str]:
    return [_text(r[0]) for r in con.execute(
        "select name from sqlite_master where type='table' and name like 'Msg\\_%' escape '\\'"
    )]


def export(db: str, out_path: str, *, self_name: str | None = None,
           max_rows: int | None = None) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.text_factory = bytes
    id2name, hash2name = build_maps(con)

    tables = list_msg_tables(con)
    stats = {"tables": len(tables), "rows": 0, "unmapped": 0, "zstd": 0,
             "by_type": {}, "chats": 0}
    unresolved = []
    touched_chats = set()

    fout = open(out_path, "w", encoding="utf-8")
    try:
        for table in tables:
            uname = hash2name.get(table[4:])
            if uname is None:
                stats["unmapped"] += 1
                unresolved.append(table)
            else:
                touched_chats.add(uname)

            sql = (f'select local_id, local_type, real_sender_id, create_time, '
                   f'message_content, WCDB_CT_message_content from "{table}" '
                   f'order by create_time')
            for local_id, ltype, sender_id, ctime, content, ctype in con.execute(sql):
                text = content or b""
                if isinstance(text, (bytes, bytearray)):
                    if ctype == 4 or text.startswith(ZSTD_MAGIC):
                        stats["zstd"] += 1
                        text = _maybe_zstd(bytes(text), ctype or 0)
                    text = text.decode("utf-8", "replace")
                sender = id2name.get(sender_id or 0, f"id:{sender_id}")
                rec = {
                    "chat": uname or table,
                    "local_id": local_id,
                    "time": ctime,
                    "type": type_label(ltype),
                    "local_type": ltype,
                    "sender": sender,
                    "is_self": bool(self_name and sender == self_name),
                    "content": text,
                }
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                stats["rows"] += 1
                stats["by_type"][rec["type"]] = stats["by_type"].get(rec["type"], 0) + 1
                if max_rows and stats["rows"] >= max_rows:
                    raise _Stop()
    except _Stop:
        pass
    finally:
        fout.close()
        con.close()

    stats["chats"] = len(touched_chats)
    if unresolved:
        stats["unresolved_sample"] = unresolved[:5]
    return stats


class _Stop(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="导出解密库中的消息为 JSONL")
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--self-name", help="本人的 wxid，用于标记 is_self")
    ap.add_argument("--max-rows", type=int, help="调试用行数上限")
    args = ap.parse_args(argv)

    if not os.path.exists(args.db):
        raise SystemExit(f"找不到 {args.db}")

    stats = export(args.db, args.out, self_name=args.self_name, max_rows=args.max_rows)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"\n输出 {args.out}  ({os.path.getsize(args.out)/1024/1024:.1f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
