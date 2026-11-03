# -*- coding: utf-8 -*-
"""词典法主题标注。

**为什么主口径是词典不是聚类**：群聊消息平均十几字，TF-IDF + KMeans 在这类语料上
必然产出垃圾桶簇（被"哈哈哈""名字""几点"这类高频泛词主导），跑十次八次都解释不了。
词典法牺牲召回，换来的是可解释、可复现、可以按月做演化，而且能随时加词重算。

规则三条：

1. **长词优先匹配**，避免"吃"命中"吃亏"、"聊"命中"无聊"；
2. **英文关键词加词边界**，否则 `ai` 会命中 `wait`、`mail`，这是实测踩过的坑；
3. **一条消息可多命中**，同时给"互斥主标签"（权重最大者）和"提及量"两个口径，
   报表里必须写清楚用的是哪个。
"""
from __future__ import annotations

import collections
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).parent / "data" / "topic_lexicon.json"

_ASCII = re.compile(r"^[\x00-\x7f]+$")


def _compile(keyword: str) -> re.Pattern:
    if _ASCII.match(keyword):
        # 英文/数字关键词要求两侧不是字母数字，防止子串误命中
        return re.compile(r"(?<![A-Za-z0-9])" + re.escape(keyword) + r"(?![A-Za-z0-9])", re.I)
    return re.compile(re.escape(keyword))


@dataclass
class TopicResult:
    topics: list[str]
    primary: list[str | None]                 # 与 group.texts() 对齐
    hits: collections.Counter                 # 提及量（可多命中）
    primary_counts: collections.Counter       # 互斥主标签
    monthly: dict[str, collections.Counter]   # 月份 → 主题提及
    monthly_total: dict[str, int]
    by_user: dict[str, collections.Counter]
    exemplars: dict[str, list[tuple[str, str]]
                     ] = field(default_factory=dict)

    @property
    def coverage(self) -> float:
        hit = sum(1 for p in self.primary if p)
        return round(hit / max(1, len(self.primary)) * 100, 1)

    def shares(self, exclusive: bool = False) -> list[dict]:
        src = self.primary_counts if exclusive else self.hits
        total = sum(src.values()) or 1
        return [
            {"name": k, "n": v, "share": round(v / total * 100, 1)}
            for k, v in src.most_common()
        ]

    def evolution(self) -> list[dict]:
        """每月各主题占当月消息数的百分比。"""
        months = sorted(self.monthly_total)
        out = []
        for tp in self.topics:
            out.append({
                "name": tp,
                "data": [
                    round(self.monthly.get(mo, collections.Counter()).get(tp, 0)
                          / max(1, self.monthly_total[mo]) * 100, 2)
                    for mo in months
                ],
            })
        return out

    def kol(self, top: int = 3, name_of=None) -> dict[str, list[dict]]:
        name_of = name_of or (lambda w: w)
        return {
            tp: [{"name": name_of(wx), "n": n} for wx, n in ctr.most_common(top)]
            for tp, ctr in self.by_user.items()
        }


class TopicLexicon:
    def __init__(self, topics: dict[str, dict]) -> None:
        self.topics = topics
        # 长词优先，短词后置；每条同时记录权重
        pairs: list[tuple[str, str, float]] = []
        for name, cfg in topics.items():
            for kw in cfg.get("keywords", []):
                pairs.append((kw, name, float(cfg.get("weight", 1.0))))
        pairs.sort(key=lambda x: -len(x[0]))
        self.rules = [(kw, tp, w, _compile(kw)) for kw, tp, w in pairs]

    # ---- 构建 ----
    @classmethod
    def default(cls) -> "TopicLexicon":
        return cls.from_json(DATA)

    @classmethod
    def from_json(cls, path: str | Path) -> "TopicLexicon":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(raw)

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.topics, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add(self, name: str, keywords: list[str], weight: float = 1.0) -> None:
        self.topics.setdefault(name, {"keywords": [], "weight": weight})
        exist = set(self.topics[name]["keywords"])
        self.topics[name]["keywords"] += [k for k in keywords if k not in exist]
        self.__init__(self.topics)

    # ---- 标注 ----
    def label(self, text: str) -> collections.Counter:
        c: collections.Counter = collections.Counter()
        for _kw, tp, w, rx in self.rules:
            if rx.search(text):
                c[tp] += w
        return c

    def annotate(self, group, exemplar_per_topic: int = 8) -> TopicResult:
        topics = list(self.topics)
        primary: list[str | None] = []
        hits: collections.Counter = collections.Counter()
        primary_counts: collections.Counter = collections.Counter()
        monthly: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        monthly_total: dict[str, int] = collections.Counter()
        by_user: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        exemplars: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)

        for m in group.texts():
            c = self.label(m.text)
            monthly_total[m.month] += 1
            if not c:
                primary.append(None)
                continue
            top = c.most_common(1)[0][0]
            primary.append(top)
            primary_counts[top] += 1
            for tp in c:
                hits[tp] += 1
                monthly[m.month][tp] += 1
                by_user[tp][m.wxid] += 1
                if len(m.text) > 18 and len(exemplars[tp]) < exemplar_per_topic * 5:
                    exemplars[tp].append((m.sender, m.text[:110]))

        return TopicResult(
            topics=topics,
            primary=primary,
            hits=hits,
            primary_counts=primary_counts,
            monthly=dict(monthly),
            monthly_total=dict(monthly_total),
            by_user=dict(by_user),
            exemplars={k: v[:exemplar_per_topic] for k, v in exemplars.items()},
        )


def member_topic_preference(result: TopicResult, group, top_members: int = 12) -> dict:
    """每人主题偏好 vs 群基线，用于画像。"""
    base: collections.Counter = collections.Counter()
    for tp in result.hits:
        base[tp] = result.hits[tp]
    base_total = sum(base.values()) or 1
    baseline = {k: round(v / base_total * 100, 1) for k, v in base.most_common()}

    out = {}
    for wx, _ in group.top_members(top_members):
        c = result.by_user.get(wx, collections.Counter())
        tt = sum(c.values()) or 1
        out[group.name_of(wx)] = {
            "covered": tt,
            "top": {k: round(v / tt * 100, 1) for k, v in c.most_common(6)},
            "lift": {k: round((v / tt) / max(1e-9, base[k] / base_total), 2)
                     for k, v in c.most_common(6)},
        }
    return {"baseline": baseline, "members": out}
