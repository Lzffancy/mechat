# 提示词

五个环节，按顺序调用。前三步产出"事实卡"，第四步才成文，第五步返修。跳步会出错——
直接让模型写正文，它会在没有事实卡的情况下自己补因果。

| 文件 | 环节 | 输入从哪来 | 输出 |
|---|---|---|---|
| [00_analyst_system.md](00_analyst_system.md) | 系统提示，全程挂着 | — | — |
| [01_cluster_naming.md](01_cluster_naming.md) | 给聚类簇命名、判断垃圾桶簇 | `cluster --k 12` | 簇名 + 保留/丢弃 |
| [02_member_profile.md](02_member_profile.md) | 成员画像 | `profile` + `ctx --who` | 人物卡（150~250 字） |
| [03_relationship_deepdive.md](03_relationship_deepdive.md) | 单人 / 双人关系深挖 | `ctx --search` 或指定时段 | 时间线 + 结构判断 |
| [04_report_prose.md](04_report_prose.md) | 报告正文 | `report_data.json` + 事实卡 | Markdown 文字块 |
| [05_prose_audit.md](05_prose_audit.md) | 文案返修 | `prose --html` 的体检结果 | 逐条改写 |

`04` 只输出文字，不输出 HTML。排版由 `python -m wxchat_analysis html` 套
纸媒杂志风模板完成，规则见 [docs/REPORT_STYLE.md](../docs/REPORT_STYLE.md)。
写作规范的完整版在 [skills/human-writing/](../skills/human-writing/)。

## 调用链

```
数据层  report_data.json（数字）      ctx 导出的窗口（原文）
              │                            │
              ├─ 01 簇命名 ────────────────┘
              ├─ 02 成员画像
              └─ 03 关系深挖  ──▶  事实卡（带消息索引的短条目）
                                        │
                        04 正文 ◀────────┘  + report_data.json
                              │
                        05 返修 ◀── prose.check 的体检结果
                              │
                        html 命令套模板（代码做排版，不是模型）
                              ▼
                          交付
```

## 四个通用约定

**一、占位符**用 `{{双花括号}}`，替换时不要动其他文字。

**二、每次调用只做一件事。** 一次让它既命名又写正文，结果一定是两件都含糊。

**三、输入里必须带消息索引。** `ctx` 的输出第一列就是索引，别在喂之前删掉——所有结论都要
能指回具体某一条，否则无法复核。

**四、输出要能被下一步直接消费。** 01 输出 JSON，02 输出固定四段的纯文本，03 输出带索引的
条目列表。都要能贴进 `04_report_prose.md` 的输入位置，不要输出聊天式的"好的，我来分析一下"。

## 什么时候不用模型

- 只想要数字和图表 → `report` 一条命令就够，模型加不了信息量；
- 数据量小于 500 条 → 自己读比调模型快，也更准；
- 只需要词频和关系图 → 模型帮不上忙。

## 记录

同一份数据换模型会换结论。产出报告时在末尾记一行：

```
模型 xxx / 温度 0.4 / 窗口 12 段共 640 条 / 生成日期 yyyy-mm-dd
```
