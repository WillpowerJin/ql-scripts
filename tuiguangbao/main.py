#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
推广宝自动看广告领奖

cron: 0 9 * * *
new Env('推广宝每日广告');

策略：
  1. 账号密码登录获取 Cookie
  2. 绑定邀请码（可选）
  3. 循环看广告并领奖
  4. 执行结束后统一 Bark 汇总推送

青龙环境变量（账号）：
  TGB_ACCOUNTS  推荐。JSON 数组，支持 name 备注，多账号
  或 TGB = 手机号#密码，一行一个账号（& 分隔多账号）
  或下列按索引对齐的变量（& 分隔多账号）：
    TGB_USER / TGB_PASS / TGB_NAME（可选）

青龙环境变量（Bark 通知）：
  BARK_URL   完整推送地址，如 https://api.day.app/你的Key/
  或 BARK_KEY + 可选 BARK_SERVER（默认 https://api.day.app）
  可选：BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL

其他环境变量：
  TGB_INVITE_CODE          邀请码（默认 000GHFAV）
  TGB_TIMEOUT              请求超时秒数（默认 15）
  TGB_MAX_RETRIES          网络错误重试次数（默认 3）
  TGB_RETRY_INTERVAL       重试间隔秒（默认 10）
  TGB_AD_WATCH_SECONDS     广告模拟观看秒数（默认 22）
  TGB_INTER_ACCOUNT_DELAY  账号间隔秒（默认 6）

依赖：requests
  青龙：依赖管理里添加 requests
  本地 yaml 配置可选：再装 PyYAML
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 16; V2426A Build/BP2A.250605.031.A3_V000L1; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/134.0.6998.135 "
    "Mobile Safari/537.36 TuiGuangBaoAndroid/1.0.2"
)
DEFAULT_BARK_SERVER = "https://api.day.app"
DEFAULT_INVITE_CODE = "000GHFAV"
SCRIPT_DIR = Path(__file__).resolve().parent

BASE_PLUGIN = "https://tg.suewammes.com/plugin.php?id=view&modac=sign"
LOGIN_URL = "https://tg.suewammes.com/member.php?mod=logging&action=login&loginsubmit=yes&mobile=2"
BIND_YQ_URL = "https://tg.suewammes.com/plugin.php?id=xigua_hh:bindcode"
LOGIN_PAGE_URL = "https://tg.suewammes.com/member.php?mod=logging&action=login&mobile=2"

logger = logging.getLogger("tuiguangbao")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    phone: str
    password: str


@dataclass
class NotifyConfig:
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = "推广宝"
    bark_sound: str = ""
    bark_icon: str = ""
    bark_level: str = ""

    def enabled(self) -> bool:
        return bool(self.bark_url or self.bark_key)


@dataclass
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    invite_code: str = DEFAULT_INVITE_CODE
    timeout: int = 15
    max_retries: int = 3
    retry_interval: int = 10
    ad_watch_seconds: int = 22
    inter_account_delay: int = 6
    user_agent: str = DEFAULT_UA
    notify: NotifyConfig = field(default_factory=NotifyConfig)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _split_multi(value: str) -> list[str]:
    """青龙多账号：用 & 或换行分隔。"""
    if not value:
        return []
    return [x.strip() for x in re.split(r"[&\n]", value) if x.strip()]


def _parse_accounts_json(raw: str) -> list[Account]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("TGB_ACCOUNTS 必须是 JSON 数组")

    accounts: list[Account] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"TGB_ACCOUNTS[{i}] 必须是对象")
        phone = str(item.get("phone") or item.get("username") or item.get("user") or "")
        pwd = str(item.get("password") or item.get("pwd") or item.get("pass") or "")
        if not phone or not pwd:
            raise ValueError(f"TGB_ACCOUNTS[{i}] 缺少手机号或密码")
        accounts.append(
            Account(name=str(item.get("name") or phone), phone=phone, password=pwd)
        )
    return accounts


