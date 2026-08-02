# 当前脚本来自于  http://ql.xmox.cn 脚本库下载！
# 脚本库官方QQ群：1079418419
# 脚本库中的所有脚本文件均来自热心网友上传和互联网收集。
# 脚本库仅提供文件上传和下载服务，不提供脚本文件的审核。
# 您在使用脚本库下载的脚本时自行检查判断风险。
# 所涉及到的 账号安全、数据泄露、设备故障、软件违规封禁、财产损失等问题及法律风险，与脚本库无关！均由开发者、上传者、使用者自行承担。

#!/usr/bin/env python3
"""
多象签到本，每天几毛，1起提
环境变量DX，值手机号#密码，多账号用 @ 隔开
例如：18812345678#123456@18812345678#123456
注册链接：https://dx.qqdd.top/i/fWT7zC
定时规则：0 10 * * *
可选 DX_WITHDRAW=0 关闭自动提现（默认开启）
流程：登录 → 签到 → 领取昨天/前天活跃收益 → 整元自动提现
"""

import hashlib
import hmac
import json
import os
import random
import secrets
import time
import urllib.parse
import sys

import requests

# ---------- 签名算法 ----------
_OBF_BYTES = [0x39, 0x28, 0x32, 0x25, 0x34, 0x3c, 0x33, 0x3a, 0x2, 0x3c, 0x33,
              0x39, 0x2f, 0x32, 0x34, 0x39, 0x2, 0x2f, 0x38, 0x2c, 0x28, 0x38,
              0x2e, 0x29, 0x2, 0x2e, 0x34, 0x3a, 0x33, 0x2, 0x2b, 0x6c]
SECRET = ''.join(chr(b ^ 0x5d) for b in _OBF_BYTES)
assert SECRET == "duoxiang_android_request_sign_v1"

def _nonce() -> str:
    return ''.join(format(secrets.randbelow(256), '02x') for _ in range(8))

def _stable_json(obj) -> str:
    """稳定JSON：递归按键排序后序列化，使用紧凑格式（无空格）"""
    def normalize(o):
        if isinstance(o, dict):
            return {k: normalize(v) for k, v in sorted(o.items())}
        if isinstance(o, list):
            return [normalize(x) for x in o]
        return o
    # 关键修改：separators 改为 (',', ':') 紧凑格式
    return json.dumps(normalize(obj), separators=(',', ':'), ensure_ascii=False)

def _body_hash(body) -> str:
    if body is None:
        return ""
    return hashlib.sha256(_stable_json(body).encode('utf-8')).hexdigest()

def _canonical_query(params) -> str:
    if not isinstance(params, dict) or not params:
        return ""
    items = sorted(params.items(), key=lambda kv: (kv[0], kv[1]))
    return "&".join(
        f"{urllib.parse.quote(str(k), safe='')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in items
    )

def _token(headers) -> str:
    auth = (headers or {}).get("Authorization")
    if not auth:
        return ""
    auth = auth.strip()
    if auth.startswith("Bearer "):
        return auth[7:]
    return ""

DEBUG = os.environ.get("DEBUG", "").lower() in ("true", "1", "yes")
AUTO_WITHDRAW = os.environ.get("DX_WITHDRAW", "1").lower() not in ("0", "false", "no", "off")
WITHDRAW_UNIT_FEN = 100
WITHDRAW_MIN_FEN = 100

def sign(method: str, url: str, headers: dict, body=None, params=None) -> dict:
    timestamp = str(int(time.time() * 1000))
    nonce = _nonce()
    uri = urllib.parse.urlparse(url)
    path = uri.path or "/"

    token = _token(headers)
    device_id = ((headers or {}).get("X-Device-Id") or "").strip()

    parts = [
        "android",
        timestamp,
        nonce,
        method.upper(),
        path,
        _canonical_query(params),
        _body_hash(body),
        token,
        device_id,
    ]
    signing_string = "\n".join(parts)
    mac = hmac.new(SECRET.encode('utf-8'), signing_string.encode('utf-8'), hashlib.sha256)
    x_sign = mac.hexdigest()

    if DEBUG:
        print(f"=== 调试信息 ===")
        print(f"签名串各部分 (用换行连接):")
        for i, p in enumerate(parts):
            print(f"  [{i}] {repr(p)}")
        print(f"完整签名串:\n{signing_string}")
        print(f"计算出的 X-Sign: {x_sign}")
        print(f"================")

    return {
        "X-Client-Type": "android",
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Sign": x_sign,
    }

