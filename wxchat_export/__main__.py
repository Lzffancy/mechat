"""`python -m wxchat_export` —— 打印提取链路和当前环境状态，不做事。

    python -m wxchat_export
"""

from __future__ import annotations

from . import __version__

STEPS = [
    ("① 探针", "python -m wxchat_export.probe", "只读：进程 / Weixin.dll / 各库 size+salt"),
    ("② 备份", "cp db{,-wal,-shm} <备份目录>", "三件套必须整套，否则快照不一致"),
    ("③ 取密钥", "（外部：scan.py + key_v4.py）", "见 README §三，本目录不含"),
    ("④ 验证", "python -m wxchat_export.verify_key <hex> --decrypt-smallest", "page-1 HMAC 逐库判定"),
    ("⑤ 解密", "python -m wxchat_export.dump --db X --key <hex> --out Y", "先验 HMAC 再解，失败即中止"),
    ("⑥ 导出", "python -m wxchat_export.export_messages --db Y --out Z.jsonl", "或 export_group 导整群"),
]


def main() -> int:
    print(f"wxchat_export {__version__} —— 微信 4.x 本地库解密与导出\n")
    for name, cmd, note in STEPS:
        print(f"{name:<8} {cmd}")
        print(f"{'':<8} └ {note}")
    print("\n详细方法、参数表与踩坑见 README.md；方案推导见 PLAN.md。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
