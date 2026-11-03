# -*- coding: utf-8 -*-
"""上下文窗口工具：把"某个人 / 某个词 / 某段时间"的消息取出来，供人读或喂给 LLM。

这是固定代码和 LLM 之间的接口。职责分清楚：

- 代码负责**取**：定位、切片、带上引用关系、去掉系统消息、按预算切块；
- LLM 负责**读**：归纳、命名、判断语气和动机。

为什么不让 LLM 直接看全量：48,400 条按每条 14 字算约 70 万汉字，一次塞进去既贵又会被
中段遗忘。实测有效的做法是先按人/词/时间定位到 10~30 条一段，一次给 5~15 段，
每段带全局索引，让模型引用索引而不是复述原文。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_LEN = 180


@dataclass
class Window:
    start: int
    end: int
    label: str = ""

    def __len__(self) -> int:
        return self.end - self.start


def render(group, msgs, maxlen: int = MAX_LEN, show_ref: bool = True,
           show_idx: bool = True) -> str:
    """把消息列表渲染成紧凑文本块。索引是给 LLM 引用用的，别去掉。"""
    names = group.names
    lines = []
    for m in msgs:
        if m.is_system:
            continue
        t = (m.text or "").replace("\n", " ").strip()
        if not t:
            continue
        head = f"{m.idx:6d} " if show_idx else ""
        ref = ""
        if show_ref and m.ref_wxid and "@chatroom" not in m.ref_wxid:
            ref = f" ⟵引 {names.display(m.ref_wxid)[:8]}"
        lines.append(f"{head}{m.time[5:16]} {names.display(m.wxid)[:12]:<13}{ref} {t[:maxlen]}")
    return "\n".join(lines)


def windows_around(group, indices: list[int], pad: int = 25) -> list[Window]:
    """以若干索引为中心取窗口，重叠的合并。"""
    spans = sorted((max(0, i - pad), min(len(group.msgs), i + pad + 1)) for i in indices)
    merged: list[Window] = []
    for s, e in spans:
        if merged and s <= merged[-1].end:
            merged[-1].end = max(merged[-1].end, e)
        else:
            merged.append(Window(s, e))
    return merged


def search(group, pattern: str, pad: int = 12, limit: int = 40,
           names_only: bool = False) -> list[Window]:
    """按正则找关键片段，返回带上下文的窗口。"""
    rx = re.compile(pattern)
    hits = [m.idx for m in group.real()
            if (rx.search(m.text or "") or (names_only and rx.search(group.name_of(m.wxid))))]
    if not hits:
        return []
    ws = windows_around(group, hits[:limit], pad=pad)
    for w in ws:
        w.label = pattern
    return ws


def by_member(group, who: str, pad: int = 0) -> list[Window]:
    """取某人的全部发言窗口。pad>0 时带上下文。"""
    wx = _resolve(group, who)
    if not wx:
        return []
    idx = [m.idx for m in group.real() if m.wxid == wx]
    if pad <= 0:
        return [Window(i, i + 1, group.name_of(wx)) for i in idx]
    return windows_around(group, idx, pad=pad)


def _resolve(group, who: str) -> str | None:
    names = group.names
    if who in group.counts:
        return who
    wx = names.resolve_at(who)
    if wx:
        return wx
    for m in group.msgs:
        if m.sender == who:
            return m.wxid
    return None


def chunk(group, windows: list[Window], max_msgs: int = 120,
          max_chars: int = 6000) -> list[str]:
    """把窗口按预算拼成若干文本块，给 LLM 分次调用用。"""
    out, buf, chars = [], [], 0
    for w in windows:
        block = render(group, group.msgs[w.start : w.end])
        if not block:
            continue
        n = block.count("\n") + 1
        if buf and (len(buf) + n > max_msgs or chars + len(block) > max_chars):
            out.append("\n\n".join(buf))
            buf, chars = [], 0
        buf.append(f"--- [{w.start}..{w.end}] {w.label} ---\n{block}")
        chars += len(block)
    if buf:
        out.append("\n\n".join(buf))
    return out


def sample_evenly(group, chunks: int = 20, size: int = 60) -> list[Window]:
    """均匀抽样，摸底整体气氛用。抽完人工读一遍再决定往下挖哪里。"""
    real = group.real()
    n = len(real)
    step = max(1, n // max(1, chunks))
    ws = []
    for k in range(chunks):
        i = k * step
        if i >= n:
            break
        ws.append(Window(real[i].idx, real[min(i + size, n) - 1].idx + 1, f"sample{k}"))
    return ws