# ---------- 业务逻辑 ----------
BASE_URL = "https://dx.qqdd.top"
DEVICE_ID = "25C1D83B333A1393"

COMMON_HEADERS = {
    "User-Agent": "Dart/3.11 (dart:io)",
    "Accept-Encoding": "gzip",
    "Version": "1.8.2",
    "VersionCode": "182",
    "X-Device-Os-Version": "9",
    "X-Device-Resolution": "1080x2256",
    "X-Device-Os-Name": "Android",
    "X-Device-Name": "10X",
    "X-Device-Platform": "android",
    "X-Device-Brand": "XIAOMI",
    "X-Device-Manufacturer": "XIAOMI",
    "X-Device-Id": DEVICE_ID,
    "Content-Type": "application/json",
}

def login(phone: str, password: str):
    url = f"{BASE_URL}/api/user/login"
    body = {"phone": phone, "password": password}
    headers = COMMON_HEADERS.copy()
    sig_headers = sign("POST", url, headers, body=body)
    headers.update(sig_headers)

    try:
        resp = requests.post(url, json=body, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"[登录HTTP错误] {phone}，状态码: {resp.status_code}, 响应: {resp.text[:200]}")
            return None
        data = resp.json()
        if data.get("status") is True:
            token = data.get("results", {}).get("token")
            if token:
                print(f"[登录成功] {phone}")
                return token
            else:
                print(f"[登录失败] {phone}，响应中无 token: {data}")
        else:
            print(f"[登录失败] {phone}，msg: {data.get('message')}")
        return None
    except Exception as e:
        print(f"[登录异常] {phone}: {e}")
        return None

def checkin(token: str, phone: str):
    url = f"{BASE_URL}/api/growth/checkin"
    headers = COMMON_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    sig_headers = sign("POST", url, headers, body=None)
    headers.update(sig_headers)

    try:
        resp = requests.post(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"[签到HTTP错误] {phone}，状态码: {resp.status_code}, 响应: {resp.text[:200]}")
            return False
        data = resp.json()
        if data.get("status") is True:
            msg = data.get("message", "")
            results = data.get("results", {})
            points = results.get("rewardPoints", 0)
            streak = results.get("streakDays", 0)
            print(f"[签到成功] {phone}: {msg}，今日获得 {points} 积分，连续签到 {streak} 天")
            return True
        else:
            print(f"[签到失败] {phone}: {data.get('message')}")
            return False
    except Exception as e:
        print(f"[签到异常] {phone}: {e}")
        return False


def invite_overview(token: str, phone: str):
    """GET /api/invite/overview，返回 results 或 None。"""
    url = f"{BASE_URL}/api/invite/overview"
    headers = COMMON_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    sig_headers = sign("GET", url, headers, body=None)
    headers.update(sig_headers)
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"[邀请概览HTTP错误] {phone}，状态码: {resp.status_code}, 响应: {resp.text[:200]}")
            return None
        data = resp.json()
        if data.get("status") is True:
            return data.get("results") or {}
        print(f"[邀请概览失败] {phone}: {data.get('message')}")
        return None
    except Exception as e:
        print(f"[邀请概览异常] {phone}: {e}")
        return None


