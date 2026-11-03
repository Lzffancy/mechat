# -*- coding: utf-8 -*-
"""命令行入口。

    python -m wxchat_analysis stats  --input 群.jsonl --members 群_members.csv
    python -m wxchat_analysis report --input 群.jsonl --members 群_members.csv -o out/
    python -m wxchat_analysis ctx    --input 群.jsonl --who 某人 --pad 8
    python -m wxchat_analysis ctx    --input 群.jsonl --search "彩礼" --pad 15
    python -m wxchat_analysis prose  --html 报告.html

`ctx` 的输出是给 LLM 用的，直接整块贴进 `prompts/02_*.md` 的输入位置。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import cluster, context, netgraph, prose, report, schema, stats, words
from .profile import hints, profile
from .topics import TopicLexicon


def _load(args):
    return schema.load(args.input, name=args.name or "", members=args.members)


def cmd_stats(args) -> None:
    g = _load(args)
    base = stats.basic(g)
    monthly = stats.monthly_detail(g)
    print(f"群 {base['group']}  {base['tmin']} ~ {base['tmax']}")
    print(f"消息 {base['total']}  真人 {base['real']}  系统 {base['system']}  "
          f"活跃日 {base['active_days']}  {base['sessions']} 个会话块（≥30min 断档）")
    print(f"成员 {base['members_active']}/{base['members_total']}  "
          f"基尼 {base['gini']}  top5 {base['top5_share']}%  top10 {base['top10_share']}%")
    print(f"平均 {base['avg_len']} 字/条  媒体 {base['media_ratio']}%  引用 {base['quote_ratio']}%")
    gaps = stats.data_gaps(monthly)
    if gaps:
        print(f"疑似导出缺口月份: {', '.join(gaps)}（占比类结论要剔除）")
    print("\n月份  消息  活跃  人均")
    for m in monthly:
        print(f"{m['month']}  {m['n']:6d}  {m['active']:4d}  {m['per_capita']:7.1f}")
    print("\n成员 top15")
    for wx, c in g.top_members(15):
        print(f"  {c:6d}  {g.name_of(wx)}")


def cmd_words(args) -> None:
    g = _load(args)
    v = words.Vocab.build(g)
    print(f"有效文本消息 {len(v.msgs)}  唯一词 {len(v.freq)}")
    for row in v.top(args.top):
        users = " ".join(f"{u['name']}:{u['n']}" for u in row["top_users"])
        print(f"{row['count']:6d}  {row['word']}  |  {users}")
    if args.distinct:
        print("\n标注性用词")
        for wx, _ in g.top_members(8):
            sig = v.distinctive(wx)
            if sig:
                print(f"  {g.name_of(wx)}: " + " ".join(f"{w}({n})" for w, n, _ in sig[:12]))


def cmd_topics(args) -> None:
    g = _load(args)
    lex = TopicLexicon.from_json(args.lexicon) if args.lexicon else TopicLexicon.default()
    res = lex.annotate(g)
    print(f"覆盖率 {res.coverage}%（未命中的进'无法归类'，不进分母）")
    print("\n主题（提及量口径，可多命中）")
    for row in res.shares():
        print(f"  {row['n']:6d} {row['share']:5.1f}%  {row['name']}")
    print("\n主题（互斥主标签口径）")
    for row in res.shares(exclusive=True):
        print(f"  {row['n']:6d} {row['share']:5.1f}%  {row['name']}")
    if args.examples:
        print("\n例证")
        for tp, ex in res.exemplars.items():
            print(f"\n--- {tp}")
            for who, t in ex[:5]:
                print(f"  {who} | {t}")


def cmd_cluster(args) -> None:
    g = _load(args)
    v = words.Vocab.build(g)
    try:
        print("k 扫描（只用来排除明显不合适的 k）")
        for row in cluster.sweep(v):
            print(f"  k={row['k']:3d} inertia={row['inertia']:>12} silhouette={row['silhouette']}")
        res = cluster.run(v, g, k=args.k)
    except ValueError as e:
        print(f"聚类跳过：{e}", file=sys.stderr)
        return
    print(f"\nK={args.k}  窗口 {res.n_docs} 个")
    for c in res.clusters:
        print(f"\n[簇{c['id']}] 窗口{c['n']} 消息{c['msg_n']} 月份{c['months']}")
        print("   " + " / ".join(c["terms"][:12]))
        for e in c["examples"][:3]:
            print(f"   · {e['time']} {e['sender']}: {e['text'][:60]}")


def cmd_graph(args) -> None:
    g = _load(args)
    net = netgraph.build(g, use_relay=args.relay)
    print(f"节点 {net.graph.number_of_nodes()} 边 {net.graph.number_of_edges()} "
          f"社群 {len(net.communities)} 模块度 {net.modularity:.4f}")
    print(f"\n{'名字':<14}{'发言':>6}{'被引':>6}{'引他':>6}{'被引率':>7}{'PR':>7}{'介数':>7}{'kcore':>6}{'社群':>5}")
    for r in net.rows[: args.top]:
        print(f"{r['name'][:13]:<14}{r['msgs']:>6}{r['q_in']:>6}{r['q_out']:>6}"
              f"{r['reply_ratio']:>7}{r['pagerank']:>7.2f}{r['between']:>7.2f}"
              f"{r['kcore']:>6}{r['community']:>5}")
    print("\n超预期关注（lift，n≥8）")
    for p in net.lift[:15]:
        print(f"  {g.name_of(p['a']):<12} → {g.name_of(p['b']):<12} n={p['n']:4d} lift={p['lift']}")


def cmd_profile(args) -> None:
    g = _load(args)
    rows = profile(g, top=args.top)
    for r in rows:
        print(f"\n{r['name']}  发言{r['msgs']} 占比{r['share']}% 活跃{r['active_days']}天 "
              f"均长{r['avg_len']}字 短句{r['short_ratio']}%")
        print(f"  发起{r['init']}（{r['init_per1000']}‰）  被引率见 graph  时段 {r['buckets']}")
        print(f"  表情{r['emoji_per100']} 问句{r['q_per100']} 情绪{r['feel_per100']} "
              f"安慰{r['comfort_per100']} 抽象{r['abstract_per100']} 玩梗{r['joke_per100']}")
        print(f"  指标粗标签: {hints(r)}")


def cmd_report(args) -> None:
    g = _load(args)
    v = words.Vocab.build(g)
    lex = TopicLexicon.from_json(args.lexicon) if args.lexicon else TopicLexicon.default()
    res = lex.annotate(g)
    rep = report.build_report(g, vocab=v, topic_result=res)
    paths = report.write(rep, args.out)
    print(f"消息 {rep['meta']['real']}  成员 {rep['meta']['members_active']}  "
          f"社群 {len(rep['communities'])}  模块度 {rep['meta']['modularity']}")
    print(f"主题覆盖 {rep['meta']['topic_coverage']}%")
    for k, p in paths.items():
        print(f"  写出 {k}: {p}")
    if args.state:
        print(f"  缓存 {g.save(args.state)}")


def cmd_ctx(args) -> None:
    g = _load(args)
    if args.range:
        a, b = args.range
        text = context.render(g, g.msgs[a:b])
    elif args.search:
        ws = context.search(g, args.search, pad=args.pad, limit=args.limit)
        if not ws:
            print(f"没有命中: {args.search}", file=sys.stderr)
            return
        blocks = context.chunk(g, ws, max_msgs=args.budget)
        text = "\n\n".join(blocks)
        print(f"命中窗口 {len(ws)} 个，切成 {len(blocks)} 块", file=sys.stderr)
    elif args.who:
        ws = context.by_member(g, args.who, pad=args.pad)
        if not ws:
            print(f"找不到成员: {args.who}", file=sys.stderr)
            return
        blocks = context.chunk(g, ws, max_msgs=args.budget)
        text = "\n\n".join(blocks)
        print(f"{len(ws)} 条发言，切成 {len(blocks)} 块", file=sys.stderr)
    elif args.sample:
        ws = context.sample_evenly(g, chunks=args.sample, size=60)
        text = "\n\n".join(context.chunk(g, ws, max_msgs=args.budget))
    else:
        print("ctx 需要 --who / --search / --range / --sample 之一", file=sys.stderr)
        return
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"写出 {args.out}（{len(text)} 字节）", file=sys.stderr)
    else:
        print(text)


def cmd_prose(args) -> None:
    if args.html:
        text = prose.extract_html(args.html)
    else:
        text = Path(args.text).read_text(encoding="utf-8")
    rep = prose.check(text)
    print(rep.render())
    sys.exit(0 if rep.clean else 1)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wxchat_analysis", description="微信群聊分析工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--input", required=True, help="jsonl / 可读txt / 中间 pkl")
        sp.add_argument("--members", help="_members.csv")
        sp.add_argument("--name", help="群名，缺省取文件名")
        return sp

    sp = common(sub.add_parser("stats", help="基础统计"))
    sp.set_defaults(func=cmd_stats)

    sp = common(sub.add_parser("words", help="词频"))
    sp.add_argument("--top", type=int, default=100)
    sp.add_argument("--distinct", action="store_true", help="附每人标志性用词")
    sp.set_defaults(func=cmd_words)

    sp = common(sub.add_parser("topics", help="词典法主题"))
    sp.add_argument("--lexicon", help="自定义词典 json")
    sp.add_argument("--examples", action="store_true")
    sp.set_defaults(func=cmd_topics)

    sp = common(sub.add_parser("cluster", help="滑窗聚类（辅助）"))
    sp.add_argument("--k", type=int, default=12)
    sp.set_defaults(func=cmd_cluster)

    sp = common(sub.add_parser("graph", help="关系网络"))
    sp.add_argument("--relay", action="store_true", help="并入时序接力弱信号（默认关）")
    sp.add_argument("--top", type=int, default=20)
    sp.set_defaults(func=cmd_graph)

    sp = common(sub.add_parser("profile", help="成员语言特征"))
    sp.add_argument("--top", type=int, default=15)
    sp.set_defaults(func=cmd_profile)

    sp = common(sub.add_parser("report", help="汇总 report_data.json + 明细表"))
    sp.add_argument("-o", "--out", default="out")
    sp.add_argument("--lexicon")
    sp.add_argument("--state", help="同时缓存中间 pickle，路径自定")
    sp.set_defaults(func=cmd_report)

    sp = common(sub.add_parser("ctx", help="导出上下文窗口（喂 LLM）"))
    sp.add_argument("--who", help="成员名或 wxid")
    sp.add_argument("--search", help="正则")
    sp.add_argument("--range", nargs=2, type=int, metavar=("START", "END"))
    sp.add_argument("--sample", type=int, help="均匀抽样段数")
    sp.add_argument("--pad", type=int, default=10, help="上下文条数")
    sp.add_argument("--limit", type=int, default=40)
    sp.add_argument("--budget", type=int, default=120, help="单块最大消息数")
    sp.add_argument("-o", "--out")
    sp.set_defaults(func=cmd_ctx)

    sp = sub.add_parser("prose", help="文案硬禁令体检")
    sp.add_argument("--html")
    sp.add_argument("--text")
    sp.set_defaults(func=cmd_prose)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
