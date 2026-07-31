#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B 站扫码获取 Cookie（青龙 / 本地）

cron: 手动运行（Cookie 失效时）
new Env('B站获取Cookie');

用途：
  手机 B 站扫码 → 写入 Cookie 缓存 → daily.py 定时任务读取。
  日常跑任务请用 daily.py，不要每天挂本脚本。

青龙：
  1. 手动运行 / 脚本调试本任务
  2. 在日志里找 ASCII 二维码，手机对着屏幕扫
     （配置了 Bark 时会再推图片链接）
  3. 手机点确认后日志显示成功
  4. 再跑 daily.py

环境变量（可选）：
  BILI_NAME / BILI_COOKIE_FILE
  BARK_URL / BARK_KEY

依赖：requests cryptography qrcode Pillow（可选 PyYAML）
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 尽早打日志：青龙「脚本调试」若 import 失败，以前会整段无输出
# ---------------------------------------------------------------------------
import sys
import os
import traceback
from pathlib import Path

# 无缓冲，避免青龙只看到空白
os.environ.setdefault("PYTHONUNBUFFERED", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)  # type: ignore[attr-defined]
except Exception:
    pass


def emit(msg: str = "") -> None:
    """
    写 stdout（flush）。
    在青龙环境再抄一份到 stderr：部分「脚本调试」只采 stderr 或只采其一。
    本地交互终端只写 stdout，避免重复两行。
    """
    line = "\n" if msg == "" else (msg if msg.endswith("\n") else msg + "\n")
    try:
        sys.stdout.write(line)
        sys.stdout.flush()
    except Exception:
        pass
    in_ql = bool(
        os.environ.get("QL_DIR")
        or os.environ.get("QL_DATA_DIR")
        or Path("/ql/data").is_dir()
    )
    if in_ql:
        try:
            sys.stderr.write(line)
            sys.stderr.flush()
        except Exception:
            pass


emit("[get_cookie] start")
emit(f"[get_cookie] python={sys.version.split()[0]}  file={__file__}")

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
emit(f"[get_cookie] script_dir={SCRIPT_DIR}")

# 延迟导入 daily，失败时一定有中文提示
try:
    from daily import (  # noqa: E402
        Account,
        BiliClient,
        load_config,
        load_notify_from_env,
        merge_account_credentials,
        resolve_cache_path,
        send_notify,
        show_login_qr,
    )

    emit("[get_cookie] import daily OK")
except Exception as e:
    emit("")
    emit("❌ 无法导入同目录 daily.py / 依赖未装全")
    emit(f"   错误: {type(e).__name__}: {e}")
    emit("")
    emit("请在青龙「依赖管理」安装：")
    emit("  requests  cryptography  qrcode  Pillow  PyYAML")
    emit("")
    emit("并确认订阅已拉取 bilibili/daily.py（与 get_cookie.py 同目录）")
    emit(f"   当前目录文件: {list(SCRIPT_DIR.glob('*.py'))}")
    emit("")
    traceback.print_exc(file=sys.stderr)
    traceback.print_exc(file=sys.stdout)
    sys.exit(2)

