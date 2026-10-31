#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""京东签到任务实现。

转写自 LazingLuo/LazingLuo_Loon-Rules 仓库（2026-10-31 仍在更新）的可读源码：
  Scripts/jd-signin.js  — createExtraSignins / runJxzySignin / runHomeSignin / runIndexSignin
差异：原仓库依赖 iOS Loon 抓包拿到的“签名环境”，本项目改为本地 quickjs
运行京东官方 SDK 自举签名（h5st.py），不依赖抓包。

任务清单：
  hs / ys   健康系每日签到（无签名接口，约 1 京豆/天/个）
  delivery  天天领豆（h5st，活动 2775 / 5358）
  game      互动游戏签到（h5st）
  jxzy      京喜签到（query 免 h5st，claim 需 h5st）
  home      家电家居签到（同京喜流程，不同 craftId）
  index     京东指数签到（同上）
"""
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import requests

from h5st import SignerPool, sha256_text

API = "https://api.m.jd.com/api"

HEALTH_KEYS = {"hs": "250520900001", "ys": "250141600001"}
DELIVERY_ACTIVITIES = ["2775", "5358"]
GAME_LINK_ID = "MWC_-5cWq-JH1wrPPteH4w"

# 京喜系三个活动共用同一套接口模板，仅页面 / craftId 不同
JXZY_FAMILY = {
    "jxzy": {"page": "2iqSwv1JiDHxAkHAikfU6XAECFmo", "craft": "6824629a7c46584759d39b78"},
    "home": {"page": "2H8G6a7JecjqHH3t1ZWSoJjPtziP", "craft": "69ae8eb86a31c802e19f9f8f"},
    "index": {"page": "3XzyjnTW4gbEk1BMxafkjP9QEKRw", "craft": "6a8270f9a65ae0dacfa38042"},
}
JX_SIGN_APP = "c50cc"
JX_SIGNSTR_KEY = b"xtl_sqg_mall-^&*-damai_(789)_@#$"  # 京东前端公开的 HMAC-MD5 key


def _zero(v) -> bool:
    return v == 0 or v == "0"


def _bean_number(v):
    """合法的京豆数量（0-100000 的整数），否则 None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int) and 0 <= v <= 100000:
        return v
    if isinstance(v, str) and v.isdigit():
        n = int(v)
        if 0 <= n <= 100000:
            return n
    return None


def _iso_now() -> str:
    """JS new Date().toISOString() 等价。"""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _ms() -> str:
    return str(int(time.time() * 1000))


def _jx_signstr(body: dict) -> str:
    """jxBodySign：body（不含 signStr）按 key 排序后，仅把 value 用 & 拼接，HMAC-MD5。"""
    values = []
    for key in sorted(body.keys()):
        v = body[key]
        if v is None:
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, separators=(",", ":"), ensure_ascii=False)
        elif isinstance(v, bool):
            v = "true" if v else "false"
        else:
            v = str(v)
        if v == "" and not isinstance(body[key], (int, float, bool)):
            continue
        values.append(v)
    payload = "&".join(values)
    return hmac.new(JX_SIGNSTR_KEY, payload.encode("utf-8"), hashlib.md5).hexdigest()


def _form(params: dict) -> str:
    from urllib.parse import quote
    return "&".join(f"{quote(str(k), safe='')}={quote(str(v), safe='')}" for k, v in params.items())


