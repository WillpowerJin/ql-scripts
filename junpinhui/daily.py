#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
习酒 · 君品荟 · 每日签到领积分（YYB Go 取 wx.login code）

cron: 25 8 * * *
new Env('君品荟签到');

只做 fm.exijiu.com「每日签到领积分」：
  - access_token：抓包 X-access-token（中长期）
  - wx_code：运行时向 YYB Go 要（app_id 固定为君品荟小程序）

青龙环境变量（账号，三选一，优先从上到下）：

  1) JUNPINHUI  多行，每行：
       host@openid|access_token#备注
     例：
       http://192.168.3.137:8000@owNAX6xxx|你的token#主号
       http://104.223.57.15:18000@owNAX6yyy|另一个token#iPhone

  2) JUNPINHUI_ACCOUNTS  JSON 数组
       [{"name":"主号","yyb":"http://host@openid","access_token":"..."}]

  3) YYB_GO + JUNPINHUI_ACCESS_TOKEN
       YYB_GO：host@openid#备注（多行，与八富相同）
       JUNPINHUI_ACCESS_TOKEN：与账号按顺序对齐，& 或换行分隔

可选：
  JUNPINHUI_NOTE / JPH_NOTE   全局备注，进 Bark 标题（如 家里青龙）
  BARK_URL / BARK_KEY         通知（与 hifiti / bafu / fanghua 共用）
  BARK_SERVER / BARK_GROUP / BARK_SOUND
  DRY_RUN=1                   只查是否已签，不 fillSignIn

依赖：requests；本地 config.yaml 可选 PyYAML
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# 青龙：尽早打日志（避免「无输出」；请用 python3 -u 运行）
# ---------------------------------------------------------------------------
def log(msg: str = "") -> None:
    """统一日志（请青龙用 python3 -u，保证实时刷出）。"""
    print(msg, flush=True)


log("君品荟签到 · 启动中…")
log(f"时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

SCRIPT_DIR = Path(__file__).resolve().parent

# 小程序 AppID（公开标识，非密钥）
APPID = "wx" + "8d41cdc4" + "4c8aeaab"
FM_HOST = "https://fm.exijiu.com"
REFERER = f"https://servicewechat.com/{APPID}/230/page-frame.html"
CHANNEL_MINI = "xj_mall_wx_applet"

P_CHECK = "/api/customer/daily/checkTodaySignIn"
P_FILL = "/api/customer/daily/fillSignIn"
P_QUERY = "/api/customer/daily/signInQuery"

DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ3A.230805.001) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 "
    "Mobile Safari/537.36 MicroMessenger/8.0.49 "
    "MiniProgramEnv/android"
)
DEFAULT_BARK = "https://api.day.app"
ICONS = "🍶🥂🍷🥃🍸🍹"

DRY_RUN = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "True", "yes")
GLOBAL_NOTE = (
    os.environ.get("JUNPINHUI_NOTE")
    or os.environ.get("JPH_NOTE")
    or os.environ.get("JUNPINHUI_TAG")
    or ""
).strip()
TIMEOUT = 20


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


# ---------------------------------------------------------------------------
# Bark
# ---------------------------------------------------------------------------

def _bark_endpoint() -> Optional[str]:
    url = (_env("BARK_URL") or _env("BARK_PUSH")).strip()
    key = (_env("BARK_KEY") or _env("BARK_DEVICE_KEY")).strip()
    if url and not url.startswith("http"):
        key = key or url
        url = ""
    if url:
        return url.rstrip("/")
    if key:
        server = (_env("BARK_SERVER") or DEFAULT_BARK).rstrip("/")
        return f"{server}/{key}"
    return None


