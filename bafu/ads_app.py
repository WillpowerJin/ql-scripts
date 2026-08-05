#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
八富生活 - 新版 App 协议看广告（手机号密码登录 + markmedia）

cron: 0 9-23/2 * * *
new Env('八富秒得App');

依赖：requests

环境变量：
  BAFU            必填。账号，多账号换行或 & 分隔
                  格式：手机号#密码
                  带备注：手机号#密码#备注（如 iPhone）
                  例：
                    13800138000#pass123#主号
                    13900139000#pass456
  BAFU_NOTE       可选。全局备注，出现在 Bark 标题（如 家里青龙）
  BARK_URL / BARK_KEY   通知（与仓库其它脚本共用）
  BARK_SERVER / BARK_GROUP / BARK_SOUND  可选
  BFSH_INVITER_CODE     邀请码，默认 U75803F7
  DRY_RUN=1             只登录查询进度，不刷广告

说明：
  - 登录 portal-server，Cookie 鉴权
  - 广告走 markmedia 激励/插屏上报，模拟观看等待后确认
  - 不依赖 YYB / 微信 code；纯 App 手机号密码协议
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# 常量
# ============================================================
PLACEMENT_ID = "48763601"
APPID = "87636"
SECRET = "898b00d0a6d876705af1d1b49f756736"
DEVICE_ID = "91809f7d-d832-401e-8015-a2de8e46042b"
X_TENANT_ID = "1992418264477876226"
NETWORK_ID = 8
AD_WAIT_SECONDS = int(os.environ.get("BAFU_AD_WAIT", "32") or "32")
AD_INTERVAL_SECONDS = int(os.environ.get("BAFU_AD_INTERVAL", "5") or "5")
INVITE_CODE = (
    os.environ.get("BFSH_INVITER_CODE")
    or os.environ.get("BAFU_INVITER_CODE")
    or "U75803F7"
).strip() or "U75803F7"

BAFU_BASE = "https://bafunet.com/portal-server"
MARKMEDIA_BASE = "http://biz.markmedia.com.cn/api"
DEFAULT_BARK_SERVER = "https://api.day.app"
ACCOUNT_ICONS = "🍺🍷🍸🍹🥂🍶🧉☕🍵🥃"
DRY_RUN = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "True", "yes")
GLOBAL_NOTE = (
    os.environ.get("BAFU_NOTE")
    or os.environ.get("BFSH_NOTE")
    or os.environ.get("BAFU_TAG")
    or ""
).strip()


# ============================================================
# 工具
# ============================================================
def log(msg: str = "") -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def mask_phone(phone: str) -> str:
    p = (phone or "").strip()
    if len(p) >= 7:
        return p[:3] + "****" + p[-4:]
    return p or "?"


# ============================================================
# 账号
# ============================================================
def get_accounts() -> list[dict[str, str]]:
    """
    BAFU：手机号#密码 或 手机号#密码#备注
    多账号：换行 或 & 分隔
    """
    raw = _env("BAFU")
    if not raw:
        return []
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    # 支持 & 与换行
    parts: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "&" in line and "#" in line:
            parts.extend(p.strip() for p in line.split("&") if p.strip())
        else:
            parts.append(line)

    acc_list: list[dict[str, str]] = []
    for i, part in enumerate(parts):
        if "#" not in part:
            log(f"⚠️ 第 {i + 1} 段格式错误（需要 手机号#密码[#备注]）：{part[:24]}…")
            continue
        bits = part.split("#")
        phone = bits[0].strip()
        pwd = bits[1].strip() if len(bits) >= 2 else ""
        note = bits[2].strip() if len(bits) >= 3 else ""
        if not phone or not pwd:
            log(f"⚠️ 第 {i + 1} 段手机号或密码为空，跳过")
            continue
        label = note or mask_phone(phone)
        acc_list.append({"phone": phone, "pwd": pwd, "note": note, "label": label})
    return acc_list


# ============================================================
# Bark（与 fun / tuiguangbao 等脚本对齐）
# ============================================================
def bark_endpoint() -> Optional[str]:
    url = _env("BARK_URL") or _env("BARK_PUSH")
    key = _env("BARK_KEY") or _env("BARK_DEVICE_KEY")
    if url and not url.startswith("http"):
        key = key or url
        url = ""
    if url:
        return url.rstrip("/")
    if key:
        server = (_env("BARK_SERVER") or DEFAULT_BARK_SERVER).rstrip("/")
        return f"{server}/{key}"
    return None


