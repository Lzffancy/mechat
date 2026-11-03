# -*- coding: utf-8 -*-
"""把 report_data.json 渲染成一份单文件、离线可读的杂志风 HTML。

分工：**排版归代码，文字归模型。** 模型只负责写正文段落（`--prose 稿件.md`），
不碰 CSS；数字和图全部由这里从 JSON 现算。所以换模型、换措辞不用重排版，
换版式也不用重算数。

样式规则写在 `templates/magazine.css` 顶部注释里，改之前先读那六条。

用法：

    python -m wxchat_analysis html --data out/report_data.json -o 报告.html
    python -m wxchat_analysis html --data out/report_data.json --prose 正文.md -o 报告.html
"""
from __future__ import annotations

import html
import json
import re
import statistics
from pathlib import Path

CSS = (Path(__file__).parent / "templates" / "magazine.css").read_text(encoding="utf-8")

INK = "#1c1a17"
INK2 = "#4a453d"
INK3 = "#8a8378"
HAIR = "#d8d2c6"
ACCENT = "#a63a28"
MUTED = "#cdc7ba"
SANS = "-apple-system,'PingFang SC','Microsoft YaHei',sans-serif"
SERIF = "'Songti SC','Noto Serif SC',SimSun,serif"

W = 560  # SVG 视图宽度


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def e(s) -> str:
    return html.escape(str(s), quote=True)


def num(v) -> str:
    try:
        return f"{int(round(float(v))):,}"
    except (TypeError, ValueError):
        return str(v)


def pct(v, digits: int = 1) -> str:
    try:
        return f"{float(v):.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def _ticks(values, labels, step: int):
    return [(labels[i], values[i]) for i in range(0, len(labels), step)]


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


# --------------------------------------------------------------------------
# SVG 图表
# --------------------------------------------------------------------------
def bars(labels: list, values: list, *, fmt=num, unit: str = "") -> str:
    """竖柱图，HTML + CSS 实现。

    用 SVG 的话，图表在 393px 的屏上会被缩到 0.64 倍，9px 的轴标签实际只剩 6px，
    只能靠放大字号硬扛，桌面上又会过大。改成 DOM 之后字号跟着断点走，两端都对。
    """
    n = len(values)
    if not n:
        return ""
    top = max(values) or 1
    hi = values.index(top)
    cols = []
    for i, (lb, v) in enumerate(zip(labels, values)):
        h = max(2, round(v / top * 100, 1))  # .bw 撑满剩余高度，峰值标签不会顶到上文
        cls = "col hi" if i == hi else "col"
        if i % 2:
            cls += " alt"
        val = f'<span class="val">{e(fmt(v))}{e(unit)}</span>' if i == hi else ""
        cols.append(
            f'<div class="{cls}" title="{e(lb)} {e(fmt(v))}">{val}'
            f'<div class="bw"><div class="bar" style="height:{h}%"></div></div>'
            f'<span class="lb">{e(lb)}</span></div>'
        )
    return f'<div class="vchart">{"".join(cols)}</div>'


def hbars(rows: list[dict], *, unit: str = "%") -> str:
    """横条图，主题份额用。左边名字，右边数字，中间是条。"""
    if not rows:
        return ""
    top = max(r["v"] for r in rows) or 1
    out = []
    for i, r in enumerate(rows):
        w = max(1.5, round(r["v"] / top * 100, 1))
        cls = "hb hi" if i < 3 else "hb"
        out.append(
            f'<div class="{cls}"><span class="k" title="{e(r["name"])}">{e(r["name"])}</span>'
            f'<span class="t"><i style="width:{w}%"></i></span>'
            f'<span class="v">{r["v"]}{e(unit)}</span></div>'
        )
    return f'<div class="hbars">{"".join(out)}</div>'


LINES_COLOR = [ACCENT, INK2, INK3, "#b08d57", "#5b7f8c"]


