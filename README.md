# mechat

微信 4.x 本地聊天记录提取 + 群聊分析。仅本人账号、本机、不联网。

分工原则一条：**能算的写死在代码里，要判断的交给 LLM，两者之间用 JSON 和上下文窗口交接。**

```
mechat/
├── wxchat_export/       ① 提取：探针 → 密钥校验 → 页级解密 → 导出（复用现成取密钥工具）
├── wxchat_analysis/     ② 分析：统计 / 分词 / 主题 / 关系网络 / 节奏 / 画像 / 汇总
├── prompts/             ③ LLM 环节：给聚类命名、写人物卡、做关系深挖、写正文、返修文案
├── docs/METHOD.md       分析方法与口径（含所有踩过的坑）
├── docs/LLM_BOUNDARY.md 哪一步必须写死、哪一步必须交给模型，以及为什么
└── examples/            一份 30 条的合成样例，跑得通全链路，不含任何真实聊天内容
```

## 快速开始

```bash
pip install -r requirements.txt

# ① 提取（微信要登录运行，步骤见 wxchat_export/README.md）
python -m wxchat_export.probe
python -m wxchat_export.verify_key <passphrase_hex> --decrypt-smallest
python -m wxchat_export.dump --db <加密库> --key <hex> --out <明文库>
python -m wxchat_export.export_group --name <群名> --root <明文目录>

# ② 分析（全流程，产出 report_data.json + 4 张表）
python -m wxchat_analysis report \
    --input <群名>.jsonl --members <群名>_members.csv -o out/

# 单步看数
python -m wxchat_analysis stats   --input <群名>.jsonl --members <群名>_members.csv
python -m wxchat_analysis topics  --input <群名>.jsonl --examples
python -m wxchat_analysis graph   --input <群名>.jsonl
python -m wxchat_analysis cluster --input <群名>.jsonl --k 12
python -m wxchat_analysis profile --input <群名>.jsonl

# ③ 取上下文喂模型 / 体检文案
python -m wxchat_analysis ctx --input <群名>.jsonl --who 某人 --pad 8
python -m wxchat_analysis ctx --input <群名>.jsonl --search "彩礼" --pad 15
python -m wxchat_analysis prose --html 报告.html

# 合成样例，验证链路是否正常（不涉及真实数据）
python -m wxchat_analysis report --input examples/demo.jsonl \
    --members examples/demo_members.csv -o /tmp/demo_out
```

## 分析方法长什么样

见 [docs/METHOD.md](docs/METHOD.md)。三句话概括：

1. **网络边只认真实回复**（引用 + @），时序共现会把图稠密化到模块度 0.06，社群发现直接失效；
2. **主题主口径是词典多标签**，聚类只用来发现词典漏掉的东西，因为短文本 KMeans 必然产垃圾桶簇；
3. **报告里每个数字都要能追到 `report_data.json` 里的一个字段**，正文不重新算数。

## LLM 环节

见 [prompts/README.md](prompts/README.md) 和 [docs/LLM_BOUNDARY.md](docs/LLM_BOUNDARY.md)。
不接模型也能出全套数字和图表，只是没有解读和行文；接入模型后多出来的是命名、归因、取舍和成文。

## 隐私与边界

- 明文库 = 完整隐私。`.gitignore` 挡掉 `*.db` / `*.jsonl` / `keys/` / `out/`，任何情况下不要提交。
- 本仓库不含任何真实聊天内容、成员名单或分析产物；`examples/` 是手写合成数据。
- 只处理本人账号在本机上的数据，不做远程访问、不绕过登录态。
- 分析结论涉及真人时，产物只作个人参考，不做二次传播。

## 已知限制

- 微信大版本升级后加密参数可能变，取密钥工具也可能失效，需要重跑定位流程（见 `wxchat_export/README.md` §三）。
- WAL 增量合并未实现，导出前必须冷备份 `.db` / `-wal` / `-shm` 三件套。
- 媒体文件只有引用，不解码图片和语音。
- 主题词典是单群调出来的，换群要重新看停用词和关键词，不要直接套用。
