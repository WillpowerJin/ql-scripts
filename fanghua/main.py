#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
芳华未来（com.mytek.rtlive）挂机脚本

支持：
  1. 直接使用已有 AppToken（推荐，长期复用）
  2. 短信验证码登录（服务端已关闭密码登录，首次用 --sms-login 获取 Token）
  3. 手机号 + 密码登录（保留兼容；当前服务端返回「暂不支持密码登录」）
  4. 签到 / 刷视频 / 领积分 / 心跳

cron: 0 8 * * *
new Env('芳华未来挂机');

青龙环境变量：
  FANGHUA_ACCOUNTS  JSON 数组，推荐
    [{"name":"主号","token":"AppToken..."}]
    或 [{"name":"主号","phone":"138...","sms_code":"123456"}]   # 验证码一次性
    或 [{"name":"主号","phone":"138...","password":"..."}]       # 服务端已关闭
  或按索引对齐：
    FANGHUA_PHONE / FANGHUA_PASSWORD / FANGHUA_TOKEN / FANGHUA_SMS_CODE
    / FANGHUA_NAME / FANGHUA_JPUSH
  本地也可使用 config.yaml（见 config.example.yaml）

通知（可选）：BARK_URL 或 BARK_KEY
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import requests

from crypto_api import FanghuaClient

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BARK_SERVER = "https://api.day.app"

WATCH_TIME_MIN = 12
WATCH_TIME_MAX = 65
PLAY_3S_DELAY_MIN = 3.2
PLAY_3S_DELAY_MAX = 7.5
NEXT_VIDEO_DELAY_MIN = 1.5
NEXT_VIDEO_DELAY_MAX = 12.0
SKIP_VIDEO_PROBABILITY = 15
EXIT_MIDWAY_PROBABILITY = 8
BATCH_VIDEO_COUNT_MIN = 5
BATCH_VIDEO_COUNT_MAX = 18
BATCH_REST_TIME_MIN = 14
BATCH_REST_TIME_MAX = 120
INTEGRAL_INTERVAL = 10
INTEGRAL_TYPE = 2
MAX_RUN_HOURS_PER_ACCOUNT = 2.0
HEARTBEAT_INTERVAL_BASE = 600
HEARTBEAT_INTERVAL_JITTER = 120
START_DELAY_MIN = 0
START_DELAY_MAX = 8
# 多账号缓存写保护
cache_lock = threading.Lock()

logger = logging.getLogger("fanghua")
print_lock = threading.Lock()
summary_lock = threading.Lock()
summary_reports: list[str] = []


def resolve_token_cache_path() -> Path:
    """
    Token 缓存路径：
      1) FANGHUA_TOKEN_CACHE
      2) 青龙：/ql/data/fanghua_token_cache.json（订阅更新不覆盖）
      3) 脚本目录 token_cache.json
    """
    env = (os.environ.get("FANGHUA_TOKEN_CACHE") or "").strip()
    if env:
        return Path(env).expanduser()
    ql_data = (os.environ.get("QL_DATA_DIR") or "").strip()
    if ql_data:
        return Path(ql_data) / "fanghua_token_cache.json"
    if Path("/ql/data").is_dir():
        return Path("/ql/data/fanghua_token_cache.json")
    return SCRIPT_DIR / "token_cache.json"


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass
class Account:
    name: str
    phone: str = ""
    password: str = ""
    token: str = ""
    sms_code: str = ""
    jpush_id: str = ""
    device_id: str = ""

    def has_password(self) -> bool:
        return bool(self.phone.strip() and self.password.strip())

    def has_token(self) -> bool:
        return bool(self.token.strip())


@dataclass
class RuntimeConfig:
    accounts: list[Account] = field(default_factory=list)
    max_run_hours: float = MAX_RUN_HOURS_PER_ACCOUNT
    timeout: float = 15.0
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER


def _split_multi(value: str) -> list[str]:
    return [x.strip() for x in value.replace("\n", "&").split("&") if x.strip()]