def _parse_accounts_from_env() -> list[Account]:
    accounts: list[Account] = []

    # 1) JSON（推荐）
    accounts_json = _env("TGB_ACCOUNTS")
    if accounts_json:
        accounts.extend(_parse_accounts_json(accounts_json))
        return accounts

    # 2) TGB 单行/多行
    tgb = _env("TGB")
    if tgb:
        for line in _split_multi(tgb):
            parts = line.split("#", 1)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ValueError(f"TGB 格式错误：{line}，应为 手机号#密码")
            phone, pwd = parts
            accounts.append(Account(name=phone.strip(), phone=phone.strip(), password=pwd.strip()))
        return accounts

    # 3) 按索引对齐
    users = _split_multi(_env("TGB_USER") or _env("TGB_USERNAME"))
    passes = _split_multi(_env("TGB_PASS") or _env("TGB_PASSWORD"))
    names = _split_multi(_env("TGB_NAME"))
    n = max(len(users), len(passes))
    if n > 0:
        for i in range(n):
            phone = users[i] if i < len(users) else ""
            pwd = passes[i] if i < len(passes) else ""
            if not phone or not pwd:
                raise ValueError(f"TGB_USER/TGB_PASS 第 {i + 1} 个账号信息不完整")
            accounts.append(
                Account(name=names[i] if i < len(names) else phone, phone=phone, password=pwd)
            )
        return accounts

    return accounts


def load_notify_from_env() -> NotifyConfig:
    bark_url = _env("BARK_URL") or _env("BARK_PUSH")
    bark_key = _env("BARK_KEY") or _env("BARK_DEVICE_KEY")

    if bark_url and not bark_url.startswith("http"):
        bark_key = bark_key or bark_url
        bark_url = ""

    return NotifyConfig(
        bark_url=bark_url,
        bark_key=bark_key,
        bark_server=_env("BARK_SERVER", DEFAULT_BARK_SERVER).rstrip("/"),
        bark_group=_env("BARK_GROUP", "推广宝"),
        bark_sound=_env("BARK_SOUND"),
        bark_icon=_env("BARK_ICON"),
        bark_level=_env("BARK_LEVEL"),
    )


def load_config_from_env() -> Optional[AppConfig]:
    accounts = _parse_accounts_from_env()
    if not accounts:
        return None

    return AppConfig(
        accounts=accounts,
        invite_code=_env("TGB_INVITE_CODE", DEFAULT_INVITE_CODE),
        timeout=int(_env("TGB_TIMEOUT", "15")),
        max_retries=int(_env("TGB_MAX_RETRIES", "3")),
        retry_interval=int(_env("TGB_RETRY_INTERVAL", "10")),
        ad_watch_seconds=int(_env("TGB_AD_WATCH_SECONDS", "22")),
        inter_account_delay=int(_env("TGB_INTER_ACCOUNT_DELAY", "6")),
        user_agent=_env("TGB_UA", DEFAULT_UA),
        notify=load_notify_from_env(),
    )


