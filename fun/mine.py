#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FUN 矿池自动任务（登录 / 收矿 / 查状态 / 可选升级）

cron: 10 8 * * *
new Env('FUN矿池');

同一份脚本：青龙用环境变量，本地用 config.yaml。

青龙环境变量 FUN（必填，多账号 & 或换行）：
  手机号#密码#收矿#升级
  手机号#密码#收矿#升级#备注
  手机号#密码#收矿#升级#备注#短信验证码
  收矿/升级：1=开 0=关
  例：
    13800138000#pass#1#0#iPhone
    13900139000#pass#1#0#Android

本地：
  cp config.example.yaml config.yaml
  python3 mine.py
  python3 mine.py --captcha 123456   # 首次新设备绑定

新设备登录会下发短信验证码（HTTP 业务码 409）。
首次：跑一遍触发短信 → 填验证码再跑一遍完成绑定 → 删掉验证码。
设备指纹：青龙 /ql/data/fun_device_cache.json ；本地 fun/device_cache.json。

可选：
  FUN_NOTE=家里青龙          # 全局备注，进 Bark 标题
  FUN_CAPTCHA / FUN_SMS      # 本轮短信验证码（绑定成功后删掉）
  FUN_DEVICE_CACHE           # 设备缓存路径
  BARK_URL / BARK_KEY        # 通知（与仓库其它项目共用）
  BARK_SERVER / BARK_GROUP / BARK_SOUND
  FUN_BASE_URL               # 默认 https://exchange.acmes.dev/api/v1

依赖：requests ；本地 yaml 再装 PyYAML
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_BASE = "https://exchange.acmes.dev/api/v1"
DEFAULT_BARK = "https://api.day.app"
WEB_ORIGIN = "https://mexchange.acmes.dev"
UA = (
    "Mozilla/5.0 (Linux; Android 16; V2426A Build/BP2A.250605.031.A3_V000L1; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/134.0.6998.135 "
    "Mobile Safari/537.36 uni-app Html5Plus/1.0 (Immersed/42.0)"
)
ICONS = "⛏️💎🪙🏭⚙️🔋📡🏔️✨🌟"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def mask_mobile(m: str) -> str:
    m = (m or "").strip()
    if len(m) >= 7:
        return m[:3] + "****" + m[-4:]
    return m or "?"


# ---------------------------------------------------------------------------
# 账号
# ---------------------------------------------------------------------------

@dataclass
class Account:
    mobile: str
    password: str
    do_claim: bool = True
    do_upgrade: bool = False
    note: str = ""
    captcha: str = ""

    @property
    def label(self) -> str:
        if self.note:
            return self.note
        return mask_mobile(self.mobile)


def parse_accounts(raw: str) -> list[Account]:
    """
    手机号#密码#收矿#升级
    手机号#密码#收矿#升级#备注
    手机号#密码#收矿#升级#备注#短信验证码
    多账号 & 或换行
    """
    if not raw:
        return []
    text = raw.replace("\n", "&")
    out: list[Account] = []
    for i, part in enumerate(text.split("&")):
        part = part.strip()
        if not part or part.startswith("#"):
            continue
        bits = part.split("#")
        if len(bits) < 4:
            log(f"⚠️ 第 {i + 1} 段格式错误，需要 手机号#密码#收矿#升级[#备注][#验证码]：{part[:20]}…")
            continue
        mobile, pwd, claim_s, up_s = bits[0].strip(), bits[1], bits[2].strip(), bits[3].strip()
        note = bits[4].strip() if len(bits) >= 5 else ""
        captcha = bits[5].strip() if len(bits) >= 6 else ""
        out.append(
            Account(
                mobile=mobile,
                password=pwd,
                do_claim=claim_s == "1",
                do_upgrade=up_s == "1",
                note=note,
                captcha=captcha,
            )
        )
    return out


