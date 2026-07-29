#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
夸克网盘自动签到

new Env('夸克自动签到')
cron: 0 8 * * *

================================================================
使用方法
================================================================

一、抓取签到参数（一次性，只需做一次）

    iOS 用户可以直接用仓库自带的 Quantumult X 脚本抓包：
      quark/quantumultx/quark_reward_capture.js
      quark/quantumultx/quark_reward_capture.snippet.conf
    参见 quark/quantumultx/ 目录的说明。

    通用抓包步骤（Charles / Stream / QX 均可）：
      1. 在手机上开启抓包代理，安装并信任对应 CA 证书
      2. 打开夸克 App，进入「我的 → 会员中心 / 抽奖页」
      3. 抓到 URL 为
             https://drive-m.quark.cn/1/clouddrive/act/growth/reward
         的请求
      4. 复制该请求「完整 URL」（后面必须带 kps、sign、vcode 三个参数）

二、写入环境变量（青龙 / 本地均可）

    方式 A（推荐）：QUARK_ACCOUNTS —— JSON 数组，多账号最清晰

      [
        {"name": "张三", "url": "https://drive-m.quark.cn/1/clouddrive/act/growth/reward?...&kps=xxx&sign=yyy&vcode=zzz"},
        {"name": "李四", "kps": "xxx", "sign": "yyy", "vcode": "zzz"}
      ]

      青龙里粘贴时必须是**一整行**合法 JSON；密码 / URL 中若有 " 需转义。

    方式 B（兼容旧格式）：COOKIE_QUARK —— 分号分隔字段，多账号用「回车」或「&&」

      推荐子写法（URL 整段贴进来，脚本自动解析）：
        user=张三; url=https://drive-m.quark.cn/1/clouddrive/act/growth/reward?...&kps=xxx&sign=yyy&vcode=zzz

      兼容子写法（拆开三个字段）：
        user=张三; kps=xxx; sign=yyy; vcode=zzz

    两个变量同时存在时以 QUARK_ACCOUNTS 优先。
    user / name 是自定义备注，多账号方便区分。

三、（可选）Bark 通知

    环境变量（与 hifiti / wangchao 等脚本共用同一套）：
      BARK_URL     完整推送地址，如 https://api.day.app/你的Key/
      或 BARK_KEY  只填 Key，服务器用 BARK_SERVER（默认 https://api.day.app）
      BARK_GROUP   分组名，默认「夸克签到」
      BARK_SOUND   铃声，可选
      BARK_ICON    图标 URL，可选
      BARK_LEVEL   通知级别（active / timeSensitive / passive），可选

    未配置 Bark 时脚本会自动跳过推送，只打印本地日志。
    同时也兼容青龙原生的 notify.py（若存在则一并触发）。

四、依赖

    青龙：依赖管理里添加 requests 即可
    本地：pip install requests

================================================================
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

SCRIPT_DIR = Path(__file__).resolve().parent

# ============================================================
# 常量
# ============================================================

QUARK_API = "https://drive-m.quark.cn/1/clouddrive/capacity/growth"
CORAL_API = "https://coral2.quark.cn/currency/v1/queryBalance"
DEFAULT_BARK_SERVER = "https://api.day.app"
DEFAULT_BARK_GROUP = "夸克签到"
TIMEOUT = 20

# ============================================================
# 通知（青龙 notify.py 可选）
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
# Bark 配置 & 推送
# ============================================================

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


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


def load_bark_config() -> BarkConfig:
    url = _env("BARK_URL") or _env("BARK_PUSH")
    key = _env("BARK_KEY") or _env("BARK_DEVICE_KEY")
    # BARK_URL 里只填了 key 时归到 key
    if url and not url.startswith("http"):
        key = key or url
        url = ""
    return BarkConfig(
        url=url,
        key=key,
        server=_env("BARK_SERVER", DEFAULT_BARK_SERVER).rstrip("/"),
        group=_env("BARK_GROUP", DEFAULT_BARK_GROUP),
        sound=_env("BARK_SOUND"),
        icon=_env("BARK_ICON"),
        level=_env("BARK_LEVEL"),
    )


def _bark_endpoint(cfg: BarkConfig) -> Optional[str]:
    if cfg.url:
        return cfg.url.strip().rstrip("/")
    if cfg.key:
        return f"{cfg.server.rstrip('/')}/{cfg.key.strip()}"
    return None


