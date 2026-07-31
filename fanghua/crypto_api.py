#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""芳华未来 API 加解密与请求封装。

请求：
  - Body: AES/CBC/PKCS5，key=16 位随机字母数字，IV=key 本身
  - X-Api-Sign: RSA/ECB/PKCS1 加密 `timestamp={ts}&aesKey={key}`（服务端公钥）
  - Content-Type: text/plain
  - GET 时参数为 ?data=<aesData>

响应：
  - encryptedKey: 仅 AES key 明文的 RSA 加密（客户端私钥解密）
  - encryptedData: AES 加密的 JSON
"""

from __future__ import annotations

import base64
import json
import random
import string
import time
from typing import Any, Optional
from urllib.parse import urljoin

import requests
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad

# 从 App 原生插件 com.plugin.apisecurity 导出（随 APK 分发）
RSA_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwVjN8e7S9Ygg2jzc+laQ
EYD1YxSRppwUl1fEjfpV8CF/KvQ5IgTcyUYDe3O7/41+i7HjX2ZuwDXPOhhoVy6o
D2e/NS/+XmUYLt9aEzo+erbq2+uxjwK93t0akM5C9xZDa4Ji0M5ICfZMx8pt56fT
IIi5m8C3s7fhh8RSVUp78XK054ZweW25Xe3tQICF6UuuqMAESfTGfhP591hEikbJ
TxUhXfRywjarlwziZyP9waZYu8D0QA7Z84xaDPU1h3kgxb6Gt5DUAdCOg0dMxuiC
24glnUET9yzHa3bIglZMMxpBiGI+B9jDYjKa03IF1NfsQn8eN1n+JlHyeMXtITrg
qQIDAQAB
-----END PUBLIC KEY-----"""

APP_RSA_PRIVATE_KEY_PEM = """-----BEGIN RSA PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDBWM3x7tL1iCDa
PNz6VpARgPVjFJGmnBSXV8SN+lXwIX8q9DkiBNzJRgN7c7v/jX6LseNfZm7ANc86
GGhXLqgPZ781L/5eZRgu31oTOj56turb67GPAr3e3RqQzkL3FkNrgmLQzkgJ9kzH
ym3np9MgiLmbwLezt+GHxFJVSnvxcrTnhnB5bbld7e1AgIXpS66owARJ9MZ+E/n3
WESKRslPFSFd9HLCNquXDOJnI/3Bpli7wPRADtnzjFoM9TWHeSDFvoa3kNQB0I6D
R0zG6ILbiCWdQRP3LMdrdsiCVkwzGkGIYj4H2MNiMprTcgXU1+xCfx43Wf4mUfJ4
xe0hOuCpAgMBAAECggEAdMfOnHJDuUmfjjF0xz/BhND/ZfjmgFuFlGPOtHKftYqF
5MveNk35jRhcwhQFWTV9WaL4UobsHexiXhSf8QidObDQLK/wU9N759O/9B0Z38Tb
1jll5ZsiU5n4kb4DdHpd/nGifbwahundNk9uUp1rSBtNAGZGjqZh8j8B+8IhWpOA
1090lPiqcbnCMueSVF3VghNPAYBYE/VpS1zQnkx54FiS/ojvhZNmW9rSnXtci3fi
QkLOg2GHI5ZTIxbFzOVb1F+TTGxtHcwOddOXz6DuaQmysXEmavcw7PrmeibWhc/J
ggBiBBcYLEUbnDdYIwnPmP+ymaQfxYUv+wQ/fjvgAQKBgQDqBGY8/pMTngWRnipA
S0ciI2to17oor1ovutAjMEEHXmHFeKVCh3NFkd0xscUF4wqqkZm8VdRz9QEANlfR
gy/CRSPTHGxZcBwjwdgr0f946XL5E2RGfNChWjECTSCxxHKktfuIrjDR1bkDIWwY
gpGUncnAL8crn+Iosqlo4YeTSQKBgQDTgl+olhYL6rg3VeiNqbWi30w3+Xn8QOBN
BnpKXBxdsUD/CBqIFyYJnvG3y2yqbNv0JwQijxC7o7VsF72eJYij3zYSufrsU6nI
filMMFpBIy5zJARiGEev3ugbIQyE09BIeizxVmOsZ6exJFhej4UipTr7xTOqulmB
Vtjg8omCYQKBgEcDBL83hQvr5Ma2Vx3heflrBBnxdIUKCPT43FYBO4pv4n1YydUx
YxJWW+fLiPzrU35E5oDXDrwNObuFwgpKo8Bw2JkkQ+Cz+2YCWYWamMppFMFuV/xn
vatowfxvyR8IfL1sl6J3MUtLbnP7vWCGpoSRiPovxWGAh9FPvcacwVY5AoGAOjvf
Eo+gKk/JwJKKoNZlCB7q4U5y450JJKvv56FMvg8bkhwtEeMtueBlNPFxTcsDFEnZ
vZoeRUthnA09S9mRsWy3ephyGbc/O9BglnWJo/2HwHPeMRP2SNnalf2XcMrQwePB
lADxGHrBlOgo3IAva8aKYt98xjjgg9fhhq3AZoECgYEA14vIL+vdzsvgIMT1mNRq
pDOTNEh9STOFPI2qD+UR0GMcPyoqsMb6ySkgPw+Evrx3W+SZASAFDxTFcIWQ2Ok3
ZKzq9nZMNbSerd+lQ7KUmunBORVGatuE1etOWIeXl63G05Rz31ElZBxi03g9/FdP
p5ImE+NFdpN3pOvjTddv7KM=
-----END RSA PRIVATE KEY-----"""

