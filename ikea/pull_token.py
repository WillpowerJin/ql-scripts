#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从已连接的已 root 安卓手机中自动提取宜家 (IKEA) 登录凭证 Token。

用途：
  宜家会员体系的成长乐园/积分签到使用的是 CIAM 授权 Token，保存在
  /data/data/com.ingka.ikea.app.cn.prod/app_webview/Default/Local Storage/leveldb/ 中。
  本脚本通过 ADB + root 权限直接提取，省去手动抓包的繁琐步骤。

前置要求：
  1. 手机开启 USB 调试并连上电脑，具有 root 权限（Magisk / KernelSU / APatch 等）
  2. 手机上打开过「宜家家居 App」并进入过「积分商城」或「签到赚积分」页面

使用方式：
  python3 ikea/pull_token.py                  # 查看提取到的 Token
  python3 ikea/pull_token.py --write-config   # 自动提取并写入 ikea/config.yaml
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
CONFIG_EXAMPLE_PATH = SCRIPT_DIR / "config.example.yaml"


def run_adb(cmd: list[str], serial: str = "") -> str:
    adb_base = ["adb"]
    if serial:
        adb_base.extend(["-s", serial])
    full_cmd = adb_base + cmd
    try:
        res = subprocess.run(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="latin1",
            errors="ignore",
            check=True,
        )
        return res.stdout
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"ADB 命令执行失败: {' '.join(full_cmd)}\n错误输出: {e.stderr}\n")
        sys.exit(1)


def pull_ikea_token(serial: str = "") -> tuple[str, str, str]:
    """从设备读取并解析 token, party_uid, card_number"""
    # 检查连接设备
    devices_out = run_adb(["devices"])
    lines = [line.strip() for line in devices_out.strip().splitlines()[1:] if line.strip()]
    active_devices = [l.split()[0] for l in lines if "device" in l and "offline" not in l]

    if not active_devices:
        sys.stderr.write("❌ 未检测到已连接的 ADB 设备，请确认手机已开启 USB 调试并连接电脑。\n")
        sys.exit(1)

    target_serial = serial or active_devices[0]

    # 读取 leveldb 中的 log 文件
    shell_cmd = 'cd "/data/data/com.ingka.ikea.app.cn.prod/app_webview/Default/Local Storage/leveldb" && cat *.log'
    out = run_adb(["shell", f"su -c '{shell_cmd}'"], serial=target_serial)

    m_tok = re.search(r"eyJ[A-Za-z0-9_\-\.]+", out)
    m_uid = re.search(r"CIAM[a-f0-9\-]+", out)
    m_card = re.search(r"6275\d{15}", out)

    if not m_tok:
        sys.stderr.write("❌ 未在 App 缓存中找到有效 Token，请在手机上打开宜家 App 并进入「积分商城」后再试。\n")
        sys.exit(1)

    token = m_tok.group(0)
    party_uid = m_uid.group(0) if m_uid else ""
    card_number = m_card.group(0) if m_card else ""

    return token, party_uid, card_number


def write_to_config(token: str, party_uid: str, account_name: str = "主号") -> None:
    try:
        import yaml  # type: ignore
    except ImportError:
        sys.stderr.write("⚠️ 未安装 PyYAML，请先运行: pip install PyYAML\n")
        return

    data = {}
    if CONFIG_PATH.is_file():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}

    if not data and CONFIG_EXAMPLE_PATH.is_file():
        try:
            with CONFIG_EXAMPLE_PATH.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}

    accounts = data.get("accounts") or []
    updated = False
    for acc in accounts:
        if isinstance(acc, dict) and acc.get("name") == account_name:
            acc["token"] = token
            if party_uid:
                acc["party_uid"] = party_uid
            updated = True
            break

    if not updated:
        new_acc = {"name": account_name, "token": token}
        if party_uid:
            new_acc["party_uid"] = party_uid
        accounts.append(new_acc)

    data["accounts"] = accounts

    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    print(f"✅ 已成功将 Token 写入配置文件: {CONFIG_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="宜家 (IKEA) Token 自动提取工具")
    parser.add_argument("--serial", type=str, default="", help="指定 ADB 设备序列号")
    parser.add_argument("--write-config", action="store_true", help="直接写入 ikea/config.yaml")
    parser.add_argument("--account", type=str, default="主号", help="写入配置时的账号名 (默认: 主号)")

    args = parser.parse_args()

    token, party_uid, card_number = pull_ikea_token(serial=args.serial)

    print("==================================================")
    print("🎉 成功从手机提取到宜家登录凭证！")
    print(f"🔑 Token 状态: 有效 (已提取，长度: {len(token)} 字符)")
    if party_uid:
        print(f"👤 用户标识 (PartyUID): 已获取")
    if card_number:
        print(f"💳 会员卡号: 已获取")
    print("==================================================")

    if args.write_config:
        write_to_config(token, party_uid, account_name=args.account)
    else:
        print("\n💡 提示: 若要直接自动保存到配置文件，可运行：")
        print("  python3 ikea/pull_token.py --write-config\n")


if __name__ == "__main__":
    main()
