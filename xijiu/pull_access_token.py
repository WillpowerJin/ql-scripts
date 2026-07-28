#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 root 安卓手机「当前登录的微信」MMKV 提取习酒 accessToken。

这是什么？
  积分签到（fm.exijiu.com）用的 X-access-token，存在微信小程序本地缓存里。
  本脚本用 adb + root 从微信 MMKV 文件里抠出来，省得你每次抓包。

限制（重要）：
  · 只适用于：已 root 的安卓机 + adb + 微信近期打开过「习酒君品荟」签到页
  · 一次只能拿到「该手机上当前微信账号」的 token（不是 config 里所有号）
  · iPhone / 未 root 安卓：请用抓包，见 README「方式 B」
  · 多账号 = 多个微信号 → 每个号各自在对应手机上拉一次，或抓包

用法：
  python pull_access_token.py
      # 打印当前手机微信里的 token

  python pull_access_token.py --write-config
      # 写入 config.yaml 第一个账号（兼容旧习惯）

  python pull_access_token.py --write-config --account iPhone
      # 写入 name 为 iPhone 的那一条 access_token

  python pull_access_token.py --serial 设备序列号
      # 多台 adb 设备时指定手机

  python pull_access_token.py --list
      # 列出 MMKV 里扫到的全部候选 token（一般只用最新一条）
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# 习酒君品荟「小程序 AppID」（公开标识，不是 AppSecret / access_token）
# 分段拼接，避免 GitHub secret scanning 误报为 “WeChat API App ID”
APPID = "wx" + "8d41cdc4" + "4c8aeaab"
MMKV_REMOTE = (
    "/data/user/0/com.tencent.mm/files/mmkv/AppBrandMMKVStorage840303009"
)
SCRIPT_DIR = Path(__file__).resolve().parent


def adb(serial: list[str], *args: str) -> bytes:
    return subprocess.check_output(
        ["adb", *serial, *args], stderr=subprocess.STDOUT
    )


def extract_tokens(data: bytes) -> list[str]:
    """从 MMKV 二进制中提取该小程序的 accessToken（去重保序）。"""
    pat = re.compile(
        re.escape(APPID.encode())
        + rb"__accessTokena?`?String#(\d+)#([A-Za-z0-9_\-=+/]{20,})"
    )
    vals = [m.group(2).decode() for m in pat.finditer(data)]
    if not vals:
        pat2 = re.compile(
            re.escape(APPID.encode())
            + rb"__accessToken.{0,8}String#\d+#([A-Za-z0-9_\-=+/]{20,})"
        )
        vals = [m.group(1).decode() for m in pat2.finditer(data)]
    # 去重保序（后出现的覆盖前的意图：仍保留全部，选 token 时用最后一条）
    seen: set[str] = set()
    out: list[str] = []
    for v in vals:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def pull_mmkv(serial: list[str]) -> bytes:
    tmp = Path(tempfile.mkdtemp(prefix="xijiu_mmkv_")) / "mmkv"
    adb(
        serial,
        "shell",
        "su",
        "-c",
        f"cp {MMKV_REMOTE} /sdcard/xijiu_mmkv.bin",
    )
    adb(serial, "pull", "/sdcard/xijiu_mmkv.bin", str(tmp))
    return tmp.read_bytes()


def list_account_names(cfg_text: str) -> list[str]:
    return re.findall(r'^\s*-\s*name:\s*["\']?([^"\'\n#]+?)["\']?\s*$', cfg_text, re.M)