def load_config_yaml(path: Path) -> AppConfig:
    try:
        import yaml
    except ImportError as e:
        raise ImportError("本地 yaml 配置需要 PyYAML：pip install PyYAML") from e

    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    accounts: list[Account] = []
    for i, item in enumerate(raw.get("accounts") or []):
        if not isinstance(item, dict):
            raise ValueError(f"accounts[{i}] 格式错误")
        phone = str(item.get("phone") or item.get("username") or item.get("user") or "")
        pwd = str(item.get("password") or item.get("pwd") or item.get("pass") or "")
        if not phone or not pwd:
            raise ValueError(f"accounts[{i}] 缺少手机号或密码")
        accounts.append(
            Account(name=str(item.get("name") or phone), phone=phone, password=pwd)
        )

    if not accounts:
        raise ValueError("配置中 accounts 为空")

    n = raw.get("notify") or {}
    env_notify = load_notify_from_env()
    notify = NotifyConfig(
        bark_url=env_notify.bark_url or str(n.get("bark_url") or ""),
        bark_key=env_notify.bark_key or str(n.get("bark_key") or ""),
        bark_server=(
            env_notify.bark_server
            if env_notify.bark_key or env_notify.bark_url
            else str(n.get("bark_server") or DEFAULT_BARK_SERVER)
        ).rstrip("/"),
        bark_group=env_notify.bark_group if _env("BARK_GROUP") else str(n.get("bark_group") or "推广宝"),
        bark_sound=env_notify.bark_sound or str(n.get("bark_sound") or ""),
        bark_icon=env_notify.bark_icon or str(n.get("bark_icon") or ""),
        bark_level=env_notify.bark_level or str(n.get("bark_level") or ""),
    )

    return AppConfig(
        accounts=accounts,
        invite_code=_env("TGB_INVITE_CODE") or str(raw.get("invite_code") or DEFAULT_INVITE_CODE),
        timeout=int(_env("TGB_TIMEOUT") or raw.get("timeout") or 15),
        max_retries=int(_env("TGB_MAX_RETRIES") or raw.get("max_retries") or 3),
        retry_interval=int(_env("TGB_RETRY_INTERVAL") or raw.get("retry_interval") or 10),
        ad_watch_seconds=int(_env("TGB_AD_WATCH_SECONDS") or raw.get("ad_watch_seconds") or 22),
        inter_account_delay=int(_env("TGB_INTER_ACCOUNT_DELAY") or raw.get("inter_account_delay") or 6),
        user_agent=_env("TGB_UA") or str(raw.get("user_agent") or DEFAULT_UA),
        notify=notify,
    )


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def delay(seconds: float) -> None:
    time.sleep(seconds)


def extract_formhash(html: str) -> Optional[str]:
    m = re.search(r'name="formhash"[^>]*value=["\']([0-9a-f]{8})["\']', html, re.I)
    if not m:
        m = re.search(r'formhash["\']?\s*[:=]\s*["\']?([0-9a-f]{8})["\']?', html, re.I)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# HTTP 客户端（带重试）
# ---------------------------------------------------------------------------

class HttpClient:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": cfg.user_agent,
                "Accept": "*/*",
                "x-requested-with": "XMLHttpRequest",
                "sec-ch-ua-platform": '"Android"',
                "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Android WebView";v="134"',
                "sec-ch-ua-mobile": "?1",
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
                "accept-encoding": "gzip, deflate",
                "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://tg.suewammes.com/plugin.php?id=xigua_hh&ac=invite",
            }
        )

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.cfg.timeout)
        # 默认不抛 HTTPError，由各接口自行判断状态码/响应体
        raise_for_status = kwargs.pop("raise_for_status", False)
        last_err: Optional[Exception] = None

        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
                if raise_for_status:
                    resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                last_err = e
                logger.warning("🌐 请求失败（%d/%d）: %s", attempt, self.cfg.max_retries, e)
                if attempt < self.cfg.max_retries:
                    logger.info("⏳ %ds 后重试…", self.cfg.retry_interval)
                    time.sleep(self.cfg.retry_interval)

        raise last_err or RuntimeError("请求重试耗尽")

    def reset(self) -> None:
        self.session.cookies.clear()


# ---------------------------------------------------------------------------
# 业务
# ---------------------------------------------------------------------------

