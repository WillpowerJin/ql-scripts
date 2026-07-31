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
  1. 手动运行本任务
  2. 在【任务日志】里找 ASCII 二维码，手机对着屏幕扫
     （同时会 Bark 推送图片链接，可点开再扫）
  3. 手机点确认后日志显示成功
  4. 再跑 daily.py

环境变量（可选）：
  BILI_NAME / BILI_COOKIE_FILE
  BARK_URL / BARK_KEY
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

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


def emit(msg: str = "") -> None:
    """青龙日志靠 stdout；flush 避免缓冲导致「看不到输出」。"""
    print(msg, flush=True)


def main() -> int:
    # 强制打到 stdout，避免青龙只抓 print 或只抓 logging 时漏日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    # 让 daily 模块的 logger 也走到 stdout
    logging.getLogger("bilibili").handlers.clear()
    logging.getLogger("bilibili").addHandler(logging.StreamHandler(sys.stdout))
    logging.getLogger("bilibili").setLevel(logging.INFO)

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
    emit("╔══════════════════════════════════════════╗")
    emit("║     📺  B 站扫码获取 Cookie              ║")
    emit("╚══════════════════════════════════════════╝")
    emit("")

    cfg = load_config(args.config)
    env_n = load_notify_from_env()
    if env_n.bark_url or env_n.bark_key:
        cfg.notify = env_n
        emit("🔔 已配置 Bark，扫码图链接会推送到手机")
    else:
        emit("ℹ️  未配置 BARK_URL/BARK_KEY → 仅日志内二维码（可对着屏幕扫）")

    name = (args.account or "").strip()
    if name:
        accs = [a for a in cfg.accounts if a.name == name]
        acc = accs[0] if accs else Account(name=name)
    else:
        acc = cfg.accounts[0] if cfg.accounts else Account(name="主号")
    acc.normalize()

    cache = resolve_cache_path()
    emit(f"👤 账号备注：{acc.name}")
    emit(f"📁 Cookie 保存：{cache}")
    emit("")
    emit("步骤：打开手机【哔哩哔哩】→ 扫一扫 → 扫日志里的码 → 点确认")
    emit("（不要用浏览器打开 passport 登录链接）")
    emit("")

    interval = 3.0
    poll_times = max(20, int(args.timeout / interval))
    client = BiliClient(acc, cfg)

    def show_and_notify(auth_url: str) -> None:
        # 1) 日志 ASCII 二维码 + 图片链接
        show_login_qr(auth_url)

        img = (
            "https://api.qrserver.com/v1/create-qr-code/?size=320x320&data="
            + quote(auth_url, safe="")
        )
        # 2) Bark（保留）
        has_bark = bool(cfg.notify.bark_key or cfg.notify.bark_url)
        if has_bark:
            body = (
                f"账号：{acc.name}\n"
                f"请用手机 B 站扫码确认\n"
                f"图片：{img}\n"
                f"保存：{cache}"
            )
            send_notify(cfg.notify, "📱 B站扫码获取Cookie", body)
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
                emit("📤 已尝试 Bark 推送（含图片链接）")
            except Exception as e:
                emit(f"⚠️  Bark 图片推送异常: {e}")
        else:
            emit("📤 跳过 Bark（未配置）")

        emit("")
        emit("⏳ 正在等待你扫码确认…")

    import daily as daily_mod

    daily_mod.show_login_qr = show_and_notify

    emit("🌐 正在向 B 站申请登录二维码…")
    t0 = time.time()
    ok = client.qr_login(poll_times=poll_times, interval=interval)
    daily_mod.show_login_qr = show_login_qr  # 还原

    if not ok:
        emit("")
        emit("❌ 获取失败：超时未确认，或二维码已失效")
        emit("👉 请重新运行本脚本再扫一次")
        emit("")
        send_notify(
            cfg.notify,
            "❌ B站Cookie获取失败",
            f"账号 {acc.name} 扫码超时或失败，请重试 get_cookie.py",
        )
        return 1

    emit("")
    emit("🔍 校验登录状态…")
    acc2 = merge_account_credentials(acc)
    client2 = BiliClient(acc2, cfg)
    if not client2.me():
        emit("")
        emit("⚠️  Cookie 已写入，但校验登录失败，请重试扫码")
        emit(f"📁 {cache}")
        emit("")
        return 1

    uname = client2.user.get("uname") or acc.name
    mid = client2.user.get("mid") or ""
    elapsed = int(time.time() - t0)
    emit("")
    emit("╔══════════════════════════════════════════╗")
    emit("║  ✅  Cookie 获取成功                     ║")
    emit("╚══════════════════════════════════════════╝")
    emit(f"👤 用户：{uname}" + (f" (mid={mid})" if mid else ""))
    emit(f"📁 已保存：{cache}")
    emit(f"⏱️  耗时：约 {elapsed} 秒")
    emit("")
    emit("👉 下一步：运行 daily.py（或等定时任务）做每日任务")
    emit("   本地：uv run daily.py")
    emit("   青龙：手动/定时跑 bilibili/daily.py")
    emit("")

    send_notify(
        cfg.notify,
        "✅ B站Cookie获取成功",
        f"用户：{uname}\n保存：{cache}\n可运行 daily.py",
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⚠️  用户中断\n", flush=True)
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ 未捕获异常: {e}\n", flush=True)
        logging.exception("get_cookie 失败")
        sys.exit(1)
