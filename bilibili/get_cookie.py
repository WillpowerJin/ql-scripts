#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B 站扫码获取 Cookie（青龙 / 本地）—— 可独立运行，不依赖 daily.py

cron: 手动运行（Cookie 失效时）
new Env('B站获取Cookie');

用法：
  python3 -u get_cookie.py
  python3 -u get_cookie.py --account 备注名
  python3 -u get_cookie.py --list          # 只列出已缓存账号
  python3 -u get_cookie.py --timeout 180

环境变量：
  BILI_NAME / BILI_COOKIE_FILE
  BARK_URL / BARK_KEY / BARK_GROUP

依赖：requests
  可选：qrcode + Pillow（终端 ASCII / 本地 PNG 二维码）

Cookie 路径（与 daily.py 约定一致）：
  1) BILI_COOKIE_FILE
  2) 青龙 /ql/data/bilibili_cookie_cache.json
  3) 本文件同目录 cookie_cache.json
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

os.environ.setdefault("PYTHONUNBUFFERED", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)  # type: ignore[attr-defined]
except Exception:
    pass

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
APPKEY = "27eb53fc9058f8c3"
APPSEC = "c2ed53a74eeefe3cf99fbd01d8c9c375"
DEFAULT_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_4_1 like Mac OS X) "
    "AppleWebKit/621.1.15.10.7 (KHTML, like Gecko) Mobile/22E252 "
    "BiliApp/84400100 os/ios model/iPhone mobi_app/iphone build/84400100"
)
DEFAULT_BARK_SERVER = "https://api.day.app"
QR_PNG_PATH = SCRIPT_DIR / "login_qr.png"
QR_HTML_PATH = SCRIPT_DIR / "login_qr.html"

try:
    import requests
