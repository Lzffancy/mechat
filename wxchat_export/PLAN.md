# 微信 4.x 本地聊天记录导出方案

目标：在你自己的机器上，把 4.1.15.55 的本地聊天库解成明文 SQLite，导出可长期保存的 JSONL。
不联网、不上传、不改动原库。

---

## 0. 路线判断（先说结论）

**不要从零逆向取密钥。** 那是整个链路里最脆、最需要跟版本的部分，自己做等于每年重写一次。

正确分工：

| 环节 | 谁做 | 理由 |
|---|---|---|
| 取密钥 | 用现成活跃项目（chatlog-keeper / WeChatDataAnalysis） | 特征码随版本漂移，跟版成本高 |
| 解密 | 自己实现 | 算法已完全确定，纯计算，不会消失，可审计 |
| 导出 | 自己实现 | 字段映射要按你的用途定制 |

这样即使上游项目明天被删库，你手上的明文库和解密器还在，只需要重新找一次 key。

---

## 1. 已实测的环境事实

| 项 | 值 |
|---|---|
| 客户端 | `C:\Program Files\Tencent\Weixin\Weixin.exe`，版本 **4.1.15.55** |
| DLL | `C:\Program Files\Tencent\Weixin\4.1.15.55\Weixin.dll` |
| 数据根目录 | `C:\Users\<you>\xwechat_files\wxid_xxxxxxxxxxxxxxxx_xxxx\` |
| 库目录 | `db_storage/`（message / contact / session / favorite / sns / emoticon / head_image / bizchat …） |
| 主消息库 | `db_storage/message/message_0.db` — 152,264,704 B，**4096 对齐** |
| 另一大库 | `db_storage/message/biz_message_0.db` — 145,702,912 B |
| 页大小验证 | 两个库 size % 4096 == 0 → page_size = 4096 成立 |
| salt 独立性 | message_0.db 头 16B = `35a671dac48f7c1f4a7cb6e6396d285b`；contact.db = `2cc35b9d048e1e3e179a2e0d83dd926a` → **每库独立 salt** |
| WAL | 每个 db 都有 `-wal` / `-shm` / `-first.material` / `-last.material` |
| 运行状态 | 微信当前运行中（message_0.db 持续写入） |

`35 a6 71 da …` 是 salt，不是 SQLite header。第 17 字节起才是密文。

---

---

## 2. 加密参数表（实测逆向结论，非推测）

来源：`LifeArchiveProject/WeChatDataAnalysis` 的 `tools/key_v4.py`（4.1.13.12 实测通过）+
`labazhou2024/chatlog-keeper`（4.1.10.31+ 支持）。两处结论一致。

**2026-10-20 已在微信 4.1.15.55 全量验证：22 个库、22 个不同 salt，同一 passphrase 全部 HMAC 通过。**

| 参数 | 值 |
|---|---|
| 密码算法 | AES-256-CBC |
| page_size | 4096 |
| KDF | PBKDF2-**HMAC-SHA512**，**256000** 轮 |
| 完整性 | HMAC-SHA512，encrypt-then-MAC |
| salt | 每库文件前 16 字节（明文） |
| mac_salt | `salt` 每字节 XOR **0x3A** |
| dek（数据密钥） | `PBKDF2(passphrase, salt, 32, 256000, SHA512)` |
| mac_key | `PBKDF2(dek, mac_salt, 32, 2, SHA512)` ← 只有 2 轮 |
| reserve | 80 = IV(16) + HMAC(64) |
| 密钥粒度 | **账号级 passphrase**，对每库 salt 各自派生 dek |

页布局（密文状态）：

```
page 1:  [ salt 16 ][ ciphertext 4000 ][ IV 16 ][ HMAC 64 ]   = 4096
其他页:  [ ciphertext 4016            ][ IV 16 ][ HMAC 64 ]   = 4096
```

HMAC 覆盖范围 = `ciphertext || IV` 再追加 4 字节小端页码：

```
mac = HMAC-SHA512(mac_key, page[start : 4032] || LE32(page_no))
page[4032 : 4096] == mac
```

明文还原：

```
page 1 = b"SQLite format 3\0" + decrypt(page[16:4016]) + b"\x00" * 80
其他页 = decrypt(page[0:4016]) + b"\x00" * 80
```

第一页那 16 字节 header 是被 salt 顶掉的，内容固定，直接写回去。末尾 80 字节在明文里是 SQLite 的 reserved 区，补零即可。

---

## 3. 执行阶段

```
Phase 0  环境探针 + 冷备份         5 min    只读
   ↓
Phase 1  取 passphrase            10-40 min  现成工具 / 或按 §5 自己写
   ↓
Phase 2  页级解密 → 明文 SQLite    2 min    本仓库 wxchat_export/
   ↓
Phase 3  schema 勘探 + 导出 JSONL  30 min   本仓库 wxchat_export/export.py
   ↓