class TuiGuangBaoClient:
    def __init__(self, account: Account, cfg: AppConfig, http: HttpClient):
        self.account = account
        self.cfg = cfg
        self.http = http

    def _post_form(self, url: str, data: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "origin": "https://tg.suewammes.com",
        }
        resp = self.http.request("POST", url, data=data, headers=headers, allow_redirects=False)
        text = resp.text.strip()
        if text.startswith("{"):
            try:
                return resp.json()
            except json.JSONDecodeError:
                pass
        return {"_raw": text, "_status": resp.status_code}

    def _get_text(self, url: str) -> str:
        resp = self.http.request("GET", url)
        return resp.text

    def login(self) -> None:
        logger.info("[%s] 📱 开始登录", self.account.name)

        page_resp = self.http.request("GET", LOGIN_PAGE_URL)
        page_html = page_resp.text
        formhash = extract_formhash(page_html)
        logger.debug("[%s] 登录页状态: %s, formhash: %s", self.account.name, page_resp.status_code, formhash)
        if not formhash:
            raise RuntimeError("获取登录 formhash 失败")

        data = {
            "formhash": formhash,
            "referer": "https://tg.suewammes.com/plugin.php?id=xigua_hb&id=xigua_hb&needlogin=1&mobile=2",
            "fastloginfield": "username",
            "cookietime": "2592000",
            "username": self.account.phone,
            "password": self.account.password,
        }

        headers = {
            "origin": "https://tg.suewammes.com",
            "upgrade-insecure-requests": "1",
        }
        login_resp = self.http.request(
            "POST", LOGIN_URL, data=data, headers=headers, allow_redirects=False
        )

        # 使用 requests 的 CookieJar 判断，比字符串拼接更可靠
        # 同时取 session cookies 和本次响应 cookies，防止 302/Set-Cookie 未同步
        self.http.session.cookies.update(login_resp.cookies)
        cookie_names = {c.name for c in self.http.session.cookies} | {c.name for c in login_resp.cookies}
        logger.debug(
            "[%s] 登录 POST 状态: %s, cookie names: %s",
            self.account.name,
            login_resp.status_code,
            cookie_names,
        )

        body = login_resp.text
        has_auth_cookie = any(name.endswith("_auth") for name in cookie_names)
        login_success = has_auth_cookie and "欢迎您回来" in body

        if not login_success:
            logger.debug("[%s] 登录失败响应体: %s", self.account.name, body[:500])
            m = re.search(r"密码错误|账号不存在|登录失败|密码为空|验证码错误|登录尝试次数过多|submit", body)
            err_key = m.group(0) if m else "未知错误"
            raise RuntimeError(f"登录验证失败：{err_key} (HTTP {login_resp.status_code})")

        logger.info("[%s] ✅ 登录成功", self.account.name)

    def _get_formhash(self) -> Optional[str]:
        try:
            text = self._get_text(BASE_PLUGIN)
            fh = extract_formhash(text)
            if fh:
                return fh
            if "登录账号" in text or "loginform" in text:
                raise RuntimeError("未登录，请检查账号密码")
            raise RuntimeError("提取不到 formhash")
        except Exception as e:
            logger.error("[%s] ❌ 获取 formhash 失败: %s", self.account.name, e)
            return None

    def bind_yq_code(self) -> dict[str, Any]:
        fh = self._get_formhash()
        if not fh:
            return {"ok": False, "message": "获取 formhash 失败"}

        try:
            data = {"formhash": fh, "yqcode": self.cfg.invite_code}
            ret = self._post_form(BIND_YQ_URL, data)
            code = ret.get("code")
            msg = ret.get("msg", "")

            if str(code) == "0":
                logger.info("[%s] 🎊 邀请码 %s 绑定成功", self.account.name, self.cfg.invite_code)
                return {"ok": True, "message": "绑定成功"}
            if msg == "不能自己":
                logger.info("[%s] ⚠️ %s", self.account.name, msg)
                return {"ok": True, "message": msg}

            logger.info("[%s] ℹ️ 邀请码绑定结果：%s", self.account.name, msg)
            return {"ok": False, "message": msg}
        except Exception as e:
            logger.error("[%s] ❌ 绑定邀请码接口异常：%s", self.account.name, e)
            return {"ok": False, "message": str(e)}

    def get_task_status(self) -> Optional[dict[str, Any]]:
        try:
            resp = self.http.request("GET", f"{BASE_PLUGIN}&submodac=status")
            ct = resp.headers.get("content-type", "")
            text = resp.text
            if not ct.startswith("application/json") and "loginform" in text:
                raise RuntimeError("登录态失效")
            data = resp.json()
            if str(data.get("code")) != "0":
                raise RuntimeError(f"code:{data.get('code')}")
            return data.get("data")
        except Exception as e:
            logger.error("[%s] ❌ 查任务失败：%s", self.account.name, e)
            return None

    def get_next_ad_token(self) -> Optional[dict[str, Any]]:
        try:
            fh = self._get_formhash()
            if not fh:
                raise RuntimeError("获取 formhash 失败")
            data = {"formhash": fh}
            ret = self._post_form(f"{BASE_PLUGIN}&submodac=next_ad", data)
            if str(ret.get("code")) != "0":
                raise RuntimeError(ret.get("msg") or "获取广告失败")
            return ret.get("data")
        except Exception as e:
            logger.error("[%s] ❌ 获取广告 Token 失败：%s", self.account.name, e)
            return None

    def submit_ad_complete(self, token: str) -> Optional[dict[str, Any]]:
        try:
            fh = self._get_formhash()
            if not fh:
                raise RuntimeError("获取 formhash 失败")
            data = {"formhash": fh, "token": token}
            ret = self._post_form(f"{BASE_PLUGIN}&submodac=complete_ad", data)
            if str(ret.get("code")) != "0":
                raise RuntimeError(ret.get("msg") or "广告上报失败")
            return ret.get("data")
        except Exception as e:
            logger.error("[%s] ❌ 广告上报失败：%s", self.account.name, e)
            return None

    def claim_reward(self) -> Optional[dict[str, Any]]:
        try:
            fh = self._get_formhash()
            if not fh:
                raise RuntimeError("获取 formhash 失败")
            data = {"formhash": fh}
            ret = self._post_form(f"{BASE_PLUGIN}&submodac=claim", data)
            msg = ret.get("msg", "")
            logger.info("[%s] 🎁 领奖返回：%s", self.account.name, msg)
            return ret.get("data")
        except Exception as e:
            logger.error("[%s] ❌ 领奖失败：%s", self.account.name, e)
            return None

    def run(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "message": "",
            "viewed": 0,
            "target": 0,
            "claimed": False,
        }

        try:
            self.login()
        except Exception as e:
            result["message"] = f"登录失败: {e}"
            return result

        delay(1.5)
        self.bind_yq_code()

        max_loops = 50
        for _ in range(max_loops):
            task_info = self.get_task_status()
            if not task_info:
                result["message"] = "获取任务状态失败"
                break

            viewed_count = task_info.get("viewed_count", 0)
            target_count = task_info.get("target_count", 0)
            countdown_seconds = task_info.get("countdown_seconds", 0)
            can_claim = task_info.get("can_claim", False)
            claimed = task_info.get("claimed", False)

            result["viewed"] = viewed_count
            result["target"] = target_count
            result["claimed"] = claimed

            logger.info(
                "[%s] 📊 进度：%d/%d | 可领奖:%s | 今日已领取:%s",
                self.account.name,
                viewed_count,
                target_count,
                can_claim,
                claimed,
            )

            if can_claim and not claimed:
                logger.info("[%s] 🎉 任务已满，准备领奖", self.account.name)
                delay(2)
                claim = self.claim_reward()
                if claim is not None:
                    result["ok"] = True
                    result["message"] = "领奖成功"
                    result["claimed"] = True
                else:
                    result["message"] = "领奖失败"
                break

            if viewed_count >= target_count:
                result["ok"] = True
                result["message"] = "今日已领取" if claimed else "任务已完成"
                logger.info("[%s] ✅ %s", self.account.name, result["message"])
                break

            if claimed:
                result["ok"] = True
                result["message"] = "今日已领取"
                logger.info("[%s] ✅ 今日已领取", self.account.name)
                break

            if countdown_seconds > 0:
                logger.info("[%s] ⏳ 冷却等待 %d 秒", self.account.name, countdown_seconds)
                delay(countdown_seconds)

            ad_data = self.get_next_ad_token()
            if not ad_data:
                result["message"] = "获取广告失败"
                break

            token = ad_data.get("token", "")
            logger.info(
                "[%s] ▶ 获取 Token：%s，模拟观看 %d 秒",
                self.account.name,
                token,
                self.cfg.ad_watch_seconds,
            )
            delay(self.cfg.ad_watch_seconds)

            new_task = self.submit_ad_complete(token)
            if not new_task:
                result["message"] = "广告上报失败"
                break

            logger.info(
                "[%s] ✅ 广告上报成功，当前完成：%s",
                self.account.name,
                new_task.get("viewed_count", viewed_count),
            )
            delay(random.randint(3000, 6000) / 1000)

        if not result["message"] and not result["ok"]:
            result["message"] = "执行未完成"

        logger.info("[%s] 💚 本号流程结束", self.account.name)
        return result


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------

