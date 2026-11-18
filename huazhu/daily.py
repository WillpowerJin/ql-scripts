#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
华住会 App / 小程序每日自动签到 (精简版)

cron: 15 8 * * *
new Env('华住会签到');

青龙面板使用说明：
  无需附加任何命令行参数，直接运行：
    task huazhu/daily.py
  环境变量配置：
    HZ_TOKEN = 你的 userToken（多账号用 & 或换行分隔）
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, quote, urlparse

import requests

SCRIPT_DIR = Path(__file__).resolve().parent

# ============================================================
# 常量定义
# ============================================================

DEFAULT_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Huazhu/iOS"
)
DEFAULT_REFERER = "https://cdn.huazhu.com/hzapp-signinfe/"
DEFAULT_ORIGIN = "https://cdn.huazhu.com"

APPGW_BASE = "https://appgw.huazhu.com"
HWEB_MBF_BASE = "https://hweb-mbf.huazhu.com"

DEFAULT_BARK_SERVER = "https://api.day.app"
DEFAULT_BARK_GROUP = "华住会签到"
RETRY_STATUS_CODES = (429, 500, 502, 503, 504)

IS_DEBUG = False

# 青龙面板统一通知
_ql_notify = None
try:
    from notify import send as _ql_notify  # type: ignore
except Exception:
    try:
        from utils.notify import send as _ql_notify  # type: ignore
    except Exception:
        _ql_notify = None


# ============================================================
# UI 打印辅助
# ============================================================

def ui_print(msg: str = "") -> None:
    print(msg, flush=True)


def ui_debug(msg: str) -> None:
    if IS_DEBUG:
        print(f"  🔍 [DEBUG] {msg}", flush=True)


def ui_banner(title: str = "每日自动签到") -> None:
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ui_print("=" * 60)
    ui_print(f"🏨 华住会 (Huazhu Club) {title}")
    ui_print(f"⏰ 执行时间: {now_str}")
    ui_print("=" * 60)
    ui_print()


# ============================================================
# 工具函数
# ============================================================

def _env(name: str, default: str = "") -> str:
    val = os.getenv(name)
    return val.strip() if val is not None and val.strip() != "" else default


def _env_int(name: str, default: int) -> int:
    v = _env(name)
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def extract_user_token(raw: str) -> str:
    """智能提取华住会 userToken"""
    if not raw:
        return ""
    text = raw.strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1].strip()

    # 正则匹配 userToken=xxx 或 user-token=xxx
    m = re.search(r"(?:userToken|user-token)\s*[:=]\s*([A-Za-z0-9_\-\.]+)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # URL 参数匹配
    if "://" in text or "?" in text:
        try:
            qs = parse_qs(urlparse(text).query)
            for k in ("userToken", "user-token", "token", "auth_token"):
                if k in qs and qs[k]:
                    return qs[k][0].strip()
        except Exception:
            pass

    # Bearer 前缀
    if text.lower().startswith("bearer "):
        text = text[7:].strip()

    # Cookie 分号分隔
    if ";" in text:
        for part in text.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                if "token" in k.lower():
                    return v.strip()

    return text


def format_point(val: Any) -> str:
    """格式化积分，带千分位逗号"""
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val or "0")


# ============================================================
# 配置读取
# ============================================================