def send_bark(title: str, body: str) -> None:
    endpoint = _bark_endpoint()
    if not endpoint:
        log("📣 未配置 BARK_URL/BARK_KEY，跳过推送")
        return
    if not endpoint.startswith("http"):
        endpoint = f"{DEFAULT_BARK.rstrip('/')}/{endpoint}"
    group = _env("BARK_GROUP") or "君品荟签到"
    payload: dict[str, Any] = {
        "title": title[:200],
        "body": body[:3500],
        "group": group,
    }
    sound = _env("BARK_SOUND")
    if sound:
        payload["sound"] = sound
    # 图标/分组美化（Bark 支持部分客户端识别）
    payload["level"] = "active"
    try:
        r = requests.post(endpoint, json=payload, timeout=15)
        if r.status_code >= 400:
            get_url = (
                f"{endpoint.rstrip('/')}/"
                f"{quote(title[:100], safe='')}/"
                f"{quote(body[:500], safe='')}"
            )
            r = requests.get(
                get_url,
                params={"group": group},
                timeout=15,
            )
        ok = r.status_code < 400
        log(f"📣 Bark {'已推送' if ok else '失败'}（HTTP {r.status_code}）")
        if not ok:
            log(f"   响应: {(r.text or '')[:200]}")
    except Exception as e:
        log(f"⚠️ Bark 推送失败: {e}")


def build_bark(results: list[dict[str, Any]]) -> tuple[str, str]:
    """美化汇总：标题短、正文卡片化（对齐 bafu / fun）。"""
    now = datetime.now().strftime("%m-%d %H:%M")
    n = len(results)
    ok_n = sum(1 for r in results if r.get("ok"))
    fail_n = n - ok_n
    signed_n = sum(1 for r in results if r.get("already"))
    fresh_n = sum(
        1
        for r in results
        if r.get("ok") and not r.get("already") and not r.get("dry_run")
    )
    points = 0
    for r in results:
        p = r.get("point")
        if p is not None:
            try:
                points += int(p)
            except (TypeError, ValueError):
                pass

    note_s = f" · {GLOBAL_NOTE}" if GLOBAL_NOTE else ""
    if n == 0:
        title = f"君品荟签到{note_s}"
    elif fail_n == 0:
        title = f"君品荟 ✅ {ok_n}/{n}{note_s}"
    elif ok_n == 0:
        title = f"君品荟 ❌ 0/{n}{note_s}"
    else:
        title = f"君品荟 ⚠️ {ok_n}/{n}{note_s}"

    lines: list[str] = []
    lines.append("🍶 习酒君品荟 · 签到汇总")
    if GLOBAL_NOTE:
        lines.append(f"🏷️ 备注：{GLOBAL_NOTE}")
    lines.append(f"📅 {now}")
    if DRY_RUN:
        lines.append("🔍 模式：DRY_RUN（未真正签到）")
    lines.append("────────────────")
    lines.append("")

    for i, r in enumerate(results):
        icon = ICONS[i % len(ICONS)]
        name = r.get("name") or "?"
        lines.append(f"{icon} 【{name}】")

        ref = (r.get("ref") or "")[:12]
        if ref:
            lines.append(f"   🔑 {ref}…")

        if not r.get("ok"):
            lines.append("   ❌ 状态：失败")
            msg = str(r.get("msg") or "未知错误")
            if len(msg) > 100:
                msg = msg[:97] + "…"
            lines.append(f"   💬 {msg}")
            if r.get("need_token") or r.get("expired"):
                lines.append("   💡 请重新抓包 X-access-token")
            elif r.get("need_wx_code"):
                lines.append("   💡 检查 YYB 服务 / 扫码是否仍存活")
        elif r.get("dry_run"):
            lines.append("   🔍 状态：未签（DRY_RUN 已跳过）")
            lines.append(f"   💬 {r.get('msg') or ''}")
        elif r.get("already"):
            lines.append("   ✅ 状态：今日已签")
            days = r.get("days")
            if days is not None:
                lines.append(f"   🔥 连续：{days} 天")
            else:
                extra = r.get("extra") or ""
                if extra:
                    lines.append(f"   🔥{extra.strip()}")
        else:
            lines.append("   ✅ 状态：签到成功")
            if r.get("point") is not None:
                lines.append(f"   🎁 积分：+{r.get('point')}")
            days = r.get("days")
            if days is not None:
                lines.append(f"   🔥 连续：{days} 天")

        if i < n - 1:
            lines.append("")

    lines.append("")
    lines.append("────────────────")
    lines.append(f"📦 账号 {n} · ✅{ok_n}  ❌{fail_n}")
    if signed_n:
        lines.append(f"📌 其中已签：{signed_n}")
    if fresh_n:
        lines.append(f"✍️ 本次新签：{fresh_n}")
    if points:
        lines.append(f"🎯 本次积分：+{points}")
    if fail_n == 0 and n > 0:
        lines.append("🎉 全部顺利")
    elif n == 0:
        lines.append("😿 未配置账号")
    elif ok_n == 0:
        lines.append("😿 请检查 access_token / YYB_GO")
    else:
        lines.append("💡 部分账号需关注日志")

    return title, "\n".join(lines)


