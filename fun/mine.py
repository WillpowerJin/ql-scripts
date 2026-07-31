#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FUN 矿池自动任务（登录 / 收矿 / 查状态 / 可选升级）

cron: 10 8 * * *
new Env('FUN矿池');

环境变量 FUN（必填，多账号 & 或换行）：
  手机号#密码#收矿#升级
  手机号#密码#收矿#升级#备注
  收矿/升级：1=开 0=关
  例：
    13800138000#pass#1#0#iPhone
    13900139000#pass#1#0#Android

可选：
  FUN_NOTE=家里青龙          # 全局备注，进 Bark 标题
  BARK_URL / BARK_KEY        # 通知（与仓库其它项目共用）
  BARK_SERVER / BARK_GROUP / BARK_SOUND
  FUN_BASE_URL               # 默认 https://exchange.acmes.dev/api/v1

依赖：requests
"""

from __future__ import annotations

import json
import os
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

    @property
    def label(self) -> str:
        if self.note:
            return self.note
        return mask_mobile(self.mobile)


def parse_accounts(raw: str) -> list[Account]:
    """
    手机号#密码#收矿#升级
    手机号#密码#收矿#升级#备注
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
            log(f"⚠️ 第 {i + 1} 段格式错误，需要 手机号#密码#收矿#升级[#备注]：{part[:20]}…")
            continue
        mobile, pwd, claim_s, up_s = bits[0].strip(), bits[1], bits[2].strip(), bits[3].strip()
        note = bits[4].strip() if len(bits) >= 5 else ""
        out.append(
            Account(
                mobile=mobile,
                password=pwd,
                do_claim=claim_s == "1",
                do_upgrade=up_s == "1",
                note=note,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Bark
# ---------------------------------------------------------------------------

def bark_endpoint() -> Optional[str]:
    url = _env("BARK_URL") or _env("BARK_PUSH")
    key = _env("BARK_KEY") or _env("BARK_DEVICE_KEY")
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
    ep = bark_endpoint()
    if not ep:
        log("📣 未配置 BARK_URL/BARK_KEY，跳过推送")
        return
    if not ep.startswith("http"):
        ep = f"{DEFAULT_BARK.rstrip('/')}/{ep}"
    group = _env("BARK_GROUP") or "FUN矿池"
    payload: dict[str, Any] = {
        "title": title[:200],
        "body": body[:3500],
        "group": group,
    }
    if _env("BARK_SOUND"):
        payload["sound"] = _env("BARK_SOUND")
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
    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": UA,
                "Content-Type": "application/json",
                "Connection": "Keep-Alive",
                "Accept-Encoding": "gzip",
            }
        )
        self.token = ""

    def _headers(self) -> dict[str, str]:
        h = dict(self.session.headers)
        if self.token:
            h["token"] = self.token
        return h

    def login(self, mobile: str, password: str) -> bool:
        url = f"{self.base}/passport/login"
        try:
            r = self.session.post(
                url,
                json={
                    "mobile": mobile,
                    "password": password,
                    "phone": mobile,
                    "device": "",
                    "captcha": "",
                },
                headers=self._headers(),
                timeout=self.timeout,
            )
            ret = r.json()
        except Exception as e:
            log(f"   ❌ 登录网络错误: {e}")
            return False
        if not ret:
            log("   ❌ 登录返回空")
            return False
        if ret.get("code") != 1:
            log(f"   ❌ 登录失败: {ret.get('msg') or ret.get('code')}")
            return False
        ui = (ret.get("data") or {}).get("userinfo") or {}
        token = ui.get("token")
        if not token:
            log("   ❌ 登录无 token")
            return False
        self.token = str(token)
        exp = ui.get("expiretime")
        log(f"   ✅ 登录成功 token={self.token[:18]}…")
        if exp:
            log(f"   ⏰ 过期时间戳: {exp}")
        return True

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


def run_account(acc: Account, base_url: str) -> dict[str, Any]:
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
        "errors": [],
    }
    log("")
    log(f"{'=' * 40}")
    log(f"👤 {acc.label}  ({mask_mobile(acc.mobile)})")
    log(f"   收矿={'开' if acc.do_claim else '关'} | 升级={'开' if acc.do_upgrade else '关'}")

    client = FunClient(base_url)
    if not client.login(acc.mobile, acc.password):
        res["errors"].append("登录失败")
        return res

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

    # 2 查状态
    info = client.mine_info()
    if info is not None:
        res["level"] = info.get("current_level")
        res["claimable"] = info.get("claimable_fu")
        res["upgrade_cost"] = info.get("next_upgrade_cost_fu")
        log(
            f"   ⛏️ 等级 LV{res['level']} | 可领 {_fnum(res['claimable'])} | "
            f"升级费 {_fnum(res['upgrade_cost'])}"
        )
    else:
        res["errors"].append("查询矿机失败")
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
                res["level"] = info2.get("current_level")
                res["claimable"] = info2.get("claimable_fu")
                res["upgrade_cost"] = info2.get("next_upgrade_cost_fu")
                log(
                    f"   ⛏️ 升级后 LV{res['level']} | 可领 {_fnum(res['claimable'])}"
                )
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
            lines.append(f"   🏭 矿机：LV{lv if lv is not None else '?'}")
            lines.append(f"   💎 可领：{claimable}")
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
    elif ok_n == 0:
        lines.append("😿 请检查账号密码 / 网络")
    else:
        lines.append("💡 部分账号见日志")

    return title, "\n".join(lines)


def main() -> int:
    log("🚀 FUN 矿池 mine.py")
    note = _env("FUN_NOTE") or _env("FUN_TAG")
    if note:
        log(f"🏷️ 全局备注: {note}")
    if bark_endpoint():
        log("📣 Bark 已配置")
    else:
        log("📣 未配置 BARK_URL/BARK_KEY")

    base = _env("FUN_BASE_URL") or DEFAULT_BASE
    log(f"🌐 API: {base}")

    accounts = parse_accounts(_env("FUN"))
    if not accounts:
        log("❌ 未配置 FUN")
        log("   格式: 手机号#密码#收矿#升级")
        log("   例: 13800138000#pass#1#0#iPhone")
        log("   多账号用 & 或换行")
        send_bark(f"FUN矿池 ❌" + (f" · {note}" if note else ""), "❌ 未配置环境变量 FUN")
        return 1

    log(f"📋 共 {len(accounts)} 个账号")
    results: list[dict[str, Any]] = []
    for i, acc in enumerate(accounts, 1):
        log(f"\n▶ [{i}/{len(accounts)}]")
        try:
            results.append(run_account(acc, base))
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

    title, body = build_bark(results, note)
    log("")
    log(body)
    send_bark(title, body)
    log("\n🏁 全部完成")
    fail = sum(1 for r in results if not r.get("ok"))
    return 1 if fail else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n⚠️ 中断")
        sys.exit(130)
