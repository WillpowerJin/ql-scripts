#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""京东每日签到（京豆）— 多账号主入口。

cron: 30 8 * * *
new Env('京东签到');

账号配置（二选一，环境变量优先）：
  1) 环境变量 JD_COOKIE = pt_key=xxx;pt_pin=xxx;  多账号用 & 或换行分隔（兼容青龙）
  2) jd/config.yaml（参考 config.example.yaml）

用法：
  python3 jd_sign.py                # 跑配置里启用的全部任务
  python3 jd_sign.py hs ys          # 只跑指定任务
  python3 jd_sign.py --tasks hs,ys,delivery

任务与现状见 README.md。
"""
import argparse
import json
import os
import random
import sys
import time
import urllib.parse

import requests
import yaml

from h5st import SignerPool
from tasks import Journal, TaskRunner, run_task, TASK_LABELS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ALL_TASKS = ["hs", "ys", "delivery", "game", "jxzy", "home", "index"]

DEFAULT_UA = ("jdapp;iPhone;4.2;12.6.3;{uuid};network/wifi;ADID/;model/iPhone13,2;"
              "addressid/0;appBuild/168800;supportApplePay/0;hasUPPay/0;pushNoticeIsOpen/0;"
              "hasOCPay/0;supportBestPay/0;session/;pap/JA2019_3111896;brand/apple;"
              "supportJDSHWK/1;Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148")


# ---------- 配置 ----------
def load_config() -> dict:
    cfg = {}
    path = os.path.join(BASE_DIR, "config.yaml")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    return cfg


def parse_cookies(cfg: dict) -> list:
    """返回 [{pin, cookie, ua}]，环境变量 JD_COOKIE 优先于配置文件。"""
    raw = os.environ.get("JD_COOKIE", "").strip()
    cookies = []
    if raw:
        for part in raw.replace("\n", "&").split("&"):
            part = part.strip()
            if part:
                cookies.append(part)
    else:
        for item in cfg.get("cookies") or []:
            item = str(item).strip()
            if item:
                cookies.append(item)
    accounts = []
    for cookie in cookies:
        pin = _cookie_value(cookie, "pt_pin")
        if not pin or not _cookie_value(cookie, "pt_key"):
            print(f"[跳过] Cookie 缺少 pt_key/pt_pin: {cookie[:30]}…")
            continue
        accounts.append({"pin": pin, "cookie": cookie})
    return accounts


def _cookie_value(cookie: str, name: str) -> str:
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith(name + "="):
            return part[len(name) + 1:]
    return ""


def device_profile(pin: str, cfg: dict) -> dict:
    """每个账号一份稳定的设备身份（UA / uuid 持久化）。"""
    cache_path = os.path.join(BASE_DIR, ".jd_device.json")
    try:
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    if pin not in cache:
        import uuid as _uuid
        cache[pin] = {"uuid": _uuid.uuid4().hex + _uuid.uuid4().hex[:8]}
        tmp = cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(tmp, cache_path)
    ua = cfg.get("user_agent") or DEFAULT_UA.format(uuid=cache[pin]["uuid"])
    return {
        "ua": ua,
        "client": str(cfg.get("client") or "apple"),
        "client_version": str(cfg.get("client_version") or "12.6.3"),
        "eid_token": str(cfg.get("eid_token") or ""),
    }


# ---------- CK 有效性检测 ----------
def check_login(account: dict, ua: str) -> bool:
    """me-api 用户信息只读查询：retcode=0 登录有效，1001 未登录。"""
    try:
        resp = requests.get(
            "https://me-api.jd.com/user_new/info/GetJDUserInfoUnion",
            headers={"Cookie": account["cookie"], "User-Agent": ua},
            timeout=15, allow_redirects=False)
        data = resp.json()
        return str(data.get("retcode")) == "0"
    except Exception:
        return True  # 检测接口本身异常时不阻塞任务


# ---------- Bark 通知（与其它项目共用 BARK_*） ----------
def send_bark(title: str, body: str):
    url = os.environ.get("BARK_URL") or os.environ.get("BARK_PUSH") or ""
    key = os.environ.get("BARK_KEY") or os.environ.get("BARK_DEVICE_KEY") or ""
    server = os.environ.get("BARK_SERVER") or "https://api.day.app"
    group = os.environ.get("BARK_GROUP") or "京东签到"
    if url and not url.startswith("http"):
        key, url = key or url, ""
    endpoint = url.rstrip("/") if url else (f"{server.rstrip('/')}/{key.strip()}" if key else "")
    if not endpoint:
        return
    try:
        requests.post(endpoint, json={"title": title, "body": body, "group": group}, timeout=10)
    except Exception as e:
        print(f"[Bark] 推送失败: {e}")


# ---------- 结果展示 ----------
def result_line(task: str, r: dict) -> str:
    name = TASK_LABELS.get(task, task)
    status = r.get("status", "?")
    if status in ("signed_confirmed", "accepted", "reward_received", "box_confirmed"):
        text = "签到成功"
    elif status == "already_done":
        text = "今天已完成"
    elif status == "partial":
        text = "部分完成"
    elif status == "no_chance":
        text = "暂无机会"
    elif status == "manual_required":
        text = "需要手动前置操作"
    elif status == "rejected":
        text = "请求被拒"
    elif status == "pending":
        text = "已提交，结果待确认"
    else:
        text = "执行未完成"
    if r.get("detail"):
        text += f"（{r['detail']}）"
    if r.get("beanQuantity") and r["beanQuantity"] > 0:
        text += f"，{r['beanQuantity']} 京豆"
    if r.get("couponCount"):
        text += f"，优惠券 {r['couponCount']} 张"
    if r.get("roundDays"):
        text += f"，本轮第 {r['roundDays']} 天"
    return f"{name}: {text}"


def mask_pin(pin: str) -> str:
    p = urllib.parse.unquote(pin)
    return p[:2] + "***" + p[-2:] if len(p) > 4 else "***"


# ---------- 主流程 ----------
def main():
    parser = argparse.ArgumentParser(description="京东每日签到")
    parser.add_argument("tasks", nargs="*", help="只跑指定任务，如: python3 jd_sign.py hs ys")
    parser.add_argument("--tasks", dest="tasks_opt", help="逗号分隔的任务列表")
    args = parser.parse_args()

    cfg = load_config()
    if args.tasks:
        selected = args.tasks
    elif args.tasks_opt:
        selected = [t.strip() for t in args.tasks_opt.split(",") if t.strip()]
    else:
        raw = cfg.get("tasks")
        selected = [t for t, on in (raw or {}).items() if on] if isinstance(raw, dict) else list(ALL_TASKS)
    selected = [t for t in selected if t in TASK_LABELS]
    if not selected:
        print("没有可执行的任务，请检查配置")
        return

    accounts = parse_cookies(cfg)
    if not accounts:
        print("未配置京东 Cookie！请设置环境变量 JD_COOKIE 或编辑 jd/config.yaml")
        sys.exit(1)

    gap = cfg.get("gap_seconds") or [5, 15]
    gap_min, gap_max = int(gap[0]), int(gap[1])
    journal = Journal(os.path.join(BASE_DIR, ".jd_journal.json"))
    pool = SignerPool(os.path.join(BASE_DIR, ".sdk_storage.json"))

    summary = []
    for idx, account in enumerate(accounts):
        pin = account["pin"]
        print(f"\n========== 账号 {idx + 1}/{len(accounts)}: {mask_pin(pin)} ==========")
        profile = device_profile(pin, cfg)
        if not check_login(account, profile["ua"]):
            print("  [×] Cookie 已失效（用户信息查询返回未登录），请重新获取 pt_key/pt_pin")
            summary.append(f"账号{idx + 1}({mask_pin(pin)}): Cookie 失效")
            continue
        account["ua"] = profile["ua"]
        runner = TaskRunner(account, profile, journal, pool)
        for i, task in enumerate(selected):
            if i > 0:
                time.sleep(random.uniform(gap_min, gap_max))
            print(f"  → {TASK_LABELS[task]}")
            try:
                result = run_task(runner, task)
            except Exception as e:
                result = {"status": "stopped", "detail": str(e)}
            line = result_line(task, result)
            print(f"    {line}")
            summary.append(f"账号{idx + 1}: {line}")
        if idx < len(accounts) - 1:
            time.sleep(random.uniform(gap_min, gap_max))

    print("\n========== 汇总 ==========")
    for line in summary:
        print(" ", line)
    send_bark("京东签到结果", "\n".join(summary))


if __name__ == "__main__":
    main()