Phase 4  WAL 增量补齐            可选     见 §7
```

---

## 4. Phase 0：先做两件事

**4.1 冷备份三件套。** 在解密前把 `db` + `-wal` + `-shm` 一起复制走，别只拷 db。

```bash
mkdir -p ~/wx_backup/message
cp db_storage/message/message_0.db{,-wal,-shm} ~/wx_backup/message/
```

微信运行中拷 db 会得到不一致的快照（WAL 里有未 checkpoint 的页），所以三件套必须整套。

**4.2 确认微信在跑。** 取 key 需要目标进程存活且处于登录态。PID 取内存占用最大的那个 `Weixin.exe`——微信是多进程，主进程才持有密钥。

---

## 5. Phase 1：取 passphrase

### 方案 A：chatlog-keeper（推荐先试）

`labazhou2024/chatlog-keeper`，Python 3.9+，MIT，84★，2026-10 仍周级更新，是目前对 4.1.10.31+ 覆盖最好的。

```bash
git clone https://github.com/labazhou2024/chatlog-keeper.git
cd chatlog-keeper && python -m pip install .

python -m chatlog_keeper.cli probe
python -m chatlog_keeper.cli extract-key --source wechat --method passive
# 0 命中再转 active（它会拉起调试态子进程，风险见 §6）
python -m chatlog_keeper.cli extract-key --source wechat --method active \
  --data-root "C:\Users\<you>\xwechat_files"
```

拿到后自己接管：

```bash
python -m chatlog_keeper.cli set-key --source wechat --key-stdin   # 粘贴 64 hex
```

密钥缓存在 `%LOCALAPPDATA%\chatlog-keeper\data\secrets\`，之后离线也能复用。

### 方案 B：WeChatDataAnalysis 的只读扫描

`LifeArchiveProject/WeChatDataAnalysis`，3784★，2026-10-19 还在推。它的 `tools/scan.py` + `tools/key_v4.py` 走的是另一条路，比盲目扫堆内存精准：

1. `scan.py` 从 `Weixin.dll` 的 `.text` 段静态提取 XOR key。特征是连续 4 条 `48 BA <imm64>`（即 `mov rdx, imm64`）紧跟 `48 85 C0`（`test rax,rax`），拼出 32 字节。
2. `key_v4.py` 用 YARA 规则扫进程内存找 `GetKeyAddrStub` 结构体（特征 `??×6 00×10 20 00 00 00 00 00 00 00 2f 00 00 00 00 00 00 00`），从匹配处读 8 字节指针，再解引用读 32 字节候选。
3. 候选过熵筛（相异字节 ≥15、可打印字符 ≤24），再用目标库第一页跑 §2 的 HMAC 校验。
4. 内存里那 32 字节通常是**被 XOR 混淆过的**，用步骤 1 的 key 还原才是真 passphrase——这就是为什么"密钥不是配置里的固定值"。

关键点：**扫结构体指针，不要扫全内存找 32 字节随机数**。后者在几个 GB 的地址空间里候选爆炸，而且 4.1.10.31+ 之后明文密钥不再长驻堆，直接扫根本扫不到。

### 方案 C：两套都不中

说明这个版本的驻留位置又变了。退路是按 §5 思路自己定位：找 `Weixin.dll` 里调用 WCDB cipher-config 的位置，下断点抓参数。这条是最后手段，工作量大。

---

## 6. Phase 2：解密

```bash
pip install pycryptodome

python -m wxchat_export.dump \
  --db "C:\Users\<you>\wxchat_backup\message\message_0.db" \
  --key <64位hex或32字节passphrase> \
  --xor-key <可选，scan.py 提取的 XOR key> \
  --out "C:\Users\<you>\wxchat_decrypted\message_0.db"