def send_bark(title: str, body: str) -> None:
    endpoint = bark_endpoint()
    if not endpoint:
        log("ℹ️ 未配置 BARK_URL/BARK_KEY，跳过推送")
        return
    if not endpoint.startswith("http"):
        endpoint = f"{DEFAULT_BARK_SERVER.rstrip('/')}/{endpoint}"
    group = _env("BARK_GROUP") or "八富秒得"
    payload: dict[str, Any] = {
        "title": title[:200],
        "body": body[:3500],
        "group": group,
    }
    sound = _env("BARK_SOUND")
    if sound:
        payload["sound"] = sound
    try:
        r = requests.post(endpoint, json=payload, timeout=15)
        if r.status_code >= 400:
            get_url = (
                f"{endpoint.rstrip('/')}/"
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


def bark_title(ok_all: bool, n: int, ok_n: int) -> str:
    tag = f" · {GLOBAL_NOTE}" if GLOBAL_NOTE else ""
    if n == 0:
        return f"八富秒得{tag} ❌ 未配置账号"
    if ok_all:
        return f"八富秒得{tag} ✅ {ok_n}/{n}"
    return f"八富秒得{tag} ⚠️ {ok_n}/{n}"


# ============================================================
# 登录 / 邀请
# ============================================================
def bafu_login(phone: str, password: str) -> Optional[requests.Session]:
    s = requests.Session()
    headers = {
        "X-Tenant-ID": X_TENANT_ID,
        "Content-Type": "application/json; charset=utf-8",
        "Host": "bafunet.com",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "User-Agent": "okhttp/4.12.0",
    }
    payload = {
        "phone": phone,
        "username": phone,
        "type": "N",
        "clientType": "app",
        "password": password,
    }
    try:
        resp = s.post(f"{BAFU_BASE}/login", headers=headers, json=payload, timeout=20)
        res_json = resp.json()
        if res_json.get("code") == 200:
            jsession = s.cookies.get("JSESSIONID")
            remember = s.cookies.get("remember-me")
            if jsession and remember:
                cookie_str = f"remember-me={remember}; JSESSIONID={jsession}"
                log(f"✅【{mask_phone(phone)}】登录成功")
                s.headers.update({"Cookie": cookie_str, "User-Agent": "okhttp/4.12.0"})
                return s
            log(f"❌【{mask_phone(phone)}】登录响应未获取 Cookie")
            return None
        log(f"❌【{mask_phone(phone)}】登录失败 {res_json}")
        return None
    except Exception as e:
        log(f"⚠️【{mask_phone(phone)}】登录异常：{e}")
        return None


def make_markmedia_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Char-Set": "utf-8",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 16; MI 8 Build/BP4A.251205.006)",
        "Host": "biz.markmedia.com.cn",
    }


def get_inviter_info(session: requests.Session) -> Optional[dict]:
    try:
        resp = session.get(f"{BAFU_BASE}/user/getInviter", timeout=15)
        return resp.json()
    except Exception as e:
        log(f"⚠️ 查询邀请人信息异常：{e}")
        return None


def bind_inviter_code(session: requests.Session, code: str) -> Optional[dict]:
    try:
        resp = session.post(
            f"{BAFU_BASE}/user/setInviter", params={"code": code}, timeout=15
        )
        return resp.json()
    except Exception as e:
        log(f"⚠️ 绑定邀请码请求异常：{e}")
        return None


def try_bind_inviter(session: requests.Session, phone: str) -> Optional[str]:
    """返回已绑定/操作结果简述，供汇总展示。"""
    label = mask_phone(phone)
    log(f"【{label}】检查邀请码绑定状态")
    resp_data = get_inviter_info(session)
    if not resp_data:
        log(f"⚠️【{label}】获取邀请信息失败，跳过绑定")
        return None

    data_info = resp_data.get("data")
    if data_info:
        inviter_name = data_info.get("nickname") or data_info.get("phone", "未知")
        log(f"【{label}】已绑定邀请人：{inviter_name}")
        return str(inviter_name)

    log(f"【{label}】暂无绑定，尝试绑定邀请码 {INVITE_CODE}")
    bind_resp = bind_inviter_code(session, INVITE_CODE)
    if not bind_resp:
        log(f"❌【{label}】绑定请求异常，继续广告任务")
        return None
    bind_code = bind_resp.get("code")
    msg = bind_resp.get("msg", "") or ""

    if bind_code == 200:
        log(f"✅【{label}】邀请码 {INVITE_CODE} 绑定成功")
        return INVITE_CODE
    if "hasCycleInvite" in msg:
        log(f"ℹ️【{label}】账号为邀请码本人，无需绑定")
        return "本人"
    if "errorReq" in msg:
        log(f"ℹ️【{label}】平台限制，无法改绑邀请人")
        return "限制改绑"
    log(f"❌【{label}】绑定提示：{msg}")
    return None


