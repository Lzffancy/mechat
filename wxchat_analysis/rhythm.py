# -*- coding: utf-8 -*-
"""群节奏：月度活跃、成员进出、接话速度、高峰日。

"群冷了"这个判断最容易做错：消息量下降有三种原因，必须分开看——
真的没人说话、某几个人退出、或者导出本身有缺口。这里的 `member_flow()`
和 `stats.data_gaps()` 就是用来分辨这三者的。
"""
from __future__ import annotations

import collections
import statistics

from .stats import monthly_detail


def member_flow(group, silent_before: str | None = None) -> dict:
    """首次 / 末次发言，判断新人加入和老成员沉默。"""
    first: dict[str, str] = {}
    last: dict[str, str] = {}
    for m in group.real():
        w = m.wxid
        if w not in first or m.time < first[w]:
            first[w] = m.time
        if w not in last or m.time > last[w]:
            last[w] = m.time
    active = group.counts

    newcomers = sorted(first.items(), key=lambda x: x[1], reverse=True)[:15]
    if silent_before:
        silent_cut = silent_before
    elif last:
        silent_cut = sorted(last.values())[len(last) // 3]
    else:
        silent_cut = "9999"
    silent = [(w, t) for w, t in sorted(last.items(), key=lambda x: x[1]) if t < silent_cut]
    return {
        "first_seen": [{"name": group.name_of(w), "wxid": w, "time": t, "msgs": active.get(w, 0)}
                       for w, t in newcomers],
        "last_seen": [{"name": group.name_of(w), "wxid": w, "time": t, "msgs": active.get(w, 0)}
                      for w, t in sorted(last.items(), key=lambda x: x[1])],
        "silent": [{"name": group.name_of(w), "wxid": w, "last": t, "msgs": active.get(w, 0)}
                   for w, t in silent],
    }


def reply_latency(group, max_gap: int = 600, min_samples: int = 50) -> list[dict]:
    """接话速度：别人说完之后，我下一条消息隔了多久。

    只统计 0~600 秒的相邻异人消息，超过 10 分钟不算"接话"。
    中位数比均值可靠，长尾（第二天才回）会把均值拉到没意义。
    """
    samples: dict[str, list[float]] = collections.defaultdict(list)
    real = group.real()
    for a, b in zip(real, real[1:]):
        if a.wxid == b.wxid or not b.wxid:
            continue
        gap = b.ts - a.ts
        if 0 <= gap <= max_gap:
            samples[b.wxid].append(gap)
    rows = []
    for wx, v in samples.items():
        if len(v) < min_samples:
            continue
        rows.append({
            "name": group.name_of(wx), "wxid": wx,
            "median": round(statistics.median(v), 1),
            "p25": round(statistics.quantiles(v, n=4)[0], 1) if len(v) >= 4 else None,
            "n": len(v),
        })
    return sorted(rows, key=lambda r: r["median"])


def hour_heat(group, top: int = 8) -> dict:
    """top N 成员的 24 小时分布，热力图直接用。"""
    real = group.real()
    keys = [w for w, _ in group.top_members(top)]
    heat = {w: [0] * 24 for w in keys}
    for m in real:
        if m.wxid in heat:
            heat[m.wxid][m.hour] += 1
    return {"names": [group.name_of(w) for w in keys],
            "data": [heat[w] for w in keys]}


def bursts(group, top: int = 10, window_min: int = 60) -> list[dict]:
    """最密集的时段：按固定窗口滑动找峰值，比"按天"更能定位事件。"""
    real = group.real()
    if not real:
        return []
    win = window_min * 60

    windows: list[tuple[int, int, int]] = []  # (条数, 左, 右)
    left = 0
    for right in range(len(real)):
        while real[right].ts - real[left].ts > win:
            left += 1
        windows.append((right - left + 1, left, right))

    picked: list[tuple[int, int, int]] = []
    for n, l, r in sorted(windows, reverse=True):
        if any(l <= pr and r >= pl for _, pl, pr in picked):
            continue
        picked.append((n, l, r))
        if len(picked) >= top:
            break

    out = []
    for n, l, r in picked:
        seg = real[l : r + 1]
        out.append({
            "start": seg[0].time, "end": seg[-1].time, "n": n,
            "senders": collections.Counter(m.sender for m in seg).most_common(5),
            "samples": [m.text[:70] for m in seg if len(m.text) > 12][:4],
        })
    return sorted(out, key=lambda x: -x["n"])


def rhythm_report(group) -> dict:
    monthly = monthly_detail(group)
    return {
        "monthly": monthly,
        "flow": member_flow(group),
        "latency": reply_latency(group),
        "heat": hour_heat(group),
        "bursts": bursts(group),
    }