def load_config(config_path: Optional[str] = None) -> dict[str, Any]:
    yaml_data: dict[str, Any] = {}
    target = Path(config_path).expanduser().resolve() if config_path else SCRIPT_DIR / "config.yaml"
    if not target.is_file():
        target = SCRIPT_DIR / "config.yml"

    if target.is_file():
        try:
            import yaml  # type: ignore
            with target.open("r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}
            ui_debug(f"已加载配置文件: {target}")
        except Exception as e:
            ui_debug(f"读取 YAML 配置异常: {e}")

    # 解析账号（优先环境变量，其次 YAML）
    accounts: list[dict[str, str]] = []
    env_json = _env("HUAZHU_ACCOUNTS")
    if env_json:
        try:
            arr = json.loads(env_json)
            if isinstance(arr, list):
                for i, it in enumerate(arr):
                    tk = str(it.get("token") or it.get("userToken") or "")
                    nm = str(it.get("name") or f"账号_{i + 1}")
                    if tk:
                        accounts.append({"name": nm, "token": tk})
        except Exception:
            pass

    if not accounts:
        env_tokens = ""
        for k in ("HZ_TOKEN", "HUAZHU_TOKEN", "HZH_TOKEN", "huazhu_cookies", "HZH_URL"):
            val = _env(k)
            if val:
                env_tokens = val
                break
        if env_tokens:
            for i, part in enumerate(re.split(r"[&\n\r]+", env_tokens)):
                part = part.strip()
                if not part:
                    continue
                name, token = f"账号_{i + 1}", part
                if "#" in part:
                    p1, p2 = part.split("#", 1)
                    name = p1.strip() or name
                    token = p2.strip()
                accounts.append({"name": name, "token": token})

    if not accounts and yaml_data.get("accounts"):
        for i, it in enumerate(yaml_data["accounts"]):
            if isinstance(it, dict):
                tk = str(it.get("token") or it.get("userToken") or "")
                nm = str(it.get("name") or f"账号_{i + 1}")
                if tk:
                    accounts.append({"name": nm, "token": tk})

    # 读取 Bark
    raw_bark = yaml_data.get("bark") or {}
    bark_url = _env("BARK_URL") or _env("BARK_PUSH") or str(raw_bark.get("url") or "")
    bark_key = _env("BARK_KEY") or _env("BARK_DEVICE_KEY") or str(raw_bark.get("key") or "")
    if bark_url and not bark_url.startswith("http"):
        bark_key = bark_key or bark_url
        bark_url = ""

    # 读取 PushPlus
    raw_pp = yaml_data.get("pushplus") or {}
    pp_token = _env("PUSHPLUS_TOKEN") or str(raw_pp.get("token") or "")
    pp_topic = _env("PUSHPLUS_TOPIC") or str(raw_pp.get("topic") or "")

    return {
        "accounts": accounts,
        "run_at": _env("RUN_AT") or str(yaml_data.get("run_at") or "08:30"),
        "random_delay": _env_int("RANDOM_DELAY", int(yaml_data.get("random_delay", 0))),
        "retry_times": _env_int("RETRY_TIMES", int(yaml_data.get("retry_times", 3))),
        "retry_delay": _env_int("RETRY_DELAY", int(yaml_data.get("retry_delay", 30))),
        "timeout": _env_int("TIMEOUT", int(yaml_data.get("timeout", 20))),
        "inter_account_delay": _env_int("INTER_ACCOUNT_DELAY", int(yaml_data.get("inter_account_delay", 3))),
        "token_file": _env("HZ_TOKEN_FILE") or _env("HUAZHU_TOKEN_FILE") or str(yaml_data.get("token_file") or ""),
        "bark": {
            "url": bark_url.strip(),
            "key": bark_key.strip(),
            "server": (_env("BARK_SERVER") or str(raw_bark.get("server") or "") or DEFAULT_BARK_SERVER).rstrip("/"),
            "group": _env("BARK_GROUP") or str(raw_bark.get("group") or "") or DEFAULT_BARK_GROUP,
            "sound": _env("BARK_SOUND") or str(raw_bark.get("sound") or ""),
            "icon": _env("BARK_ICON") or str(raw_bark.get("icon") or ""),
            "level": _env("BARK_LEVEL") or str(raw_bark.get("level") or ""),
        },
        "pushplus": {
            "token": pp_token.strip(),
            "topic": pp_topic.strip(),
        },
    }


# ============================================================
# 华住会业务请求
# ============================================================

class HuazhuClient:
    def __init__(self, name: str, raw_token: str, cfg: dict[str, Any]):
        self.name = name
        self.cfg = cfg
        self.token = extract_user_token(raw_token)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        retries = self.cfg["retry_times"]
        base_delay = self.cfg["retry_delay"]
        timeout = self.cfg["timeout"]

        for attempt in range(retries + 1):
            try:
                resp = self.session.request(method, url, timeout=timeout, **kwargs)
                # 检查服务端滑动续期下发的新 Token
                for sc in resp.headers.get("Set-Cookie", "").split(","):
                    m = re.search(r"userToken=([A-Za-z0-9_\-\.]+)", sc)
                    if m and m.group(1) and m.group(1) != self.token:
                        self.token = m.group(1)
                        tf = self.cfg.get("token_file")
                        if tf:
                            try:
                                Path(tf).expanduser().resolve().write_text(self.token, encoding="utf-8")
                                ui_print(f"  ✨ 服务端续发新凭证，已保存至: {tf}")
                            except Exception:
                                pass

                if resp.status_code not in RETRY_STATUS_CODES:
                    return resp

                if attempt < retries:
                    ra = resp.headers.get("Retry-After", "").strip()
                    wait_sec = int(ra) if ra.isdigit() else base_delay * (attempt + 1)
                    ui_print(f"  ⚠️ 遇 HTTP {resp.status_code} 限流/波动，等待 {wait_sec} 秒后重试 ({attempt + 1}/{retries})...")
                    time.sleep(wait_sec)
                    continue
                return resp
            except Exception as e:
                if attempt < retries:
                    wait_sec = base_delay * (attempt + 1)
                    ui_print(f"  ⚠️ 网络请求异常: {e}，等待 {wait_sec} 秒后重试 ({attempt + 1}/{retries})...")
                    time.sleep(wait_sec)
                    continue
                raise

        raise RuntimeError(f"请求失败，已重试 {retries} 次")

    def sign_in(self) -> tuple[int, str]:
        """主通道签到，返回 (code, message)"""
        url = f"{APPGW_BASE}/game/sign_in"
        headers = {
            "Cookie": f"userToken={self.token}",
            "Referer": DEFAULT_REFERER,
            "Origin": DEFAULT_ORIGIN,
        }
        resp = self._request("GET", url, params={"date": int(time.time())}, headers=headers)
        data = resp.json()
        return data.get("code", resp.status_code), data.get("message") or ""

    def query_status(self) -> tuple[Optional[int], Optional[int]]:
        """查询 (memberPoint, yearSignInCount)"""
        url = f"{APPGW_BASE}/game/sign_header"
        headers = {
            "Cookie": f"userToken={self.token}",
            "Referer": DEFAULT_REFERER,
            "Origin": DEFAULT_ORIGIN,
        }
        try:
            resp = self._request("GET", url, headers=headers)
            content = resp.json().get("content") or {}
            return content.get("memberPoint"), content.get("yearSignInCount")
        except Exception as e:
            ui_debug(f"查询签到状态异常: {e}")
            return None, None

    def fallback_mbf_signin(self) -> tuple[bool, str, Optional[int]]:
        """备用 MBF 通道签到"""
        url = f"{HWEB_MBF_BASE}/api/signIn"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Client-Platform": "APP-IOS",
            "User-Token": self.token,
        }
        day_str = datetime.datetime.now().strftime("%d")
        resp = self._request("POST", url, headers=headers, data=f"state=1&day={day_str}")
        data = resp.json()
        content = data.get("content") or {}
        b_code = str(data.get("businessCode", ""))

        # 查询备用积分
        point = None
        try:
            p_resp = self._request("POST", f"{HWEB_MBF_BASE}/api/getPoint", headers=headers, data="{}")
            point = (p_resp.json().get("content") or {}).get("point")
        except Exception:
            pass

        if b_code == "1000":
            if content.get("success") is True:
                return True, "🎉 备用通道签到成功！", point
            if content.get("isSign") is True:
                return True, "👌 备用通道确认今日已签到。", point

        msg = data.get("message") or "未知错误"
        return False, f"❌ 签到失败: {msg}", point

    def run(self, only_check: bool = False) -> dict[str, Any]:
        """执行账号签到或查分流程"""
        if not self.token:
            ui_print(f"❌ 【{self.name}】未配置 userToken，请先配置凭证！")
            ui_print()
            return {"name": self.name, "ok": False, "status_desc": "凭证缺失 ❌", "hint": "请配置 HZ_TOKEN"}

        mask = f"{self.token[:4]}***{self.token[-4:]}" if len(self.token) >= 8 else "***"
        ui_print(f"👤 正在执行账号: 【{self.name}】")
        ui_print(f"  🔑 凭据校验: 有效 (Token: {mask})")

        if only_check:
            pts, days = self.query_status()
            if pts is not None:
                ui_print(f"  💰 会员总积分: {format_point(pts)}")
            if days is not None:
                ui_print(f"  📅 今年累计签到: {days} 天")
            ui_print(f"  ✅ 账号状态正常！\n")
            return {
                "name": self.name,
                "ok": pts is not None,
                "status_desc": "账号正常 ✅",
                "point": format_point(pts) if pts is not None else None,
                "days": days,
            }

        ui_print("  📡 正在请求官方主线签到通道 (appgw)...")
        status_desc = ""
        is_ok = False
        hint = ""

        try:
            code, msg = self.sign_in()
            if code == 200:
                is_ok = True
                status_desc = "签到成功 🎉"
                ui_print("  🎉 签到成功！")
            elif code == 5004 or "已签到" in msg:
                is_ok = True
                status_desc = "今日已签到 👌"
                ui_print("  👌 今日已签到，无需重复签到。")
            elif code in (401, 1003) or "unauthorized" in msg.lower():
                is_ok = False
                status_desc = "凭据已失效 (Token Expired) ❌"
                hint = "Token 已过期，请重新抓包更新 HZ_TOKEN"
                ui_print(f"  ❌ {status_desc}！{hint}")
            elif code == 429:
                is_ok = False
                status_desc = "请求被限流 (HTTP 429) ⚠️"
                hint = "华住服务繁忙，建议设置 RANDOM_DELAY 错峰"
                ui_print(f"  ⚠️ {status_desc}！")
            else:
                ui_print(f"  ⚠️ 主通道返回 code={code} ({msg})，尝试备用通道...")
                is_ok, status_desc, fb_pts = self.fallback_mbf_signin()
                ui_print(f"  {status_desc}\n")
                return {
                    "name": self.name,
                    "ok": is_ok,
                    "status_desc": status_desc,
                    "point": format_point(fb_pts) if fb_pts is not None else None,
                    "days": None,
                }
        except Exception as e:
            ui_print(f"  ⚠️ 主通道请求异常: {e}，尝试备用通道...")
            is_ok, status_desc, fb_pts = self.fallback_mbf_signin()
            ui_print(f"  {status_desc}\n")
            return {
                "name": self.name,
                "ok": is_ok,
                "status_desc": status_desc,
                "point": format_point(fb_pts) if fb_pts is not None else None,
                "days": None,
            }

        # 查询最新积分与天数
        pts, days = self.query_status()
        if pts is not None:
            ui_print(f"  💰 会员总积分: {format_point(pts)}")
        if days is not None:
            ui_print(f"  📅 今年累计签到: {days} 天")
        ui_print()

        return {
            "name": self.name,
            "ok": is_ok,
            "status_desc": status_desc,
            "point": format_point(pts) if pts is not None else None,
            "days": days,
            "hint": hint,
        }