def send_bark(cfg: BarkConfig, title: str, body: str) -> None:
    endpoint = _bark_endpoint(cfg)
    if not endpoint:
        return
    payload: dict[str, Any] = {
        "title": title,
        "body": body,
        "group": cfg.group or DEFAULT_BARK_GROUP,
    }
    if cfg.sound:
        payload["sound"] = cfg.sound
    if cfg.icon:
        payload["icon"] = cfg.icon
    if cfg.level:
        payload["level"] = cfg.level
    try:
        r = requests.post(endpoint, json=payload, timeout=15)
        if r.status_code >= 400:
            get_url = (
                f"{endpoint}/{quote(title, safe='')}/{quote(body, safe='')}"
            )
            r = requests.get(get_url, timeout=15)
        print(f"📣 Bark 已推送（HTTP {r.status_code}）")
    except Exception as e:
        print(f"📣 Bark 推送失败: {e}")


# ============================================================
# 环境变量解析
# ============================================================

def get_env() -> list[str]:
    # 方式 A（推荐）：QUARK_ACCOUNTS JSON 数组
    json_raw = os.environ.get("QUARK_ACCOUNTS")
    if json_raw:
        parsed = _parse_accounts_json(json_raw)
        if parsed:
            return parsed

    # 方式 B（兼容旧格式）：COOKIE_QUARK，分号字段 + \n/&& 分隔多账号
    raw = os.environ.get("COOKIE_QUARK")
    if raw:
        return [x.strip() for x in re.split(r"\n|&&", raw) if x.strip()]

    # 方式 C（本地兜底）：config.yaml
    yaml_cookies = _load_cookies_from_yaml()
    if yaml_cookies:
        return yaml_cookies

    print("❌ 未配置账号：请设置 QUARK_ACCOUNTS 或 COOKIE_QUARK 环境变量，或提供 config.yaml")
    if _ql_notify:
        _ql_notify("夸克自动签到", "❌ 未配置账号：QUARK_ACCOUNTS / COOKIE_QUARK 均缺失")
    sys.exit(0)


def _parse_accounts_json(raw: str) -> list[str]:
    """
    QUARK_ACCOUNTS 支持 JSON 数组或单个 JSON 对象，字段与 config.yaml 对齐：
      [
        {"name": "张三", "url": "https://drive-m.quark.cn/1/clouddrive/act/growth/reward?...&kps=..&sign=..&vcode=.."},
        {"name": "李四", "kps": "...", "sign": "...", "vcode": "..."}
      ]
    也允许 name 缺省。字段名 name / user 等价。
    """
    import json as _json
    try:
        data = _json.loads(raw)
    except Exception as e:
        print(f"⚠️  QUARK_ACCOUNTS 不是合法 JSON: {e}，尝试回退到 COOKIE_QUARK")
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        print("⚠️  QUARK_ACCOUNTS 顶层应为 JSON 数组或对象，忽略")
        return []
    out: list[str] = []
    for acc in data:
        if not isinstance(acc, dict):
            continue
        parts: list[str] = []
        name = acc.get("name") or acc.get("user")
        if name:
            parts.append(f"user={name}")
        if acc.get("url"):
            parts.append(f"url={acc['url']}")
        for k in ("kps", "sign", "vcode"):
            if acc.get(k):
                parts.append(f"{k}={acc[k]}")
        if parts:
            out.append("; ".join(parts))
    return out