except ImportError:
    print(
        "❌ 缺少 requests，请安装: pip install requests\n"
        "   青龙：依赖管理 → requests",
        flush=True,
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def emit(msg: str = "") -> None:
    line = "\n" if msg == "" else (msg if msg.endswith("\n") else msg + "\n")
    try:
        sys.stdout.write(line)
        sys.stdout.flush()
    except Exception:
        pass
    in_ql = bool(
        os.environ.get("QL_DIR")
        or os.environ.get("QL_DATA_DIR")
        or Path("/ql/data").is_dir()
    )
    if in_ql:
        try:
            sys.stderr.write(line)
            sys.stderr.flush()
        except Exception:
            pass


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def app_sign(params: dict[str, Any]) -> dict[str, str]:
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
    for k, v in d.items():
        if k not in keys and v:
            parts.append(f"{k}={v}")
    return "; ".join(parts)


def _mid_from_cookie(cookie: str) -> str:
    return str(parse_cookie(cookie).get("DedeUserID") or "").strip()


# ---------------------------------------------------------------------------
# Cookie 缓存路径 / 读写（与 daily 约定一致，可供 daily import）
# ---------------------------------------------------------------------------

def resolve_cache_path() -> Path:
    env = _env("BILI_COOKIE_FILE") or _env("BILI_COOKIE_CACHE")
    if env:
        return Path(env).expanduser()
    ql_data = _env("QL_DATA_DIR")
    if ql_data:
        return Path(ql_data) / "bilibili_cookie_cache.json"
    if Path("/ql/data").is_dir():
        return Path("/ql/data/bilibili_cookie_cache.json")
    return SCRIPT_DIR / "cookie_cache.json"


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
    emit(f"[*] Cookie 已写入: {path}")


def find_cache_key_by_mid(mid: str) -> Optional[str]:
    mid = str(mid or "").strip()
    if not mid:
        return None
    for key, ent in (load_cache().get("accounts") or {}).items():
        if not isinstance(ent, dict):
            continue
        if str(ent.get("mid") or "").strip() == mid:
            return str(key)
        if _mid_from_cookie(str(ent.get("cookie") or "")) == mid:
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
    """按 mid 去重写入。返回 (storage_key, 'new'|'update')。"""
    mid = str(mid or _mid_from_cookie(cookie) or "").strip()
    uname = str(uname or "").strip()
    preferred_name = str(preferred_name or "").strip()
    if preferred_name in ("主号", "扫码待识别", "account", "account_1"):
        preferred_name = ""

    data = load_cache()
    accounts: dict[str, Any] = data.setdefault("accounts", {})
    existing_key = find_cache_key_by_mid(mid) if mid else None

    if existing_key:
        key = preferred_name or existing_key
        if preferred_name and preferred_name != existing_key:
            if existing_key in accounts and preferred_name not in accounts:
                accounts[preferred_name] = accounts.pop(existing_key)
            key = preferred_name
        elif not preferred_name and uname and existing_key in (
            "主号",
            "扫码待识别",
            mid,
            "account",
        ):
            if uname != existing_key and uname not in accounts:
                accounts[uname] = accounts.pop(existing_key)
                key = uname
            else:
                key = existing_key
        action = "update"
    else:
        key = preferred_name or uname or mid or f"account_{len(accounts) + 1}"
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


@dataclass
class CachedAccount:
    name: str
    cookie: str = ""
    access_token: str = ""
    mid: str = ""
    uname: str = ""


def list_cached_accounts() -> list[CachedAccount]:
    out: list[CachedAccount] = []
    for key, ent in (load_cache().get("accounts") or {}).items():
        if not isinstance(ent, dict):
            continue
        ck = str(ent.get("cookie") or "").strip()
        if not ck:
            continue
        uname = str(ent.get("uname") or "").strip()
        mid = str(ent.get("mid") or "") or _mid_from_cookie(ck)
        out.append(
            CachedAccount(
                name=uname or str(key),
                cookie=ck,
                access_token=str(ent.get("access_token") or ""),
                mid=mid,
                uname=uname,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------

@dataclass
class NotifyConfig:
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = "B站"


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
        bark_group=_env("BARK_GROUP", "B站"),
    )


def send_notify(cfg: NotifyConfig, title: str, body: str) -> None:
    if not (cfg.bark_url or cfg.bark_key):
        return
    try:
        if cfg.bark_url:
            url = cfg.bark_url.rstrip("/")
            if cfg.bark_key and cfg.bark_key not in url:
                push = f"{url}/{cfg.bark_key}/{quote(title)}/{quote(body)}"
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
        requests.get(push, params=params or None, timeout=10)
    except Exception as e:
        emit(f"[!] Bark 失败: {e}")


# ---------------------------------------------------------------------------
# 二维码展示
# ---------------------------------------------------------------------------

def show_login_qr(auth_url: str) -> str:
    """打印 ASCII 二维码 + 图片链接。返回在线图片 URL。"""
    online_img = (
        "https://api.qrserver.com/v1/create-qr-code/?size=320x320&data="
        + quote(auth_url, safe="")
    )
    emit("")
    emit("=" * 48)
    emit("  请用【手机哔哩哔哩 App】扫一扫 -> 扫下方二维码")
    emit("  不要用电脑浏览器打开登录链接本身")
    emit("  约 2～3 分钟有效，确认后脚本自动继续")
    emit("=" * 48)
    emit("")

    printed = False
    try:
        import qrcode  # type: ignore

        qr = qrcode.QRCode(border=1, box_size=1)
        qr.add_data(auth_url)
        qr.make(fit=True)
        print("", flush=True)
        qr.print_ascii(invert=True)
        print("", flush=True)
        printed = True
        emit("[OK] 上方为登录二维码（手机对着日志/屏幕扫）")
    except Exception as e:
        emit(f"[!] 终端画码失败（可选: pip install qrcode Pillow）: {e}")

    emit("")
    emit("[*] 二维码图片链接（可点开再扫 / Bark）：")
    emit(online_img)
    emit("")

    try:
        import qrcode  # type: ignore

        img = qrcode.make(auth_url)
        img.save(QR_PNG_PATH)
        emit(f"[*] 本地图片: {QR_PNG_PATH}")
        b64 = base64.b64encode(QR_PNG_PATH.read_bytes()).decode("ascii")
        html = f"""<!DOCTYPE html><html><head><meta charset=utf-8>
<title>B站扫码</title></head><body style="text-align:center;background:#111;color:#eee">
<h1>B站扫码登录</h1>
<img src="data:image/png;base64,{b64}" style="background:#fff;padding:12px"/>
</body></html>"""
        QR_HTML_PATH.write_text(html, encoding="utf-8")
        emit(f"[*] 本地网页: file://{QR_HTML_PATH}")
    except Exception:
        pass

    if not printed:
        emit("[*] 请打开上方图片链接再扫")
    emit("")
    return online_img


# ---------------------------------------------------------------------------
# 扫码登录
# ---------------------------------------------------------------------------

def fetch_nav(session: requests.Session, cookie: str, ua: str = DEFAULT_UA) -> dict[str, Any]:
    try:
        r = session.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers={"User-Agent": ua, "Cookie": cookie},
            timeout=20,
        )
        return r.json()
    except Exception as e:
        return {"code": -1, "message": str(e)}


def qr_login(
    preferred_name: str = "",
    *,
    timeout_sec: int = 180,
    interval: float = 3.0,
    notify: Optional[NotifyConfig] = None,
    on_qr: Optional[Any] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    TV 扫码登录。
    返回 (ok, storage_key, info)  info 含 uname/mid/cookie/access_token/action
    """
    notify = notify or NotifyConfig()
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": DEFAULT_UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
    )

    body = app_sign(
        {
            "appkey": APPKEY,
            "local_id": 0,
            "ts": int(time.time()),
            "mobi_app": "iphone",
        }
    )
    try:
        r = session.post(
            "https://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code",
            data=body,
            timeout=20,
        )
        resp = r.json()
    except Exception as e:
        emit(f"[!] 请求二维码失败: {e}")
        return False, "", {}

    if resp.get("code") != 0:
        emit(f"[!] 获取二维码失败: {resp.get('message')}")
        return False, "", {}

    data = resp.get("data") or {}
    auth_code = data.get("auth_code")
    url = data.get("url") or ""
    if not auth_code:
        emit("[!] auth_code 为空")
        return False, "", {}
    if not url:
        url = (
            "https://passport.bilibili.com/x/passport-tv-login/h5/qrcode/auth"
            f"?auth_code={auth_code}&mobi_app=iphone"
        )

    emit("[*] 已拿到 auth，输出二维码…")
    online_img = show_login_qr(url)
    if on_qr:
        try:
            on_qr(url, online_img)
        except Exception as e:
            emit(f"[!] on_qr 回调: {e}")

    if notify.bark_url or notify.bark_key:
        send_notify(
            notify,
            "B站扫码获取Cookie",
            f"请用手机 B 站扫码\n图片：{online_img}\n保存：{resolve_cache_path()}",
        )
        try:
            key = notify.bark_key
            base = (notify.bark_url or notify.bark_server).rstrip("/")
            if key and key not in base:
                push = f"{base}/{key}"
            else:
                push = base
            requests.get(
                f"{push}/{quote('B站扫码')}/{quote('点开图片或看日志二维码')}",
                params={"url": online_img, "group": notify.bark_group or "B站"},
                timeout=10,
            )
            emit("[*] Bark 已推送")
        except Exception as e:
            emit(f"[!] Bark 推送: {e}")
    else:
        emit("[*] 未配置 Bark，仅日志二维码")

    poll_times = max(20, int(timeout_sec / interval))
    emit(f"[*] 等待扫码确认（约 {timeout_sec}s）…")

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
        try:
            pr = session.post(
                "https://passport.bilibili.com/x/passport-tv-login/qrcode/poll",
                data=poll_body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
                },
                timeout=20,
            )
            poll = pr.json()
        except Exception as e:
            emit(f"[!] 轮询网络错误: {e}")
            continue

        code = poll.get("code")
        if code == 0:
            pdata = poll.get("data") or {}
            access_token = str(pdata.get("access_token") or "")
            cookie_info = pdata.get("cookie_info") or {}
            jar: dict[str, str] = {}
            for c in cookie_info.get("cookies") or []:
                if isinstance(c, dict) and c.get("name"):
                    jar[str(c["name"])] = str(c.get("value") or "")
            if not jar.get("SESSDATA"):
                emit(f"[!] 扫码成功但无 SESSDATA: {str(poll)[:280]}")
                return False, "", {}

            ck = cookie_header(jar)
            mid = jar.get("DedeUserID") or ""
            uname = ""
            nav = fetch_nav(session, ck)
            if nav.get("code") in (0, "0"):
                ud = nav.get("data") or {}
                uname = str(ud.get("uname") or "")
                mid = str(ud.get("mid") or mid)

            key, action = cache_upsert(
                ck,
                access_token,
                preferred_name=preferred_name,
                mid=str(mid),
                uname=uname,
            )
            for p in (QR_PNG_PATH, QR_HTML_PATH):
                try:
                    if p.is_file():
                        p.unlink()
                except OSError:
                    pass

            info = {
                "uname": uname,
                "mid": str(mid),
                "cookie": ck,
                "access_token": access_token,
                "action": action,
                "key": key,
            }
            return True, key, info

        if code == 86038:
            emit("[!] 二维码已失效，请重跑脚本")
            return False, "", {}
        if code in (86039, 86090):
            emit(f"[*] 等待确认… ({i + 1}/{poll_times}) {poll.get('message')}")
            continue
        emit(f"[!] 轮询 code={code} msg={poll.get('message')}")

    emit("[!] 扫码超时")
    return False, "", {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_list() -> int:
    path = resolve_cache_path()
    accs = list_cached_accounts()
    emit(f"Cookie 文件: {path}")
    emit(f"共 {len(accs)} 个账号")
    for a in accs:
        emit(f"  - {a.name}  mid={a.mid or '?'}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="B 站扫码获取 Cookie（独立脚本）")
    ap.add_argument("--account", default="", help="备注名；默认用 B 站昵称")
    ap.add_argument("--timeout", type=int, default=180, help="等待扫码秒数")
    ap.add_argument("--list", action="store_true", help="列出已缓存账号后退出")
    args = ap.parse_args(argv)

    emit("")
    emit("=" * 44)
    emit("  Bilibili get_cookie  (独立版，无需 daily.py)")
    emit("=" * 44)
    emit(f"python={sys.version.split()[0]}")
    emit(f"file={__file__}")
    emit("")

    if args.list:
        return cmd_list()

    notify = load_notify_from_env()
    if notify.bark_url or notify.bark_key:
        emit("[*] Bark 已配置")
    else:
        emit("[*] 未配置 BARK_URL/BARK_KEY")

    name = (args.account or _env("BILI_NAME")).strip()
    if name:
        emit(f"[*] 指定备注: {name}（同 mid 会更新不重复）")
    else:
        emit("[*] 未指定备注：将用 B 站昵称建档（推荐多账号）")

    cache = resolve_cache_path()
    existing = list_cached_accounts()
    emit(f"[*] Cookie 文件: {cache}")
    emit(f"[*] 当前已缓存 {len(existing)} 个账号:")
    if existing:
        for a in existing:
            emit(f"    - {a.name}" + (f"  mid={a.mid}" if a.mid else ""))
    else:
        emit("    （暂无）")
    emit("")
    emit("步骤: 手机 哔哩哔哩 -> 扫一扫 -> 扫日志二维码 -> 确认")
    emit("换号再扫=新增；同一号再扫=更新 Cookie")
    emit("")

    t0 = time.time()
    ok, key, info = qr_login(
        preferred_name=name,
        timeout_sec=args.timeout,
        notify=notify,
    )
    if not ok:
        emit("")
        emit("获取失败：超时或二维码失效，请重跑")
        emit("")
        send_notify(notify, "B站Cookie获取失败", "扫码超时或失败，请重试")
        return 1

    uname = info.get("uname") or key
    mid = info.get("mid") or ""
    action = info.get("action") or ""
    all_now = list_cached_accounts()
    elapsed = int(time.time() - t0)

    emit("")
    emit("=" * 44)
    emit("  OK  Cookie 获取成功" + (f"  ({action})" if action else ""))
    emit("=" * 44)
    emit(f"用户昵称: {uname}" + (f"  mid={mid}" if mid else ""))
    emit(f"缓存键: {key}")
    emit(f"保存: {cache}")
    emit(f"耗时: 约 {elapsed}s")
    emit(f"缓存共 {len(all_now)} 个账号:")
    for a in all_now:
        mark = " <- 本次" if a.name == uname or a.name == key else ""
        emit(f"    - {a.name}{mark}")
    emit("")
    emit("本脚本可单独使用。若要用 daily.py 做每日任务，")
    emit("请把 daily.py 放同目录或同一 Cookie 路径（BILI_COOKIE_FILE）。")
    emit("")

    send_notify(
        notify,
        "B站Cookie获取成功",
        f"用户：{uname} mid={mid}\n缓存共 {len(all_now)} 个号\n{cache}",
    )
    return 0


if __name__ == "__main__":
    try:
        emit("[get_cookie] start")
        code = main()
        emit(f"[get_cookie] exit={code}")
        sys.exit(code)
    except SystemExit:
        raise
    except Exception as e:
        emit(f"未捕获异常: {type(e).__name__}: {e}")
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)