# ---------------------------------------------------------------------------
# YYB Go
# ---------------------------------------------------------------------------

def parse_yyb_host_ref(line: str) -> tuple[Optional[str], Optional[str], str]:
    """解析 host@openid 或 host@openid#备注 → (host, ref, note)。"""
    env = (line or "").strip()
    if not env or env.startswith("#"):
        return None, None, ""
    note = ""
    at = env.find("@")
    if at >= 0:
        tail = env[at + 1 :]
        if "#" in tail:
            ref_part, note = tail.split("#", 1)
            env = env[: at + 1] + ref_part
            note = note.strip()
    else:
        if "#" in env:
            env, note = env.rsplit("#", 1)
            note = note.strip()
    if "@" not in env:
        return None, None, note
    host, ref = env.split("@", 1)
    host, ref = host.strip(), ref.strip()
    if not host or not ref:
        return None, None, note
    if not host.startswith("http://") and not host.startswith("https://"):
        host = "http://" + host
    return host.rstrip("/"), ref, note


def get_yyb_code(host: str, ref: str, appid: str = APPID) -> Optional[str]:
    url = f"{host.rstrip('/')}/wxapp/getCode"
    try:
        resp = requests.post(
            url,
            json={"ref": ref, "app_id": appid},
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            log(f"   ⚠️ YYB HTTP {resp.status_code}: {resp.text[:120]}")
            return None
        data = resp.json()
        code = None
        if isinstance(data, dict):
            d = data.get("data")
            if isinstance(d, dict):
                result = d.get("result")
                if isinstance(result, dict):
                    code = result.get("code")
                if (
                    not code
                    and isinstance(d.get("code"), str)
                    and len(d["code"]) > 4
                ):
                    code = d.get("code")
            if not code and isinstance(data.get("result"), dict):
                code = data["result"].get("code")
        if isinstance(code, str) and len(code) > 4:
            return code
        log(
            f"   ⚠️ YYB 无有效 code: "
            f"{json.dumps(data, ensure_ascii=False)[:200]}"
        )
        return None
    except Exception as e:
        log(f"   ⚠️ YYB 异常: {e}")
        return None


# ---------------------------------------------------------------------------
# 账号
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    host: str
    ref: str
    access_token: str

    @property
    def display(self) -> str:
        return self.name or (self.ref[:8] + "…" if self.ref else "?")


def _split_multi(raw: str) -> list[str]:
    """青龙多值：换行 / & / 英文分号。"""
    raw = (raw or "").strip()
    if not raw:
        return []
    # 统一换行
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" in raw:
        parts = raw.split("\n")
    elif "&" in raw:
        parts = raw.split("&")
    elif ";" in raw and raw.count(";") >= 1 and "|" not in raw:
        # 仅当不像 host|token 时用分号
        parts = raw.split(";")
    else:
        parts = [raw]
    out = []
    for x in parts:
        x = x.strip()
        if x and not x.startswith("#"):
            out.append(x)
    return out


def parse_jph_line(line: str) -> Optional[Account]:
    """host@openid|access_token#备注"""
    line = (line or "").strip()
    if not line or line.startswith("#"):
        return None
    note = ""
    if "#" in line:
        left, maybe_note = line.rsplit("#", 1)
        if "|" in left or "@" in left:
            line, note = left, maybe_note.strip()
    if "|" not in line:
        return None
    yyb_part, token = line.split("|", 1)
    token = token.strip()
    host, ref, note2 = parse_yyb_host_ref(yyb_part)
    note = note or note2
    if not host or not ref or not token:
        return None
    name = note or (ref[:8] + "…")
    return Account(name=name, host=host, ref=ref, access_token=token)


def load_accounts() -> list[Account]:
    accounts: list[Account] = []

    # 1) JUNPINHUI
    raw = _env("JUNPINHUI")
    if raw:
        for line in _split_multi(raw):
            acc = parse_jph_line(line)
            if acc:
                accounts.append(acc)
            else:
                h, r, _n = parse_yyb_host_ref(line)
                if h and r:
                    log(f"⚠️ JUNPINHUI 行缺少 |access_token: {line[:48]}…")
                else:
                    log(f"⚠️ JUNPINHUI 格式错误: {line[:60]}")
        if accounts:
            return accounts

    # 2) JSON
    jraw = _env("JUNPINHUI_ACCOUNTS") or _env("JPH_ACCOUNTS")
    if jraw:
        try:
            arr = json.loads(jraw)
        except json.JSONDecodeError as e:
            raise ValueError(f"JUNPINHUI_ACCOUNTS JSON 无效: {e}") from e
        if not isinstance(arr, list):
            raise ValueError("JUNPINHUI_ACCOUNTS 须为 JSON 数组")
        for i, item in enumerate(arr):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("note") or f"账号{i+1}").strip()
            token = str(
                item.get("access_token")
                or item.get("accessToken")
                or item.get("token")
                or ""
            ).strip()
            host = ref = None
            yyb = str(
                item.get("yyb") or item.get("yyb_go") or item.get("YYB_GO") or ""
            ).strip()
            if yyb:
                host, ref, note = parse_yyb_host_ref(yyb)
                if note and (not name or name.startswith("账号")):
                    name = note
            else:
                host = str(item.get("host") or item.get("yyb_host") or "").strip()
                ref = str(item.get("ref") or item.get("openid") or "").strip()
                if host and not host.startswith("http"):
                    host = "http://" + host
                host = host.rstrip("/") if host else None
            if not host or not ref or not token:
                log(f"⚠️ JSON 账号不完整: {name}")
                continue
            accounts.append(
                Account(name=name, host=host, ref=ref, access_token=token)
            )
        if accounts:
            return accounts

    # 3) YYB_GO + token
    yyb_raw = _env("YYB_GO")
    tok_raw = _env("JUNPINHUI_ACCESS_TOKEN") or _env("JPH_ACCESS_TOKEN")
    if yyb_raw and tok_raw:
        yyb_lines: list[tuple[str, str, str]] = []
        for line in _split_multi(yyb_raw):
            h, r, n = parse_yyb_host_ref(line)
            if h and r:
                yyb_lines.append((h, r, n))
        tokens = _split_multi(tok_raw)
        n = min(len(yyb_lines), len(tokens))
        if len(yyb_lines) != len(tokens):
            log(
                f"⚠️ YYB_GO({len(yyb_lines)}) 与 TOKEN({len(tokens)}) "
                f"数量不一致，按 {n} 个对齐"
            )
        for i in range(n):
            h, r, note = yyb_lines[i]
            accounts.append(
                Account(
                    name=note or f"账号{i+1}",
                    host=h,
                    ref=r,
                    access_token=tokens[i],
                )
            )
        if accounts:
            return accounts

    # 4) 本地 config.yaml
    cfg_path = SCRIPT_DIR / "config.yaml"
    if cfg_path.is_file():
        try:
            import yaml  # type: ignore
        except ImportError:
            log("⚠️ 有 config.yaml 但未安装 PyYAML，跳过")
            return accounts
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        for i, item in enumerate(cfg.get("accounts") or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or f"账号{i+1}").strip()
            token = str(item.get("access_token") or "").strip()
            yyb = str(item.get("yyb") or item.get("yyb_go") or "").strip()
            host = ref = None
            if yyb:
                host, ref, note = parse_yyb_host_ref(yyb)
                if note and name.startswith("账号"):
                    name = note
            else:
                host = str(item.get("host") or "").strip()
                ref = str(item.get("ref") or item.get("openid") or "").strip()
                if host and not host.startswith("http"):
                    host = "http://" + host
                host = host.rstrip("/") if host else None
            if host and ref and token:
                accounts.append(
                    Account(name=name, host=host, ref=ref, access_token=token)
                )
    return accounts


