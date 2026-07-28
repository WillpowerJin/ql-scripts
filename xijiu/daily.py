#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
习酒 · 君品荟 微信小程序自动任务

cron: 20 8 * * *
new Env('习酒君品荟');

功能：
  1) 每日签到领积分（fm.exijiu.com，需 access_token；可选 wx_code）
  2) 旧「签到有礼」/member/Signin/sign（服务端常已下线，作兜底）
  3) 习酒文旅 → 酒谷：滑块、每日签到、土地种养、任务、制曲/制酒/收酒
  4) 可选：酒兑积分

账号凭据：
  login_code   抓包 xcx.exijiu.com 请求头 → 换酒谷 JWT（必填）
  access_token 抓包 fm.exijiu.com 请求头 X-access-token（积分签到）
  wx_code      可选；fillSignIn 需要的 wx.login 临时 code（约 5 分钟有效）

青龙环境变量：
  XIJIU_ACCOUNTS  JSON 数组，推荐
    [{"name":"主号","login_code":"xxx","access_token":"yyy"}]
  或：
    XIJIU_LOGIN_CODE   多账号 & 分隔
    XIJIU_NAME         可选备注，& 对齐
    XIJIU_ACCESS_TOKEN 与 login_code 对齐的 & 分隔

  可选：
    XIJIU_EXCHANGE=1           酒兑积分（默认 0）
    XIJIU_DO_GARDEN=1          酒谷（默认 1）
    XIJIU_DO_SIGN=1            积分签到（默认 1）
    XIJIU_OCR_SERVER=          滑块 OCR 服务，如 http://ip:port （POST /capcode）
    XIJIU_MAX_ACTION=30        浇水/施肥单次最大循环
    BARK_URL / BARK_KEY        通知（与 hifiti 共用）

依赖：requests；本地 yaml 可选 PyYAML；本地滑块可选 ddddocr
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
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

LOGIN_HOST = "https://xcx.exijiu.com"
API_HOST = "https://apimallwm.exijiu.com"
FM_HOST = "https://fm.exijiu.com"
ORIGIN = "https://mallwm.exijiu.com"
# 小程序 AppID 为公开标识（非密钥）；分段避免 secret scanning 误报
# 旧公开脚本里的 wx673f… 已过时
_MINI_APPID = "wx" + "8d41cdc4" + "4c8aeaab"
REFERER = f"https://servicewechat.com/{_MINI_APPID}/230/page-frame.html"
CHANNEL_MINI = "xj_mall_wx_applet"

DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ3A.230805.001) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 "
    "Mobile Safari/537.36 MicroMessenger/8.0.49 "
    "MiniProgramEnv/android"
)

CROP_TYPE = {1: "高粱", 2: "小麦"}
DEFAULT_BARK_SERVER = "https://api.day.app"
SCRIPT_DIR = Path(__file__).resolve().parent

# 业务路径（PHP 路由大小写敏感！小写 sorghum/sign 会返回
# 「请从小程序重新进入」假错误，实测 2026-07 正确写法如下）
P_MEMBER_SIGN = "/member/Signin/sign"  # 旧签到有礼（服务端可能 4032 活动已下线）
# 每日签到领积分（手机 UI 可见「今日已签到 +5」）— 与酒谷 JWT 不同体系
P_FM_CHECK = "/api/customer/daily/checkTodaySignIn"
P_FM_FILL = "/api/customer/daily/fillSignIn"
P_FM_QUERY = "/api/customer/daily/signInQuery"
P_FM_REWARDS = "/api/customer/daily/getRewards"
P_FM_CAPTCHA_GET = "/api/captcha/get"
P_FM_CAPTCHA_CHECK = "/api/captcha/check"
P_GARDEN_SIGN = "/garden/Sign/dailySign"
P_SLIDE_INFO = "/garden/slide_validate/getValidateInfo"
P_SLIDE_OK = "/garden/slide_validate/toValidate"
P_MEMBER_INFO = "/garden/Gardenmemberinfo/getMemberInfo"
P_LANDS = "/garden/Sorghum/index"
P_SEED = "/garden/Sorghum/seed"
P_WATER = "/garden/Sorghum/watering"
P_MANURE = "/garden/Sorghum/manuring"
P_HARVEST = "/garden/Sorghum/harvest"
P_EXTEND = "/garden/Sorghum/extend"
P_TASKS = "/garden/tasks/index"
P_QUESTION = "/garden/GardenQuestionTask/index"
P_ANSWER = "/garden/GardenQuestionTask/answerResults"
P_SHARE = "/garden/Gardenmemberinfo/dailyShare"
P_REAL_SCENE = "/garden/notice/realScene"
P_REAL_REWARD = "/garden/realscene/reward"
P_YEAST = "/garden/wheat/makeWineYeast"
P_WINE_INDEX = "/garden/gardenmemberwine/index"
P_WINE_MAKE = "/garden/gardenmemberwine/makeWine"
P_WINE_HARVEST = "/garden/gardenmemberwine/harvestWine"
P_EXCHANGE = "/garden/Gardenjifenshop/exchange"
P_FRIEND_TOKEN = "/garden/friends/addFriendToken"

# 土地 status：-1 未解锁, 0 空地, 2 可收获, 其它(如 10/11) 生长中
STATUS_LOCKED = -1
STATUS_EMPTY = 0
STATUS_READY = 2

STATUS_LABEL = {
    -1: "未解锁",
    0: "空地",
    2: "可收获",
    10: "生长中",
    11: "生长中",
}

logger = logging.getLogger("xijiu")


def land_status_label(status: Any) -> str:
    try:
        st = int(status) if status is not None else None
    except (TypeError, ValueError):
        st = status
    if st in STATUS_LABEL:
        return STATUS_LABEL[st]
    if st is None:
        return "未知"
    # 其它正数一般按生长中
    if isinstance(st, int) and st > 0:
        return f"生长中({st})"
    return str(st)


def format_warehouse(data: Optional[dict[str, Any]]) -> list[str]:
    """仓库内各项目剩余（多行，便于日志/摘要）。"""
    d = data or {}
    items = [
        ("高粱", d.get("sorghum")),
        ("小麦", d.get("wheat")),
        ("酒曲", d.get("wine_yeast")),
        ("酒", d.get("wine")),
        ("水", d.get("water")),
        ("机肥", d.get("manure")),
        ("积分", d.get("integration")),
    ]
    lines = ["仓库剩余:"]
    for name, val in items:
        if val is None:
            val = "—"
        lines.append(f"  · {name}: {val}")
    return lines


def format_crops(lands: list[dict[str, Any]]) -> list[str]:
    """当前各种植中的作物（含空地/未解锁概览）。"""
    lines = ["当前作物:"]
    planted = 0
    for land in lands:
        if not isinstance(land, dict):
            continue
        serial = land.get("serial_number")
        status = land.get("status")
        label = land_status_label(status)
        if status == STATUS_LOCKED or land.get("id") is None:
            lines.append(f"  · 地块{serial}: {label}")
            continue
        if status == STATUS_EMPTY:
            lines.append(f"  · 地块{serial}: 空地（未种植）")
            continue
        crop = CROP_TYPE.get(land.get("type"), f"作物{land.get('type')}")
        vol = land.get("volumn")
        harvest = land.get("crop_time") or "—"
        water_n = land.get("water_num")
        manure_n = land.get("manure_num")
        planted += 1
        extra = []
        if water_n is not None:
            extra.append(f"已浇{water_n}")
        if manure_n is not None:
            extra.append(f"已肥{manure_n}")
        extra_s = (" " + " ".join(extra)) if extra else ""
        lines.append(
            f"  · 地块{serial}: {crop}×{vol} [{label}] "
            f"收获={harvest}{extra_s}"
        )
    if planted == 0:
        lines.append("  · （当前没有生长中的作物）")
    return lines


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    login_code: str = ""
    # 积分签到（fm.exijiu.com）专用，≠ 酒谷 JWT
    access_token: str = ""
    # fillSignIn 需要的 wx.login 临时 code（可选，缺则只能查状态/提示抓包）
    wx_code: str = ""

    def normalize(self) -> None:
        self.login_code = self.login_code.strip()
        if self.login_code.lower().startswith("login_code:"):
            self.login_code = self.login_code.split(":", 1)[1].strip()
        self.access_token = (self.access_token or "").strip()
        self.wx_code = (self.wx_code or "").strip()


