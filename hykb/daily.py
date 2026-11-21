#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
好游快爆 · 翻滚吧爆米花 + 爆友等级

cron: 10 8 * * *
new Env('好游快爆爆米花');

纯协议，不碰真机、不碰浏览器。

覆盖：
  爆米花活动  浇水 / 收割 / 播种 / 玉米转爆米花 / 买种子
  每日任务    小游戏 / 分享 / 答题 / 开App / 游戏分类 / 快玩
  爆爆口令    自动拉当天口令 + 提交
  爆爆战令    任务经验值 + 等级奖励
  爆友等级    每日爆友分任务（只领不花钱的）
  好友互动    偷玉米

青龙环境变量（账号）：
  HYKB_ACCOUNTS  推荐。JSON 数组
    [{"name":"主号","cookie":"scookie 的值"}]
  HYKB_COOKIE    兼容。scookie 值，多账号用 & 或换行分隔
    （⚠️ 是活动请求表单里的 scookie 参数，不是浏览器 Cookie 头）

可选：
  HYKB_SAFE              1=安全模式（默认，慢但稳）；0=快
  HYKB_FARM_ROUNDS       快玩重复领取轮数，默认 0（关）
  HYKB_WAIT_SECONDS      阶段 A→B 等待秒，默认 345（小游戏 5 分钟）
  HYKB_ANSWER_BANK       答题答案本路径，默认脚本目录 hykb_answers.json
  HYKB_SMID              数美设备指纹，已内置默认值
  HYKB_TIMEOUT           请求超时秒，默认 20
  HYKB_INTER_ACCOUNT_DELAY  多账号间隔秒，默认 10

通知（与仓库其它脚本共用）：
  BARK_URL / BARK_KEY / BARK_SERVER / BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL
  SERVERCHAN_KEY / WEBHOOK_URL

依赖：requests（本地用 config.yaml 时再加 PyYAML）

三条铁律：
  1. 不花爆米花买爆友分（500 换 2 那条已剔除）
  2. 不重复刷快玩（默认 0 轮）
  3. 每个请求之间随机 4~12 秒，任务组之间 15~40 秒
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

SCRIPT_DIR = Path(__file__).resolve().parent

BASE = "https://huodong3.3839.com/n/hykb/cornfarm/"
SHOP = "https://shop.3839.com/index.php?"
SEED_GOODS_ID = 8220
BDT = "https://huodong3.3839.com/n/hykb/baoyoudiantang2026/ajax.php"
DEFAULT_BARK_SERVER = "https://api.day.app"

UA = (
    "Mozilla/5.0 (Linux; Android 13; M2012K11AC Build/TKQ1.220829.002; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/115.0.5790.166 "
    "Mobile Safari/537.36Androidkb/1.5.7.005(android;M2012K11AC;13;1080x2320;WiFi);"
    "@4399_sykb_android_activity@"
)
VER = "1.5.7.005"

# 数美设备指纹：从 App 的 JS 桥里掏出来的固定值
DEFAULT_SMID = (
    "BTtcR2aIFMC8F3lmYNy281vb7d19hukr911jQjgcw6Nck7t/w9411BzuL5MINxfNuEq+"
    "omH1j5rlxkaI5yr/YIQ=="
)

# 爆友分任务 id（已剔除会花资源的那几条）
BYF_TASKS = [1, 2, 6, 7, 8, 141, 71, 10, 15, 16, 74, 75, 76,
             129, 130, 131, 14, 98, 99, 100, 101, 102, 122, 103]

REQ_JITTER = (4.0, 12.0)
TASK_GAP = (15.0, 40.0)
START_JITTER = (0, 150)

# 全局安全模式，由 main() 按配置设置（脚本按账号串行执行）
SAFE = True

logger = logging.getLogger("hykb")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    cookie: str = ""  # 活动请求里的 scookie 值

    def normalize(self) -> None:
        raw = (self.cookie or "").strip()
        if raw.lower().startswith("scookie="):
            raw = raw.split("=", 1)[1].strip()
        if raw.lower().startswith("cookie:"):
            raw = raw.split(":", 1)[1].strip()
        self.cookie = raw
        if not self.name:
            self.name = "account"


@dataclass
class NotifyConfig:
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = "好游快爆"
    bark_sound: str = ""
    bark_icon: str = ""
    bark_level: str = ""
    serverchan_key: str = ""
    webhook_url: str = ""

    def enabled(self) -> bool:
        return bool(
            self.bark_url or self.bark_key or self.serverchan_key or self.webhook_url
        )


@dataclass
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    safe: bool = True
    farm_rounds: int = 0
    wait_seconds: int = 345
    timeout: int = 20
    answer_bank: str = ""
    smid: str = DEFAULT_SMID
    inter_account_delay: int = 10
    notify: NotifyConfig = field(default_factory=NotifyConfig)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    v = _env(name)
    if not v:
        return default
    return v.lower() in ("1", "true", "yes", "on", "y")


def _split_multi(value: str) -> list[str]:
    return [x.strip() for x in re.split(r"[&\n]", value or "") if x.strip()]


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
        bark_group=_env("BARK_GROUP", "好游快爆"),
        bark_sound=_env("BARK_SOUND"),
        bark_icon=_env("BARK_ICON"),
        bark_level=_env("BARK_LEVEL"),
        serverchan_key=_env("SERVERCHAN_KEY") or _env("PUSH_KEY"),
        webhook_url=_env("WEBHOOK_URL"),
    )


def load_accounts_from_env() -> list[Account]:
    raw = _env("HYKB_ACCOUNTS")
    if raw:
        data = json.loads(raw)
        out: list[Account] = []
        for i, item in enumerate(data, 1):
            acc = Account(
                name=str(item.get("name") or f"账号{i}"),
                cookie=str(item.get("cookie") or item.get("scookie") or ""),
            )
            acc.normalize()
            out.append(acc)
        return out

    raw = _env("HYKB_COOKIE") or _env("HYKB_SCOOKIE") or _env("hykb_cookie")
    out = []
    for i, block in enumerate(_split_multi(raw), 1):
        acc = Account(name=f"账号{i}", cookie=block)
        acc.normalize()
        out.append(acc)
    return out


