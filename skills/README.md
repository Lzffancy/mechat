# human-writing

中文写作与改稿规范，从本机 `~/.workbuddy/skills/human-writing` 打包进来，
跟着仓库走，换机器不用重新找。

```
skills/human-writing/
  SKILL.md                 主规则：材料检查、说话位置、成稿硬禁令
  references/forum-prose.md  论坛长帖与公众号文章的写法
  references/reality.md     现实内容的核验要求
  references/revision.md    改稿规则，区分绝对禁词和需判断的词
  references/fiction.md     虚构创作
  references/formats.md     短内容、口播、剧本等格式
  scripts/check_prose.py    硬禁令检查脚本（只报警，不自动改文）
```

## 在这个项目里怎么用

**写作环节**：`prompts/00_analyst_system.md` 里的写作纪律就是这份规范的压缩版，
完整规则看 `SKILL.md`，长文写法看 `references/forum-prose.md`。

**体检环节**，两个都跑：

```bash
# 完整版，报得细（含需人工判断的警告项）
python skills/human-writing/scripts/check_prose.py 正文.md

# 内置版，只报硬禁令，能直接嵌进流程里拿结构化结果
python -m wxchat_analysis prose --text 正文.md
python -m wxchat_analysis prose --html 报告.html
```

两者的差别：`check_prose.py` 覆盖全部软硬规则并区分"绝对禁词"和"需结合语境判断的词"，
是最终交付前的把关；`wxchat_analysis/prose.py` 只做硬禁令，输出结构化结果给返修脚本用。

## 硬禁令（成稿必须清零）

- 中文冒号 `：`、英文冒号 `:`（网址、代码、机器字段除外）
- 破折号 `——`、单破折号 `—`、连接号 `–`
- 翻案句：不是…而是 / 并非…而是 / 不在于…而在于 / 与其说…不如说 / 不只…还 / 表面…实际 / 看似…实则
- 硬停词：不丢 / 说白了 / 说穿了 / 先说结论
- 模型路标：更微妙的是 / 还有一层 / 只说对了一半 / 值得注意的是 / 需要指出的是 / 从某种意义上说
- 绝对禁词：赋能、抓手、闭环、能力沉淀、打法、拉通、底层逻辑、顶层设计、认知跃迁、
  价值释放、能力建设、降本增效、内容矩阵、全链路、组合拳、想象空间、结构性机会、
  关键命题、深层逻辑、技术底座、单点风险、认知增量、材料锚点
- 借喻包装抽象概念：仓库、抽屉、温度、死亡、坍塌、浪潮、钥匙、底座
- 把抽象事物当实体操作的动词：钉住、锚定、打通、落地、沉淀、撬动、撕开、解剖

覆盖标题、小标题、正文、图注和引用转述。引用的原话命中禁令时改成转述，不能靠引号保留。

## 一个豁免

本仓库 `examples/prose_sample.md` 里的 `::` 是引语来源标记的语法符号，
会被 `check_prose.py` 判为英文冒号，属于格式豁免，不用改。