DEFAULT_BASE_URL = "https://api.cdwjyyh.com"
DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 14; PKG110 Build/UKQ1.230924.001; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/139.0.7296.98 "
    "Mobile Safari/537.36 (Immersed/48.0) Html5Plus/1.0"
)
DEFAULT_APP_VERSION = "1.8.1"
DEFAULT_APP_VERSION_CODE = "1810"

_RSA_PUB = RSA.import_key(RSA_PUBLIC_KEY_PEM)
_RSA_PRIV = RSA.import_key(APP_RSA_PRIVATE_KEY_PEM)


def _rand_aes_key(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def _rand_nonce(length: int = 13) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def encrypt_aes(plain: str, key: str) -> str:
    kb = key.encode("utf-8")
    cipher = AES.new(kb, AES.MODE_CBC, iv=kb)
    return base64.b64encode(cipher.encrypt(pad(plain.encode("utf-8"), 16))).decode("ascii")


def decrypt_aes(cipher_b64: str, key: str) -> str:
    kb = key.encode("utf-8")
    cipher = AES.new(kb, AES.MODE_CBC, iv=kb)
    return unpad(cipher.decrypt(base64.b64decode(cipher_b64)), 16).decode("utf-8")


def encrypt_rsa(plain: str) -> str:
    cipher = PKCS1_v1_5.new(_RSA_PUB)
    return base64.b64encode(cipher.encrypt(plain.encode("utf-8"))).decode("ascii")


def decrypt_rsa(cipher_b64: str) -> str:
    cipher = PKCS1_v1_5.new(_RSA_PRIV)
    sentinel = b"__rsa_decrypt_failed__"
    pt = cipher.decrypt(base64.b64decode(cipher_b64), sentinel)
    if pt == sentinel:
        raise ValueError("RSA 解密失败")
    return pt.decode("utf-8")


def hybrid_encrypt(payload: Any, timestamp_ms: str) -> tuple[str, str]:
    """返回 (aesData, rsaSign)。"""
    if payload is None:
        payload = {}
    plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    aes_key = _rand_aes_key()
    aes_data = encrypt_aes(plain, aes_key)
    rsa_sign = encrypt_rsa(f"timestamp={timestamp_ms}&aesKey={aes_key}")
    return aes_data, rsa_sign


def hybrid_decrypt_response(data: dict[str, Any]) -> Any:
    """解密服务端 {encryptedKey, encryptedData} 响应。"""
    if not isinstance(data, dict):
        return data
    if "encryptedKey" not in data or "encryptedData" not in data:
        return data
    key_plain = decrypt_rsa(data["encryptedKey"])
    if "aesKey=" in key_plain:
        aes_key = key_plain.split("aesKey=", 1)[1].split("&", 1)[0]
    else:
        aes_key = key_plain.strip()
    plain = decrypt_aes(data["encryptedData"], aes_key)
    return json.loads(plain)


class FanghuaClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        app_token: str = "",
        device_id: str = "",
        user_agent: str = DEFAULT_UA,
        app_version: str = DEFAULT_APP_VERSION,
        app_version_code: str = DEFAULT_APP_VERSION_CODE,
        platform: str = "android",
        timeout: float = 15.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.app_token = app_token or ""
        self.device_id = device_id or _rand_aes_key(32).upper()
        self.user_agent = user_agent
        self.app_version = app_version
        self.app_version_code = app_version_code
        self.platform = platform
        self.timeout = timeout
        self.session = session or requests.Session()

    def set_token(self, token: str) -> None:
        self.app_token = token or ""

    def _headers(self, timestamp_ms: str, rsa_sign: str) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Content-Type": "text/plain",
            "AppToken": self.app_token or "",
            "liveToken": "",
            "CompanyUserToken": "",
            "X-Api-Timestamp": timestamp_ms,
            "X-Api-Nonce": _rand_nonce(),
            "X-Api-DeviceId": self.device_id,
            "X-Api-Sign": rsa_sign,
            "AppVersion": self.app_version,
            "AppPlatform": self.platform,
            "AppVersionCode": self.app_version_code,
        }

    def request(self, method: str, path: str, data: Any = None) -> dict[str, Any]:
        method = method.upper()
        if data is None:
            data = {}
        ts = str(int(time.time() * 1000))
        aes_data, rsa_sign = hybrid_encrypt(data, ts)
        headers = self._headers(ts, rsa_sign)
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        if method == "GET":
            resp = self.session.get(
                url, headers=headers, params={"data": aes_data}, timeout=self.timeout
            )
        else:
            resp = self.session.request(
                method, url, headers=headers, data=aes_data, timeout=self.timeout
            )
        try:
            body = resp.json()
        except Exception as exc:
            raise RuntimeError(f"非 JSON 响应 HTTP {resp.status_code}: {resp.text[:200]}") from exc
        decoded = hybrid_decrypt_response(body)
        if not isinstance(decoded, dict):
            return {"code": resp.status_code, "data": decoded, "raw": body}
        return decoded

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.request("GET", path, params or {})

    def post(self, path: str, data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.request("POST", path, data or {})

    # -------------------- 业务接口 --------------------

    def login(
        self,
        phone: str,
        password: str,
        jpush_id: str = "",
        source: str = "app",
    ) -> dict[str, Any]:
        """手机号+密码登录，成功后自动写入 AppToken。"""
        payload = {
            "phone": phone,
            "password": password,
            "jpushId": jpush_id or self.device_id,
            "loginType": 1,
            "source": source,
        }
        res = self.post("/app/app/login", payload)
        if res.get("code") == 200 and res.get("token"):
            self.set_token(res["token"])
        return res

    def get_user_info(self) -> dict[str, Any]:
        return self.get("/app/user/getUserInfo", {})

    def create_logs(self, user_id: str | int) -> dict[str, Any]:
        return self.post("/app/common/createLogs", {"userId": str(user_id)})

    def get_app_page_config(self) -> dict[str, Any]:
        return self.get("/app/common/getAppPageConfig", {})

    def sign(self) -> dict[str, Any]:
        return self.post("/app/integral/sign", {})

    def get_video_list(
        self,
        page_num: int = 1,
        page_size: int = 10,
        is_random: int = 1,
        keyword: str = "",
        video_id: str = "",
    ) -> dict[str, Any]:
        return self.get(
            "/app/video/getVideoList-new",
            {
                "keyword": keyword,
                "isRandom": is_random,
                "videoId": video_id,
                "pageNum": page_num,
                "pageSize": page_size,
            },
        )

    def track_video(self, video_id: str | int, event: str) -> dict[str, Any]:
        return self.post("/app/video/track", {"videoId": str(video_id), "event": event})

    def add_integral(self, type_: int = 2, video_id: str | int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"type": type_}
        if video_id is not None and type_ == 2:
            body["videoId"] = str(video_id)
        return self.post("/app/integral/addIntegral", body)

    def heartbeat(self, action: str = "HEARTBEAT") -> dict[str, Any]:
        return self.post("/app/portrait/heartbeat", {"action": action})