def load_config_from_env() -> Optional[AppConfig]:
    accounts = load_accounts_from_env()
    if not accounts:
        return None
    try:
        farm_rounds = int(_env("HYKB_FARM_ROUNDS", "0") or 0)
    except ValueError:
        farm_rounds = 0
    try:
        wait_seconds = int(_env("HYKB_WAIT_SECONDS", "345") or 345)
    except ValueError:
        wait_seconds = 345
    return AppConfig(
        accounts=accounts,
        safe=_env_bool("HYKB_SAFE", True),
        farm_rounds=max(0, farm_rounds),
        wait_seconds=max(0, wait_seconds),
        timeout=int(_env("HYKB_TIMEOUT", "20") or 20),
        answer_bank=_env("HYKB_ANSWER_BANK"),
        smid=_env("HYKB_SMID", DEFAULT_SMID),
        inter_account_delay=int(_env("HYKB_INTER_ACCOUNT_DELAY", "10") or 10),
        notify=load_notify_from_env(),
    )


def load_config_yaml(path: Path) -> AppConfig:
    try:
        import yaml
    except ImportError as e:
        raise ImportError("本地 yaml 配置需要 PyYAML：pip install PyYAML") from e
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    accounts: list[Account] = []
    for i, item in enumerate(raw.get("accounts") or []):
        if not isinstance(item, dict):
            raise ValueError(f"accounts[{i}] 格式错误")
        acc = Account(
            name=str(item.get("name") or f"账号{i + 1}"),
            cookie=str(item.get("cookie") or item.get("scookie") or ""),
        )
        acc.normalize()
        if not acc.cookie:
            raise ValueError(f"账号 [{acc.name}] 未配置 cookie（scookie）")
        accounts.append(acc)
    if not accounts:
        raise ValueError("配置中 accounts 为空")

    n = raw.get("notify") or {}
    env_notify = load_notify_from_env()
    notify = NotifyConfig(
        bark_url=env_notify.bark_url or str(n.get("bark_url") or ""),
        bark_key=env_notify.bark_key or str(n.get("bark_key") or ""),
        bark_server=str(n.get("bark_server") or env_notify.bark_server or DEFAULT_BARK_SERVER).rstrip("/"),
        bark_group=env_notify.bark_group if _env("BARK_GROUP") else str(n.get("bark_group") or "好游快爆"),
        bark_sound=env_notify.bark_sound or str(n.get("bark_sound") or ""),
        bark_icon=env_notify.bark_icon or str(n.get("bark_icon") or ""),
        bark_level=env_notify.bark_level or str(n.get("bark_level") or ""),
        serverchan_key=env_notify.serverchan_key or str(n.get("serverchan_key") or ""),
        webhook_url=env_notify.webhook_url or str(n.get("webhook_url") or ""),
    )

    return AppConfig(
        accounts=accounts,
        safe=_env_bool("HYKB_SAFE", bool(raw.get("safe", True))),
        farm_rounds=int(_env("HYKB_FARM_ROUNDS") or raw.get("farm_rounds") or 0),
        wait_seconds=int(_env("HYKB_WAIT_SECONDS") or raw.get("wait_seconds") or 345),
        timeout=int(_env("HYKB_TIMEOUT") or raw.get("timeout") or 20),
        answer_bank=_env("HYKB_ANSWER_BANK") or str(raw.get("answer_bank") or ""),
        smid=_env("HYKB_SMID") or str(raw.get("smid") or DEFAULT_SMID),
        inter_account_delay=int(_env("HYKB_INTER_ACCOUNT_DELAY") or raw.get("inter_account_delay") or 10),
        notify=notify,
    )


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------

def log(msg: str, tag: str = "") -> None:
    if tag:
        logger.info("[%s] %s", tag, msg)
    else:
        logger.info("%s", msg)


def nap(sec: float, extra: Optional[float] = None) -> None:
    if SAFE:
        sec = sec + (extra if extra is not None else random.uniform(*REQ_JITTER))
    time.sleep(max(sec, 0.3))


def tgap() -> None:
    if SAFE:
        time.sleep(random.uniform(*TASK_GAP))


def fetch_miling() -> str:
    """从快爆工具页接口拉今天的爆爆口令"""
    try:
        r = requests.post(
            "https://www.onebiji.com/hykb_tools/miling/mrkl/ajax.php",
            data={"op": "get_info", "t": random.random()},
            headers={"User-Agent": UA,
                     "Referer": "https://www.onebiji.com/hykb_tools/miling/mrkl/preview.php?immgj=1",
                     "X-Requested-With": "XMLHttpRequest"},
            timeout=20,
        )
        j = r.json()
        if j.get("status") == "ok":
            return ((j.get("today_miling") or {}).get("miling") or "").strip()
    except Exception:
        pass
    return ""


