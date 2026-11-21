#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1KF 会员中心（vip.1kf.com）每日签到

cron: 0 8 * * *
new Env('1KF每日签到');

流程：Cookie 校验登录态 → 签到（/qiandao 拿 csrf → POST /public/sign_ajax.php）
      → 可选积分抽奖（/choujiang，默认关）→ 积分够线自动兑换余额（/exchange_logs）

青龙环境变量（账号，二选一）：
  KF_ACCOUNTS  推荐。JSON 数组
    [{"name":"主号","cookie":"session_token=...; PHPSESSID=..."}]
  KF_COOKIE    兼容旧脚本。Cookie 串，多账号用 & 或换行分隔
    ⚠️ 站点规则：一人一号，多号必封，建议只配一个

可选：
  KF_LOTTERY        1=开启积分抽奖（每次 10 积分），默认 0
  KF_LOTTERY_TIMES  每次最多抽几轮，默认 1（上限 30）
  KF_EXCHANGE       1=积分够线自动兑换余额，默认 1
  KF_EXCHANGE_MIN   兑换门槛（积分），默认 20（站点最低 20 起兑）
  KF_EXCHANGE_ALL   1=全部兑光；默认 0=只兑 20 的整数倍留零头
  KF_TIMEOUT        请求超时秒，默认 20
  KF_INTER_ACCOUNT_DELAY  多账号间隔秒，默认 5

通知（与仓库其它脚本共用）：
  BARK_URL / BARK_KEY / BARK_SERVER / BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL
  SERVERCHAN_KEY / WEBHOOK_URL

依赖：requests（本地用 config.yaml 时再加 PyYAML）

注册/登录：https://vip.1kf.com/index?t=13392 （微信扫码）
逻辑参考：ql.xmox.cn 脚本库《1KF每日低保》，端点与页面结构已按现网实测修正
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

cache_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

BASE = "https://vip.1kf.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
DEFAULT_BARK_SERVER = "https://api.day.app"
SCRIPT_DIR = Path(__file__).resolve().parent

logger = logging.getLogger("1kf")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    cookie: str = ""

    def has_cookie(self) -> bool:
        return bool(self.cookie.strip())

    def normalize(self) -> None:
        self.cookie = self.cookie.strip()
        if self.cookie.lower().startswith("cookie:"):
            self.cookie = self.cookie.split(":", 1)[1].strip()
        if not self.name:
            self.name = "account"


@dataclass
class NotifyConfig:
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = "1KF签到"
    bark_sound: str = ""
    bark_icon: str = ""
    bark_level: str = ""
    serverchan_key: str = ""
    webhook_url: str = ""

    def enabled(self) -> bool:
        return bool(
            self.bark_url
            or self.bark_key
            or self.serverchan_key
            or self.webhook_url
        )


@dataclass
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    timeout: int = 20
    lottery: bool = False
    lottery_times: int = 1
    exchange: bool = True
    exchange_min: float = 20.0
    exchange_all: bool = False
    inter_account_delay: int = 5
    notify: NotifyConfig = field(default_factory=NotifyConfig)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    v = _env(name)
    if not v:
        return default
    return v.lower() in ("1", "true", "yes", "on", "y")


def parse_cookie(raw: str) -> dict[str, str]:
    """支持 'k=v; k2=v2' 或直接粘贴报头值。返回 dict。"""
    out: dict[str, str] = {}
    for part in re.split(r"[;\n]", raw):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        if k.lower() in ("path", "domain", "expires", "max-age", "samesite",
                         "secure", "httponly"):
            continue
        out[k] = v.strip()
    return out


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
        bark_group=_env("BARK_GROUP", "1KF签到"),
        bark_sound=_env("BARK_SOUND"),
        bark_icon=_env("BARK_ICON"),
        bark_level=_env("BARK_LEVEL"),
        serverchan_key=_env("SERVERCHAN_KEY") or _env("PUSH_KEY"),
        webhook_url=_env("WEBHOOK_URL"),
    )


