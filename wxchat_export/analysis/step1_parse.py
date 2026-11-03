# -*- coding: utf-8 -*-
"""Step 1: 解析 + 基础统计"""
import json, collections, re, os, pickle, html

SRC = r"C:\Users\<you>\wx_dec\示例群\示例群.jsonl"
OUT = r"C:\Users\<you>\Desktop\wxchat\out"
os.makedirs(OUT, exist_ok=True)

msgs = []
with open(SRC, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        t = d.get('type') or ''
        c = d.get('content') or ''
        rec = {
            'ts': d.get('ts'),
            'time': d.get('time'),
            'sender_id': d.get('sender_id'),
            'wxid': d.get('sender_wxid'),
            'sender': d.get('sender') or d.get('sender_wxid'),
            'type': t,
            'text': '',
            'ref_wxid': None,
            'ref_name': None,
            'ats': [],
        }
        if t == 'text':
            rec['text'] = c
        elif t.startswith('app:'):
            mm = re.search(r'<title>(.*?)</title>', c, re.S)
            if mm:
                rec['text'] = html.unescape(mm.group(1))
            if t == 'app:quote':
                rm = re.search(r'<refermsg>.*?<chatusr>(.*?)</chatusr>', c, re.S)
                nm = re.search(r'<refermsg>.*?<displayname>(.*?)</displayname>', c, re.S)
                if rm:
                    rec['ref_wxid'] = rm.group(1).strip()
                if nm:
                    rec['ref_name'] = html.unescape(nm.group(1).strip())
        elif t in ('image', 'sticker', 'video', 'voice', 'location', 'card'):
            rec['text'] = ''
        if '@' in rec['text']:
            rec['ats'] = re.findall(r'@([^\s@\u2005]+)', rec['text'])
        msgs.append(rec)

msgs.sort(key=lambda x: (x['ts'] or 0))

# 成员表
import csv
members = {}
with open(r"C:\Users\<you>\wx_dec\示例群\示例群_members.csv", 'r', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        members[row['wxid']] = {
            'member_id': row['member_id'],
            'nick': row['昵称'],
            'remark': row['备注'],
            'display': row['显示名'],
            'cnt_declared': int(row['发言数'] or 0),
        }

print("messages", len(msgs))
print("members", len(members))
print("distinct senders", len(set(m['wxid'] for m in msgs)))
print("quotes with ref", sum(1 for m in msgs if m['ref_wxid']))
print("msgs with at", sum(1 for m in msgs if m['ats']))

# ref_wxid 是 chatroom 的情况
refc = collections.Counter(m['ref_wxid'] for m in msgs if m['ref_wxid'])
print("ref targets", refc.most_common(10))

atc = collections.Counter()
for m in msgs:
    for a in m['ats']:
        atc[a] += 1
print("at tokens top", atc.most_common(15))

with open(os.path.join(OUT, 'msgs.pkl'), 'wb') as f:
    pickle.dump({'msgs': msgs, 'members': members}, f)