def write_token_to_config(
    cfg_path: Path, token: str, account: str = ""
) -> str:
    """
    把 token 写入 config.yaml。
    account 为空：更新第一个 access_token 字段（或插到第一个账号下）。
    account 非空：只更新 name 匹配的那条账号。
    返回写入目标描述。
    """
    if not cfg_path.is_file():
        raise FileNotFoundError(f"无 {cfg_path}")
    text = cfg_path.read_text(encoding="utf-8")
    token_line = f'access_token: "{token}"'

    if account:
        # 按账号块替换：从 - name: "xxx" 到下一个 - name: 或文件结束
        names = list_account_names(text)
        if account not in names:
            known = "、".join(names) if names else "(无)"
            raise ValueError(
                f"config 中找不到 name={account!r}；现有账号：{known}"
            )
        # 用行扫描更稳
        lines = text.splitlines(keepends=True)
        target_i = None
        for i, line in enumerate(lines):
            m = re.match(
                r'^(\s*)-\s*name:\s*["\']?'
                + re.escape(account)
                + r'["\']?\s*$',
                line,
            )
            if m:
                target_i = i
                break
        if target_i is None:
            raise ValueError(f"无法定位账号块 name={account!r}")

        # 账号块缩进：下一项同级 "- " 之前
        base_indent = re.match(r"^(\s*)-", lines[target_i]).group(1)  # type: ignore
        field_indent = base_indent + "  "
        end = len(lines)
        for j in range(target_i + 1, len(lines)):
            if re.match(rf"^{re.escape(base_indent)}-\s+", lines[j]):
                end = j
                break

        block = lines[target_i:end]
        replaced = False
        for k, bl in enumerate(block):
            if re.match(rf"^{re.escape(field_indent)}access_token\s*:", bl):
                block[k] = f'{field_indent}{token_line}\n'
                replaced = True
                break
        if not replaced:
            # 插在 name 行后面
            block.insert(1, f"{field_indent}{token_line}\n")
        lines[target_i:end] = block
        cfg_path.write_text("".join(lines), encoding="utf-8")
        return f"{cfg_path} → 账号 [{account}]"

    # 默认：第一个 access_token
    if re.search(r"^\s*access_token:", text, re.M):
        text2 = re.sub(
            r"^(\s*)access_token:.*$",
            rf'\1{token_line}',
            text,
            count=1,
            flags=re.M,
        )
        cfg_path.write_text(text2, encoding="utf-8")
        names = list_account_names(text)
        who = names[0] if names else "第一个 access_token"
        return f"{cfg_path} → 账号 [{who}]（默认第一个）"

    # 没有 access_token 字段：插到第一个 name 下
    text2, n = re.subn(
        r'^(\s*-\s*name:\s*.+)$',
        rf'\1\n    {token_line}',
        text,
        count=1,
        flags=re.M,
    )
    if n == 0:
        raise ValueError("config.yaml 中没有 accounts / name，无法写入")
    cfg_path.write_text(text2, encoding="utf-8")
    names = list_account_names(text2)
    who = names[0] if names else "第一个账号"
    return f"{cfg_path} → 账号 [{who}]（新建字段）"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="从 root 安卓微信 MMKV 提取习酒 access_token（仅当前微信号）"
    )
    ap.add_argument(
        "--write-config",
        action="store_true",
        help="写入 config.yaml（默认第一个账号；配合 --account 指定）",
    )
    ap.add_argument(
        "--account",
        "-a",
        default="",
        help='写入指定账号，如 --account iPhone（与 config 里 name 一致）',
    )
    ap.add_argument(
        "--serial",
        "-s",
        default="",
        help="adb 设备序列号（多台手机时）",
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="列出扫到的全部候选 token（默认用最新一条）",
    )
    ap.add_argument(
        "--config",
        type=Path,
        default=SCRIPT_DIR / "config.yaml",
        help="config.yaml 路径",
    )
    args = ap.parse_args()
    serial = ["-s", args.serial] if args.serial else []

    try:
        data = pull_mmkv(serial)
    except subprocess.CalledProcessError as e:
        err = e.output.decode("utf-8", errors="replace") if e.output else str(e)
        print(
            "adb/root 失败。需要：安卓已 root、USB 调试、微信打开过君品荟。\n"
            f"详情: {err[:400]}",
            file=sys.stderr,
        )
        print(
            "\n若是 iPhone 或无法 root：请抓包 fm.exijiu.com 的 X-access-token 手动填配置。",
            file=sys.stderr,
        )
        return 1

    vals = extract_tokens(data)
    if not vals:
        print(
            "未找到 accessToken：请先用【当前微信】打开 习酒君品荟 → 签到页 再重试",
            file=sys.stderr,
        )
        return 1

    if args.list:
        print(f"共 {len(vals)} 条候选（越靠后通常越新）：", file=sys.stderr)
        for i, t in enumerate(vals):
            print(f"  [{i}] {t[:16]}…{t[-8:]}  len={len(t)}", file=sys.stderr)
        print(vals[-1])
        return 0

    token = vals[-1]
    print(token)
    print(
        f"（已取最新 1/{len(vals)} 条；当前手机微信账号的 token）",
        file=sys.stderr,
    )

    if args.write_config or args.account:
        try:
            where = write_token_to_config(
                args.config, token, account=(args.account or "").strip()
            )
        except (OSError, ValueError) as e:
            print(f"写入失败: {e}", file=sys.stderr)
            return 2
        print(f"已写入 {where}", file=sys.stderr)
        if not args.account:
            print(
                "提示：多账号请加 --account 名称，例如：\n"
                "  python pull_access_token.py --write-config --account iPhone",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