def claim_active_reward(token: str, phone: str, offset_days: int):
    """POST /api/invite/active-reward/claim 领取昨天(1)/前天(2)活跃奖。"""
    url = f"{BASE_URL}/api/invite/active-reward/claim"
    body = {"offsetDays": int(offset_days)}
    label = {1: "昨天", 2: "前天"}.get(int(offset_days), f"offsetDays={offset_days}")
    headers = COMMON_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    sig_headers = sign("POST", url, headers, body=body)
    headers.update(sig_headers)
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(
                f"[领取{label}HTTP错误] {phone}，状态码: {resp.status_code}, "
                f"响应: {resp.text[:200]}"
            )
            return False
        data = resp.json()
        msg = data.get("message", "")
        if data.get("status") is True:
            results = data.get("results") or {}
            amount = results.get("amount")
            balance = results.get("balance")
            parts = []
            if amount is not None:
                try:
                    parts.append(f"到账 {float(amount) / 100:.2f} 元")
                except (TypeError, ValueError):
                    parts.append(f"到账 {amount}")
            if balance is not None:
                try:
                    parts.append(f"余额 {float(balance) / 100:.2f} 元")
                except (TypeError, ValueError):
                    parts.append(f"余额 {balance}")
            extra = ("，" + "，".join(parts)) if parts else ""
            print(f"[领取{label}成功] {phone}: {msg}{extra}")
            return True
        print(f"[领取{label}] {phone}: {msg}")
        return False
    except Exception as e:
        print(f"[领取{label}异常] {phone}: {e}")
        return False


def claim_yesterday_income(token: str, phone: str):
    """自动领取昨天（及仍可领的前天）活跃收益。"""
    overview = invite_overview(token, phone)
    if overview is None:
        return False

    stats = overview.get("stats") or []
    targets = [s for s in stats if s.get("canClaim") is True]
    if not targets:
        targets = [
            s
            for s in stats
            if int(s.get("offsetDays") or -1) in (1, 2)
            and s.get("rewardPaid") is not True
            and float(s.get("totalRewardAmount") or 0) > 0
        ]

    if not targets:
        yest = next((s for s in stats if int(s.get("offsetDays") or -1) == 1), None)
        if yest is not None:
            paid = yest.get("rewardPaid")
            reward = yest.get("reward")
            if paid is True:
                print(f"[领取收益] {phone}: 昨天收益已领取（{reward}）")
            else:
                print(f"[领取收益] {phone}: 昨天暂无可领（{reward}）")
        else:
            print(f"[领取收益] {phone}: 暂无可领取的活跃奖")
        return False

    ok_any = False
    for s in sorted(targets, key=lambda x: int(x.get("offsetDays") or 99)):
        od = int(s.get("offsetDays") or 0)
        if od not in (1, 2):
            continue
        label = s.get("label") or ({1: "昨天", 2: "前天"}.get(od, str(od)))
        reward = s.get("reward")
        print(f"[领取收益] {phone}: 准备领取{label}（{reward}）...")
        if claim_active_reward(token, phone, od):
            ok_any = True
        time.sleep(random.uniform(1.0, 2.5))
    return ok_any


def get_profile(token: str, phone: str):
    url = f"{BASE_URL}/api/user/profile"
    headers = COMMON_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    sig_headers = sign("GET", url, headers, body=None)
    headers.update(sig_headers)
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"[资料HTTP错误] {phone}，状态码: {resp.status_code}, 响应: {resp.text[:200]}")
            return None
        data = resp.json()
        if data.get("status") is True:
            return data.get("results") or {}
        print(f"[资料失败] {phone}: {data.get('message')}")
        return None
    except Exception as e:
        print(f"[资料异常] {phone}: {e}")
        return None


def withdraw_balance(token: str, phone: str, amount_fen: int):
    """POST /api/balance/withdraw，amount 单位为分，须为整元。"""
    url = f"{BASE_URL}/api/balance/withdraw"
    body = {"amount": int(amount_fen)}
    yuan = int(amount_fen) / 100
    headers = COMMON_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    sig_headers = sign("POST", url, headers, body=body)
    headers.update(sig_headers)
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"[提现HTTP错误] {phone}，状态码: {resp.status_code}, 响应: {resp.text[:200]}")
            return False
        data = resp.json()
        msg = data.get("message", "")
        if data.get("status") is True:
            results = data.get("results") or {}
            wno = results.get("withdrawNo") or results.get("orderNo") or ""
            extra = f"，单号 {wno}" if wno else ""
            print(f"[提现成功] {phone}: {msg}，提现 {yuan:.2f} 元{extra}")
            return True
        print(f"[提现失败] {phone}: {msg}")
        return False
    except Exception as e:
        print(f"[提现异常] {phone}: {e}")
        return False


