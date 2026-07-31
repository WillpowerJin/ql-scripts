#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B 站扫码获取 Cookie（青龙 / 本地）

cron: 手动运行（Cookie 失效时）
new Env('B站获取Cookie');

用途：
  用手机 B 站扫码，把 SESSDATA / bili_jct / access_token 写入缓存文件，
  供同目录 daily.py 定时任务读取。日常跑任务时不要挂这个脚本。

青龙：
  1. 订阅本仓库后，任务列表应有 get_cookie.py
  2. 手动运行一次，看日志里的二维码图链接，或 Bark 推送
  3. 手机 B 站扫码确认
  4. 成功后写入 BILI_COOKIE_FILE 或 /ql/data/bilibili_cookie_cache.json
  5. 再跑 daily.py

环境变量（可选）：
  BILI_NAME          账号备注，默认 主号
  BILI_COOKIE_FILE   Cookie 缓存绝对路径
  BARK_URL / BARK_KEY  推送（会带上二维码图片链接）
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from urllib.parse import quote

# 与 daily 同目录
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


logger = logging.getLogger("bili_cookie")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
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

    cfg = load_config(args.config)
    # 通知以环境变量为准（青龙常用）
    env_n = load_notify_from_env()
    if env_n.bark_url or env_n.bark_key:
        cfg.notify = env_n

    name = (args.account or "").strip()
    if name:
        accs = [a for a in cfg.accounts if a.name == name]
        if not accs:
            acc = Account(name=name)
        else:
            acc = accs[0]
    else:
        acc = cfg.accounts[0] if cfg.accounts else Account(name="主号")
    acc.normalize()

    cache = resolve_cache_path()
    logger.info("账号：%s", acc.name)
    logger.info("Cookie 将写入：%s", cache)
    logger.info("")
    logger.info("请用手机【哔哩哔哩 App】扫码（不要用浏览器打开登录链接）")
    logger.info("扫码确认后本任务会自动结束")

    # 包装 show：青龙日志里再推一条带图通知
    interval = 3.0
    poll_times = max(20, int(args.timeout / interval))

    client = BiliClient(acc, cfg)

    # 复用 BiliClient.qr_login，并在展示后推送 Bark
    original_show = show_login_qr

    def show_and_notify(auth_url: str) -> None:
        original_show(auth_url)
        img = (
            "https://api.qrserver.com/v1/create-qr-code/?size=320x320&data="
            + quote(auth_url, safe="")
        )
        body = (
            f"账号：{acc.name}\n"
            f"请用手机 B 站扫码确认登录\n"
            f"二维码图：{img}\n"
            f"保存位置：{cache}"
        )
        # Bark 打开图片
        send_notify(cfg.notify, "B站扫码获取Cookie", body)
        # 再尝试带 url 的推送（部分客户端可点开）
        try:
            if cfg.notify.bark_key or cfg.notify.bark_url:
                from daily import quote as _q  # already imported quote
                import requests

                key = cfg.notify.bark_key
                base = (cfg.notify.bark_url or cfg.notify.bark_server).rstrip("/")
                if key and key not in base:
                    push = f"{base}/{key}"
                else:
                    push = base
                requests.get(
                    f"{push}/{quote('B站扫码')}/{quote('点开看图或看日志二维码')}",
                    params={"url": img, "group": cfg.notify.bark_group or "B站"},
                    timeout=10,
                )
        except Exception as e:
            logger.debug("Bark 图片推送: %s", e)

    # 临时替换展示函数
    import daily as daily_mod

    daily_mod.show_login_qr = show_and_notify

    ok = client.qr_login(poll_times=poll_times, interval=interval)
    daily_mod.show_login_qr = original_show

    if not ok:
        send_notify(
            cfg.notify,
            "B站Cookie获取失败",
            f"账号 {acc.name} 扫码超时或失败，请重试 get_cookie.py",
        )
        print("\n❌ 获取失败，请重新运行本脚本\n")
        return 1

    # 校验
    acc2 = merge_account_credentials(acc)
    client2 = BiliClient(acc2, cfg)
    if not client2.me():
        print("\n⚠️  已写入但校验登录失败，请重试\n")
        return 1

    uname = client2.user.get("uname") or acc.name
    msg = (
        f"✅ 账号 {uname} Cookie 已保存\n"
        f"📁 {cache}\n"
        f"可运行 daily.py 做每日任务"
    )
    print("\n" + msg + "\n")
    send_notify(cfg.notify, "B站Cookie获取成功", msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