def _as_bool(v: Any, default: bool = True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on", "y"):
        return True
    if s in ("0", "false", "no", "off", "n", ""):
        return False
    return default


def running_on_qinglong() -> bool:
    return bool(_env("QL_DATA_DIR")) or Path("/ql/data").is_dir()


@dataclass
class AppConfig:
    accounts: list[Account]
    note: str = ""
    base_url: str = DEFAULT_BASE
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK
    bark_group: str = "FUN矿池"
    bark_sound: str = ""
    device_cache: str = ""
    captcha: str = ""
    source: str = ""  # env / yaml，仅日志


def resolve_captcha(acc: Account, cfg: Optional[AppConfig] = None) -> str:
    return (
        acc.captcha
        or (cfg.captcha if cfg else "")
        or _env("FUN_CAPTCHA")
        or _env("FUN_SMS")
    )


def captcha_hint() -> str:
    if running_on_qinglong():
        return (
            "青龙新增环境变量 FUN_CAPTCHA=验证码"
            "（或把验证码写到 FUN 第 6 段），立刻再运行本任务"
        )
    return (
        "本地任选其一后立刻再跑："
        " python3 mine.py --captcha 验证码"
        " ｜ export FUN_CAPTCHA=验证码"
        " ｜ 把验证码写进 config.yaml 该账号的 captcha"
    )


# ---------------------------------------------------------------------------
# 设备指纹缓存（官方登录 header：X-Device-Id = md5("web:" + 本地串)）
# ---------------------------------------------------------------------------

_ACTIVE_CFG: Optional[AppConfig] = None


def resolve_device_cache_path() -> Path:
    env = _env("FUN_DEVICE_CACHE")
    if env:
        return Path(env).expanduser()
    if _ACTIVE_CFG and _ACTIVE_CFG.device_cache:
        p = Path(_ACTIVE_CFG.device_cache).expanduser()
        return p if p.is_absolute() else (SCRIPT_DIR / p)
    ql_data = _env("QL_DATA_DIR")
    if ql_data:
        return Path(ql_data) / "fun_device_cache.json"
    if Path("/ql/data").is_dir():
        return Path("/ql/data") / "fun_device_cache.json"
    return SCRIPT_DIR / "device_cache.json"


def load_device_cache() -> dict[str, Any]:
    path = resolve_device_cache_path()
    if not path.is_file():
        legacy = SCRIPT_DIR / "device_cache.json"
        if legacy.is_file() and legacy != path:
            path = legacy
        else:
            return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def save_device_cache(cache: dict[str, Any]) -> None:
    path = resolve_device_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"   ⚠️ 设备缓存写入失败: {e}")


def _new_fallback_id() -> str:
    return f"{int(time.time() * 1000)}-{secrets.token_hex(4)}-{secrets.token_hex(4)}"


def _device_id_from_fallback(fallback: str) -> str:
    return hashlib.md5(f"web:{fallback}".encode("utf-8")).hexdigest()


def get_or_create_device(mobile: str, cache: dict[str, Any]) -> tuple[str, bool]:
    """返回 (device_id, created_now)。"""
    rec = cache.get(mobile)
    if not isinstance(rec, dict):
        rec = {}
    fallback = str(rec.get("fallback_id") or "").strip()
    did = str(rec.get("device_id") or "").strip()
    if fallback and did:
        cache[mobile] = rec
        return did, False
    fallback = fallback or _new_fallback_id()
    did = _device_id_from_fallback(fallback)
    rec.update({"fallback_id": fallback, "device_id": did, "bound": bool(rec.get("bound"))})
    cache[mobile] = rec
    save_device_cache(cache)
    return did, True


def mark_device_bound(mobile: str, device_id: str, cache: dict[str, Any]) -> None:
    rec = cache.get(mobile)
    if not isinstance(rec, dict):
        rec = {}
    rec["device_id"] = device_id
    rec["bound"] = True
    rec["bound_at"] = datetime.now().isoformat(timespec="seconds")
    cache[mobile] = rec
    save_device_cache(cache)