```

实现要点（`wxchat_export/page.py`）：

- 逐页流式处理，峰值内存 ≈ 1 页，152MB 库不吃内存
- 每页先校验 HMAC 再解密，**任何一页校验失败立即中止**，不要静默跳过——失败意味着密钥错或参数错
- page 1 解密后前 16 字节必须等于 `b"SQLite format 3\0"`，这是第二道自检
- 输出文件用标准 `sqlite3` 可直接打开

跑完验证：

```bash
python -c "import sqlite3;c=sqlite3.connect(r'...\message_0.db');print(c.execute('pragma integrity_check').fetchone())"
```

期望 `('ok',)`。

---

## 7. Phase 4：WAL（可选但重要）

字面库是 checkpoint 之后的状态。微信运行时最新消息还压在 `-wal` 里，只解 db 会漏掉最近的。

两个选择：

1. **省事**：先用 chatlog-keeper 导出一次，它已经把 WAL 帧按 HMAC 校验后合并了。
2. **自己补**：WAL 格式是 32 字节 header + 若干帧（24 字节帧头 + 4096 字节页数据）。帧头明文，页数据按 §2 同样方式加密，但 HMAC 用的是**真实页码**而不是帧序号。salt 取 WAL header 的 offset 16..24。

本仓库先不实现 WAL 合并，留了接口位。原因：微信在跑的时候 WAL 一直在变，做增量合并的收益不如直接冷备份后整体解一次。

---

## 8. 风险与边界

**账号风险**

| 动作 | 风险 |
|---|---|
| 读本地 db 文件 | 接近 0，服务端不可见 |
| 只读扫内存取 key | 低，无注入无 hook |
| 调试器启动微信取 key | 中高，会拉起调试态子进程，需手机重新确认 |

前两个能做就做，第三个只在必须时用。真正的封号触发点是服务端异常行为（批量加好友、模拟发消息、多开改包），本地读数据不在那个范围内。

腾讯的实际处置对象是**代码托管平台上的仓库**（DMCA），不是用户账号。2025-10-20 那天 chatlog（9.2k★）和 PyWxDump（9.6k★）同时被清空，就是项目级风险，不是用户级风险。这也是为什么本方案坚持"解密层自己做"。

**其他**

- 解出来的明文库 = 完整隐私，别放网盘、别进 git。`.gitignore` 里加上 `*.db`、`*.jsonl`、`keys/`。
- 不要在微信升级过程中取 key。等版本目录稳定、`Weixin.dll` 存在再动手（有人踩过：退出微信触发自动升级，dll 一度不存在）。
- 多账号时密钥是账号级的，A 的 key 解不开 B 的库，需要各取一次。
- PC 端本地历史不会自动从服务器全量拉取。新登录账号本地近乎空，历史要先从手机「聊天记录迁移」过来。

---

## 9. 实测结果（微信 4.1.15.55，2026-10-20 本机）

全链路已跑通，参数表在 4.1.15.55 上**完全成立**。

**取密钥**

| 步骤 | 结果 |
|---|---|
| §5 方案 A（chatlog-keeper `--method passive`） | **失败**，`passive scan found no key`，与 4.1.10.31+ 的设计变化一致 |
| `scan.py` 静态提取 XOR key | **成功**，从 `Weixin.dll`（195 MB）命中 1 处，VA `0x18037C7B5`，文件偏移 `0x37BBB5` |
| `key_v4.py` 只读指针扫描 | **成功，8.6 秒**：7615 个原始候选 → 熵筛后 1596 个 → 第 128 个命中 |
| 校验 | 用 `contact.db` 的 page 1 HMAC 判定，一次通过 |

**参数验证**

用同一 passphrase 对账号下全部 22 个库跑 `check_page1`：

```
22/22 个库 HMAC 校验通过
contact / contact_fts / emoticon / favorite / favorite_fts / general / hardlink /
head_image / biz_message_0 / media_0 / media_1 / message_0 / message_1 /
message_fts / message_resource / weclaw / session / sns / solitaire / third_app_icon ...
```

22 个库 22 个不同 salt，全部通过 —— §2 的参数表没有任何一项需要调整。

**解密与导出**

- `message_1.db` 13.6 MB / 3470 页，0.3 秒解完，`pragma integrity_check = ok`
- 导出 **14,343 条消息 / 121 个会话 / 16.2 MB JSONL**，表名到 wxid 的映射 100% 命中
- 其中 4495 条内容需要 zstd 解压，全部解压正常

**4.x 存储结构（实测补充 §3 的空白）**

```
Name2Id(rowid, user_name, is_session)      rowid 即消息里的 real_sender_id
Msg_<md5(user_name)>                       每个会话一张表，md5 为 utf-8 字符串的 32 位小写 hex
消息列：local_id / server_id / local_type / sort_seq / real_sender_id /
        create_time / message_content / compress_content / WCDB_CT_message_content
```

三个容易踩的点：

1. `WCDB_CT_message_content == 4` 表示 `message_content` 是 **zstd 压缩**（魔数 `28 b5 2f fd`）。不解压就会把二进制当文本读。
2. `local_type` 是 **64 位复合值**：高 32 位 sub_type，低 32 位主类型。`244813135921 == (57<<32)|49`，即 app 消息的引用子类型。按单值查表会得到一堆 `type_244813135921`。
3. 表名反查要自己算 md5，`sqlite_master` 里那 121 张 `Msg_*` 表名本身不带账号信息。

**能力边界**

`message_1.db` 只是分库之一。`message_0.db`（145 MB）和 `biz_message_0.db`（139 MB）量级更大，同一流程直接套用即可。WAL 仍未合并，最近几小时的消息可能还在 `-wal` 里。

---

## 10. 这个方案不做什么

- 不碰别人账号的数据
- 不做服务端自动化（那才是封号区）
- 不打包分发、不做 GUI——自用脚本，越少暴露越久
- 不保证跨大版本可用。4.1.15 的参数下次升级可能就变，届时重跑 §5 定位
