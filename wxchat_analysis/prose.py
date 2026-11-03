# -*- coding: utf-8 -*-
"""文案体检：把 LLM 写的正文过一遍硬禁令。

规则来自长期被指出的问题，不是风格偏好，是硬约束：

- 中文冒号、英文冒号——正文里不用，改成句号或逗号；
- 破折号——拆成两个短句，不要机械换逗号；
- 翻案句（不是…而是）——拆成两句陈述；
- 黑话（赋能/抓手/闭环/沉淀…）——直接删，换成具体动作；
- 借喻动词（钉住/锚定/打通/解剖…）——把抽象事物当实体的动词，一律删。

`check()` 只报形状，不判对错。"方法论""一套流程"这类可能是本义，必须人工看。
用法见 `prompts/05_prose_audit.md`。
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

COLON_CN = "："

REVERSAL = [
    (r"不是[^。！？\n]{1,30}?而是", "不是…而是"),
    (r"并非[^。！？\n]{1,30}?而是", "并非…而是"),
    (r"不在于[^。！？\n]{1,30}?而在于", "不在于…而在于"),
    (r"与其说[^。！？\n]{1,30}?不如说", "与其说…不如说"),
    (r"不只是[^。！？\n]{1,20}?还", "不只…还"),
    (r"看似[^。！？\n]{1,20}?实则", "看似…实则"),
    (r"表面上?[^。！？\n]{1,20}?实际上?", "表面…实际"),
]

HARD_STOP = ["不丢", "说白了", "说穿了", "先说结论"]
MODEL_MARKERS = ["更微妙的是", "还有一层", "只说对了一半", "值得注意的是", "需要指出的是",
                 "从某种意义上说", "换句话说"]
BANNED = ["赋能", "抓手", "闭环", "能力沉淀", "打法", "拉通", "底层逻辑", "顶层设计",
          "认知跃迁", "价值释放", "能力建设", "降本增效", "内容矩阵", "全链路", "组合拳",
          "想象空间", "结构性机会", "关键命题", "深层逻辑", "技术底座", "单点风险",
          "认知增量", "材料锚点"]
METAPHOR_VERBS = ["钉住", "锚定", "打通", "落地", "沉淀", "撬动", "撕开", "解剖", "抓手",
                  "温度", "坍塌", "浪潮", "钥匙", "底座", "抽屉", "仓库", "闭环"]

URL = re.compile(r"https?://\S+")


@dataclass
class Issue:
    kind: str
    text: str
    count: int
    level: str = "error"  # error / warn


@dataclass
class ProseReport:
    chars: int
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warns(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warn"]

    @property
    def clean(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines = [f"汉字数 {self.chars}  问题 {len(self.errors)} 条 / 待判断 {len(self.warns)} 条"]
        for i in self.issues:
            tag = "✗" if i.level == "error" else "?"
            lines.append(f"  {tag} {i.count:>3}  {i.kind}: {i.text[:60]}")
        if self.clean:
            lines.append("  硬禁令全部通过")
        return "\n".join(lines)


def _ctx(text: str, pos: int, width: int = 18) -> str:
    return text[max(0, pos - width) : pos + width].replace("\n", " ")


def check(text: str) -> ProseReport:
    body = URL.sub(" ", text or "")
    rep = ProseReport(chars=len(re.findall(r"[\u4e00-\u9fa5]", body)))

    n = body.count(COLON_CN)
    if n:
        pos = body.index(COLON_CN)
        rep.issues.append(Issue("中文冒号", _ctx(body, pos), n))

    dash_hits = body.count("——") + body.replace("——", "").count("—") + body.count("–")
    if dash_hits:
        cands = [body.index(d) for d in ("——", "—", "–") if d in body]
        rep.issues.append(Issue("破折号", _ctx(body, min(cands)), dash_hits))

    for rx, label in REVERSAL:
        ms = re.findall(rx, body)
        if ms:
            rep.issues.append(Issue("翻案句", f"{label} ← {ms[0][:40]}", len(ms)))

    for w in HARD_STOP + MODEL_MARKERS + BANNED + METAPHOR_VERBS:
        c = body.count(w)
        if c:
            level = "error" if w in BANNED or w in HARD_STOP else "warn"
            rep.issues.append(Issue("用词", w, c, level=level))

    # 长句：一段里超过 4 个"的"通常是翻译腔
    for para in body.split("\n"):
        if len(para) > 120 and para.count("的") >= 5:
            rep.issues.append(Issue("长句（人工判断）", para[:50], para.count("的"), level="warn"))
            break

    rep.issues.sort(key=lambda i: (i.level != "error", -i.count))
    return rep


_HTML_BREAK = re.compile(r"</(p|div|li|h1|h2|h3|section|blockquote|tr)>|<br\s*/?>", re.I)


def extract_html(path: str) -> str:
    """从 HTML 里抽纯文本：先剥 style/script，再把块级标签换行，最后去标签。"""
    raw = open(path, encoding="utf-8").read()
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    raw = _HTML_BREAK.sub("\n", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = html.unescape(raw)
    return re.sub(r"\n{3,}", "\n\n", raw)
