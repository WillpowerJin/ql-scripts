#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B 站每日任务（登录/观看/分享/投币/银瓜子兑硬币/大会员部分任务）

cron: 30 7 * * *
new Env('B站每日任务');

凭据（任选其一，无需 App 抓包）：
  1) 扫码：python daily.py --qr
  2) Cookie：SESSDATA + bili_jct（浏览器复制）
  3) 账密：username + password（多数环境会被极验拦住）

青龙环境变量：
  BILI_ACCOUNTS  JSON 数组
    [{"name":"主号","cookie":"SESSDATA=...; bili_jct=..."}]
  或：
    BILI_COOKIE / BILI_USERNAME / BILI_PASSWORD / BILI_NAME（& 多账号）
  可选：
    BILI_COIN_NUM=5  BILI_SILVER2COIN=1  BILI_VIP_TASKS=1
  通知：BARK_URL / BARK_KEY

依赖：requests cryptography；本地 yaml 可选 PyYAML
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
except ImportError:
    serialization = None  # type: ignore
    padding = None  # type: ignore

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent

# 与 ClydeTime 脚本一致的 iOS appkey（TV 扫码 / 部分 App 接口签名）
APPKEY = "27eb53fc9058f8c3"
APPSEC = "c2ed53a74eeefe3cf99fbd01d8c9c375"

DEFAULT_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_4_1 like Mac OS X) "
    "AppleWebKit/621.1.15.10.7 (KHTML, like Gecko) Mobile/22E252 "
    "BiliApp/84400100 os/ios model/iPhone mobi_app/iphone build/84400100 "
    "osVer/18.3 network/2 channel/AppStore"
)
DEFAULT_BARK_SERVER = "https://api.day.app"

logger = logging.getLogger("bilibili")


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def resolve_cache_path() -> Path:
    """
    Cookie 缓存路径（get_cookie / daily 共用）：
      1) 环境变量 BILI_COOKIE_FILE
      2) 青龙：/ql/data/bilibili_cookie_cache.json（订阅更新脚本时不被覆盖）
      3) 脚本目录 cookie_cache.json（本地开发）
    """
    env = _env("BILI_COOKIE_FILE") or _env("BILI_COOKIE_CACHE")
    if env:
        return Path(env).expanduser()
    ql_data = _env("QL_DATA_DIR")
    if ql_data:
        return Path(ql_data) / "bilibili_cookie_cache.json"
    if Path("/ql/data").is_dir():
        return Path("/ql/data/bilibili_cookie_cache.json")
    return SCRIPT_DIR / "cookie_cache.json"


def _split_multi(s: str) -> list[str]:
    if not s:
        return []
    return [x.strip() for x in s.split("&") if x.strip()]


def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def app_sign(params: dict[str, Any]) -> dict[str, str]:
    """B 站 App 签名：参数按 key 排序拼接 + appsec 后 MD5。"""
    body = {k: str(v) for k, v in params.items() if v is not None}
    qs = "&".join(f"{k}={body[k]}" for k in sorted(body.keys()))
    body["sign"] = md5_hex(qs + APPSEC)
    return body


def parse_cookie(cookie: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (cookie or "").replace("\n", " ").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def cookie_header(d: dict[str, str]) -> str:
    keys = [
        "DedeUserID",
        "DedeUserID__ckMd5",
        "SESSDATA",
        "bili_jct",
        "sid",
        "Buvid",
    ]
    parts = []
    for k in keys:
        if k in d and d[k]:
            parts.append(f"{k}={d[k]}")
    # 其余字段一并带上
    for k, v in d.items():
        if k not in keys and v:
            parts.append(f"{k}={v}")
    return "; ".join(parts)


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return time.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    cookie: str = ""
    username: str = ""
    password: str = ""
    access_token: str = ""

    def normalize(self) -> None:
        self.name = (self.name or "").strip() or "account"
        self.cookie = (self.cookie or "").strip()
        self.username = (self.username or "").strip()
        self.password = self.password or ""
        self.access_token = (self.access_token or "").strip()

    def has_cookie(self) -> bool:
        c = parse_cookie(self.cookie)
        return bool(c.get("SESSDATA") and c.get("bili_jct"))

    def has_password(self) -> bool:
        return bool(self.username and self.password)


@dataclass
class NotifyConfig:
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = "B站每日任务"
    bark_sound: str = ""
    bark_icon: str = ""
    bark_level: str = ""
    serverchan_key: str = ""
    webhook_url: str = ""


@dataclass
class GeetestConfig:
    token: str = ""
    challenge: str = ""
    validate: str = ""
    seccode: str = ""


@dataclass
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    coin_num: int = 5
    silver2coin: bool = True
    vip_tasks: bool = True
    manga_sign: bool = True
    live_sign: bool = False  # 官方活动多已下线，默认关
    timeout: int = 25
    user_agent: str = DEFAULT_UA
    geetest: GeetestConfig = field(default_factory=GeetestConfig)


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
        bark_group=_env("BARK_GROUP", "B站每日任务"),
        bark_sound=_env("BARK_SOUND"),
        bark_icon=_env("BARK_ICON"),
        bark_level=_env("BARK_LEVEL"),
        serverchan_key=_env("SERVERCHAN_KEY") or _env("PUSH_KEY"),
        webhook_url=_env("WEBHOOK_URL"),
    )


def _parse_accounts_from_env() -> list[Account]:
    accounts: list[Account] = []
    raw = _env("BILI_ACCOUNTS")
    if raw:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("BILI_ACCOUNTS 必须是 JSON 数组")
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(f"BILI_ACCOUNTS[{i}] 必须是对象")
            acc = Account(
                name=str(item.get("name") or f"account_{i + 1}"),
                cookie=str(item.get("cookie") or ""),
                username=str(item.get("username") or item.get("user") or ""),
                password=str(item.get("password") or item.get("pass") or ""),
                access_token=str(
                    item.get("access_token") or item.get("accessToken") or ""
                ),
            )
            acc.normalize()
            accounts.append(acc)
        return accounts

    cookies = _split_multi(_env("BILI_COOKIE"))
    users = _split_multi(_env("BILI_USERNAME") or _env("BILI_USER"))
    pwds = _split_multi(_env("BILI_PASSWORD") or _env("BILI_PASS"))
    names = _split_multi(_env("BILI_NAME"))
    n = max(len(cookies), len(users), len(pwds))
    for i in range(n):
        acc = Account(
            name=names[i] if i < len(names) else (
                users[i] if i < len(users) else f"account_{i + 1}"
            ),
            cookie=cookies[i] if i < len(cookies) else "",
            username=users[i] if i < len(users) else "",
            password=pwds[i] if i < len(pwds) else "",
        )
        acc.normalize()
        accounts.append(acc)
    return accounts