def load_bank(path: str) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_bank(path: str, bank: dict[str, str]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bank, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _fmt_num(value: Any) -> str:
    n = _num(value)
    return f"{n:g}" if n is not None else "-"


def snapshot(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "baomihua": _num(cfg.get("baomihua")),
        "seed": _num(cfg.get("seed")),
        "corn": _num(cfg.get("corn")),
        "csd": str(cfg.get("csd_jdt") or ""),
    }


# ---------------------------------------------------------------------------
# 好游快爆客户端
# ---------------------------------------------------------------------------

class HykbClient:
    def __init__(self, account: Account, cfg: AppConfig, tag: str = ""):
        self.account = account
        self.cfg = cfg
        self.tag = tag or account.name
        self.scookie = account.cookie.strip()
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Origin": "https://huodong3.i3839.com",
            "Referer": BASE + "index.php?imm=0",
            "X-Requested-With": "XMLHttpRequest",
        })
        self.html = ""
        self.page_token = ""
        self.random_str = ""
        self.time_diff = 0
        self.enter_time = 0
        self.token_name = "token"
        self.token_value = "default"
        self.nick = self.tag
        self.cfg_data: dict[str, Any] = {}
        self.share_ok = 0
        self.dati_ok = 0
        self.kouling_ok = 0
        self.byf_got = 0
        self.season_got = 0
        self.season_level = None
        self.season_score = None
        self.byf_value = None
        self.byf_level = None
        self.byf_today = None

    # ---------- 页面 ----------
    def load_page(self) -> bool:
        r = self.s.get(BASE + "index.php?imm=0", timeout=self.cfg.timeout)
        self.html = r.text
        m1 = re.search(r'pageToken\s*=\s*"([^"]+)"', self.html)
        m2 = re.search(r'pageRandomStr\s*=\s*"([^"]+)"', self.html)
        m3 = re.search(r"setACTServerTime\((\d+)\)", self.html)
        if not (m1 and m2):
            return False
        self.page_token, self.random_str = m1.group(1), m2.group(1)
        server_ms = int(m3.group(1)) if m3 else int(time.time() * 1000)
        self.time_diff = server_ms - int(time.time() * 1000)
        self.enter_time = server_ms
        return True

    def discover(self) -> dict[str, Any]:
        h = self.html

        def pick(fn: str) -> list[int]:
            ids: set[int] = set()
            for m in re.finditer(rf'onclick="Daily\.{fn}\(', h):
                tag_start = h.rfind("<a", max(0, m.start() - 600), m.start())
                tag = h[tag_start if tag_start > 0 else 0: m.end() + 220]
                for x in re.findall(r'data-id="(\d+)"', tag):
                    ids.add(int(x))
                arg_end = h.find(")", m.end())
                for x in re.findall(r"'(\d+)'", h[m.end():arg_end]):
                    ids.add(int(x))
                for x in re.findall(r"daily_(?:btn|li_label)_(\d+)", tag):
                    ids.add(int(x))
            return sorted(ids)

        titles = dict(re.findall(r'daily_dt_ok_(\d+)">\s*<span>([^<]+)</span>', h))
        yids = sorted(set(int(x) for x in re.findall(r"Daily\.DailyYuyueLing\((\d+)", h)))
        return {
            "small": pick("DailySmallGame"),
            "share": pick("DailyShare"),
            "dati": pick("DailyDati"),
            "app": pick("DailyApp"),
            "cate": pick("DailyGameCateJump"),
            "down": pick("DailyDownGameLing"),
            "inter": pick("DailyInteractiveLing"),
            "jiaohu": pick("DailyJiaohuLing"),
            "yuyue": [(i, titles.get(str(i), "")) for i in yids],
        }

    # ---------- 请求 ----------
    def _params(self, ac: str, **kw: Any) -> dict[str, Any]:
        tt = int(time.time() * 1000) + self.time_diff
        sign = hashlib.md5(
            f"{self.page_token}|{self.random_str}|{tt}|visitV2".encode()).hexdigest()[:10]
        p: dict[str, Any] = {
            "ac": ac, "r": f"{random.random()}",
            self.token_name: self.token_value,
            "token_version": "v2", "page_token": self.page_token,
            "enter_time": self.enter_time, "token_time": tt,
            "token_time2": int(time.time() * 1000),
            "random_str": self.random_str, "token_sign": sign,
            "scookie": self.scookie, "verison": VER,
        }
        p.update(kw)
        return p

    def post(self, ajax: str, ac: str, **kw: Any) -> dict[str, Any]:
        try:
            return self.s.post(
                BASE + ajax, data=self._params(ac, **kw), timeout=self.cfg.timeout
            ).json()
        except Exception as e:
            return {"key": "error", "msg": str(e)[:100]}

    def ling(self, ac: str, tid: int) -> dict[str, Any]:
        return self.post("ajax_daily.php", ac, id=tid, VersionCode="100000000",
                         smdeviceid="", verison=VER)

    # ---------- 基础业务 ----------
    def login(self) -> dict[str, Any]:
        d = self.post("ajax.php", "login")
        cfg = d.get("config") or {}
        if isinstance(cfg, dict):
            self.cfg_data = cfg
            self.nick = cfg.get("nickname") or self.nick
            if cfg.get("token_name"):
                self.token_name, self.token_value = cfg["token_name"], cfg["token_value"]
        return d

    def harvest(self) -> dict[str, Any]:
        return self.post("ajax_plant.php", "Harvest")

    def plant(self, corn_id: Optional[int] = None) -> dict[str, Any]:
        cid = corn_id or self.cfg_data.get("next_seed_id") or 1
        r = self.post("ajax_plant.php", "Plant", corn_id=cid)
        if str(r.get("key")) == "502":
            for alt in (1, 2, 3, 4):
                if alt == cid:
                    continue
                r2 = self.post("ajax_plant.php", "Plant", corn_id=alt)
                if str(r2.get("key")) == "ok":
                    return r2
                nap(1)
        return r

    def sign(self) -> dict[str, Any]:
        return self.post("ajax_sign.php", "Sign")

    # 玉米 → 爆米花
    def produce_all(self) -> Optional[dict[str, Any]]:
        try:
            cfg = self.login().get("config") or {}
            corn = int(cfg.get("corn") or 0)
            if corn <= 0:
                return None
            self.post("ajax_bag.php", "Produce", preNum=corn, resure="0")
            nap(1.5)
            r = self.post("ajax_bag.php", "Produce", preNum=corn, resure="1")
            if str(r.get("key")) == "ok":
                log(f"玉米 {corn} → 爆米花 +{r.get('add_bmh')}（现 {r.get('baomihua')}）", self.tag)
                return r
        except Exception:
            pass
        return None

    def harvest_plant(self) -> str:
        h = self.harvest()
        nap(2)
        p = self.plant()
        nap(1.5)
        pr = self.produce_all()
        extra = f"/产爆米花+{pr.get('add_bmh')}" if pr else ""
        return f"收割{h.get('key')}/播种{p.get('key')}{extra}"

    # ---------- 商店买种子 ----------
    def buy_seeds(self, keep: int = 5, max_buy: int = 6) -> int:
        try:
            cfg = self.login().get("config") or {}
            have = int(cfg.get("seed") or 0)
            if have >= keep:
                return 0
            need = min(keep - have, max_buy)
            s = requests.Session()
            s.headers.update({
                "User-Agent": UA,
                "Referer": f"https://shop.3839.com/?id={SEED_GOODS_ID}",
                "X-Requested-With": "XMLHttpRequest",
            })
            got = 0
            for _ in range(need):
                base = {"id": SEED_GOODS_ID, "scookie": self.scookie,
                        "r": random.random(), "smdeviceid": self.cfg.smid}
                s.post(SHOP + "c=DetailVirtual&a=choose", data=base, timeout=15)
                nap(0.8)
                s.post(SHOP + "c=OrderVirtual&a=checkOrder",
                       data=dict(base, version=VER, client=1), timeout=15)
                nap(0.8)
                r = s.post(SHOP + "c=OrderVirtual&a=createOrder",
                           data=dict(base, version=VER, client=1, order_flag=1), timeout=15)
                j = r.json()
                if j.get("code") != 200:
                    log(f"买种子失败 {j.get('code')} {j.get('msg', '')}", self.tag)
                    break
                got += 1
                nap(1.5)
            if got:
                after = self.login().get("config") or {}
                log(f"商店买种子 {got} 个（5爆米花/个），现有 {after.get('seed')} 个，"
                    f"爆米花 {after.get('baomihua')}", self.tag)
            return got
        except Exception:
            log("买种子异常：" + traceback.format_exc(limit=1), self.tag)
            return 0

    def buy_seed(self) -> Optional[dict[str, Any]]:
        """活动内经验值兑换种子（要富余经验值，基本够不着，留着兜底）"""
        try:
            cfg = self.login().get("config") or {}
            if int(cfg.get("seed") or 0) > 0:
                return None
            init = self.post("ajax_season.php", "seasonManualInit")
            score = int(init.get("user_score") or 0)
            if score - 5000 < 100:
                log(f"种子为 0，兑换需富余经验值（当前战令 {score}/5000），还不够", self.tag)
                return None
            for pid in (7, 8):
                r = self.post("ajax_season.php", "userExchangePrize", prize_id=pid)
                if str(r.get("key")) == "ok":
                    log(f"种子兑换成功 prize_id={pid}", self.tag)
                    return r
                nap(1.2)
        except Exception:
            pass
        return None

    # ---------- 每日任务 ----------
    def claim(self, ac: str, tid: int, name: str = "",
              got: Optional[list[str]] = None) -> Any:
        r = self.ling(ac, tid)
        k = str(r.get("key"))
        if k == "ok":
            line = f"{name or ac}#{tid} 成熟度+{r.get('reward_csd_num')} 爆米花+{r.get('reward_bmh_num')}"
            log("领到 " + line, self.tag)
            if got is not None:
                got.append(line)
            if str(r.get("chengshoudu")) == "100":
                log("成熟度满 → " + self.harvest_plant(), self.tag)
        elif k == "2005":
            log("成熟度满，先收割 → " + self.harvest_plant(), self.tag)
            nap(2)
            return self.claim(ac, tid, name, got)
        return k, r

    def farm(self, rounds: int, tid: int = 3806) -> int:
        got = 0
        for _ in range(rounds):
            r = self.ling("DailyKuaiwanGameLing", tid)
            if str(r.get("key")) != "ok":
                break
            got += 1
            if str(r.get("chengshoudu")) == "100":
                self.harvest_plant()
            nap(1.5)
        return got

    def share_task(self, tid: int) -> str:
        r = self.post("ajax_daily.php", "DailyShare", id=tid, onlyc=0)
        k = str(r.get("key"))
        if k == "2001":
            return "已领过"
        if k != "2002":
            return f"分享信息异常 {k}"
        st = r.get("share_type") or "allnoweibo"
        cb = self.post("ajax_daily.php", "DailyShareCallback", id=tid, mode=st, source="ds")
        if str(cb.get("key")) != "ok":
            return f"回调失败 {cb.get('key')}"
        lg = self.ling("DailyShareLing", tid)
        return "ok" if str(lg.get("key")) == "ok" else f"领奖失败 {lg.get('key')}"

    def dati(self, tid: int = 7, bank: Optional[dict[str, str]] = None) -> str:
        q = self.post("ajax_daily.php", "DailyDati", id=tid)
        k = str(q.get("key"))
        if k == "2001":
            return "今日次数用完"
        if k == "2002":
            return "已领过"
        if k != "2004":
            return f"取题异常 {k}"
        title = q.get("title", "")
        opts = [q.get(f"option{i}") for i in range(1, 5)]
        bank = bank if bank is not None else {}

        if title in bank:
            r = self.post("ajax_daily.php", "DailyDatiAnswer", id=tid, option=bank[title])
            log("答案本命中，直接答", self.tag)
        else:
            nap(1)
            r = self.post("ajax_daily.php", "DailyDatiAnswer", id=tid, option=opts[0])
            if str(r.get("key")) == "2003":
                right = r.get("back_answer")
                log(f"答题错了，正确答案「{right}」，剩 {r.get('sy_dati_num')} 次", self.tag)
                if right and title:
                    bank[title] = right
                    save_bank(self.cfg.answer_bank, bank)
                if not right:
                    return "没拿到正确答案"
                nap(1)
                r = self.post("ajax_daily.php", "DailyDatiAnswer", id=tid, option=right)

        if str(r.get("key")) != "ok":
            return f"答题失败 {r.get('key')} {r.get('info', '')}"
        nap(1)
        lg = self.post("ajax_daily.php", "DailyDatiLing", id=tid, smdeviceid="", verison=VER)
        if str(lg.get("key")) == "2005":
            self.harvest_plant()
            nap(2)
            lg = self.post("ajax_daily.php", "DailyDatiLing", id=tid, smdeviceid="", verison=VER)
        return "ok" if str(lg.get("key")) == "ok" else f"领奖失败 {lg.get('key')}"

    # ---------- 爆爆口令 ----------
    def secretorder(self, code: str) -> dict[str, Any]:
        return self.post("ajax_more.php", "Secretorder",
                         miling=code, smdeviceid=self.cfg.smid, verison=VER)

    def kouling(self) -> str:
        try:
            code = fetch_miling()
            if not code:
                return "没取到今天口令"
            r = self.secretorder(code)
            k = str(r.get("key"))
            if k == "ok":
                log(f"口令「{code}」→ +{r.get('add_baomihua')} 爆米花", self.tag)
                return "ok"
            return {"501": "模块关闭", "502": "口令不存在", "503": "被领光",
                    "504": "今日已用过", "505": "口令过期"}.get(k, f"失败 {k}")
        except Exception:
            return "口令异常：" + traceback.format_exc(limit=1)

    # ---------- 爆爆战令 ----------
    def season(self) -> list[str]:
        got: list[str] = []
        try:
            for tag in (1, 2, 3, 4):
                for _ in range(6):
                    r = self.post("ajax_season.php", "loadTaskDataByTagId", tag_id=tag)
                    lst = r.get("list") or {}
                    hit = 0
                    for tid, info in lst.items():
                        if info.get("btn_status") != "wait_receive":
                            continue
                        rr = self.post("ajax_season.php", "receiveStageTaskScore", task_id=tid)
                        if str(rr.get("key")) == "ok":
                            got.append(f"战令任务#{tid} 经验+{rr.get('add_score')}")
                            log(f"战令任务#{tid} → 经验+{rr.get('add_score')}", self.tag)
                            hit += 1
                        nap(1.5)
                    if not hit:
                        break
                    tgap()

            init = self.post("ajax_season.php", "seasonManualInit")
            self.season_level = init.get("user_level")
            self.season_score = init.get("user_score")
            for lv, st in (init.get("user_prize_data") or {}).items():
                if st != "completed":
                    continue
                rr = self.post("ajax_season.php", "receiveLevelPrize",
                               prize_id=int(lv), level=int(lv))
                if str(rr.get("key")) == "ok":
                    name = (rr.get("prize_data") or {}).get("prize_name", "")
                    got.append(f"战令{lv}级 {name}")
                    log(f"战令{lv}级 → {name}", self.tag)
                nap(1.5)
            log(f"战令等级 {init.get('user_level')} 经验 {init.get('user_score')}", self.tag)
        except Exception:
            log("战令异常：" + traceback.format_exc(limit=1), self.tag)
        return got

    # ---------- 爆友等级 ----------
    def bdt(self, ac: str, **kw: Any) -> dict[str, Any]:
        d = {"ac": ac, "r": random.random(), "scookie": self.scookie}
        d.update(kw)
        try:
            r = requests.post(BDT, data=d, timeout=self.cfg.timeout, headers={
                "User-Agent": UA,
                "Referer": "https://huodong3.3839.com/n/hykb/baoyoudiantang2026/index.php",
                "X-Requested-With": "XMLHttpRequest"})
            return r.json()
        except Exception:
            return {"key": "error"}

    def byf(self) -> list[str]:
        got: list[str] = []
        try:
            for tid in BYF_TASKS:
                r = self.bdt("lingQuRenWu", id=tid, type=0, t=random.random())
                if str(r.get("key")) == "ok":
                    info = r.get("info") or "领取成功"
                    got.append(f"爆友分#{tid} {info}")
                    log(f"爆友分#{tid} → {info}", self.tag)
                nap(2)

            for ac in ("lingQuXunZhang", "lingQuHuoYueDu", "lingqukaoshi"):
                r = self.bdt(ac)
                if str(r.get("key")) == "ok":
                    got.append(f"{ac} ok")
                    log(f"{ac} → {r.get('info', 'ok')}", self.tag)
                nap(2)

            c = (self.bdt("login").get("config") or {})
            if c:
                self.byf_value = c.get("byf")
                self.byf_level = c.get("level")
                self.byf_today = f"{c.get('daily_byf_earned')}/{c.get('daily_byf_total')}"
                log(f"爆友分 {c.get('byf')}（今日 {c.get('daily_byf_earned')}/"
                    f"{c.get('daily_byf_total')}） 等级 Lv{c.get('level')}", self.tag)
        except Exception:
            log("爆友分异常：" + traceback.format_exc(limit=1), self.tag)
        return got

    # ---------- 偷玉米 ----------
    def steal_corn(self, times: int = 5, max_try: int = 15) -> int:
        try:
            r = self.post("ajax_interactive.php", "iafInit")
            uids = list((r.get("friendRecommend") or {}).keys())
            left = int(r.get("sy_steal_yumi_num") or 0)
            if left <= 0:
                log("今日偷玉米次数已用完", self.tag)
                return 0
            got = 0
            for uid in uids[:max_try]:
                if got >= min(times, left):
                    break
                rr = self.post("ajax_friendhome.php", "HelpReap", fuid=uid)
                if str(rr.get("key")) == "ok":
                    got += 1
                    log(f"偷到好友 {uid} 的玉米（{got}/{left}）", self.tag)
                nap(2)
            return got
        except Exception:
            return 0