def load_accounts_from_env() -> list[Account]:
    raw = _env("KF_ACCOUNTS")
    if raw:
        data = json.loads(raw)
        out = []
        for i, item in enumerate(data, 1):
            acc = Account(
                name=str(item.get("name") or f"账号{i}"),
                cookie=str(item.get("cookie") or ""),
            )
            acc.normalize()
            out.append(acc)
        return out
    out = []
    for i, block in enumerate(re.split(r"[\n&]+", _env("KF_COOKIE")), 1):
        block = block.strip()
        if not block or "=" not in block:
            continue
        acc = Account(name=f"账号{i}", cookie=block)
        acc.normalize()
        out.append(acc)
    return out


def load_config_from_env() -> Optional[AppConfig]:
    accounts = load_accounts_from_env()
    if not accounts:
        return None
    try:
        lottery_times = int(_env("KF_LOTTERY_TIMES", "1"))
    except ValueError:
        lottery_times = 1
    try:
        exchange_min = float(_env("KF_EXCHANGE_MIN", "20"))
    except ValueError:
        exchange_min = 20.0
    return AppConfig(
        accounts=accounts,
        timeout=int(_env("KF_TIMEOUT", "20")),
        lottery=_env_bool("KF_LOTTERY", False),
        lottery_times=max(0, min(lottery_times, 30)),
        exchange=_env_bool("KF_EXCHANGE", True),
        exchange_min=max(20.0, exchange_min),  # 站点最低 20 积分起兑
        exchange_all=_env_bool("KF_EXCHANGE_ALL", False),
        inter_account_delay=int(_env("KF_INTER_ACCOUNT_DELAY", "5")),
        notify=load_notify_from_env(),
    )


def load_config_yaml(path: Path) -> AppConfig:
    try:
        import yaml
    except ImportError as e:
        raise ImportError("本地 yaml 配置需要 PyYAML：pip install PyYAML") from e
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    accounts: list[Account] = []
    for i, item in enumerate(raw.get("accounts") or []):
        if not isinstance(item, dict):
            raise ValueError(f"accounts[{i}] 格式错误")
        acc = Account(
            name=str(item.get("name") or f"账号{i + 1}"),
            cookie=str(item.get("cookie") or ""),
        )
        acc.normalize()
        if not acc.has_cookie():
            raise ValueError(f"账号 [{acc.name}] 未配置 cookie")
        accounts.append(acc)
    if not accounts:
        raise ValueError("配置中 accounts 为空")

    n = raw.get("notify") or {}
    env_notify = load_notify_from_env()
    notify = NotifyConfig(
        bark_url=env_notify.bark_url or str(n.get("bark_url") or ""),
        bark_key=env_notify.bark_key or str(n.get("bark_key") or ""),
        bark_server=str(n.get("bark_server") or env_notify.bark_server or DEFAULT_BARK_SERVER).rstrip("/"),
        bark_group=env_notify.bark_group if _env("BARK_GROUP") else str(n.get("bark_group") or "1KF签到"),
        bark_sound=env_notify.bark_sound or str(n.get("bark_sound") or ""),
        bark_icon=env_notify.bark_icon or str(n.get("bark_icon") or ""),
        bark_level=env_notify.bark_level or str(n.get("bark_level") or ""),
        serverchan_key=env_notify.serverchan_key or str(n.get("serverchan_key") or ""),
        webhook_url=env_notify.webhook_url or str(n.get("webhook_url") or ""),
    )

    cfg_env = load_config_from_env()
    return AppConfig(
        accounts=accounts,
        timeout=int(_env("KF_TIMEOUT") or raw.get("timeout") or 20),
        lottery=_env_bool("KF_LOTTERY", bool(raw.get("lottery", False))),
        lottery_times=int(_env("KF_LOTTERY_TIMES") or raw.get("lottery_times") or 1),
        exchange=_env_bool("KF_EXCHANGE", bool(raw.get("exchange", True))),
        exchange_min=max(20.0, float(_env("KF_EXCHANGE_MIN") or raw.get("exchange_min") or 20)),
        exchange_all=_env_bool("KF_EXCHANGE_ALL", bool(raw.get("exchange_all", False))),
        inter_account_delay=int(_env("KF_INTER_ACCOUNT_DELAY") or raw.get("inter_account_delay") or 5),
        notify=notify,
    ) if not cfg_env else cfg_env


# ---------------------------------------------------------------------------
# 1KF 客户端
# ---------------------------------------------------------------------------