# ---------------------------------------------------------------------------
# 业务
# ---------------------------------------------------------------------------

class Client:
    def __init__(self, account: Account):
        self.account = account
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_UA})

    def _fm_headers(self) -> dict[str, str]:
        return {
            "User-Agent": DEFAULT_UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/json",
            "channel": "miniapp",
            "X-access-token": self.account.access_token,
            "Origin": FM_HOST,
            "Referer": REFERER,
            "Connection": "keep-alive",
        }

    def fm_post(self, path: str, body: Any = None) -> dict[str, Any]:
        if body is None:
            body = {}
        try:
            r = self.session.post(
                f"{FM_HOST}{path}",
                headers=self._fm_headers(),
                json=body,
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            return {"_ok": False, "_msg": f"网络错误: {e}"}
        try:
            body_j = r.json()
        except Exception:
            return {
                "_ok": False,
                "_msg": f"非 JSON HTTP {r.status_code}: {r.text[:160]}",
            }
        code = body_j.get("code")
        ok = code in (0, "0", 200, "200", 10000, "10000") or body_j.get(
            "success"
        ) is True
        if body_j.get("success") is True and code not in (401, "401", "99990002"):
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

    def _query_streak(self) -> tuple[Optional[int], str]:
        """返回 (连续天数, 文案后缀)。"""
        q = self.fm_post(P_QUERY, {})
        qd = q.get("data")
        if isinstance(qd, list) and qd:
            feat = qd[0].get("feature") if isinstance(qd[0], dict) else None
            try:
                if isinstance(feat, str):
                    feat = json.loads(feat)
                if isinstance(feat, dict):
                    num = (feat.get("extra") or {}).get("signNum1")
                    if num is not None:
                        return int(num), f" 连续{num}天"
            except Exception:
                pass
        if isinstance(qd, dict):
            days = qd.get("continuousSignDays") or qd.get("continuousDays")
            if days is not None:
                try:
                    d = int(days)
                    return d, f" 连续{d}天"
                except (TypeError, ValueError):
                    return None, f" 连续{days}天"
        return None, ""

    def sign(self) -> dict[str, Any]:
        if not self.account.access_token:
            return {
                "ok": False,
                "msg": "未配置 access_token",
                "need_token": True,
            }

        check = self.fm_post(P_CHECK, {})
        data = check.get("data")
        msg = str(check.get("_msg") or "")
        if check.get("code") in (401, "401") or "未登录" in msg:
            return {
                "ok": False,
                "msg": "access_token 已失效（401）。请重新抓包 X-access-token",
                "need_token": True,
                "expired": True,
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
            days, extra = self._query_streak()
            return {
                "ok": True,
                "msg": f"今日已签到{extra}",
                "already": True,
                "days": days,
                "extra": extra,
            }

        if DRY_RUN:
            return {
                "ok": True,
                "msg": "今日未签（DRY_RUN 不执行 fillSignIn）",
                "already": False,
                "dry_run": True,
            }

        log(f"   📥 YYB getCode appid={APPID[:10]}…")
        wx_code = get_yyb_code(self.account.host, self.account.ref, APPID)
        if not wx_code:
            return {
                "ok": False,
                "msg": "今日未签，YYB 未返回 wx_code（检查服务/扫码态）",
                "need_wx_code": True,
            }
        log(f"   🎫 code={wx_code[:12]}…")

        fill = self.fm_post(
            P_FILL,
            {"code": wx_code, "channelCode": CHANNEL_MINI},
        )
        fmsg = str(fill.get("_msg") or "")
        fdata = fill.get("data")
        point = None
        if isinstance(fdata, dict):
            point = fdata.get("pointValue") or fdata.get("point")

        if fill.get("_ok"):
            if any(k in fmsg for k in ("已签", "重复")):
                days, extra = self._query_streak()
                return {
                    "ok": True,
                    "msg": fmsg or "今日已签到",
                    "already": True,
                    "days": days,
                    "extra": extra,
                }
            days, extra = self._query_streak()
            tip = (
                f"签到成功+{point}积分{extra}"
                if point is not None
                else (fmsg or f"签到成功{extra}")
            )
            return {
                "ok": True,
                "msg": tip,
                "already": False,
                "point": point,
                "days": days,
                "extra": extra,
            }

        if "code" in fmsg and any(k in fmsg for k in ("空", "无效", "失败")):
            return {
                "ok": False,
                "msg": fmsg or "wx_code 无效",
                "need_wx_code": True,
            }
        return {"ok": False, "msg": fmsg or "积分签到失败"}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    log("🚀 君品荟 · 每日签到（YYB）")
    if GLOBAL_NOTE:
        log(f"🏷️ 全局备注: {GLOBAL_NOTE}")
    if _bark_endpoint():
        log("📣 Bark 已配置")
    else:
        log("📣 未配置 BARK_URL/BARK_KEY")
    if DRY_RUN:
        log("🔍 DRY_RUN：只查询不 fillSignIn")
    log(f"🎯 小程序 appid={APPID}")
    log("")

    try:
        accounts = load_accounts()
    except ValueError as e:
        log(f"❌ {e}")
        title, body = build_bark([])
        send_bark(title if title else "君品荟 ❌", f"❌ 配置错误\n{e}")
        return 1

    if not accounts:
        log("❌ 未配置账号")
        log("   青龙变量 JUNPINHUI（多行）：")
        log("   http://YYB地址@openid|access_token#备注")
        log("   或 YYB_GO + JUNPINHUI_ACCESS_TOKEN")
        title, body = build_bark([])
        send_bark(
            f"君品荟 ❌" + (f" · {GLOBAL_NOTE}" if GLOBAL_NOTE else ""),
            "❌ 未配置账号\n\n"
            "请设置环境变量：\n"
            "JUNPINHUI=http://host@openid|token#备注\n"
            "或 YYB_GO + JUNPINHUI_ACCESS_TOKEN",
        )
        return 1

    log(f"📋 共 {len(accounts)} 个账号")
    results: list[dict[str, Any]] = []
    n_ok = 0

    for i, acc in enumerate(accounts):
        icon = ICONS[i % len(ICONS)]
        log("")
        log(f"{'=' * 40}")
        log(f"{icon} [{i+1}/{len(accounts)}] {acc.display}")
        log(f"   openid={acc.ref[:14]}…")
        log(f"   yyb={acc.host}")
        try:
            r = Client(acc).sign()
        except Exception as e:
            log(f"   ❌ 异常: {e}")
            r = {"ok": False, "msg": f"异常: {e}"}
        ok = bool(r.get("ok"))
        if ok:
            n_ok += 1
        mark = "✅" if ok else "❌"
        log(f"   {mark} {r.get('msg')}")
        results.append(
            {
                "name": acc.display,
                "ref": acc.ref,
                **r,
            }
        )

    title, body = build_bark(results)
    log("")
    log(body)
    log("")
    log(f"🏁 结束 {n_ok}/{len(accounts)} 成功")
    send_bark(title, body)
    return 0 if n_ok == len(accounts) else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n已中断")
        sys.exit(130)
    except Exception as e:
        log(f"❌ 未捕获异常: {e}")
        send_bark(
            f"君品荟 ❌" + (f" · {GLOBAL_NOTE}" if GLOBAL_NOTE else ""),
            f"❌ 脚本异常\n{e}",
        )
        sys.exit(1)