import argparse  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402
from urllib.parse import quote  # noqa: E402


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    # daily 内部 logger → stdout
    blog = logging.getLogger("bilibili")
    blog.handlers.clear()
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    blog.addHandler(h)
    blog.setLevel(logging.INFO)
    blog.propagate = False

    ap = argparse.ArgumentParser(description="B 站扫码获取 Cookie")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--account", default="", help="账号 name，默认第一个或「主号」")
    ap.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="等待扫码秒数，默认 180",
    )
    args = ap.parse_args()

    emit("")
    emit("=" * 44)
    emit("  Bilibili get_cookie  (扫码获取 Cookie)")
    emit("=" * 44)
    emit("")

    try:
        cfg = load_config(args.config)
    except Exception as e:
        emit(f"⚠️  load_config 失败，使用默认账号: {e}")
        from daily import AppConfig

        cfg = AppConfig(accounts=[Account(name="主号")])

    env_n = load_notify_from_env()
    if env_n.bark_url or env_n.bark_key:
        cfg.notify = env_n
        emit("[*] Bark 已配置，扫码图链接会推送")
    else:
        emit("[*] 未配置 BARK_URL/BARK_KEY，仅日志内二维码")

    name = (args.account or os.environ.get("BILI_NAME") or "").strip()
    if name:
        accs = [a for a in cfg.accounts if a.name == name]
        acc = accs[0] if accs else Account(name=name)
    else:
        acc = cfg.accounts[0] if cfg.accounts else Account(name="主号")
    acc.normalize()

    cache = resolve_cache_path()
    emit(f"[*] 账号备注: {acc.name}")
    emit(f"[*] Cookie 保存: {cache}")
    emit("")
    emit("步骤: 手机打开 哔哩哔哩 -> 扫一扫 -> 扫日志里的码 -> 点确认")
    emit("不要用电脑浏览器打开 passport 登录链接")
    emit("")

    interval = 3.0
    poll_times = max(20, int(args.timeout / interval))
    client = BiliClient(acc, cfg)

    def show_and_notify(auth_url: str) -> None:
        emit("[*] 已拿到 auth 链接，开始输出二维码…")
        show_login_qr(auth_url)

        img = (
            "https://api.qrserver.com/v1/create-qr-code/?size=320x320&data="
            + quote(auth_url, safe="")
        )
        has_bark = bool(cfg.notify.bark_key or cfg.notify.bark_url)
        if has_bark:
            body = (
                f"账号：{acc.name}\n"
                f"请用手机 B 站扫码确认\n"
                f"图片：{img}\n"
                f"保存：{cache}"
            )
            try:
                send_notify(cfg.notify, "B站扫码获取Cookie", body)
            except Exception as e:
                emit(f"[!] send_notify 失败: {e}")
            try:
                import requests

                key = cfg.notify.bark_key
                base = (cfg.notify.bark_url or cfg.notify.bark_server).rstrip("/")
                if key and key not in base:
                    push = f"{base}/{key}"
                else:
                    push = base
                requests.get(
                    f"{push}/{quote('B站扫码')}/{quote('点开图片或看青龙日志二维码')}",
                    params={
                        "url": img,
                        "group": cfg.notify.bark_group or "B站",
                    },
                    timeout=10,
                )
                emit("[*] Bark 已推送（含图片链接）")
            except Exception as e:
                emit(f"[!] Bark 推送异常: {e}")
        else:
            emit("[*] 跳过 Bark（未配置）")

        emit("")
        emit("[*] 等待扫码确认中…（请看上方二维码）")

    import daily as daily_mod

    daily_mod.show_login_qr = show_and_notify

    emit("[*] 正在请求 B 站登录二维码…")
    t0 = time.time()
    try:
        ok = client.qr_login(poll_times=poll_times, interval=interval)
    except Exception as e:
        emit(f"❌ qr_login 异常: {e}")
        traceback.print_exc(file=sys.stdout)
        return 1
    finally:
        daily_mod.show_login_qr = show_login_qr

    if not ok:
        emit("")
        emit("❌ 获取失败：超时未确认或二维码失效")
        emit("👉 请重新运行本脚本")
        emit("")
        try:
            send_notify(
                cfg.notify,
                "B站Cookie获取失败",
                f"账号 {acc.name} 扫码超时或失败",
            )
        except Exception:
            pass
        return 1

    emit("")
    emit("[*] 校验登录…")
    acc2 = merge_account_credentials(acc)
    client2 = BiliClient(acc2, cfg)
    if not client2.me():
        emit("")
        emit("⚠️ Cookie 已写入，但校验登录失败，请重试")
        emit(f"   路径: {cache}")
        emit("")
        return 1

    uname = client2.user.get("uname") or acc.name
    mid = client2.user.get("mid") or ""
    elapsed = int(time.time() - t0)
    emit("")
    emit("=" * 44)
    emit("  OK  Cookie 获取成功")
    emit("=" * 44)
    emit(f"用户: {uname}" + (f"  mid={mid}" if mid else ""))
    emit(f"保存: {cache}")
    emit(f"耗时: 约 {elapsed}s")
    emit("")
    emit("下一步: 运行 daily.py 做每日任务")
    emit("")

    try:
        send_notify(
            cfg.notify,
            "B站Cookie获取成功",
            f"用户：{uname}\n保存：{cache}\n可运行 daily.py",
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        code = main()
        emit(f"[get_cookie] exit={code}")
        sys.exit(code)
    except SystemExit:
        raise
    except Exception as e:
        emit("")
        emit(f"❌ 未捕获异常: {type(e).__name__}: {e}")
        traceback.print_exc(file=sys.stdout)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
