# -*- coding: utf-8 -*-
"""基础统计：量、时间分布、活跃度、集中度。

口径约定（写报告前必须固定，否则两版数字对不上）：

- 分母：占比一律用真人消息数 `len(group.real())`，系统事件不进分母也不进成员榜；
- 会话块：相邻消息间隔 > 30 分钟算断档，用于"话题段"而不是"天"；
- 集中度：发言条数的基尼系数，top5/top10 份额另算；
- 导出缺口：某些月份数据不全，占比类结论要标注或剔除。
"""
from __future__ import annotations

import collections
import re
from datetime import datetime

WEEKDAY = "一二三四五六日"
SESSION_GAP = 1800  # 秒


def gini(values: list[float]) -> float:
    """基尼系数。0 = 完全均匀，1 = 一人独占。"""
    xs = sorted(x for x in values if x is not None)
    n = len(xs)
    if n == 0:
        return 0.0
    s = sum(xs)
    if s == 0:
        return 0.0
    cum = 0.0
    for i, x in enumerate(xs, 1):
        cum += i * x
    return (2 * cum) / (n * s) - (n + 1) / n


def sessions(msgs: list, gap: int = SESSION_GAP) -> list[list]:
    """按时间断档切会话块。"""
    if not msgs:
        return []
    blocks, cur = [], [msgs[0]]
    for a, b in zip(msgs, msgs[1:]):
        if b.ts - a.ts > gap:
            blocks.append(cur)
            cur = [b]
        else:
            cur.append(b)
    blocks.append(cur)
    return blocks


def basic(group) -> dict:
    real = group.real()
    if not real:
        raise ValueError("没有真人消息，检查导出是否为空")
    n = len(real)
    by_day = collections.Counter(m.date for m in real)
    by_month = collections.Counter(m.month for m in real)
    by_hour = collections.Counter(m.hour for m in real)
    by_dow = collections.Counter(m.weekday for m in real)
    by_type = collections.Counter(m.type for m in group.msgs)
    per_member = {w: c for w, c in group.counts.items() if c}

    span_days = len(by_day)
    blocks = sessions(real)
    counts_sorted = sorted(per_member.values(), reverse=True)
    total = sum(counts_sorted) or 1

    text_ws = [m for m in real if m.text and not m.is_media]
    return {
        "group": group.name,
        "total": len(group.msgs),
        "real": n,
        "system": len(group.msgs) - n,
        "tmin": real[0].time,
        "tmax": real[-1].time,
        "span_days": (datetime.fromtimestamp(real[-1].ts).date()
                      - datetime.fromtimestamp(real[0].ts).date()).days + 1,
        "active_days": span_days,
        "months": dict(sorted(by_month.items())),
        "hours": {f"{h:02d}": by_hour.get(h, 0) for h in range(24)},
        "weekday": {WEEKDAY[i]: by_dow.get(i, 0) for i in range(7)},
        "types": dict(by_type.most_common()),
        "members_total": len(group.members) or len(per_member),
        "members_active": len(per_member),
        "sessions": len(blocks),
        "sessions_ge10": sum(1 for b in blocks if len(b) >= 10),
        "avg_msgs_per_active_day": round(n / span_days, 1),
        "avg_len": round(sum(len(m.text) for m in text_ws) / max(1, len(text_ws)), 1),
        "media_ratio": round(sum(1 for m in real if m.is_media) / n * 100, 1),
        "quote_ratio": round(sum(1 for m in real if m.is_quote) / n * 100, 1),
        "gini": round(gini(counts_sorted), 3),
        "top5_share": round(sum(counts_sorted[:5]) / total * 100, 1),
        "top10_share": round(sum(counts_sorted[:10]) / total * 100, 1),
        "per_member": per_member,
    }


def peak_windows(msgs: list, top: int = 10) -> list[dict]:
    """峰值日 + 当日前三句样本，人工核对"那天到底发生了什么"用。"""
    by_day = collections.Counter(m.date for m in msgs)
    out = []
    for day, c in by_day.most_common(top):
        rows = [m for m in msgs if m.date == day]
        out.append({
            "date": day,
            "n": c,
            "senders": collections.Counter(m.sender for m in rows).most_common(5),
            "samples": [m.text[:60] for m in rows if len(m.text) > 15][:3],
        })
    return out


def monthly_detail(group) -> list[dict]:
    """月度消息量 / 活跃人数 / 人均，成员进出分析的基础。"""
    real = group.real()
    n = collections.Counter(m.month for m in real)
    act: dict[str, set] = collections.defaultdict(set)
    for m in real:
        act[m.month].add(m.wxid)
    return [
        {
            "month": mo,
            "n": n[mo],
            "active": len(act[mo]),
            "per_capita": round(n[mo] / max(1, len(act[mo])), 1),
        }
        for mo in sorted(n)
    ]


def data_gaps(monthly: list[dict], threshold: float = 0.25) -> list[str]:
    """找出消息量显著低于中位数的月份，报告里要标注成"导出缺口"而不是"群冷了"。"""
    if not monthly:
        return []
    vals = [m["n"] for m in monthly]
    vals_sorted = sorted(vals)
    med = vals_sorted[len(vals_sorted) // 2]
    return [m["month"] for m in monthly if m["n"] < med * threshold]
