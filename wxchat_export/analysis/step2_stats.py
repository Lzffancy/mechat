# -*- coding: utf-8 -*-
"""Step 2: 基础统计 + @名称映射"""
import pickle, os, collections, re, datetime, json

OUT = r"C:\Users\<you>\Desktop\wxchat\out"
d = pickle.load(open(os.path.join(OUT, 'msgs.pkl'), 'rb'))
msgs, members = d['msgs'], d['members']

# ---- 名称词典 ----
name2wx = {}
for wx, m in members.items():
    for k in (m['nick'], m['display'], m['remark']):
        if k and k.strip():
            name2wx[k.strip()] = wx
# 常见别名补丁（群昵称变更）
alias = {
    '杨院的粉丝': None, 'SCP': None, '一言的粉丝': None, '圆圆的CR2025': None,
    '圆圆1号': None, 'XiAO': None, '晏池': None, '暗夜': None,
}
# 打印未匹配的 at token 频次
atc = collections.Counter()
for mm in msgs:
    for a in mm['ats']:
        a = a.strip().replace('\x7f', '')
        if a:
            atc[a] += 1
unmatched = [(k, v) for k, v in atc.most_common() if k not in name2wx]
print("=== 未匹配 @ 名称 top30 ===")
for k, v in unmatched[:30]:
    print(repr(k), v)

print("\n=== 成员发言数（按 members.csv 声明） ===")
tot = sum(m['cnt_declared'] for m in members.values())
print("declared total", tot)

# ---- 基础统计 ----
by_sender = collections.Counter(m['wxid'] for m in msgs)
by_type = collections.Counter(m['type'] for m in msgs)
days = collections.Counter(m['time'][:10] for m in msgs)
months = collections.Counter(m['time'][:7] for m in msgs)
hours = collections.Counter(m['time'][11:13] for m in msgs)
wday = collections.Counter(datetime.date.fromisoformat(k).weekday() for k in days)

tmin, tmax = msgs[0]['time'], msgs[-1]['time']
span = (datetime.datetime.fromisoformat(tmax) - datetime.datetime.fromisoformat(tmin)).days + 1
print(f"\ntime {tmin} ~ {tmax}  span={span}d  active_days={len(days)}")
print("avg msgs/day(active)", round(len(msgs)/len(days), 1))
print("monthly", dict(sorted(months.items())))
print("hours", dict(sorted(hours.items())))
print("weekday", dict(sorted(wday.items())))
print("types", by_type.most_common())

# 文本量
txt_msgs = [m for m in msgs if m['type'] == 'text']
chars = sum(len(m['text']) for m in txt_msgs)
print(f"text msgs {len(txt_msgs)}  total chars {chars}  avg len {chars/len(txt_msgs):.1f}")

# 每日 Top20
print("\n=== 最活跃日期 top15 ===")
for k, v in days.most_common(15):
    print(k, v)

# 单条最长
longest = sorted(txt_msgs, key=lambda x: -len(x['text']))[:5]
print("\n=== 最长消息 ===")
for m in longest:
    print(m['time'], m['sender'], len(m['text']), m['text'][:120].replace('\n', ' '))

# 连续对话段（session）划分：间隔 > 30min 视为新段
sess = []
cur = [msgs[0]]
for a, b in zip(msgs, msgs[1:]):
    if (b['ts'] or 0) - (a['ts'] or 0) > 1800:
        sess.append(cur); cur = [b]
    else:
        cur.append(b)
sess.append(cur)
print(f"\nsessions(>30min gap) {len(sess)}  avg {len(msgs)/len(sess):.1f} msgs/session")
print("top5 session size", sorted([len(s) for s in sess], reverse=True)[:5])

stats = {
    'tmin': tmin, 'tmax': tmax, 'span': span, 'n': len(msgs),
    'active_days': len(days), 'sessions': len(sess),
    'months': dict(sorted(months.items())),
    'hours': dict(sorted(hours.items())),
    'weekday': dict(sorted(wday.items())),
    'types': dict(by_type),
    'days': dict(days),
    'by_sender': dict(by_sender),
    'unmatched_at': unmatched,
}
pickle.dump(stats, open(os.path.join(OUT, 'stats.pkl'), 'wb'))
json.dump(stats, open(os.path.join(OUT, 'stats.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
