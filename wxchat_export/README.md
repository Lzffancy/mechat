# wxchat_export

微信 4.x 本地聊天记录提取工具。仅本人账号、仅本机、不联网、不修改原库。

这个目录是**唯一入口**：取密钥之后的全部环节（探针 / 解密 / 验证 / 导出 / 测试）都在这里，
方法说明和踩坑记录也一并放在这里，不再散落在仓库根目录。

- 完整方案推导与实测记录：[PLAN.md](PLAN.md)
- 参数表来源：`LifeArchiveProject/WeChatDataAnalysis` 的 `tools/key_v4.py` +
  `labazhou2024/chatlog-keeper`，2026-10-20 在微信 **4.1.15.55** 上 22 个库全量验证通过

```
wxchat_export/
  README.md            本文件：方法总览
  PLAN.md              方案推导 + 实测原始记录
  requirements.txt     pycryptodome / psutil / zstandard（jieba 供 analysis 用）
  __main__.py          python -m wxchat_export 打印链路
  probe.py             ① 环境探针（只读）
  verify_key.py        ④ 密钥验证（逐库 page-1 HMAC）
  page.py              SQLCipher 4 页级解密核心
  dump.py              ⑤ 整库解密 CLI
  export.py            schema 勘探 + 任意单表导出
  export_messages.py   ⑤ 消息导出 JSONL
  export_group.py      ⑤ 指定群全量导出 + 昵称映射
  tests/               自洽性测试（加解密互逆、篡改检出）
  analysis/            下游一次性分析脚本（硬编码路径，非通用工具）
```

---

## 一、提取链路（五步）

```
① 环境探针      probe.py          只读：进程 / 安装目录 / Weixin.dll / 各库 size+salt
② 冷备份        （手工 cp）       db + -wal + -shm 三件套一起拷
③ 取 passphrase （外部工具）       见 §三，本目录不含——跟版本漂移的东西不该自己维护
④ 页级解密      dump.py           4096 字节一页，HMAC 先验后解
⑤ 导出          export_messages.py / export_group.py    JSONL / TXT / CSV
```

分工原则：**取密钥用现成活跃项目，解密与导出自己实现**。算法已确定、纯计算、可审计，
上游项目被删库也不影响你手上的库和这个解密器，只需要重新找一次 key。

## 二、加密参数表（实测结论，非推测）

| 参数 | 值 |
|---|---|
| 密码算法 | AES-256-CBC |
| page_size | 4096 |
| KDF | PBKDF2-**HMAC-SHA512**，**256000** 轮 |
| 完整性 | HMAC-SHA512，encrypt-then-MAC |
| salt | 每库文件前 16 字节（明文，22 个库 22 个不同值） |
| mac_salt | `salt` 每字节 XOR **0x3A** |
| dek | `PBKDF2(passphrase, salt, 32, 256000, SHA512)` |
| mac_key | `PBKDF2(dek, mac_salt, 32, **2**, SHA512)` ← 只有 2 轮 |
| reserve | 80 = IV(16) + HMAC(64) |
| 密钥粒度 | 账号级 passphrase，对每库 salt 各自派生 dek |

页布局与还原：

```
page 1:  [ salt 16 ][ ciphertext 4000 ][ IV 16 ][ HMAC 64 ]   = 4096
其他页:  [ ciphertext 4016            ][ IV 16 ][ HMAC 64 ]   = 4096

mac = HMAC-SHA512(mac_key, page[start:4032] || LE32(page_no))   # 末尾 4 字节是小端页码

page 1 明文 = b"SQLite format 3\0" + decrypt(page[16:4016]) + b"\x00"*80
其他页 明文 = decrypt(page[0:4016]) + b"\x00"*80
```

page 1 的头 16 字节被 salt 顶掉了，内容固定，直接写回；末尾 80 字节在明文里是 SQLite
reserved 区，补零即可。**HMAC 必须校验、失败必须中止**——失败意味着密钥或参数错，
静默跳过只会产出一个打不开的库。

## 三、取 passphrase（本目录不含，外部完成）