def _load_cookies_from_yaml() -> list[str]:
    """
    读取本地 config.yaml 的 accounts 列表；青龙里通常没有 yaml 也没装 PyYAML。
    支持：
      accounts:
        - name: 张三
          url: "https://drive-m.quark.cn/1/clouddrive/act/growth/reward?...&kps=..&sign=..&vcode=.."
        - name: 李四
          kps: "..."
          sign: "..."
          vcode: "..."
    """
    cfg_path = SCRIPT_DIR / "config.yaml"
    if not cfg_path.exists():
        return []
    try:
        import yaml  # type: ignore
    except ImportError:
        print("⚠️  发现 config.yaml 但未安装 PyYAML，跳过（青龙请用 COOKIE_QUARK 环境变量）")
        return []
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"⚠️  config.yaml 解析失败: {e}")
        return []
    accounts = data.get("accounts") or []
    out: list[str] = []
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        parts: list[str] = []
        if acc.get("name"):
            parts.append(f"user={acc['name']}")
        if acc.get("url"):
            parts.append(f"url={acc['url']}")
        for k in ("kps", "sign", "vcode"):
            if acc.get(k):
                parts.append(f"{k}={acc[k]}")
        if parts:
            out.append("; ".join(parts))
    # yaml 里的 bark 配置回填到 env（仅当 env 未设时）
    notify = data.get("notify") or {}
    for env_key, yaml_key in (
        ("BARK_URL", "bark_url"),
        ("BARK_KEY", "bark_key"),
        ("BARK_SERVER", "bark_server"),
        ("BARK_GROUP", "bark_group"),
        ("BARK_SOUND", "bark_sound"),
        ("BARK_ICON", "bark_icon"),
        ("BARK_LEVEL", "bark_level"),
    ):
        if not os.environ.get(env_key) and notify.get(yaml_key):
            os.environ[env_key] = str(notify[yaml_key])
    return out


def extract_params(url: str) -> dict[str, str]:
    query = url.split("?", 1)[1] if "?" in url else ""
    params: dict[str, str] = {}
    for part in query.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k] = v
    return {
        "kps": params.get("kps", ""),
        "sign": params.get("sign", ""),
        "vcode": params.get("vcode", ""),
    }


