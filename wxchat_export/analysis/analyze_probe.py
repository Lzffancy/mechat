# -*- coding: utf-8 -*-
import json, collections, re, os

SRC = r"C:\Users\<you>\wx_dec\示例群\示例群.jsonl"

types = collections.Counter()
at_samples = []
quote_samples = []
n = 0
senders = collections.Counter()
ts_min, ts_max = None, None

with open(SRC, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        n += 1
        types[d.get('type')] += 1
        ts = d.get('ts')
        if ts:
            ts_min = ts if ts_min is None else min(ts_min, ts)
            ts_max = ts if ts_max is None else max(ts_max, ts)
        senders[d.get('sender')] += 1
        c = d.get('content') or ''
        if 'atuserlist' in c or '@chatroom' in c:
            if len(at_samples) < 3:
                at_samples.append(c[:1200])
        if d.get('type') in ('quote', 'app', 'link') and len(quote_samples) < 2:
            quote_samples.append((d.get('type'), c[:1500]))

print("total", n)
print("types", dict(types))
print("time", ts_min, ts_max)
print("senders", len(senders))
print("---- at samples ----")
for s in at_samples:
    print(s[:900])
    print('...')
print("---- other samples ----")
for t, s in quote_samples:
    print(t, s[:1000])
