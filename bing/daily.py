#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
必应积分助手（国内版）

cron: 20 8 * * *
new Env('必应积分助手');

基于社区脚本「必应积分助手 v1.4.1」（作者 满天星 / By-cyt）重写为仓库统一风格：
  读取 cn.bing.com 登录 Cookie，自动完成每日搜索、每日集、每日问答、精选任务，
  领取待领取积分，并展示连续打卡进度与今日未完成项。

青龙环境变量（账号，必填，多账号 & / 换行 / # 分隔）：
  BING_COOKIE   完整 Cookie（cn.bing.com，浏览器 F12 → Application → Cookies 全选复制）
  兼容原变量：by（写法相同）
  或 BING_ACCOUNTS：
    [{"name":"主号","cookie":"MUID=...; _U=..."}]

可选：
  BING_SEARCH_TIMES        每日搜索目标次数（默认 15，最多 20）
  BING_DELAY               搜索/任务间隔秒，格式 "3-8"（默认 3-8）
  BING_WAIT_SECONDS        最终积分查询前等待秒（默认 60）
  BING_OFFERS              是否执行每日精选任务（默认 1）
  BING_CHECKIN             是否尝试每日签到（默认 1）
  BING_CLAIM               是否领取待领取积分（默认 1）
  BING_TIMEOUT             请求超时秒（默认 20）
  BING_INTER_ACCOUNT_DELAY 账号间隔秒（默认 5）

通知（与 hifiti / huazhu 等共用）：
  BARK_URL 或 BARK_KEY [+ BARK_SERVER]
  BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL
  PUSHPLUS_TOKEN / PUSHPLUS_TOPIC
  青龙环境自动调用 notify.py

依赖：requests（本地 yaml 再装 PyYAML）
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, quote, unquote_plus, urlencode, urlparse

import requests

SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

APP_NAME = "必应积分"
VERSION = "1.5.0"

BASE = "https://cn.bing.com"
REWARDS_PANEL = "https://cn.bing.com/rewards/panelflyout?channel=bingflyout&partnerId=BingRewards"
REWARDS_API = "https://rewards.bing.com/api/getuserinfo?type=1"
EARN_PANEL = "https://rewards.bing.com/earn"
DASHBOARD = "https://rewards.bing.com/dashboard"

PC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0"
)

# /earn 路由的 Next Router State Tree（与账号无关，路由结构固定）
EARN_ROUTER_TREE = (
    "%5B%22%22%2C%7B%22children%22%3A%5B%22(nav)%22%2C%7B%22children%22%3A"
    "%5B%22earn%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2Cnull%2Cnull%2C0%5D"
    "%7D%2Cnull%2Cnull%2C0%5D%7D%2Cnull%2Cnull%2C0%5D%7D%2Cnull%2Cnull%2C16%5D"
)

# 领取积分（Next.js Server Action）；ID 随微软发版会变，失败时会自动从线上 JS 重新提取
CLAIM_ACTION_ID = "00491296f1d668ad46b65342c95cb9d72a62c1fa9d"
REPORT_ACTION_ID = "707e6eb15bdfdd5fba193f0a77e934f7018faf87ce"

DEFAULT_BARK_SERVER = "https://api.day.app"
DEFAULT_BARK_GROUP = "必应积分"
DEFAULT_TIMEOUT = 20
DEFAULT_SEARCH_TIMES = 15
DEFAULT_DELAY_MIN = 3
DEFAULT_DELAY_MAX = 8
DEFAULT_WAIT_SECONDS = 60
DEFAULT_INTER_ACCOUNT_DELAY = 5

MISSING_CONFIG_HINT = (
    "❌ 未找到账号配置。\n"
    "📝 青龙：设置 BING_COOKIE = 完整的 cn.bing.com Cookie（多账号 & 或换行分隔）\n"
    "📝 本地：cp config.example.yaml config.yaml 并填写"
)

PARTIAL_COOKIE_HINT = (
    "Cookie 缺少 _U 登录态：可能只复制了部分 Cookie。请在浏览器 Network "
    "面板复制完整请求头 Cookie，而不是 Applications 里的部分行"
)

REWARDS_SESSION_HINT = (
    "Bing 已登录，但 rewards.bing.com 仍要求登录（缺少 Rewards/登录站点 Cookie）。"
    "请先在浏览器打开 https://rewards.bing.com/earn 确认能看到积分，"
    "再复制该页请求头里的完整 Cookie"
)

STREAK_LABELS = {
    "bing": "必应搜索",
    "dailyset": "每日集",
    "edge": "Edge 浏览 30 分钟",
    "bingapp": "必应App 签到",
    "dailystreak": "每日连续打卡总天数",
    "msn": "MSN 文章",
    "outlook": "Outlook",
    "visualsearch": "视觉搜索",
}

# 正常人类搜索词库（分类随机，避免奇怪句子）
NORMAL_SEARCH_TERMS = [
    "今天天气", "天气预报", "附近美食推荐", "家常菜做法", "早餐吃什么",
    "晚餐食谱", "减肥餐", "快递查询", "火车票", "机票价格",
    "附近酒店", "超市营业时间", "药店", "医院挂号", "公交路线",
    "地铁线路", "打车优惠", "外卖优惠券", "家政服务", "搬家公司",
    "水电缴费", "燃气费查询", "物业费", "停车位", "洗车",
    "汽车保养", "违章查询", "驾照换证", "身份证办理", "社保查询",
    "公积金", "个税计算", "银行利率", "理财产品", "保险推荐",
    "最新手机推荐", "笔记本电脑排行", "科技新闻", "AI工具", "Python教程",
    "软件下载", "电脑技巧", "WiFi设置", "路由器推荐", "固态硬盘",
    "机械键盘", "鼠标推荐", "显示器推荐", "显卡排行", "CPU对比",
    "主板推荐", "电源推荐", "机箱推荐", "散热器", "耳机推荐",
    "音箱推荐", "智能手表", "手环推荐", "平板推荐", "电子书阅读器",
    "投影仪", "扫地机器人", "空气净化器", "加湿器", "电动牙刷",
    "电影推荐", "电视剧排行", "音乐排行榜", "游戏攻略", "小说推荐",
    "旅游攻略", "景点推荐", "拍照技巧", "综艺推荐", "演唱会门票",
    "话剧演出", "展览推荐", "博物馆", "动物园", "游乐园",
    "滑雪场", "温泉", "民宿推荐", "露营装备", "钓鱼技巧",
    "宠物饲养", "花卉养殖", "手工DIY", "绘画教程", "书法入门",
    "吉他教程", "钢琴入门", "舞蹈教学", "健身计划", "瑜伽入门",
    "英语学习", "考研资料", "公务员考试", "在线课程", "学习方法",
    "知识问答", "读书笔记", "考证", "雅思", "托福",
    "四六级", "教师资格证", "会计证", "心理咨询师", "健康管理师",
    "编程入门", "数据分析", "设计教程", "办公软件技巧", "PPT模板",
    "Excel技巧", "Word教程", "简历模板", "面试技巧", "职场沟通",
    "淘宝热销", "京东比价", "优惠券", "打折", "性价比推荐",
    "商品评价", "品牌对比", "拼多多", "双十一", "618",
    "年货节", "双十二", "会员日", "秒杀", "团购",
    "海淘", "代购", "奢侈品", "二手交易", "闲鱼",
    "转转", "得物", "小红书种草", "什么值得买", "慢慢买",
    "今日新闻", "热点事件", "热搜榜", "微博热搜", "知乎热榜",
    "抖音热点", "B站热门", "头条新闻", "澎湃新闻", "36氪",
    "虎嗅", "知乎日报", "少数派", "差评", "酷安",
    "IT之家", "快科技", "太平洋电脑网", "中关村在线", "汽车之家",
]

IS_DEBUG = False

# 青龙面板统一通知
_ql_notify = None
try:
    from notify import send as _ql_notify  # type: ignore
except Exception:
    try:
        from utils.notify import send as _ql_notify  # type: ignore
    except Exception:
        _ql_notify = None


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

def log(msg: str = "") -> None:
    print(msg, flush=True)


def debug(msg: str) -> None:
    if IS_DEBUG:
        print(f"🔍 [DEBUG] {msg}", flush=True)


def section(title: str) -> None:
    log(f"======= {title} =======")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    cookie: str