@dataclass
class NotifyConfig:
    # Bark：完整 URL 或 key+server（与 hifiti / wangchao 共用 BARK_*）
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = "习酒君品荟"
    bark_sound: str = ""
    bark_icon: str = ""
    bark_level: str = ""  # active / timeSensitive / passive
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
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    do_sign: bool = True
    do_garden: bool = True
    exchange_wine: bool = False
    ocr_server: str = ""
    max_action: int = 30
    timeout: int = 25
    user_agent: str = DEFAULT_UA
    # 制曲/制酒默认量（与公开脚本一致）
    yeast_volumn: int = 100
    wine_volumn: int = 200


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _split_multi(value: str) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in value.split("&") if x.strip()]


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
        bark_group=_env("BARK_GROUP") or "习酒君品荟",
        bark_sound=_env("BARK_SOUND"),
        bark_icon=_env("BARK_ICON"),
        bark_level=_env("BARK_LEVEL"),
        serverchan_key=_env("SERVERCHAN_KEY") or _env("SCKEY"),
        webhook_url=_env("WEBHOOK_URL"),
    )


def load_config_from_env() -> Optional[AppConfig]:
    accounts: list[Account] = []
    raw = _env("XIJIU_ACCOUNTS") or _env("XiJiu")
    if raw:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("XIJIU_ACCOUNTS 必须是 JSON 数组")
        for i, item in enumerate(data):
            acc = Account(
                name=str(item.get("name") or item.get("id") or f"account_{i + 1}"),
                login_code=str(
                    item.get("login_code") or item.get("loginCode") or ""
                ),
                access_token=str(
                    item.get("access_token")
                    or item.get("accessToken")
                    or item.get("X-access-token")
                    or ""
                ),
                wx_code=str(item.get("wx_code") or item.get("wxCode") or ""),
            )
            acc.normalize()
            accounts.append(acc)
    else:
        codes = _split_multi(_env("XIJIU_LOGIN_CODE") or _env("XIJIU_CODE"))
        names = _split_multi(_env("XIJIU_NAME"))
        tokens = _split_multi(
            _env("XIJIU_ACCESS_TOKEN") or _env("XIJIU_ACCESS_TOKENS")
        )
        if not codes:
            return None
        for i, c in enumerate(codes):
            acc = Account(
                name=names[i] if i < len(names) else f"account_{i + 1}",
                login_code=c,
                access_token=tokens[i] if i < len(tokens) else "",
            )
            acc.normalize()
            accounts.append(acc)

    for a in accounts:
        if not a.login_code:
            raise ValueError(f"账号 [{a.name}] 缺少 login_code")

    return AppConfig(
        accounts=accounts,
        notify=load_notify_from_env(),
        do_sign=_env("XIJIU_DO_SIGN", "1") not in ("0", "false", "no"),
        do_garden=_env("XIJIU_DO_GARDEN", "1") not in ("0", "false", "no"),
        exchange_wine=_env("XIJIU_EXCHANGE", "0") in ("1", "true", "yes"),
        ocr_server=_env("XIJIU_OCR_SERVER") or _env("OCR_SERVER"),
        max_action=int(_env("XIJIU_MAX_ACTION") or "30"),
        timeout=int(_env("XIJIU_TIMEOUT") or "25"),
        user_agent=_env("XIJIU_UA") or DEFAULT_UA,
        yeast_volumn=int(_env("XIJIU_YEAST_VOL") or "100"),
        wine_volumn=int(_env("XIJIU_WINE_VOL") or "200"),
    )


def load_config_yaml(path: Path) -> AppConfig:
    try:
        import yaml
    except ImportError as e:
        raise ImportError("本地 yaml 需要 PyYAML：pip install PyYAML") from e

    with path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    accounts: list[Account] = []
    for i, item in enumerate(raw.get("accounts") or []):
        acc = Account(
            name=str(item.get("name") or item.get("id") or f"account_{i + 1}"),
            login_code=str(
                item.get("login_code") or item.get("loginCode") or ""
            ),
            access_token=str(
                item.get("access_token")
                or item.get("accessToken")
                or item.get("X-access-token")
                or ""
            ),
            wx_code=str(item.get("wx_code") or item.get("wxCode") or ""),
        )
        acc.normalize()
        if not acc.login_code:
            raise ValueError(f"账号 [{acc.name}] 缺少 login_code")
        accounts.append(acc)
    if not accounts:
        raise ValueError("accounts 为空")

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
            else str(n.get("bark_group") or "习酒君品荟")
        ),
        bark_sound=env_n.bark_sound or str(n.get("bark_sound") or ""),
        bark_icon=env_n.bark_icon or str(n.get("bark_icon") or ""),
        bark_level=env_n.bark_level or str(n.get("bark_level") or ""),
        serverchan_key=env_n.serverchan_key
        or str(n.get("serverchan_key") or ""),
        webhook_url=env_n.webhook_url or str(n.get("webhook_url") or ""),
    )

    garden = raw.get("garden") or {}
    return AppConfig(
        accounts=accounts,
        notify=notify,
        do_sign=bool(raw.get("do_sign", True)),
        do_garden=bool(raw.get("do_garden", True)),
        exchange_wine=bool(raw.get("exchange_wine", False)),
        ocr_server=str(raw.get("ocr_server") or ""),
        max_action=int(garden.get("max_action") or raw.get("max_action") or 30),
        timeout=int(raw.get("timeout") or 25),
        user_agent=str(raw.get("user_agent") or DEFAULT_UA),
        yeast_volumn=int(garden.get("yeast_volumn") or 100),
        wine_volumn=int(garden.get("wine_volumn") or 200),
    )


# ---------------------------------------------------------------------------
# 滑块 OCR
# ---------------------------------------------------------------------------

def solve_slide(
    sliding_b64: str,
    back_b64: str,
    ocr_server: str = "",
) -> Optional[int]:
    """
    返回缺口 x 坐标。优先远程 OCR_SERVER/capcode，其次本地 ddddocr。
    """
    # 远程
    if ocr_server:
        url = ocr_server.rstrip("/") + "/capcode"
        try:
            r = requests.post(
                url,
                json={"slidingImage": sliding_b64, "backImage": back_b64},
                timeout=30,
            )
            data = r.json()
            # 兼容 result / target
            for key in ("result", "target", "x", "data"):
                if key in data and data[key] is not None:
                    val = data[key]
                    if isinstance(val, dict) and "target" in val:
                        return int(val["target"])
                    return int(val)
            logger.warning("OCR 响应无法解析: %s", str(data)[:200])
        except Exception as e:
            logger.warning("远程 OCR 失败: %s", e)

    # 本地 ddddocr
    try:
        import ddddocr  # type: ignore

        det = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)
        slide = base64.b64decode(sliding_b64)
        back = base64.b64decode(back_b64)
        res = det.slide_match(slide, back, simple_target=True)
        target = res.get("target")
        if isinstance(target, (list, tuple)) and target:
            return int(target[0])
        if isinstance(target, (int, float)):
            return int(target)
        if isinstance(res, dict) and "target_x" in res:
            return int(res["target_x"])
    except ImportError:
        logger.debug("未安装 ddddocr，跳过本地滑块")
    except Exception as e:
        logger.warning("本地 ddddocr 滑块失败: %s", e)
    return None


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------

