# -*- coding: utf-8 -*-
"""统一数据模型。

上游有三条来路，字段各不相同，分析层不应该关心这些差异：

1. `export_group.py` 导出的 JSONL（一行一条消息，app:* 消息的 XML 还没拆）
2. `export_group.py` 导出的 `_可读.txt`（按天分段，正文已压平，丢了 wxid）
3. 中间态 pickle `{'msgs': [...], 'members': {...}}`（本库自己落的缓存格式）

全部在 `load()` 里归一成 `Group`，之后的模块只吃 `Message`。
"""
from __future__ import annotations

import csv
import html
import json
import pickle
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

FMT = "%Y-%m-%d %H:%M:%S"

# 无正文的媒体类型，统计口径上要单独算
MEDIA_TYPES = frozenset(
    {"image", "sticker", "video", "voice", "file", "location", "card", "emotion", "link"}
)


@dataclass(slots=True)
class Message:
    """一条群消息。

    `wxid` 为空表示系统事件（撤回、拍一拍、入群），这些行的 `sender` 是占位名，
    统计成员榜时必须剔除，否则会凭空多出一个人。
    """

    idx: int
    ts: float
    wxid: str
    sender: str
    type: str
    text: str = ""
    ats: tuple[str, ...] = ()
    ref_wxid: str | None = None
    ref_name: str | None = None

    # ---- 派生字段 ----
    @property
    def time(self) -> str:
        return datetime.fromtimestamp(self.ts).strftime(FMT)

    @property
    def date(self) -> str:
        return self.time[:10]

    @property
    def month(self) -> str:
        return self.time[:7]

    @property
    def hour(self) -> int:
        return int(self.time[11:13])

    @property
    def weekday(self) -> int:
        return datetime.fromtimestamp(self.ts).weekday()

    @property
    def is_system(self) -> bool:
        return not self.wxid or self.type == "system"

    @property
    def is_media(self) -> bool:
        return self.type in MEDIA_TYPES or (self.text or "").startswith("[")

    @property
    def is_quote(self) -> bool:
        return bool(self.ref_wxid)

    @classmethod
    def from_dict(cls, d: dict, idx: int = 0) -> "Message":
        """接受任意上游字典，缺字段不报错。"""
        raw_time = d.get("time")
        ts = d.get("ts")
        if ts is None:
            if not raw_time:
                raise ValueError(f"消息缺少 time/ts: {d!r}")
            ts = datetime.strptime(raw_time[:19], FMT).timestamp()
        elif not raw_time:
            raw_time = datetime.fromtimestamp(ts).strftime(FMT)
        ats = d.get("ats") or ()
        if isinstance(ats, str):
            ats = (ats,)
        return cls(
            idx=idx,
            ts=float(ts),
            wxid=(d.get("wxid") or d.get("sender_wxid") or ""),
            sender=(d.get("sender") or d.get("name") or ""),
            type=(d.get("type") or "text"),
            text=(d.get("text") or d.get("content") or ""),
            ats=tuple(x for x in ats if x),
            ref_wxid=d.get("ref_wxid") or None,
            ref_name=d.get("ref_name") or d.get("quote") or None,
        )

    def to_dict(self) -> dict:
        return {
            "idx": self.idx,
            "ts": self.ts,
            "time": self.time,
            "wxid": self.wxid,
            "sender": self.sender,
            "type": self.type,
            "text": self.text,
            "ats": list(self.ats),
            "ref_wxid": self.ref_wxid,
            "ref_name": self.ref_name,
        }


@dataclass
class Group:
    """一个群的全部消息 + 成员表。"""

    name: str
    msgs: list[Message]
    members: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.msgs.sort(key=lambda m: m.ts)
        for i, m in enumerate(self.msgs):
            m.idx = i
        self._names = None
        self._counts = None

    # ---- 常用切片 ----
    def real(self) -> list[Message]:
        """真人消息（剔系统事件）。占比类统计一律用这个做分母。"""
        return [m for m in self.msgs if not m.is_system]

    def texts(self) -> list[Message]:
        """有正文的真人消息，分词和话题分析用。"""
        return [m for m in self.real() if m.text and not m.is_media]

    def of(self, wxid: str) -> list[Message]:
        return [m for m in self.msgs if m.wxid == wxid]

    def contexts(self, start: int, end: int) -> list[Message]:
        return self.msgs[max(0, start) : max(0, end)]

    # ---- 名字 ----
    @property
    def names(self):
        if self._names is None:
            from .clean import NameResolver

            self._names = NameResolver(self)
        return self._names

    def name_of(self, wxid: str, maxlen: int = 14) -> str:
        return self.names.display(wxid)[:maxlen]

    # ---- 计数 ----
    @property
    def counts(self) -> dict[str, int]:
        if self._counts is None:
            c: dict[str, int] = {}
            for m in self.msgs:
                if m.wxid:
                    c[m.wxid] = c.get(m.wxid, 0) + 1
            self._counts = c
        return self._counts

    def top_members(self, n: int = 20, exclude_system: bool = True) -> list[tuple[str, int]]:
        items = self.counts.items()
        return sorted(items, key=lambda x: -x[1])[:n]

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as f:
            pickle.dump(
                {"group": self.name, "members": self.members,
                 "msgs": [m.to_dict() for m in self.msgs]},
                f,
            )
        return p