def _stable_device_id(seed: str) -> str:
    """由账号标识生成稳定、可复现的 32 位大写 hex 设备 ID（不同账号必不同）。"""
    digest = hashlib.sha256(f"fanghua-device|{seed}".encode("utf-8")).hexdigest().upper()
    return digest[:32]


def _stable_jpush_id(seed: str) -> str:
    digest = hashlib.sha256(f"fanghua-jpush|{seed}".encode("utf-8")).hexdigest()
    return digest[:32]


def _account_cache_key(account: Account) -> str:
    return (account.phone or account.name or "default").strip()


def load_token_cache() -> dict[str, Any]:
    """缓存结构（按账号隔离）:
    {
      "138xxxx": {"token": "...", "device_id": "...", "jpush_id": "..."},
      ...
    }
    兼容旧版纯字符串: "138xxxx": "token..."
    """
    path = resolve_token_cache_path()
    if not path.exists():
        # 兼容旧本地路径
        legacy = SCRIPT_DIR / "token_cache.json"
        if legacy.exists() and legacy != path:
            path = legacy
        else:
            return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(v, str):
            out[k] = {"token": v, "device_id": "", "jpush_id": ""}
        elif isinstance(v, dict):
            out[k] = {
                "token": str(v.get("token") or ""),
                "device_id": str(v.get("device_id") or ""),
                "jpush_id": str(v.get("jpush_id") or ""),
            }
    return out


def save_token_cache(cache: dict[str, Any]) -> None:
    path = resolve_token_cache_path()
    try:
        with cache_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except Exception as exc:
        logger.warning("写入 token 缓存失败 (%s): %s", path, exc)


def resolve_account_ids(account: Account, cache: dict[str, Any]) -> tuple[str, str]:
    """为账号解析稳定的 device_id / jpush_id，并写回 account + cache。

    优先级：配置文件 > 缓存 > 按手机号稳定生成。
    保证：同账号跨次运行 ID 不变；不同账号 ID 不同。
    """
    key = _account_cache_key(account)
    entry = cache.get(key) if isinstance(cache.get(key), dict) else {}
    if not isinstance(entry, dict):
        entry = {}

    device_id = (
        (account.device_id or "").strip()
        or str(entry.get("device_id") or "").strip()
        or _stable_device_id(key)
    )
    jpush_id = (
        (account.jpush_id or "").strip()
        or str(entry.get("jpush_id") or "").strip()
        or _stable_jpush_id(key)
    )
    account.device_id = device_id
    account.jpush_id = jpush_id
    entry["device_id"] = device_id
    entry["jpush_id"] = jpush_id
    if account.token:
        entry["token"] = account.token
    elif entry.get("token"):
        pass
    cache[key] = entry
    return device_id, jpush_id


def update_account_cache(
    cache: dict[str, Any],
    account: Account,
    *,
    token: str = "",
) -> None:
    key = _account_cache_key(account)
    entry = cache.get(key) if isinstance(cache.get(key), dict) else {}
    if not isinstance(entry, dict):
        entry = {}
    if token:
        entry["token"] = token
        account.token = token
    if account.device_id:
        entry["device_id"] = account.device_id
    if account.jpush_id:
        entry["jpush_id"] = account.jpush_id
    cache[key] = entry
    save_token_cache(cache)