def lines(series: list[dict], labels: list, *, height: int = 190, unit: str = "%") -> str:
    """多条折线，主题月度演化用。图例放在图下方，用短横线段 + 文字。"""
    if not series or not labels:
        return ""
    pad_l, pad_r, pad_t, pad_b = 10, 10, 14, 34
    n = len(labels)
    top = max((max(s["data"]) for s in series if s["data"]), default=1) or 1
    sx = lambda i: pad_l + (W - pad_l - pad_r) * (i / max(1, n - 1))
    sy = lambda v: pad_t + (height - pad_t - pad_b) * (1 - v / top)
    parts = [f'<svg viewBox="0 0 {W} {height}" role="img">']
    parts.append(
        f'<line x1="{pad_l}" y1="{height - pad_b}" x2="{W - pad_r}" y2="{height - pad_b}" '
        f'stroke="{INK}" stroke-width="1"/>'
    )
    for i, lb in enumerate(labels):
        if n > 8 and i % 2:
            continue
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        parts.append(
            f'<text x="{sx(i):.1f}" y="{height - pad_b + 16}" font-size="14" fill="{INK3}" '
            f'font-family="{SANS}" text-anchor="{anchor}">{e(lb)}</text>'
        )
    for k, s in enumerate(series[:5]):
        col = LINES_COLOR[k % len(LINES_COLOR)]
        pts = " ".join(f"{sx(i):.1f},{sy(v):.1f}" for i, v in enumerate(s["data"]))
        parts.append(
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.6" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        lx = pad_l + (k % 3) * ((W - pad_l - pad_r) / 3)
        ly = height - 8 + (k // 3) * 0
        parts.append(
            f'<line x1="{lx:.1f}" y1="{ly - 4:.1f}" x2="{lx + 14:.1f}" y2="{ly - 4:.1f}" '
            f'stroke="{col}" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{lx + 19:.1f}" y="{ly:.1f}" font-size="13" fill="{INK2}" '
            f'font-family="{SANS}">{e(_short(s["name"], 11))}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def scatter(points: list[dict], *, height: int = 300, top_names: int = 6) -> str:
    """发言数 vs 被引用次数。右上角是枢纽人物，左下角是潜水员。"""
    pts = [p for p in points if p.get("x")]
    if not pts:
        return ""
    pad_l, pad_r, pad_t, pad_b = 34, 12, 12, 30
    xs = [p["x"] for p in pts]
    ys = [p["y"] for p in pts]
    xmax, ymax = max(xs) or 1, max(ys) or 1
    sx = lambda v: pad_l + (W - pad_l - pad_r) * (v / xmax)
    sy = lambda v: height - pad_b - (height - pad_t - pad_b) * (v / ymax)
    parts = [f'<svg viewBox="0 0 {W} {height}" role="img">']
    parts.append(
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{height - pad_b}" stroke="{INK}" stroke-width="1"/>'
        f'<line x1="{pad_l}" y1="{height - pad_b}" x2="{W - pad_r}" y2="{height - pad_b}" stroke="{INK}" stroke-width="1"/>'
    )
    for txt, x, y in ((num(xmax), W - pad_r, height - pad_b + 16), (num(ymax), 6, pad_t + 10)):
        parts.append(
            f'<text x="{x}" y="{y}" font-size="14" fill="{INK3}" font-family="{SANS}">'
            f'{e(txt)}</text>'
        )
    parts.append(
        f'<text x="{W - pad_r}" y="{height - 6}" font-size="14" fill="{INK3}" '
        f'font-family="{SANS}" text-anchor="end">发言条数 →</text>'
    )
    # 中位数参考线：散点图天然左密右疏，没有参考线看着像渲染失败
    mx = statistics.median(xs)
    my = statistics.median(ys)
    for x1, y1, x2, y2, lx, ly, lab in (
        (sx(mx), pad_t, sx(mx), height - pad_b, sx(mx) + 4, pad_t + 9, "发言中位数"),
        (pad_l, sy(my), W - pad_r, sy(my), pad_l + 3, sy(my) - 5, "被引中位数"),
    ):
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{HAIR}" stroke-width="1" stroke-dasharray="3 3"/>'
        )
        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="14" fill="{INK3}" '
            f'font-family="{SANS}">{e(lab)}</text>'
        )
    ordered = sorted(pts, key=lambda p: -(p.get("pr", 0) or 0))
    named = {id(p) for p in ordered[:top_names]}
    for p in pts:
        r = 2.6 + min(6.5, (p.get("pr") or 0) / 6)
        col = ACCENT if id(p) in named else "#a49e90"
        parts.append(
            f'<circle cx="{sx(p["x"]):.1f}" cy="{sy(p["y"]):.1f}" r="{r:.1f}" '
            f'fill="{col}" fill-opacity="{0.9 if id(p) in named else 0.55}"/>'
        )
    # 名字标签避让：靠右的点改成右对齐往左放，纵向撞车就往下推一行
    placed: list[tuple[float, float]] = []
    for p in ordered[:top_names]:
        x, y = sx(p["x"]), sy(p["y"])
        anchor = "end" if x > W - 120 else "start"
        dx = -8 if anchor == "end" else 8
        tx, ty = x + dx, min(max(y + 4, pad_t + 12), height - pad_b - 3)
        while any(abs(ty - py) < 15 and abs(tx - px) < 95 for px, py in placed):
            ty += 15
            if ty > height - pad_b - 3:
                ty = pad_t + 12
                break
        placed.append((tx, ty))
        parts.append(
            f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="16" fill="{INK}" '
            f'font-family="{SANS}" text-anchor="{anchor}">{e(p["name"])}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------
# 正文稿件（模型写的部分）
# --------------------------------------------------------------------------
def load_prose(path: str | Path) -> dict[str, list[dict]]:
    """解析 Markdown 稿件。

    `## 01` 分节，段内支持：
    - 普通段落 → `<p>`
    - `> 引用` → 引语块（下一行 `—— 来源` 不必写，用 `::src` 结尾给来源）
    - `- 项` → 列表
    """
    raw = Path(path).read_text(encoding="utf-8") if path else ""
    out: dict[str, list[dict]] = {}
    cur = "00"
    buf: list[str] = []
    items: list[str] = []

    def flush():
        if buf:
            out.setdefault(cur, []).append({"kind": "p", "text": md_inline(" ".join(buf))})
            buf.clear()
        if items:
            out.setdefault(cur, []).append({"kind": "ul", "items": [md_inline(x) for x in items]})
            items.clear()

    for line in raw.splitlines():
        s = line.rstrip()
        if re.match(r"^#{1,3}\s", s):
            flush()
            cur = re.sub(r"^#{1,3}\s*", "", s).strip()
            continue
        if not s.strip():
            flush()
            continue
        if s.lstrip().startswith(">"):
            flush()
            src = ""
            body = s.lstrip()[1:].strip()
            if "::" in body:
                body, src = body.rsplit("::", 1)
            out.setdefault(cur, []).append({"kind": "quote", "text": md_inline(body.strip()),
                                            "src": e(src.strip())})
            continue
        if s.lstrip().startswith("- "):
            items.append(s.lstrip()[2:])
            continue
        buf.append(s.strip())
    flush()
    return out


def md_inline(text: str) -> str:
    """只支持加粗和书名号转义，其余原样输出。"""
    t = html.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t


def _blocks(blocks: list[dict]) -> str:
    out = []
    for b in blocks or []:
        if b["kind"] == "p":
            out.append(f"<p>{b['text']}</p>")
        elif b["kind"] == "quote":
            src = f'<span class="src">{b["src"]}</span>' if b.get("src") else ""
            out.append(f'<div class="pull">{b["text"]}{src}</div>')
        elif b["kind"] == "ul":
            out.append("<ul>" + "".join(f"<li>{x}</li>" for x in b["items"]) + "</ul>")
    return "".join(out)


# --------------------------------------------------------------------------
# 组装
# --------------------------------------------------------------------------
def _dl(rows: list[tuple[str, str, str | None]]) -> str:
    items = []
    for k, v, sub in rows:
        tail = f"<small>{e(sub)}</small>" if sub else ""
        items.append(f'<div class="row"><span class="k">{e(k)}</span>'
                     f'<span class="v">{v}{tail}</span></div>')
    return f'<div class="dl">{"".join(items)}</div>'


def render(data: dict, *, prose: dict | None = None, title: str | None = None) -> str:
    prose = prose or {}
    m = data.get("meta", {})
    group = m.get("group") or "群聊"
    rows = data.get("rows") or []
    monthly = data.get("monthly") or []
    months = data.get("months") or [x["month"] for x in monthly]
    # 群名可能是文件名（从导出路径取的），没有汉字就直接叫「这个群」
    shown = group if re.search(r"[\u4e00-\u9fa5]", group) else "这个群"
    name = title or f"{shown} 的 {m.get('span_days', 0)} 天"

    def sec(slug: str, num_: str, h: str, body: str, note: str = "") -> str:
        blocks = _blocks(prose.get(slug) or prose.get(num_) or [])
        note_html = f'<span class="note">{md_inline(note)}</span>' if note else ""
        return (
            f'<section><div class="sec-head"><span class="num">{e(num_)}</span>'
            f'<div class="tt"><h2>{e(h)}</h2>{note_html}</div></div>{blocks}{body}</section>'
        )

    # ---- 封面 ----
    cover_blocks = _blocks(prose.get("00") or prose.get("封面") or [])
    dek = (
        f"{num(m.get('real'))} 条消息，{num(m.get('members_active'))} 个人，"
        f"从 {e(str(m.get('tmin'))[:10])} 到 {e(str(m.get('tmax'))[:10])}。"
    )
    mast = [
        (num(m.get("real")), "消息"),
        (num(m.get("members_active")), "发言成员"),
        (num(m.get("active_days")), "活跃天"),
        (pct(m.get("top5_share")), "前五人占比"),
    ]
    cover = (
        '<header class="cover">'
        '<div class="kicker">群聊观察</div>'
        f"<h1>{e(name)}</h1>"
        f'<p class="dek">{dek}</p>'
        '<div class="masthead">'
        + "".join(f'<div class="m"><div class="n">{v}</div><div class="l">{e(k)}</div></div>'
                  for v, k in mast)
        + "</div>"
        f"{cover_blocks}</header>"
    )

    # ---- 01 基本盘 ----
    body = ""
    if monthly:
        body += (
            '<figure>'
            + bars([x["month"][2:] for x in monthly], [x["n"] for x in monthly])
            + "<figcaption>每月消息量。峰值月份染红。</figcaption></figure>"
        )
    if data.get("hours"):
        hrs = data["hours"]
        body += (
            "<figure>"
            + bars([f"{h:02d}" for h in range(24)], hrs)
            + "<figcaption>24 小时分布，按发言时间计。</figcaption></figure>"
        )
    body += _dl([
        ("人均发言", num(m.get("real", 0) / max(1, m.get("members_active", 1))), "条/人"),
        ("发言集中度", f"{m.get('gini', 0)}", "基尼系数"),
        ("前十人占比", pct(m.get("top10_share")), ""),
        ("平均每条", f"{m.get('avg_len', 0)} 字", ""),
        ("话题段", num(m.get("sessions")), "30 分钟断档"),
        ("媒体消息", pct(m.get("media_ratio")), "图片表情等"),
        ("引用回复", pct(m.get("quote_ratio")), ""),
    ])
    gaps = m.get("data_gaps") or []
    note01 = f"数据缺口月份 {', '.join(gaps)}，占比类结论要剔除。" if gaps else ""
    s01 = sec("01", "01", "这个群有多大", body, note01)

    # ---- 02 在聊什么 ----
    body = ""
    ts = data.get("topic_share") or []
    if ts:
        body += (
            "<figure>"
            + hbars([{"name": t["name"], "v": t["share"]} for t in ts[:8]])
            + "<figcaption>主题份额，按提及量口径（一条消息可命中多个主题）。</figcaption></figure>"
        )
    evo = data.get("topic_evolution") or []
    if evo:
        body += (
            "<figure>"
            + lines(evo[:3], [x[2:] for x in months], height=200)
            + "<figcaption>前三主题的月度占比，占当月消息数的百分比。</figcaption></figure>"
        )
    kol = data.get("topic_kol") or {}
    cards = []
    for t in ts[:6]:
        top_users = kol.get(t["name"]) or []
        if not top_users:
            continue
        who = " / ".join(f"{u['name']}（{num(u['n'])}）" for u in top_users[:2])
        cards.append(
            f'<div class="card"><div class="t">{e(t["name"])}</div>'
            f'<div class="h">{e(who)}</div>'
            f'<div class="b">{num(t["n"])} 条提及，占 {pct(t["share"])}</div></div>'
        )
    if cards:
        body += '<div class="cards">' + "".join(cards) + "</div>"
    s02 = sec("02", "02", "在聊什么",
              body, f"词典覆盖率 {pct(m.get('topic_coverage'))}，未命中的多为碎片短句。")

    # ---- 03 谁和谁 ----
    body = ""
    sc = data.get("scatter") or []
    if sc:
        body += (
            "<figure>"
            + scatter(sc)
            + "<figcaption>横轴发言条数，纵轴被引用次数，点的大小是 PageRank。"
              "右下角空着是正常的，头部之外的人发言和被引本来就都很少。</figcaption></figure>"
        )
    body += _dl([
        (r["name"], num(r["msgs"]),
         f"被引 {num(r['q_in'])}，被引率 {r['reply_ratio']}，社群{r['community'] + 1 if r['community'] >= 0 else '外围'}")
        for r in rows[:10]
    ])
    pairs = data.get("strong_pairs") or []
    if pairs:
        body += '<div class="sub">最强互动对</div>' + _dl([
            (f"{p['a']} ↔ {p['b']}", num(p["total"]), f"{p['ab']} / {p['ba']}，平衡度 {p['balance']}")
            for p in pairs[:6]
        ])
    lift = data.get("lift") or []
    if lift:
        body += '<div class="sub">超预期关注</div>' + _dl([
            (f"{p['from']} → {p['to']}", f"{p['lift']}×", f"{num(p['n'])} 次引用")
            for p in lift[:6]
        ])
    comms = data.get("communities") or []
    if comms:
        cards = []
        for c in comms[:4]:
            cards.append(
                f'<div class="card"><div class="t">社群 {c["id"] + 1} · {num(c["size"])} 人</div>'
                f'<div class="h">{e("、".join(c["members"][:8]))}</div></div>'
            )
        body += '<div class="sub">社群</div><div class="cards">' + "".join(cards) + "</div>"
    s03 = sec("03", "03", "谁和谁在说话",
              body, f"模块度 {m.get('modularity')}，越低越说明没有派系。")

    # ---- 04 人物 ----
    body = ""
    profs = (data.get("profiles") or [])[:6]
    cards = []
    for p in profs:
        b = p.get("buckets") or {}
        peak = max(b, key=b.get) if b else "-"
        cards.append(
            f'<div class="card"><div class="t">{num(p["msgs"])} 条 · 占 {p["share"]}%</div>'
            f'<div class="h">{e(p["name"])}</div>'
            f'<div class="b">均长 {p["avg_len"]} 字，短句 {p["short_ratio"]}%，'
            f'发起话题 {p["init_per1000"]}‰，活跃时段 {e(peak)}</div></div>'
        )
    body += '<div class="cards">' + "".join(cards) + "</div>" if cards else ""
    s04 = sec("04", "04", "几个人的样子",
              body, "这里只有可数的行为指标，角色判断要读原文。")

    # ---- 05 节奏 ----
    rhy = data.get("rhythm") or {}
    body = ""
    lat = (rhy.get("latency") or [])[:6]
    if lat:
        body += '<div class="sub">接话速度</div>' + _dl([
            (r["name"], f"{r['median']:.0f} 秒", f"{num(r['n'])} 次接话的中位数")
            for r in lat
        ])
    bursts = (rhy.get("bursts") or [])[:5]
    if bursts:
        body += '<div class="sub">最密集的时段</div>' + _dl([
            (f"{b['start'][5:16]} 起", num(b["n"]), f"{e(b['end'][11:16])} 结束，"
             f"{e('、'.join(n for n, _ in b['senders'][:3]))}")
            for b in bursts
        ])
    flow = (rhy.get("flow") or {}).get("silent") or []
    if flow:
        body += '<div class="sub">已经沉默的人</div>' + _dl([
            (f["name"], str(f["last"])[:10], f"累计 {num(f['msgs'])} 条")
            for f in flow[:5]
        ])
    s05 = sec("05", "05", "群的节奏", body)

    # ---- 06 结论 ----
    concl = prose.get("06") or prose.get("结论") or []
    body = ""
    if concl:
        first, rest = concl[0], concl[1:]
        body += f'<div class="concl"><div class="big">{first["text"]}</div>'
        body += "".join(f"<p>{b['text']}</p>" for b in rest if b["kind"] == "p")
        body += "</div>"
    else:
        body += ('<div class="todo">结论段待写。用 prompts/04_report_prose.md 生成正文，'
                 "存成 md 后用 --prose 填进来。</div>")
    body += _blocks([b for b in concl if b["kind"] != "p"])
    s06 = sec("06", "06", "结论", body)

    foot = (
        '<div class="foot">'
        f"口径 消息 {num(m.get('total'))} 条（系统 {num(m.get('system'))} 条不计入成员榜）"
        f"／ 时间 {e(str(m.get('tmin'))[:10])} 至 {e(str(m.get('tmax'))[:10])}"
        f"／ 主题词典 15 类，覆盖率 {pct(m.get('topic_coverage'))}<br>"
        "正文数字全部来自 report_data.json，不重新计算。涉及真人，仅作个人参考，不做二次传播。"
        "</div>"
    )

    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{e(name)}</title><style>{CSS}</style></head>"
        f'<body><div id="bar"></div><article class="page">{cover}{s01}{s02}{s03}{s04}{s05}{s06}{foot}</article>'
        "<script>addEventListener('scroll',function(){var h=document.documentElement;"
        "var p=h.scrollTop/(h.scrollHeight-h.clientHeight||1);"
        "document.getElementById('bar').style.width=(p*100)+'%'});</script>"
        "</body></html>"
    )


def write(data: dict, path: str | Path, *, prose: dict | None = None,
          title: str | None = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(data, prose=prose, title=title), encoding="utf-8")
    return p
