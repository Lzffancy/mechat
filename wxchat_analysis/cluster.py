# -*- coding: utf-8 -*-
"""滑窗 TF-IDF + KMeans 主题聚类。

**定位：这是"发现意外话题"的辅助手段，不是主口径。** 短文本群聊直接对单条消息聚类
必然失败，所以先把连续 N 条有效消息拼成一段"话题段"再聚类，簇的语义才立得住。

已知问题（不要试图调参解决）：

- 6~12 个簇里通常有 2~3 个是垃圾桶，装的是"哈哈哈 / 几点 / 名字"这类填充语；
- 簇的关键词只能提示方向，命名必须人（或 LLM）看着代表消息来定；
- 结果对 k 敏感，`sweep()` 的轮廓系数只用来排除明显不合适的 k，不能当结论。

结论进报告前，一律先用词典法（topics.py）交叉验证；聚类只提供"词典没覆盖到什么"。
"""
from __future__ import annotations

import collections
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize

WINDOW = 40
STEP = 20
MIN_TOKENS = 30


@dataclass
class ClusterResult:
    k: int
    labels: np.ndarray
    terms: list[str]
    centers: np.ndarray
    clusters: list[dict]
    msg_label: np.ndarray
    msg_conf: np.ndarray
    n_docs: int

    def summary(self) -> list[dict]:
        return [
            {"id": c["id"], "n": c["n"], "terms": c["terms"][:10],
             "months": c["months"], "examples": c["examples"][:3]}
            for c in self.clusters
        ]


def _docs(vocab, window: int, step: int) -> tuple[list[str], list[tuple[int, int]]]:
    docs, rng = [], []
    n = len(vocab.tokens)
    for i in range(0, max(1, n - window + 1), step):
        merged = [w for seg in vocab.tokens[i : i + window] for w in seg]
        if len(merged) < MIN_TOKENS:
            continue
        docs.append(" ".join(merged))
        rng.append((i, min(i + window, n)))
    return docs, rng


def _vectorize(docs: list[str]):
    if not docs:
        raise ValueError("没有可用的窗口，消息太少或全被停用词过滤掉了")
    # min_df 要跟着语料规模走，固定 8 在几百条的小群上会直接得到空词表
    min_df = 8 if len(docs) >= 200 else max(2, len(docs) // 20)
    vec = TfidfVectorizer(min_df=min_df, max_df=0.5, token_pattern=r"(?u)\S+", sublinear_tf=True)
    try:
        X = vec.fit_transform(docs)
    except ValueError as e:
        raise ValueError(f"词表为空（{e}），样本太小，这套聚类不适合，改用词典法") from e
    return vec, X, np.array(vec.get_feature_names_out())


def sweep(vocab, ks=(6, 8, 10, 12, 14, 16), window: int = WINDOW, step: int = STEP) -> list[dict]:
    """跑一遍 k，输出惯性 + 轮廓系数。只用于排除，不用于选优。"""
    docs, _ = _docs(vocab, window, step)
    _vec, X, _ = _vectorize(docs)
    out = []
    for k in ks:
        if k * 3 >= X.shape[0]:
            continue
        km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
        s = silhouette_score(X, km.labels_, sample_size=min(3000, X.shape[0]), random_state=0)
        out.append({"k": k, "inertia": round(float(km.inertia_), 1), "silhouette": round(float(s), 4)})
    return out


def run(vocab, group, k: int = 12, window: int = WINDOW, step: int = STEP,
        top_terms: int = 14, examples: int = 10) -> ClusterResult:
    docs, rng = _docs(vocab, window, step)
    if len(docs) < max(20, k * 2):
        raise ValueError(
            f"只有 {len(docs)} 个窗口，跑不了 K={k} 的聚类。"
            "消息量小的时候聚类没有意义，直接用词典法（topics）"
        )
    vec, X, terms = _vectorize(docs)
    km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)

    # 消息级归属：与簇质心做余弦。
    # 空文档（纯媒体 / 全是停用词）的向量是零向量，余弦恒为 0，argmax 会全部落到簇 0，
    # 制造一个几万条的假簇。必须单独标成 -1。
    msg_docs = [" ".join(t) for t in vocab.tokens]
    Xm = normalize(vec.transform(msg_docs))
    C = normalize(km.cluster_centers_)
    sim = Xm @ C.T
    lab = sim.argmax(axis=1)
    conf = sim.max(axis=1)
    empty = np.array([not d.strip() for d in msg_docs])
    lab[empty] = -1
    conf[empty] = 0.0

    clusters = []
    for c in range(k):
        idx_w = np.argsort(-km.cluster_centers_[c])[:top_terms]
        months = collections.Counter(vocab.msgs[i].month for i in range(len(docs)) if km.labels_[i] == c)
        idx_m = [i for i in range(len(lab)) if lab[i] == c]
        idx_m.sort(key=lambda i: -conf[i])
        ex = []
        for i in idx_m:
            txt = (vocab.msgs[i].text or "").replace("\n", " ")
            if len(txt) < 6:
                continue
            ex.append({"time": vocab.msgs[i].date, "sender": vocab.msgs[i].sender, "text": txt[:90]})
            if len(ex) >= examples:
                break
        clusters.append({
            "id": c,
            "n": int((km.labels_ == c).sum()),
            "msg_n": len(idx_m),
            "terms": [terms[i] for i in idx_w],
            "months": months.most_common(2),
            "examples": ex,
        })
    return ClusterResult(k=k, labels=km.labels_, terms=list(terms), centers=km.cluster_centers_,
                         clusters=clusters, msg_label=lab, msg_conf=conf, n_docs=len(docs))
