# -*- coding: utf-8 -*-
"""成员语言特征。

全部是可数的行为指标，`profile()` 只出数，不下结论。
"这个人是什么角色"必须由人（或 LLM）结合原文判断——指标能说明"爱发问句、爱发表情、
短句率 78%"，但说明不了"他在群里是干什么的"。这一层边界别糊掉。

正则特征都是这个语料上验证过的写法，换群要重看：
`SELF` 抓"我对象/我领导"这类自我指涉的社会关系，不是单抓"我"。
"""
from __future__ import annotations

import collections
import re

EMOJI = re.compile(r"\[[^\]]{1,8}\]|[\U0001F300-\U0001FAFF\u2600-\u27BF]")
QUESTION = re.compile(r"[?？]")
EXCLAIM = re.compile(r"[!！]")
SELF = re.compile(r"我(对象|老公|老婆|妈|爸|家|室友|领导|同事|公司|单位|学校|朋友|工作)")
PLAN = re.compile(r"(计划|安排|打算|准备|明天|下周|下个月|周末|提前|预约|定好|流程|步骤|先.*再)")
ABSTRACT = re.compile(r"(本质|意义|逻辑|系统|结构|文明|人类|社会|时代|历史|哲学|未来|趋势|阶层|资本)")
FEEL = re.compile(r"(难过|开心|委屈|难受|好累|崩溃|焦虑|害怕|孤独|emo|爽|气死|心疼|痛苦|舒服|压力|内耗)")
AGREE = re.compile(r"(确实|同意|对的|是啊|没错|同感|是这样的|真实|有道理)")
COMFORT = re.compile(r"(摸摸|抱抱|没事|辛苦|别想太多|慢慢来|理解你|正常的|加油|会好的)")
WHY = re.compile(r"(为什么|为啥|凭什么|怎么会|咋回事)")
SWEAR = re.compile(r"(卧槽|他妈的|md|MD|操|傻逼|废物|扯淡|离谱|恶心)")
JOKE = re.compile(r"(hhhh|哈哈哈|笑死|绷不住|乐死|梗|段子|笑拥)")
LIST_STYLE = re.compile(r"^(\d[、.]|[一二三四五六七八九十][、.]|首先|其次|第一|第二)")
MENTION = re.compile(r"@[^\s\u2005]{2,14}")

BUCKETS = [(0, 7, "凌晨"), (7, 12, "上午"), (12, 18, "下午"), (18, 24, "深夜")]


def _rate(hits: int, n: int) -> float:
    return round(hits / max(1, n) * 100, 2)


def profile_one(group, wxid: str, session_starts: collections.Counter) -> dict:
    ms = group.of(wxid)
    n = len(ms)
    txt = [m for m in ms if m.text and not m.is_media]
    tn = len(txt)
    buckets = [0, 0, 0, 0]
    for m in ms:
        for i, (lo, hi, _) in enumerate(BUCKETS):
            if lo <= m.hour < hi:
                buckets[i] += 1
                break
    bsum = sum(buckets) or 1

    return {
        "name": group.name_of(wxid),
        "wxid": wxid,
        "msgs": n,
        "share": _rate(n, len(group.real())),
        "active_days": len({m.date for m in ms}),
        "avg_len": round(sum(len(m.text) for m in txt) / max(1, tn), 1),
        "short_ratio": _rate(sum(1 for m in ms if len(m.text) <= 6), n),
        "media_ratio": _rate(sum(1 for m in ms if m.is_media), n),
        "quote_ratio": _rate(sum(1 for m in ms if m.is_quote), n),
        "emoji_per100": _rate(sum(len(EMOJI.findall(m.text)) for m in ms), n),
        "q_per100": _rate(sum(len(QUESTION.findall(m.text)) for m in txt), tn),
        "excl_per100": _rate(sum(len(EXCLAIM.findall(m.text)) for m in txt), tn),
        "self_per100": _rate(sum(1 for m in txt if SELF.search(m.text)), tn),
        "plan_per100": _rate(sum(1 for m in txt if PLAN.search(m.text)), tn),
        "abstract_per100": _rate(sum(1 for m in txt if ABSTRACT.search(m.text)), tn),
        "feel_per100": _rate(sum(1 for m in txt if FEEL.search(m.text)), tn),
        "agree_per100": _rate(sum(1 for m in txt if AGREE.search(m.text)), tn),
        "comfort_per100": _rate(sum(1 for m in txt if COMFORT.search(m.text)), tn),
        "why_per100": _rate(sum(1 for m in txt if WHY.search(m.text)), tn),
        "swear_per100": _rate(sum(1 for m in txt if SWEAR.search(m.text)), tn),
        "joke_per100": _rate(sum(1 for m in txt if JOKE.search(m.text)), tn),
        "mention_out": sum(len(MENTION.findall(m.text)) for m in ms),
        "list_style": sum(1 for m in txt if LIST_STYLE.match(m.text)),
        "init": session_starts[wxid],
        "init_per1000": round(session_starts[wxid] / max(1, n) * 1000, 1),
        "hour_mean": round(sum(m.hour + int(m.time[14:16]) / 60 for m in ms) / max(1, n), 1),
        "buckets": {name: round(v / bsum * 100) for v, (_, _, name) in zip(buckets, BUCKETS)},
    }


def profile(group, top: int = 25, session_starts: collections.Counter | None = None) -> list[dict]:
    if session_starts is None:
        from .stats import sessions

        session_starts = collections.Counter(
            b[0].wxid for b in sessions(group.real()) if len(b) >= 3 and b[0].wxid
        )
    return [profile_one(group, w, session_starts) for w, _ in group.top_members(top)]


ROLE_HINTS = [
    ("话题发动", lambda r: r["init_per1000"] >= 12 and r["share"] >= 3),
    ("高频应答", lambda r: r["msgs"] >= 1000 and r["init_per1000"] < 6),
    ("长文型", lambda r: r["avg_len"] >= 25),
    ("短句型", lambda r: r["short_ratio"] >= 70),
    ("情绪表达", lambda r: r["feel_per100"] >= 2.5),
    ("安慰者", lambda r: r["comfort_per100"] >= 1),
    ("提问者", lambda r: r["q_per100"] >= 20),
    ("抽象讨论", lambda r: r["abstract_per100"] >= 1.5),
    ("玩梗", lambda r: r["joke_per100"] >= 3),
    ("列表/条理化", lambda r: r["list_style"] >= 20),
]


def hints(row: dict) -> list[str]:
    """指标层面能给出的粗标签，只作为 LLM 写作的输入提示，不进正文当结论。"""
    return [name for name, cond in ROLE_HINTS if cond(row)]
