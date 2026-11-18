#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宜家家居 (IKEA) 每日自动签到

cron: 20 8 * * *
new Env('宜家签到');

================================================================
使用提示
================================================================
青龙面板直接添加定时任务即可，无需附加任何参数：
  task ikea/daily.py
脚本默认即为单次签到执行模式。

配置方式（环境变量 / 配置文件）：
  青龙面板「环境变量」添加：
    IKEA_TOKEN = 你的登录 Token（多账号用 & 或换行分隔）
  或使用本地配置文件：
    cp ikea/config.example.yaml ikea/config.yaml
  如果手机已连接且已 root，也可在电脑上一键提取：
    python3 ikea/pull_token.py --write-config
================================================================
"""

from __future__ import annotations

import argparse
import base64
import datetime
import json
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

SCRIPT_DIR = Path(__file__).resolve().parent

# ============================================================
# 常量定义
# ============================================================

DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
)
DEFAULT_ORIGIN = "https://res.app.ikea.cn"
DEFAULT_REFERER = "https://res.app.ikea.cn/"

BFF_BASE = "https://bff.app.ikea.cn"
CIAM_BASE = "https://ciam.family.ikea.cn"

ACTIVITY_NAME = "FAMILY_MEMBER_DAILY_SIGN_IN"
DEFAULT_ZIP_CODE = "100012"

DEFAULT_RUN_AT = "08:35"
DEFAULT_RANDOM_DELAY = 0
DEFAULT_RETRY_TIMES = 3
DEFAULT_RETRY_DELAY = 15
DEFAULT_TIMEOUT = 20
DEFAULT_INTER_ACCOUNT_DELAY = 3
DEFAULT_BARK_SERVER = "https://api.day.app"
DEFAULT_BARK_GROUP = "宜家签到"

RETRY_STATUS_CODES = (429, 500, 502, 503, 504)

IS_DEBUG = False

# ============================================================
# 控制台 UI 输出与美化
# ============================================================

def set_debug(val: bool) -> None:
    global IS_DEBUG
    IS_DEBUG = val


def ui_print(msg: str = "") -> None:
    print(msg, flush=True)


def ui_debug(msg: str) -> None:
    if IS_DEBUG:
        print(f"  🔍 [DEBUG] {msg}", flush=True)


def ui_banner(title: str = "每日自动签到") -> None:
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ui_print("=" * 60)
    ui_print(f"🛋️ 宜家 (IKEA) {title}")
    ui_print(f"⏰ 执行时间: {now_str}")
    ui_print("=" * 60)
    ui_print()


# ============================================================
# 青龙统一通知导入
# ============================================================

_ql_notify = None
try:
    from notify import send as _ql_notify  # type: ignore
except Exception:
    try:
        from utils.notify import send as _ql_notify  # type: ignore
    except Exception:
        _ql_notify = None


# ============================================================
# 数据结构与配置类
# ============================================================

@dataclass
class Account:
    name: str
    token: str
    party_uid: str = ""

    def clean_token(self) -> str:
        t = self.token.strip()
        if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
            t = t[1:-1].strip()
        if t.lower().startswith("bearer "):
            t = t[7:].strip()
        return t

    def get_party_uid(self) -> str:
        """若未单独配置 party_uid，自动从 JWT Token 中提取"""
        if self.party_uid:
            return self.party_uid.strip()
        clean = self.clean_token()
        if "." in clean:
            try:
                parts = clean.split(".")
                if len(parts) >= 2:
                    payload_b64 = parts[1]
                    rem = len(payload_b64) % 4
                    if rem:
                        payload_b64 += "=" * (4 - rem)
                    decoded = json.loads(base64.urlsafe_b64decode(payload_b64))
                    uid = decoded.get("partyUID") or decoded.get("user_id") or decoded.get("sub")
                    if uid:
                        return str(uid).strip()
            except Exception as e:
                ui_debug(f"从 JWT 提取 partyUID 失败: {e}")
        return "default-key"


@dataclass
class BarkConfig:
    url: str = ""
    key: str = ""
    server: str = DEFAULT_BARK_SERVER
    group: str = DEFAULT_BARK_GROUP
    sound: str = ""
    icon: str = ""
    level: str = ""

    def enabled(self) -> bool:
        return bool(self.url or self.key)


@dataclass
class PushPlusConfig:
    token: str = ""
    topic: str = ""

    def enabled(self) -> bool:
        return bool(self.token)


@dataclass
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    run_at: str = DEFAULT_RUN_AT
    random_delay: int = DEFAULT_RANDOM_DELAY
    retry_times: int = DEFAULT_RETRY_TIMES
    retry_delay: int = DEFAULT_RETRY_DELAY
    timeout: int = DEFAULT_TIMEOUT
    inter_account_delay: int = DEFAULT_INTER_ACCOUNT_DELAY
    notify_on: str = "all"  # all | fail | success
    bark: BarkConfig = field(default_factory=BarkConfig)
    pushplus: PushPlusConfig = field(default_factory=PushPlusConfig)


# ============================================================
# 加密与辅助函数
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


def _split_multiline(val: str) -> list[str]:
    if not val:
        return []
    return [x.strip() for x in re.split(r"[&\n\r]+", val) if x.strip()]


def format_point(val: Any) -> str:
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val or "0")


def ikea_encrypt(payload: dict[str, Any], key: str) -> str:
    """
    宜家前端专属 XOR 混淆加密算法：
    将 JSON 序列化字符串与 partyUid 进行逐字节循环异或运算，再进行 Base64 编码。
    """
    data_str = json.dumps(payload, separators=(",", ":"))
    data_bytes = data_str.encode("utf-8")
    key_bytes = key.encode("utf-8")
    encrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(data_bytes))
    return base64.b64encode(encrypted).decode("utf-8")


def ikea_decrypt(b64_str: str, key: str) -> str:
    """宜家前端异或解密"""
    encrypted = base64.b64decode(b64_str)
    key_bytes = key.encode("utf-8")
    decrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(encrypted))
    return decrypted.decode("utf-8", "ignore")


# ============================================================
# 配置加载
# ============================================================

def load_bark_config(raw_bark: Optional[dict[str, Any]] = None) -> BarkConfig:
    raw = raw_bark or {}
    url = _env("BARK_URL") or _env("BARK_PUSH") or str(raw.get("url") or "")
    key = _env("BARK_KEY") or _env("BARK_DEVICE_KEY") or str(raw.get("key") or "")
    if url and not url.startswith("http"):
        key = key or url
        url = ""
    group = _env("BARK_GROUP") or str(raw.get("group") or "") or DEFAULT_BARK_GROUP
    server = (_env("BARK_SERVER") or str(raw.get("server") or "") or DEFAULT_BARK_SERVER).rstrip("/")
    return BarkConfig(
        url=url.strip(),
        key=key.strip(),
        server=server,
        group=group,
        sound=_env("BARK_SOUND") or str(raw.get("sound") or ""),
        icon=_env("BARK_ICON") or str(raw.get("icon") or ""),
        level=_env("BARK_LEVEL") or str(raw.get("level") or ""),
    )


def load_pushplus_config(raw_pushplus: Optional[dict[str, Any]] = None) -> PushPlusConfig:
    raw = raw_pushplus or {}
    token = _env("PUSHPLUS_TOKEN") or str(raw.get("token") or "")
    topic = _env("PUSHPLUS_TOPIC") or str(raw.get("topic") or "")
    return PushPlusConfig(token=token.strip(), topic=topic.strip())


def parse_accounts_from_env() -> list[Account]:
    # 1. 优先 IKEA_ACCOUNTS JSON 数组
    raw_json = _env("IKEA_ACCOUNTS")
    if raw_json:
        try:
            arr = json.loads(raw_json)
            if isinstance(arr, list):
                res: list[Account] = []
                for i, item in enumerate(arr):
                    if isinstance(item, dict):
                        token = str(item.get("token") or item.get("accessToken") or "")
                        name = str(item.get("name") or f"账号_{i + 1}")
                        p_uid = str(item.get("party_uid") or item.get("partyUid") or "")
                        if token:
                            res.append(Account(name=name, token=token, party_uid=p_uid))
                if res:
                    return res
        except json.JSONDecodeError as e:
            ui_debug(f"解析 IKEA_ACCOUNTS JSON 失败: {e}")

    # 2. 依次检查兼容环境变量
    token_str = _env("IKEA_TOKEN") or _env("IKEA_ACCESS_TOKEN") or _env("IEKA_TOKEN")
    items = _split_multiline(token_str)
    accounts: list[Account] = []
    for i, item in enumerate(items):
        acc_name = f"账号_{i + 1}"
        acc_token = item
        acc_uid = ""
        if "#" in item:
            parts = item.split("#", 2)
            acc_name = parts[0].strip() or acc_name
            acc_token = parts[1].strip()
            if len(parts) >= 3:
                acc_uid = parts[2].strip()
        accounts.append(Account(name=acc_name, token=acc_token, party_uid=acc_uid))
    return accounts


def load_config(config_path: Optional[str] = None) -> AppConfig:
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

    accounts = parse_accounts_from_env()

    if not accounts and yaml_data.get("accounts"):
        for i, item in enumerate(yaml_data["accounts"]):
            if isinstance(item, dict):
                token = str(item.get("token") or item.get("accessToken") or "")
                name = str(item.get("name") or f"账号_{i + 1}")
                p_uid = str(item.get("party_uid") or item.get("partyUid") or "")
                if token:
                    accounts.append(Account(name=name, token=token, party_uid=p_uid))

    return AppConfig(
        accounts=accounts,
        run_at=_env("RUN_AT") or str(yaml_data.get("run_at") or DEFAULT_RUN_AT),
        random_delay=_env_int("RANDOM_DELAY", int(yaml_data.get("random_delay", DEFAULT_RANDOM_DELAY))),
        retry_times=_env_int("RETRY_TIMES", int(yaml_data.get("retry_times", DEFAULT_RETRY_TIMES))),
        retry_delay=_env_int("RETRY_DELAY", int(yaml_data.get("retry_delay", DEFAULT_RETRY_DELAY))),
        timeout=_env_int("TIMEOUT", int(yaml_data.get("timeout", DEFAULT_TIMEOUT))),
        inter_account_delay=_env_int("INTER_ACCOUNT_DELAY", int(yaml_data.get("inter_account_delay", DEFAULT_INTER_ACCOUNT_DELAY))),
        notify_on=_env("NOTIFY_ON", str(yaml_data.get("notify_on", "all"))).lower(),
        bark=load_bark_config(yaml_data.get("bark")),
        pushplus=load_pushplus_config(yaml_data.get("pushplus")),
    )


# ============================================================
# 推送通知
# ============================================================

def send_push_notifications(cfg: AppConfig, results: list[dict[str, Any]], only_check: bool) -> None:
    all_ok = all(r["ok"] for r in results)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    action = "状态查询" if only_check else "每日签到"

    status_tag = "全部成功 🎉" if all_ok else "有异常需关注 ⚠️"
    title = f"🛋️ 宜家{action} · {status_tag}"

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
        lines.append("🎉 宜家今日签到已全部完成！")
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
    if cfg.bark.enabled():
        endpoint = cfg.bark.url.rstrip("/") if cfg.bark.url else f"{cfg.bark.server.rstrip('/')}/{cfg.bark.key.strip()}"
        payload: dict[str, Any] = {
            "title": title,
            "body": content,
            "group": cfg.bark.group or DEFAULT_BARK_GROUP,
        }
        for opt in ("sound", "icon", "level"):
            val = getattr(cfg.bark, opt)
            if val:
                payload[opt] = val
        try:
            r = requests.post(endpoint, json=payload, timeout=15)
            if r.status_code >= 400:
                requests.get(f"{endpoint}/{quote(title, safe='')}/{quote(content, safe='')}", timeout=15)
            ui_print("📣 通知状态: 已发送至 iOS Bark 推送 📱")
        except Exception as e:
            ui_debug(f"Bark 发送失败: {e}")

    # 3. PushPlus 通知
    if cfg.pushplus.enabled():
        try:
            requests.post(
                "https://www.pushplus.plus/send",
                json={
                    "token": cfg.pushplus.token,
                    "title": title,
                    "content": content.replace("\n", "<br>"),
                    "template": "html",
                    "topic": cfg.pushplus.topic or "",
                },
                timeout=15,
            )
            ui_print("📣 通知状态: 已发送至 PushPlus 微信推送 💬")
        except Exception as e:
            ui_debug(f"PushPlus 发送失败: {e}")


# ============================================================
# 宜家业务 Client
# ============================================================

class IkeaClient:
    def __init__(self, account: Account, config: AppConfig):
        self.account = account
        self.config = config
        self.token = account.clean_token()
        self.party_uid = account.get_party_uid()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_UA,
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json, text/plain, */*",
            "Origin": DEFAULT_ORIGIN,
            "Referer": DEFAULT_REFERER,
        })

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        retries = self.config.retry_times
        base_delay = self.config.retry_delay
        timeout = self.config.timeout

        for attempt in range(retries + 1):
            try:
                resp = self.session.request(method, url, timeout=timeout, **kwargs)
                if resp.status_code not in RETRY_STATUS_CODES:
                    return resp
                if attempt < retries:
                    wait_sec = base_delay * (attempt + 1)
                    ui_print(f"  ⚠️ 遇 HTTP {resp.status_code} 异常，等待 {wait_sec} 秒后重试 ({attempt + 1}/{retries})...")
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

    def get_activity_info(self) -> tuple[Optional[int], Optional[int]]:
        """获取签到活动 ID 及每日签到玩法 ID"""
        url = f"{BFF_BASE}/customer-bff/v3.0/activity"
        params = {"name": ACTIVITY_NAME, "zipCode": DEFAULT_ZIP_CODE}
        resp = self._request("GET", url, params=params)
        data = resp.json().get("data") or {}
        act_id = data.get("id")
        gameplay_id = None
        for g in data.get("gameplayList", []):
            if g.get("gameplayType") == "DAILY_SIGN_IN":
                gameplay_id = g.get("id")
                break
        return act_id, gameplay_id

    def check_signed_today(self, activity_id: int) -> tuple[bool, Optional[int]]:
        """检查今日是否已签到，并返回连签天数"""
        url = f"{BFF_BASE}/customer-bff/v3.0/activity/participants"
        params = {"activityId": activity_id, "zipCode": DEFAULT_ZIP_CODE}
        resp = self._request("GET", url, params=params)
        props = (resp.json().get("data") or {}).get("properties") or {}
        last_date = props.get("lastSignInDate") or ""
        consecutive_days = props.get("consecutiveDays")
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        is_signed = (last_date == today_str)
        return is_signed, consecutive_days

    def do_sign_in(self, activity_id: int, gameplay_id: int) -> tuple[bool, str]:
        """触发每日签到事件"""
        url = f"{BFF_BASE}/customer-bff/v3.0/activity/events"
        payload = {
            "activityId": activity_id,
            "eventType": "DAILY_SIGN_IN",
            "gameplayId": gameplay_id,
        }
        enc_data = ikea_encrypt(payload, self.party_uid)
        resp = self._request("POST", url, json={"encryptData": enc_data})
        res_json = resp.json()
        code = str(res_json.get("code", ""))
        msg = res_json.get("message") or ""

        if code == "0" or resp.status_code == 200 and code == "200":
            return True, "签到成功 🎉"
        if code == "5147" or "已经签到" in msg:
            return True, "今日已签到 👌"
        if code in ("401", "10001") or "token" in msg.lower():
            return False, "凭据已失效 (Token Expired) ❌"
        return False, f"签到失败 (code={code}): {msg}"

    def get_points(self) -> Optional[int]:
        """获取当前会员可用积分"""
        url = f"{BFF_BASE}/customer-bff/point/benefit/summary"
        try:
            resp = self._request("GET", url)
            data = resp.json().get("data") or {}
            return data.get("availablePoints")
        except Exception as e:
            ui_debug(f"获取积分失败: {e}")
            return None

    def execute(self, only_check: bool = False) -> dict[str, Any]:
        if not self.token:
            msg = f"❌ 【{self.account.name}】未配置 Token"
            ui_print(msg)
            return {"name": self.account.name, "ok": False, "status_desc": "Token 缺失 ❌", "hint": "请配置 IKEA_TOKEN"}

        mask = f"{self.token[:6]}***{self.token[-6:]}" if len(self.token) > 12 else "***"
        ui_print(f"👤 正在执行账号: 【{self.account.name}】")
        ui_print(f"  🔑 凭据校验: 有效 (Token: {mask})")

        # 1. 查询活动与今日签到状态
        ui_print("  📡 正在获取宜家会员活动状态...")
        try:
            act_id, gameplay_id = self.get_activity_info()
            if not act_id or not gameplay_id:
                act_id, gameplay_id = 10003, 15  # 官方默认活动 ID 与玩法 ID
            ui_debug(f"Activity ID: {act_id}, Gameplay ID: {gameplay_id}")

            signed_today, days = self.check_signed_today(act_id)
        except Exception as e:
            ui_print(f"  ❌ 连接宜家会员服务异常: {e}")
            return {
                "name": self.account.name,
                "ok": False,
                "status_desc": f"连接失败: {e}",
                "hint": "请检查网络或 Token 是否过期",
            }

        # 2. 仅查询状态
        if only_check:
            pts = self.get_points()
            if pts is not None:
                ui_print(f"  💰 会员总积分: {format_point(pts)}")
            if days is not None:
                ui_print(f"  📅 连续签到: {days} 天")
            status_text = "今日已完成签到 👌" if signed_today else "今日尚未签到 ⏳"
            ui_print(f"  {status_text}\n")
            return {
                "name": self.account.name,
                "ok": True,
                "status_desc": status_text,
                "point": format_point(pts) if pts is not None else None,
                "days": days,
            }

        # 3. 执行每日签到
        is_ok = False
        status_desc = ""
        hint = ""

        if signed_today:
            is_ok = True
            status_desc = "今日已签到 👌"
            ui_print(f"  👌 今日已签到，无需重复打卡。")
        else:
            ui_print("  🚀 正在提交每日签到打卡请求...")
            try:
                is_ok, status_desc = self.do_sign_in(act_id, gameplay_id)
                ui_print(f"  {status_desc}")
                if "失效" in status_desc:
                    hint = "Token 已过期，请用 pull_token.py 或抓包更新"
                elif is_ok:
                    days = (days or 0) + 1
            except Exception as e:
                is_ok = False
                status_desc = f"打卡异常: {e}"
                ui_print(f"  ❌ {status_desc}")

        # 4. 获取最新积分
        pts = self.get_points()
        if pts is not None:
            ui_print(f"  💰 会员总积分: {format_point(pts)}")
        if days is not None:
            ui_print(f"  📅 连续签到: {days} 天")
        ui_print()

        return {
            "name": self.account.name,
            "ok": is_ok,
            "status_desc": status_desc,
            "point": format_point(pts) if pts is not None else None,
            "days": days,
            "hint": hint,
        }


# ============================================================
# 执行调度器
# ============================================================

def run_once(config: AppConfig, only_check: bool = False) -> int:
    action_name = "账号状态查询" if only_check else "每日自动签到"
    ui_banner(action_name)

    if not config.accounts:
        ui_print("❌ 未检测到宜家账号配置或 IKEA_TOKEN 环境变量！")
        ui_print("💡 提示: 请在青龙面板「环境变量」添加 IKEA_TOKEN，或配置 config.yaml。")
        ui_print("📱 如果手机连着电脑，也可直接运行: python3 ikea/pull_token.py --write-config")
        ui_print("=" * 60)
        ui_print()
        return 2

    # 青龙错峰延迟
    if config.random_delay > 0 and (os.environ.get("QL_DIR") or os.environ.get("HOSTNAME")):
        delay = random.randint(0, config.random_delay)
        ui_print(f"⏳ 检测到定时任务环境，随机错峰等待 {delay} 秒 (约 {delay / 60.0:.1f} 分钟)...")
        ui_print()
        time.sleep(delay)

    results: list[dict[str, Any]] = []

    for i, acc in enumerate(config.accounts):
        if i > 0 and config.inter_account_delay > 0:
            time.sleep(config.inter_account_delay)

        client = IkeaClient(acc, config)
        res = client.execute(only_check=only_check)
        results.append(res)

    all_ok = all(r["ok"] for r in results)

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

    send_push_notifications(config, results, only_check=only_check)
    ui_print("✨ 宜家任务全部完成！\n")
    return 0 if all_ok else 1


def run_loop(config: AppConfig) -> None:
    target_time = config.run_at.strip()
    ui_banner("后台常驻模式")
    ui_print(f"🕒 常驻服务已启动：每天 {target_time} 准时执行签到（错峰上限: {config.random_delay} 秒）\n")
    last_run_date: Optional[datetime.date] = None

    while True:
        now = datetime.datetime.now()
        current_hm = now.strftime("%H:%M")

        if current_hm == target_time and last_run_date != now.date():
            last_run_date = now.date()
            delay = random.randint(0, config.random_delay) if config.random_delay > 0 else 0
            if delay > 0:
                ui_print(f"⏳ 随机错峰等待 {delay} 秒 (约 {delay / 60.0:.1f} 分钟)...")
                time.sleep(delay)

            ui_print(f"⏰ 到达定时时间，开始执行签到...")
            try:
                run_once(config)
            except Exception as e:
                ui_print(f"❌ 运行发生未捕获异常: {e}")

        time.sleep(20)


# ============================================================
# 入口函数
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="宜家 (IKEA) 每日自动签到脚本")
    parser.add_argument("--check", action="store_true", help="仅查询积分与状态，不签到")
    parser.add_argument("--loop", action="store_true", help="常驻后台每天定时运行")
    parser.add_argument("--config", type=str, default="", help="指定配置文件路径")
    parser.add_argument("--debug", action="store_true", help="输出调试日志")

    args = parser.parse_args()

    debug = args.debug or _env("DEBUG") in ("1", "true", "yes")
    set_debug(debug)

    config = load_config(config_path=args.config)

    # 默认直接执行单次签到（青龙面板无需添加任何参数）
    if args.loop:
        run_loop(config)
    else:
        sys.exit(run_once(config, only_check=args.check))


if __name__ == "__main__":
    main()