实测结论：微信 4.1.10.31+ 起密钥不再驻留明文内存，`chatlog-keeper extract-key --method passive`
**失败**。当前可用路径是「静态 XOR key + 只读指针扫描」：

1. `scan.py` 从 `Weixin.dll` 的 `.text` 段静态提 XOR key——特征是连续 4 条
   `48 BA <imm64>`（`mov rdx, imm64`）紧跟 `48 85 C0`（`test rax,rax`），拼出 32 字节。
   实测 195 MB 的 dll 命中 1 处。
2. `key_v4.py` 用 YARA 扫进程内存找 `GetKeyAddrStub` 结构体，从匹配处读 8 字节指针再解引用
   读 32 字节候选。实测 8.6 秒，7615 候选 → 熵筛 1596 → 第 128 个命中。
3. 内存里那 32 字节是**被 XOR 混淆过的**，用第 1 步的 key 还原才是真 passphrase ——
   这就是为什么"密钥不是安装目录里的固定值"。
4. 判别标准只有一个：候选 key 对目标库 page 1 的 HMAC 能否通过（`verify_key.py`）。

关键：**扫结构体指针，不要扫全内存找 32 字节随机数**。后者在几 GB 地址空间里候选爆炸，
且新版明文密钥根本不长驻堆，扫了也扫不到。

取 key 需要 `Weixin.exe` 存活且处于登录态；PID 取内存占用最大的那个（多进程，主进程才持密钥）。

## 四、命令

```bash
pip install -r wxchat_export/requirements.txt

# ① 探针（微信要登录运行）
python -m wxchat_export.probe
python -m wxchat_export.probe --data-root "C:\Users\you\xwechat_files"

# ② 密钥验证：对账号下每个库跑 page-1 HMAC，顺带端到端解最小的库
python -m wxchat_export.verify_key <passphrase_hex> [--xor-key <hex>] --decrypt-smallest

# ③ 解密（有错就报错，不静默）
python -m wxchat_export.dump --db <加密库> --key <hex> [--xor-key <hex>] --out <明文库>

# ④ 导出
python -m wxchat_export.export_messages --db <明文库> --out msgs.jsonl --self-name <你的wxid>
python -m wxchat_export.export_group --name 示例群 --root C:\Users\xxx\wx_dec

# schema 勘探（字段随版本变，先看再导）
python -m wxchat_export.export --db <明文库> --schema

# 自洽性测试（不证明参数对，只证明实现互逆）
python -m wxchat_export.tests.test_roundtrip
```

`export_group` 产出四份：`<群名>.jsonl`（结构化全量）、`<群名>.txt`（原始）、
`<群名>_可读.txt`（XML 压平、按天分段）、`<群名>_members.csv`（成员 + 发言数）。

## 五、4.x 存储结构

```
Name2Id(rowid, user_name, is_session)     rowid 即消息里的 real_sender_id
Msg_<md5(user_name)>                      每个会话一张表，md5 为 utf-8 字符串的 32 位小写 hex
消息列：local_id / server_id / local_type / sort_seq / real_sender_id /
        create_time / message_content / compress_content / WCDB_CT_message_content
```

昵称映射链条：`real_sender_id` → 各分库自己的 `Name2Id.rowid` → `wxid` →
`contact.remark`（备注）> `contact.nick_name`（昵称）> `wxid`。

## 六、踩坑清单（都已在代码里处理）

1. **密钥不再驻留明文内存**。4.1.10.31+ 起 passive 扫描必然 0 命中，别再浪费时间。
2. **群消息分散在多个分库**。同一个群可能在 `message_0.db` 和 `message_1.db` 各有一张
   `Msg_<md5>` 表，两个库的 `Name2Id` 是**独立 id 空间**，跨库混用 rowid 必然错——必须逐库解析。
3. **`text_factory = bytes` 时不能用 `bytes` 绑定参数查 TEXT 列**，SQLite 会按 BLOB 比较
   而永远不相等。用 `str` 绑定，读出来再 decode。这个坑一度让人误判"本地没有该群消息"。