class TaskRunner:
    def __init__(self, account: dict, cfg: dict, journal, signer_pool: SignerPool):
        """
        account: {pin, cookie, ua}
        cfg:     {client, client_version, eid_token}
        journal: Journal 实例（跨调用共享，按天去重）
        """
        self.pin = account["pin"]
        self.cookie = account["cookie"]
        self.ua = account["ua"]
        self.cfg = cfg
        self.journal = journal
        self.signers = signer_pool
        self.http = requests.Session()
        self.http.headers.update({
            "Cookie": self.cookie,
            "User-Agent": self.ua,
            "Content-Type": "application/x-www-form-urlencoded",
        })

    # ---------- 基础请求 ----------
    def _post(self, url: str, params: dict, headers: dict = None) -> dict:
        resp = self.http.post(url, data=_form(params).encode("utf-8"),
                              headers=headers or {}, timeout=15, allow_redirects=False)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError("接口响应不是 JSON（可能被风控拦截）")
        if not isinstance(data, dict):
            raise RuntimeError("接口响应结构异常")
        return data

    def _signer(self, app_id: str, referer: str = "https://pro.m.jd.com/"):
        return self.signers.get(self.pin, app_id, self.ua, self.cookie, referer)

    def _signed_params(self, function_id: str, appid: str, body: dict, h5st_app: str,
                       referer: str = "https://pro.m.jd.com/") -> dict:
        """构造带 h5st 的 form 参数（对齐 jd-signin.js 的 signed()）。"""
        body_text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        params = {
            "functionId": function_id,
            "appid": appid,
            "body": body_text,
            "client": self.cfg["client"],
            "clientVersion": self.cfg["client_version"],
            "t": _ms(),
        }
        sign_input = {k: params[k] for k in ("appid", "body", "client", "clientVersion", "functionId", "t")}
        sign_input["body"] = sha256_text(body_text)
        params["h5st"] = self._signer(h5st_app, referer).sign(sign_input)
        if self.cfg.get("eid_token"):
            params["x-api-eid-token"] = self.cfg["eid_token"]
        return params

    # ---------- hs / ys 健康签到（无签名） ----------
    def health(self, task: str) -> dict:
        app_key = HEALTH_KEYS[task]
        headers = {"Referer": "https://laputa.jd.com/", "Origin": "https://laputa.jd.com"}

        def query():
            return self._post(f"{API}?functionId=jdh_bm_getKitTask", {
                "functionId": "jdh_bm_getKitTask",
                "appid": "jdh-middle",
                "body": json.dumps({"m_patch_appKey": app_key, "groupCode": "openkits",
                                    "channel": "jdhapp"}, separators=(",", ":")),
            }, headers)

        def kit(data):
            if not _zero(data.get("code")):
                raise RuntimeError(f"查询被拒绝: code={data.get('code')}")
            r = data.get("result")
            if not isinstance(r, dict) or int(r.get("status", -1)) not in (0, 1, 2, 3, 4):
                raise RuntimeError("签到状态读取失败")
            return r

        before = kit(query())
        if int(before["status"]) == 4:
            old = self.journal.prior(self.pin, task)
            out = {"status": "already_done"}
            if old and _bean_number(old.get("beanQuantity")) is not None:
                out["beanQuantity"] = old["beanQuantity"]
            return out
        if self.journal.prior(self.pin, task):
            return {"status": "pending", "detail": "今天已提交，去页面确认"}
        if not before.get("encodeId") or not before.get("id"):
            raise RuntimeError("缺少签到任务标识")

        claim_body = {"encodeId": before["encodeId"], "taskId": before["id"],
                      "appKey": app_key, "channel": "jdhapp", "infoId": _iso_now()}
        self.journal.mark(self.pin, task, "pending")
        resp = self._post(f"{API}?functionId=jdh_msoa_doTaskGw", {
            "functionId": "jdh_msoa_doTaskGw",
            "appid": "JDHAPP",
            "body": json.dumps(claim_body, separators=(",", ":")),
        }, headers)
        if not _zero(resp.get("code")):
            return {"status": "rejected", "detail": "签到请求未通过"}

        # 奖励：result.result.prizeInfovo[].money 求和（字段缺失记未知，不假设 0 或 1）
        quantity = None
        nested = resp.get("result") or {}
        if _zero(nested.get("code", 0)):
            rows = (nested.get("result") or {}).get("prizeInfovo")
            if isinstance(rows, list) and rows:
                total, ok = 0, True
                for row in rows:
                    n = _bean_number((row or {}).get("money"))
                    if n is None:
                        ok = False
                        break
                    total += n
                if ok and total <= 100000:
                    quantity = total
        self.journal.mark(self.pin, task, "accepted",
                          beanQuantity=quantity if quantity is not None else -1)
        try:
            if int(kit(query())["status"]) == 4:
                self.journal.mark(self.pin, task, "confirmed",
                                  beanQuantity=quantity if quantity is not None else -1)
                out = {"status": "signed_confirmed"}
                if quantity is not None:
                    out["beanQuantity"] = quantity
                return out
        except Exception:
            pass
        out = {"status": "pending", "detail": "已提交，签到状态待确认"}
        if quantity is not None:
            out["beanQuantity"] = quantity
        return out

    # ---------- 天天领豆（h5st） ----------
    def delivery(self) -> dict:
        task = "delivery"
        origin = "https://prodev.jd.com"
        headers = {"Referer": origin + "/", "Origin": origin, "x-rp-client": "h5_1.0.0"}

        class BizError(RuntimeError):
            def __init__(self, code, msg):
                super().__init__(f"业务码 {code}")
                self.code, self.msg = code, msg

        def call(function_id, h5st_app, body):
            params = self._signed_params(function_id, "signed_wh5_ihub", body, h5st_app,
                                         referer=origin + "/")
            return self._post(f"{API}?functionId={function_id}", params, headers)

        def business_data(j):
            if j.get("success") is False:
                raise RuntimeError("请求未通过")
            code = j.get("code")
            if code is not None and not _zero(code) and code not in (200, "200"):
                raise RuntimeError(f"接口码 {code}")
            data = j.get("data")
            if not isinstance(data, dict):
                raise RuntimeError("响应结构异常")
            biz = data.get("bizCode")
            if not _zero(biz):
                raise BizError(biz, data.get("bizMsg") or "")
            return data.get("result")

        # 已知业务码：-2002 已签到；-4001 连签奖励不可用（“奖励偷偷溜走了”）
        ALREADY, NO_AWARD = ("-2002", -2002), ("-4001", -4001)
        parts = []
        for activity_id in DELIVERY_ACTIVITIES:
            amount, accepted = 0, False
            try:
                home = business_data(call("bean_deliverySign_home", "c1e85",
                                          {"activityId": activity_id}))
                if not isinstance(home, dict):
                    raise RuntimeError("签到首页结构变化")
                for function_id, suffix in (("bean_deliverySign_sign", "sign"),
                                            ("bean_deliverySign_continue_award", "continue")):
                    entry_id = f"{task}:{activity_id}:{suffix}"
                    old = self.journal.prior(self.pin, entry_id)
                    if old:
                        if old.get("state") in ("accepted", "confirmed") and \
                                _bean_number(old.get("beanQuantity")) is not None:
                            amount += old["beanQuantity"]
                            accepted = True
                            continue
                        parts.append({"activityId": activity_id, "status": "pending",
                                      "detail": "今天已有提交记录", "beanQuantity": amount})
                        break
                    try:
                        self.journal.mark(self.pin, entry_id, "pending")
                        result = business_data(call(function_id, "987dd", {"activityId": activity_id}))
                    except BizError as e:
                        if e.code in ALREADY:
                            # 今天已签到：记为完成，不重复提交
                            self.journal.mark(self.pin, entry_id, "confirmed", beanQuantity=0)
                            accepted = True
                            continue
                        if e.code in NO_AWARD and suffix == "continue":
                            # 连签奖励今日不可用：正常分支，不算失败
                            self.journal.mark(self.pin, entry_id, "confirmed", beanQuantity=0)
                            continue
                        raise
                    n = _bean_number((result or {}).get("value"))
                    if n is None:
                        raise RuntimeError("京豆奖励字段变化")
                    self.journal.mark(self.pin, entry_id, "accepted", beanQuantity=n)
                    amount += n
                    accepted = True
                else:
                    parts.append({"activityId": activity_id,
                                  "status": "accepted" if accepted else "pending",
                                  "beanQuantity": amount})
                    continue
            except Exception as e:
                parts.append({"activityId": activity_id,
                              "status": "partial" if accepted else "stopped",
                              "beanQuantity": amount, "detail": str(e)})
        ok = all(p["status"] == "accepted" for p in parts)

        def part_text(p):
            if p["status"] == "accepted":
                return f"获得 {p['beanQuantity']} 京豆" if p.get("beanQuantity") else "今日已签到/奖励已领"
            return p.get("detail", p["status"])

        detail = "；".join(f"{p['activityId']}: {part_text(p)}" for p in parts)
        total = sum(p.get("beanQuantity") or 0 for p in parts)
        out = {"status": "accepted" if ok else "partial", "parts": parts, "detail": detail}
        if total:
            out["beanQuantity"] = total
        return out

    # ---------- 互动游戏签到（h5st） ----------
    def game(self) -> dict:
        task = "game"
        origin = "https://pro.jd.com"
        headers = {"Referer": origin + "/", "Origin": origin, "x-rp-client": "h5_1.0.0"}

        def call(function_id, h5st_app, body):
            params = self._signed_params(function_id, "wegame-hub", body, h5st_app,
                                         referer=origin + "/")
            return self._post(f"{API}?functionId={function_id}", params, headers)

        def state(j):
            if j.get("success") is not True:
                raise RuntimeError("互动签到状态读取失败")
            r = (j.get("data") or {}).get("signMainVo")
            if not isinstance(r, dict) or int(r.get("currentStatus", -1)) not in (0, 1, 3):
                raise RuntimeError("互动签到状态读取失败")
            return r

        def query():
            return state(call("weGameHome", "101aa",
                              {"envType": 1, "linkId": GAME_LINK_ID, "babelChannel": "ttt106"}))

        before = query()
        status = int(before["currentStatus"])
        if status == 3:
            return {"status": "already_done"}
        if status != 1:
            return {"status": "manual_required", "detail": "请先在活动页完成前置条件"}
        if self.journal.prior(self.pin, task):
            return {"status": "pending", "detail": "今天已提交，去页面确认"}
        mark_str = before.get("markStr")
        if not mark_str:
            raise RuntimeError("缺少本次签到标识")

        self.journal.mark(self.pin, task, "pending")
        resp = call("weGameLottery", "730a6",
                    {"envType": 1, "linkId": GAME_LINK_ID, "status": 1, "markStr": mark_str})
        if resp.get("success") is not True:
            return {"status": "rejected", "detail": "领取请求未通过"}
        amount = _bean_number(((resp.get("data") or {}).get("awardResultVO") or {}).get("amount"))
        self.journal.mark(self.pin, task, "accepted",
                          beanQuantity=amount if amount is not None else -1)
        try:
            if int(query()["currentStatus"]) == 3:
                self.journal.mark(self.pin, task, "confirmed",
                                  beanQuantity=amount if amount is not None else -1)
                out = {"status": "signed_confirmed"}
                if amount is not None:
                    out["beanQuantity"] = amount
                return out
        except Exception:
            pass
        out = {"status": "pending", "detail": "领取返回成功，签到状态待确认"}
        if amount is not None:
            out["beanQuantity"] = amount
        return out

    # ---------- 京喜系签到（京喜 / 家电家居 / 京东指数） ----------
    def jxzy_family(self, task: str) -> dict:
        const = JXZY_FAMILY[task]
        referer = f"https://pro.m.jd.com/mall/active/{const['page']}/index.html"
        headers = {"Referer": referer, "Origin": "https://pro.m.jd.com"}
        base_body = {"source": "jxzy", "craftId": const["craft"], "sceneval": 2,
                     "buid": 325, "appCode": "ms1888ebbf"}

        def fresh_body(extra: dict = None) -> dict:
            body = dict(base_body)
            if extra:
                body.update(extra)
            body["time"] = int(time.time() * 1000)
            body["signStr"] = _jx_signstr(body)
            return body

        def make_params(function_id: str, body: dict) -> dict:
            return {
                "appid": "jx_h5_babel", "channel": "jxh5", "client": "jxh5",
                "clientVersion": "1.2.5", "functionId": function_id,
                "body": json.dumps(body, separators=(",", ":"), ensure_ascii=False),
                "t": _ms(),
            }

        def query():
            return self._post(f"{API}?functionId=jxzy_active_querySign",
                              make_params("jxzy_active_querySign", fresh_body()), headers)

        def parse_status(data):
            if str(data.get("code")) != "0" or not isinstance(data.get("data"), dict):
                raise RuntimeError(f"查询失败: {data.get('code')} {data.get('msg') or data.get('message') or ''}")
            d = data["data"]
            st = d.get("status")
            days = d.get("alreadySignDays")
            if st not in (1, 2) or not isinstance(days, int) or not isinstance(d.get("itemId"), str):
                raise RuntimeError("签到状态不明确")
            sign_list = d.get("signList")
            today_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
            # 与 jsDay 对齐：UTC+8 日期
            today_str = datetime.fromtimestamp(time.time() + 8 * 3600, timezone.utc).strftime("%Y-%m-%d")
            today = isinstance(sign_list, list) and any(
                isinstance(x, str) and x.startswith(today_str + "_") for x in sign_list)
            if (st == 2 and not today) or (st == 1 and today):
                raise RuntimeError("签到状态与今日记录不一致")
            return {"done": st == 2, "days": days, "itemId": d["itemId"]}

        before = query()
        state = parse_status(before)
        if state["done"]:
            return {"status": "already_done", "roundDays": state["days"]}
        if self.journal.prior(self.pin, task):
            return {"status": "pending", "detail": "今天已有领取提交记录，请到活动页确认",
                    "roundDays": state["days"]}

        claim_body = fresh_body({"itemId": state["itemId"]})
        params = make_params("jxzy_active_drawSign", claim_body)
        sign_input = {k: params[k] for k in ("appid", "body", "functionId", "t", "client", "clientVersion")}
        sign_input["body"] = sha256_text(params["body"])
        params["h5st"] = self._signer(JX_SIGN_APP, referer).sign(sign_input)
        if self.cfg.get("eid_token"):
            params["x-api-eid-token"] = self.cfg["eid_token"]

        self.journal.mark(self.pin, task, "pending")
        received = self._post(f"{API}?functionId=jxzy_active_drawSign", params, headers)
        if str(received.get("code")) != "0" or not isinstance(received.get("data"), dict):
            raise RuntimeError(f"领取失败: {received.get('code')} "
                               f"{received.get('msg') or received.get('message') or ''}")
        claimed = received["data"]
        today_str = datetime.fromtimestamp(time.time() + 8 * 3600, timezone.utc).strftime("%Y-%m-%d")
        sign_list = claimed.get("signList")
        if not isinstance(sign_list, list) or not any(
                isinstance(x, str) and x.startswith(today_str + "_") for x in sign_list):
            raise RuntimeError("领取结果未确认，请到活动页查看")

        beans, coupon_amount, coupon_count = 0, 0.0, 0
        for row in claimed.get("prizeInfos") or []:
            if not isinstance(row, dict) or row.get("discount") in (None, ""):
                continue
            try:
                amount = float(row["discount"])
            except (TypeError, ValueError):
                continue
            if amount <= 0 or amount > 100000:
                continue
            if row.get("prizeType") == 2 and amount == int(amount):
                beans += int(amount)
            elif row.get("prizeType") == 1:
                coupon_amount += amount
                coupon_count += 1

        self.journal.mark(self.pin, task, "accepted", beanQuantity=beans)
        out = {"roundDays": claimed.get("alreadySignDays")}
        if beans:
            out["beanQuantity"] = beans
        if coupon_count:
            out["couponCount"] = coupon_count
            out["couponAmount"] = round(coupon_amount, 2)
        try:
            after = parse_status(query())
            if after["done"]:
                self.journal.mark(self.pin, task, "confirmed", beanQuantity=beans)
                out["status"] = "signed_confirmed"
                out["roundDays"] = after["days"]
                return out
        except Exception:
            pass
        out["status"] = "claim_success_verify_unconfirmed"
        return out