class KfClient:
    def __init__(self, account: Account, cfg: AppConfig):
        self.account = account
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BASE + "/qiandao",
            "Origin": BASE,
        })
        for k, v in parse_cookie(account.cookie).items():
            self.session.cookies.set(k, v, domain="vip.1kf.com", path="/")
        self.uid = ""
        self.csrf = ""
        self.points: Optional[float] = None
        self.rate = 20.0

    def get(self, path: str) -> requests.Response:
        r = self.session.get(BASE + path, timeout=self.cfg.timeout)
        r.encoding = "utf-8"
        return r

    def post(self, path: str, data: dict[str, Any]) -> requests.Response:
        r = self.session.post(BASE + path, data=data, timeout=self.cfg.timeout)
        r.encoding = "utf-8"
        return r

    def post_json(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        r = self.post(path, data)
        try:
            return r.json()
        except Exception:
            snippet = re.sub(r"\s+", " ", r.text)[:200]
            raise RuntimeError(f"{path} 返回非 JSON（HTTP {r.status_code}）：{snippet}")

    # ---- 状态解析 -------------------------------------------------------
    def fetch_state(self) -> dict[str, Any]:
        """打开签到页，解析 登录态/签到状态/连签/csrf。"""
        r = self.get("/qiandao")
        if r.status_code != 200:
            raise RuntimeError(f"打开签到页失败 HTTP {r.status_code}")
        html = r.text
        st: dict[str, Any] = {"logged_in": False, "uid": None, "signed": False,
                              "streak": None, "csrf": None}

        m = re.search(r'VIP-username[^>]*>\s*(?:ID#)?(\d+)', html)
        if m:
            st["logged_in"] = True
            st["uid"] = m.group(1)
        if "退出登录" in html or "logout=1" in html:
            st["logged_in"] = True
        if not st["logged_in"]:
            raise RuntimeError("Cookie 已失效或未登录（页面没有用户信息），请重新获取")

        # 未签到特征：存在可点的「立即签到」提交按钮（现网实测）
        if re.search(r'name="sign_submit"[^>]*>\s*<i[^>]*>\s*</i>\s*立即签到', html) \
                or re.search(r'name="sign_submit"[^>]*value="1"', html) and "立即签到" in html:
            st["signed"] = False
        elif re.search(r"今日已签到|已签到\s*</button>|SIGN-status-info signed", html):
            st["signed"] = True

        m = re.search(r"已连续签到\s*<strong[^>]*>\s*(\d+)\s*</strong>", html)
        if m:
            st["streak"] = int(m.group(1))
        m = re.search(r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)', html)
        if m:
            st["csrf"] = m.group(1)

        self.uid = st["uid"] or ""
        self.csrf = st["csrf"] or ""
        return st

    # ---- 签到 -----------------------------------------------------------
    def sign(self) -> tuple[bool, str]:
        res = self.post_json("/public/sign_ajax.php", {"csrf_token": self.csrf})
        if res.get("success"):
            msg = res.get("message") or "签到成功"
            extra = []
            if res.get("streak_msg"):
                extra.append(res["streak_msg"])
            if res.get("qiyu_msg"):
                extra.append(res["qiyu_msg"])
            if res.get("sign_streak"):
                extra.append(f"连续{res['sign_streak']}天")
            return True, msg + ("（" + "；".join(extra) + "）" if extra else "")
        return False, res.get("message") or json.dumps(res, ensure_ascii=False)[:200]

    # ---- 抽奖 -----------------------------------------------------------
    def lottery(self) -> tuple[bool, str]:
        res = self.post_json("/choujiang", {"action": "draw"})
        if res.get("code") != 0:
            return False, res.get("msg") or res.get("message") or json.dumps(res, ensure_ascii=False)[:120]
        prize = res.get("prize") or {}
        pname = {"balance": "元余额", "points": "积分", "growth": "经验值",
                 "shiwubi": "实物币", "quiz_points": "活动点"}
        ptype = prize.get("prize_type") or ""
        pval = prize.get("prize_value") or 0
        if res.get("msg"):
            text = res["msg"]
        elif float(pval or 0) > 0:
            text = f"+{pval}{pname.get(ptype, ptype)}"
        else:
            text = "谢谢参与"
        if res.get("is_time_rule_special"):
            text = "时段必中：" + text
        return True, text

    # ---- 资产 -----------------------------------------------------------
    def assets(self) -> dict[str, Any]:
        """从 /exchange_logs 读取 积分 / 余额 / 活动点（统计卡片，最可靠）"""
        out: dict[str, Any] = {}
        try:
            html = self.get("/exchange_logs").text
            st = self.parse_exchange(html)
            out.update({k: v for k, v in st.items() if v is not None})
            if "points" in out:
                self.points = out["points"]
            if st.get("rate"):
                self.rate = st["rate"]
        except Exception as e:
            logger.warning("[%s] 读取资产失败：%s", self.account.name, e)
        return out

    @staticmethod
    def parse_exchange(html: str) -> dict[str, Any]:
        """解析兑换页统计卡片：当前积分 / 当前余额 / 当前活动点；顺带拿兑换比例"""
        st: dict[str, Any] = {"points": None, "balance": None, "quiz_points": None, "rate": None}
        cards = re.findall(
            r'<div class="exchange-stat">\s*<div class="label">([^<]+)</div>\s*'
            r'<div class="value[^"]*"[^>]*>([^<]*)</div>', html)
        for label, value in cards:
            v = re.sub(r"[^\d.]", "", value)
            if not v:
                continue
            label = label.strip()
            if "积分" in label and "活动" not in label:
                st["points"] = float(v)
            elif "余额" in label:
                st["balance"] = float(v)
            elif "活动点" in label:
                st["quiz_points"] = float(v)
        m = re.search(r"1\s*元\s*=\s*<strong>([\d.]+)</strong>\s*积分", html)
        if m:
            st["rate"] = float(m.group(1))
        return st

    # ---- 兑换（积分 → 余额现金） -----------------------------------------
    def exchange(self, points: int) -> tuple[bool, str]:
        res = self.post_json("/exchange_logs", {"exchange_submit": 1, "points": points})
        if res.get("success"):
            msg = res.get("message") or "兑换成功"
            gain = int(points // (self.rate or 20.0))
            return True, f"{msg}（{points}积分 → 余额 +{gain}元）"
        return False, res.get("message") or json.dumps(res, ensure_ascii=False)[:160]

    # ---- 主流程 -----------------------------------------------------------
    def run(self) -> dict[str, Any]:
        acc = self.account
        result: dict[str, Any] = {
            "ok": False, "name": acc.name, "message": "", "uid": "",
            "points_before": None, "points_after": None,
            "balance_before": None, "balance_after": None,
            "signed": False, "lottery": "", "exchange": "", "steps": [],
        }

        before = self.assets()
        result["points_before"] = before.get("points")
        result["balance_before"] = before.get("balance")

        st = self.fetch_state()
        result["uid"] = self.uid
        logger.info("[%s] uid=%s 已签到=%s 连续=%s", acc.name, self.uid, st["signed"], st["streak"])

        # ---- 签到 ----
        if st["signed"]:
            result["signed"] = True
            result["message"] = f"今日已签到（连续 {st['streak'] or '?'} 天）"
            logger.info("[%s] ✅ %s", acc.name, result["message"])
        else:
            time.sleep(random.uniform(1, 3))
            try:
                ok, msg = self.sign()
            except Exception as e:
                ok, msg = False, str(e)
            result["signed"] = ok
            result["message"] = ("签到成功：" if ok else "签到失败：") + msg
            logger.info("[%s] %s %s", acc.name, "✅" if ok else "❌", result["message"])
        result["steps"].append("sign:" + ("ok" if result["signed"] else "fail"))

        # ---- 抽奖（默认关闭，积分留着兑换现金更划算） ----
        if self.cfg.lottery and self.cfg.lottery_times > 0:
            results = []
            for i in range(self.cfg.lottery_times):
                self.points = None
                self.assets()
                pts = self.points
                if pts is not None and pts >= 10 and pts >= self.cfg.exchange_min:
                    results.append(f"积分 {pts:g} 已达兑换线，不再抽奖")
                    break
                if pts is not None and pts < 10:
                    results.append(f"积分 {pts:g} 不足 10，跳过抽奖")
                    break
                time.sleep(random.uniform(2, 4))
                try:
                    ok, txt = self.lottery()
                except Exception as e:
                    ok, txt = False, str(e)
                logger.info("[%s] 第%d次抽奖：%s %s", acc.name, i + 1, ok, txt)
                results.append(("✅ " if ok else "⚠️ ") + f"第{i + 1}抽：{txt}")
                if not ok:
                    break
            result["lottery"] = " | ".join(results)

        # ---- 积分兑换余额（现金） ----
        if self.cfg.exchange:
            self.points = None
            after_assets = self.assets()
            pts = self.points
            rate = self.rate or 20.0
            if pts is None:
                result["exchange"] = "读取积分失败，跳过"
            elif pts < self.cfg.exchange_min:
                result["exchange"] = f"积分 {pts:g} < {self.cfg.exchange_min:g}，未达兑换线"
            else:
                to_ex = int(pts) if self.cfg.exchange_all else int(pts // rate * rate)
                time.sleep(random.uniform(1, 3))
                try:
                    ok, msg = self.exchange(to_ex)
                except Exception as e:
                    ok, msg = False, str(e)
                if ok:
                    logger.info("[%s] 💰 兑换成功：%s", acc.name, msg)
                    result["exchange"] = msg
                else:
                    logger.warning("[%s] ❌ 兑换失败：%s", acc.name, msg)
                    result["exchange"] = "兑换失败：" + msg

        self.points = None
        after = self.assets()
        result["points_after"] = after.get("points")
        result["balance_after"] = after.get("balance")

        result["ok"] = result["signed"]
        if not result["message"]:
            result["message"] = "完成"
        return result


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------

def _fmt_num(v: Optional[float]) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else "-"


def format_summary(account_results: list[tuple[str, dict[str, Any]]]) -> str:
    from datetime import datetime as _dt

    lines: list[str] = [f"📅 {_dt.now().strftime('%m-%d %H:%M')}", ""]
    ok_n = sum(1 for _, r in account_results if r.get("ok"))
    fail_n = len(account_results) - ok_n

    for i, (name, r) in enumerate(account_results):
        ok = bool(r.get("ok"))
        lines.append(f"{'✅' if ok else '❌'} {name}" + (f"（uid {r['uid']}）" if r.get("uid") else ""))
        msg = str(r.get("message") or "").strip()
        lines.append(f"   {'✅' if ok else '❌'} {msg}")

        pb, pa = r.get("points_before"), r.get("points_after")
        bb, ba = r.get("balance_before"), r.get("balance_after")
        if isinstance(pa, (int, float)):
            delta = ""
            if isinstance(pb, (int, float)):
                d = round(pa - pb, 2)
                if abs(d) > 0:
                    delta = f"（{d:+g}）"
            lines.append(f"   💰 积分：{_fmt_num(pa)}{delta}")
        if isinstance(ba, (int, float)):
            lines.append(f"   💵 余额：¥{ba:.2f}")
        if r.get("lottery"):
            lines.append(f"   🎰 {r['lottery']}")
        if r.get("exchange"):
            lines.append(f"   💱 {r['exchange']}")
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
    base = "1KF每日签到"
    if n == 0:
        return base
    if ok_n == n:
        base += f" ✅ {ok_n}/{n}"
    elif ok_n == 0:
        base += f" ❌ 0/{n}"
    else:
        base += f" ⚠️ {ok_n}/{n}"
    total_delta = sum(
        (r.get("points_after") or 0) - (r.get("points_before") or 0)
        for _, r in account_results
        if isinstance(r.get("points_after"), (int, float))
        and isinstance(r.get("points_before"), (int, float))
    )
    if abs(total_delta) > 0:
        base += f" 积分{total_delta:+g}"
    return base


def _build_bark_endpoint(cfg: NotifyConfig) -> Optional[str]:
    if cfg.bark_url:
        return cfg.bark_url.strip().rstrip("/")
    if cfg.bark_key:
        server = (cfg.bark_server or DEFAULT_BARK_SERVER).rstrip("/")
        return f"{server}/{cfg.bark_key.strip()}"
    return None


def send_bark(cfg: NotifyConfig, title: str, body: str) -> None:
    endpoint = _build_bark_endpoint(cfg)
    if not endpoint:
        return
    payload = {"title": title, "body": body, "group": cfg.bark_group}
    if cfg.bark_sound:
        payload["sound"] = cfg.bark_sound
    if cfg.bark_icon:
        payload["icon"] = cfg.bark_icon
    if cfg.bark_level:
        payload["level"] = cfg.bark_level
    try:
        r = requests.post(endpoint, json=payload, timeout=15)
        if r.status_code >= 400:
            get_url = f"{endpoint}/{quote(title[:100], safe='')}/{quote(body[:500], safe='')}"
            r = requests.get(get_url, timeout=15)
        logger.info("📣 Bark %s（HTTP %s）", "已推送" if r.status_code < 400 else "失败", r.status_code)
    except Exception as e:
        logger.warning("📣 Bark 推送失败: %s", e)


def send_serverchan(key: str, title: str, content: str) -> None:
    try:
        r = requests.post(
            f"https://sctapi.ftqq.com/{key}.send",
            data={"title": title, "desp": content}, timeout=15,
        )
        logger.info("📣 Server酱 %s（HTTP %s）", "已推送" if r.status_code < 400 else "失败", r.status_code)
    except Exception as e:
        logger.warning("📣 Server酱 推送失败: %s", e)


def send_notify(cfg: NotifyConfig, title: str, content: str) -> None:
    sent = False
    if cfg.bark_url or cfg.bark_key:
        send_bark(cfg, title, content)
        sent = True
    if cfg.serverchan_key:
        send_serverchan(cfg.serverchan_key, title, content)
        sent = True
    if cfg.webhook_url:
        try:
            r = requests.post(cfg.webhook_url, json={"title": title, "content": content}, timeout=15)
            logger.info("📣 Webhook 已推送（HTTP %s）", r.status_code)
            sent = True
        except Exception as e:
            logger.warning("📣 Webhook 推送失败: %s", e)
    if not sent:
        logger.info("📣 未配置 Bark/通知渠道，跳过推送")


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
        "青龙：设置 KF_ACCOUNTS 或 KF_COOKIE\n"
        "本地：cp config.example.yaml config.yaml 并填写"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="1KF 会员中心每日签到（签到/抽奖/兑换）")
    parser.add_argument("-c", "--config", help="本地 yaml 配置路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    parser.add_argument("--check", action="store_true", help="只校验 Cookie 登录态，不签到")
    args = parser.parse_args()

    setup_logging(args.verbose)

    try:
        cfg = resolve_config(args)
    except Exception as e:
        logger.error("❌ %s", e)
        return 2

    logger.info("🚀 1KF · 每日签到")
    logger.info(
        "   账号 %d 个 · 通知 %s · 抽奖 %s · 兑换 %s",
        len(cfg.accounts),
        "开" if cfg.notify.enabled() else "关",
        f"开(≤{cfg.lottery_times}次)" if cfg.lottery else "关",
        f"开(≥{cfg.exchange_min:g}积分)" if cfg.exchange else "关",
    )

    account_results: list[tuple[str, dict[str, Any]]] = []
    for i, acc in enumerate(cfg.accounts):
        log_banner(f"👤 {acc.name}")
        try:
            client = KfClient(acc, cfg)
            if args.check:
                st = client.fetch_state()
                result = {"ok": True, "name": acc.name, "message": "Cookie 有效",
                          "uid": client.uid, "signed": st["signed"],
                          "points_before": None, "points_after": None,
                          "balance_before": None, "balance_after": None,
                          "lottery": "", "exchange": "", "steps": ["check"]}
            else:
                result = client.run()
        except Exception as e:
            logger.error("[%s] 💥 未处理异常: %s", acc.name, e)
            logger.debug("exception traceback", exc_info=True)
            result = {"ok": False, "name": acc.name, "message": str(e), "uid": "",
                      "points_before": None, "points_after": None,
                      "balance_before": None, "balance_after": None,
                      "lottery": "", "exchange": "", "steps": ["error"]}

        if result.get("ok"):
            logger.info("[%s] ✅ %s", acc.name, result.get("message") or "OK")
        else:
            logger.error("[%s] ❌ %s", acc.name, result.get("message") or "失败")
        account_results.append((acc.name, result))

        if i < len(cfg.accounts) - 1:
            logger.info("⏳ 等待 %d 秒后执行下一账号…", cfg.inter_account_delay)
            time.sleep(max(0, cfg.inter_account_delay))

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