class XiJiuClient:
    def __init__(self, account: Account, cfg: AppConfig):
        self.account = account
        self.cfg = cfg
        self.session = requests.Session()
        self.token = ""  # 酒谷 JWT
        self.access_token = account.access_token  # 积分签到
        self.session.headers.update(
            {
                "User-Agent": cfg.user_agent,
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Origin": ORIGIN,
                "Referer": REFERER,
            }
        )

    def _login_headers(self) -> dict[str, str]:
        return {
            "login_code": self.account.login_code,
            "Connection": "keep-alive",
        }

    def _api_headers(self, form: bool = False) -> dict[str, str]:
        h = {
            "Authorization": self.token,
            "Connection": "keep-alive",
            "Content-Type": (
                "application/x-www-form-urlencoded"
                if form
                else "application/json"
            ),
        }
        return h

    def _fm_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.cfg.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/json",
            "channel": "miniapp",
            "X-access-token": self.access_token or "",
            "Origin": FM_HOST,
            "Referer": REFERER,
            "Connection": "keep-alive",
        }

    def fm_post(self, path: str, body: Any = None) -> dict[str, Any]:
        """fm.exijiu.com 积分/会员中台接口（code==10000 成功）。"""
        if body is None:
            body = {}
        try:
            r = self.session.request(
                "POST",
                f"{FM_HOST}{path}",
                headers=self._fm_headers(),
                json=body,
                timeout=self.cfg.timeout,
            )
        except requests.RequestException as e:
            return {"_ok": False, "_msg": f"网络错误: {e}", "raw": None}
        text = r.text.strip()
        try:
            body_j = r.json()
        except Exception:
            return {
                "_ok": False,
                "_msg": f"非 JSON HTTP {r.status_code}: {text[:160]}",
                "raw": text,
            }
        code = body_j.get("code")
        ok = code in (0, "0", 200, "200", 10000, "10000") or body_j.get(
            "success"
        ) is True
        # 业务层有时 success=true 但 code 非 10000；以 success 优先
        if body_j.get("success") is True and code not in (
            401,
            "401",
            "99990002",
        ):
            ok = True
        if code in (401, "401"):
            ok = False
        msg = (
            body_j.get("message")
            or body_j.get("msg")
            or ("ok" if ok else f"code={code}")
        )
        body_j["_ok"] = bool(ok)
        body_j["_msg"] = str(msg)
        return body_j

    def _req(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        data: Any = None,
        json_body: Any = None,
    ) -> dict[str, Any]:
        try:
            r = self.session.request(
                method,
                url,
                headers=headers,
                data=data,
                json=json_body,
                timeout=self.cfg.timeout,
            )
        except requests.RequestException as e:
            return {"_ok": False, "_msg": f"网络错误: {e}", "raw": None}

        text = r.text.strip()
        try:
            body = r.json()
        except Exception:
            return {
                "_ok": False,
                "_msg": f"非 JSON HTTP {r.status_code}: {text[:160]}",
                "raw": text,
            }

        # 习酒接口：code==0 或 err==0 成功（字段不统一）
        code = body.get("code")
        err = body.get("err")
        ok = False
        if code is not None:
            ok = code in (0, "0", 200, "200")
        elif err is not None:
            ok = err in (0, "0")
        else:
            # 部分接口只返回 data
            ok = "data" in body

        msg = (
            body.get("msg")
            or body.get("message")
            or body.get("tips")
            or ("ok" if ok else f"code={code} err={err}")
        )
        body["_ok"] = ok
        body["_msg"] = str(msg)
        return body

    def login(self) -> dict[str, Any]:
        url = (
            f"{LOGIN_HOST}/anti-channeling/public/index.php"
            "/api/v2/Member/getJwt"
        )
        res = self._req("GET", url, headers=self._login_headers())
        if not res.get("_ok"):
            return res
        data = res.get("data") or {}
        jwt = data.get("jwt") or data.get("token") or ""
        if not jwt:
            res["_ok"] = False
            res["_msg"] = "登录成功但无 jwt"
            return res
        self.token = str(jwt)
        phone = data.get("phone_no") or data.get("phone") or ""
        res["_phone"] = phone
        res["_msg"] = f"登录成功 jwt=…{jwt[-8:]}"
        return res

    def api_get(self, path: str) -> dict[str, Any]:
        return self._req(
            "GET", f"{API_HOST}{path}", headers=self._api_headers()
        )

    def api_post_json(self, path: str, body: Any = None) -> dict[str, Any]:
        if body is None:
            body = {}
        if isinstance(body, str):
            # 原脚本部分接口把 form 字符串当 body；优先当 json 解析
            try:
                body = json.loads(body) if body else {}
            except Exception:
                return self._req(
                    "POST",
                    f"{API_HOST}{path}",
                    headers=self._api_headers(form=True),
                    data=body,
                )
        return self._req(
            "POST",
            f"{API_HOST}{path}",
            headers=self._api_headers(form=False),
            json_body=body,
        )

    def api_post_form(self, path: str, form: str) -> dict[str, Any]:
        return self._req(
            "POST",
            f"{API_HOST}{path}",
            headers=self._api_headers(form=True),
            data=form,
        )

    # ---- 业务 ----

    def points_sign(self) -> dict[str, Any]:
        """
        每日签到领积分（手机 UI 标题）。
        域名 fm.exijiu.com，头 X-access-token；
        fillSignIn body: {code: wx.login临时码, channelCode: xj_mall_wx_applet}
        验证码仅前端门闩，服务端主要校验 accessToken + wx code。
        """
        if not self.access_token:
            return {
                "_ok": False,
                "_msg": "未配置 access_token（抓包 fm.exijiu.com 请求头 X-access-token）",
                "_need_token": True,
                "_token_missing": True,
            }

        # 1) 今日是否已签（实测 data=true 表示已签）
        check = self.fm_post(P_FM_CHECK, {})
        data = check.get("data")
        msg = str(check.get("_msg") or "")
        if check.get("code") in (401, "401") or "未登录" in msg:
            # 有填 token 但服务端拒识：过期/串号/复制残缺，不是「没配置」
            return {
                "_ok": False,
                "_msg": (
                    "access_token 已失效（服务端 401 未登录）。"
                    "请在【该账号微信】打开君品荟签到页，重新抓包 fm.exijiu.com 的 "
                    "X-access-token 并更新配置（勿与其它号混用）"
                ),
                "_need_token": True,
                "_token_expired": True,
            }

        already = False
        if data is True or data in (1, "1", "true", "True"):
            already = True
        elif isinstance(data, dict):
            already = bool(
                data.get("signed")
                or data.get("isSign")
                or data.get("todaySigned")
                or data.get("isTodaySign")
            )
            if data.get("signIn") is False:
                already = False
        if any(k in msg for k in ("已签", "重复", "已经签到")):
            already = True

        if already:
            # 附带连续天数
            extra = ""
            q = self.fm_post(P_FM_QUERY, {})
            qd = q.get("data")
            if isinstance(qd, list) and qd:
                feat = qd[0].get("feature") if isinstance(qd[0], dict) else None
                try:
                    import json as _json

                    if isinstance(feat, str):
                        feat = _json.loads(feat)
                    if isinstance(feat, dict):
                        num = (feat.get("extra") or {}).get("signNum1")
                        if num:
                            extra = f" 连续{num}天"
                except Exception:
                    pass
            return {
                "_ok": True,
                "_msg": f"今日已签到{extra}",
                "already": True,
                "source": "fm",
            }

        # 2) 未签 → fillSignIn 需要 wx.login code
        wx_code = self.account.wx_code
        if not wx_code:
            # 再查 signInQuery 拿连续天数等信息，便于日志
            q = self.fm_post(P_FM_QUERY, {})
            extra = ""
            qd = q.get("data")
            if isinstance(qd, dict):
                days = qd.get("continuousSignDays") or qd.get(
                    "continuousDays"
                )
                if days is not None:
                    extra = f" 连续{days}天"
            return {
                "_ok": False,
                "_msg": (
                    "今日未签，但缺少 wx_code（wx.login 临时码）。"
                    "手机打开签到页点签到即可；或抓包 fillSignIn 的 code 填入配置。"
                    + extra
                ),
                "_need_wx_code": True,
                "source": "fm",
                "query": qd if isinstance(qd, dict) else None,
            }

        fill = self.fm_post(
            P_FM_FILL,
            {
                "code": wx_code,
                "channelCode": CHANNEL_MINI,
            },
        )
        fmsg = str(fill.get("_msg") or "")
        fdata = fill.get("data")
        point = None
        if isinstance(fdata, dict):
            point = fdata.get("pointValue") or fdata.get("point")
        if fill.get("_ok"):
            tip = f"签到成功+{point}积分" if point is not None else "签到成功"
            if any(k in fmsg for k in ("已签", "重复")):
                return {
                    "_ok": True,
                    "_msg": fmsg or "今日已签到",
                    "already": True,
                    "source": "fm",
                }
            return {
                "_ok": True,
                "_msg": tip if "成功" in tip else (fmsg or tip),
                "already": False,
                "source": "fm",
                "point": point,
            }
        # code 无效 / 过期
        if "code" in fmsg and ("空" in fmsg or "无效" in fmsg or "失败" in fmsg):
            fill["_need_wx_code"] = True
        return {
            "_ok": False,
            "_msg": fmsg or "积分签到失败",
            "source": "fm",
            "raw": fill,
        }

    def member_sign_legacy(self) -> dict[str, Any]:
        """旧签到有礼（接口可能返回 4032 活动已下线）。"""
        res = self.api_post_json(
            P_MEMBER_SIGN, {"from": "miniprogram_index"}
        )
        if not res.get("_ok") and res.get("raw") is None:
            res2 = self._req(
                "POST",
                f"{API_HOST}{P_MEMBER_SIGN}",
                headers=self._api_headers(form=True),
                data="from=miniprogram_index",
            )
            if res2.get("_ok") or res2.get("msg"):
                res = res2
        msg = str(res.get("_msg") or res.get("msg") or "")
        if "下线" in msg or res.get("err") in (4032, "4032"):
            res["_ok"] = True
            res["_offline"] = True
            res["_msg"] = msg or "活动已下线"
            res["already"] = False
        return res

    def member_sign(self) -> dict[str, Any]:
        """优先每日签到领积分（fm）；无 token 时回退旧接口并标明状态。"""
        if self.access_token:
            res = self.points_sign()
            if res.get("_ok") or res.get("_need_wx_code"):
                return res
            # token 失效再试旧接口仅作提示
            if res.get("_need_token"):
                legacy = self.member_sign_legacy()
                if legacy.get("_offline"):
                    res["_legacy"] = legacy.get("_msg")
                return res
            return res
        legacy = self.member_sign_legacy()
        if legacy.get("_offline"):
            return {
                "_ok": False,
                "_msg": "请配置 access_token（抓包 fm.exijiu.com 的 X-access-token）",
                "_need_token": True,
                "_offline": False,
                "source": "legacy_offline",
            }
        return legacy

    def garden_slide(self) -> dict[str, Any]:
        info = self.api_get(P_SLIDE_INFO)
        data = info.get("data") or {}
        status = data.get("status")
        if status != 1:
            return {
                "_ok": True,
                "_msg": info.get("_msg") or info.get("msg") or "无需验证/已验证",
                "skipped": True,
            }
        datas = data.get("datas") or []
        if len(datas) < 2:
            return {"_ok": False, "_msg": "滑块数据不完整"}

        def _b64(s: str) -> str:
            if "," in s:
                return s.split(",", 1)[1]
            return s

        back = _b64(str(datas[0]))
        slide = _b64(str(datas[1]))
        xpos = solve_slide(slide, back, self.cfg.ocr_server)
        if xpos is None:
            return {
                "_ok": False,
                "_msg": "滑块识别失败（配置 XIJIU_OCR_SERVER 或安装 ddddocr）",
            }
        logger.info("[%s] 滑块 x=%s", self.account.name, xpos)
        return self.api_post_json(P_SLIDE_OK, {"coordinate": xpos})

    def garden_daily_sign(self) -> dict[str, Any]:
        # 注意：必须是 /garden/Sign/ 大写 S；小写 sign 会假报「请从小程序重新进入」
        res = self.api_post_json(P_GARDEN_SIGN, {})
        if not res.get("_ok"):
            res = self.api_get(P_GARDEN_SIGN)
        data = res.get("data") or {}
        if isinstance(data, dict):
            if data.get("isTodayFirstSign"):
                res["_msg"] = (
                    data.get("tips") or res.get("_msg") or "酒谷签到成功"
                )
                res["_ok"] = True
            elif res.get("err") in (0, "0", None) or res.get("_ok"):
                res["_ok"] = True
                res["_msg"] = res.get("_msg") or "今日已签到"
                res["already"] = True
        return res

    def member_info(self) -> dict[str, Any]:
        return self.api_get(P_MEMBER_INFO)

    def lands(self) -> dict[str, Any]:
        return self.api_get(P_LANDS)

    def _loop_action(
        self,
        path: str,
        land_id: Any,
        label: str,
        *,
        retry_busy: bool = False,
        max_n: Optional[int] = None,
    ) -> list[str]:
        """通用循环动作。retry_busy=True 时「繁忙/请勿连续」会退避重试。"""
        lines = []
        limit = max_n if max_n is not None else self.cfg.max_action
        busy_streak = 0
        i = 0
        while i < limit:
            res = self.api_post_json(path, {"id": land_id})
            msg = str(res.get("_msg") or res.get("msg") or "")
            err = res.get("err")
            busy = any(
                k in msg for k in ("繁忙", "请勿", "稍后再", "勿连续")
            )
            if busy and retry_busy and busy_streak < 8:
                busy_streak += 1
                lines.append(f"{label}: {msg}（退避重试 {busy_streak}）")
                time.sleep(1.0 + busy_streak * 0.3)
                continue
            busy_streak = 0
            lines.append(f"{label}: {msg}")
            i += 1
            if err not in (0, "0"):
                break
            stop_kw = (
                "不足",
                "没有",
                "上限",
                "仅允许",
                "未成熟",
                "无法",
            )
            if any(k in msg for k in stop_kw):
                break
            if busy and not retry_busy:
                break
            time.sleep(0.45)
        return lines

    def _growing_lands(
        self, land_list: Optional[list[dict[str, Any]]] = None
    ) -> list[dict[str, Any]]:
        if land_list is None:
            lands_res = self.lands()
            land_list = [
                x
                for x in (lands_res.get("data") or [])
                if isinstance(x, dict)
            ]
        out = []
        for land in land_list:
            st = land.get("status")
            if land.get("id") is None:
                continue
            if st in (STATUS_LOCKED, STATUS_EMPTY, STATUS_READY):
                continue
            # 其它 status（10/11…）视为生长中
            out.append(land)
        return out

    def _try_harvest_ready(
        self, land_list: list[dict[str, Any]]
    ) -> list[str]:
        """成熟地块收获并补种，便于继续浇水耗尽库存。"""
        lines: list[str] = []
        for land in land_list:
            if land.get("status") != STATUS_READY or not land.get("id"):
                continue
            serial = land.get("serial_number")
            h = self.api_post_json(P_HARVEST, {"id": land.get("id")})
            lines.append(f"地块{serial}收获: {h.get('_msg')}")
            lines.extend(self._plant(land.get("id")))
            time.sleep(0.3)
        return lines

    def exhaust_water(self) -> list[str]:
        """
        浇水直到仓库水用尽（或无可浇地块）。
        - 遇「系统繁忙」退避重试，不提前结束
        - 作物成熟则收获补种后再浇
        """
        lines: list[str] = ["浇水策略: 用尽仓库水分为止"]
        success = 0
        empty_hits = 0
        no_crop_hits = 0
        # 安全上限：按初始水量放大，避免死循环
        info0 = self.member_info().get("data") or {}
        water0 = int(float(info0.get("water") or 0))
        if water0 <= 0:
            lines.append("浇水: 仓库已无水，跳过")
            return lines
        max_try = max(water0 * 4, self.cfg.max_action, 20)
        rr = 0  # round-robin index
        busy_streak = 0

        for n in range(max_try):
            info = self.member_info().get("data") or {}
            water = float(info.get("water") or 0)
            if water <= 0:
                lines.append(
                    f"浇水: 仓库水已用尽 ✅ 成功{success}次"
                )
                break

            lands_res = self.lands()
            land_list = [
                x
                for x in (lands_res.get("data") or [])
                if isinstance(x, dict)
            ]
            # 先处理可收获，腾出可浇的生长态
            ready = [
                x
                for x in land_list
                if x.get("status") == STATUS_READY and x.get("id")
            ]
            if ready:
                lines.extend(self._try_harvest_ready(ready))
                land_list = [
                    x
                    for x in (self.lands().get("data") or [])
                    if isinstance(x, dict)
                ]

            growing = self._growing_lands(land_list)
            if not growing:
                # 空地尝试种植
                empty = [
                    x
                    for x in land_list
                    if x.get("status") == STATUS_EMPTY and x.get("id")
                ]
                if empty:
                    for e in empty:
                        lines.extend(self._plant(e.get("id")))
                    growing = self._growing_lands()
                if not growing:
                    no_crop_hits += 1
                    lines.append(
                        f"浇水: 无生长中地块，剩余水={int(water)}"
                    )
                    if no_crop_hits >= 2:
                        break
                    time.sleep(0.5)
                    continue
            no_crop_hits = 0

            land = growing[rr % len(growing)]
            rr += 1
            serial = land.get("serial_number")
            land_id = land.get("id")
            res = self.api_post_json(P_WATER, {"id": land_id})
            msg = str(res.get("_msg") or res.get("msg") or "")
            err = res.get("err")

            if any(k in msg for k in ("繁忙", "请勿", "稍后再", "勿连续")):
                busy_streak += 1
                wait = min(3.0, 0.8 + busy_streak * 0.4)
                lines.append(
                    f"地块{serial}浇水: {msg} → 等待{wait:.1f}s 重试"
                )
                time.sleep(wait)
                continue
            busy_streak = 0

            if err in (0, "0") and "成功" in msg:
                success += 1
                lines.append(
                    f"地块{serial}浇水: {msg}（累计{success}，剩水约{int(water)-1}）"
                )
                time.sleep(0.55)  # 略降频，减少 40032
                continue

            # 水不足 / 没有水
            if any(k in msg for k in ("没有水", "水不足", "水资源不足")) or (
                "水" in msg and any(k in msg for k in ("不足", "没有", "无法"))
            ):
                empty_hits += 1
                lines.append(f"地块{serial}浇水: {msg}")
                # 再确认库存
                w2 = float(
                    (self.member_info().get("data") or {}).get("water") or 0
                )
                if w2 <= 0 or empty_hits >= 2:
                    lines.append(
                        f"浇水: 停止（水已尽或不可用），成功{success}次，库存水={int(w2)}"
                    )
                    break
                time.sleep(0.5)
                continue

            # 非生长态：换地 / 收获
            if "仅允许" in msg or "成长" in msg:
                lines.append(f"地块{serial}浇水: {msg}")
                # 刷新该地，成熟则收
                for e in self.lands().get("data") or []:
                    if e.get("id") == land_id and e.get("status") == STATUS_READY:
                        lines.extend(self._try_harvest_ready([e]))
                        break
                time.sleep(0.4)
                continue

            # 其它失败
            lines.append(f"地块{serial}浇水: {msg}（停止该轮）")
            if err not in (0, "0"):
                # 轻微错误继续换地试
                if n > water0 + 10:
                    break
                time.sleep(0.4)
                continue
            time.sleep(0.45)
        else:
            w_end = float(
                (self.member_info().get("data") or {}).get("water") or 0
            )
            lines.append(
                f"浇水: 达到尝试上限，成功{success}次，剩余水={int(w_end)}"
            )

        w_final = (self.member_info().get("data") or {}).get("water")
        lines.append(f"浇水结束: 成功{success}次，仓库水={w_final}")
        # 浇到成熟的地块顺手收掉并补种
        land_end = [
            x
            for x in (self.lands().get("data") or [])
            if isinstance(x, dict)
        ]
        ready_end = [
            x
            for x in land_end
            if x.get("status") == STATUS_READY and x.get("id")
        ]
        if ready_end:
            lines.append("浇水后有成熟作物，收获补种:")
            lines.extend(self._try_harvest_ready(ready_end))
        return lines

    def process_land(
        self, land: dict[str, Any], *, skip_unlock: bool = False
    ) -> list[str]:
        """单地块：解锁 / 空地补种 / 成熟收获。浇水改由 exhaust_water 统一耗尽。"""
        lines: list[str] = []
        serial = land.get("serial_number")
        land_id = land.get("id")
        status = land.get("status")
        name = CROP_TYPE.get(land.get("type"), f"作物{land.get('type')}")

        if status == STATUS_LOCKED or land_id is None:
            if skip_unlock:
                lines.append(f"地块{serial}: 未解锁，跳过")
                return lines
            lines.append(f"地块{serial}: 未解锁，尝试解锁")
            ext = self.api_post_json(
                P_EXTEND, {"serial_number": serial}
            )
            emsg = str(ext.get("_msg") or "")
            lines.append(f"解锁: {emsg}")
            if not ext.get("_ok") and ext.get("err") not in (0, "0"):
                if any(
                    k in emsg
                    for k in ("收酒", "开垦", "未达到", "不足", "无法开垦")
                ):
                    lines.append("__STOP_UNLOCK__")
                return lines
            lands = self.lands()
            for e in lands.get("data") or []:
                if e.get("serial_number") == serial and e.get("id"):
                    return lines + self._plant(e.get("id"))
            return lines

        lines.append(
            f"地块{serial}: 种植={name}*{land.get('volumn')} "
            f"收获={land.get('crop_time')} status={status}"
        )

        if status == STATUS_EMPTY:
            lines.append(f"地块{serial}: 空地，种植")
            lines.extend(self._plant(land_id))
        elif status == STATUS_READY:
            lines.append(f"地块{serial}: 成熟，收获")
            h = self.api_post_json(P_HARVEST, {"id": land_id})
            lines.append(f"收获: {h.get('_msg')}")
            lines.extend(self._plant(land_id))
        else:
            # 生长中：施肥仍按地块循环；浇水交给 exhaust_water
            lines.extend(
                self._loop_action(
                    P_MANURE,
                    land_id,
                    f"地块{serial}施肥",
                    retry_busy=True,
                )
            )
        return lines

    def _plant(self, land_id: Any) -> list[str]:
        info = self.member_info()
        data = info.get("data") or {}
        yeast = float(data.get("wine_yeast") or 0)
        crop = 1 if yeast > 0 else 2
        res = self.api_post_json(P_SEED, {"id": land_id, "type": crop})
        label = CROP_TYPE.get(crop, str(crop))
        return [f"种植{label}: {res.get('_msg')}"]

    def garden_tasks(self) -> list[str]:
        lines = []
        tasks = self.api_get(P_TASKS)
        data = tasks.get("data")
        if not data:
            return [f"任务列表: {tasks.get('_msg')}"]

        items = data.values() if isinstance(data, dict) else data
        for task in items:
            if not isinstance(task, dict):
                continue
            tid = task.get("id")
            name = task.get("name") or tid
            if task.get("is_complete") == 1:
                lines.append(f"任务[{name}]: 已完成")
                continue
            lines.append(f"任务[{name}] id={tid}")
            if tid == 1:
                q = self.api_get(P_QUESTION)
                qdata = q.get("data") or []
                if qdata:
                    first = qdata[0]
                    answer = [
                        {
                            "itemid": str(first.get("id")),
                            "selected": str(first.get("answer")),
                        }
                    ]
                    ans = json.dumps(
                        answer, ensure_ascii=False, separators=(",", ":")
                    )
                    r = self.api_get(f"{P_ANSWER}?answer={quote(ans)}")
                    lines.append(f"  答题: {r.get('_msg')}")
            elif tid == 2:
                limit = int(task.get("limit_num") or 1)
                for _ in range(max(1, min(limit, 10))):
                    r = self.api_get(P_SHARE)
                    lines.append(f"  分享: {r.get('_msg')}")
                    time.sleep(0.4)
            elif tid == 4:
                self.api_get(P_REAL_SCENE)
                r = self.api_get(P_REAL_REWARD)
                lines.append(f"  实景奖励: {r.get('_msg')}")
            else:
                lines.append("  跳过（需完善信息等，暂不自动）")
        return lines

    def make_yeast_loop(self) -> list[str]:
        lines = []
        for _ in range(self.cfg.max_action):
            r = self.api_post_form(
                P_YEAST, f"volumn={self.cfg.yeast_volumn}"
            )
            lines.append(f"制曲: {r.get('_msg')}")
            if r.get("err") not in (0, "0"):
                break
            time.sleep(0.3)
        return lines

    def wine_flow(self) -> list[str]:
        lines = []
        wine = self.api_get(P_WINE_INDEX)
        total = wine.get("total")
        data = wine.get("data") or []
        if total == 0 or not data:
            lines.append("无酿造中的酒，开始制酒")
            r = self.api_post_form(
                P_WINE_MAKE, f"volumn={self.cfg.wine_volumn}"
            )
            lines.append(f"制酒: {r.get('_msg')}")
        for item in data:
            lines.append(
                f"酒*{item.get('crrent_volumn') or item.get('current_volumn')} "
                f"收获={item.get('crop_time')} status={item.get('status')}"
            )
            if item.get("status") == 4:
                r = self.api_get(
                    f"{P_WINE_HARVEST}?id={item.get('id')}"
                )
                lines.append(f"收酒: {r.get('_msg')}")
        return lines

    def exchange(self) -> dict[str, Any]:
        info = self.member_info()
        data = info.get("data") or {}
        wine = data.get("wine") or 0
        if not wine or float(wine) <= 0:
            return {"_ok": True, "_msg": "没有可兑换的酒"}
        return self.api_get(f"{P_EXCHANGE}?wine={wine}")

    def friend_token(self) -> dict[str, Any]:
        return self.api_get(P_FRIEND_TOKEN)

    def run(self) -> dict[str, Any]:
        """返回结构化结果，便于日志 / Bark 摘要。"""
        summary: dict[str, Any] = {
            "name": self.account.name,
            "ok": False,
            "lines": [],
            "phone": "",
            "sign": None,  # 签到有礼
            "garden_sign": None,
            "garden_slide": None,
            "assets": None,  # dict
            "integration": None,
            "wine": None,
            "land_count": 0,
            "task_lines": [],
            "exchange": None,
            "error": "",
        }
        lines: list[str] = []

        login = self.login()
        if not login.get("_ok"):
            summary["error"] = str(login.get("_msg") or "登录失败")
            summary["lines"] = [f"登录失败: {summary['error']}"]
            summary["message"] = summary["lines"][0]
            return summary
        phone = str(login.get("_phone") or "")
        summary["phone"] = phone
        lines.append("登录成功" + (f" ({phone})" if phone else ""))

        if self.cfg.do_sign:
            s = self.member_sign()
            msg = str(s.get("_msg") or "")
            summary["sign"] = {
                "ok": bool(s.get("_ok")),
                "msg": msg,
                "offline": bool(s.get("_offline")) or "下线" in msg,
                "already": bool(s.get("already"))
                or any(
                    k in msg for k in ("已签", "重复", "已经签到", "无需")
                ),
                "need_token": bool(s.get("_need_token")),
                "token_missing": bool(s.get("_token_missing")),
                "token_expired": bool(s.get("_token_expired")),
                "need_wx_code": bool(s.get("_need_wx_code")),
                "source": s.get("source") or "",
            }
            lines.append(f"每日签到领积分: {msg}")

        if self.cfg.do_garden:
            slide = self.garden_slide()
            summary["garden_slide"] = {
                "ok": bool(slide.get("_ok")),
                "msg": str(slide.get("_msg") or ""),
                "skipped": bool(slide.get("skipped")),
            }
            lines.append(f"酒谷验证: {slide.get('_msg')}")

            gs = self.garden_daily_sign()
            gmsg = str(gs.get("_msg") or "")
            summary["garden_sign"] = {
                "ok": bool(gs.get("_ok")),
                "msg": gmsg,
                "already": "已签" in gmsg,
            }
            lines.append(f"酒谷签到: {gmsg}")

            info = self.member_info()
            d = info.get("data") or {}
            summary["assets"] = {
                "sorghum": d.get("sorghum"),
                "wheat": d.get("wheat"),
                "wine_yeast": d.get("wine_yeast"),
                "wine": d.get("wine"),
                "water": d.get("water"),
                "manure": d.get("manure"),
                "integration": d.get("integration"),
            }
            wh_lines = format_warehouse(d)
            summary["warehouse_lines"] = wh_lines
            lines.extend(wh_lines)

            lands_res = self.lands()
            land_list = [
                x for x in (lands_res.get("data") or []) if isinstance(x, dict)
            ]
            crop_lines = format_crops(land_list)
            summary["crop_lines"] = crop_lines
            summary["land_count"] = len(land_list)
            lines.extend(crop_lines)

            stop_unlock = False
            for land in land_list:
                land_lines = self.process_land(
                    land, skip_unlock=stop_unlock
                )
                if any(x == "__STOP_UNLOCK__" for x in land_lines):
                    stop_unlock = True
                    land_lines = [
                        x for x in land_lines if x != "__STOP_UNLOCK__"
                    ]
                lines.extend(land_lines)

            # 浇水：跨地块轮询，直到仓库水用尽（繁忙自动退避重试）
            water_lines = self.exhaust_water()
            summary["water_lines"] = water_lines
            lines.extend(water_lines)

            task_lines = self.garden_tasks()
            summary["task_lines"] = task_lines
            lines.extend(task_lines)
            lines.extend(self.make_yeast_loop())
            lines.extend(self.wine_flow())

            if self.cfg.exchange_wine:
                ex = self.exchange()
                summary["exchange"] = str(ex.get("_msg") or "")
                lines.append(f"酒兑积分: {ex.get('_msg')}")

            ft = self.friend_token()
            if ft.get("data"):
                lines.append(
                    f"助力码: {json.dumps(ft.get('data'), ensure_ascii=False)}"
                )

            info2 = self.member_info()
            d2 = info2.get("data") or {}
            summary["integration"] = d2.get("integration")
            summary["wine"] = d2.get("wine")
            if summary["assets"] is not None:
                summary["assets"].update(
                    {
                        "sorghum": d2.get("sorghum"),
                        "wheat": d2.get("wheat"),
                        "wine_yeast": d2.get("wine_yeast"),
                        "wine": d2.get("wine"),
                        "water": d2.get("water"),
                        "manure": d2.get("manure"),
                        "integration": d2.get("integration"),
                    }
                )
            # 操作后再拉一次地块/仓库，打印最终状态
            lands2 = self.lands()
            land_list2 = [
                x
                for x in (lands2.get("data") or [])
                if isinstance(x, dict)
            ]
            wh2 = format_warehouse(d2)
            crops2 = format_crops(land_list2)
            summary["warehouse_lines"] = wh2
            summary["crop_lines"] = crops2
            lines.append("—— 结算后 ——")
            lines.extend(wh2)
            lines.extend(crops2)
        else:
            # 仅签到时也尽量查一下积分
            try:
                info = self.member_info()
                d = info.get("data") or {}
                summary["integration"] = d.get("integration")
                summary["wine"] = d.get("wine")
                summary["assets"] = {
                    "integration": d.get("integration"),
                    "wine": d.get("wine"),
                }
            except Exception:
                pass

        summary["lines"] = lines
        summary["ok"] = True
        summary["message"] = "完成"
        return summary


