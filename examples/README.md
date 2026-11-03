# 合成样例

`demo.jsonl` 和 `demo_members.csv` 是手写的假数据：5 个人、60 条消息、3 个月，
覆盖文本、图片、表情、引用、@、系统消息六种形态。作用是让全链路跑得通，
**不含任何真实聊天内容**。

```bash
python -m wxchat_analysis report --input examples/demo.jsonl \
    --members examples/demo_members.csv -o /tmp/demo_out

python -m wxchat_analysis stats  --input examples/demo.jsonl --members examples/demo_members.csv
python -m wxchat_analysis graph  --input examples/demo.jsonl --members examples/demo_members.csv
python -m wxchat_analysis ctx    --input examples/demo.jsonl --search 彩礼 --pad 3
```

两点说明：

- 数据量小，`cluster` 会直接跳过并提示改用词典法，这是设计行为不是故障；
- 引用消息的 `content` 是真实导出里的 XML 形态，用来验证 `refermsg.chatusr`
  的解析路径，改数据结构前先跑一遍样例。