def auto_withdraw(token: str, phone: str):
    """余额按整元自动提现（最低 1 元）；需已绑定支付宝与实名。"""
    if not AUTO_WITHDRAW:
        print(f"[提现] {phone}: 已关闭（DX_WITHDRAW=0）")
        return False

    profile = get_profile(token, phone)
    if profile is None:
        return False

    try:
        balance = int(profile.get("balance") or 0)
    except (TypeError, ValueError):
        balance = 0
    alipay = (profile.get("alipayAccount") or "").strip()
    real_name = (profile.get("personalVerifiedName") or profile.get("realName") or "").strip()
    amount = (balance // WITHDRAW_UNIT_FEN) * WITHDRAW_UNIT_FEN

    print(
        f"[提现] {phone}: 余额 {balance / 100:.2f} 元，"
        f"支付宝={alipay or '未绑定'}，实名={real_name or '未认证'}"
    )
    if not alipay:
        print(f"[提现] {phone}: 未绑定支付宝，跳过")
        return False
    if not real_name:
        print(f"[提现] {phone}: 未实名认证，跳过")
        return False
    if amount < WITHDRAW_MIN_FEN:
        print(f"[提现] {phone}: 不足 1 元整，跳过（零头 {balance % 100} 分保留）")
        return False

    print(f"[提现] {phone}: 申请提现 {amount / 100:.2f} 元（整元，零头保留）...")
    return withdraw_balance(token, phone, amount)


def main():
    dx_env = os.environ.get("DX", "")
    if not dx_env:
        print("错误：未设置环境变量 DX，请设置手机号#密码，多账号用 @ 隔开")
        sys.exit(1)

    accounts = []
    for item in dx_env.split("@"):
        item = item.strip()
        if not item:
            continue
        if "#" not in item:
            print(f"警告：账号格式错误（缺少 #），跳过: {item}")
            continue
        phone, pwd = item.split("#", 1)
        accounts.append((phone.strip(), pwd.strip()))

    if not accounts:
        print("没有有效的账号，退出")
        sys.exit(1)

    print(f"共 {len(accounts)} 个账号待处理")
    print(f"[提现] 自动提现={'开' if AUTO_WITHDRAW else '关'}（整元，最低 1 元）")

    for idx, (phone, pwd) in enumerate(accounts, 1):
        print(f"\n===== 处理第 {idx}/{len(accounts)} 个账号: {phone} =====")

        token = login(phone, pwd)
        if not token:
            time.sleep(random.uniform(2, 5))
            continue

        delay_login = random.uniform(5, 10)
        print(f"登录成功，等待 {delay_login:.1f} 秒后签到...")
        time.sleep(delay_login)

        checkin(token, phone)

        delay_claim = random.uniform(2, 5)
        print(f"签到完成，等待 {delay_claim:.1f} 秒后领取昨日收益...")
        time.sleep(delay_claim)
        claim_yesterday_income(token, phone)

        delay_wd = random.uniform(2, 4)
        print(f"等待 {delay_wd:.1f} 秒后尝试提现...")
        time.sleep(delay_wd)
        auto_withdraw(token, phone)

        if idx < len(accounts):
            delay_next = random.uniform(30, 60)
            print(f"等待 {delay_next:.1f} 秒后处理下一个账号...")
            time.sleep(delay_next)

    print("\n所有账号处理完毕！")

if __name__ == "__main__":
    main()
    
# === 脚本来自于 http://ql.xmox.cn 脚本库 ===