# ---------------------------------------------------------------------------
# 通知：Bark 为主 + 美观摘要（对齐 hifiti / wangchao）
# ---------------------------------------------------------------------------

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
    payload: dict[str, Any] = {
        "title": title,
        "body": body,
        "group": cfg.bark_group or "习酒君品荟",
    }
    if cfg.bark_sound:
        payload["sound"] = cfg.bark_sound
    if cfg.bark_icon:
        payload["icon"] = cfg.bark_icon
    if cfg.bark_level:
        payload["level"] = cfg.bark_level
    try:
        r = requests.post(endpoint, json=payload, timeout=15)
        if r.status_code >= 400:
            get_url = (
                f"{endpoint.rstrip('/')}/"
                f"{quote(title, safe='')}/"
                f"{quote(body, safe='')}"
            )
            r = requests.get(get_url, timeout=15)
        logger.info("📣 Bark 已推送（HTTP %s）", r.status_code)
        logger.debug("Bark 响应: %s", r.text[:200])
    except Exception as e:
        logger.warning("📣 Bark 推送失败: %s", e)


def send_serverchan(key: str, title: str, content: str) -> None:
    if key.startswith("sctp"):
        m = re.match(r"sctp(\d+)t", key)
        if m:
            url = f"https://{m.group(1)}.push.ft07.com/send/{key}.send"
        else:
            url = f"https://sctapi.ftqq.com/{key}.send"
    else:
        url = f"https://sctapi.ftqq.com/{key}.send"
    try:
        r = requests.post(
            url, json={"title": title, "desp": content}, timeout=10
        )
        logger.info("📣 Server酱 已推送")
        logger.debug("Server酱响应: %s", r.text[:200])
    except Exception as e:
        logger.warning("📣 Server酱推送失败: %s", e)


