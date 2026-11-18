# 当前脚本来自于  http://ql.xmox.cn 脚本库下载！
# 脚本库官方QQ群：1079418419
# 脚本库中的所有脚本文件均来自热心网友上传和互联网收集。
# 脚本库仅提供文件上传和下载服务，不提供脚本文件的审核。
# 您在使用脚本库下载的脚本时自行检查判断风险。
# 所涉及到的 账号安全、数据泄露、设备故障、软件违规封禁、财产损失等问题及法律风险，与脚本库无关！均由开发者、上传者、使用者自行承担。

#!/usr/bin/env python3
# new Env("范清录-看广告")
# cron: 0 9 * * *
"""
环境变量 SJLM
格式：账号#密码#账号#密码
注册地址：http://c.fanqinglu.xyz/#/?inviteCode=tCC2wP
注册实名好了在跑脚本，目前内测，上线一个币8块钱一个
每个账号每日执行3次广告上报，每次间隔20秒
"""
import requests
import os
import time

session = requests.Session()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 16; V2426A Build/BP2A.250605.031.A3_V000L1; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/134.0.6998.135 Mobile Safari/537.36  XiaoMi/MiuiBrowser/10.8.1 LT-APP/48/104/YM-RT/",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "http://c.fanqinglu.xyz:8001",
    "X-Requested-With": "com.plw.alllove.sjlmgg",
    "Referer": "http://c.fanqinglu.xyz:8001/",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "token": ""
}
BASE_URL = "http://c.fanqinglu.xyz:8001"
DAILY_AD_TIMES = 3
SLEEP_INTERVAL = 20


def login(account: str, password: str):
    url = f"{BASE_URL}/api/user/login"
    payload = {
        "loginType": 1,
        "account": account,
        "password": password
    }
    login_header = HEADERS.copy()
    login_header["Content-Type"] = "application/json"
    resp = session.post(url, json=payload, headers=login_header, timeout=15)
    res_json = resp.json()
    code = res_json.get("code")
    if code == "200":
        token_val = res_json["data"]["tokenValue"]
        print(f"✅账号 {account} 登录成功")
        return token_val
    else:
        print(f"❌账号 {account} 登录失败 {res_json}")
        return None


def watch_ads(token: str):
    headers = HEADERS.copy()
    headers["token"] = token
    url = f"{BASE_URL}/api/user/watchAds"
    resp = session.post(url, headers=headers, data="", timeout=15)
    res_json = resp.json()
    if res_json.get("code") == "200" and res_json.get("data") == 1:
        print(f"🎁广告上报成功，奖励已发放")
        return True
    else:
        print(f"⚠️广告上报结果: {res_json}")
        return False


def main():
    env_data = os.getenv("SJLM", "")
    if not env_data:
        print("请配置环境变量 SJLM")
        return
    parts = env_data.split("#")
    accounts = []
    for i in range(0, len(parts), 2):
        if i + 1 >= len(parts):
            break
        acc = parts[i].strip()
        pwd = parts[i+1].strip()
        accounts.append((acc, pwd))
    print(f"📋载入账号 {len(accounts)} 个，每个账号每日执行{DAILY_AD_TIMES}次广告上报")
    for acc, pwd in accounts:
        print(f"\n====账号 {acc}====")
        token = login(acc, pwd)
        if not token:
            continue
        for idx in range(1, DAILY_AD_TIMES + 1):
            print(f"\n---第 {idx}/{DAILY_AD_TIMES} 次广告上报---")
            watch_ads(token)
            if idx < DAILY_AD_TIMES:
                print(f"⏳等待 {SLEEP_INTERVAL} 秒后执行下一次")
                time.sleep(SLEEP_INTERVAL)
        time.sleep(5)


if __name__ == "__main__":
    main()

# === 脚本来自于 http://ql.xmox.cn 脚本库 ===