# ---------------------------------------------------------------------------
# 配置：青龙环境变量优先，本地 config.yaml 兜底
# ---------------------------------------------------------------------------

def _notify_from_env() -> dict[str, str]:
    url = _env("BARK_URL") or _env("BARK_PUSH")
    key = _env("BARK_KEY") or _env("BARK_DEVICE_KEY")
    if url and not url.startswith("http"):
        key = key or url
        url = ""
    return {
        "bark_url": url,
        "bark_key": key,
        "bark_server": _env("BARK_SERVER") or DEFAULT_BARK,
        "bark_group": _env("BARK_GROUP"),
        "bark_sound": _env("BARK_SOUND"),
    }


def load_config_from_env() -> Optional[AppConfig]:
    accounts = parse_accounts(_env("FUN"))
    if not accounts:
        return None
    n = _notify_from_env()
    return AppConfig(
        accounts=accounts,
        note=_env("FUN_NOTE") or _env("FUN_TAG"),
        base_url=_env("FUN_BASE_URL") or DEFAULT_BASE,
        bark_url=n["bark_url"],
        bark_key=n["bark_key"],
        bark_server=(n["bark_server"] or DEFAULT_BARK).rstrip("/"),
        bark_group=n["bark_group"] or "FUN矿池",
        bark_sound=n["bark_sound"],
        device_cache=_env("FUN_DEVICE_CACHE"),
        captcha=_env("FUN_CAPTCHA") or _env("FUN_SMS"),
        source="env",
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
        mobile = str(item.get("mobile") or item.get("phone") or "").strip()
        password = str(item.get("password") or item.get("pwd") or item.get("pass") or "")
        note = str(item.get("name") or item.get("note") or "").strip()
        captcha = str(item.get("captcha") or item.get("sms") or "").strip()
        if not mobile or not password:
            raise ValueError(f"accounts[{i}] 需要 mobile/phone + password")
        claim = item.get("claim", item.get("do_claim", True))
        upgrade = item.get("upgrade", item.get("do_upgrade", False))
        accounts.append(
            Account(
                mobile=mobile,
                password=password,
                do_claim=_as_bool(claim, True),
                do_upgrade=_as_bool(upgrade, False),
                note=note,
                captcha=captcha,
            )
        )

    if not accounts:
        raise ValueError(f"{path} 中 accounts 为空")

    n = raw.get("notify") or {}
    env_n = _notify_from_env()
    bark_url = env_n["bark_url"] or str(n.get("bark_url") or "")
    bark_key = env_n["bark_key"] or str(n.get("bark_key") or "")
    if bark_url and not bark_url.startswith("http"):
        bark_key = bark_key or bark_url
        bark_url = ""
    bark_server = (
        env_n["bark_server"]
        if (env_n["bark_url"] or env_n["bark_key"])
        else str(n.get("bark_server") or DEFAULT_BARK)
    ).rstrip("/")
    bark_group = env_n["bark_group"] or str(n.get("bark_group") or "FUN矿池")
    bark_sound = env_n["bark_sound"] or str(n.get("bark_sound") or "")

    return AppConfig(
        accounts=accounts,
        note=_env("FUN_NOTE") or _env("FUN_TAG") or str(raw.get("note") or raw.get("tag") or ""),
        base_url=_env("FUN_BASE_URL") or str(raw.get("base_url") or DEFAULT_BASE),
        bark_url=bark_url,
        bark_key=bark_key,
        bark_server=bark_server or DEFAULT_BARK,
        bark_group=bark_group or "FUN矿池",
        bark_sound=bark_sound,
        device_cache=_env("FUN_DEVICE_CACHE") or str(raw.get("device_cache") or ""),
        captcha=_env("FUN_CAPTCHA") or _env("FUN_SMS") or str(raw.get("captcha") or ""),
        source=str(path),
    )


def resolve_config(args: argparse.Namespace) -> AppConfig:
    if args.config:
        return load_config_yaml(Path(args.config))

    env_cfg = load_config_from_env()
    local = SCRIPT_DIR / "config.yaml"
    if env_cfg is not None:
        if local.is_file():
            log("📦 已用环境变量 FUN，本地 config.yaml 不会被读取")
        return env_cfg
    if local.is_file():
        return load_config_yaml(local)
    raise FileNotFoundError(
        "未找到账号配置。青龙请设环境变量 FUN；"
        f"本地请 cp config.example.yaml config.yaml 后填写，或 python3 mine.py -c 路径"
    )


# ---------------------------------------------------------------------------
# Bark
# ---------------------------------------------------------------------------

def bark_endpoint(cfg: Optional[AppConfig] = None) -> Optional[str]:
    cfg = cfg or _ACTIVE_CFG
    url = (cfg.bark_url if cfg else "") or _env("BARK_URL") or _env("BARK_PUSH")
    key = (cfg.bark_key if cfg else "") or _env("BARK_KEY") or _env("BARK_DEVICE_KEY")
    if url and not url.startswith("http"):
        key = key or url
        url = ""
    if url:
        return url.rstrip("/")
    if key:
        server = (
            (cfg.bark_server if cfg else "") or _env("BARK_SERVER") or DEFAULT_BARK
        ).rstrip("/")
        return f"{server}/{key}"
    return None


def send_bark(title: str, body: str, cfg: Optional[AppConfig] = None) -> None:
    cfg = cfg or _ACTIVE_CFG
    ep = bark_endpoint(cfg)
    if not ep:
        log("📣 未配置 BARK_URL/BARK_KEY，跳过推送")
        return
    if not ep.startswith("http"):
        ep = f"{DEFAULT_BARK.rstrip('/')}/{ep}"
    group = (cfg.bark_group if cfg else "") or _env("BARK_GROUP") or "FUN矿池"
    payload: dict[str, Any] = {
        "title": title[:200],
        "body": body[:3500],
        "group": group,
    }
    sound = (cfg.bark_sound if cfg else "") or _env("BARK_SOUND")
    if sound:
        payload["sound"] = sound
    try:
        r = requests.post(ep, json=payload, timeout=15)
        if r.status_code >= 400:
            get_url = (
                f"{ep}/"
                f"{quote(title[:100], safe='')}/"
                f"{quote(body[:500], safe='')}"
            )
            r = requests.get(get_url, params={"group": group}, timeout=15)
        ok = r.status_code < 400
        log(f"📣 Bark {'已推送' if ok else '失败'}（HTTP {r.status_code}）")
        if not ok:
            log(f"   响应: {(r.text or '')[:200]}")
    except Exception as e:
        log(f"📣 Bark 失败: {e}")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class FunClient:
    def __init__(self, base_url: str, device_id: str, timeout: float = 15.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.device_id = device_id
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": UA,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": WEB_ORIGIN,
                "Referer": f"{WEB_ORIGIN}/",
                "Connection": "Keep-Alive",
                "Accept-Encoding": "gzip",
                "X-Device-Id": device_id,
            }
        )
        self.token = ""

    def _headers(self) -> dict[str, str]:
        h = dict(self.session.headers)
        if self.token:
            h["token"] = self.token
        h["X-Device-Id"] = self.device_id
        return h

    def login(self, mobile: str, password: str, captcha: str = "") -> tuple[bool, str]:
        url = f"{self.base}/passport/login"
        try:
            r = self.session.post(
                url,
                json={
                    "mobile": mobile,
                    "password": password,
                    "phone": mobile,
                    "captcha": captcha or "",
                },
                headers=self._headers(),
                timeout=self.timeout,
            )
            ret = r.json()
        except Exception as e:
            log(f"   ❌ 登录网络错误: {e}")
            return False, f"网络: {e}"
        if not ret:
            log("   ❌ 登录返回空")
            return False, "登录返回空"

        code = ret.get("code")
        msg = str(ret.get("msg") or code or "失败")

        if code == 409 or "新设备" in msg or "短信验证码" in msg:
            log(f"   ⚠️ {msg}")
            log("   平台已向该手机号发送短信。请按下面做完绑定：")
            log("   1. 查收短信验证码")
            log(f"   2. {captcha_hint()}")
            log("   3. 立刻再运行一次（验证码很快过期）")
            log("   4. 看到「设备已绑定」后，删掉验证码，之后定时不再要")
            if captcha:
                log("   ℹ️ 本轮已提交验证码，但仍被判定为新设备，请换最新一条短信再试")
                return False, "验证码未通过（仍是新设备）"
            return False, "新设备需短信验证码"

        if code != 1:
            log(f"   ❌ 登录失败: {msg}")
            if "验证码" in msg:
                log(f"   请用最新一条短信：{captcha_hint()}")
            return False, msg

        ui = (ret.get("data") or {}).get("userinfo") or {}
        token = ui.get("token")
        if not token:
            log("   ❌ 登录无 token")
            return False, "登录无 token"
        self.token = str(token)
        exp = ui.get("expiretime")
        log(f"   ✅ 登录成功 token={self.token[:18]}…")
        if exp:
            log(f"   ⏰ 过期时间戳: {exp}")
        return True, msg or "登录成功"

    def mine_info(self) -> Optional[dict[str, Any]]:
        try:
            r = self.session.get(
                f"{self.base}/mining_pool/my",
                headers=self._headers(),
                timeout=self.timeout,
            )
            d = r.json()
        except Exception as e:
            log(f"   ❌ 查询矿机异常: {e}")
            return None
        if d.get("code") != 1:
            log(f"   ❌ 查询矿机失败: {d.get('msg')}")
            return None
        return d.get("data") or {}

    def eco_overview(self) -> Optional[dict[str, Any]]:
        """矿池页「余额」来自生态账户，不是现货钱包。"""
        try:
            r = self.session.get(
                f"{self.base}/eco/overview",
                headers=self._headers(),
                timeout=self.timeout,
            )
            d = r.json()
        except Exception as e:
            log(f"   ❌ 查询生态账户异常: {e}")
            return None
        if d.get("code") != 1:
            log(f"   ❌ 查询生态账户失败: {d.get('msg')}")
            return None
        return d.get("data") or {}

    def claim(self) -> tuple[bool, str]:
        try:
            r = self.session.post(
                f"{self.base}/mining_pool/claim",
                headers=self._headers(),
                json={},
                timeout=self.timeout,
            )
            d = r.json()
        except Exception as e:
            return False, f"网络: {e}"
        if d.get("code") == 1:
            return True, d.get("msg") or "领取成功"
        return False, str(d.get("msg") or d.get("code") or "失败")

    def upgrade(self) -> tuple[bool, str]:
        try:
            r = self.session.post(
                f"{self.base}/mining_pool/upgrade",
                headers=self._headers(),
                json={},
                timeout=self.timeout,
            )
            d = r.json()
        except Exception as e:
            return False, f"网络: {e}"
        if d.get("code") == 1:
            return True, d.get("msg") or "升级成功"
        return False, str(d.get("msg") or d.get("code") or "失败")