# ---------------------------------------------------------------------------
# 三阶段
# ---------------------------------------------------------------------------

def phase_a(acc: HykbClient, initialized: bool = False) -> Optional[dict[str, Any]]:
    """登录 + 发现任务 + 打启动标记 + 分享 + 答题 + 口令 + 爆友分 + 偷玉米 + 战令"""
    try:
        if not initialized:
            if not acc.load_page():
                log("页面 token 拿不到", acc.tag)
                return None
            d = acc.login()
            if d.get("loginStatus") != "100":
                log(f"登录失败 {d.get('key')}/{d.get('loginStatus')}", acc.tag)
                return None
        cfg = acc.cfg_data
        log(f"{acc.nick} | 成熟度 {cfg.get('csd_jdt')} 爆米花 {cfg.get('baomihua')} "
            f"种子 {cfg.get('seed')} 玉米 {cfg.get('corn')}", acc.tag)
        t = acc.discover()
        log(f"发现任务：小游戏{len(t['small'])} 分享{len(t['share'])} 答题{len(t['dati'])} "
            f"开App{len(t['app'])} 分类{len(t['cate'])} 下载{len(t['down'])} "
            f"互动{len(t['inter'])} 种草{len(t['jiaohu'])} 预约{len(t['yuyue'])}", acc.tag)

        for tid in t["small"]:
            acc.post("ajax_daily.php", "DailySmallGame", id=tid)
            nap(0.8)
        for tid in t["app"]:
            acc.post("ajax_daily.php", "DailyApp", id=tid)
            nap(0.8)
        for tid in t["cate"]:
            acc.post("ajax_daily.php", "DailyGameCateJump", id=tid)
            nap(0.8)
        log("启动标记打完（小游戏5分钟 / 开App·分类60秒）", acc.tag)

        tgap()
        for tid in t["share"]:
            r = acc.share_task(tid)
            if r == "ok":
                acc.share_ok += 1
            else:
                log(f"分享#{tid} → {r}", acc.tag)
            nap(1.5)

        tgap()
        bank = load_bank(acc.cfg.answer_bank)
        for tid in t["dati"]:
            r = acc.dati(tid, bank)
            log(f"答题#{tid} → {r}", acc.tag)
            if r == "ok":
                acc.dati_ok += 1
            nap(1.5)

        tgap()
        kr = acc.kouling()
        log(f"爆爆口令 → {kr}", acc.tag)
        if kr == "ok":
            acc.kouling_ok = 1

        tgap()
        bg = acc.byf()
        if bg:
            acc.byf_got = len(bg)

        tgap()
        sc = acc.steal_corn()
        if sc:
            log(f"偷玉米 {sc} 次（推战令任务）", acc.tag)

        tgap()
        sg = acc.season()
        if sg:
            acc.season_got = len(sg)
        return t
    except Exception:
        log("阶段A异常：" + traceback.format_exc(limit=2), acc.tag)
        return None