def _build_bark_endpoint(cfg: NotifyConfig) -> Optional[str]:
    if cfg.bark_url:
        return cfg.bark_url.rstrip("/")
    if cfg.bark_key:
        server = (cfg.bark_server or DEFAULT_BARK_SERVER).rstrip("/")
        return f"{server}/{cfg.bark_key}"
    return None


def send_bark(cfg: NotifyConfig, title: str, body: str) -> None:
    endpoint = _build_bark_endpoint(cfg)
    if not endpoint:
        return

    payload: dict[str, Any] = {
        "title": title,
        "body": body,
        "group": cfg.bark_group or "推广宝",
    }
    if cfg.bark_sound:
        payload["sound"] = cfg.bark_sound
    if cfg.bark_icon:
        payload["icon"] = cfg.bark_icon
    if cfg.bark_level:
        payload["level"] = cfg.bark_level

    post_url = endpoint if endpoint.endswith("/push") else f"{endpoint}/push"

    try:
        r = requests.post(post_url, json=payload, timeout=15)
        if r.status_code >= 400:
            get_url = f"{endpoint.rstrip('/')}/{quote(title, safe='')}/{quote(body, safe='')}"
            r = requests.get(get_url, timeout=15)
        logger.info("📣 Bark 已推送（HTTP %s）", r.status_code)
    except Exception as e:
        logger.warning("📣 Bark 推送失败: %s", e)