def _fnum(v: Any) -> str:
    if v is None:
        return "0"
    try:
        x = float(v)
        if abs(x - int(x)) < 1e-9:
            return str(int(x))
        return f"{x:.4f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(v)


def _as_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def apply_mine_info(res: dict[str, Any], info: dict[str, Any]) -> None:
    res["level"] = info.get("current_level")
    res["claimable"] = info.get("claimable_fu")
    res["upgrade_cost"] = info.get("next_upgrade_cost_fu")
    res["daily_income"] = info.get("decayed_daily_income_fu") or info.get("daily_income_fu")
    res["total_earned"] = info.get("total_earned_fu")


def apply_eco(res: dict[str, Any], client: FunClient) -> None:
    data = client.eco_overview()
    if not data:
        return
    res["balance"] = data.get("fu_available")
    res["balance_freeze"] = data.get("fu_freeze")
    res["hashrate"] = data.get("hashrate_available") or data.get("hashrate_total")


def run_account(acc: Account, cfg: AppConfig) -> dict[str, Any]:
    res: dict[str, Any] = {
        "label": acc.label,
        "mobile": mask_mobile(acc.mobile),
        "note": acc.note,
        "ok": False,
        "claim": None,
        "upgrade": None,
        "level": None,
        "claimable": None,
        "upgrade_cost": None,
        "balance": None,
        "balance_freeze": None,
        "hashrate": None,
        "daily_income": None,
        "total_earned": None,
        "errors": [],
    }
    log("")
    log(f"{'=' * 40}")
    log(f"👤 {acc.label}  ({mask_mobile(acc.mobile)})")
    log(f"   收矿={'开' if acc.do_claim else '关'} | 升级={'开' if acc.do_upgrade else '关'}")

    cache = load_device_cache()
    device_id, created = get_or_create_device(acc.mobile, cache)
    bound = bool((cache.get(acc.mobile) or {}).get("bound"))
    cache_path = resolve_device_cache_path()
    log(f"   📲 设备 ID {device_id[:12]}… {'(新生成)' if created else '(缓存)'}"
        f"{' 已绑定' if bound else ' 未绑定'}")
    log(f"   💾 缓存: {cache_path}")

    captcha = resolve_captcha(acc, cfg)
    if captcha:
        log("   🔑 本轮将提交短信验证码")

    client = FunClient(cfg.base_url, device_id)
    ok, msg = client.login(acc.mobile, acc.password, captcha)
    if not ok:
        res["errors"].append(msg if msg and msg != "登录失败" else "登录失败")
        return res

    mark_device_bound(acc.mobile, device_id, cache)
    if captcha:
        log("   📌 设备已绑定。请删掉验证码（FUN_CAPTCHA / config.yaml captcha / 账号第 6 段），避免下次误用过期码")
    elif created:
        where = "/ql/data" if running_on_qinglong() else str(SCRIPT_DIR)
        log(f"   📌 设备已写入缓存，请保留该文件（{where}）")

    time.sleep(0.8)

    # 1 收矿
    if acc.do_claim:
        log("   💰 执行收矿…")
        ok, msg = client.claim()
        res["claim"] = {"ok": ok, "msg": msg}
        if ok:
            log(f"   ✅ 收矿: {msg}")
        else:
            log(f"   ℹ️ 收矿: {msg}")
            # 「暂无可领取」不算失败
            if "无可领取" not in msg and "没有" not in msg and "暂无" not in msg:
                res["errors"].append(f"收矿:{msg}")
        time.sleep(1.0)
    else:
        res["claim"] = {"ok": None, "msg": "已关闭"}
        log("   ⏭️ 跳过收矿")

    # 2 查状态（矿机 + 钱包余额）
    info = client.mine_info()
    if info is not None:
        apply_mine_info(res, info)
        log(
            f"   ⛏️ 等级 LV{res['level']} | 可领 {_fnum(res['claimable'])} | "
            f"日产 {_fnum(res['daily_income'])} | 升级费 {_fnum(res['upgrade_cost'])}"
        )
    else:
        res["errors"].append("查询矿机失败")
    apply_eco(res, client)
    if res.get("balance") is not None:
        freeze = _as_float(res.get("balance_freeze")) or 0.0
        extra = f" | 冻结 {_fnum(res['balance_freeze'])}" if freeze > 0 else ""
        hr = res.get("hashrate")
        hr_s = f" | 算力 {_fnum(hr)}" if hr is not None else ""
        log(f"   💰 余额 {_fnum(res['balance'])} FU{extra}{hr_s}")
    time.sleep(1.0)

    # 3 升级
    if acc.do_upgrade:
        log("   ⬆️ 执行升级…")
        ok, msg = client.upgrade()
        res["upgrade"] = {"ok": ok, "msg": msg}
        if ok:
            log(f"   ✅ 升级: {msg}")
            time.sleep(1.0)
            info2 = client.mine_info()
            if info2:
                apply_mine_info(res, info2)
                log(
                    f"   ⛏️ 升级后 LV{res['level']} | 可领 {_fnum(res['claimable'])}"
                )
            apply_eco(res, client)
            if res.get("balance") is not None:
                log(f"   💰 余额 {_fnum(res['balance'])} FU")
        else:
            log(f"   ℹ️ 升级: {msg}")
            # 余额不足等不算严重
            if "成功" not in msg:
                res["errors"].append(f"升级:{msg}")
    else:
        res["upgrade"] = {"ok": None, "msg": "已关闭"}
        log("   ⏭️ 跳过升级")

    # 登录成功且查询成功视为 ok（收矿无产出不算失败）
    hard = [e for e in res["errors"] if not e.startswith("升级:")]
    res["ok"] = not hard and res["level"] is not None
    if res["ok"]:
        log("   🏁 本号完成")
    else:
        log("   ⚠️ 本号有异常")
    return res


