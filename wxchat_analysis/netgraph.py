# -*- coding: utf-8 -*-
"""关系网络。

**这条线的核心结论只有一句：别用"时间窗共现"当关系边。**

实测：48,400 条消息按 90 秒邻接能抽出 19,684 条"接力"边，图直接稠密化，
Louvain 模块度掉到 0.06 以下，"社群发现"退化成随机切块。真正可用的边只有两种：

- `app:quote` 消息里的 `refermsg.chatusr` —— 明确的"我在回你"，权重 1.0；
- @ 提及 —— 明确的"我在叫你"，权重 1.5（比引用强，因为带指向性）。

时序接力只保留 0.15 的弱权重、默认关掉，用来解释"谁紧跟着谁说话"这种语气现象。

指标含义（写报告时别混）：

- `pagerank` 被关注度（被引用越多越高），`between` 桥接度（跨圈层的中转）；
- `reply_ratio` = 被引 / (被引 + 引他人)，>0.5 是"被追问型"，<0.5 是"追问型"；
- `kcore` 核心层，用来区分核心圈和边缘人；
- `lift` 超预期关注：`n / (out_a * in_b / total)`，配合 n≥8 一起看，
  不然小样本会把冷门组合顶到第一。
"""
from __future__ import annotations

import collections
import itertools
from dataclasses import dataclass, field

import networkx as nx
import numpy as np

WEIGHTS = {"quote": 1.0, "at": 1.5, "relay": 0.15}
RELAY_GAP = 60  # 秒


@dataclass
class RelationNetwork:
    graph: nx.DiGraph
    undirected: nx.Graph
    quote: collections.Counter
    at: collections.Counter
    relay: collections.Counter
    rows: list[dict]
    communities: list[list[str]]
    modularity: float
    lift: list[dict] = field(default_factory=list)

    def community_names(self, name_of, limit: int = 20) -> list[dict]:
        out = []
        for i, c in enumerate(self.communities):
            members = sorted(c, key=lambda w: -self.graph.nodes[w].get("msgs", 0))
            out.append({
                "id": i,
                "size": len(c),
                "members": [name_of(w) for w in members[:limit]],
            })
        return out

    def to_json(self, name_of) -> dict:
        return {
            "nodes": [
                {**{k: v for k, v in r.items() if k != "wxid"}, "id": name_of(r["wxid"])}
                for r in self.rows
            ],
            "links": [
                {"source": name_of(u), "target": name_of(v),
                 "weight": round(d["w"], 2), "quote": d.get("quote", 0), "at": d.get("at", 0)}
                for u, v, d in self.graph.edges(data=True) if d["w"] >= 2
            ],
            "modularity": round(self.modularity, 4),
            "communities": [[name_of(w) for w in c] for c in self.communities],
        }


