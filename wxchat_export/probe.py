"""环境探针：定位进程、DLL、数据库目录。

只做只读探测，不碰内存、不改文件。

    python -m wxchat_export.probe
    python -m wxchat_export.probe --data-root "C:\\Users\\you\\xwechat_files"
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

WECHAT_EXE = "Weixin.exe"
DB_NAMES = ("message_*.db", "contact.db", "session.db", "favorite.db",
            "biz_message_*.db", "sns.db")


def find_pids(name: str = WECHAT_EXE) -> list[tuple[int, int]]:
    """返回 [(pid, 内存字节)]，按内存降序。主进程才持密钥。"""
    try:
        import psutil
    except ImportError:
        return []
    out = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() == name.lower():
                mem = proc.info["memory_info"]
                out.append((proc.info["pid"], mem.rss if mem else 0))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(out, key=lambda x: x[1], reverse=True)


def find_install_dir() -> str | None:
    """注册表优先，退回默认路径。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Tencent\Weixin") as k:
            path, _ = winreg.QueryValueEx(k, "InstallPath")
            if path and os.path.isdir(path):
                return path
    except Exception:  # noqa: BLE001
        pass
    for cand in (r"C:\Program Files\Tencent\Weixin",
                 r"C:\Program Files (x86)\Tencent\Weixin"):
        if os.path.isdir(cand):
            return cand
    return None


def find_weixin_dll(install_dir: str | None) -> tuple[str | None, str | None]:
    """Weixin.exe 只是启动器，真正的 DLL 在 <版本号>\\ 子目录。"""
    if not install_dir:
        return None, None
    versions = []
    for name in os.listdir(install_dir):
        full = os.path.join(install_dir, name)
        dll = os.path.join(full, "Weixin.dll")
        if os.path.isdir(full) and os.path.exists(dll):
            versions.append((name, dll))
    if not versions:
        return None, None

    def vkey(pair: str) -> tuple:
        return tuple(int(x) if x.isdigit() else 0 for x in pair.split("."))

    versions.sort(key=lambda p: vkey(p[0]), reverse=True)
    return versions[0]


def find_accounts(data_root: str) -> list[str]:
    if not os.path.isdir(data_root):
        return []
    return [d for d in glob.glob(os.path.join(data_root, "*"))
            if os.path.isdir(os.path.join(d, "db_storage"))]


def describe_db(path: str) -> str:
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        salt = f.read(16).hex()
    align = size % 4096
    flag = "" if align == 0 else f"  ⚠ 非 4096 对齐(余 {align})"
    wal = " +wal" if os.path.exists(path + "-wal") else ""
    return (f"    {os.path.basename(path):<24} {size/1024/1024:>8.1f} MB"
            f"  salt={salt}{wal}{flag}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="微信 4.x 导出环境探针")
    ap.add_argument("--data-root", default=None, help="xwechat_files 目录")
    args = ap.parse_args(argv)

    print("== 进程 ==")
    pids = find_pids()
    if pids:
        for i, (pid, rss) in enumerate(pids):
            mark = "  <- 主进程（取密钥用它）" if i == 0 else ""
            print(f"  PID {pid:<8} RSS {rss/1024/1024:.0f} MB{mark}")
    else:
        print("  未发现 Weixin.exe（取密钥时必须登录运行）")

    print("\n== 安装目录 ==")
    install = find_install_dir()
    print(f"  {install or '未找到'}")
    ver, dll = find_weixin_dll(install)
    if dll:
        print(f"  版本 {ver}")
        print(f"  DLL {dll}")
    else:
        print("  未找到 Weixin.dll（升级未完成？等版本目录稳定再试）")

    print("\n== 数据目录 ==")
    roots = []
    if args.data_root:
        roots.append(args.data_root)
    else:
        home = os.path.expanduser("~")
        for cand in (os.path.join(home, "xwechat_files"),
                     os.path.join(home, "Documents", "xwechat_files")):
            if os.path.isdir(cand):
                roots.append(cand)
    if not roots:
        print("  未找到 xwechat_files，用 --data-root 指定")
        return 1

    for root in roots:
        print(f"  {root}")
        for acct in find_accounts(root):
            print(f"  账号 {os.path.basename(acct)}")
            db_dir = os.path.join(acct, "db_storage")
            found = 0
            for base in ("message", "contact", "session"):
                d = os.path.join(db_dir, base)
                if not os.path.isdir(d):
                    continue
                for name in DB_NAMES:
                    for path in sorted(glob.glob(os.path.join(d, name))):
                        print(describe_db(path))
                        found += 1
            if not found:
                print("    （未发现已知库文件名，手动 ls 一下 db_storage）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
