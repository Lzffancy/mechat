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

### 正文稿件（`--prose`）

`prose_sample.md` 是模型输出该长什么样的样例，格式约定：

- 分节标题 `## 00`（封面导语）、`## 01` 到 `## 06`，对应报告的章节编号
- 普通段落直接写，空行分段
- `>` 开头是引语块，`::` 后面接来源（可选）
- `- ` 开头是列表
- `**文字**` 是加粗

生成：

```bash
python -m wxchat_analysis html --data out/report_data.json \
    --prose examples/prose_sample.md -o out/报告.html
```

写完先过体检，两项必须清零：

```bash
python skills/human-writing/scripts/check_prose.py examples/prose_sample.md
python -m wxchat_analysis prose --text examples/prose_sample.md
```

两点说明：

- 数据量小，`cluster` 会直接跳过并提示改用词典法，这是设计行为不是故障；
- 引用消息的 `content` 是真实导出里的 XML 形态，用来验证 `refermsg.chatusr`
  的解析路径，改数据结构前先跑一遍样例。