def build(group, *, use_relay: bool = False, resolution: float = 1.2,
          min_msgs: int = 1) -> RelationNetwork:
    names = group.names
    real = group.real()

    quote: collections.Counter = collections.Counter()
    for m in real:
        r = m.ref_wxid
        if not r or "@chatroom" in r or r == m.wxid or not m.wxid:
            continue
        quote[(m.wxid, r)] += 1

    at: collections.Counter = collections.Counter()
    unresolved: collections.Counter = collections.Counter()
    for m in real:
        for tok in m.ats:
            wx = names.resolve_at(tok)
            if wx and wx != m.wxid:
                at[(m.wxid, wx)] += 1
            elif not wx:
                unresolved[tok] += 1

    relay: collections.Counter = collections.Counter()
    if use_relay:
        for a, b in zip(real, real[1:]):
            if a.wxid and b.wxid and a.wxid != b.wxid and 0 <= b.ts - a.ts <= RELAY_GAP:
                relay[(b.wxid, a.wxid)] += 1

    active = [w for w, c in group.counts.items() if c >= min_msgs]
    g = nx.DiGraph()
    g.add_nodes_from(active)
    for (a, b), n in quote.items():
        if a in g and b in g:
            d = g.get_edge_data(a, b, {})
            g.add_edge(a, b, w=d.get("w", 0) + n * WEIGHTS["quote"],
                       quote=d.get("quote", 0) + n, at=d.get("at", 0))
    for (a, b), n in at.items():
        if a in g and b in g:
            d = g.get_edge_data(a, b, {})
            g.add_edge(a, b, w=d.get("w", 0) + n * WEIGHTS["at"],
                       quote=d.get("quote", 0), at=d.get("at", 0) + n)
    for (a, b), n in relay.items():
        if a in g and b in g:
            d = g.get_edge_data(a, b, {})
            g.add_edge(a, b, w=d.get("w", 0) + n * WEIGHTS["relay"],
                       quote=d.get("quote", 0), at=d.get("at", 0),
                       relay=d.get("relay", 0) + n)

    U = nx.Graph()
    for u, v, d in g.edges(data=True):
        U.add_edge(u, v, weight=U.get_edge_data(u, v, {}).get("weight", 0) + d["w"])

    pr = nx.pagerank(U, weight="weight", alpha=0.85) if U.number_of_edges() else {}
    btw = nx.betweenness_centrality(U, normalized=True) if U.number_of_edges() else {}
    core = nx.core_number(U) if U.number_of_edges() else {n: 0 for n in U}

    communities: list[list[str]] = []
    modularity = 0.0
    if U.number_of_edges():
        try:
            communities = nx.community.louvain_communities(U, weight="weight",
                                                           resolution=resolution, seed=42)
        except Exception:  # 老版本 networkx 没有 louvain
            communities = list(nx.community.greedy_modularity_communities(U, weight="weight"))
        communities = sorted([list(c) for c in communities], key=len, reverse=True)
        modularity = float(nx.community.modularity(U, communities, weight="weight"))

    com_id = {w: i for i, c in enumerate(communities) for w in c}

    q_out, q_in = collections.Counter(), collections.Counter()
    at_out, at_in = collections.Counter(), collections.Counter()
    for (a, b), n in quote.items():
        q_out[a] += n
        q_in[b] += n
    for (a, b), n in at.items():
        at_out[a] += n
        at_in[b] += n

    rows = []
    for wx in active:
        n = group.counts[wx]
        peers = set(v for _, v in g.out_edges(wx)) | set(u for u, _ in g.in_edges(wx))
        rows.append({
            "wxid": wx,
            "name": names.display(wx),
            "msgs": n,
            "q_out": q_out[wx], "q_in": q_in[wx],
            "at_out": at_out[wx], "at_in": at_in[wx],
            "out_w": round(sum(d["w"] for _, _, d in g.out_edges(wx, data=True)), 1),
            "in_w": round(sum(d["w"] for _, _, d in g.in_edges(wx, data=True)), 1),
            "degree": g.degree(wx),
            "peers": len(peers),
            "pagerank": round(pr.get(wx, 0) * 100, 3),
            "between": round(btw.get(wx, 0) * 100, 3),
            "kcore": core.get(wx, 0),
            "reply_ratio": round(q_in[wx] / max(1, q_in[wx] + q_out[wx]), 3),
            "community": com_id.get(wx, -1),
        })
    rows.sort(key=lambda r: -r["msgs"])
    for r in rows:
        g.nodes[r["wxid"]]["msgs"] = r["msgs"]

    return RelationNetwork(
        graph=g, undirected=U, quote=quote, at=at, relay=relay, rows=rows,
        communities=communities, modularity=modularity,
        lift=expected_lift(quote),
    )


def expected_lift(counter: collections.Counter, min_n: int = 8, top: int = 40) -> list[dict]:
    """超预期关注度：n / 期望。期望按行/列边际独立计算。"""
    total = sum(counter.values()) or 1
    out_tot, in_tot = collections.Counter(), collections.Counter()
    for (a, b), n in counter.items():
        out_tot[a] += n
        in_tot[b] += n
    pairs = []
    for (a, b), n in counter.items():
        if n < min_n:
            continue
        exp = out_tot[a] * in_tot[b] / total
        if exp <= 0:
            continue
        lift = n / exp
        pairs.append({"a": a, "b": b, "n": n, "lift": round(lift, 2),
                      "score": lift * float(np.log1p(n))})
    pairs.sort(key=lambda x: -x["score"])
    return pairs[:top]


def pair_matrix(net: RelationNetwork, top: int = 12, name_of=None) -> dict:
    """高频互动矩阵，给热力图用。对称化：A↔B 的引用合计。"""
    name_of = name_of or (lambda w: w)
    keys = [r["wxid"] for r in net.rows[:top]]
    pair: collections.Counter = collections.Counter()
    for (a, b), n in net.quote.items():
        if a in keys and b in keys:
            pair[tuple(sorted((a, b)))] += n
    data = []
    for i, a in enumerate(keys):
        for j, b in enumerate(keys):
            if i == j:
                continue
            v = pair.get(tuple(sorted((a, b))), 0)
            if v:
                data.append([i, j, v])
    return {"names": [name_of(w) for w in keys], "data": data}


def strong_pairs(net: RelationNetwork, top: int = 30, name_of=None) -> list[dict]:
    name_of = name_of or (lambda w: w)
    pair: collections.Counter = collections.Counter()
    for (a, b), n in net.quote.items():
        pair[tuple(sorted((a, b)))] += n
    out = []
    for (a, b), n in pair.most_common(top):
        ab, ba = net.quote.get((a, b), 0), net.quote.get((b, a), 0)
        out.append({"a": name_of(a), "b": name_of(b), "total": n, "ab": ab, "ba": ba,
                    "balance": round(min(ab, ba) / max(1, max(ab, ba)), 2)})
    return out