class Journal:
    """按天记录提交状态，避免重复领取（对齐 jd-signin.js 的 mark/prior 语义）。"""

    LIMIT = 30  # 保留最近 30 天的记录

    def __init__(self, path):
        import pathlib
        self.path = pathlib.Path(path)
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}
        today = self.today()
        # 只保留最近 LIMIT 天的日期前缀记录
        for key in list(self.data.keys()):
            if key[:10] < "2000-01-01":
                del self.data[key]
        self._date = today

    @staticmethod
    def today() -> str:
        # 与 JS 的 jsDay 一致：UTC+8 日期
        return datetime.fromtimestamp(time.time() + 8 * 3600, timezone.utc).strftime("%Y-%m-%d")

    def _key(self, pin: str, entry_id: str) -> str:
        digest = hashlib.sha256(pin.encode("utf-8")).hexdigest()[:24]
        return f"{self._date}:{digest}:{entry_id}"

    def prior(self, pin: str, entry_id: str):
        return self.data.get(self._key(pin, entry_id))

    def mark(self, pin: str, entry_id: str, state: str, beanQuantity: int = None):
        entry = {"state": state, "time": int(time.time() * 1000)}
        if beanQuantity is not None and beanQuantity >= 0:
            entry["beanQuantity"] = beanQuantity
        self.data[self._key(pin, entry_id)] = entry
        # 清理过期记录
        from datetime import timedelta
        limit = (datetime.now(timezone.utc) - timedelta(days=self.LIMIT)).strftime("%Y-%m-%d")
        for key in list(self.data.keys()):
            if key[:10] < limit:
                del self.data[key]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)


TASK_LABELS = {
    "hs": "hs健康签到", "ys": "ys健康签到",
    "delivery": "天天领豆", "game": "互动游戏签到",
    "jxzy": "京喜签到", "home": "家电家居签到", "index": "京东指数签到",
}


def run_task(runner: TaskRunner, task: str) -> dict:
    if task in ("hs", "ys"):
        return runner.health(task)
    if task == "delivery":
        return runner.delivery()
    if task == "game":
        return runner.game()
    if task in JXZY_FAMILY:
        return runner.jxzy_family(task)
    raise ValueError(f"未知任务: {task}")