# --------------------------------------------------------------------------
# 加载
# --------------------------------------------------------------------------

def load(path: str | Path, name: str = "", members: str | Path | None = None) -> Group:
    """按后缀分派。`members` 指向 `_members.csv` 时补上昵称表。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    suffix = p.suffix.lower()
    if suffix == ".jsonl":
        group = load_jsonl(p, name=name or p.stem, members=members)
    elif suffix in (".pkl", ".pickle"):
        group = load_pickle(p, name=name or p.stem)
    elif suffix == ".txt":
        group = load_readable_txt(p, name=name or p.stem)
    else:
        raise ValueError(f"不认识的输入格式: {p.suffix}")
    return group


def load_jsonl(path: str | Path, name: str = "", members: str | Path | None = None) -> Group:
    """`export_group.py` 的 JSONL：app 消息正文藏在 `<title>`，引用目标藏在 `refermsg`。"""
    p = Path(path)
    msgs: list[Message] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            rec = _flatten_app_xml(d)
            msgs.append(Message.from_dict(rec, idx=len(msgs)))
    mem = read_members_csv(members) if members else {}
    return Group(name=name or p.stem, msgs=msgs, members=mem)


def _flatten_app_xml(d: dict) -> dict:
    """把 app:* 消息的 XML 拆成 text / ref_wxid / ref_name。"""
    rec = dict(d)
    t = (d.get("type") or "")
    c = d.get("content") or ""
    rec.setdefault("text", "")
    if t == "text":
        rec["text"] = c
    elif t.startswith("app:"):
        m = re.search(r"<title>(.*?)</title>", c, re.S)
        if m:
            rec["text"] = html.unescape(m.group(1))
        if t == "app:quote":
            rm = re.search(r"<refermsg>.*?<chatusr>(.*?)</chatusr>", c, re.S)
            nm = re.search(r"<refermsg>.*?<displayname>(.*?)</displayname>", c, re.S)
            if rm:
                rec["ref_wxid"] = rm.group(1).strip()
            if nm:
                rec["ref_name"] = html.unescape(nm.group(1).strip())
    elif t in MEDIA_TYPES:
        rec["text"] = ""
    txt = rec.get("text") or ""
    if "@" in txt:
        rec["ats"] = re.findall(r"@([^\s@\u2005]+)", txt)
    return rec


_READ_DATE = re.compile(r"^=====\s*(\d{4}-\d{2}-\d{2})\s*=====\s*$")
_READ_MSG = re.compile(r"^(\d{1,2}:\d{2}:\d{2})\s+([^:]{1,40}):\s*(.*)$")


def load_readable_txt(path: str | Path, name: str = "") -> Group:
    """`_可读.txt`：按天分段，只有名字没有 wxid。

    这条路丢了 wxid，网络分析做不了，但用来抽样阅读、跑词频和词典话题够用。
    """
    p = Path(path)
    msgs: list[Message] = []
    cur_date = None
    with p.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            m = _READ_DATE.match(line)
            if m:
                cur_date = m.group(1)
                continue
            m = _READ_MSG.match(line)
            if not (m and cur_date):
                continue
            t, who, body = m.groups()
            quote = ""
            if " | 引用: " in body:
                body, quote = body.split(" | 引用: ", 1)
            ts = datetime.strptime(f"{cur_date} {t}", FMT).timestamp()
            msgs.append(
                Message(
                    idx=len(msgs), ts=ts, wxid=who.strip(), sender=who.strip(),
                    type="text", text=body.strip(), ref_name=quote.strip()[:500] or None,
                )
            )
    return Group(name=name or p.stem, msgs=msgs)


def load_pickle(path: str | Path, name: str = "") -> Group:
    """读本库缓存或其他脚本落的 `{'msgs': [...], 'members': {...}}`。"""
    p = Path(path)
    with p.open("rb") as f:
        d = pickle.load(f)
    if isinstance(d, dict) and "msgs" in d:
        rows, mem = d["msgs"], d.get("members") or {}
        group_name = d.get("group") or name or p.stem
    elif isinstance(d, list):
        rows, mem, group_name = d, {}, name or p.stem
    else:
        raise ValueError("pickle 结构不认识，需要 {'msgs': [...], 'members': {...}}")
    msgs = [m if isinstance(m, Message) else Message.from_dict(m, idx=i)
            for i, m in enumerate(rows)]
    return Group(name=group_name, msgs=msgs, members=mem)


def read_members_csv(path: str | Path) -> dict[str, dict]:
    """`export_group.py` 的 `_members.csv`（utf-8-sig，中文表头）。"""
    mem: dict[str, dict] = {}
    with Path(path).open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            wx = row.get("wxid") or ""
            if not wx:
                continue
            mem[wx] = {
                "member_id": row.get("member_id", ""),
                "nick": row.get("昵称", ""),
                "remark": row.get("备注", ""),
                "display": row.get("显示名") or row.get("昵称") or "",
                "cnt_declared": int(row.get("发言数") or 0),
            }
    return mem