def format_summary(
    account_results: list[tuple[str, dict[str, Any]]],
) -> str:
    from datetime import datetime as _dt

    lines: list[str] = []
    lines.append(f"📅 {_dt.now().strftime('%m-%d %H:%M')}")
    lines.append("")

    ok_n = sum(1 for _, r in account_results if r.get("ok"))
    fail_n = len(account_results) - ok_n

    for i, (name, result) in enumerate(account_results):
        ok = bool(result.get("ok"))
        viewed = result.get("viewed", 0)
        target = result.get("target", 0)
        claimed = bool(result.get("claimed"))
        msg = str(result.get("message") or "").strip()

        lines.append(f"{'✅' if ok else '❌'} {name}")
        lines.append(f"   📊 进度：{viewed}/{target}")

        if claimed:
            lines.append("   💰 今日已领奖")
        elif ok and msg == "任务已完成":
            lines.append("   ✅ 任务已完成，尚未领奖")
        elif ok:
            lines.append(f"   ✅ {msg}")
        else:
            short = msg if len(msg) <= 100 else msg[:97] + "…"
            lines.append(f"   ❌ {short}")

        if i < len(account_results) - 1:
            lines.append("")

    lines.append("")
    lines.append("────────")
    if fail_n == 0:
        lines.append(f"📊 合计：{ok_n}/{len(account_results)} 全部成功 🎉")
    elif ok_n == 0:
        lines.append(f"📊 合计：{ok_n}/{len(account_results)} 全部失败")
    else:
        lines.append(f"📊 合计：成功 {ok_n} · 失败 {fail_n}（共 {len(account_results)} 号）")

    return "\n".join(lines)


def format_notify_title(account_results: list[tuple[str, dict[str, Any]]]) -> str:
    ok_n = sum(1 for _, r in account_results if r.get("ok"))
    n = len(account_results)
    if n == 0:
        return "推广宝每日广告"
    if ok_n == n:
        return f"推广宝每日广告 ✅ {ok_n}/{n}"
    if ok_n == 0:
        return f"推广宝每日广告 ❌ 0/{n}"
    return f"推广宝每日广告 ⚠️ {ok_n}/{n}"


