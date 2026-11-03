# -*- coding: utf-8 -*-
"""分词与词频。

短文本群聊做词频有三个必踩的坑：

1. **不滤词性，榜上全是"就是/然后/感觉"**。必须 `pseg` 后只留名词性 + 动名词；
2. **不滤链接和哈希**，`https://...`、32 位 md5 会把 `[A-Za-z0-9]` 频次拉满；
3. **停用词表要按群定制**。通用停用词表对群聊无效，需要补上这个群的口头禅
   （"旺柴""红包""好吃"），否则所有人都长得一样。

另外提供 `distinctive()`：给每个人算"他爱用但别人不爱用"的词，
用 `p_u * log(p_u / p_all)` 而不是纯词频，纯词频只会把话最多的人顶上榜。
"""
from __future__ import annotations

import collections
import math
import re

import jieba
import jieba.posseg as pseg

jieba.setLogLevel(20)

# 名词性词性白名单：n 类 + 动名词 + 形容词 + 英文
ALLOW_POS = frozenset("n nr ns nt nz vn an eng j jn s l i".split())

BASE_STOP = set(
    """的 了 是 我 你 他 她 它 我们 你们 他们 这 那 有 没 就 在 也 都 和 吧 啊 呀 吗 呢 不
什么 怎么 现在 还是 可以 感觉 觉得 然后 但是 因为 所以 真的 就是 这个 那个 自己 一下 时候
已经 还有 这种 那种 知道 会 要 能 说 看 去 来 上 下 里 个 很 太 好 对 过 给 又 再 才 还
这么 那么 一个 两个 不是 没有 一样 有点 其实 应该 可能 如果 只是 大家 别人 之前 以后 今天
明天 昨天 出来 起来 一点 一堆 干嘛 确实 哈哈 嗯 哦 噢 诶 唉 好像 不能 这样 那样 一直 比较
非常 特别 反正 完全 直接 刚刚 之后 这里 那里 多少 为什么 怎么样 哪儿 东西 时候 需要 的话
是不是 或者 很多 不行 不要 看到 一起 一些 谢谢 发现 不用 不过 一般 而且 以为 时间 不想
""".split()
)

_ASCII_WORD = re.compile(r"^[a-z]{1,2}$")
_HAS_CJK = re.compile(r"[\u4e00-\u9fa5]")


class Vocab:
    """一次分词的全部结果，供词频 / 区分度 / 话题共用。"""

    def __init__(self, stop: set[str] | None = None):
        self.stop = set(BASE_STOP) | set(stop or ())
        self.tokens: list[list[str]] = []          # 与 texts 对齐
        self.msgs: list = []
        self.freq: collections.Counter = collections.Counter()
        self.by_user: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        self.by_word: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        self.sender_of: dict[str, str] = {}
        self.user_total: collections.Counter = collections.Counter()

    # ---- 构建 ----
    @classmethod
    def build(cls, group, stop: set[str] | None = None, pos_filter: bool = True) -> "Vocab":
        from .clean import clean_text

        v = cls(stop)
        for m in group.texts():
            toks = v.cut(clean_text(m.text), pos_filter=pos_filter)
            v.tokens.append(toks)
            v.msgs.append(m)
            v.sender_of[m.wxid] = m.sender
            for w in toks:
                v.freq[w] += 1
                v.by_user[m.wxid][w] += 1
                v.by_word[w][m.wxid] += 1
                v.user_total[m.wxid] += 1
        return v

    def cut(self, text: str, pos_filter: bool = True) -> list[str]:
        out = []
        if pos_filter:
            pairs = pseg.cut(text)
        else:
            pairs = ((w, "n") for w in jieba.cut(text))
        for w, flag in pairs:
            w = w.strip()
            if len(w) < 2 or w in self.stop:
                continue
            if pos_filter and flag not in ALLOW_POS:
                continue
            if not _HAS_CJK.search(w) and not w.isascii():
                continue
            if _ASCII_WORD.match(w):
                continue
            if re.fullmatch(r"[\d\.,%\-]+", w):
                continue
            out.append(w)
        return out

    # ---- 报表 ----
    def top(self, n: int = 100, with_users: int = 3) -> list[dict]:
        rows = []
        for w, c in self.freq.most_common(n):
            rows.append({
                "word": w,
                "count": c,
                "top_users": [
                    {"name": self._name(wx), "n": k}
                    for wx, k in self.by_word[w].most_common(with_users)
                ],
            })
        return rows

    def distinctive(self, wxid: str, top: int = 18, min_hits: int = 8) -> list[tuple[str, int, float]]:
        """某人的标志性用词：命中≥min_hits 才参与，避免一条生僻词冲到第一。"""
        total = self.user_total.get(wxid, 0)
        if total < 50:
            return []
        grand = sum(self.freq.values()) or 1
        scored = []
        for w, c_all in self.freq.items():
            a = self.by_user[wxid].get(w, 0)
            if a < min_hits:
                continue
            p_u = a / total
            p_all = c_all / grand
            if p_all <= 0:
                continue
            scored.append((w, a, p_u * math.log(p_u / p_all)))
        scored.sort(key=lambda x: -x[2])
        return scored[:top]

    def _name(self, wxid: str) -> str:
        return self.sender_of.get(wxid, wxid)