def _all_need_sms(results: list[dict[str, Any]]) -> bool:
    if not results:
        return False
    return all(
        any("短信" in str(e) or "新设备" in str(e) or "验证码" in str(e) for e in (r.get("errors") or []))
        for r in results
        if not r.get("ok")
    ) and all(not r.get("ok") for r in results)


def build_bark(results: list[dict[str, Any]], note: str) -> tuple[str, str]:
    now = datetime.now().strftime("%m-%d %H:%M")
    n = len(results)
    ok_n = sum(1 for r in results if r.get("ok"))
    fail_n = n - ok_n
    note_s = f" · {note}" if note else ""

    if n == 0:
        title = f"FUN矿池{note_s}"
    elif fail_n == 0:
        title = f"FUN矿池 ✅{note_s}"
    elif ok_n == 0:
        title = f"FUN矿池 ❌{note_s}"
    else:
        title = f"FUN矿池 ⚠️ {ok_n}/{n}{note_s}"

    lines = [
        "⛏️ FUN 矿池 · 任务汇总",
    ]
    if note:
        lines.append(f"🏷️ 备注：{note}")
    lines.append(f"📅 {now}")
    lines.append("────────────────")
    lines.append("")

    for i, r in enumerate(results):
        icon = ICONS[i % len(ICONS)]
        label = r.get("label") or r.get("mobile") or "?"
        lines.append(f"{icon} 【{label}】")
        if r.get("note") and r.get("note") != label:
            lines.append(f"   📱 {r['note']} · {r.get('mobile')}")
        else:
            lines.append(f"   📱 {r.get('mobile')}")

        if not r.get("ok") and r.get("errors"):
            lines.append("   ❌ 状态：失败")
            err = "; ".join(r["errors"])
            if len(err) > 90:
                err = err[:87] + "…"
            lines.append(f"   💬 {err}")
        else:
            lv = r.get("level")
            claimable = _fnum(r.get("claimable"))
            cost = _fnum(r.get("upgrade_cost"))
            bal = r.get("balance")
            freeze = _as_float(r.get("balance_freeze")) or 0.0
            lines.append(f"   🏭 矿机：LV{lv if lv is not None else '?'}")
            if bal is not None:
                lines.append(f"   💰 余额：{_fnum(bal)} FU")
                if freeze > 0:
                    lines.append(f"   🧊 冻结：{_fnum(r.get('balance_freeze'))} FU")
            lines.append(f"   💎 可领：{claimable}")
            daily = r.get("daily_income")
            if daily is not None:
                lines.append(f"   📈 日产：{_fnum(daily)}")
            lines.append(f"   ⬆️ 升级费：{cost}")

            cl = r.get("claim") or {}
            if cl.get("ok") is True:
                lines.append("   💰 收矿：成功 ✅")
            elif cl.get("ok") is False:
                lines.append(f"   💰 收矿：{cl.get('msg') or '无产出'} ℹ️")
            elif cl.get("ok") is None:
                lines.append("   💰 收矿：已关闭 ⏭️")

            up = r.get("upgrade") or {}
            if up.get("ok") is True:
                lines.append("   🚀 升级：成功 ✅")
            elif up.get("ok") is False:
                lines.append(f"   🚀 升级：{up.get('msg') or '失败'} ⚠️")
            elif up.get("ok") is None:
                lines.append("   🚀 升级：已关闭 ⏭️")

        if i < n - 1:
            lines.append("")

    lines.append("")
    lines.append("────────────────")
    lines.append(f"📦 账号 {n} · ✅{ok_n}  ❌{fail_n}")
    if fail_n == 0:
        lines.append("🎉 全部顺利")
    elif _all_need_sms(results):
        lines.append("📱 新设备：填验证码后立刻再跑一次")
    elif ok_n == 0:
        lines.append("😿 请检查账号密码 / 网络 / 短信验证码")
    else:
        lines.append("💡 部分账号见日志")

    return title, "\n".join(lines)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FUN 矿池：登录 / 收矿 / 可选升级（本地 yaml 或青龙环境变量）")
    p.add_argument(
        "-c",
        "--config",
        default="",
        help="本地 config.yaml 路径（默认 ./config.yaml；未指定且无 FUN 时自动读取）",
    )
    p.add_argument(
        "--captcha",
        default="",
        help="本轮短信验证码（仅首次新设备绑定；成功后不要再传）",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    global _ACTIVE_CFG
    args = parse_args(argv)
    log("🚀 FUN 矿池 mine.py")
    log(f"🖥️ 运行环境: {'青龙' if running_on_qinglong() else '本地'}")

    try:
        cfg = resolve_config(args)
    except Exception as e:
        log(f"❌ {e}")
        log("   青龙：FUN=手机号#密码#收矿#升级[#备注][#验证码]")
        log("   本地：cp config.example.yaml config.yaml 后填写")
        send_bark("FUN矿池 ❌", f"❌ 未配置账号\n{e}")
        return 1

    if args.captcha.strip():
        cfg.captcha = args.captcha.strip()

    _ACTIVE_CFG = cfg

    if cfg.note:
        log(f"🏷️ 全局备注: {cfg.note}")
    log(f"📄 配置来源: {cfg.source or '?'}")
    if bark_endpoint(cfg):
        log("📣 Bark 已配置")
    else:
        log("📣 未配置 BARK_URL/BARK_KEY（本地可写在 config.yaml 的 notify）")

    log(f"🌐 API: {cfg.base_url}")
    log(f"💾 设备缓存: {resolve_device_cache_path()}")

    if cfg.captcha or any(a.captcha for a in cfg.accounts):
        log("🔑 已配置验证码（绑定成功后请删除）")

    accounts = cfg.accounts
    log(f"📋 共 {len(accounts)} 个账号")
    results: list[dict[str, Any]] = []
    for i, acc in enumerate(accounts, 1):
        log(f"\n▶ [{i}/{len(accounts)}]")
        try:
            results.append(run_account(acc, cfg))
        except Exception as e:
            log(f"   ❌ 异常: {e}")
            results.append(
                {
                    "label": acc.label,
                    "mobile": mask_mobile(acc.mobile),
                    "note": acc.note,
                    "ok": False,
                    "errors": [str(e)],
                }
            )
        if i < len(accounts):
            time.sleep(2.0)

    title, body = build_bark(results, cfg.note)
    log("")
    log(body)
    send_bark(title, body, cfg)
    log("\n🏁 全部完成")
    fail = sum(1 for r in results if not r.get("ok"))
    return 1 if fail else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n⚠️ 中断")
        sys.exit(130)
