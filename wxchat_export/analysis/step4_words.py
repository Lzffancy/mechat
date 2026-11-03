# -*- coding: utf-8 -*-
"""Step 4: 分词 + 词频探索"""
import pickle, os, re, collections, json
import jieba

OUT = r"C:\Users\<you>\Desktop\wxchat\out"
d = pickle.load(open(os.path.join(OUT, 'msgs.pkl'), 'rb'))
msgs, members = d['msgs'], d['members']

STOP = set("""的 了 是 我 你 他 她 它 们 在 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 会 着 没有 看 好 自己 这 那 什么 啊 吧 呢 吗 呀 哦 嗯 哈 就 还 但是 但 因为 所以 如果 现在 可以 这个 那个 还是 感觉 觉得 知道 然后 就是 真的 已经 一下 有点 有点 可能 应该 怎么 这么 那么 我们 你们 他们 大家 时候 东西 一下 不是 没 太 太 再 又 才 都 只 把 被 让 给 对 从 向 跟 和 或 而 却 之类 这样 那样 一样 一直 已经 比较 非常 特别 其实 反正 确实 完全 直接 刚刚 之前 之后 现在 今天 明天 昨天 这里 那里 哪 谁 多少 几 个 条 张 次 点 块 元 说 讲 问 答 嗯嗯 哈哈 哈哈哈 哈哈哈哈 笑 笑死 表情 图片 语音 文件 链接 群 微信 消息""".split())

NOISE_PAT = re.compile(r'(http|mp://|www\.|\.com|\.cn|红包|领取|优惠券|美团|淘宝|拼多多|助力|戳一戳)')

def clean(t):
    t = re.sub(r'\[[^\]]{1,10}\]', ' ', t)      # 表情占位
    t = re.sub(r'@\S+', ' ', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip()

texts, meta = [], []
for m in msgs:
    if m['type'] not in ('text', 'app:quote', 'app:link'):
        continue
    t = clean(m['text'] or '')
    if len(t) < 2 or NOISE_PAT.search(t):
        continue
    texts.append(t)
    meta.append(m)

print("有效文本消息", len(texts))

# 自定义词典：群内黑话/人名
jieba.load_userdict_from = None
for wx, mm in members.items():
    nm = (mm['display'] or '').strip()
    if nm and not nm.startswith('wxid') and len(nm) >= 2:
        jieba.add_word(nm, freq=200)
for w in ['大模型','ChatGPT','Claude','Gemini','DeepSeek','GPT','API','前端','后端','运维','测试','产品经理',
          '程序员','代码','服务器','数据库','裁员','跳槽','面试','加班','年终奖','绩效','房贷','基金','股票',
          '马拉松','徒步','露营','火锅','烧烤','奶茶','咖啡','健身','减肥','猫','狗','旅游','日本','新疆','珠海',
          '深圳','北京','上海','广州','杭州','成都','重庆','西安','考研','考公','结婚','离婚','相亲','生娃']:
    jieba.add_word(w, freq=100)

wc = collections.Counter()
wc_per = collections.defaultdict(collections.Counter)
for t, m in zip(texts, meta):
    for w in jieba.cut(t):
        w = w.strip()
        if len(w) < 2 or w in STOP or w.isdigit() or re.fullmatch(r'[a-zA-Z]{1}', w):
            continue
        if not re.search(r'[\u4e00-\u9fa5a-zA-Z]', w):
            continue
        wc[w] += 1
        wc_per[m['wxid']][w] += 1

print("\n=== 全群高频词 top80 ===")
for w, c in wc.most_common(80):
    print(f"{w}:{c}", end='  ')
print("\n\n词条总数", len(wc))

pickle.dump({'texts': texts, 'meta': meta, 'wc': wc}, open(os.path.join(OUT, 'texts.pkl'), 'wb'))
pickle.dump(dict(wc_per), open(os.path.join(OUT, 'wc_per.pkl'), 'wb'))