4. **群聊他人消息正文前缀是 `<wxid>: `**，自己的不带。不剥掉会污染内容；而且这个前缀比
   `real_sender_id` 更可靠，能补上 `Name2Id` 里 `user_name` 为空的 id。
5. **系统事件的 `real_sender_id` 指向占位 id**（`Name2Id.user_name` 为空），不是真人。
   判据用"该 rowid 的 user_name 是否为空"，比按 `local_type` 判断更全。
6. **`WCDB_CT_message_content == 4` 表示内容是 zstd 压缩**（魔数 `28 b5 2f fd`）。
   不解压就会把二进制当文本读。解压失败原样保留，不中断导出。
7. **`local_type` 是 64 位复合值**：高 32 位 sub_type，低 32 位主类型。
   `244813135921 == (57<<32)|49`，即 app 消息的引用子类型。按单值查表会得到一堆 `type_244813135921`。
8. **昵称可能被设成纯控制字符**（实测 `\x7f\x7f`），输出前要清洗，并回退到 wxid。
9. **WAL 未合并**。只解 `.db` 会漏掉尚未 checkpoint 的最新消息。WAL 是 32 字节 header +
   若干帧（24 字节帧头 + 4096 字节页），帧头明文，页数据同样加密、但 HMAC 用的是**真实页码**
   而不是帧序号，salt 取 WAL header 的 offset 16..24。当前选择不实现：微信在跑时 WAL 一直变，
   冷备份后整体解一次更划算。

## 七、已验证 / 未实现 / 边界

已验证（微信 4.1.15.55，2026-10-20 本机）：

- 22/22 个库 page-1 HMAC 通过（22 个不同 salt，同一 passphrase）→ 参数表零调整
- `message_1.db` 13.6 MB / 3470 页，0.3 秒解完，`integrity_check = ok`
- 导出 14,343 条消息 / 121 个会话 / 16.2 MB JSONL，表名→wxid 映射 100% 命中
- 4495 条 zstd 压缩内容全部正常解压

未实现：

- WAL 增量合并（见踩坑 9）
- 媒体文件（图片 `.dat` / 语音）——message 库只有引用，需要时用 chatlog-keeper 的 `images`
- 联系人/群名 join 的通用化——`contact.db` 里有，但字段随版本变，按需再写

硬约束：

- 明文库 = 完整隐私。别放网盘、别进 git（`.gitignore` 已挡 `*.db` / `*.jsonl` / `keys/`）。
- 微信运行中直接拷 `.db` 会拿到不一致快照，必须 `-wal` / `-shm` 一起拷。
- 升级过程中不要取 key，等版本目录稳定、`Weixin.dll` 存在再动手。
- 多账号密钥是账号级的，A 的 key 解不开 B 的库。
- 不保证跨大版本可用。参数变了就重跑 §三 的定位流程。

## 八、下游分析

**通用分析走 `wxchat_analysis/`（见仓库根 README），这里是保留的一次性脚本。**

`analysis/` 里是当时为了复现某个口径随手写的脚本，硬编码了本机路径
（`C:\Users\<you>\wx_dec\示例群\示例群.jsonl` 和 `C:\Users\<you>\Desktop\wxchat\out`），
换人换机器要自己改开头几行常量。保留原样，不做通用化。

```
step1_parse.py    解析导出 JSONL → 提取 at / 引用 / 正文，落 out/msgs.pkl
step2_stats.py    基础统计 + @名称映射（含群昵称变更的别名补丁）
step3_names.py    用引用消息里的历史昵称反推 wxid ↔ 昵称，补齐 Name2Id 的缺口
step4_words.py    jieba 分词 + 词频探索
analyze_probe.py  单文件速览：类型分布 / 时间范围 / 发送者分布 / 样本抽样
```

这几个脚本里踩过的坑（POS 过滤、别名反推、系统消息判定）都已经固化进
`wxchat_analysis/` 的 `words.py` / `clean.py` / `schema.py`，新分析直接用库，不要照抄脚本。

`out/` 是产物目录（pkl / json），别进 git。
