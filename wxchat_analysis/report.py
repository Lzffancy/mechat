# -*- coding: utf-8 -*-
"""汇总成一份 `report_data.json` 和几张明细表。

报告正文（HTML / Markdown）只吃这个 JSON，不直接碰 pickle；
这样换版式不用重算，重算不用改版式。

三张 CSV 是给人核对数字用的，不是产物：
`成员关系指标` / `主题月度演化` / `强互动对`。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from . import netgraph, profile as profile_mod, rhythm as rhythm_mod, stats as stats_mod
from .topics import TopicLexicon


def build_report(group, *, vocab=None, topic_result=None, net=None,
                 lexicon_path=None) -> dict:
    base = stats_mod.basic(group)
    monthly = stats_mod.monthly_detail(group)
    rhy = rhythm_mod.rhythm_report(group)
    if net is None:
        net = netgraph.build(group)
    if topic_result is None:
        topic_result = TopicLexicon.default().annotate(group)
    prof = profile_mod.profile(group)

    months = [m["month"] for m in monthly]
    keep = {r["wxid"] for r in net.rows if r["msgs"] >= 30}
    name_of = lambda w: group.name_of(w)  # noqa: E731

    nodes = [
        {
            "id": r["name"], "wxid": r["wxid"], "msgs": r["msgs"],
            "pagerank": r["pagerank"], "between": r["between"],
            "q_in": r["q_in"], "q_out": r["q_out"],
            "at_in": r["at_in"], "at_out": r["at_out"],
            "community": r["community"], "kcore": r["kcore"],
            "reply_ratio": r["reply_ratio"],
        }
        for r in net.rows if r["wxid"] in keep
    ]
    links = [
        {"source": name_of(u), "target": name_of(v), "value": d.get("quote", 0),
         "weight": round(d["w"], 2)}
        for u, v, d in net.graph.edges(data=True)
        if u in keep and v in keep and d.get("quote", 0) >= 3
    ]
    at_links = [
        {"source": name_of(u), "target": name_of(v), "value": d.get("at", 0)}
        for u, v, d in net.graph.edges(data=True)
        if u in keep and v in keep and d.get("at", 0) > 0
    ]

    report = {
        "meta": {
            "group": group.name,
            "tmin": base["tmin"], "tmax": base["tmax"],
            "span_days": base["span_days"], "active_days": base["active_days"],
            "total": base["total"], "real": base["real"], "system": base["system"],
            "members_total": base["members_total"], "members_active": base["members_active"],
            "sessions": base["sessions"], "avg_len": base["avg_len"],
            "gini": base["gini"], "top5_share": base["top5_share"],
            "top10_share": base["top10_share"],
            "media_ratio": base["media_ratio"], "quote_ratio": base["quote_ratio"],
            "modularity": round(net.modularity, 4),
            "topic_coverage": topic_result.coverage,
            "data_gaps": stats_mod.data_gaps(monthly),
        },
        "months": months,
        "monthly": monthly,
        "hours": [base["hours"][f"{h:02d}"] for h in range(24)],
        "weekday": list(base["weekday"].values()),
        "types": base["types"],
        "topic_share": topic_result.shares(exclusive=False),
        "topic_primary": topic_result.shares(exclusive=True),
        "topic_evolution": topic_result.evolution(),
        "topic_kol": {k: v for k, v in topic_result.kol(name_of=name_of).items()},
        "nodes": nodes, "links": links, "at_links": at_links,
        "communities": net.community_names(name_of),
        "rows": net.rows,
        "lift": [{**p, "from": name_of(p["a"]), "to": name_of(p["b"])} for p in net.lift],
        "kcore": {name_of(w): k for w, k in
                  ((r["wxid"], r["kcore"]) for r in net.rows)},
        "strong_pairs": netgraph.strong_pairs(net, name_of=name_of),
        "rhythm": rhy,
        "profiles": prof,
        "words": vocab.top(120) if vocab else [],
        "scatter": [
            {"name": r["name"], "x": r["msgs"], "y": r["q_in"],
             "pr": r["pagerank"], "comm": r["community"], "ratio": r["reply_ratio"]}
            for r in net.rows if r["msgs"] >= 30
        ],
    }
    return report


def write(report: dict, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    p = out / "report_data.json"
    p.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    paths["report_data"] = p

    p = out / "members.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["排名", "成员", "发言数", "发言占比%", "被引", "引他人", "被@", "@他人",
                    "PageRank", "介数", "被引率", "k-core", "社群"])
        tot = sum(r["msgs"] for r in report["rows"]) or 1
        for i, r in enumerate(report["rows"], 1):
            w.writerow([i, r["name"], r["msgs"], round(r["msgs"] / tot * 100, 2),
                        r["q_in"], r["q_out"], r["at_in"], r["at_out"],
                        r["pagerank"], r["between"], r["reply_ratio"], r["kcore"],
                        f"社群{r['community'] + 1}" if r["community"] >= 0 else "外围"])
    paths["members_csv"] = p

    p = out / "topic_evolution.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["主题"] + report["months"])
        for s in report["topic_evolution"]:
            w.writerow([s["name"]] + s["data"])
        w.writerow(["当月消息量"] + [m["n"] for m in report["monthly"]])
        w.writerow(["当月活跃人数"] + [m["active"] for m in report["monthly"]])
    paths["topic_csv"] = p

    p = out / "strong_pairs.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["成员A", "成员B", "互相引用合计", "A→B", "B→A", "平衡度"])
        for r in report["strong_pairs"]:
            w.writerow([r["a"], r["b"], r["total"], r["ab"], r["ba"], r["balance"]])
    paths["pairs_csv"] = p

    p = out / "profiles.json"
    p.write_text(json.dumps(report["profiles"], ensure_ascii=False, indent=1), encoding="utf-8")
    paths["profiles"] = p

    return paths