def send_notify(cfg: NotifyConfig, title: str, content: str) -> None:
    if not cfg.enabled():
        logger.info("📣 未配置 Bark，跳过推送")
        return

    if cfg.bark_url or cfg.bark_key:
        send_bark(cfg, title, content)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def log_banner(title: str) -> None:
    logger.info("──────── %s ────────", title)


def resolve_config(args: argparse.Namespace) -> AppConfig:
    if args.config:
        return load_config_yaml(Path(args.config))

    env_cfg = load_config_from_env()
    if env_cfg is not None:
        logger.info("📦 已从环境变量加载 %d 个账号", len(env_cfg.accounts))
        return env_cfg

    local = SCRIPT_DIR / "config.yaml"
    if local.is_file():
        logger.info("📦 使用本地配置: %s", local)
        return load_config_yaml(local)

    raise FileNotFoundError(
        "未找到账号配置。\n"
        "青龙：请设置环境变量 TGB_ACCOUNTS 或 TGB 或 TGB_USER/TGB_PASS\n"
        "本地：cp config.example.yaml config.yaml 并填写"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="推广宝自动看广告领奖（青龙 / Bark）")
    parser.add_argument("-c", "--config", help="本地 yaml 配置路径（可选）")
    parser.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    parser.add_argument("--login-only", action="store_true", help="仅测试登录，不执行广告任务")
    args = parser.parse_args()

    setup_logging(args.verbose)

    try:
        cfg = resolve_config(args)
    except Exception as e:
        logger.error("❌ %s", e)
        return 2

    logger.info("🚀 推广宝自动看广告领奖")
    logger.info(
        "   账号 %s 个 · 通知 %s · 邀请码 %s · 广告观看 %ds",
        len(cfg.accounts),
        "开" if cfg.notify.enabled() else "关",
        cfg.invite_code,
        cfg.ad_watch_seconds,
    )

    account_results: list[tuple[str, dict[str, Any]]] = []

    for i, acc in enumerate(cfg.accounts):
        log_banner(f"👤 {acc.name}")

        if getattr(args, "login_only", False):
            try:
                http = HttpClient(cfg)
                TuiGuangBaoClient(acc, cfg, http).login()
                result = {"ok": True, "message": "登录成功", "viewed": 0, "target": 0, "claimed": False}
                logger.info("[%s] ✅ 登录成功", acc.name)
            except Exception as e:
                logger.error("[%s] ❌ 登录失败：%s", acc.name, e)
                logger.debug("exception traceback", exc_info=True)
                result = {"ok": False, "message": f"登录失败: {e}", "viewed": 0, "target": 0, "claimed": False}
            account_results.append((acc.name, result))
            if i < len(cfg.accounts) - 1:
                logger.info("⏳ 等待 %d 秒后测试下一账号…", cfg.inter_account_delay)
                delay(cfg.inter_account_delay)
            continue

        try:
            http = HttpClient(cfg)
            result = TuiGuangBaoClient(acc, cfg, http).run()
        except Exception as e:
            logger.error("[%s] 💥 未处理异常: %s", acc.name, e)
            logger.debug("exception traceback", exc_info=True)
            result = {
                "ok": False,
                "message": str(e),
                "viewed": 0,
                "target": 0,
                "claimed": False,
            }

        if result.get("ok"):
            logger.info("[%s] ✅ 流程结束：%s", acc.name, result.get("message"))
        else:
            logger.error("[%s] ❌ 流程结束：%s", acc.name, result.get("message"))

        account_results.append((acc.name, result))

        if i < len(cfg.accounts) - 1:
            logger.info("⏳ 等待 %d 秒后执行下一账号…", cfg.inter_account_delay)
            delay(cfg.inter_account_delay)

    summary = format_summary(account_results)
    title = format_notify_title(account_results)

    logger.info("")
    log_banner("执行结果")
    for line in summary.splitlines():
        logger.info("%s", line)

    send_notify(cfg.notify, title, summary)

    any_fail = any(not r.get("ok") for _, r in account_results)
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