def load_accounts_from_env() -> list[Account]:
    raw = os.environ.get("FANGHUA_ACCOUNTS", "").strip()
    if raw:
        data = json.loads(raw)
        accounts: list[Account] = []
        for i, item in enumerate(data, 1):
            accounts.append(
                Account(
                    name=str(item.get("name") or item.get("phone") or f"账号{i}"),
                    phone=str(item.get("phone") or ""),
                    password=str(item.get("password") or ""),
                    token=str(item.get("token") or item.get("app_token") or ""),
                    sms_code=str(item.get("sms_code") or item.get("code") or ""),
                    jpush_id=str(item.get("jpush_id") or item.get("jpushId") or ""),
                    device_id=str(item.get("device_id") or item.get("deviceId") or ""),
                )
            )
        return accounts

    phones = _split_multi(os.environ.get("FANGHUA_PHONE", ""))
    passwords = _split_multi(os.environ.get("FANGHUA_PASSWORD", ""))
    tokens = _split_multi(os.environ.get("FANGHUA_TOKEN", ""))
    codes = _split_multi(os.environ.get("FANGHUA_SMS_CODE", ""))
    names = _split_multi(os.environ.get("FANGHUA_NAME", ""))
    jpushes = _split_multi(os.environ.get("FANGHUA_JPUSH", ""))
    n = max(len(phones), len(tokens), 0)
    if n == 0:
        return []
    accounts = []
    for i in range(n):
        phone = phones[i] if i < len(phones) else ""
        token = tokens[i] if i < len(tokens) else ""
        password = passwords[i] if i < len(passwords) else ""
        sms_code = codes[i] if i < len(codes) else ""
        name = names[i] if i < len(names) else (phone or f"账号{i+1}")
        jpush = jpushes[i] if i < len(jpushes) else ""
        accounts.append(
            Account(
                name=name,
                phone=phone,
                password=password,
                token=token,
                sms_code=sms_code,
                jpush_id=jpush,
            )
        )
    return accounts


def load_config_yaml(path: Path) -> RuntimeConfig:
    cfg = RuntimeConfig()
    if not path.exists():
        return cfg
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.warning("未安装 PyYAML，跳过 %s", path)
        return cfg
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    accounts = []
    for i, item in enumerate(data.get("accounts") or [], 1):
        accounts.append(
            Account(
                name=str(item.get("name") or item.get("phone") or f"账号{i}"),
                phone=str(item.get("phone") or ""),
                password=str(item.get("password") or ""),
                token=str(item.get("token") or item.get("app_token") or ""),
                sms_code=str(item.get("sms_code") or item.get("code") or ""),
                jpush_id=str(item.get("jpush_id") or item.get("jpushId") or ""),
                device_id=str(item.get("device_id") or item.get("deviceId") or ""),
            )
        )
    cfg.accounts = accounts
    cfg.max_run_hours = float(data.get("max_run_hours", MAX_RUN_HOURS_PER_ACCOUNT))
    cfg.timeout = float(data.get("timeout", 15))
    notify = data.get("notify") or {}
    cfg.bark_url = str(notify.get("bark_url") or "")
    cfg.bark_key = str(notify.get("bark_key") or "")
    cfg.bark_server = str(notify.get("bark_server") or DEFAULT_BARK_SERVER)
    return cfg


def merge_config() -> RuntimeConfig:
    yaml_cfg = load_config_yaml(SCRIPT_DIR / "config.yaml")
    env_accounts = load_accounts_from_env()
    cfg = yaml_cfg
    if env_accounts:
        cfg.accounts = env_accounts
    if os.environ.get("FANGHUA_MAX_RUN_HOURS"):
        cfg.max_run_hours = float(os.environ["FANGHUA_MAX_RUN_HOURS"])
    # 通知：与 hifiti / bilibili 共用 BARK_*
    bark_url = (os.environ.get("BARK_URL") or os.environ.get("BARK_PUSH") or "").strip()
    bark_key = (os.environ.get("BARK_KEY") or os.environ.get("BARK_DEVICE_KEY") or "").strip()
    if bark_url and not bark_url.startswith("http"):
        bark_key = bark_key or bark_url
        bark_url = ""
    if bark_url:
        cfg.bark_url = bark_url
    if bark_key:
        cfg.bark_key = bark_key
    if os.environ.get("BARK_SERVER"):
        cfg.bark_server = os.environ["BARK_SERVER"].strip().rstrip("/")
    return cfg


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------