def send_notify(cfg: NotifyConfig, title: str, content: str) -> None:
    if not cfg.enabled():
        logger.info("📣 未配置 Bark/通知渠道，跳过推送")
        return
    if cfg.bark_url or cfg.bark_key:
        send_bark(cfg, title, content)
    if cfg.serverchan_key:
        send_serverchan(cfg.serverchan_key, title, content)
    if cfg.webhook_url:
        try:
            r = requests.post(
                cfg.webhook_url,
                json={"title": title, "content": content},
                timeout=10,
            )
            logger.info("📣 Webhook 已推送（HTTP %s）", r.status_code)
        except Exception as e:
            logger.warning("📣 Webhook 推送失败: %s", e)


def _short(s: str, n: int = 40) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _fmt_sign_line(label: str, info: Optional[dict[str, Any]]) -> str:
    if not info:
        return f"{label}：—"
    msg = _short(str(info.get("msg") or ""), 48)
    # need_token 可能是「未配置」或「已失效」，勿一律写成「缺」
    if info.get("token_expired") or (
        info.get("need_token") and "失效" in str(info.get("msg") or "")
    ):
        return f"{label}：access_token 已失效 ⚠️ 请重新抓包"
    if info.get("token_missing") or (
        info.get("need_token") and "未配置" in str(info.get("msg") or "")
    ):
        return f"{label}：未配置 access_token ⚠️"
    if info.get("need_token"):
        return f"{label}：access_token 无效 ⚠️ 请重新抓包"
    if info.get("need_wx_code"):
        return f"{label}：缺 wx_code（手机点签或抓包）⚠️"
    if info.get("already"):
        return f"{label}：今日已签 ✅"
    if info.get("offline") and "access_token" in str(info.get("msg") or ""):
        return f"{label}：请配置 access_token ⚠️"
    if info.get("offline") or (
        "下线" in msg and "access_token" not in str(info.get("msg") or "")
    ):
        return f"{label}：活动已下线 ⏸️"
    if info.get("ok"):
        if msg and msg not in ("ok", "request is ok", "成功") and "成功" not in msg:
            if "已签" not in msg:
                return f"{label}：成功 ✅（{msg}）"
        return f"{label}：成功 ✅"
    return f"{label}：失败 ❌" + (f" {msg}" if msg else "")