# ============================================================
# 推送通知模块 (Bark / 青龙 / PushPlus)
# ============================================================

def send_push_notifications(cfg: dict[str, Any], results: list[dict[str, Any]], only_check: bool) -> None:
    all_ok = all(r["ok"] for r in results)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    action = "状态查询" if only_check else "每日签到"

    # 构建标题
    status_tag = "全部成功 🎉" if all_ok else "有异常需关注 ⚠️"
    title = f"🏨 华住会{action} · {status_tag}"

    # 构建优美的 Bark 卡片内容
    lines = [
        f"⏰ 执行时间: {now_str}",
        "────────────────────────",
    ]

    for r in results:
        lines.append(f"👤 【{r['name']}】")
        lines.append(f"   ✨ 状态: {r['status_desc']}")
        if r.get("point") is not None:
            lines.append(f"   💰 积分: {r['point']}")
        if r.get("days") is not None:
            lines.append(f"   📅 连签: {r['days']} 天")
        if r.get("hint"):
            lines.append(f"   💡 提示: {r['hint']}")
        lines.append("────────────────────────")

    if all_ok:
        lines.append("🎉 华住会今日签到已全部完成！")
    else:
        lines.append("⚠️ 部分账号执行存在异常，请留意排查。")

    content = "\n".join(lines)

    # 1. 优先青龙面板统一通知
    if _ql_notify:
        try:
            ui_print("📣 通知状态: 正在调用青龙面板统一通知发送推送 🚀")
            _ql_notify(title, content)
            return
        except Exception:
            pass

    # 2. Bark 通知
    bark = cfg.get("bark") or {}
    if bark.get("url") or bark.get("key"):
        endpoint = bark["url"].rstrip("/") if bark.get("url") else f"{bark['server']}/{bark['key']}"
        payload: dict[str, Any] = {
            "title": title,
            "body": content,
            "group": bark.get("group") or DEFAULT_BARK_GROUP,
        }
        for opt in ("sound", "icon", "level"):
            if bark.get(opt):
                payload[opt] = bark[opt]
        try:
            r = requests.post(endpoint, json=payload, timeout=15)
            if r.status_code >= 400:
                requests.get(f"{endpoint}/{quote(title, safe='')}/{quote(content, safe='')}", timeout=15)
            ui_print("📣 通知状态: 已发送至 iOS Bark 推送 📱")
        except Exception as e:
            ui_debug(f"Bark 发送失败: {e}")

    # 3. PushPlus 微信通知
    pp = cfg.get("pushplus") or {}
    if pp.get("token"):
        try:
            requests.post(
                "https://www.pushplus.plus/send",
                json={
                    "token": pp["token"],
                    "title": title,
                    "content": content.replace("\n", "<br>"),
                    "template": "html",
                    "topic": pp.get("topic") or "",
                },
                timeout=15,
            )
            ui_print("📣 通知状态: 已发送至 PushPlus 微信推送 💬")
        except Exception as e:
            ui_debug(f"PushPlus 发送失败: {e}")


