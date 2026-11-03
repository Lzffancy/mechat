# -*- coding: utf-8 -*-
"""昵称解析与文本清洗。

群聊里"谁是谁"比看起来难，四类坑：

1. 有人把昵称设成纯控制字符（实测 `\\x7f\\x7f`），显示出来是空白；
2. 同一个人改过多次昵称，当天的 @ 文本用的是旧名；
3. 改名后 `contact` 表只剩最新昵称，旧昵称只在历史引用消息的 `displayname` 里；
4. 同名小号（同一昵称两个 wxid），显示名必须加后缀区分。

`refermsg.displayname` 是唯一能批量还原历史昵称的来源，所以 `NameResolver`
一上来先扫一遍引用消息建别名表，再退回成员表、最后退回 wxid 前缀。
"""
from __future__ import annotations

import collections
import re

CTRL = re.compile(r"[\x00-\x1f\x7f]")
URL = re.compile(r"https?://\S+")
LONG_ASCII = re.compile(r"[A-Za-z0-9_\-]{12,}")
MEDIA_TAG = re.compile(r"\[[\u4e00-\u9fa5A-Za-z]{1,6}\]")


def strip_ctrl(s: str) -> str:
    return CTRL.sub("", s or "").strip()


def clean_text(text: str) -> str:
    """去掉链接、长串哈希、媒体占位符，留下可分词的自然语言。"""
    t = URL.sub(" ", text or "")
    t = LONG_ASCII.sub(" ", t)
    t = MEDIA_TAG.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


class NameResolver:
    """wxid → 可读名，带历史昵称兜底。"""

    def __init__(self, group, overrides: dict[str, str] | None = None) -> None:
        self.group = group
        self.members = group.members or {}
        self.overrides = dict(overrides or {})

        # 历史昵称：引用消息里的 displayname，按出现次数排序
        self.hist: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        for m in group.msgs:
            if m.ref_wxid and m.ref_name and "@chatroom" not in m.ref_wxid:
                n = strip_ctrl(m.ref_name)
                if n:
                    self.hist[m.ref_wxid][n] += 1

        # 别名 → wxid，先成员表后历史名
        self.name2wx: dict[str, str] = {}
        for wx, info in self.members.items():
            for k in (info.get("remark"), info.get("display"), info.get("nick")):
                k = strip_ctrl(k or "")
                if k:
                    self.name2wx[k] = wx
        for wx, ctr in self.hist.items():
            for n, _ in ctr.most_common():
                self.name2wx.setdefault(n, wx)

        self._dup_names = self._find_duplicates()

    # ---------------- 显示名 ----------------
    def display(self, wxid: str) -> str:
        if not wxid:
            return "（系统）"
        if wxid in self.overrides:
            return self.overrides[wxid]
        info = self.members.get(wxid) or {}
        raw = strip_ctrl(info.get("display") or info.get("nick") or "")
        if raw and not raw.startswith("wxid"):
            return self._dedupe(wxid, raw)
        for n, _ in (self.hist.get(wxid) or collections.Counter()).most_common():
            n = strip_ctrl(n)
            if n:
                return self._dedupe(wxid, n)
        return wxid[:12]

    def _find_duplicates(self) -> dict[str, list[str]]:
        by_name: dict[str, list[str]] = collections.defaultdict(list)
        for wx, info in self.members.items():
            n = strip_ctrl(info.get("display") or info.get("nick") or "")
            if n:
                by_name[n].append(wx)
        return {n: wxs for n, wxs in by_name.items() if len(wxs) > 1}

    def _dedupe(self, wxid: str, name: str) -> str:
        """同名小号加序号后缀，否则报表里会出现两个一模一样的人。"""
        twins = self._dup_names.get(name)
        if not twins or wxid not in twins:
            return name
        order = sorted(twins, key=lambda w: -self.group.counts.get(w, 0))
        return f"{name}({order.index(wxid) + 1})"

    # ---------------- @ 解析 ----------------
    def resolve_at(self, token: str) -> str | None:
        """把 @ 后面的裸文本映射回 wxid。

        @ 的文本是"发送那一刻的昵称"，可能带空格截断，精确命中率通常不到七成，
        所以依次退化：精确 → 前缀 → 互为前缀 → 包含（长度≥3 才允许，防误配）。
        """
        tok = strip_ctrl(token)
        if not tok:
            return None
        if tok in self.name2wx:
            return self.name2wx[tok]
        cands: list[tuple[int, str]] = []
        for k, wx in self.name2wx.items():
            if k.startswith(tok) or tok.startswith(k):
                cands.append((len(k), wx))
            elif len(tok) >= 3 and tok in k:
                cands.append((len(k) + 100, wx))
        return min(cands)[1] if cands else None


def appearance_order(group) -> list[str]:
    """按首次发言时间排序的成员列表，做报表行序时比按发言数更稳定。"""
    first: dict[str, float] = {}
    for m in group.msgs:
        if m.wxid and (m.wxid not in first or m.ts < first[m.wxid]):
            first[m.wxid] = m.ts
    return [w for w, _ in sorted(first.items(), key=lambda x: x[1])]