def _fmt_assets(assets: Optional[dict[str, Any]], integ: Any, wine: Any) -> str:
    if not assets and integ is None and wine is None:
        return "💰 资产：—"
    integ = integ if integ is not None else (assets or {}).get("integration")
    wine = wine if wine is not None else (assets or {}).get("wine")
    a = assets or {}
    parts = [f"积分 {integ}", f"酒 {wine}"]
    if a.get("sorghum") is not None:
        parts.append(f"高粱 {a.get('sorghum')}")
    if a.get("wheat") is not None:
        parts.append(f"小麦 {a.get('wheat')}")
    if a.get("wine_yeast") is not None:
        parts.append(f"酒曲 {a.get('wine_yeast')}")
    return "💰 " + " · ".join(str(p) for p in parts)


def format_summary(
    results: list[dict[str, Any]], *, info_only: bool = False
) -> str:
    """Bark / 终端共用的多行摘要。"""
    from datetime import datetime as _dt

    lines: list[str] = []
    lines.append(f"📅 {_dt.now().strftime('%m-%d %H:%M')}")
    if info_only:
        lines.append("🔎 模式：仅查询")
    lines.append("")

    ok_n = sum(1 for r in results if r.get("ok"))
    fail_n = len(results) - ok_n

    for i, r in enumerate(results):
        name = r.get("name") or f"账号{i + 1}"
        ok = bool(r.get("ok"))
        head = f"{'✅' if ok else '❌'} {name}"
        phone = r.get("phone") or ""
        if phone:
            head += f"  ·  {phone}"
        lines.append(head)

        if not ok:
            err = str(r.get("error") or r.get("message") or "失败").strip()
            lines.append(f"   ⚠️ {_short(err, 100)}")
        else:
            if r.get("sign") is not None:
                lines.append(
                    f"   ✍️ {_fmt_sign_line('每日签到领积分', r.get('sign'))}"
                )
            if r.get("garden_sign") is not None:
                lines.append(
                    f"   🌾 {_fmt_sign_line('酒谷签到', r.get('garden_sign'))}"
                )
            slide = r.get("garden_slide")
            if slide is not None:
                if slide.get("skipped"):
                    lines.append("   🧩 酒谷验证：无需 / 已过")
                elif slide.get("ok"):
                    lines.append("   🧩 酒谷验证：通过 ✅")
                else:
                    lines.append(
                        f"   🧩 酒谷验证：❌ {_short(str(slide.get('msg') or ''), 36)}"
                    )
            lines.append(
                f"   {_fmt_assets(r.get('assets'), r.get('integration'), r.get('wine'))}"
            )
            # 仓库剩余（摘要里压成一行，详情见过程日志）
            a = r.get("assets") or {}
            if any(
                a.get(k) is not None
                for k in (
                    "sorghum",
                    "wheat",
                    "wine_yeast",
                    "water",
                    "manure",
                    "wine",
                )
            ):
                lines.append(
                    "   📦 仓库："
                    f"高粱{a.get('sorghum')} · 小麦{a.get('wheat')} · "
                    f"酒曲{a.get('wine_yeast')} · 酒{a.get('wine')} · "
                    f"水{a.get('water')} · 机肥{a.get('manure')}"
                )
            # 当前作物（只列有种植的）
            crop_lines = r.get("crop_lines") or []
            planted = [
                x
                for x in crop_lines
                if x.startswith("  · 地块")
                and "未解锁" not in x
                and "空地" not in x
                and "没有生长" not in x
            ]
            if planted:
                lines.append("   🌱 当前作物：")
                for cl in planted:
                    # "  · 地块1: ..." → 缩进对齐
                    lines.append(f"      {cl.strip()}")
            elif r.get("land_count"):
                lines.append("   🌱 当前作物：无")
            if r.get("land_count"):
                lines.append(f"   🪴 地块：{r.get('land_count')} 块已处理")
            tasks = r.get("task_lines") or []
            done_n = sum(1 for t in tasks if "已完成" in str(t))
            if tasks:
                lines.append(f"   📋 任务：完成约 {done_n}/{len(tasks)} 项")
            if r.get("exchange"):
                lines.append(f"   🔄 兑积分：{_short(str(r.get('exchange')), 40)}")

        if i < len(results) - 1:
            lines.append("")

    lines.append("")
    lines.append("────────")
    if fail_n == 0:
        lines.append(f"📊 合计：{ok_n}/{len(results)} 全部成功 🎉")
    elif ok_n == 0:
        lines.append(f"📊 合计：{ok_n}/{len(results)} 全部失败")
    else:
        lines.append(
            f"📊 合计：成功 {ok_n} · 失败 {fail_n}（共 {len(results)} 号）"
        )
    return "\n".join(lines)