# ============================================================
# 广告 API
# ============================================================
def get_user_info(session: requests.Session) -> tuple[Optional[str], Optional[dict]]:
    try:
        resp = session.get(f"{BAFU_BASE}/user/getBaseInfoAnon", timeout=15)
        data = resp.json()
    except Exception as e:
        log(f"获取用户信息异常: {e}")
        return None, None
    if data.get("code") == 200:
        ud = data["data"]
        log(
            f"用户: {ud.get('nickname', ud.get('phone'))}, "
            f"收益: {ud.get('adProfit')}"
        )
        return str(ud["id"]), ud
    log(f"获取用户信息失败: {data}")
    return None, None


def check_limit(session: requests.Session) -> Optional[dict]:
    try:
        resp = session.get(
            f"{BAFU_BASE}/ad/checkLimit",
            params={"adpid": PLACEMENT_ID},
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        log(f"checkLimit 异常: {e}")
        return None
    if data.get("code") == 200:
        return data["data"]
    log(f"checkLimit 失败: {data}")
    return None


def request_interstitial() -> bool:
    url = f"{MARKMEDIA_BASE}/sdk/reward/interstitial/{PLACEMENT_ID}"
    headers = make_markmedia_headers()
    headers.pop("Content-Type", None)
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        return resp.json().get("code") == 0
    except Exception as e:
        log(f"request_interstitial 异常: {e}")
        return False


def report_show_reward() -> bool:
    url = f"{MARKMEDIA_BASE}/app/statement/show/reward"
    body = {
        "placementId": PLACEMENT_ID,
        "appid": APPID,
        "secret": SECRET,
        "deviceId": DEVICE_ID,
    }
    try:
        resp = requests.post(
            url, json=body, headers=make_markmedia_headers(), timeout=10
        )
        return resp.json().get("code") == 0
    except Exception:
        return False


def request_reward() -> bool:
    url = f"{MARKMEDIA_BASE}/app/statement/request/reward"
    body = {
        "placementId": PLACEMENT_ID,
        "appid": APPID,
        "secret": SECRET,
        "deviceId": DEVICE_ID,
    }
    try:
        resp = requests.post(
            url, json=body, headers=make_markmedia_headers(), timeout=10
        )
        return resp.json().get("code") == 0
    except Exception:
        return False


def confirm_reward(check_limit_id: str, user_id: str) -> bool:
    url = f"{MARKMEDIA_BASE}/sdk/reward/v2/self/{PLACEMENT_ID}"
    body = {
        "user_custom_data": f"{check_limit_id}_{PLACEMENT_ID}",
        "network_id": NETWORK_ID,
        "device_id": "",
        "user_id": user_id,
        "anythink_reward_fallback": 1,
    }
    try:
        resp = requests.post(
            url, json=body, headers=make_markmedia_headers(), timeout=10
        )
        log(f"  确认完成: {resp.status_code}, {resp.text[:200]}")
        return resp.status_code == 200
    except Exception as e:
        log(f"confirm_reward 异常: {e}")
        return False


# ============================================================
# 单账号流程
# ============================================================
def watch_loop(session: requests.Session, phone: str, label: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": label,
        "phone": mask_phone(phone),
        "watched": 0,
        "final_count": None,
        "total_ads": None,
        "profit": None,
        "inviter": None,
        "errors": [],
        "dry_run": DRY_RUN,
    }

    user_id, ud = get_user_info(session)
    if not user_id:
        result["errors"].append("获取用户ID失败")
        return result
    if ud is not None:
        result["profit"] = ud.get("adProfit")

    inv = try_bind_inviter(session, phone)
    if inv:
        result["inviter"] = inv
    time.sleep(2)

    limit_data = check_limit(session)
    if not limit_data:
        result["errors"].append("查询广告限制失败")
        return result

    total = int(limit_data.get("totalAds") or 0)
    cnt = int(limit_data.get("count") or "0")
    result["total_ads"] = total
    result["final_count"] = cnt
    log(f"【{label}】当前进度: {cnt}/{total}")

    if DRY_RUN:
        log(f"【{label}】DRY_RUN：不刷广告")
        return result

    if cnt >= total > 0:
        log(f"【{label}】今日广告已达上限 {cnt}/{total}")
        return result

    ad_count = 0
    fail_streak = 0
    max_fail = 8

    while True:
        limit_data = check_limit(session)
        if not limit_data:
            fail_streak += 1
            log(f"查询广告限制失败，等待 30s 重试（连续失败 {fail_streak}/{max_fail}）")
            if fail_streak >= max_fail:
                result["errors"].append("checkLimit 连续失败")
                break
            time.sleep(30)
            continue

        check_id = limit_data.get("id") or str(uuid.uuid4()).replace("-", "")
        total = int(limit_data.get("totalAds") or 0)
        cnt = int(limit_data.get("count") or "0")
        result["total_ads"] = total
        result["final_count"] = cnt

        if total > 0 and cnt >= total:
            log(f"【{label}】今日广告已达上限 {cnt}/{total}，共完成 {ad_count} 条")
            break

        log(f"【{label}】进度: {cnt}/{total}")

        if not request_interstitial():
            fail_streak += 1
            log(f"请求广告物料失败，30s 重试（{fail_streak}/{max_fail}）")
            if fail_streak >= max_fail:
                result["errors"].append("interstitial 连续失败")
                break
            time.sleep(30)
            continue
        time.sleep(0.3)

        if not report_show_reward():
            fail_streak += 1
            log(f"上报展示失败（{fail_streak}/{max_fail}）")
            if fail_streak >= max_fail:
                result["errors"].append("show/reward 连续失败")
                break
            time.sleep(30)
            continue
        time.sleep(0.3)

        if not request_reward():
            fail_streak += 1
            log(f"请求奖励上报失败（{fail_streak}/{max_fail}）")
            if fail_streak >= max_fail:
                result["errors"].append("request/reward 连续失败")
                break
            time.sleep(30)
            continue

        log(f"等待 {AD_WAIT_SECONDS}s（模拟观看广告）...")
        time.sleep(AD_WAIT_SECONDS)

        if not confirm_reward(check_id, user_id):
            fail_streak += 1
            log(f"广告完成确认失败（{fail_streak}/{max_fail}）")
            if fail_streak >= max_fail:
                result["errors"].append("confirm 连续失败")
                break
            time.sleep(30)
            continue

        time.sleep(0.5)

        new_limit = check_limit(session)
        if new_limit and int(new_limit.get("count") or "0") > cnt:
            ad_count += 1
            fail_streak = 0
            result["watched"] = ad_count
            result["final_count"] = int(new_limit.get("count") or "0")
            result["total_ads"] = int(new_limit.get("totalAds") or total)
            log(
                f"✅ 观看成功！{cnt} → {new_limit['count']}，"
                f"已完成 {ad_count} 条"
            )
            log(f"等待 {AD_INTERVAL_SECONDS}s 进行下一条...")
            time.sleep(AD_INTERVAL_SECONDS)
        else:
            fail_streak += 1
            log(f"⚠️ 计数未上涨 {cnt}，等待 30s 重试（{fail_streak}/{max_fail}）")
            if fail_streak >= max_fail:
                result["errors"].append("计数未上涨连续失败")
                break
            time.sleep(30)

    # 收尾再查一次收益
    try:
        _, ud2 = get_user_info(session)
        if ud2 is not None:
            result["profit"] = ud2.get("adProfit")
    except Exception:
        pass

    return result


# ============================================================
# 汇总
# ============================================================
def push_summary(results: list[dict[str, Any]]) -> None:
    if not results:
        send_bark(bark_title(False, 0, 0), "❌ 无账号结果")
        return

    n = len(results)
    ok_n = sum(1 for r in results if not r.get("errors"))
    fail_n = n - ok_n
    total_watched = sum(int(r.get("watched") or 0) for r in results)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = []
    lines.append("🎬 八富生活 · App 看广告汇总")
    if GLOBAL_NOTE:
        lines.append(f"🏷️ 备注：{GLOBAL_NOTE}")
    lines.append(f"📅 {now}")
    lines.append("────────────────")
    lines.append("")

    for i, r in enumerate(results):
        icon = ACCOUNT_ICONS[i % len(ACCOUNT_ICONS)]
        name = r.get("name") or "?"
        head = f"{icon} 【{name}】"
        if r.get("phone") and r.get("phone") != name:
            head += f"  {r['phone']}"
        lines.append(head)

        if r.get("errors"):
            err = "; ".join(r["errors"])
            if len(err) > 80:
                err = err[:77] + "…"
            lines.append("   ❌ 状态：异常")
            lines.append(f"   💬 {err}")
        elif r.get("dry_run"):
            fc = r.get("final_count")
            ta = r.get("total_ads")
            lines.append("   🔍 DRY_RUN 仅查询")
            if fc is not None:
                lines.append(f"   📊 今日进度：{fc}/{ta}")
        else:
            w = int(r.get("watched") or 0)
            if w > 0:
                lines.append(f"   ✅ 本次完成：{w} 条广告")
            else:
                lines.append("   ✅ 状态：正常（已满或无需再看）")
            fc = r.get("final_count")
            ta = r.get("total_ads")
            if fc is not None:
                lines.append(f"   📊 今日进度：{fc}/{ta}")

        if r.get("profit") is not None:
            lines.append(f"   💰 收益：{r['profit']}")
        inv = r.get("inviter")
        if inv:
            lines.append(f"   🤝 邀请：{inv}")

        if i < n - 1:
            lines.append("")

    lines.append("")
    lines.append("────────────────")
    lines.append(f"📦 账号 {n} 个 · ✅{ok_n}  ❌{fail_n}")
    lines.append(f"🎯 合计观看：{total_watched} 条")
    if fail_n == 0:
        lines.append("🎉 全部顺利")
    elif ok_n == 0:
        lines.append("😿 请检查 BAFU 账号密码 / 网络")
    else:
        lines.append("💡 部分账号需关注日志")

    text = "\n".join(lines)
    log("")
    log(text)
    send_bark(bark_title(fail_n == 0, n, ok_n), text)


# ============================================================
# 入口
# ============================================================
def main() -> int:
    log("🚀 八富秒得 App 协议 ads_app")
    if GLOBAL_NOTE:
        log(f"🏷️ 全局备注: {GLOBAL_NOTE}")
    if bark_endpoint():
        log("📣 Bark 已配置")
    else:
        log("📣 未配置 BARK_URL/BARK_KEY")
    if DRY_RUN:
        log("🔍 DRY_RUN：只查询不刷广告")
    log(f"🎯 placement={PLACEMENT_ID} wait={AD_WAIT_SECONDS}s interval={AD_INTERVAL_SECONDS}s")

    accounts = get_accounts()
    if not accounts:
        log("❌ 未读取到账号！请配置环境变量 BAFU")
        log("   格式：手机号#密码  或  手机号#密码#备注")
        log("   多账号换行或 & 分隔；全局备注：BAFU_NOTE=家里青龙")
        send_bark(
            bark_title(False, 0, 0),
            "❌ 未配置 BAFU\n格式：手机号#密码[#备注]\n多账号换行",
        )
        return 1

    log(f"📋 {len(accounts)} 个账号")
    results: list[dict[str, Any]] = []

    for idx, acc in enumerate(accounts, 1):
        phone = acc["phone"]
        label = acc["label"]
        log("")
        log("=" * 60)
        log(f"▶ [{idx}/{len(accounts)}] {label}（{mask_phone(phone)}）")
        try:
            sess = bafu_login(phone, acc["pwd"])
            if not sess:
                results.append(
                    {
                        "name": label,
                        "phone": mask_phone(phone),
                        "watched": 0,
                        "errors": ["登录失败"],
                    }
                )
                continue
            r = watch_loop(sess, phone, label)
            r.setdefault("name", label)
            results.append(r)
        except Exception as e:
            log(f"❌ 异常: {e}")
            results.append(
                {
                    "name": label,
                    "phone": mask_phone(phone),
                    "watched": 0,
                    "errors": [f"异常: {e}"],
                }
            )
        if idx < len(accounts):
            log("当前账号结束，切换下一账号…")
            time.sleep(5)

    push_summary(results)
    log("🏁 全部完成")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n⚠️ 用户中断")
        sys.exit(130)