def parse_account(cookie_str: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for seg in cookie_str.replace(" ", "").split(";"):
        if "=" in seg:
            k, v = seg.split("=", 1)
            data[k] = v
    if "url" in data:
        data.update(extract_params(data["url"]))
    return data


# ============================================================
# 夸克接口
# ============================================================

def convert_bytes(b: float) -> str:
    units = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = 0
    while b >= 1024 and i < len(units) - 1:
        b /= 1024
        i += 1
    return f"{b:.2f} {units[i]}"


@dataclass
class SignResult:
    name: str
    ok: bool = False
    vip: str = ""                 # 88VIP / 普通用户
    total_capacity: str = ""      # 网盘总容量
    sign_total: str = ""          # 签到累计容量
    already: bool = False         # 今日是否已签
    today_reward: str = ""        # 今日奖励（人类可读）
    progress: str = ""            # 连签进度 3/7
    message: str = ""             # 失败原因


class Quark:
    def __init__(self, user_data: dict[str, str]) -> None:
        self.p = user_data
        self.name = user_data.get("user") or "未命名"

    def _query(self) -> dict[str, str]:
        return {
            "pr": "ucpro",
            "fr": "android",
            "kps": self.p.get("kps", ""),
            "sign": self.p.get("sign", ""),
            "vcode": self.p.get("vcode", ""),
        }

    def growth_info(self) -> Optional[dict[str, Any]]:
        try:
            r = requests.get(
                f"{QUARK_API}/info", params=self._query(), timeout=TIMEOUT
            ).json()
        except Exception as e:
            print(f"⚠️  growth/info 请求异常: {e}")
            return None
        return r.get("data") or None

    def growth_sign(self) -> tuple[bool, Any]:
        try:
            r = requests.post(
                f"{QUARK_API}/sign",
                params=self._query(),
                json={"sign_cyclic": True},
                timeout=TIMEOUT,
            ).json()
        except Exception as e:
            return False, f"请求异常: {e}"
        if r.get("data"):
            return True, r["data"]["sign_daily_reward"]
        return False, r.get("message") or "未知错误"

    def do_sign(self) -> SignResult:
        res = SignResult(name=self.name)
        info = self.growth_info()
        if not info:
            res.message = "获取成长信息失败（kps/sign/vcode 可能已过期）"
            return res

        res.vip = "88VIP" if info.get("88VIP") else "普通用户"
        res.total_capacity = convert_bytes(info.get("total_capacity", 0))
        sign_reward_bytes = (info.get("cap_composition") or {}).get(
            "sign_reward", 0
        )
        res.sign_total = convert_bytes(sign_reward_bytes)

        cap_sign = info.get("cap_sign") or {}
        target = cap_sign.get("sign_target", 7)
        progress = cap_sign.get("sign_progress", 0)

        if cap_sign.get("sign_daily"):
            res.ok = True
            res.already = True
            res.today_reward = convert_bytes(
                cap_sign.get("sign_daily_reward", 0)
            )
            res.progress = f"{progress}/{target}"
            return res

        ok, ret = self.growth_sign()
        if ok:
            res.ok = True
            res.today_reward = convert_bytes(ret)
            res.progress = f"{progress + 1}/{target}"
        else:
            res.message = str(ret)
        return res


# ============================================================
# 展示 / 格式化
# ============================================================

BAR = "═" * 48


def print_banner(title: str) -> None:
    print(BAR)
    print(f"  {title}")
    print(BAR)


def print_account_block(idx: int, total: int, res: SignResult) -> None:
    print()
    print(f"┌─ 🙍 账号 {idx}/{total} · {res.name}")
    if not res.ok and not res.total_capacity:
        # 完全失败
        print(f"│  ❌ 签到失败：{res.message}")
        print("└" + "─" * 47)
        return
    print(f"│  🏷️  身份：{res.vip}")
    print(f"│  💾 网盘总容量：{res.total_capacity}")
    print(f"│  📦 签到累计：{res.sign_total}")
    if res.already:
        print(f"│  ✅ 今日已签：+{res.today_reward}  连签 {res.progress}")
    elif res.ok:
        print(f"│  ✅ 签到成功：+{res.today_reward}  连签 {res.progress}")
    else:
        print(f"│  ❌ 签到失败：{res.message}")
    print("└" + "─" * 47)


def format_bark_body(results: list[SignResult]) -> str:
    """Bark / 汇总通知的正文（多行，紧凑排版）"""
    lines: list[str] = []
    lines.append(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    ok_n = sum(1 for r in results if r.ok)
    total = len(results)

    for i, r in enumerate(results, 1):
        prefix = "✅" if r.ok else "❌"
        lines.append(f"{prefix} #{i} {r.name}")

        if not r.ok and not r.total_capacity:
            lines.append(f"   ⚠️ {r.message}")
        else:
            lines.append(f"   🏷️ {r.vip} · 💾 {r.total_capacity}")
            lines.append(f"   📦 累计 {r.sign_total}")
            if r.already:
                lines.append(
                    f"   ✍️ 今日已签 +{r.today_reward} · 连签 {r.progress}"
                )
            elif r.ok:
                lines.append(
                    f"   ✨ 签到成功 +{r.today_reward} · 连签 {r.progress}"
                )
            else:
                lines.append(f"   ⚠️ 签到失败：{r.message}")

        if i < total:
            lines.append("")

    lines.append("")
    lines.append("────────")
    fail_n = total - ok_n
    if fail_n == 0:
        lines.append(f"📊 合计：{ok_n}/{total} 全部成功 🎉")
    elif ok_n == 0:
        lines.append(f"📊 合计：0/{total} 全部失败")
    else:
        lines.append(f"📊 合计：成功 {ok_n} · 失败 {fail_n}（共 {total} 号）")
    return "\n".join(lines)


def format_bark_title(results: list[SignResult]) -> str:
    total = len(results)
    ok_n = sum(1 for r in results if r.ok)
    if total == 0:
        return "夸克签到"
    if ok_n == total:
        return f"夸克签到 ✅ {ok_n}/{total}"
    if ok_n == 0:
        return f"夸克签到 ❌ 0/{total}"
    return f"夸克签到 ⚠️ {ok_n}/{total}"


# ============================================================
# 主流程
# ============================================================

def main() -> None:
    print_banner("🐬 夸克网盘 · 自动签到")
    cookies = get_env()
    print(f"🔍 检测到 {len(cookies)} 个账号")

    results: list[SignResult] = []
    for i, raw in enumerate(cookies, 1):
        user = parse_account(raw)
        res = Quark(user).do_sign()
        results.append(res)
        print_account_block(i, len(cookies), res)

    print()
    print_banner("📝 签到汇总")
    body = format_bark_body(results)
    print(body)
    print(BAR)

    # 通知：Bark 优先，兼容青龙 notify.py
    title = format_bark_title(results)
    bark = load_bark_config()
    if bark.enabled():
        send_bark(bark, title, body)
    else:
        print("📣 未配置 Bark（BARK_URL / BARK_KEY），跳过 Bark 推送")

    if _ql_notify:
        try:
            _ql_notify(title, body)
            print("📣 青龙 notify 已推送")
        except Exception as e:
            print(f"📣 青龙 notify 推送失败: {e}")


if __name__ == "__main__":
    main()