# ============================================================
# 执行流程
# ============================================================

def run_once(cfg: dict[str, Any], only_check: bool = False) -> int:
    ui_banner("账号状态查询" if only_check else "每日自动签到")

    accounts = cfg.get("accounts") or []
    if not accounts:
        ui_print("❌ 未检测到华住会账号配置或 HZ_TOKEN 环境变量！")
        ui_print("💡 提示: 请在青龙面板「环境变量」添加 HZ_TOKEN，或配置 config.yaml。")
        ui_print("📖 抓包指引: 详见 huazhu/README.md。")
        ui_print("=" * 60)
        ui_print()
        return 2

    # 青龙面板错峰延迟
    delay_max = cfg.get("random_delay", 0)
    if delay_max > 0 and (os.environ.get("QL_DIR") or os.environ.get("HOSTNAME")):
        d = random.randint(0, delay_max)
        ui_print(f"⏳ 检测到定时任务环境，随机错峰等待 {d} 秒 (约 {d / 60.0:.1f} 分钟)...")
        ui_print()
        time.sleep(d)

    results: list[dict[str, Any]] = []
    inter_delay = cfg.get("inter_account_delay", 3)

    for i, acc in enumerate(accounts):
        if i > 0 and inter_delay > 0:
            time.sleep(inter_delay)
        client = HuazhuClient(acc["name"], acc["token"], cfg)
        res = client.run(only_check=only_check)
        results.append(res)

    all_ok = all(r["ok"] for r in results)

    # 终端汇总
    ui_print("=" * 60)
    ui_print("📋 签到结果汇总")
    ui_print("-" * 60)
    for r in results:
        status_icon = "✅" if r["ok"] else "❌"
        extra = []
        if r.get("point") is not None:
            extra.append(f"积分: {r['point']}")
        if r.get("days") is not None:
            extra.append(f"连签: {r['days']}天")
        extra_str = f" [{ ' | '.join(extra) }]" if extra else ""
        ui_print(f"  {status_icon} 【{r['name']}】{r['status_desc']}{extra_str}")
    ui_print("=" * 60)
    ui_print()

    # 发送推送通知
    send_push_notifications(cfg, results, only_check=only_check)
    ui_print("✨ 华住会任务全部完成！\n")
    return 0 if all_ok else 1