def send_bark(cfg: RuntimeConfig, title: str, content: str) -> None:
    """POST JSON 推送；失败时 fallback GET。"""
    url = (cfg.bark_url or "").strip().rstrip("/")
    key = (cfg.bark_key or "").strip()
    if not url and key:
        server = (cfg.bark_server or DEFAULT_BARK_SERVER).rstrip("/")
        url = f"{server}/{key}"
    if not url:
        logger.info(
            "📣 未配置 BARK_URL/BARK_KEY，跳过推送"
            "（青龙环境变量与 hifiti 共用即可）"
        )
        return
    if not url.startswith("http"):
        url = f"{DEFAULT_BARK_SERVER.rstrip('/')}/{url}"

    payload = {
        "title": title[:200],
        "body": content[:3500],
        "group": "芳华未来",
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code >= 400:
            from urllib.parse import quote

            get_url = (
                f"{url}/"
                f"{quote(title[:100], safe='')}/"
                f"{quote(content[:500], safe='')}"
            )
            r = requests.get(get_url, timeout=15)
        ok = r.status_code < 400
        logger.info(
            "📣 Bark %s（HTTP %s）",
            "已推送" if ok else "失败",
            r.status_code,
        )
        if not ok:
            logger.warning("Bark 响应: %s", (r.text or "")[:200])
    except Exception as exc:
        logger.warning("📣 Bark 推送失败: %s", exc)


# ---------------------------------------------------------------------------
# 登录 / 任务
# ---------------------------------------------------------------------------


def _login_with_token(
    account: Account, client: FanghuaClient, cache: dict[str, Any], token: str
) -> bool:
    client.set_token(token)
    info = client.get_user_info()
    if info.get("code") == 200 and info.get("user"):
        update_account_cache(cache, account, token=token)
        logger.info(
            "[%s] Token 有效 userId=%s", account.name, info["user"].get("userId")
        )
        return True
    logger.info(
        "[%s] Token 已失效: %s", account.name, info.get("msg") or info.get("code")
    )
    # 清掉失效 Token，避免登录请求带着旧 AppToken 被服务端直接拒绝
    client.set_token("")
    return False


def _login_with_sms(
    account: Account, client: FanghuaClient, cache: dict[str, Any]
) -> bool:
    if not account.phone.strip():
        logger.error("[%s] 短信登录需要 phone", account.name)
        return False
    if not account.sms_code.strip():
        return False
    logger.info("[%s] 使用短信验证码登录…", account.name)
    res = client.login_by_phone(
        account.phone, account.sms_code.strip(), jpush_id=account.jpush_id
    )
    if res.get("code") == 200 and res.get("token"):
        update_account_cache(cache, account, token=res["token"])
        user = res.get("user") or {}
        logger.info(
            "[%s] 验证码登录成功 userId=%s integral=%s",
            account.name,
            user.get("userId"),
            user.get("integral"),
        )
        return True
    if res.get("code") == 200 and isinstance(res.get("users"), list):
        logger.error(
            "[%s] 返回多用户列表，请先在 App 内选定账号，再复制 Token 到配置: %s",
            account.name,
            res.get("msg"),
        )
        return False
    logger.error("[%s] 验证码登录失败: %s", account.name, res.get("msg") or res)
    return False


def ensure_login(account: Account, client: FanghuaClient, cache: dict[str, Any]) -> bool:
    """登录顺序：缓存 Token → 手机号密码 → 短信验证码。

    服务端目前已关闭密码登录（code=500「暂不支持密码登录」），
    常规运行应依赖 Token；首次可用 --sms-login 或 FANGHUA_SMS_CODE 获取。
    """
    cache_key = _account_cache_key(account)
    entry = cache.get(cache_key) if isinstance(cache.get(cache_key), dict) else {}
    if not isinstance(entry, dict):
        entry = {}

    # 1) 先用已有 Token，避免每次重登把 App 端 Token 顶掉
    token = (account.token or "").strip() or str(entry.get("token") or "").strip()
    if token and _login_with_token(account, client, cache, token):
        return True

    # 2) 密码登录（服务端若重新开放则可用）
    if account.has_password():
        logger.info(
            "[%s] 尝试手机号密码登录… deviceId=%s… jpush=%s…",
            account.name,
            (account.device_id or "")[:8],
            (account.jpush_id or "")[:8],
        )
        res = client.login(account.phone, account.password, jpush_id=account.jpush_id)
        if res.get("code") == 200 and res.get("token"):
            update_account_cache(cache, account, token=res["token"])
            user = res.get("user") or {}
            logger.info(
                "[%s] 密码登录成功 userId=%s integral=%s",
                account.name,
                user.get("userId"),
                user.get("integral"),
            )
            return True
        if res.get("code") == 200 and isinstance(res.get("users"), list):
            logger.error(
                "[%s] 返回多用户列表，请在 App 内选定账号后再用 token 方式运行: %s",
                account.name,
                res.get("msg"),
            )
            return False
        msg = str(res.get("msg") or "")
        if "密码登录" in msg and "不支持" in msg:
            logger.warning("[%s] 服务端已关闭密码登录，改走短信验证码", account.name)
        else:
            logger.error("[%s] 密码登录失败: %s", account.name, msg or res)
    elif not account.sms_code:
        logger.info("[%s] 未配置 password，尝试使用已有 Token", account.name)

    # 3) 短信验证码登录（需要一次性 sms_code）
    if _login_with_sms(account, client, cache):
        return True

    logger.error(
        "[%s] 登录失败：服务端不支持密码登录，当前也没有有效 Token。"
        "请先在本机运行 `python3 main.py --sms-login`（会发短信并提示输入验证码），"
        "成功后会写入 Token 缓存，之后定时任务无需再登录。",
        account.name,
    )
    return False


def safe_call(label: str, fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("%s 异常: %s", label, exc)
        return None


def run_account(account: Account, cfg: RuntimeConfig, cache: dict[str, Any], rng: random.Random) -> None:
    # 每账号独立、稳定的 device / jpush，互不串号
    device_id, jpush_id = resolve_account_ids(account, cache)
    save_token_cache(cache)
    client = FanghuaClient(
        app_token=account.token,
        device_id=device_id,
        timeout=cfg.timeout,
    )
    # login 体里的 jpushId 与请求头 X-Api-DeviceId 分开：jpush 用稳定 jpush_id
    account.jpush_id = jpush_id
    if not ensure_login(account, client, cache):
        return

    info = safe_call("getUserInfo", client.get_user_info) or {}
    user = info.get("user") or {}
    user_id = user.get("userId")
    init_coin = user.get("integral")
    if not user_id:
        logger.error("[%s] 无法获取 userId", account.name)
        return

    safe_call("createLogs", client.create_logs, user_id)
    safe_call("getAppPageConfig", client.get_app_page_config)
    sign_res = safe_call("sign", client.sign) or {}
    if sign_res.get("code") == 200:
        logger.info("[%s] 签到成功: %s", account.name, sign_res.get("msg") or "ok")
    else:
        logger.info("[%s] 签到: %s", account.name, sign_res.get("msg") or sign_res)

    start_time = time.time()
    last_hb = time.time()
    video_count = 0
    coin_count = 0
    batch_num = 0
    batch_max = rng.randint(BATCH_VIDEO_COUNT_MIN, BATCH_VIDEO_COUNT_MAX)
    stop_reason = "正常结束"

    try:
        while True:
            if time.time() - start_time > cfg.max_run_hours * 3600:
                stop_reason = f"达到 {cfg.max_run_hours} 小时上限"
                break

            if batch_num >= batch_max:
                sleep_s = rng.uniform(BATCH_REST_TIME_MIN, BATCH_REST_TIME_MAX)
                logger.info("[%s] 本批次 %s 条完成，休息 %.1fs", account.name, batch_max, sleep_s)
                time.sleep(sleep_s)
                batch_num = 0
                batch_max = rng.randint(BATCH_VIDEO_COUNT_MIN, BATCH_VIDEO_COUNT_MAX)

            vres = safe_call("getVideoList", client.get_video_list) or {}
            vlist = ((vres.get("data") or {}).get("list")) if isinstance(vres, dict) else None
            if not vlist:
                logger.warning("[%s] 未获取到视频，60s 后重试: %s", account.name, vres.get("msg") if vres else "")
                time.sleep(60)
                continue
            rng.shuffle(vlist)

            for video in vlist:
                if time.time() - start_time > cfg.max_run_hours * 3600:
                    stop_reason = f"达到 {cfg.max_run_hours} 小时上限"
                    break

                vid = video.get("id")
                safe_call("track PLAY", client.track_video, vid, "PLAY")
                time.sleep(rng.uniform(PLAY_3S_DELAY_MIN, PLAY_3S_DELAY_MAX))
                safe_call("track PLAY_3S", client.track_video, vid, "PLAY_3S")

                if rng.random() < SKIP_VIDEO_PROBABILITY / 100:
                    video_count += 1
                    batch_num += 1
                    logger.info("[%s] 跳过视频 %s，累计 %s", account.name, vid, video_count)
                    time.sleep(rng.uniform(NEXT_VIDEO_DELAY_MIN, NEXT_VIDEO_DELAY_MAX))
                    continue

                watch_total = rng.uniform(WATCH_TIME_MIN, WATCH_TIME_MAX)
                if rng.random() < EXIT_MIDWAY_PROBABILITY / 100:
                    actual = watch_total * rng.uniform(0.3, 0.7)
                    time.sleep(actual)
                    video_count += 1
                    batch_num += 1
                    logger.info("[%s] 中途退出视频 %s，观看 %.1fs", account.name, vid, actual)
                    time.sleep(rng.uniform(NEXT_VIDEO_DELAY_MIN, NEXT_VIDEO_DELAY_MAX))
                    continue

                elapse = 0
                last_coin = 0
                single_coin = 0
                while elapse < watch_total:
                    time.sleep(1)
                    elapse += 1
                    if elapse - last_coin >= INTEGRAL_INTERVAL:
                        ares = safe_call("addIntegral", client.add_integral, INTEGRAL_TYPE, vid) or {}
                        if ares.get("code") == 200:
                            coin_count += 1
                            single_coin += 1
                        last_coin = elapse
                    if time.time() - start_time > cfg.max_run_hours * 3600:
                        break

                safe_call("track COMPLETE", client.track_video, vid, "COMPLETE")
                video_count += 1
                batch_num += 1
                with print_lock:
                    logger.info(
                        "[%s] 完成视频 %s 观看%.1fs 本条领积分%s次 累计视频%s 累计领币%s",
                        account.name,
                        vid,
                        watch_total,
                        single_coin,
                        video_count,
                        coin_count,
                    )
                time.sleep(rng.uniform(NEXT_VIDEO_DELAY_MIN, NEXT_VIDEO_DELAY_MAX))

                hb_gap = HEARTBEAT_INTERVAL_BASE + rng.uniform(
                    -HEARTBEAT_INTERVAL_JITTER, HEARTBEAT_INTERVAL_JITTER
                )
                if time.time() - last_hb > hb_gap:
                    safe_call("heartbeat", client.heartbeat)
                    last_hb = time.time()

            if stop_reason.startswith("达到"):
                break
    except Exception as exc:
        stop_reason = f"异常: {exc}"
        logger.exception("[%s] 任务异常", account.name)

    end_info = safe_call("getUserInfo", client.get_user_info) or {}
    end_coin = (end_info.get("user") or {}).get("integral")
    run_h = round((time.time() - start_time) / 3600, 2)
    profit = None
    if isinstance(init_coin, (int, float)) and isinstance(end_coin, (int, float)):
        profit = end_coin - init_coin
    msg = (
        f"账号：{account.name}\n"
        f"运行：{run_h}h | 视频：{video_count} | 领币次数：{coin_count}\n"
        f"积分：{init_coin} → {end_coin} | 净收益：{profit if profit is not None else 'N/A'}\n"
        f"结束原因：{stop_reason}"
    )
    with summary_lock:
        summary_reports.append(msg)
    logger.info("[%s] 结束\n%s", account.name, msg)


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _mask_phone(phone: str) -> str:
    phone = phone.strip()
    if len(phone) >= 7:
        return f"{phone[:3]}****{phone[-4:]}"
    return phone or "(未配置手机号)"


def _client_for(
    account: Account, cfg: RuntimeConfig, cache: dict[str, Any]
) -> FanghuaClient:
    device_id, jpush_id = resolve_account_ids(account, cache)
    account.jpush_id = jpush_id
    save_token_cache(cache)
    return FanghuaClient(device_id=device_id, timeout=cfg.timeout)


def send_login_codes(cfg: RuntimeConfig, cache: dict[str, Any]) -> int:
    """只发送短信验证码，不登录；配合 --sms-code 使用。"""
    ok = 0
    for acc in cfg.accounts:
        if not acc.phone.strip():
            logger.error("[%s] 未配置手机号，无法发送验证码", acc.name)
            continue
        client = _client_for(acc, cfg, cache)
        res = client.send_code(acc.phone)
        if res.get("code") == 200:
            logger.info("[%s] 验证码已发送至 %s", acc.name, _mask_phone(acc.phone))
            ok += 1
        else:
            logger.error("[%s] 发送验证码失败: %s", acc.name, res.get("msg") or res)
    return 0 if ok == len(cfg.accounts) else 2


def sms_login_interactive(cfg: RuntimeConfig, cache: dict[str, Any]) -> int:
    """发验证码 → 终端输入 6 位码 → 登录并写 Token 缓存。"""
    if not sys.stdin.isatty():
        logger.error(
            "当前不是交互终端，无法输入验证码。"
            "请在本机终端运行，或改用 --send-code + --sms-code。"
        )
        return 2
    ok = 0
    for acc in cfg.accounts:
        if not acc.phone.strip():
            logger.error("[%s] 未配置手机号，无法短信登录", acc.name)
            continue
        client = _client_for(acc, cfg, cache)
        res = client.send_code(acc.phone)
        if res.get("code") != 200:
            logger.error("[%s] 发送验证码失败: %s", acc.name, res.get("msg") or res)
            continue
        logger.info("[%s] 验证码已发送至 %s", acc.name, _mask_phone(acc.phone))
        try:
            code = input(f"[{acc.name}] 请输入收到的验证码（直接回车跳过）: ").strip()
        except (EOFError, KeyboardInterrupt):
            logger.error("[%s] 未输入验证码，跳过", acc.name)
            continue
        if not code:
            logger.warning("[%s] 未输入验证码，跳过", acc.name)
            continue
        res = client.login_by_phone(acc.phone, code, jpush_id=acc.jpush_id)
        if res.get("code") == 200 and res.get("token"):
            update_account_cache(cache, acc, token=res["token"])
            logger.info(
                "[%s] 验证码登录成功，Token 已写入 %s",
                acc.name,
                resolve_token_cache_path(),
            )
            ok += 1
        elif res.get("code") == 200 and isinstance(res.get("users"), list):
            logger.error(
                "[%s] 返回多用户列表（App 内需先选择账号）: %s",
                acc.name,
                res.get("msg"),
            )
        else:
            logger.error("[%s] 验证码登录失败: %s", acc.name, res.get("msg") or res)
    return 0 if ok == len(cfg.accounts) else 2


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="芳华未来挂机（Token / 短信验证码登录）")
    parser.add_argument("-c", "--config", default=str(SCRIPT_DIR / "config.yaml"), help="配置文件路径")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--login-only", action="store_true", help="仅登录校验，不挂机")
    parser.add_argument("--max-hours", type=float, default=None, help="覆盖单账号最长运行小时")
    parser.add_argument(
        "--send-code", action="store_true", help="只发送短信验证码，不登录（配合 --sms-code）"
    )
    parser.add_argument(
        "--sms-login",
        action="store_true",
        help="发送验证码并在终端输入，登录成功后写入 Token 缓存",
    )
    parser.add_argument(
        "--sms-code",
        default="",
        help="短信验证码；多账号用 & 或 , 分隔（按账号顺序对应）",
    )
    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    cfg = merge_config()
    custom = Path(args.config)
    default_cfg = (SCRIPT_DIR / "config.yaml").resolve()
    if custom.exists() and custom.resolve() != default_cfg:
        # 指定其它 yaml：以其为底，环境变量账号/Bark 仍优先
        y = load_config_yaml(custom)
        env_accounts = load_accounts_from_env()
        if env_accounts:
            y.accounts = env_accounts
        env_merged = merge_config()
        y.bark_url = env_merged.bark_url or y.bark_url
        y.bark_key = env_merged.bark_key or y.bark_key
        y.bark_server = env_merged.bark_server or y.bark_server
        if os.environ.get("FANGHUA_MAX_RUN_HOURS"):
            y.max_run_hours = env_merged.max_run_hours
        cfg = y
    if args.max_hours is not None:
        cfg.max_run_hours = args.max_hours
    if args.sms_code:
        codes = [x.strip() for x in args.sms_code.replace("&", ",").split(",") if x.strip()]
        for i, acc in enumerate(cfg.accounts):
            if i < len(codes):
                acc.sms_code = codes[i]

    if not cfg.accounts:
        logger.error(
            "未配置账号。青龙请设 FANGHUA_ACCOUNTS 或 FANGHUA_PHONE+FANGHUA_PASSWORD；"
            "本地可复制 config.example.yaml 为 config.yaml"
        )
        return 1

    cache = load_token_cache()
    if args.send_code:
        return send_login_codes(cfg, cache)
    if args.sms_login:
        return sms_login_interactive(cfg, cache)
    logger.info("Token 缓存: %s", resolve_token_cache_path())
    if cfg.bark_url or cfg.bark_key:
        logger.info("通知: Bark 已配置")
    else:
        logger.info("通知: 未配置 BARK_URL/BARK_KEY")
    logger.info("加载 %s 个账号，单号最长 %.2f 小时", len(cfg.accounts), cfg.max_run_hours)

    if args.login_only:
        ok = 0
        for acc in cfg.accounts:
            device_id, jpush_id = resolve_account_ids(acc, cache)
            save_token_cache(cache)
            client = FanghuaClient(device_id=device_id, timeout=cfg.timeout)
            acc.jpush_id = jpush_id
            if ensure_login(acc, client, cache):
                info = client.get_user_info()
                user = info.get("user") or {}
                logger.info(
                    "[%s] OK userId=%s integral=%s device=%s… token=%s…",
                    acc.name,
                    user.get("userId"),
                    user.get("integral"),
                    device_id[:8],
                    (client.app_token or "")[:20],
                )
                ok += 1
        return 0 if ok == len(cfg.accounts) else 2

    threads: list[threading.Thread] = []
    for idx, acc in enumerate(cfg.accounts, 1):
        rng = random.Random(int(time.time() * 1000) + idx)
        delay = rng.uniform(START_DELAY_MIN, START_DELAY_MAX)
        logger.info("[%s] %.1fs 后启动", acc.name, delay)
        time.sleep(delay)
        t = threading.Thread(target=run_account, args=(acc, cfg, cache, rng), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    if summary_reports:
        full = "芳华未来挂机完成\n\n" + "\n\n".join(summary_reports)
        send_bark(cfg, "芳华未来挂机", full)
        print("\n" + full)
    logger.info("全部结束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
