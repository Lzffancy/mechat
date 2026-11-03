# -*- coding: utf-8 -*-
"""Step 3: 用引用消息的历史昵称建立 wxid<->昵称映射，并解析@"""
import pickle, os, collections, re, json

OUT = r"C:\Users\<you>\Desktop\wxchat\out"
d = pickle.load(open(os.path.join(OUT, 'msgs.pkl'), 'rb'))
msgs, members = d['msgs'], d['members']

# 历史昵称：从 refermsg 提取 (wxid -> set(displayname))
hist = collections.defaultdict(collections.Counter)
for m in msgs:
    w, n = m['ref_wxid'], m['ref_name']
    if w and n and '@chatroom' not in w:
        hist[w][n] += 1

print("=== 通过引用建立的历史昵称（推断归属） ===")
person_names = {}
for wx, ctr in sorted(hist.items(), key=lambda x: -sum(x[1].values())):
    names = [n for n, _ in ctr.most_common() if n.strip()]
    cur = members.get(wx, {}).get('display', '?')
    person_names[wx] = names
    print(f"{wx:26s} 当前={cur:22s} 历史={names[:8]}")

# 别名词典
name2wx = {}
for wx, m in members.items():
    for k in (m['nick'], m['display'], m['remark']):
        if k and k.strip():
            name2wx[k.strip()] = wx
for wx, names in person_names.items():
    for n in names:
        name2wx.setdefault(n.strip(), wx)

# 手工补丁：无法自动推断的
manual = {
    '时不时冒个泡的小王': None,
}
# 模糊匹配：at token 与成员名的包含关系
def resolve(tok):
    tok = tok.strip().replace('\x7f', '')
    if not tok:
        return None
    if tok in name2wx:
        return name2wx[tok]
    cands = []
    for k, wx in name2wx.items():
        if k.startswith(tok) or tok.startswith(k) or (len(tok) >= 3 and tok in k):
            cands.append((len(k), wx))
    if not cands:
        return None
    cands.sort()
    return cands[0][1]

atc = collections.Counter()
resolved, unresolved = collections.Counter(), collections.Counter()
for m in msgs:
    for a in m['ats']:
        atc[a.strip().replace('\x7f', '')] += 1
        wx = resolve(a)
        if wx:
            resolved[wx] += 1
        else:
            unresolved[a.strip()] += 1

print("\n=== @ 解析结果 ===")
print("总@次数", sum(atc.values()), " 解析成功", sum(resolved.values()))
print("\n未解析 top20:")
for k, v in unresolved.most_common(20):
    print(repr(k), v)
print("\n被@最多 top15:")
for wx, v in resolved.most_common(15):
    print(members.get(wx, {}).get('display', wx), v)

pickle.dump({'name2wx': name2wx, 'hist': dict(hist)}, open(os.path.join(OUT, 'names.pkl'), 'wb'))

# 2026-04 断档检查
apr = [m['time'] for m in msgs if m['time'].startswith('2026-04')]
print("\n2026-04 消息数", len(apr), apr[:3], apr[-3:] if apr else '')
days_apr = sorted(set(t[:10] for t in apr))
print("2026-04 活跃日", days_apr)
# 前后月尾部/头部日期
for mo in ['2026-03', '2026-05']:
    ds = sorted(set(m['time'][:10] for m in msgs if m['time'].startswith(mo)))
    print(mo, "首日", ds[0], "末日", ds[-1], "活跃天", len(ds))