def run_loop(cfg: dict[str, Any]) -> None:
    target_time = cfg.get("run_at", "08:30").strip()
    delay_max = cfg.get("random_delay", 0)
    ui_banner("后台常驻模式")
    ui_print(f"🕒 常驻服务已启动：每天 {target_time} 准时执行签到（错峰上限: {delay_max} 秒）\n")
    last_date: Optional[datetime.date] = None

    while True:
        now = datetime.datetime.now()
        if now.strftime("%H:%M") == target_time and last_date != now.date():
            last_date = now.date()
            if delay_max > 0:
                d = random.randint(0, delay_max)
                ui_print(f"⏳ 随机错峰等待 {d} 秒 (约 {d / 60.0:.1f} 分钟)...")
                time.sleep(d)
            ui_print(f"⏰ 到达定时时间，开始签到...")
            try:
                run_once(cfg)
            except Exception as e:
                ui_print(f"❌ 执行异常: {e}")
        time.sleep(20)


def main() -> None:
    parser = argparse.ArgumentParser(description="华住会每日自动签到脚本 (精简版)")
    parser.add_argument("--check", action="store_true", help="仅查询积分与状态，不签到")
    parser.add_argument("--loop", action="store_true", help="常驻后台每天定时运行")
    parser.add_argument("--config", type=str, default="", help="指定配置文件路径")
    parser.add_argument("--debug", action="store_true", help="输出调试日志")

    args = parser.parse_args()

    global IS_DEBUG
    IS_DEBUG = args.debug or _env("DEBUG") in ("1", "true", "yes")

    cfg = load_config(config_path=args.config)

    # 默认直接执行单次签到（青龙面板无需添加任何参数）
    if args.loop:
        run_loop(cfg)
    else:
        sys.exit(run_once(cfg, only_check=args.check))


if __name__ == "__main__":
    main()