def load_config_from_env() -> Optional[AppConfig]:
    accounts = _parse_accounts_from_env()
    if not accounts:
        return None
    coin = int(_env("BILI_COIN_NUM") or "5")
    def _flag(key: str, default: str = "1") -> bool:
        return _env(key, default) not in ("0", "false", "False")

    return AppConfig(
        accounts=accounts,
        notify=load_notify_from_env(),
        coin_num=max(0, min(5, coin)),
        silver2coin=_flag("BILI_SILVER2COIN"),
        vip_tasks=_flag("BILI_VIP_TASKS"),
        manga_sign=_flag("BILI_MANGA_SIGN"),
        live_sign=_flag("BILI_LIVE_SIGN", "0"),
        timeout=int(_env("BILI_TIMEOUT") or "25"),
        user_agent=_env("BILI_UA") or DEFAULT_UA,
    )


def load_config_yaml(path: Path) -> AppConfig:
    try:
        import yaml
    except ImportError as e:
        raise ImportError("本地 yaml 需要: pip install PyYAML") from e
    if not path.is_file():
        raise FileNotFoundError(f"配置不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    accounts: list[Account] = []
    for i, item in enumerate(raw.get("accounts") or []):
        if not isinstance(item, dict):
            raise ValueError(f"accounts[{i}] 格式错误")
        acc = Account(
            name=str(item.get("name") or f"account_{i + 1}"),
            cookie=str(item.get("cookie") or ""),
            username=str(item.get("username") or item.get("user") or ""),
            password=str(item.get("password") or item.get("pass") or ""),
            access_token=str(
                item.get("access_token") or item.get("accessToken") or ""
            ),
        )
        acc.normalize()
        accounts.append(acc)

    n = raw.get("notify") or {}
    env_n = load_notify_from_env()
    notify = NotifyConfig(
        bark_url=env_n.bark_url or str(n.get("bark_url") or ""),
        bark_key=env_n.bark_key or str(n.get("bark_key") or ""),
        bark_server=(
            env_n.bark_server
            if env_n.bark_url or env_n.bark_key
            else str(n.get("bark_server") or DEFAULT_BARK_SERVER)
        ).rstrip("/"),
        bark_group=(
            env_n.bark_group
            if _env("BARK_GROUP")
            else str(n.get("bark_group") or "B站每日任务")
        ),
        bark_sound=env_n.bark_sound or str(n.get("bark_sound") or ""),
        bark_icon=env_n.bark_icon or str(n.get("bark_icon") or ""),
        bark_level=env_n.bark_level or str(n.get("bark_level") or ""),
        serverchan_key=env_n.serverchan_key
        or str(n.get("serverchan_key") or ""),
        webhook_url=env_n.webhook_url or str(n.get("webhook_url") or ""),
    )

    g = raw.get("geetest") or {}
    geetest = GeetestConfig(
        token=str(g.get("token") or ""),
        challenge=str(g.get("challenge") or ""),
        validate=str(g.get("validate") or ""),
        seccode=str(g.get("seccode") or ""),
    )

    coin = int(raw.get("coin_num") if raw.get("coin_num") is not None else 5)
    if _env("BILI_COIN_NUM"):
        coin = int(_env("BILI_COIN_NUM"))

    return AppConfig(
        accounts=accounts,
        notify=notify,
        coin_num=max(0, min(5, coin)),
        silver2coin=bool(raw.get("silver2coin", True)),
        vip_tasks=bool(raw.get("vip_tasks", True)),
        manga_sign=bool(raw.get("manga_sign", True)),
        live_sign=bool(raw.get("live_sign", False)),
        timeout=int(raw.get("timeout") or 25),
        user_agent=str(raw.get("user_agent") or DEFAULT_UA),
        geetest=geetest,
    )


def load_config(path: Optional[Path] = None) -> AppConfig:
    env_cfg = load_config_from_env()
    yaml_path = path or (SCRIPT_DIR / "config.yaml")
    if yaml_path.is_file():
        cfg = load_config_yaml(yaml_path)
        if env_cfg and env_cfg.accounts:
            # 环境变量账号优先合并：同名覆盖
            by_name = {a.name: a for a in cfg.accounts}
            for a in env_cfg.accounts:
                by_name[a.name] = a
            cfg.accounts = list(by_name.values())
            if env_cfg.notify.bark_url or env_cfg.notify.bark_key:
                cfg.notify = env_cfg.notify
        return cfg
    if env_cfg:
        return env_cfg
    # 无配置时仍可 --qr 写缓存
    return AppConfig(accounts=[Account(name="主号")])


# ---------------------------------------------------------------------------
# Cookie 缓存
# ---------------------------------------------------------------------------

def load_cache() -> dict[str, Any]:
    path = resolve_cache_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(data: dict[str, Any]) -> None:
    path = resolve_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Cookie 已写入: %s", path)


def cache_get(name: str) -> dict[str, Any]:
    return (load_cache().get("accounts") or {}).get(name) or {}


def _mid_from_cookie(cookie: str) -> str:
    return str(parse_cookie(cookie).get("DedeUserID") or "").strip()


def find_cache_key_by_mid(mid: str) -> Optional[str]:
    """按 B 站 uid(mid) 查找已有缓存键，用于多账号去重。"""
    mid = str(mid or "").strip()
    if not mid:
        return None
    for key, ent in (load_cache().get("accounts") or {}).items():
        if not isinstance(ent, dict):
            continue
        if str(ent.get("mid") or "").strip() == mid:
            return str(key)
        cmid = _mid_from_cookie(str(ent.get("cookie") or ""))
        if cmid == mid:
            return str(key)
    return None


def cache_upsert(
    cookie: str,
    access_token: str = "",
    *,
    preferred_name: str = "",
    mid: str = "",
    uname: str = "",
) -> tuple[str, str]:
    """
    写入/更新 Cookie 缓存。
    以 mid(DedeUserID) 判断是否同一账号：
      - 已存在 → 更新该条（避免重复扫码变成两个号）
      - 新 mid → 新增一条
    存储键优先：preferred_name（用户指定）→ 已有键 → uname → mid。

    返回 (storage_key, action)  action: new | update
    """
    mid = str(mid or _mid_from_cookie(cookie) or "").strip()
    uname = str(uname or "").strip()
    preferred_name = str(preferred_name or "").strip()
    # 占位名不当作真实备注
    if preferred_name in ("主号", "扫码待识别", "account", "account_1"):
        # 若已有同 mid，保留旧键；否则用 uname
        preferred_name = ""

    data = load_cache()
    accounts: dict[str, Any] = data.setdefault("accounts", {})
    existing_key = find_cache_key_by_mid(mid) if mid else None

    if existing_key:
        key = preferred_name or existing_key
        if preferred_name and preferred_name != existing_key:
            # 用户指定新备注：迁到新键
            if existing_key in accounts and preferred_name not in accounts:
                accounts[preferred_name] = accounts.pop(existing_key)
            key = preferred_name
        elif not preferred_name and uname and existing_key in (
            "主号",
            "扫码待识别",
            mid,
        ):
            # 把临时键升级为昵称
            if uname != existing_key and uname not in accounts:
                accounts[uname] = accounts.pop(existing_key)
                key = uname
            else:
                key = existing_key
        action = "update"
    else:
        key = preferred_name or uname or mid or f"account_{len(accounts) + 1}"
        # 避免覆盖不同 mid 的同名键
        if key in accounts:
            old_mid = str(accounts[key].get("mid") or "") or _mid_from_cookie(
                str(accounts[key].get("cookie") or "")
            )
            if old_mid and mid and old_mid != mid:
                key = f"{key}_{mid}" if mid else f"{key}_{len(accounts) + 1}"
        action = "new"

    prev = accounts.get(key) if isinstance(accounts.get(key), dict) else {}
    accounts[key] = {
        "cookie": cookie,
        "access_token": access_token or prev.get("access_token") or "",
        "mid": mid or prev.get("mid") or "",
        "uname": uname or prev.get("uname") or "",
        "updated_at": now_str(),
    }
    data["updated_at"] = now_str()
    save_cache(data)
    return key, action


def cache_set(name: str, cookie: str, access_token: str = "") -> None:
    """兼容旧调用：按 name 写入，仍会按 mid 去重合并。"""
    mid = _mid_from_cookie(cookie)
    cache_upsert(
        cookie,
        access_token,
        preferred_name=name,
        mid=mid,
    )


def list_cached_accounts() -> list[Account]:
    """缓存中所有带 Cookie 的账号（供 daily 多账号遍历）。"""
    out: list[Account] = []
    for key, ent in (load_cache().get("accounts") or {}).items():
        if not isinstance(ent, dict):
            continue
        ck = str(ent.get("cookie") or "").strip()
        if not ck:
            continue
        uname = str(ent.get("uname") or "").strip()
        display = uname or str(key)
        acc = Account(
            name=display,
            cookie=ck,
            access_token=str(ent.get("access_token") or ""),
        )
        acc.normalize()
        out.append(acc)
    return out


def merge_account_credentials(acc: Account) -> Account:
    """配置 Cookie 优先；否则按 name / 缓存匹配。"""
    if acc.has_cookie():
        return acc
    cached = cache_get(acc.name)
    if not cached.get("cookie"):
        # 用配置名对不上时，尝试缓存里唯一一条
        all_acc = list_cached_accounts()
        if len(all_acc) == 1:
            acc.cookie = all_acc[0].cookie
            acc.access_token = acc.access_token or all_acc[0].access_token
            return acc
        return acc
    acc.cookie = str(cached["cookie"])
    if not acc.access_token and cached.get("access_token"):
        acc.access_token = str(cached["access_token"])
    return acc


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------

def send_notify(cfg: NotifyConfig, title: str, body: str) -> None:
    if cfg.bark_url or cfg.bark_key:
        try:
            if cfg.bark_url:
                url = cfg.bark_url.rstrip("/")
                if url.endswith(cfg.bark_key) if cfg.bark_key else False:
                    push = f"{url}/{quote(title)}/{quote(body)}"
                else:
                    # 完整 URL 或 server/key
                    if cfg.bark_key and cfg.bark_key not in url:
                        push = f"{url.rstrip('/')}/{cfg.bark_key}/{quote(title)}/{quote(body)}"
                    else:
                        push = f"{url}/{quote(title)}/{quote(body)}"
            else:
                push = (
                    f"{cfg.bark_server.rstrip('/')}/{cfg.bark_key}/"
                    f"{quote(title)}/{quote(body)}"
                )
            params = {}
            if cfg.bark_group:
                params["group"] = cfg.bark_group
            if cfg.bark_sound:
                params["sound"] = cfg.bark_sound
            if cfg.bark_icon:
                params["icon"] = cfg.bark_icon
            if cfg.bark_level:
                params["level"] = cfg.bark_level
            requests.get(push, params=params or None, timeout=10)
        except Exception as e:
            logger.warning("Bark 通知失败: %s", e)
    if cfg.webhook_url:
        try:
            requests.post(
                cfg.webhook_url,
                json={"title": title, "content": body},
                timeout=10,
            )
        except Exception as e:
            logger.warning("Webhook 失败: %s", e)


# ---------------------------------------------------------------------------
# 扫码展示（勿用浏览器打开 auth 链接 — 那是给手机 B 站扫的）
# ---------------------------------------------------------------------------

QR_PNG_PATH = SCRIPT_DIR / "login_qr.png"
QR_HTML_PATH = SCRIPT_DIR / "login_qr.html"


def _log_print(msg: str = "") -> None:
    """写入 stdout（青龙任务日志会抓 print；flush 避免缓冲吞日志）。"""
    print(msg, flush=True)


def show_login_qr(auth_url: str) -> None:
    """
    在终端/任务日志里输出可扫二维码（ASCII + 在线图片链接）。
    auth_url 不要在 PC 浏览器直接打开（会提示去手机）。
    """
    online_img = (
        "https://api.qrserver.com/v1/create-qr-code/?size=320x320&data="
        + quote(auth_url, safe="")
    )

    _log_print("")
    _log_print("=" * 48)
    _log_print("📱 请用【手机哔哩哔哩 App】→ 扫一扫 → 扫下方二维码")
    _log_print("⚠️  不要用电脑浏览器打开登录链接本身")
    _log_print("⏱️  约 2～3 分钟内有效，确认后脚本会自动继续")
    _log_print("=" * 48)
    _log_print("")

    # 1) 终端 / 青龙日志 ASCII 二维码（手机对着屏幕扫）
    printed = False
    try:
        import qrcode  # type: ignore

        qr = qrcode.QRCode(border=1, box_size=1)
        qr.add_data(auth_url)
        qr.make(fit=True)
        # invert=True 适合浅色底日志；深色终端也一般可扫
        print("", flush=True)
        qr.print_ascii(invert=True)
        print("", flush=True)
        printed = True
        _log_print("✅ 上方为登录二维码（手机对着日志/终端屏幕扫）")
    except Exception as e:
        _log_print(f"⚠️  终端二维码绘制失败（可 pip install qrcode Pillow）: {e}")

    # 2) 在线图片链接（Bark / 浏览器打开后扫）— 始终打印
    _log_print("")
    _log_print("🔗 二维码图片链接（可点开再扫，或已推送到 Bark）：")
    _log_print(online_img)
    _log_print("")

    # 3) 本地 PNG / HTML（可选）
    png_ok = False
    try:
        import qrcode  # type: ignore

        img = qrcode.make(auth_url)
        img.save(QR_PNG_PATH)
        png_ok = True
        _log_print(f"💾 本地图片: {QR_PNG_PATH}")
    except Exception as e:
        logger.debug("生成 PNG 失败: %s", e)

    try:
        if png_ok and QR_PNG_PATH.is_file():
            b64 = base64.b64encode(QR_PNG_PATH.read_bytes()).decode("ascii")
            html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>B站扫码登录</title>
<style>
body{{font-family:sans-serif;text-align:center;padding:2rem;background:#0f0f0f;color:#eee}}
img{{width:min(360px,90vw);height:auto;background:#fff;padding:12px;border-radius:8px}}
</style></head><body>
<h1>B 站扫码登录</h1>
<p>请用手机 B 站扫下方码</p>
<img src="data:image/png;base64,{b64}" alt="login qr"/>
</body></html>"""
            QR_HTML_PATH.write_text(html, encoding="utf-8")
            _log_print(f"💾 本地网页: file://{QR_HTML_PATH}")
    except Exception as e:
        logger.debug("写 HTML 失败: %s", e)

    if not printed:
        _log_print("👉 终端未能画码时，请打开上方「二维码图片链接」再扫")
    _log_print("")


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------

class BiliClient:
    def __init__(self, account: Account, cfg: AppConfig):
        self.account = account
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": cfg.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        self.cookies: dict[str, str] = {}
        self.access_token = account.access_token
        self.user: dict[str, Any] = {}
        if account.cookie:
            self.cookies = parse_cookie(account.cookie)
            self._apply_cookies()

    def _apply_cookies(self) -> None:
        self.session.headers["Cookie"] = cookie_header(self.cookies)
        for k, v in self.cookies.items():
            self.session.cookies.set(k, v, domain=".bilibili.com")

    def _timeout(self) -> int:
        return self.cfg.timeout

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        data: Any = None,
        json_body: Any = None,
        headers: Optional[dict[str, str]] = None,
        form: bool = False,
    ) -> dict[str, Any]:
        h = dict(headers or {})
        try:
            r = self.session.request(
                method,
                url,
                params=params,
                data=data,
                json=json_body,
                headers=h,
                timeout=self._timeout(),
            )
        except requests.RequestException as e:
            return {"code": -1, "message": f"网络错误: {e}", "data": None}
        try:
            return r.json()
        except Exception:
            return {
                "code": -1,
                "message": f"非 JSON HTTP {r.status_code}: {r.text[:160]}",
                "data": None,
            }

    # ---- 扫码登录（TV）----

    def qr_login(self, poll_times: int = 40, interval: float = 3.0) -> bool:
        """终端扫码登录，成功后写入 self.cookies / cache。"""
        body = app_sign(
            {
                "appkey": APPKEY,
                "local_id": 0,
                "ts": int(time.time()),
                "mobi_app": "iphone",
            }
        )
        resp = self.request(
            "POST",
            "https://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.get("code") != 0:
            logger.error("获取二维码失败: %s", resp.get("message"))
            return False
        data = resp.get("data") or {}
        auth_code = data.get("auth_code")
        url = data.get("url") or ""
        if not auth_code:
            logger.error("auth_code 为空")
            return False
        if not url:
            url = (
                "https://passport.bilibili.com/x/passport-tv-login/h5/qrcode/auth"
                f"?auth_code={auth_code}&mobi_app=iphone"
            )

        show_login_qr(url)
        logger.info("等待扫码，超时约 %s 秒…", int(poll_times * interval))

        for i in range(poll_times):
            time.sleep(interval)
            poll_body = app_sign(
                {
                    "appkey": APPKEY,
                    "auth_code": auth_code,
                    "local_id": 0,
                    "ts": int(time.time()),
                }
            )
            poll = self.request(
                "POST",
                "https://passport.bilibili.com/x/passport-tv-login/qrcode/poll",
                data=poll_body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
                },
            )
            code = poll.get("code")
            if code == 0:
                pdata = poll.get("data") or {}
                self.access_token = str(pdata.get("access_token") or "")
                cookie_info = pdata.get("cookie_info") or {}
                cookies_list = cookie_info.get("cookies") or []
                jar: dict[str, str] = {}
                for c in cookies_list:
                    if isinstance(c, dict) and c.get("name"):
                        jar[str(c["name"])] = str(c.get("value") or "")
                if not jar and pdata.get("cookie_info"):
                    # 兼容其它结构
                    pass
                if not jar.get("SESSDATA"):
                    # 有的返回 cookies 为 list of dict 已处理；否则尝试顶层
                    logger.error("扫码成功但未拿到 SESSDATA: %s", str(poll)[:300])
                    return False
                self.cookies = jar
                self._apply_cookies()
                ck = cookie_header(jar)
                self.account.cookie = ck
                self.account.access_token = self.access_token
                # 拉昵称，按 mid 去重写入（多账号 / 重复扫同一号）
                mid = jar.get("DedeUserID") or ""
                uname = ""
                try:
                    if self.me():
                        uname = str(self.user.get("uname") or "")
                        mid = str(self.user.get("mid") or mid)
                except Exception:
                    pass
                key, action = cache_upsert(
                    ck,
                    self.access_token,
                    preferred_name=self.account.name,
                    mid=str(mid),
                    uname=uname,
                )
                self.account.name = key
                if action == "update":
                    logger.info(
                        "扫码成功：更新已有账号 [%s] mid=%s uname=%s → %s",
                        key,
                        mid,
                        uname or "?",
                        resolve_cache_path(),
                    )
                else:
                    logger.info(
                        "扫码成功：新增账号 [%s] mid=%s uname=%s → %s",
                        key,
                        mid,
                        uname or "?",
                        resolve_cache_path(),
                    )
                for p in (QR_PNG_PATH, QR_HTML_PATH):
                    try:
                        if p.is_file():
                            p.unlink()
                    except OSError:
                        pass
                return True
            if code == 86038:
                logger.error("二维码已失效，请重试 --qr")
                return False
            if code in (86039, 86090):
                logger.info(
                    "等待扫码确认… (%s/%s) %s",
                    i + 1,
                    poll_times,
                    poll.get("message"),
                )
                continue
            logger.warning("轮询状态 code=%s msg=%s", code, poll.get("message"))
        logger.error("扫码超时")
        return False

    # ---- 账密登录（Web + 可选极验）----

    def password_login(self) -> bool:
        if serialization is None:
            logger.error("账密登录需要 cryptography: pip install cryptography")
            return False
        if not self.account.has_password():
            logger.error("未配置 username/password")
            return False

        key_resp = self.request(
            "GET", "https://passport.bilibili.com/x/passport-login/web/key"
        )
        if key_resp.get("code") != 0:
            logger.error("获取登录公钥失败: %s", key_resp.get("message"))
            return False
        kd = key_resp.get("data") or {}
        hash_s = str(kd.get("hash") or "")
        key_pem = str(kd.get("key") or "")
        if not hash_s or not key_pem:
            logger.error("公钥数据不完整")
            return False

        pub = serialization.load_pem_public_key(key_pem.encode())
        plain = (hash_s + self.account.password).encode("utf-8")
        enc = base64.b64encode(
            pub.encrypt(plain, padding.PKCS1v15())
        ).decode("ascii")

        # 拉极验参数
        cap = self.request(
            "GET",
            "https://passport.bilibili.com/x/passport-login/captcha",
            params={"source": "main_web"},
        )
        cap_data = (cap.get("data") or {}) if cap.get("code") == 0 else {}
        token = self.cfg.geetest.token or str(cap_data.get("token") or "")
        geetest = cap_data.get("geetest") or {}
        challenge = self.cfg.geetest.challenge or str(
            geetest.get("challenge") or ""
        )
        validate = self.cfg.geetest.validate
        seccode = self.cfg.geetest.seccode or (
            f"{validate}|jordan" if validate else ""
        )

        form = {
            "username": self.account.username,
            "password": enc,
            "keep": "0",
            "source": "main_web",
            "go_url": "https://www.bilibili.com",
        }
        if token:
            form["token"] = token
        if challenge:
            form["challenge"] = challenge
        if validate:
            form["validate"] = validate
            form["seccode"] = seccode

        self.session.headers["Referer"] = "https://passport.bilibili.com/login"
        self.session.headers["Origin"] = "https://passport.bilibili.com"
        resp = self.request(
            "POST",
            "https://passport.bilibili.com/x/passport-login/web/login",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        code = resp.get("code")
        if code == 0:
            # Set-Cookie 已在 session；补全 dict
            jar = requests.utils.dict_from_cookiejar(self.session.cookies)
            # 合并 bilibili 域
            for c in self.session.cookies:
                if c.value:
                    jar[c.name] = c.value
            if not jar.get("SESSDATA"):
                # 有时在 data
                data = resp.get("data") or {}
                logger.error("登录成功但无 SESSDATA: %s", str(resp)[:300])
                return False
            self.cookies = jar
            self._apply_cookies()
            ck = cookie_header(jar)
            self.account.cookie = ck
            cache_set(self.account.name, ck, self.access_token)
            logger.info("账密登录成功")
            return True

        msg = str(resp.get("message") or "")
        if code == -105 or "验证码" in msg:
            logger.error(
                "账密登录被极验拦截 (code=%s %s)。"
                "B 站强制 Geetest，纯脚本无法稳定过验证码。"
                "请改用: python daily.py --qr  或浏览器复制 Cookie。",
                code,
                msg,
            )
            if challenge:
                logger.info(
                    "若有打码平台，可配置 geetest.validate 后重试；"
                    "challenge=%s token=%s",
                    challenge[:16] + "…",
                    token[:16] + "…" if token else "",
                )
            return False
        logger.error("账密登录失败 code=%s msg=%s", code, msg)
        return False

    # ---- 用户与任务 ----

    def me(self) -> bool:
        resp = self.request(
            "GET", "https://api.bilibili.com/x/web-interface/nav"
        )
        if resp.get("code") not in (0, "0"):
            logger.error(
                "[%s] 用户信息失败(请更新 Cookie): %s",
                self.account.name,
                resp.get("message"),
            )
            return False
        self.user = resp.get("data") or {}
        if not self.user.get("isLogin"):
            logger.error("[%s] 未登录", self.account.name)
            return False
        li = self.user.get("level_info") or {}
        logger.info(
            "[%s] %s Lv%s 硬币=%s 经验=%s/%s",
            self.account.name,
            self.user.get("uname"),
            li.get("current_level"),
            int(self.user.get("money") or 0),
            li.get("current_exp"),
            li.get("next_exp"),
        )
        return True

    def exp_reward(self) -> dict[str, Any]:
        resp = self.request(
            "GET", "https://api.bilibili.com/x/member/web/exp/reward"
        )
        if resp.get("code") != 0:
            logger.warning("任务状态查询失败: %s", resp.get("message"))
            return {}
        return resp.get("data") or {}

    def dynamic_videos(self) -> list[dict[str, Any]]:
        mid = self.cookies.get("DedeUserID") or self.user.get("mid")
        resp = self.request(
            "GET",
            "https://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/dynamic_new",
            params={
                "uid": mid,
                "type_list": 8,
                "from": "",
                "platform": "web",
            },
        )
        cards = (resp.get("data") or {}).get("cards") or []
        return cards if isinstance(cards, list) else []

    def watch(self, aid: Any, bvid: str, cid: Any) -> bool:
        body = {
            "aid": aid,
            "cid": cid,
            "bvid": bvid,
            "mid": self.user.get("mid"),
            "csrf": self.cookies.get("bili_jct"),
            "played_time": 1,
            "real_played_time": 1,
            "realtime": 1,
            "start_ts": int(time.time()),
            "type": 3,
            "dt": 2,
            "play_type": 0,
            "from_spmid": 0,
            "spmid": 0,
            "auto_continued_play": 0,
            "refer_url": "https%3A%2F%2Ft.bilibili.com%2F",
            "bsource": "",
        }
        resp = self.request(
            "POST",
            "https://api.bilibili.com/x/click-interface/web/heartbeat",
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"https://www.bilibili.com/video/{bvid}",
            },
        )
        ok = resp.get("code") == 0
        logger.info("观看 %s: %s", bvid, "成功" if ok else resp.get("message"))
        return ok

    def share(self, aid: Any, cid: Any, short_link: str) -> bool:
        if not self.access_token:
            # 无 access_token 时尝试 web 分享接口降级
            resp = self.request(
                "POST",
                "https://api.bilibili.com/x/web-interface/share/add",
                data={
                    "aid": aid,
                    "csrf": self.cookies.get("bili_jct"),
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded"
                },
            )
            ok = resp.get("code") == 0
            logger.info("分享(web): %s", "成功" if ok else resp.get("message"))
            return ok

        body = app_sign(
            {
                "access_key": self.access_token,
                "actionKey": "appkey",
                "appkey": APPKEY,
                "build": "72700100",
                "c_locale": "zh-Hans_CN",
                "device": "phone",
                "disable_rcmd": 0,
                "link": short_link,
                "mobi_app": "iphone",
                "object_extra_fields": "%7B%7D",
                "oid": aid,
                "panel_type": 1,
                "platform": "ios",
                "s_locale": "zh-Hans_CN",
                "share_channel": "WEIXIN",
                "share_id": "main.ugc-video-detail.0.0.pv",
                "share_origin": "vinfo_share",
                "sid": cid,
                "spm_id": "main.ugc-video-detail.0.0",
                "statistics": "%7B%22appId%22%3A1%2C%22version%22%3A%228.44.0%22%2C%22abtest%22%3A%22%22%2C%22platform%22%3A1%7D",
                "success": 1,
                "ts": int(time.time()),
            }
        )
        # 签名后按 key 排序提交
        ordered = {k: body[k] for k in sorted(body.keys())}
        resp = self.request(
            "POST",
            "https://api.bilibili.com/x/share/finish",
            data=ordered,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        ok = resp.get("code") == 0
        logger.info("分享: %s", "成功" if ok else resp.get("message"))
        return ok

    def followings(self, ps: int = 20) -> list[int]:
        mid = self.cookies.get("DedeUserID") or self.user.get("mid")
        resp = self.request(
            "GET",
            "https://api.bilibili.com/x/relation/followings",
            params={
                "vmid": mid,
                "ps": ps,
                "order_type": "attention",
            },
        )
        if resp.get("code") != 0:
            logger.warning("关注列表失败: %s", resp.get("message"))
            return []
        lst = (resp.get("data") or {}).get("list") or []
        return [int(x["mid"]) for x in lst if x.get("mid")]

    def random_aid_from_mid(self, mid: int) -> int:
        # 简单列表接口（无 wbi 时部分环境可用）
        resp = self.request(
            "GET",
            "https://api.bilibili.com/x/space/arc/search",
            params={"mid": mid, "ps": 10, "pn": 1, "order": "pubdate"},
            headers={"Referer": f"https://space.bilibili.com/{mid}"},
        )
        if resp.get("code") != 0:
            return 0
        vlist = ((resp.get("data") or {}).get("list") or {}).get("vlist") or []
        if not vlist:
            return 0
        item = random.choice(vlist)
        logger.info(
            "投币候选: %s - %s",
            item.get("author"),
            (item.get("title") or "")[:40],
        )
        return int(item.get("aid") or 0)

    def coin_add(self, aid: int) -> bool:
        if self.access_token:
            body = {
                "access_key": self.access_token,
                "aid": aid,
                "multiply": 1,
                "select_like": 0,
            }
            resp = self.request(
                "POST",
                "https://app.bilibili.com/x/v2/view/coin/add",
                data=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "app-key": "iphone",
                },
            )
        else:
            resp = self.request(
                "POST",
                "https://api.bilibili.com/x/web-interface/coin/add",
                data={
                    "aid": aid,
                    "multiply": 1,
                    "select_like": 0,
                    "cross_domain": "true",
                    "csrf": self.cookies.get("bili_jct"),
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": "https://www.bilibili.com",
                },
            )
        ok = resp.get("code") == 0
        logger.info("投币 aid=%s: %s", aid, "成功" if ok else resp.get("message"))
        return ok

    def silver2coin(self) -> str:
        resp = self.request(
            "POST",
            "https://api.live.bilibili.com/xlive/revenue/v1/wallet/silver2coin",
            data={
                "csrf": self.cookies.get("bili_jct"),
                "csrf_token": self.cookies.get("bili_jct"),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        code = resp.get("code")
        if code == 0:
            d = resp.get("data") or {}
            return f"兑换成功 +{d.get('coin')} 硬币"
        if code == 403:
            return f"未兑换: {resp.get('message')}"
        return f"失败: {resp.get('message')}"

    def vip_extra_exp(self) -> str:
        if not self.access_token:
            return "跳过(需 access_token，请扫码登录)"
        body = app_sign(
            {
                "csrf": self.cookies.get("bili_jct"),
                "ts": int(time.time()),
                "buvid": self.cookies.get("Buvid") or "",
                "mobi_app": "iphone",
                "platform": "ios",
                "appkey": APPKEY,
                "access_key": self.access_token,
            }
        )
        resp = self.request(
            "POST",
            "https://api.bilibili.com/x/vip/experience/add",
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "app-key": "iphone",
            },
        )
        if resp.get("code") == 0:
            return "额外经验 +10"
        return f"额外经验: {resp.get('message')}"

    def live_sign(self) -> str:
        """直播中心签到（部分账号已下线，失败会忽略）。"""
        resp = self.request(
            "GET",
            "https://api.live.bilibili.com/xlive/web-ucenter/v1/sign/DoSign",
        )
        code = resp.get("code")
        if code == 0:
            d = resp.get("data") or {}
            return f"成功 {d.get('text') or ''} 连续{d.get('hadSignDays')}天"
        if code == 1011040:
            return "今日已签"
        return f"{resp.get('message') or code}"

    def manga_sign(self) -> str:
        """漫画 App 签到（领卡券积分，与主站经验无关）。"""
        resp = self.request(
            "POST",
            "https://manga.bilibili.com/twirp/activity.v1.Activity/ClockIn",
            data={"platform": "android"},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://manga.bilibili.com",
            },
        )
        # 漫画接口成功常为 code=0；已签可能是 "clockin clockin has duplicate"
        code = resp.get("code")
        msg = str(resp.get("msg") or resp.get("message") or "")
        if code == 0:
            return "成功"
        if "duplicate" in msg.lower() or "已" in msg:
            return f"今日已签 ({msg or code})"
        return f"{msg or code}"

    def big_score_sign(self) -> str:
        """大会员大积分 · 三日签到。"""
        if not self.access_token:
            return "跳过(需 access_token)"
        resp = self.request(
            "POST",
            f"https://api.bilibili.com/pgc/activity/score/task/sign2"
            f"?csrf={self.cookies.get('bili_jct')}",
            json_body={"t": now_str(), "device": "phone", "ts": int(time.time())},
            headers={"Referer": "https://big.bilibili.com/mobile/bigPoint/task"},
        )
        if resp.get("code") == 0:
            return "成功"
        return str(resp.get("message") or resp.get("code"))

    def big_score_dress_view(self) -> str:
        if not self.access_token:
            return "跳过"
        body = {
            "csrf": self.cookies.get("bili_jct"),
            "ts": int(time.time()),
            "taskCode": "dress-view",
            "statistics": "%7B%22appId%22%3A1%2C%22version%22%3A%228.44.0%22%2C%22abtest%22%3A%22%22%2C%22platform%22%3A1%7D",
            "appkey": APPKEY,
            "access_key": self.access_token,
        }
        resp = self.request(
            "POST",
            "https://api.bilibili.com/pgc/activity/score/task/complete/v2",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.get("code") == 0:
            return "浏览装扮商城 成功"
        return f"装扮商城: {resp.get('message')}"

    def big_score_vipmall(self) -> str:
        resp = self.request(
            "POST",
            "https://show.bilibili.com/api/activity/fire/common/event/dispatch",
            json_body={"eventId": "hevent_oy4b7h3epeb"},
            headers={"Content-Type": "application/json"},
        )
        if resp.get("code") == 0:
            return "浏览会员购 成功"
        return f"会员购: {resp.get('message')}"

    def vip_privilege_monthly(self) -> list[str]:
        """每月 1/15 尝试领大会员福利（B 币券等）。"""
        day = time.strftime("%d")  # 01..31
        if day not in ("01", "15"):
            return []
        out: list[str] = []
        # 年度大会员更多权益；普通大会员 6/7
        vip_type = int(self.user.get("vipType") or 0)
        types = [1, 2, 3, 4, 5, 6, 7] if vip_type == 2 else [6, 7]
        for t in types:
            resp = self.request(
                "POST",
                "https://api.bilibili.com/x/vip/privilege/receive",
                data={
                    "csrf": self.cookies.get("bili_jct"),
                    "type": t,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.get("code") == 0:
                out.append(f"福利 type={t} 领取成功")
            else:
                out.append(f"福利 type={t}: {resp.get('message')}")
            time.sleep(0.4)
        return out

    def run_daily(self, info_only: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.account.name,
            "ok": False,
            "need_cookie": False,
            "lines": [],
        }
        lines: list[str] = []
        cache_path = resolve_cache_path()

        def mark(ok: bool, title: str, detail: str = "") -> str:
            icon = "✅" if ok else "⚠️"
            if detail:
                return f"  {icon} {title}：{detail}"
            return f"  {icon} {title}"

        def skip(title: str, detail: str) -> str:
            return f"  ⏭️  {title}：{detail}"

        if not self.cookies.get("SESSDATA"):
            result["need_cookie"] = True
            lines.extend(
                [
                    f"📺 B站每日任务 · {self.account.name}",
                    "────────────────",
                    "❌ 未找到有效 Cookie",
                    "",
                    "请先运行扫码脚本获取 Cookie：",
                    "  · 本地：uv run get_cookie.py",
                    "  · 青龙：手动运行任务「B站获取Cookie」",
                    "",
                    f"Cookie 保存位置：{cache_path}",
                    "获取成功后，再执行 daily.py / 定时任务即可。",
                ]
            )
            result["lines"] = lines
            return result

        if not self.me():
            result["need_cookie"] = True
            lines.extend(
                [
                    f"📺 B站每日任务 · {self.account.name}",
                    "────────────────",
                    "❌ Cookie 已失效（请重新扫码）",
                    "",
                    "  · 本地：uv run get_cookie.py",
                    "  · 青龙：运行「B站获取Cookie」",
                    f"  · 缓存：{cache_path}",
                ]
            )
            result["lines"] = lines
            return result

        uname = self.user.get("uname") or self.account.name
        result["uname"] = uname
        li = self.user.get("level_info") or {}
        money0 = int(self.user.get("money") or 0)
        lines.extend(
            [
                f"📺 B站每日任务 · {uname}",
                "────────────────",
                f"👤 等级 Lv{li.get('current_level')}  |  "
                f"经验 {li.get('current_exp')}/{li.get('next_exp')}  |  "
                f"硬币 {money0}",
                "",
            ]
        )

        if info_only:
            result["ok"] = True
            result["lines"] = lines + ["ℹ️  仅查询信息（--info-only）"]
            return result

        status = self.exp_reward()
        need_watch = not status.get("watch")
        need_share = not status.get("share")
        coins_done = int(status.get("coins") or 0)  # 已得经验，每币 10
        target_coins = self.cfg.coin_num
        need_coin_times = max(0, target_coins - coins_done // 10)

        # 动态里取视频做观看/分享
        watch_detail = "今日已完成" if not need_watch else "待执行"
        share_detail = "今日已完成" if not need_share else "待执行"
        if need_watch or need_share:
            cards = self.dynamic_videos()
            if not cards:
                if need_watch:
                    watch_detail = "动态无视频，跳过"
                if need_share:
                    share_detail = "动态无视频，跳过"
            else:
                item = random.choice(cards)
                desc = item.get("desc") or {}
                try:
                    card = json.loads(item.get("card") or "{}")
                except Exception:
                    card = {}
                aid = desc.get("rid")
                bvid = desc.get("bvid") or card.get("bvid") or ""
                cid = card.get("cid")
                short = (card.get("short_link_v2") or card.get("short_link") or "")
                if isinstance(short, str):
                    short = short.replace("\\/", "/")
                short_enc = quote(short, safe="") if short else ""

                if need_watch and aid and cid and bvid:
                    ok = self.watch(aid, bvid, cid)
                    watch_detail = f"成功 {bvid}" if ok else "失败"
                    time.sleep(1)
                if need_share and aid and cid:
                    ok = self.share(aid, cid, short_enc or short)
                    share_detail = "成功" if ok else "失败"
                    time.sleep(1)

        # 投币（失败重试）
        money = float(self.user.get("money") or 0)
        coin_success = 0
        coin_detail = ""
        if need_coin_times <= 0:
            coin_detail = "今日已完成或目标为 0"
        elif money <= 5:
            coin_detail = "硬币不足（≤5 停止）"
        else:
            mids = self.followings()
            if not mids:
                coin_detail = "无关注列表，请先关注一些 UP"
            else:
                attempts = 0
                max_attempts = need_coin_times + 10
                while coin_success < need_coin_times and attempts < max_attempts:
                    attempts += 1
                    if money <= 5:
                        coin_detail = f"成功{coin_success}/{need_coin_times}（硬币不足停）"
                        break
                    aid = 0
                    for _try in range(6):
                        mid = random.choice(mids)
                        aid = self.random_aid_from_mid(mid)
                        if aid:
                            break
                    if not aid:
                        time.sleep(0.3)
                        continue
                    if self.coin_add(aid):
                        coin_success += 1
                        money -= 1
                    time.sleep(0.5)
                if not coin_detail:
                    coin_detail = (
                        f"本次 +{coin_success}/{need_coin_times} "
                        f"（尝试 {attempts} 次）"
                    )

        extras: list[str] = []
        if self.cfg.silver2coin:
            s2c = self.silver2coin()
            if "成功" in s2c:
                extras.append(mark(True, "银瓜子兑硬币", s2c))
            else:
                extras.append(skip("银瓜子兑硬币", s2c))

        if self.cfg.live_sign:
            ls = self.live_sign()
            if "成功" in ls or "已签" in ls:
                extras.append(mark(True, "直播签到", ls))
            else:
                extras.append(skip("直播签到", ls))

        if self.cfg.manga_sign:
            ms = self.manga_sign()
            manga_ok = any(
                k in ms for k in ("成功", "已签", "重复", "duplicate")
            )
            extras.append(mark(manga_ok, "漫画签到", ms))

        if self.cfg.vip_tasks and int(self.user.get("vipStatus") or 0) == 1:
            for title, fn in (
                ("大会员额外经验", self.vip_extra_exp),
                ("大积分三日签", self.big_score_sign),
                ("大积分·装扮商城", self.big_score_dress_view),
                ("大积分·会员购", self.big_score_vipmall),
            ):
                msg = fn()
                ok = "成功" in msg or "+10" in msg
                extras.append(mark(ok, title, msg) if ok else skip(title, msg))
            for p in self.vip_privilege_monthly():
                extras.append(mark("成功" in p, "大会员月度福利", p))

        # 结算
        status2 = self.exp_reward()
        watch_ok = bool(status2.get("watch"))
        share_ok = bool(status2.get("share"))
        coins_exp = int(status2.get("coins") or 0)
        coin_ok = coins_exp >= min(50, target_coins * 10) or target_coins == 0
        login_ok = bool(status2.get("login")) or watch_ok

        lines.append("📋 主站经验")
        lines.append(mark(login_ok, "登录"))
        lines.append(
            mark(watch_ok, "观看", watch_detail if need_watch else "今日已完成")
        )
        lines.append(
            mark(share_ok, "分享", share_detail if need_share else "今日已完成")
        )
        lines.append(
            mark(
                coin_ok,
                "投币",
                f"{coins_exp // 10}/5 枚 · 经验 {coins_exp}/50"
                + (f" · {coin_detail}" if coin_detail else ""),
            )
        )

        if extras:
            lines.append("")
            lines.append("🎁 扩展任务")
            lines.extend(extras)

        lines.append("")
        core_done = login_ok and watch_ok and share_ok and coin_ok
        if core_done:
            lines.append("🏁 完成度：主站经验任务已完成 ✅")
        else:
            missing = []
            if not login_ok:
                missing.append("登录")
            if not watch_ok:
                missing.append("观看")
            if not share_ok:
                missing.append("分享")
            if not coin_ok:
                missing.append(f"投币({coins_exp // 10}/{target_coins})")
            lines.append("🏁 完成度：主站未完成 ⚠️  缺 " + "、".join(missing))

        result["ok"] = True
        result["core_done"] = core_done
        result["lines"] = lines
        return result


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def pick_accounts(cfg: AppConfig, only: str = "") -> list[Account]:
    """
    合并「配置账号」+「Cookie 缓存中的全部账号」。
    同一 mid 只保留一条；有 Cookie 的才会进入任务列表。
    """
    by_mid: dict[str, Account] = {}
    order: list[str] = []

    def _add(acc: Account) -> None:
        acc.normalize()
        if not acc.has_cookie():
            acc = merge_account_credentials(acc)
        if not acc.has_cookie() and not acc.has_password():
            return
        mid = _mid_from_cookie(acc.cookie) if acc.has_cookie() else ""
        uid = mid or f"name:{acc.name}"
        if uid in by_mid:
            # 已有则合并 token/name（昵称优先）
            old = by_mid[uid]
            if acc.access_token and not old.access_token:
                old.access_token = acc.access_token
            if acc.cookie:
                old.cookie = acc.cookie
            # 显示名：更像昵称的覆盖「主号」
            if old.name in ("主号", "扫码待识别") and acc.name not in (
                "主号",
                "扫码待识别",
            ):
                old.name = acc.name
            return
        by_mid[uid] = acc
        order.append(uid)

    for acc in cfg.accounts:
        _add(Account(
            name=acc.name,
            cookie=acc.cookie,
            username=acc.username,
            password=acc.password,
            access_token=acc.access_token,
        ))
    for acc in list_cached_accounts():
        _add(acc)

    accs = [by_mid[k] for k in order]
    if only:
        only = only.strip()
        filtered = [
            a
            for a in accs
            if a.name == only
            or only in a.name
            or _mid_from_cookie(a.cookie) == only
        ]
        if not filtered:
            raise SystemExit(f"未找到账号: {only}（可用昵称 / mid / 缓存键）")
        return filtered
    return accs


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser(description="B 站每日任务")
    ap.add_argument("--config", type=Path, default=None, help="配置文件路径")
    ap.add_argument("--account", default="", help="只处理指定 name")
    ap.add_argument("--qr", action="store_true", help="扫码登录并缓存 Cookie")
    ap.add_argument(
        "--login-password",
        action="store_true",
        help="尝试用户名密码登录（常被极验拦截）",
    )
    ap.add_argument("--info-only", action="store_true", help="只查用户信息")
    ap.add_argument("--coin", type=int, default=None, help="覆盖投币次数 0-5")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.coin is not None:
        cfg.coin_num = max(0, min(5, args.coin))

    accounts = pick_accounts(cfg, args.account)
    if not accounts:
        logger.error("无账号。请配置 config.yaml 或环境变量，或: python daily.py --qr")
        return 1

    summaries: list[str] = []
    any_fail = False
    need_cookie = False

    logger.info("Cookie 缓存路径: %s", resolve_cache_path())
    logger.info("本次共 %s 个账号", len(accounts))
    for i, a in enumerate(accounts, 1):
        mid = _mid_from_cookie(a.cookie) if a.has_cookie() else "-"
        logger.info("  %s) %s  mid=%s  cookie=%s", i, a.name, mid or "?", "有" if a.has_cookie() else "无")

    for acc in accounts:
        logger.info("======== %s ========", acc.name)
        client = BiliClient(acc, cfg)

        if args.qr:
            logger.info("提示：青龙环境更推荐单独运行 get_cookie.py")
            if not client.qr_login():
                any_fail = True
                summaries.append(f"{acc.name}: 扫码失败")
                continue
            acc = merge_account_credentials(acc)
            client = BiliClient(acc, cfg)

        if args.login_password:
            if not client.password_login():
                any_fail = True
                summaries.append(f"{acc.name}: 账密登录失败")
                continue
            acc = merge_account_credentials(acc)
            client = BiliClient(acc, cfg)

        # 无 cookie 时尝试账密自动登（非扫码场景）
        if (
            not client.cookies.get("SESSDATA")
            and acc.has_password()
            and not args.qr
        ):
            logger.info("尝试账密登录…")
            if client.password_login():
                acc = merge_account_credentials(acc)
                client = BiliClient(acc, cfg)

        res = client.run_daily(info_only=args.info_only)
        text = "\n".join(res.get("lines") or [])
        print("\n" + text + "\n")
        summaries.append(text or f"{acc.name}: 无输出")
        if res.get("need_cookie"):
            need_cookie = True
            any_fail = True
        elif not res.get("ok"):
            any_fail = True
        elif res.get("ok") and res.get("core_done") is False:
            any_fail = True

    body = "\n\n".join(summaries)
    if need_cookie:
        title = "B站每日任务 · 需要获取 Cookie"
    elif any_fail:
        title = "B站每日任务 · 有未完成项"
    else:
        title = "B站每日任务 · 完成 ✅"
    print("=" * 40)
    print(body)
    send_notify(cfg.notify, title, body[:1500])
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