@dataclass
class NotifyConfig:
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = DEFAULT_BARK_GROUP
    bark_sound: str = ""
    bark_icon: str = ""
    bark_level: str = ""
    pushplus_token: str = ""
    pushplus_topic: str = ""

    def bark_enabled(self) -> bool:
        return bool(self.bark_url or self.bark_key)


@dataclass
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    search_times: int = DEFAULT_SEARCH_TIMES
    delay_min: int = DEFAULT_DELAY_MIN
    delay_max: int = DEFAULT_DELAY_MAX
    wait_seconds: int = DEFAULT_WAIT_SECONDS
    offers: bool = True
    checkin: bool = True
    claim: bool = True
    timeout: int = DEFAULT_TIMEOUT
    inter_account_delay: int = DEFAULT_INTER_ACCOUNT_DELAY
    user_agent: str = PC_UA


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value is not None and value.strip() else default


def _env_int(name: str, default: int, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() not in ("0", "false", "no", "off")


def _normalize_bark(url: str, key: str) -> tuple[str, str]:
    url, key = (url or "").strip(), (key or "").strip()
    if url and not url.startswith("http"):
        key = key or url
        url = ""
    return url, key


def load_notify_from_env() -> NotifyConfig:
    bark_url, bark_key = _normalize_bark(
        _env("BARK_URL") or _env("BARK_PUSH"),
        _env("BARK_KEY") or _env("BARK_DEVICE_KEY"),
    )
    return NotifyConfig(
        bark_url=bark_url,
        bark_key=bark_key,
        bark_server=_env("BARK_SERVER", DEFAULT_BARK_SERVER).rstrip("/"),
        bark_group=_env("BARK_GROUP", DEFAULT_BARK_GROUP) or DEFAULT_BARK_GROUP,
        bark_sound=_env("BARK_SOUND"),
        bark_icon=_env("BARK_ICON"),
        bark_level=_env("BARK_LEVEL"),
        pushplus_token=_env("PUSHPLUS_TOKEN"),
        pushplus_topic=_env("PUSHPLUS_TOPIC"),
    )


def normalize_cookie(raw: str) -> str:
    text = (raw or "").strip()
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    return text


def parse_cookie(raw: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in normalize_cookie(raw).split(";"):
        item = part.strip()
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key, value = key.strip(), value.strip()
        if key:
            cookies[key] = value
    return cookies


def account_identity(account: Account) -> str:
    cookies = parse_cookie(account.cookie)
    for key in ("_U", "MUID", "SRCHUID"):
        if cookies.get(key):
            return f"{key}:{cookies[key]}"
    return f"cookie:{account.cookie}"


def _parse_account_item(item: dict[str, Any], index: int) -> Optional[Account]:
    cookie = normalize_cookie(
        str(item.get("cookie") or item.get("bing_cookie") or item.get("ck") or "")
    )
    if not cookie or "=" not in cookie:
        return None
    name = str(
        item.get("name") or item.get("note") or item.get("remark") or f"账号{index}"
    ).strip()
    return Account(name=name, cookie=cookie)


def _parse_accounts_json(raw: str) -> list[Account]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("BING_ACCOUNTS 必须是 JSON 数组")
    accounts: list[Account] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"BING_ACCOUNTS[{i}] 必须是对象")
        acc = _parse_account_item(item, i + 1)
        if acc:
            accounts.append(acc)
    return accounts


def _parse_accounts_from_env() -> list[Account]:
    raw_json = _env("BING_ACCOUNTS")
    if raw_json:
        try:
            accounts = _parse_accounts_json(raw_json)
            if accounts:
                return accounts
        except Exception as exc:
            log(f"⚠️ BING_ACCOUNTS 解析失败，回退到分隔字符串：{exc}")

    raw = _env("BING_COOKIE") or _env("BING_COOKIES") or _env("by")
    accounts: list[Account] = []
    for i, part in enumerate(re.split(r"[&\n#]", raw), 1):
        cookie = normalize_cookie(part)
        if not cookie or "=" not in cookie:
            continue
        accounts.append(Account(name=f"账号{i}", cookie=cookie))
    return accounts


def _merge_accounts(*groups: list[Account]) -> list[Account]:
    seen: set[str] = set()
    merged: list[Account] = []
    for group in groups:
        for acc in group:
            ident = account_identity(acc)
            if ident in seen:
                continue
            seen.add(ident)
            merged.append(acc)
    return merged


def _parse_delay(value: str, default: tuple[int, int] = (DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX)) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\s*[-,~ ]\s*(\d+)\s*", value or "")
    if not match:
        return default
    low, high = int(match.group(1)), int(match.group(2))
    return (low, high) if low <= high else (high, low)


def load_config_yaml(path: Path) -> AppConfig:
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("本地 yaml 配置需要 PyYAML：pip install PyYAML") from exc
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    accounts: list[Account] = []
    for i, item in enumerate(raw.get("accounts") or [], 1):
        if not isinstance(item, dict):
            raise ValueError(f"accounts[{i - 1}] 格式错误")
        acc = _parse_account_item(item, i)
        if acc:
            accounts.append(acc)

    delay_value = str(raw.get("delay") or "")
    if delay_value:
        delay_min, delay_max = _parse_delay(delay_value)
    else:
        raw_min = raw.get("delay_min")
        raw_max = raw.get("delay_max")
        delay_min = int(raw_min) if raw_min is not None else DEFAULT_DELAY_MIN
        delay_max = int(raw_max) if raw_max is not None else DEFAULT_DELAY_MAX
        if delay_min > delay_max:
            delay_min, delay_max = delay_max, delay_min

    raw_wait = raw.get("wait_seconds")
    wait_seconds = int(raw_wait) if raw_wait is not None else DEFAULT_WAIT_SECONDS
    raw_inter = raw.get("inter_account_delay")
    inter_account_delay = (
        int(raw_inter) if raw_inter is not None else DEFAULT_INTER_ACCOUNT_DELAY
    )

    bark = raw.get("bark") or raw.get("notify") or {}
    pushplus = raw.get("pushplus") or {}
    env_notify = load_notify_from_env()
    bark_url, bark_key = _normalize_bark(
        str(bark.get("url") or bark.get("bark_url") or ""),
        str(bark.get("key") or bark.get("bark_key") or ""),
    )
    notify = NotifyConfig(
        bark_url=env_notify.bark_url or bark_url,
        bark_key=env_notify.bark_key or bark_key,
        bark_server=(
            env_notify.bark_server
            if env_notify.bark_enabled()
            else str(bark.get("server") or DEFAULT_BARK_SERVER)
        ).rstrip("/"),
        bark_group=_env("BARK_GROUP") or str(bark.get("group") or DEFAULT_BARK_GROUP),
        bark_sound=env_notify.bark_sound or str(bark.get("sound") or ""),
        bark_icon=env_notify.bark_icon or str(bark.get("icon") or ""),
        bark_level=env_notify.bark_level or str(bark.get("level") or ""),
        pushplus_token=env_notify.pushplus_token or str(pushplus.get("token") or ""),
        pushplus_topic=env_notify.pushplus_topic or str(pushplus.get("topic") or ""),
    )
    return AppConfig(
        accounts=accounts,
        notify=notify,
        search_times=max(1, min(int(raw.get("search_times") or DEFAULT_SEARCH_TIMES), 20)),
        delay_min=delay_min,
        delay_max=delay_max,
        wait_seconds=max(0, min(wait_seconds, 300)),
        offers=bool(raw.get("offers", True)),
        checkin=bool(raw.get("checkin", True)),
        claim=bool(raw.get("claim", True)),
        timeout=int(raw.get("timeout") or DEFAULT_TIMEOUT),
        inter_account_delay=max(0, min(inter_account_delay, 120)),
        user_agent=str(raw.get("user_agent") or PC_UA),
    )


def resolve_config(config_path: Optional[str] = None) -> AppConfig:
    yaml_path = Path(config_path).expanduser() if config_path else SCRIPT_DIR / "config.yaml"
    yaml_cfg = load_config_yaml(yaml_path) if yaml_path.is_file() else None

    env_accounts = _parse_accounts_from_env()
    yaml_accounts = list(yaml_cfg.accounts) if yaml_cfg else []
    accounts = _merge_accounts(env_accounts, yaml_accounts)
    if not accounts:
        raise FileNotFoundError(MISSING_CONFIG_HINT)

    cfg = yaml_cfg or AppConfig()
    cfg.accounts = accounts
    if yaml_cfg is None:
        cfg.notify = load_notify_from_env()

    cfg.search_times = _env_int("BING_SEARCH_TIMES", cfg.search_times, 1, 20)
    if _env("BING_DELAY"):
        cfg.delay_min, cfg.delay_max = _parse_delay(
            _env("BING_DELAY"), (cfg.delay_min, cfg.delay_max)
        )
    cfg.wait_seconds = _env_int("BING_WAIT_SECONDS", cfg.wait_seconds, 0, 300)
    cfg.offers = _env_bool("BING_OFFERS", cfg.offers)
    cfg.checkin = _env_bool("BING_CHECKIN", cfg.checkin)
    cfg.claim = _env_bool("BING_CLAIM", cfg.claim)
    cfg.timeout = _env_int("BING_TIMEOUT", cfg.timeout, 5, 120)
    cfg.inter_account_delay = _env_int(
        "BING_INTER_ACCOUNT_DELAY", cfg.inter_account_delay, 0, 120
    )
    cfg.user_agent = _env("BING_UA") or cfg.user_agent or PC_UA
    return cfg


# ---------------------------------------------------------------------------
# HTTP 与基础解析
# ---------------------------------------------------------------------------

def make_session(cookie_str: str) -> requests.Session:
    session = requests.Session()
    session.cookies.update(parse_cookie(cookie_str))
    session.headers.update({"User-Agent": PC_UA})
    return session


def get_headers(ua: str = PC_UA, referer: Optional[str] = None) -> dict[str, str]:
    headers = {
        "User-Agent": ua,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def get_username(session: requests.Session) -> Optional[str]:
    """从必应首页获取账号名称。"""
    try:
        r = session.get(f"{BASE}/", headers=get_headers(PC_UA), timeout=10)
        match = re.search(r'id="id_n"[^>]*>([^<]+)<', r.text)
        if match:
            return match.group(1).strip()
    except Exception as exc:
        debug(f"获取用户名失败: {exc}")
    return None


def get_search_term(used_terms: set[str]) -> str:
    """生成正常人类搜索词，随机词库 + 随机修饰，去重。"""
    for _ in range(30):
        base = random.choice(NORMAL_SEARCH_TERMS)
        modifier = random.choice(
            ["", "", "", "", "2026", "最新", "推荐", "攻略", "大全", "哪个好", "怎么样", "2026年", "排行"]
        )
        term = f"{base} {modifier}".strip() if modifier else base
        if term not in used_terms and 0 < len(term) <= 30:
            used_terms.add(term)
            return term
    return f"{random.choice(NORMAL_SEARCH_TERMS)} {int(time.time()) % 1000}"


def do_search(session: requests.Session, term: str) -> bool:
    """执行一次搜索（必须带 form=QBRE 才计入每日搜索积分）。"""
    try:
        r = session.get(
            f"{BASE}/search",
            params={"q": term, "form": "QBRE"},
            headers=get_headers(PC_UA, f"{BASE}/"),
            timeout=15,
        )
        return r.status_code == 200
    except Exception as exc:
        log(f"  搜索异常: {exc}")
        return False


def extract_daily_set_activities(html: str) -> list[dict[str, Any]]:
    """提取每日集活动（兼容 2026-11 新结构与旧的 destinationUrl）。"""
    activities: list[dict[str, Any]] = []
    if not html:
        return activities
    text = html.replace('\\"', '"')
    seen: set[str] = set()

    for match in re.finditer(r'"offerId"\s*:\s*"(Gamification_DailySet[^"]*)"', text):
        offer_id = match.group(1)
        if offer_id in seen:
            continue
        start = text.rfind('{"date"', max(0, match.start() - 2000), match.start())
        block = text[start if start > 0 else max(0, match.start() - 1500) : match.end() + 300]
        dest = re.search(r'"destination"\s*:\s*"(https?://[^"]+)"', block)
        if not dest:
            continue
        done = re.search(r'"isCompleted"\s*:\s*(true|false)', block)
        points = re.search(r'"points"\s*:\s*([0-9]+)', block)
        title = re.search(r'"title"\s*:\s*"([^"]*)"', block)
        offer_hash = re.search(r'"hash"\s*:\s*"([0-9a-f]{40,64})"', block)
        seen.add(offer_id)
        activities.append(
            {
                "hash": offer_hash.group(1) if offer_hash else "",
                "url": dest.group(1)
                .replace("\\u0026", "&")
                .replace("&amp;", "&")
                .replace('\\"', '"'),
                "complete": bool(done and done.group(1) == "true"),
                "offer_id": offer_id,
                "points": int(points.group(1)) if points else 0,
                "title": title.group(1) if title else offer_id[-8:],
            }
        )
    if activities:
        return activities

    urls = re.findall(r'"destinationUrl"\s*:\s*"(https?://[^"]*bing\.com/search\?[^"]*)"', html)
    for url in urls:
        url = url.replace("\\u0026", "&").replace("&amp;", "&").replace("\\u0022", "%22")
        if any(k in url for k in ["rnoreward", "DailySet", "ML2X9E", "ML2X9F", "tgrew4", "ML2G76"]):
            if url not in seen:
                seen.add(url)
                activities.append(
                    {"url": url, "complete": False, "offer_id": "", "points": 0, "title": ""}
                )
    return activities


def get_daily_set_status(html: str) -> tuple[Optional[int], Optional[int]]:
    """获取每日集完成状态，如 (1, 3)。"""
    text = (html or "").replace('\\"', '"')
    match = re.search(
        r'"type"\s*:\s*"dailyset"[^}]*?"activitiesCompleted"\s*:\s*(\d+)'
        r'[^}]*?"activitiesTotal"\s*:\s*(\d+)',
        text,
        re.S,
    )
    if match:
        return int(match.group(1)), int(match.group(2))
    m1 = re.search(r'partner_dset_titleArg0"\s*:\s*"(\d+)"', html)
    m2 = re.search(r'partner_dset_titleArg1"\s*:\s*"(\d+)"', html)
    if m1 and m2:
        return int(m1.group(1)), int(m2.group(1))
    match = re.search(r"每日集\((\d+)/(\d+)\s*活动\)", html)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def get_daily_search_status(html: str) -> tuple[Optional[int], Optional[int]]:
    """获取每日搜索积分状态，返回 (已赚, 上限)。"""
    if not html:
        return None, None
    for match in re.finditer(r'"pointProgressMax"\s*:\s*15\s*,\s*"pointProgress"\s*:\s*(\d+)', html):
        return int(match.group(1)), 15
    for match in re.finditer(r'"pointProgress"\s*:\s*(\d+)\s*,\s*"pointProgressMax"\s*:\s*15', html):
        return int(match.group(1)), 15
    text = html.replace('\\"', '"')
    match = re.search(r'"pc"\s*:\s*\{\s*"max"\s*:\s*(\d+)\s*,\s*"progress"\s*:\s*(\d+)', text)
    if match:
        return int(match.group(2)), int(match.group(1))
    for match in re.finditer(r'pointProgressMax\\?"\s*:\s*(\d+)\s*,\s*\\?"pointProgress\\?"\s*:\s*(\d+)', html):
        maximum, current = int(match.group(1)), int(match.group(2))
        if 0 < current <= maximum <= 60:
            return current, maximum
    return None, None


def extract_ig_iid(html: str) -> tuple[str, str]:
    ig, iid = "", "SERP.5057"
    match = re.search(r'IG["\s:=]+([A-Fa-f0-9]{32})', html)
    if match:
        ig = match.group(1)
    match = re.search(r'IID["\s:=]+(SERP\.\d+)', html)
    if match:
        iid = match.group(1)
    return ig, iid


def extract_quiz_total(html: str) -> Optional[int]:
    for match in re.finditer(r"(\d+)\s*/\s*(\d+)", html):
        current, total = int(match.group(1)), int(match.group(2))
        if total in (3, 5, 7, 10) and 1 <= current <= total:
            return total
    return None


def get_quiz_panel_status(html: str, quiz_url: str) -> tuple[Optional[bool], Optional[int]]:
    match = re.search(r"[?&]q=([^&]+)", quiz_url)
    if not match:
        return None, None
    query = match.group(1)
    for item in re.finditer(r'destinationUrl"\s*:\s*"([^"]*)"', html, re.I):
        if query in item.group(1):
            block = html[max(0, item.start() - 2000) : min(len(html), item.end() + 300)]
            progress = re.search(r'"pointProgress"\s*:\s*(\d+)', block)
            max_progress = re.search(r'"pointProgressMax"\s*:\s*(\d+)', block)
            if progress and max_progress:
                return (
                    int(progress.group(1)) >= int(max_progress.group(1)),
                    int(max_progress.group(1)),
                )
    return None, None


def report_activity(session: requests.Session, activity_url: str, page_html: str, ig: str, iid: str) -> bool:
    """调用旧版 reportActivity 接口触发积分（兜底）。"""
    parsed = urlparse(activity_url.replace("www.bing.com", "cn.bing.com"))
    params = parse_qs(parsed.query)
    report_params = {"IG": ig, "IID": iid, "q": params.get("q", [""])[0]}
    for key in ["form", "FORM", "OCID", "PUBL", "CREA", "filters"]:
        if key in params:
            report_params[key] = params[key][0]
    report_params["rnoreward"] = "1"
    report_params["ajaxreq"] = "1"

    report_url = "https://cn.bing.com/rewardsapp/reportActivity?" + urlencode(report_params)
    try:
        r = session.post(
            report_url,
            headers={
                "User-Agent": PC_UA,
                "Referer": activity_url.replace("www.bing.com", "cn.bing.com"),
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
            timeout=15,
        )
        return r.status_code == 200
    except Exception:
        return False


def report_offer_v2(
    session: requests.Session,
    page_html: str,
    offer_hash: str,
    offer_id: str,
    referer: Optional[str] = None,
) -> bool:
    """走 Rewards 新版 Server Action 上报活动完成。"""
    url = "https://rewards.bing.com/earn?section=streaks"
    body = json.dumps(
        [offer_hash, 11, {"offerid": offer_id, "isPromotional": "$undefined", "timezoneOffset": "-480"}],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    headers = _action_headers(page_html, referer or url, REPORT_ACTION_ID)
    headers["next-router-state-tree"] = EARN_ROUTER_TREE
    try:
        r = session.post(url, headers=headers, data=body, timeout=20)
        if r.status_code >= 400:
            return False
        return "1:true" in (r.text or "")
    except Exception:
        return False


def complete_daily_set(session: requests.Session, delay_min: int, delay_max: int) -> tuple[int, int]:
    """完成每日集活动，返回 (完成数, 总数)。"""
    section("每日集")
    html = get_earn_page(session)
    if not html:
        try:
            r = session.get(REWARDS_PANEL, headers=get_headers(PC_UA), timeout=15)
            html = r.text if r.status_code == 200 else ""
        except Exception as exc:
            log(f"  面板访问异常: {exc}")
            return 0, 0
    if not html:
        log("  面板访问失败")
        return 0, 0

    done, total = get_daily_set_status(html)
    if done is not None:
        log(f" 当前进度: {done}/{total}")
        if done >= total:
            log(" ✅ 每日集已全部完成")
            return done, total

    activities = extract_daily_set_activities(html)
    log(f"  提取到 {len(activities)} 个活动")
    pending = [act for act in activities if not act["complete"]]
    log(f"  未完成: {len(pending)} 个")

    for index, act in enumerate(pending):
        url = act["url"]
        log(f"  活动[{index + 1}]: {act['title'] or url[:50]} (+{act['points']}分)")
        page = ""
        try:
            r = session.get(url, headers=get_headers(PC_UA, "https://rewards.bing.com/earn"), timeout=20)
            if r.status_code == 200:
                page = r.text
            else:
                log(f"    页面 status={r.status_code}")
        except Exception as exc:
            log(f"    页面异常: {exc}")

        ok = False
        offer_hash = act.get("hash", "")
        if offer_hash and act.get("offer_id"):
            ok = report_offer_v2(
                session, html, offer_hash, act["offer_id"], "https://rewards.bing.com/earn?section=streaks"
            )
            log(f"    {'✅ 积分已触发' if ok else '❌ 新版上报失败'}")

        if not ok and page:
            ig, iid = extract_ig_iid(page)
            if ig:
                ok = report_activity(session, url, page, ig, iid)
                log(f"    {'✅ 旧接口已触发' if ok else '❌ 旧接口失败'}")
        time.sleep(random.randint(delay_min, delay_max))

    html2 = get_earn_page(session)
    done2, total2 = get_daily_set_status(html2)
    if done2 is not None:
        log(f"  最终进度: {done2}/{total2}")
        return done2, total2
    return done or 0, total or 0


def extract_quiz_from_html(html: str) -> tuple[Optional[str], Optional[list[dict[str, str]]], str]:
    """从页面 HTML 提取 quiz 问题和选项，返回 (question, options, user_id)。"""
    opt_pattern = (
        r'''class=["'][^"']*btq_opt[^"']*["'][\s\S]*?'''
        r'''href=["']([^"']+)["'][\s\S]*?'''
        r'''acf-button-standard__label["'][^>]*>([^<]+)</div>'''
    )
    options: list[dict[str, str]] = []
    for match in re.finditer(opt_pattern, html):
        href = match.group(1).replace("&amp;", "&")
        text = match.group(2).strip()
        q_match = re.search(r"[?&]q=([^&]+)", href)
        correct = unquote_plus(q_match[1]) if q_match else ""
        options.append({"text": text, "href": href, "correct": correct})

    if not options:
        return None, None, ""

    question = ""
    q_match = re.search(r"([^<>]{10,200})</div>\s*</div>\s*<div class=[\"']btq_opts", html)
    if q_match:
        question = q_match.group(1).strip()
    if not question:
        q_match = re.search(r"btq_title[\"'][^>]*>([\s\S]{0,300})", html)
        if q_match:
            question = re.sub(r"<[^>]+>", "", q_match.group(1)).strip()[:100]

    uid_match = re.search(r'"UserId"\s*:\s*"([^"]+)"', html)
    user_id = uid_match.group(1) if uid_match else ""
    return question, options, user_id


def complete_quiz(session: requests.Session, quiz_url: str, delay_min: int, delay_max: int) -> int:
    """完成一个 Quiz 的所有题目（自动提取正确答案）。"""
    quiz_url = quiz_url.replace("www.bing.com", "cn.bing.com")
    current_url = quiz_url
    completed = 0

    for round_num in range(10):
        try:
            r = session.get(current_url, headers=get_headers(PC_UA), timeout=15)
            if r.status_code != 200:
                break

            question, options, user_id = extract_quiz_from_html(r.text)
            if not options:
                if round_num == 0:
                    section("每日问答")
                    total_q = extract_quiz_total(r.text)
                    if total_q:
                        log(f" 当前进度: {total_q}/{total_q}")
                    log(" ✅ 每日问答已全部完成")
                return completed

            if round_num == 0:
                section("每日问答")

            correct_answer = options[0]["correct"]
            correct_opt = next((opt for opt in options if correct_answer in opt["text"]), None)
            if not correct_opt:
                correct_opt = options[-1]

            log(f"  {round_num + 1}. {(question or '')[:45]}")
            log(f"     正在查找正确答案→ {correct_opt['text']}")

            try:
                session.post(
                    "https://www.bing.com/funapi/api/quiz/record?ajaxreq=1",
                    json={
                        "PartnerId": "BingQAUX",
                        "QuestionText": question,
                        "OptionText": correct_opt["text"],
                        "UserId": user_id,
                    },
                    headers={
                        "User-Agent": PC_UA,
                        "Content-Type": "application/json",
                        "Referer": current_url,
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=10,
                )
            except Exception as exc:
                log(f"    quiz/record 异常: {exc}")

            ig, iid = extract_ig_iid(r.text)
            opt_full_url = correct_opt["href"]
            if opt_full_url.startswith("/"):
                opt_full_url = "https://cn.bing.com" + opt_full_url
            report_activity(session, opt_full_url, r.text, ig, iid)

            completed += 1
            current_url = opt_full_url
            time.sleep(random.randint(delay_min, delay_max))
        except Exception as exc:
            log(f"  第{round_num + 1}题异常: {exc}")
            break

    if completed > 0:
        log(f"  🎉 全部答完（共 {completed} 题）")
    return completed


def extract_quiz_urls(html: str) -> list[str]:
    """从 Rewards 面板提取所有 Quiz URL（排除每日集活动）。"""
    urls: list[str] = []
    for match in re.finditer(r'"destinationUrl"\s*:\s*"(https?://[^"]*bing\.com/search\?[^"]*)"', html, re.I):
        url = match.group(1).replace("\\u0026", "&")
        low = url.lower()
        if ("quiz" in low or "quote" in low) and "dailyset" not in low and "rnoreward" not in low:
            if url not in urls:
                urls.append(url)
    return urls


def check_points(session: requests.Session) -> Optional[int]:
    """查询积分（rewards.bing.com 不通时回退到 cn.bing.com 面板）。"""
    try:
        r = session.get(
            REWARDS_API,
            timeout=8,
            headers={"Accept": "application/json", "Referer": "https://rewards.bing.com/", "User-Agent": PC_UA},
        )
        if r.status_code == 200:
            data = r.json()
            pts = data.get("dashboard", {}).get("userStatus", {}).get("availablePoints", 0)
            if pts:
                return pts
    except Exception:
        pass
    try:
        r = session.get(REWARDS_PANEL, headers=get_headers(PC_UA), timeout=8)
        if r.status_code == 200:
            for pattern in [
                r'"availablePoints"\s*:\s*(\d+)',
                r'"Balance"\s*:\s*(\d+)',
                r"(\d{1,3}(?:,\d{3})+)\s*<",
            ]:
                match = re.search(pattern, r.text)
                if match:
                    return int(match.group(1).replace(",", ""))
    except Exception:
        pass
    return None


DEFAULT_POINTS_RE = re.compile(r'"availablePoints"\s*:\s*"?([0-9]{1,6})')
ESCAPED_Q = re.compile(r'\\\"')


def _unescape_html(html: str) -> str:
    """Rewards 页面内嵌 RSC 数据是双重转义 JSON，还原反斜杠+引号。"""
    return html.replace('\\"', '"')


def _offer_points(block: str) -> int:
    head = block[: block.find('"offerId"')] if '"offerId"' in block else block
    match = re.search(r'"points"\s*:\s*([0-9]{1,4})', head) or re.search(r'"points"\s*:\s*([0-9]{1,4})', block)
    return int(match.group(1)) if match else 0


def get_points_from_html(html: str) -> Optional[int]:
    if not html:
        return None
    text = _unescape_html(html)
    for pattern in (r'"balance"\s*:\s*([0-9]+)', r'"availablePoints"\s*:\s*"?([0-9]+)'):
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def get_earn_page(session: requests.Session) -> str:
    try:
        r = session.get(EARN_PANEL, headers=get_headers(PC_UA, DASHBOARD), timeout=20)
        if r.status_code == 200:
            return r.text
    except Exception as exc:
        log(f"  earn 页面访问异常: {exc}")
    return ""


def get_dashboard(session: requests.Session) -> str:
    try:
        r = session.get(DASHBOARD, headers=get_headers(PC_UA, EARN_PANEL), timeout=20)
        if r.status_code == 200:
            return r.text
    except Exception as exc:
        log(f"  dashboard 访问异常: {exc}")
    return ""


def rewards_session_ok(session: requests.Session, earn_html: str = "") -> bool:
    """判断 rewards.bing.com 是否已经建立登录会话。

    cn.bing.com 登录不等于 Rewards 登录：缺少 Rewards/登录站点 Cookie 时，
    /earn 会被重定向到 login.live.com，页面里没有 balance/可领取卡片。
    """
    text = _unescape_html(earn_html or get_earn_page(session))
    return '"balance"' in text or "DashboardHeader_ClaimablePoints" in text


def _find_hash(block: str) -> str:
    match = re.search(r'"hash"\s*:\s*"([0-9a-f]{40,64})"', block)
    return match.group(1) if match else ""


def extract_offers(html: str) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    if not html:
        return offers
    text = _unescape_html(html)
    seen: set[str] = set()
    for match in re.finditer(r'"offerId"\s*:\s*"([^"]+)', text):
        offer_id = match.group(1)
        if offer_id in seen:
            continue
        seen.add(offer_id)
        start = text.rfind('{"', max(0, match.start() - 2500), match.start())
        if start < 0:
            start = max(0, match.start() - 2000)
        block = text[start : match.end() + 200]

        dest = re.search(r'"destination"\s*:\s*"(https?://[^"]+)"', block)
        title = re.search(r'"title"\s*:\s*"([^"]*)"', block)
        desc = re.search(r'"description"\s*:\s*"([^"]*)"', block)
        completed = re.search(r'"isCompleted"\s*:\s*(true|false)', block)
        locked = re.search(r'"isLocked"\s*:\s*(true|false)', block)
        offers.append(
            {
                "id": offer_id,
                "dest": dest.group(1) if dest else "",
                "title": (title.group(1) if title else offer_id)[:24],
                "desc": desc.group(1) if desc else "",
                "points": _offer_points(block),
                "completed": (completed.group(1) == "true") if completed else False,
                "locked": (locked.group(1) == "true") if locked else False,
                "hash": _find_hash(block),
                "raw": block,
            }
        )
    return offers


def extract_streaks(html: str) -> list[dict[str, Any]]:
    streaks: list[dict[str, Any]] = []
    if not html:
        return streaks
    text = _unescape_html(html)
    for match in re.finditer(r'"type"\s*:\s*"streak"\s*,\s*"model"\s*:\s*\{"streak"\s*:\s*\{', text):
        block = text[match.end() : match.end() + 1200]
        completed = re.search(r'"activitiesCompleted"\s*:\s*([0-9]+)', block)
        total = re.search(r'"activitiesTotal"\s*:\s*([0-9]+)', block)
        partner = re.search(r'"partner"\s*:\s*"([^"]+)"', block)
        day = re.search(r'"currentDay"\s*:\s*([0-9]+)', block)
        total_days = re.search(r'"totalDays"\s*:\s*([0-9]+)', block)
        item = {
            "partner": partner.group(1) if partner else "?",
            "done": int(completed.group(1)) if completed else 0,
            "total": int(total.group(1)) if total else 0,
            "day": int(day.group(1)) if day else 0,
            "total_days": int(total_days.group(1)) if total_days else 0,
        }
        streaks.append(item)
    match = re.search(r'"streakCounter"\s*:\s*([0-9]+)', text)
    if match:
        streaks.append({"partner": "dailystreak", "done": int(match.group(1)), "total": 0, "day": 0, "total_days": 0})
    return streaks


def streak_lines(html: str) -> list[str]:
    lines: list[str] = []
    for streak in extract_streaks(html):
        partner = streak["partner"]
        if partner == "dailystreak":
            lines.append(f"{STREAK_LABELS[partner]}: {streak['done']} 天")
            continue
        if streak["total"] <= 0:
            continue
        day_info = f" 第{streak['day']}/{streak['total_days']}天" if streak["total_days"] else ""
        flag = "✅" if streak["done"] >= streak["total"] else "·"
        lines.append(
            f"{flag} {STREAK_LABELS.get(partner, partner)}: "
            f"{streak['done']}/{streak['total']}{day_info}"
        )
    return lines


def _streak_of(html: str, partner: str) -> Optional[dict[str, Any]]:
    for streak in extract_streaks(html):
        if streak["partner"] == partner:
            return streak
    return None


def do_checkin(session: requests.Session) -> bool:
    """尝试每日签到（网页接口通常无效，需必应 App）。"""
    section("每日签到")
    html = get_dashboard(session) or get_earn_page(session)
    app = _streak_of(html, "bingapp")
    if app and app["total"] > 0 and app["done"] >= app["total"]:
        log(f" 当前进度: {app['done']}/{app['total']}")
        log(" ✅ 每日签到已完成")
        return True

    action_id = None
    try:
        r = session.get("https://rewards.bing.com/earn?section=streaks", headers=get_headers(PC_UA), timeout=20)
        match = re.search(r'"([0-9a-f]{40})"', r.text)
        if match:
            action_id = match.group(1)
    except Exception:
        pass

    headers = get_headers(PC_UA, "https://rewards.bing.com/earn?section=streaks")
    headers.update(
        {
            "Accept": "text/x-component",
            "Content-Type": "text/plain;charset=UTF-8",
            "Origin": "https://rewards.bing.com",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
    )
    if action_id:
        headers["Next-Action"] = action_id
    try:
        r = session.post(
            "https://rewards.bing.com/earn?section=streaks",
            headers=headers,
            data="[]",
            timeout=15,
        )
        log(f"  签到请求: HTTP {r.status_code}" + ("" if action_id else "（未取到 action id）"))
    except Exception as exc:
        log(f"  签到请求异常: {exc}")

    time.sleep(2)
    html2 = get_dashboard(session) or get_earn_page(session)
    app2 = _streak_of(html2, "bingapp")
    if app2:
        log(f" 当前进度: {app2['done']}/{app2['total']}")
        if app2["total"] > 0 and app2["done"] >= app2["total"]:
            log(" ✅ 每日签到已完成")
            return True
    log(" ⚠️ 签到未生效（该签到需必应App端，网页接口通常无效）")
    return False


def complete_offers(
    session: requests.Session,
    earn_html: str,
    skip_ids: set[str],
    delay_min: int,
    delay_max: int,
    notes: list[str],
) -> tuple[int, int]:
    """完成 earn 页的每日精选任务，返回 (成功数, 待做数)。"""
    section("每日精选任务")
    offers = extract_offers(earn_html)
    if not offers:
        log("  未解析到任务列表（earn 页面异常）")
        notes.append("每日精选任务: 未解析到任务列表")
        return 0, 0

    pending: list[dict[str, Any]] = []
    done_count = locked_count = 0
    for offer in offers:
        if offer["id"] in skip_ids or not re.search(r"bing\.com/search\?", offer["dest"]):
            continue
        if "dailyset" in offer["id"].lower() or "dailyset" in offer["raw"].lower():
            continue
        if offer["completed"]:
            done_count += 1
            continue
        if offer["locked"]:
            locked_count += 1
            continue
        if offer["points"] <= 0:
            continue
        pending.append(offer)

    log(
        f"  共 {len(offers)} 个任务，已完成 {done_count} 个，"
        f"待做 {len(pending)} 个，锁定 {locked_count} 个"
    )

    ok_count = 0
    for index, offer in enumerate(pending):
        url = offer["dest"].replace("https://www.bing.com", "https://cn.bing.com")
        try:
            r = session.get(url, headers=get_headers(PC_UA, EARN_PANEL), timeout=15)
            page = r.text if r.status_code == 200 else ""
            ok = False
            if offer.get("hash"):
                ok = report_offer_v2(
                    session,
                    earn_html,
                    offer["hash"],
                    offer["id"],
                    "https://rewards.bing.com/earn?section=streaks",
                )
            if not ok and page:
                ig, iid = extract_ig_iid(page)
                if ig:
                    ok = report_activity(session, url, page, ig, iid)
            log(
                f"  任务[{index + 1}/{len(pending)}] {offer['title']} "
                f"(+{offer['points']}分): {'✅ 已触发' if ok else '❌ 触发失败'}"
            )
            if ok:
                ok_count += 1
                notes.append(f"精选任务「{offer['title']}」已提交(+{offer['points']})")
        except Exception as exc:
            log(f"  任务[{index + 1}/{len(pending)}] {offer['title']} ❌ 异常: {exc}")
        if index < len(pending) - 1:
            time.sleep(random.randint(delay_min, delay_max))
    return ok_count, len(pending)


SKIP_LABEL_KEYS = ("Edg", "Edge", "banner", "Sweeps", "RAF", "Duolingo", "Refer")


def get_claimable(html: str) -> Optional[int]:
    """解析「可领取」积分数。"""
    if not html:
        return None
    text = _unescape_html(html)
    match = re.search(
        r'DashboardHeader_ClaimablePoints.{0,300}?"points"\s*:\s*"?(\d+|\$undefined)',
        text,
        re.S,
    )
    if not match:
        return None
    return 0 if match.group(1) == "$undefined" else int(match.group(1))


def _deployment_id(html: str) -> Optional[str]:
    match = re.search(r"dpl=(\d{8}-\d+)", html or "")
    return match.group(1) if match else None


def _action_headers(html: str, referer: str, action_id: str) -> dict[str, str]:
    headers = get_headers(PC_UA, referer)
    headers.update(
        {
            "Accept": "text/x-component",
            "Content-Type": "text/plain;charset=UTF-8",
            "Origin": "https://rewards.bing.com",
            "Next-Action": action_id,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
    )
    deployment = _deployment_id(html)
    if deployment:
        headers["x-deployment-id"] = deployment
    return headers


def discover_action_id(
    session: requests.Session,
    page_html: str,
    func_name: str,
    max_chunks: int = 40,
) -> Optional[str]:
    """从线上 JS chunk 自动挖 Server Action id。"""
    if not page_html:
        return None
    seen: set[str] = set()
    todo: list[str] = []
    for match in re.finditer(r"/_next/static/chunks/[^\"'\s]+\.js", page_html):
        if match.group(0) not in seen:
            seen.add(match.group(0))
            todo.append(match.group(0))

    pattern = re.compile(
        r'createServerReference\)\("([0-9a-f]{40,44})"[^)]*?"' + re.escape(func_name) + r'"'
    )
    checked: set[str] = set()
    fetched = 0
    while todo and fetched < max_chunks:
        path = todo.pop(0)
        if path in checked:
            continue
        checked.add(path)
        try:
            r = session.get("https://rewards.bing.com" + path, headers=get_headers(PC_UA), timeout=20)
            if r.status_code != 200:
                continue
            fetched += 1
            text = r.text or ""
        except Exception:
            continue
        match = pattern.search(text)
        if match:
            log(f"  已挖到 action id: {func_name} = {match.group(1)[:12]}...")
            return match.group(1)
        for item in re.finditer(r'static/chunks/([^"\'\s]+\.js)', text):
            path2 = "/_next/static/chunks/" + item.group(1)
            if path2 not in seen:
                seen.add(path2)
                todo.append(path2)
    return None


def claim_points(session: requests.Session) -> dict[str, Any]:
    """领取「可领取」积分。"""
    section("领取积分")
    html = get_dashboard(session)
    if not html:
        log("  无法获取 dashboard，跳过")
        return {"status": "skip", "before": None, "after": None, "claimed": 0}

    before = get_claimable(html)
    if before is None:
        log("  未解析到「可领取」积分，跳过")
        return {"status": "skip", "before": None, "after": None, "claimed": 0}
    if before <= 0:
        log("  当前可领取: 0")
        log(" ✅ 暂无待领取积分")
        return {"status": "none", "before": 0, "after": 0, "claimed": 0}

    log(f"  当前可领取: {before} 分，开始领取...")
    ok = False
    try:
        r = session.post(
            DASHBOARD,
            headers=_action_headers(html, DASHBOARD, CLAIM_ACTION_ID),
            data="[]",
            timeout=20,
        )
        if r.status_code >= 400:
            log("  内置 action id 失效，尝试从线上 JS 重新提取...")
            action_id = discover_action_id(session, html, "reportClaimAllPoints")
            if action_id:
                r = session.post(
                    DASHBOARD,
                    headers=_action_headers(html, DASHBOARD, action_id),
                    data="[]",
                    timeout=20,
                )
        body = r.text or ""
        log(f"  领取请求: HTTP {r.status_code}")
        if "NEXT_REDIRECT" in body and "login" in body:
            log("  ⚠️ 登录态失效（被重定向到登录页），请更新 Cookie")
            return {"status": "expired", "before": before, "after": None, "claimed": 0}
        if r.status_code in (200, 204):
            ok = True
    except Exception as exc:
        log(f"  领取请求异常: {exc}")
        return {"status": "failed", "before": before, "after": None, "claimed": 0}

    time.sleep(2)
    after = get_claimable(get_dashboard(session))
    if after is not None and after < before:
        log(f" ✅ 领取成功: {before} → {after}（+{before - after} 分）")
        return {"status": "ok", "before": before, "after": after, "claimed": before - after}
    if after == 0:
        log(f" ✅ 领取成功: {before} → 0")
        return {"status": "ok", "before": before, "after": 0, "claimed": before}
    if ok:
        log(f" ⚠️ 已发送领取请求，但复查仍显示可领取 {after} 分")
        log("   可能原因: 积分刚到账有延迟，稍后重跑本脚本即可")
    return {"status": "pending", "before": before, "after": after, "claimed": 0}


def collect_pending(
    earn_html: str,
    search_progress: tuple[Optional[int], Optional[int]],
    daily_set_done: Any,
    quiz_pending: list[str],
    notes: list[str],
) -> list[str]:
    """汇总今日未完成的任务。"""
    items: list[str] = []
    s_done, s_max = search_progress
    if s_done is not None and s_max and s_done < s_max:
        items.append(f"每日搜索 仅 {s_done}/{s_max} 分")
    if daily_set_done is False:
        items.append("每日集 未全部完成")
    for title in quiz_pending:
        items.append(f"问答「{title}」未完成")
    for offer in extract_offers(earn_html):
        if "dailyset" in offer["id"].lower() or "dailyset" in offer["raw"].lower():
            continue
        if offer["completed"] or not re.search(r"bing\.com/search\?", offer["dest"]):
            continue
        if any(k in offer["dest"] for k in ("rewards.bing.com", "microsoft.com")):
            continue
        if offer["locked"]:
            items.append(f"{offer['title']}（等级不够，已锁定）")
        elif offer["points"] > 0:
            items.append(f"{offer['title']}(+{offer['points']})")
    for note in notes:
        match = re.match(r"精选任务「(.+?)」已提交", note)
        if match:
            title = match.group(1)
            items = [item for item in items if not item.startswith(title + "(")]
    return items


def show_pending(items: list[str]) -> None:
    section("今日任务汇总")
    if not items:
        log(" 🎉 能自动做的任务已全部完成")
        return
    for item in items:
        log(f"  · {item}")


# ---------------------------------------------------------------------------
# 单账号流程
# ---------------------------------------------------------------------------

def run_account(account: Account, cfg: AppConfig, check_only: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": account.name,
        "username": "",
        "ok": False,
        "points_before": None,
        "points_after": None,
        "search_before": None,
        "search_limit": None,
        "search_after": None,
        "search_after_limit": None,
        "search_ran": 0,
        "search_ok": 0,
        "daily_set_done": None,
        "daily_set_total": None,
        "quiz_done": 0,
        "quiz_total": 0,
        "offers_ok": 0,
        "offers_total": 0,
        "checkin": "跳过",
        "claim": None,
        "claimable": None,
        "streaks": [],
        "pending": [],
        "message": "",
    }

    log(f"🔐 [{account.name}] 使用 Cookie 登录 cn.bing.com")
    cookie_map = parse_cookie(account.cookie)
    if not cookie_map.get("_U"):
        result["message"] = PARTIAL_COOKIE_HINT
        log(f"❌ [{account.name}] {result['message']}")
        return result

    session = make_session(account.cookie)
    username = get_username(session)
    earn_html = get_earn_page(session)
    points_before = check_points(session)
    if points_before is None and earn_html:
        points_before = get_points_from_html(earn_html)

    result["username"] = username or ""
    result["points_before"] = points_before

    if not username and not points_before:
        result["message"] = "Cookie 无效或已过期（未获取到用户名/积分）"
        log(f"❌ [{account.name}] {result['message']}")
        return result

    if not rewards_session_ok(session, earn_html):
        result["message"] = REWARDS_SESSION_HINT
        log(f"❌ [{account.name}] {result['message']}")
        return result

    log(
        f"👤 [{account.name}] 用户: {username or '未知'}  "
        f"💰 当前积分: {points_before if points_before is not None else '查询失败'}"
    )

    if check_only:
        dashboard = get_dashboard(session)
        result["claimable"] = get_claimable(dashboard)
        result["streaks"] = streak_lines(dashboard)
        result["ok"] = True
        result["message"] = "Cookie 可用"
        return result

    # 0. 每日签到 + 连续打卡
    if cfg.checkin:
        result["checkin"] = "完成" if do_checkin(session) else "未生效"
    dashboard = get_dashboard(session)
    result["streaks"] = streak_lines(dashboard)
    if result["streaks"]:
        section("连续打卡")
        for line in result["streaks"]:
            log(f"  {line}")
    else:
        log("  未获取到连续打卡数据")

    # 0.5 领取积分
    if cfg.claim:
        result["claim"] = claim_points(session)
    else:
        result["claim"] = {"status": "skip"}

    # 1. 每日搜索
    panel_html = ""
    try:
        r = session.get(REWARDS_PANEL, headers=get_headers(PC_UA), timeout=15)
        panel_html = r.text
    except Exception:
        pass
    search_earned, search_limit = get_daily_search_status(panel_html)
    if search_earned is None and earn_html:
        search_earned, search_limit = get_daily_search_status(earn_html)
    result["search_before"] = search_earned
    result["search_limit"] = search_limit

    need_times = cfg.search_times
    if search_earned is not None and search_limit:
        remaining = max(0, search_limit - search_earned)
        need_times = min(cfg.search_times, remaining)
    search_done = bool(search_earned is not None and search_limit and search_earned >= search_limit)

    if search_done:
        section("每日搜索")
        log(f" 当前进度: {search_earned}/{search_limit}")
        log(" ✅ 每日搜索已全部完成")
    else:
        if search_earned is not None and search_limit:
            section(f"每日搜索（{search_earned}/{search_limit} 分，补 {need_times} 次）")
        else:
            section(f"每日搜索（{need_times} 次）")
        used_terms: set[str] = set()
        ok_count = 0
        for index in range(need_times):
            term = get_search_term(used_terms)
            ok = do_search(session, term)
            ok_count += 1 if ok else 0
            log(f"  搜索[{index + 1}/{need_times}] '{term[:25]}': {'✅' if ok else '❌'}")
            if index < need_times - 1:
                time.sleep(random.randint(cfg.delay_min, cfg.delay_max))
        result["search_ran"] = need_times
        result["search_ok"] = ok_count

    # 2. 每日集
    ds_done, ds_total = complete_daily_set(session, cfg.delay_min, cfg.delay_max)
    result["daily_set_done"] = ds_done
    result["daily_set_total"] = ds_total

    # 3. 每日问答
    quiz_pending: list[str] = []
    try:
        r = session.get(REWARDS_PANEL, headers=get_headers(PC_UA), timeout=15)
        quiz_urls = extract_quiz_urls(r.text)
        for quiz_url in quiz_urls:
            result["quiz_total"] += 1
            done, _ = get_quiz_panel_status(r.text, quiz_url)
            if done:
                section("每日问答")
                total_q = None
                try:
                    rq = session.get(
                        quiz_url.replace("www.bing.com", "cn.bing.com"),
                        headers=get_headers(PC_UA),
                        timeout=10,
                    )
                    total_q = extract_quiz_total(rq.text)
                except Exception:
                    pass
                if total_q:
                    log(f" 当前进度: {total_q}/{total_q}")
                log(" ✅ 每日问答已全部完成")
                result["quiz_done"] += 1
                continue
            completed = complete_quiz(session, quiz_url, cfg.delay_min, cfg.delay_max)
            if completed > 0:
                result["quiz_done"] += 1
            else:
                query = parse_qs(urlparse(quiz_url).query).get("q", [""])[0]
                quiz_pending.append(unquote_plus(query)[:30] or quiz_url[:30])
            time.sleep(random.randint(cfg.delay_min, cfg.delay_max))
    except Exception:
        pass

    # 4. 每日精选任务
    skip_ids: set[str] = set()
    earn_html2 = get_earn_page(session)
    if earn_html2:
        earn_html = earn_html2
    notes: list[str] = []
    if cfg.offers:
        for offer in extract_offers(earn_html):
            if re.search(r"rnoreward=1|dailyset", offer["raw"], re.I) and "search?" in offer["dest"]:
                skip_ids.add(offer["id"])
        offers_ok, offers_total = complete_offers(
            session, earn_html, skip_ids, cfg.delay_min, cfg.delay_max, notes
        )
        result["offers_ok"] = offers_ok
        result["offers_total"] = offers_total

    # 5. 等积分到账后统计
    if cfg.wait_seconds > 0:
        log(f"⏳ 等待 {cfg.wait_seconds} 秒让积分到账...")
        time.sleep(cfg.wait_seconds)

    earn_html3 = get_earn_page(session) or earn_html
    search_progress = get_daily_search_status(earn_html3)
    if search_progress[0] is None and search_earned is not None:
        search_progress = (
            min(search_limit, search_earned + need_times) if search_limit else search_earned,
            search_limit,
        )
    result["search_after"] = search_progress[0]
    result["search_after_limit"] = search_progress[1]
    ds_complete = bool(ds_total and ds_done >= ds_total)
    pending = collect_pending(
        earn_html3,
        search_progress,
        None if ds_complete else False,
        quiz_pending,
        notes,
    )
    result["pending"] = pending
    show_pending(pending)

    points_after = check_points(session)
    if points_after is None:
        points_after = get_points_from_html(earn_html3)
    result["points_after"] = points_after
    if points_before is not None and points_after is not None:
        log(f"✅ 任务已全部完成！积分: {points_before} → {points_after} (+{points_after - points_before})")
    elif points_after is not None:
        log(f"✅ 任务已全部完成！当前积分: {points_after}")
    else:
        log("✅ 任务已全部完成（积分查询不可用）")

    result["ok"] = True
    result["message"] = "任务已全部完成" if not pending else f"仍有 {len(pending)} 项未完成"
    return result


# ---------------------------------------------------------------------------
# 汇总与通知
# ---------------------------------------------------------------------------

def _fmt_points(value: Any) -> str:
    return str(value) if value is not None else "未知"


def _join_items(items: list[str], limit: int = 5) -> str:
    if not items:
        return ""
    if len(items) <= limit:
        return "；".join(items)
    return "；".join(items[:limit]) + f"；等 {len(items)} 项"


def format_summary(results: list[dict[str, Any]], check_only: bool = False) -> str:
    lines = [f"📅 {datetime.now().strftime('%m-%d %H:%M')}", ""]
    ok_count = sum(1 for item in results if item.get("ok"))
    for i, result in enumerate(results):
        lines.append(f"{'✅' if result.get('ok') else '❌'} {result.get('name') or '账号'}")
        if not result.get("ok") and result.get("message"):
            lines.append(f"   ⚠️ {result['message']}")
            if i < len(results) - 1:
                lines.append("")
            continue
        if result.get("username"):
            lines.append(f"   👤 用户：{result['username']}")
        if check_only:
            if result.get("ok"):
                lines.append(f"   💰 积分：{_fmt_points(result.get('points_before'))}")
                if result.get("claimable") is not None:
                    lines.append(f"   🎁 可领取：{result['claimable']} 分")
                if result.get("streaks"):
                    lines.append(f"   🔥 连续打卡：{_join_items(result['streaks'], 3)}")
            elif result.get("message"):
                lines.append(f"   ⚠️ {result['message']}")
        else:
            before = result.get("points_before")
            after = result.get("points_after")
            if before is not None and after is not None:
                lines.append(f"   💰 积分：{before} → {after}（+{after - before}）")
            else:
                lines.append(f"   💰 积分：{_fmt_points(after if before is None else before)}")
            if result.get("search_before") is not None and result.get("search_limit"):
                after = result.get("search_after")
                limit = result.get("search_after_limit") or result["search_limit"]
                if after is not None:
                    search_text = f"{result['search_before']}/{result['search_limit']} → {after}/{limit}"
                else:
                    search_text = f"{result['search_before']}/{result['search_limit']}"
                if result.get("search_ran"):
                    search_text += f"（补搜 {result['search_ran']} 次）"
                lines.append(f"   🔎 搜索：{search_text}")
            if result.get("daily_set_total"):
                lines.append(
                    f"   📅 每日集：{result.get('daily_set_done', 0)}/{result['daily_set_total']}"
                )
            if result.get("quiz_total"):
                lines.append(f"   ❓ 问答：{result.get('quiz_done', 0)}/{result['quiz_total']}")
            if result.get("offers_total"):
                lines.append(
                    f"   ✨ 精选：{result.get('offers_ok', 0)}/{result['offers_total']}"
                )
            if result.get("checkin") != "跳过":
                lines.append(f"   📱 签到：{result['checkin']}")
            claim = result.get("claim") or {}
            if claim.get("claimed"):
                lines.append(f"   🎁 领取：+{claim['claimed']} 分")
            elif claim.get("before"):
                lines.append(f"   🎁 可领取：{claim['before']} 分（待复查）")
            if result.get("streaks"):
                lines.append(f"   🔥 连续打卡：{_join_items(result['streaks'], 3)}")
            if result.get("pending"):
                lines.append(f"   ⚠️ 未完成：{_join_items(result['pending'])}")
        if i < len(results) - 1:
            lines.append("")
    lines.append("")
    lines.append("────────")
    if ok_count == len(results):
        lines.append(f"📊 合计：{ok_count}/{len(results)} 全部成功 🎉")
    elif ok_count == 0:
        lines.append(f"📊 合计：0/{len(results)} 全部失败")
    else:
        lines.append(f"📊 合计：成功 {ok_count} · 失败 {len(results) - ok_count}")
    return "\n".join(lines)


def format_notify_title(results: list[dict[str, Any]], check_only: bool = False) -> str:
    action = "查询" if check_only else "日常任务"
    ok_count = sum(1 for item in results if item.get("ok"))
    total = len(results)
    if total == 0:
        return f"{APP_NAME} {action}"
    if ok_count == total:
        return f"{APP_NAME} {action} ✅ {ok_count}/{total}"
    if ok_count == 0:
        return f"{APP_NAME} {action} ❌ 0/{total}"
    return f"{APP_NAME} {action} ⚠️ {ok_count}/{total}"


def send_notifications(cfg: AppConfig, results: list[dict[str, Any]], check_only: bool = False) -> None:
    title = format_notify_title(results, check_only)
    content = format_summary(results, check_only)

    if _ql_notify:
        try:
            log("📣 通知状态: 正在调用青龙面板统一通知发送推送 🚀")
            _ql_notify(title, content)
            return
        except Exception as exc:
            debug(f"青龙通知发送失败: {exc}")

    if cfg.notify.bark_enabled():
        endpoint = (
            cfg.notify.bark_url.rstrip("/")
            if cfg.notify.bark_url
            else f"{cfg.notify.bark_server.rstrip('/')}/{cfg.notify.bark_key}"
        )
        payload: dict[str, Any] = {
            "title": title,
            "body": content,
            "group": cfg.notify.bark_group or DEFAULT_BARK_GROUP,
        }
        for option in ("bark_sound", "bark_icon", "bark_level"):
            value = getattr(cfg.notify, option)
            if value:
                payload[option.replace("bark_", "")] = value
        try:
            r = requests.post(endpoint, json=payload, timeout=15)
            if r.status_code >= 400:
                requests.get(
                    f"{endpoint}/{quote(title, safe='')}/{quote(content, safe='')}",
                    timeout=15,
                )
            log("📣 通知状态: 已发送至 iOS Bark 推送 📱")
        except Exception as exc:
            log(f"⚠️ Bark 推送失败: {exc}")
    else:
        log("📣 未配置 BARK_URL / BARK_KEY，跳过 Bark 推送")

    if cfg.notify.pushplus_token:
        try:
            requests.post(
                "https://www.pushplus.plus/send",
                json={
                    "token": cfg.notify.pushplus_token,
                    "title": title,
                    "content": content.replace("\n", "<br>"),
                    "template": "html",
                    "topic": cfg.notify.pushplus_topic or "",
                },
                timeout=15,
            )
            log("📣 通知状态: 已发送至 PushPlus 微信推送 💬")
        except Exception as exc:
            log(f"⚠️ PushPlus 推送失败: {exc}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="必应积分助手（国内版）")
    parser.add_argument("--config", help="本地 yaml 配置路径")
    parser.add_argument("--check", action="store_true", help="仅验证 Cookie 并查询积分/可领取，不执行任务")
    parser.add_argument("--debug", action="store_true", help="输出调试日志")
    args = parser.parse_args(argv)

    global IS_DEBUG
    IS_DEBUG = args.debug or _env("DEBUG") in ("1", "true", "yes")

    log("=" * 50)
    log(f"🎯 {APP_NAME} v{VERSION}" + ("（仅查询）" if args.check else ""))
    log(f"⏰ 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 50)

    try:
        cfg = resolve_config(args.config)
    except FileNotFoundError as exc:
        log(str(exc) or MISSING_CONFIG_HINT)
        return 1
    except Exception as exc:
        log(f"❌ 读取配置失败: {exc}")
        return 1

    log(f"👥 共 {len(cfg.accounts)} 个账号")
    results: list[dict[str, Any]] = []
    for i, account in enumerate(cfg.accounts):
        log("=" * 50)
        log(f"🚀 开始执行 {account.name}")
        results.append(run_account(account, cfg, check_only=args.check))
        if i < len(cfg.accounts) - 1 and cfg.inter_account_delay > 0:
            log(f"⏳ 等待 {cfg.inter_account_delay} 秒后执行下一个账号…")
            time.sleep(cfg.inter_account_delay)

    summary = format_summary(results, check_only=args.check)
    log("\n" + summary)
    log("\n🎊 所有账号任务执行完成!")

    send_notifications(cfg, results, check_only=args.check)
    return 0 if any(item.get("ok") for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