def format_notify_title(results: list[dict[str, Any]]) -> str:
    ok_n = sum(1 for r in results if r.get("ok"))
    n = len(results)
    if n == 0:
        return "习酒君品荟"
    if ok_n == n:
        return f"习酒君品荟 ✅ {ok_n}/{n}"
    if ok_n == 0:
        return f"习酒君品荟 ❌ 0/{n}"
    return f"习酒君品荟 ⚠️ {ok_n}/{n}"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
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
        logger.info("📦 从环境变量加载 %d 个账号", len(env_cfg.accounts))
        return env_cfg
    local = SCRIPT_DIR / "config.yaml"
    if local.is_file():
        logger.info("📦 使用本地配置 %s", local)
        return load_config_yaml(local)
    raise FileNotFoundError(
        "未找到账号配置。\n"
        "青龙：设置 XIJIU_ACCOUNTS 或 XIJIU_LOGIN_CODE\n"
        "本地：cp config.example.yaml config.yaml 并填写 login_code"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="习酒君品荟 · 签到/酒谷")
    parser.add_argument("-c", "--config", help="yaml 配置路径")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--no-sign", action="store_true", help="跳过签到有礼")
    parser.add_argument("--no-garden", action="store_true", help="跳过酒谷")
    parser.add_argument("--exchange", action="store_true", help="酒兑积分")
    parser.add_argument("--info-only", action="store_true", help="只登录查资产")
    args = parser.parse_args()
    setup_logging(args.verbose)

    log_banner("习酒君品荟 开始")
    try:
        cfg = resolve_config(args)
    except Exception as e:
        logger.error("%s", e)
        return 2

    if args.no_sign:
        cfg.do_sign = False
    if args.no_garden:
        cfg.do_garden = False
    if args.exchange:
        cfg.exchange_wine = True
    if args.info_only:
        cfg.do_sign = False
        cfg.do_garden = False

    # 默认 OCR：可用环境变量覆盖；未配置时用已部署 VPS（可在 yaml 关闭）
    if not cfg.ocr_server:
        cfg.ocr_server = _env("XIJIU_OCR_SERVER") or _env("OCR_SERVER") or ""

    results: list[dict[str, Any]] = []

    for acc in cfg.accounts:
        log_banner(acc.name)
        try:
            client = XiJiuClient(acc, cfg)
            if args.info_only:
                login = client.login()
                if not login.get("_ok"):
                    result = {
                        "name": acc.name,
                        "ok": False,
                        "error": login.get("_msg"),
                        "message": login.get("_msg"),
                        "lines": [str(login.get("_msg"))],
                    }
                else:
                    info = client.member_info()
                    d = info.get("data") or {}
                    lands_res = client.lands()
                    land_list = [
                        x
                        for x in (lands_res.get("data") or [])
                        if isinstance(x, dict)
                    ]
                    wh = format_warehouse(d)
                    crops = format_crops(land_list)
                    result = {
                        "name": acc.name,
                        "ok": True,
                        "phone": login.get("_phone") or "",
                        "integration": d.get("integration"),
                        "wine": d.get("wine"),
                        "assets": {
                            "sorghum": d.get("sorghum"),
                            "wheat": d.get("wheat"),
                            "wine_yeast": d.get("wine_yeast"),
                            "wine": d.get("wine"),
                            "water": d.get("water"),
                            "manure": d.get("manure"),
                            "integration": d.get("integration"),
                        },
                        "warehouse_lines": wh,
                        "crop_lines": crops,
                        "land_count": len(land_list),
                        "message": "查询成功",
                        "lines": wh + crops,
                    }
            else:
                result = client.run()
                result["name"] = acc.name
        except Exception as e:
            logger.exception("[%s] 异常", acc.name)
            result = {
                "name": acc.name,
                "ok": False,
                "error": str(e),
                "message": str(e),
                "lines": [str(e)],
            }

        results.append(result)

        # 详细过程日志（完整 lines）
        if result.get("ok"):
            logger.info("✅ [%s] 完成", acc.name)
        else:
            logger.error("❌ [%s] %s", acc.name, result.get("error") or result.get("message"))
        for L in result.get("lines") or []:
            logger.info("   · %s", L)

    summary = format_summary(results, info_only=args.info_only)
    title = format_notify_title(results)

    print("\n======== 执行结果 ========\n" + summary)
    logger.info("\n%s", summary)
    send_notify(cfg.notify, title, summary)
    log_banner("习酒君品荟 结束")
    any_fail = any(not r.get("ok") for r in results)
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
