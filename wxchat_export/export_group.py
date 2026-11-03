"""导出指定群聊的全部消息，并把 sender_id 映射到昵称。

4.x 的群消息可能被拆到多个分库（message_0 / message_1 ...），同一个群在
每个库里都有独立的 Name2Id id 空间，所以必须逐库解析 sender，不能混用。

    python -m wxchat_export.export_group --name 示例群 --root <解密库目录> --out <输出目录>

昵称取值顺序：contact.remark（备注）> contact.nick_name（昵称）> wxid
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from .export_messages import _maybe_zstd, type_label, _text

TZ = timezone(timedelta(hours=8))

# 微信里存在把昵称设成纯控制字符的情况（实测 \x7f\x7f），
# 直接输出会变成不可见字符，这里清洗掉并可回退到 wxid。
_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

# 群聊里他人消息的 message_content 前缀是 "<发送者wxid>: "，自己的不带。
# 这个前缀比 real_sender_id 更直接，实测能补上 Name2Id 里 user_name 为空的 id。
_PREFIX = re.compile(
    r"^((?:wxid_[A-Za-z0-9_-]+)|(?:\d+@chatroom)|(?:gh_[A-Za-z0-9_-]+)|(?:\d+@openim)):\s*"
)


def clean_name(name: str | None, fallback: str) -> str:
    c = _CTRL.sub("", name or "").strip()
    return c or fallback


def find_group(contact_db: str, name: str) -> list[tuple[str, str, str]]:
    """按昵称/备注模糊匹配群。返回 [(username, nick, remark)]。"""
    con = sqlite3.connect(f"file:{contact_db}?mode=ro", uri=True)
    rows = con.execute(
        "select username, nick_name, remark from contact "
        "where username like '%@chatroom' and (nick_name like ? or remark like ?)",
        (f"%{name}%", f"%{name}%"),
    ).fetchall()
    con.close()
    return [(u, n or "", r or "") for u, n, r in rows]


def build_nick_map(contact_db: str) -> dict[str, str]:
    con = sqlite3.connect(f"file:{contact_db}?mode=ro", uri=True)
    out = {}
    for username, nick, remark in con.execute(
            "select username, nick_name, remark from contact"):
        if username:
            out[username] = (remark or "").strip() or (nick or "").strip() or username
    con.close()
    return out


def group_members(contact_db: str, group_id: str) -> list[dict]:
    con = sqlite3.connect(f"file:{contact_db}?mode=ro", uri=True)
    rid = con.execute("select id from chat_room where username=?", (group_id,)).fetchone()
    if not rid:
        con.close()
        return []
    rows = con.execute(
        "select m.member_id, c.username, c.nick_name, c.remark "
        "from chatroom_member m left join contact c on c.id = m.member_id "
        "where m.room_id = ? order by m.member_id", (rid[0],)).fetchall()
    con.close()
    return [{"member_id": r[0], "wxid": r[1], "nick": r[2] or "", "remark": r[3] or ""}
            for r in rows]


def read_db(db: str, target: str, nicks: dict[str, str], nick_of: dict[int, str]):
    """从单个分库读该群消息，yield 标准化 dict。"""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.text_factory = bytes
    tabs = {_text(r[0]) for r in con.execute(
        "select name from sqlite_master where type='table'")}
    if target not in tabs:
        con.close()
        return

    id2name: dict[int, str] = {}
    empty_ids: set[int] = set()
    if "Name2Id" in tabs:
        for rowid, uname in con.execute("select rowid, user_name from Name2Id"):
            uname = _text(uname)
            if uname:
                id2name[rowid] = uname
            else:
                empty_ids.add(rowid)
        nick_of = {rowid: nicks.get(u, u) for rowid, u in id2name.items()}

    sql = (f'select local_id, local_type, real_sender_id, create_time, sort_seq, '
           f'message_content, WCDB_CT_message_content, server_id from "{target}" '
           f'order by create_time, sort_seq')
    for local_id, ltype, sid, ctime, sort_seq, content, ctype, server_id in con.execute(sql):
        raw = content or b""
        if isinstance(raw, (bytes, bytearray)):
            if ctype == 4 or raw.startswith(b"\x28\xb5\x2f\xfd"):
                raw = _maybe_zstd(bytes(raw), ctype or 0)
            text = raw.decode("utf-8", "replace")
        else:
            text = raw or ""
        prefix_wxid = ""
        m = _PREFIX.match(text)
        if m:
            prefix_wxid = m.group(1)
            text = text[m.end():]
        wxid = prefix_wxid or id2name.get(sid or 0, "")
        raw_name = nicks.get(wxid) or nick_of.get(sid or 0) or wxid
        label = type_label(ltype)
        if label == "system" or (not prefix_wxid and (sid or 0) in empty_ids):
            # 系统事件的 real_sender_id 指向 Name2Id 里 user_name 为空的占位 id
            sender, raw_name, wxid = "（系统）", "（系统）", ""
        else:
            sender = clean_name(raw_name, wxid or f"id:{sid}")
        yield {
            "db": os.path.basename(db),
            "local_id": local_id,
            "server_id": server_id,
            "ts": ctime,
            "time": datetime.fromtimestamp(ctime, TZ).strftime("%Y-%m-%d %H:%M:%S")
            if ctime else "",
            "sort_seq": sort_seq,
            "sender_id": sid,
            "sender_wxid": wxid,
            "sender": sender,
            "sender_raw": raw_name,
            "type": label,
            "local_type": ltype,
            "content": text,
        }
    con.close()


def pretty_content(text: str, mtype: str) -> str:
    """把 XML 类消息（引用/链接/小程序/文件…）压成一行可读文本。

    JSONL 里保留原始 XML，这里只影响可读版输出。
    """
    t = (text or "").strip()
    if not t.startswith("<"):
        return t
    import xml.etree.ElementTree as ET

    def grab(root, tag: str) -> str:
        e = root.find(f".//{tag}")
        if e is None:
            return ""
        return "".join(e.itertext()).strip()

    try:
        root = ET.fromstring(t)
    except ET.ParseError:
        # 微信 XML 常带裸 & 或控制字符，退化成正则抽几个关键字段
        out = []
        for tag in ("title", "des"):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", t, re.S)
            if m and m.group(1).strip():
                out.append(m.group(1).strip())
        return " / ".join(out) or t[:120]

    if root.tag == "emoji":
        return f"[表情] {root.get('md5', '')[:8]}"
    if root.tag == "sysmsg":
        # 撤回/入群等系统事件，replacemsg 是微信给的中文提示
        note = grab(root, "replacemsg") or grab(root, "content")
        return "[系统] " + (note or root.get("type", ""))
    title = grab(root, "title")
    des = grab(root, "des")
    url = grab(root, "url")
    quoted = grab(root, "refermsg/content")
    md5 = grab(root, "md5")

    parts = []
    if title:
        parts.append(title)
    if des and des != title:
        parts.append(des)
    if quoted:
        parts.append("引用: " + quoted.replace("\n", " ")[:200])
    if url:
        parts.append(url)
    if not parts:
        parts.append("[" + mtype + "]")
    return " | ".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="导出群聊全部消息并映射昵称")
    ap.add_argument("--name", required=True, help="群昵称/备注关键词")
    ap.add_argument("--root", default=r"C:\Users\<you>\wx_dec", help="解密库目录")
    ap.add_argument("--out", default=None, help="输出目录")
    ap.add_argument("--pick", default=None, help="多个群命中时指定 username")
    args = ap.parse_args(argv)

    contact_db = os.path.join(args.root, "contact.db")
    if not os.path.exists(contact_db):
        raise SystemExit(f"缺 {contact_db}，先解密 contact.db")

    hits = find_group(contact_db, args.name)
    if not hits:
        raise SystemExit(f"没找到匹配 '{args.name}' 的群")
    if len(hits) > 1 and not args.pick:
        print("命中多个群，用 --pick 指定：", file=sys.stderr)
        for u, n, r in hits:
            print(f"  {u}  昵称={n}  备注={r}", file=sys.stderr)
        return 2
    group_id, nick, remark = next((h for h in hits if h[0] == args.pick), hits[0])
    display = clean_name(nick, "") or clean_name(remark, "") or group_id
    print(f"群: {group_id}  昵称={nick}  备注={remark}  用于显示={display}", file=sys.stderr)

    md5 = hashlib.md5(group_id.encode("utf-8")).hexdigest()
    target = f"Msg_{md5}"
    nicks = build_nick_map(contact_db)
    members = group_members(contact_db, group_id)

    dbs = sorted(
        os.path.join(args.root, f)
        for f in os.listdir(args.root)
        if f.startswith("message") and f.endswith(".db")
    )
    print(f"扫描 {len(dbs)} 个消息库，目标表 {target}", file=sys.stderr)

    seen = set()
    rows = []
    for db in dbs:
        n0 = len(rows)
        for rec in read_db(db, target, nicks, {}):
            key = rec["server_id"] or (rec["db"], rec["local_id"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(rec)
        print(f"  {os.path.basename(db):<16} +{len(rows) - n0}", file=sys.stderr)

    rows.sort(key=lambda r: (r["ts"] or 0, r["sort_seq"] or 0))

    # 目录名去掉括号类符号，保留可读主体
    folder = re.sub(r"[【】\[\]（）()]", "", display).strip() or display
    safe = "".join(c for c in folder if c not in r'\/:*?"<>|').strip() or "group"
    out_dir = args.out or os.path.join(args.root, safe)
    os.makedirs(out_dir, exist_ok=True)

    jsonl = os.path.join(out_dir, f"{safe}.jsonl")
    with open(jsonl, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    txt = os.path.join(out_dir, f"{safe}.txt")
    with open(txt, "w", encoding="utf-8") as f:
        for r in rows:
            body = r["content"].replace("\n", " ⏎ ")
            f.write(f"[{r['time']}] {r['sender']}: {body}\n")

    readable = os.path.join(out_dir, f"{safe}_可读.txt")
    with open(readable, "w", encoding="utf-8") as f:
        last_day = ""
        for r in rows:
            day = r["time"][:10]
            if day != last_day:
                f.write(f"\n===== {day} =====\n")
                last_day = day
            body = pretty_content(r["content"], r["type"]).replace("\n", " ")
            f.write(f"{r['time'][11:]} {r['sender']}: {body}\n")

    csv_path = os.path.join(out_dir, f"{safe}_members.csv")
    with open(csv_path, "w", encoding="utf-8-sig") as f:
        f.write("member_id,wxid,昵称,备注,显示名,发言数\n")
        cnt: dict[str, int] = {}
        for r in rows:
            cnt[r["sender_wxid"]] = cnt.get(r["sender_wxid"], 0) + 1
        for m in members:
            shown = clean_name(m["remark"], "") or clean_name(m["nick"], "") or m["wxid"]
            f.write(f"{m['member_id']},{m['wxid']},{m['nick']},{m['remark']},{shown},"
                    f"{cnt.get(m['wxid'], 0)}\n")

    types: dict[str, int] = {}
    senders: dict[str, int] = {}
    for r in rows:
        types[r["type"]] = types.get(r["type"], 0) + 1
        senders[r["sender"]] = senders.get(r["sender"], 0) + 1

    print(json.dumps({
        "group": group_id,
        "display": display,
        "messages": len(rows),
        "time_range": [rows[0]["time"], rows[-1]["time"]] if rows else [],
        "members": len(members),
        "distinct_senders": len(senders),
        "by_type": dict(sorted(types.items(), key=lambda kv: -kv[1])),
        "top_senders": dict(sorted(senders.items(), key=lambda kv: -kv[1])[:10]),
        "out": out_dir,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