def phase_b(acc: HykbClient, tasks: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    if not tasks:
        return acc.nick, [], []
    got: list[str] = []
    need: list[str] = []
    for label, n in (("分享任务", acc.share_ok), ("答题", acc.dati_ok),
                     ("爆爆口令", acc.kouling_ok), ("爆友分", acc.byf_got),
                     ("战令", acc.season_got)):
        if n:
            got.append(f"{label} {n} 个（阶段A已完成）")

    tgap()
    for tid in tasks["small"]:
        acc.claim("DailySmallGameLing", tid, "小游戏", got)
        nap(1.2)
    tgap()
    for tid in tasks["app"]:
        acc.claim("DailyAppLing", tid, "开App", got)
        nap(1.2)
    for tid in tasks["cate"]:
        acc.claim("DailyGameCateLing", tid, "游戏分类", got)
        nap(1.2)
    tgap()
    for tid in tasks["down"]:
        k, r = acc.claim("DailyDownGameLing", tid, "下载试玩", got)
        if k == "2002":
            need.append(f"#{tid} 下载试玩（要真下载过）")
        nap(1.2)
    for tid in tasks["inter"]:
        k, r = acc.claim("DailyInteractiveLing", tid, "好友互动", got)
        if k == "2002":
            need.append(f"#{tid} 好友互动（要先帮好友处理事件3次）")
        nap(1.2)
    for tid in tasks["jiaohu"]:
        k, r = acc.claim("DailyJiaohuLing", tid, "种草好友", got)
        if k == "2002":
            need.append(f"#{tid} 种草好友（要在好友页分享一次）")
        nap(1.2)
    tgap()
    for tid, title in tasks["yuyue"]:
        k, r = acc.claim("DailyYuyueLing", tid, "预约", got)
        if k == "2002":
            log(f"预约#{tid} 还没约 → {title}", acc.tag)
            need.append(f"#{tid} {title}")
        nap(1.2)

    tgap()
    try:
        cfg = acc.login().get("config", {})
        acc.cfg_data = cfg if isinstance(cfg, dict) else acc.cfg_data
        csd = _num(cfg.get("csd_jdt"))
        if csd is not None and csd >= 100:
            log("收尾 " + acc.harvest_plant(), acc.tag)
        elif str(cfg.get("grew")) == "-1":
            log("播种 " + str(acc.plant().get("key")), acc.tag)
        acc.produce_all()
        acc.buy_seeds()
        acc.buy_seed()
        cfg2 = acc.login().get("config") or {}
        acc.cfg_data = cfg2 if isinstance(cfg2, dict) else acc.cfg_data
        try:
            seed_left = int(cfg2.get("seed") or 0)
        except (TypeError, ValueError):
            seed_left = 0
        if seed_left <= 1:
            need.append(f"种子只剩 {cfg2.get('seed')} 个（青龙买不到，要手动补）")
        s = acc.sign()
        log("浇水 → " + str(s.get("key")) + ("（今日已浇）" if str(s.get("key")) == "1001" else ""), acc.tag)
    except Exception:
        log("收尾异常：" + traceback.format_exc(limit=1), acc.tag)
    return acc.nick, got, need


# ---------------------------------------------------------------------------
# 单账号执行
# ---------------------------------------------------------------------------

def run_account(index: int, account: Account, cfg: AppConfig,
                dry: bool = False, check: bool = False) -> dict[str, Any]:
    tag = "A%d" % index
    client = HykbClient(account, cfg, tag)
    result: dict[str, Any] = {
        "ok": False, "name": account.name, "nick": "", "message": "",
        "before": {}, "after": {}, "got": [], "need": [],
        "season_level": None, "season_score": None,
        "byf": None, "byf_level": None, "byf_today": None,
        "farm_rounds": 0, "steps": [],
    }
    log(f"👤 {account.name}", tag)
    try:
        if not client.load_page():
            result["message"] = "页面 token 拿不到"
            log(result["message"], tag)
            return result
        d = client.login()
        if d.get("loginStatus") != "100":
            result["message"] = f"登录失败 {d.get('key')}/{d.get('loginStatus')}"
            log(result["message"], tag)
            return result

        result["nick"] = client.nick
        result["before"] = snapshot(client.cfg_data)
        log(f"账号 {client.nick} | 爆米花 {_fmt_num(result['before']['baomihua'])} "
            f"成熟度 {result['before']['csd'] or '-'} 种子 {_fmt_num(result['before']['seed'])} "
            f"玉米 {_fmt_num(result['before']['corn'])}", tag)

        if check:
            result["ok"] = True
            result["message"] = "登录成功（仅校验）"
            result["after"] = result["before"]
            result["steps"].append("check")
            return result

        if dry:
            t = client.discover()
            result["ok"] = True
            result["message"] = (
                f"dry-run 登录成功：小游戏{len(t['small'])} 分享{len(t['share'])} "
                f"答题{len(t['dati'])} 开App{len(t['app'])} 分类{len(t['cate'])} "
                f"下载{len(t['down'])} 互动{len(t['inter'])} 种草{len(t['jiaohu'])} "
                f"预约{len(t['yuyue'])}"
            )
            result["after"] = result["before"]
            result["steps"].append("dry-run")
            return result

        tasks = phase_a(client, initialized=True)
        if not tasks:
            result["message"] = "阶段A失败"
            result["steps"].append("phase_a:fail")
            return result
        result["steps"].append("phase_a:ok")

        if cfg.wait_seconds > 0:
            log(f"等 {cfg.wait_seconds} 秒，把小游戏那 5 分钟走完…", tag)
            time.sleep(cfg.wait_seconds)

        nick, got, need = phase_b(client, tasks)
        result["nick"] = nick or result["nick"]
        result["got"] = got
        result["need"] = need
        result["season_level"] = client.season_level
        result["season_score"] = client.season_score
        result["byf"] = client.byf_value
        result["byf_level"] = client.byf_level
        result["byf_today"] = client.byf_today
        result["steps"].append("phase_b:ok")

        if cfg.farm_rounds > 0:
            n = client.farm(cfg.farm_rounds)
            result["farm_rounds"] = n
            if n:
                log(f"快玩重复 {n} 轮", tag)

        result["after"] = snapshot(client.cfg_data)
        result["ok"] = bool(got) or not need
        if result["ok"]:
            result["message"] = f"完成 {len(got)} 个奖励" + (f"，还差 {len(need)} 个" if need else "")
        else:
            result["message"] = f"未领到奖励，还差 {len(need)} 个"
    except Exception as e:
        result["message"] = f"{type(e).__name__}: {str(e)[:160]}"
        log("💥 " + result["message"], tag)
        logger.debug("exception traceback", exc_info=True)
    finally:
        client.s.close()
    return result


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------

def format_summary(results: list[tuple[str, dict[str, Any]]]) -> str:
    from datetime import datetime as _dt

    lines: list[str] = [f"📅 {_dt.now().strftime('%m-%d %H:%M')}", ""]
    ok_n = sum(1 for _, r in results if r.get("ok"))
    fail_n = len(results) - ok_n

    for i, (name, r) in enumerate(results):
        ok = bool(r.get("ok"))
        lines.append(f"{'✅' if ok else '❌'} {name}" + (f"（{r['nick']}）" if r.get("nick") else ""))
        msg = str(r.get("message") or "").strip()
        lines.append(f"   {'✅' if ok else '❌'} {msg}")

        before = r.get("before") or {}
        after = r.get("after") or {}
        b_bmh, a_bmh = before.get("baomihua"), after.get("baomihua")
        if isinstance(a_bmh, (int, float)):
            delta = ""
            if isinstance(b_bmh, (int, float)):
                d = round(a_bmh - b_bmh, 2)
                if abs(d) > 0:
                    delta = f"（{d:+g}）"
            lines.append(f"   🍿 爆米花：{_fmt_num(a_bmh)}{delta}")
        if after:
            lines.append(
                f"   🌱 种子：{_fmt_num(after.get('seed'))} · 玉米：{_fmt_num(after.get('corn'))}"
                f" · 成熟度：{after.get('csd') or '-'}"
            )
        if r.get("season_level") is not None:
            lines.append(f"   🏆 战令：Lv{r.get('season_level')} / 经验 {_fmt_num(r.get('season_score'))}")
        if r.get("byf") is not None:
            lines.append(
                f"   👥 爆友分：{_fmt_num(r.get('byf'))}（今日 {r.get('byf_today') or '-'}）"
                f" Lv{r.get('byf_level') or '-'}"
            )
        if r.get("got"):
            shown = r["got"][:12]
            lines.append("   ✅ 领到：" + "；".join(shown) + ("…" if len(r["got"]) > 12 else ""))
        if r.get("need"):
            lines.append("   ⚠️ 还差：" + "；".join(r["need"][:8]))
        if i < len(results) - 1:
            lines.append("")

    lines.append("")
    lines.append("────────")
    if fail_n == 0:
        lines.append(f"📊 合计：{ok_n}/{len(results)} 全部成功 🎉")
    elif ok_n == 0:
        lines.append(f"📊 合计：{ok_n}/{len(results)} 全部失败")
    else:
        lines.append(f"📊 合计：成功 {ok_n} · 失败 {fail_n}（共 {len(results)} 号）")
    return "\n".join(lines)


def format_notify_title(results: list[tuple[str, dict[str, Any]]]) -> str:
    ok_n = sum(1 for _, r in results if r.get("ok"))
    n = len(results)
    base = "好游快爆爆米花"
    if n == 0:
        return base
    if ok_n == n:
        base += f" ✅ {ok_n}/{n}"
    elif ok_n == 0:
        base += f" ❌ 0/{n}"
    else:
        base += f" ⚠️ {ok_n}/{n}"
    total_delta = 0.0
    for _, r in results:
        before = r.get("before") or {}
        after = r.get("after") or {}
        b, a = before.get("baomihua"), after.get("baomihua")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            total_delta += a - b
    if abs(total_delta) > 0:
        base += f" 爆米花{total_delta:+g}"
    return base


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
    payload: dict[str, Any] = {"title": title, "body": body, "group": cfg.bark_group}
    if cfg.bark_sound:
        payload["sound"] = cfg.bark_sound
    if cfg.bark_icon:
        payload["icon"] = cfg.bark_icon
    if cfg.bark_level:
        payload["level"] = cfg.bark_level
    try:
        r = requests.post(endpoint, json=payload, timeout=15)
        if r.status_code >= 400:
            get_url = f"{endpoint}/{quote(title[:100], safe='')}/{quote(body[:500], safe='')}"
            r = requests.get(get_url, timeout=15)
        logger.info("📣 Bark %s（HTTP %s）", "已推送" if r.status_code < 400 else "失败", r.status_code)
    except Exception as e:
        logger.warning("📣 Bark 推送失败: %s", e)


def send_serverchan(key: str, title: str, content: str) -> None:
    try:
        r = requests.post(
            f"https://sctapi.ftqq.com/{key}.send",
            data={"title": title, "desp": content}, timeout=15,
        )
        logger.info("📣 Server酱 %s（HTTP %s）", "已推送" if r.status_code < 400 else "失败", r.status_code)
    except Exception as e:
        logger.warning("📣 Server酱 推送失败: %s", e)


def send_notify(cfg: NotifyConfig, title: str, content: str) -> None:
    sent = False
    if cfg.bark_url or cfg.bark_key:
        send_bark(cfg, title, content)
        sent = True
    if cfg.serverchan_key:
        send_serverchan(cfg.serverchan_key, title, content)
        sent = True
    if cfg.webhook_url:
        try:
            r = requests.post(cfg.webhook_url, json={"title": title, "content": content}, timeout=15)
            logger.info("📣 Webhook 已推送（HTTP %s）", r.status_code)
            sent = True
        except Exception as e:
            logger.warning("📣 Webhook 推送失败: %s", e)
    if not sent:
        logger.info("📣 未配置 Bark/通知渠道，跳过推送")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
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
        logger.info("📦 已从环境变量加载 %d 个账号", len(env_cfg.accounts))
        return env_cfg
    local = SCRIPT_DIR / "config.yaml"
    if local.is_file():
        logger.info("📦 使用本地配置: %s", local)
        return load_config_yaml(local)
    raise FileNotFoundError(
        "未找到账号配置。\n"
        "青龙：设置 HYKB_ACCOUNTS 或 HYKB_COOKIE（scookie 值）\n"
        "本地：cp config.example.yaml config.yaml 并填写"
    )


def main() -> int:
    global SAFE
    parser = argparse.ArgumentParser(description="好游快爆爆米花每日任务（协议版）")
    parser.add_argument("-c", "--config", help="本地 yaml 配置路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    parser.add_argument("--check", action="store_true", help="只登录校验 scookie，不做任务")
    parser.add_argument("--dry-run", "--dry", dest="dry", action="store_true",
                        help="登录并发现任务，不做任何写操作")
    parser.add_argument("--nowait", action="store_true", help="跳过阶段 A→B 的等待")
    args = parser.parse_args()

    setup_logging(args.verbose)

    try:
        cfg = resolve_config(args)
    except Exception as e:
        logger.error("❌ %s", e)
        return 2

    SAFE = cfg.safe
    if not cfg.answer_bank:
        cfg.answer_bank = str(SCRIPT_DIR / "hykb_answers.json")
    if args.nowait:
        cfg.wait_seconds = 0

    dry = bool(args.dry)
    check = bool(args.check)
    if (dry or check) and cfg.wait_seconds > 0:
        cfg.wait_seconds = 0

    logger.info("🚀 好游快爆 · 爆米花")
    logger.info(
        "   账号 %d 个 · 安全模式 %s · 通知 %s · 等待 %ss · 快玩重复 %d",
        len(cfg.accounts),
        "开" if cfg.safe else "关",
        "开" if cfg.notify.enabled() else "关",
        cfg.wait_seconds,
        cfg.farm_rounds,
    )

    if cfg.safe and not (dry or check):
        d = random.uniform(*START_JITTER)
        logger.info("随机等待 %.0f 秒再开跑，避开整点", d)
        time.sleep(d)

    results: list[tuple[str, dict[str, Any]]] = []
    for i, acc in enumerate(cfg.accounts, 1):
        log_banner(f"👤 {acc.name}")
        result = run_account(i, acc, cfg, dry=dry, check=check)
        if result.get("ok"):
            logger.info("[%s] ✅ %s", acc.name, result.get("message") or "OK")
        else:
            logger.error("[%s] ❌ %s", acc.name, result.get("message") or "失败")
        results.append((acc.name, result))
        if i < len(cfg.accounts):
            logger.info("⏳ 等待 %d 秒后执行下一账号…", cfg.inter_account_delay)
            time.sleep(max(0, cfg.inter_account_delay))

    summary = format_summary(results)
    title = format_notify_title(results)
    logger.info("")
    log_banner("执行结果")
    for line in summary.splitlines():
        logger.info("%s", line)
    send_notify(cfg.notify, title, summary)

    any_fail = any(not r.get("ok") for _, r in results)
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
