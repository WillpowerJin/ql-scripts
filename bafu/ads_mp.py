#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
八富生活 · 小程序协议看广告（/ad/complete）

cron: 0 9-23/2 * * *
new Env('八富生活小程序');

业务逻辑对齐「八富生活小程序新版」：
- YYB GO 取微信 code → getOpenidAnon → phoneLogin
- captcha issue/verify → checkLimit → /ad/complete（Feistel token）

环境变量：
  YYB_GO          必填。多账号换行或 & 分隔
                  格式：host:port@ref
                  带备注：host:port@ref#备注（如 iPhone）
                  例：
                    192.168.2.199:8000@owNAXHSWnZNI#iPhone
                    192.168.2.199:8000@owNAxxxxxxxx#家里
  BAFU_NOTE       可选。全局备注，进 Bark 标题（区分多台青龙）
  BARK_URL / BARK_KEY   通知（与仓库其它脚本共用）
  BARK_SERVER / BARK_GROUP / BARK_SOUND  可选
  BFSH_INVITER_CODE     邀请码，默认 U75803F7
  BFSH_FORCE_REBIND=0   已绑定则不改绑（默认会尝试 setInviter）
  DRY_RUN=1             只查询不 complete
  QYWX_KEY              可选，企业微信机器人（兼容旧配置）
  BFSH_CAPTCHA_TOKEN    可选，覆盖验证码 Token
"""
import os
import sys
import json
import time
import uuid
import random
import signal
import requests
import urllib3

from datetime import datetime
from urllib.parse import quote

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def log(msg=""):
    print(msg, flush=True)


DEFAULT_BARK_SERVER = "https://api.day.app"
GLOBAL_NOTE = (
    os.environ.get("BAFU_NOTE")
    or os.environ.get("BFSH_NOTE")
    or os.environ.get("BAFU_TAG")
    or ""
).strip()


def _env(key, default=""):
    return (os.environ.get(key) or default).strip()


def bark_endpoint():
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


def send_bark(title, body):
    endpoint = bark_endpoint()
    if not endpoint:
        log("ℹ️ 未配置 BARK_URL/BARK_KEY，跳过 Bark 推送")
        return
    if not endpoint.startswith("http"):
        endpoint = f"{DEFAULT_BARK_SERVER.rstrip('/')}/{endpoint}"
    group = _env("BARK_GROUP") or "八富生活小程序"
    payload = {
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


def bark_title(ok_all, n, ok_n):
    tag = f" · {GLOBAL_NOTE}" if GLOBAL_NOTE else ""
    if n == 0:
        return f"八富小程序{tag} ❌ 未配置账号"
    if ok_all:
        return f"八富小程序{tag} ✅ {ok_n}/{n}"
    if ok_n == 0:
        return f"八富小程序{tag} ❌ 0/{n}"
    return f"八富小程序{tag} ⚠️ {ok_n}/{n}"



def handle_sigterm(signum, frame):
    log("\n收到终止信号，脚本退出")
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)

# ---------- SSL 补丁 ----------
_ORIG_REQUEST = requests.Session.request


def _patched_request(self, *args, **kwargs):
    kwargs.setdefault("verify", False)
    return _ORIG_REQUEST(self, *args, **kwargs)


requests.Session.request = _patched_request


def _mount_retry(session, retries=2):
    retry = urllib3.util.retry.Retry(
        total=retries, backoff_factor=0.5,
        status_forcelist=[502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = requests.adapters.HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)


# ---------- 配置 ----------
APPID = "wxb9be8e4f98c3fbe5"
PORTAL = "https://bafunet.com/portal-server"
ADPID = "2919867719"
TENANT_ID = "1992418264477876226"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bfsh_v2_cache.json")


CAPTCHA_TOKEN = os.environ.get("BFSH_CAPTCHA_TOKEN", "")

# Windows 微信小程序 UA（抓包）
WX_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
         "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows "
         "WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat XWEB/19841")


DEVICE_POOL = [
    {"brand":"Xiaomi","model":"2201123C","market":"MI 12","android":"13","build":"TKQ1.220829.002"},
    {"brand":"Xiaomi","model":"2203121C","market":"MI 12 Pro","android":"13","build":"TKQ1.220829.002"},
    {"brand":"Xiaomi","model":"2210132C","market":"MI 12S Ultra","android":"13","build":"TKQ1.220829.002"},
    {"brand":"Xiaomi","model":"22021211RC","market":"MI 12X","android":"13","build":"TKQ1.220829.002"},
    {"brand":"Xiaomi","model":"2304FPN6DC","market":"MI 13","android":"14","build":"UKQ1.230804.001"},
    {"brand":"Xiaomi","model":"23127PN0CC","market":"Xiaomi 14","android":"14","build":"UKQ1.231003.002"},
    {"brand":"Xiaomi","model":"23116PN5BC","market":"Xiaomi 14 Pro","android":"14","build":"UKQ1.231003.002"},
    {"brand":"Xiaomi","model":"24031PN0DC","market":"Xiaomi 14 Ultra","android":"15","build":"VKQ1.240223.001"},
    {"brand":"Xiaomi","model":"24129PN7DC","market":"Xiaomi 15","android":"15","build":"VKQ1.240223.001"},
    {"brand":"Redmi","model":"22081212C","market":"Redmi Note 12 Pro","android":"13","build":"TKQ1.220829.002"},
    {"brand":"Redmi","model":"23049RAD8C","market":"Redmi Note 13 Pro","android":"14","build":"UKQ1.230917.001"},
    {"brand":"Redmi","model":"23046PNC9C","market":"Redmi Note 13 Pro+","android":"14","build":"UKQ1.230917.001"},
    {"brand":"Redmi","model":"23090RA98C","market":"Redmi K60 Ultra","android":"13","build":"TKQ1.220829.002"},
    {"brand":"Redmi","model":"23113RKC6C","market":"Redmi K70","android":"14","build":"UKQ1.230917.001"},
    {"brand":"Redmi","model":"2312DRA50C","market":"Redmi K70 Pro","android":"14","build":"UKQ1.230917.001"},
    {"brand":"Redmi","model":"24069RA21C","market":"Redmi K70 Ultra","android":"14","build":"UKQ1.230917.001"},
    {"brand":"HUAWEI","model":"ALN-AL00","market":"Mate60","android":"12","build":"HUAWEIALN-AL00"},
    {"brand":"HUAWEI","model":"ALN-AL10","market":"Mate60 Pro","android":"12","build":"HUAWEIALN-AL10"},
    {"brand":"HUAWEI","model":"ALT-AL00","market":"Mate X5","android":"13","build":"HUAWEIALT-AL00"},
    {"brand":"HUAWEI","model":"CET-AL00","market":"Mate50","android":"12","build":"HUAWEICET-AL00"},
    {"brand":"HUAWEI","model":"DCO-AL00","market":"Mate50 Pro","android":"12","build":"HUAWEIDCO-AL00"},
    {"brand":"HUAWEI","model":"MNA-AL00","market":"P60","android":"12","build":"HUAWEIMNA-AL00"},
    {"brand":"HUAWEI","model":"MNA-AL20","market":"P60 Pro","android":"12","build":"HUAWEIMNA-AL20"},
    {"brand":"HUAWEI","model":"BLK-AL00","market":"nova 12","android":"13","build":"HUAWEIBLK-AL00"},
    {"brand":"OPPO","model":"PGFM10","market":"Find X6","android":"14","build":"UKQ1.230924.001"},
    {"brand":"OPPO","model":"PGD110","market":"Find X6 Pro","android":"14","build":"UKQ1.230924.001"},
    {"brand":"OPPO","model":"PJX110","market":"Find X7","android":"14","build":"UKQ1.230924.001"},
    {"brand":"OPPO","model":"PHZ110","market":"Find X7 Ultra","android":"14","build":"UKQ1.230924.001"},
    {"brand":"OPPO","model":"PGEM10","market":"Find N3","android":"13","build":"TKQ1.221103.001"},
    {"brand":"OPPO","model":"PGU110","market":"Reno11","android":"14","build":"UKQ1.231207.002"},
    {"brand":"OPPO","model":"PHY110","market":"Reno12","android":"14","build":"UKQ1.231207.002"},
    {"brand":"OPPO","model":"PJV110","market":"Reno12 Pro","android":"14","build":"UKQ1.231207.002"},
    {"brand":"vivo","model":"V2241A","market":"X90","android":"13","build":"UP1A.231005.007"},
    {"brand":"vivo","model":"V2303A","market":"X90 Pro","android":"13","build":"UP1A.231005.007"},
    {"brand":"vivo","model":"V2309A","market":"X100","android":"14","build":"UP1A.231005.007"},
    {"brand":"vivo","model":"V2329A","market":"X100 Pro","android":"14","build":"UP1A.231005.007"},
    {"brand":"vivo","model":"V2307A","market":"iQOO 12","android":"14","build":"UP1A.231005.007"},
    {"brand":"vivo","model":"V2338A","market":"iQOO Neo9","android":"14","build":"UP1A.231005.007"},
    {"brand":"vivo","model":"V2405A","market":"X200","android":"15","build":"UP1A.231005.007"},
    {"brand":"vivo","model":"V2413A","market":"X200 Pro","android":"15","build":"UP1A.231005.007"},
    {"brand":"samsung","model":"SM-S9110","market":"Galaxy S23","android":"14","build":"UP1A.231005.007"},
    {"brand":"samsung","model":"SM-S9180","market":"Galaxy S23 Ultra","android":"14","build":"UP1A.231005.007"},
    {"brand":"samsung","model":"SM-S9210","market":"Galaxy S24","android":"14","build":"UP1A.231005.007"},
    {"brand":"samsung","model":"SM-S9260","market":"Galaxy S24+","android":"14","build":"UP1A.231005.007"},
    {"brand":"samsung","model":"SM-S9280","market":"Galaxy S24 Ultra","android":"14","build":"UP1A.231005.007"},
    {"brand":"samsung","model":"SM-A5460","market":"Galaxy A54","android":"14","build":"UP1A.231005.007"},
    {"brand":"samsung","model":"SM-A5560","market":"Galaxy A55","android":"14","build":"UP1A.231005.007"},
    {"brand":"Honor","model":"PGT-AN00","market":"Magic5","android":"13","build":"UKQ1.230917.001"},
    {"brand":"Honor","model":"BVL-AN00","market":"Magic6","android":"14","build":"UKQ1.230917.001"},
    {"brand":"Honor","model":"VER-AN10","market":"Magic V2","android":"13","build":"UKQ1.230917.001"},
    {"brand":"Honor","model":"REP-AN00","market":"Honor 90 Pro","android":"13","build":"UKQ1.230917.001"},
    {"brand":"Honor","model":"MAA-AN00","market":"Honor 100","android":"14","build":"UKQ1.230917.001"},
    {"brand":"OnePlus","model":"PJD110","market":"OnePlus 12","android":"14","build":"UKQ1.231003.002"},
    {"brand":"OnePlus","model":"PJE110","market":"Ace 3","android":"14","build":"UKQ1.231003.002"},
    {"brand":"OnePlus","model":"PJZ110","market":"OnePlus 13","android":"15","build":"UKQ1.240223.001"},
    {"brand":"realme","model":"RMX3888","market":"GT5 Pro","android":"14","build":"UKQ1.230917.001"},
    {"brand":"realme","model":"RMX3851","market":"GT Neo6","android":"14","build":"UKQ1.230917.001"},
    {"brand":"realme","model":"RMX3842","market":"realme 12 Pro+","android":"14","build":"UKQ1.230917.001"},
    {"brand":"meizu","model":"M381Q","market":"Meizu 20","android":"13","build":"TKQ1.221114.001"},
    {"brand":"meizu","model":"M391Q","market":"Meizu 20 Pro","android":"13","build":"TKQ1.221114.001"},
    {"brand":"meizu","model":"M461Q","market":"Meizu 21","android":"14","build":"UKQ1.230917.001"},
    {"brand":"meizu","model":"M481Q","market":"Meizu 21 Pro","android":"14","build":"UKQ1.230917.001"},
    {"brand":"Google","model":"GKWS6","market":"Pixel 8","android":"14","build":"AP2A.240805.005"},
    {"brand":"Google","model":"GC3VE","market":"Pixel 8 Pro","android":"14","build":"AP2A.240805.005"},
    {"brand":"Google","model":"GP4BC","market":"Pixel 7","android":"13","build":"TQ3A.230901.001"}
]

_M32 = (1 << 32) - 1
_M64 = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15


def _rotl32(x, k):
    return ((x << k) | (x >> (32 - k))) & _M32


def _rotl64(x, k):
    return ((x << k) | (x >> (64 - k))) & _M64


def _feistel_round_fn(r, key):
    u = (r ^ (key & _M32)) & _M32
    u = _rotl32(u, 7)
    u = (0x9E3779B9 * u) & _M32
    u = (u ^ (u >> 13)) & _M32
    u = _rotl32(u, 3)
    return u


def _feistel_key_schedule(seed):
    keys = []
    k = seed & _M64
    for i in range(12):
        keys.append(k)
        k = (_rotl64(k, 13) ^ (_GOLDEN * (i + 1))) & _M64
    return keys


def feistel_encrypt(ad_id, user_id):
    plain = int(ad_id)
    seed = int(user_id)
    keys = _feistel_key_schedule(seed)
    left = (plain >> 32) & _M32
    right = plain & _M32
    for g in range(12):
        v = (left ^ _feistel_round_fn(right, keys[g])) & _M32
        left, right = right, v
    out = ((right << 32) | left) & _M64
    if out >= (1 << 63):
        out -= 1 << 64
    return str(out)


# 模拟观看广告/间隔时间（观看需 >=10 秒，服务端校验）
AD_WATCH_MIN = 20
AD_WATCH_EXTRA = 4
AD_GAP_MIN = 7
AD_GAP_EXTRA = 1

QYWX_KEY = os.environ.get("QYWX_KEY", "")
DRY_RUN = os.environ.get("DRY_RUN", "") == "1"
INVITER_CODE = os.environ.get("BFSH_INVITER_CODE", "U75803F7")
FORCE_REBIND = os.environ.get("BFSH_FORCE_REBIND", "1") != "0"
ACCOUNT_ICONS = "🍺🍷🍸🍹🥂🍶🧉☕🍵🥃"

# YYB GO 微信 code 服务
YYB_APPID = APPID


# ---------- 设备生成 ----------
def create_device():
    d = random.choice(DEVICE_POOL)
    device = d.copy()
    device["device_id"] = str(uuid.uuid4())
    device["ua"] = (
        f"Dalvik/2.1.0 (Linux; U; Android {d['android']}; {d['market']} Build/{d['build']})"
    )
    return device


# ---------- 缓存 ----------
def load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"  ⚠️ 写缓存失败: {e}")


def ok_resp(data):
    if not isinstance(data, dict):
        return False
    if data.get("_error") or data.get("error"):
        return False
    return data.get("code") in (None, 0, 200)


# ---------- 广告人机验证（captchaToken） ----------
# 中文 → 验证码图片文件名映射（图片文件名为英文）
CN2EN = {
    "苹果": "apple", "星星": "star", "花": "flower", "帽子": "hat", "狗": "dog",
    "自行车": "bicycle", "出租车": "taxi", "树": "tree", "猫": "cat", "鸟": "bird",
    "鱼": "fish", "蝴蝶": "butterfly", "香蕉": "banana", "西瓜": "watermelon",
    "汽车": "car", "房子": "house", "伞": "umbrella", "飞机": "airplane",
    "轮船": "ship", "船": "ship", "月亮": "moon", "太阳": "sun", "云": "cloud",
    "山": "mountain", "足球": "football", "红绿灯": "traffic_light", "火车": "train",
    "公交车": "bus", "摩托车": "motorcycle", "鹿": "deer", "兔子": "rabbit",
    "猴子": "monkey", "熊猫": "panda", "老虎": "tiger", "狮子": "lion",
    "大象": "elephant", "骆驼": "camel", "马": "horse", "牛": "cow", "羊": "sheep",
    "猪": "pig", "鸡": "chicken", "鸭": "duck", "鹅": "goose", "乌龟": "turtle",
    "青蛙": "frog", "蛇": "snake", "蜘蛛": "spider", "蜜蜂": "bee", "蚂蚁": "ant",
    "蜻蜓": "dragonfly", "瓢虫": "ladybug", "蜗牛": "snail", "螃蟹": "crab",
    "龙虾": "lobster", "虾": "shrimp", "海豚": "dolphin", "鲸鱼": "whale",
    "鲨鱼": "shark", "章鱼": "octopus", "水母": "jellyfish", "海星": "starfish",
    "蛋糕": "cake", "冰淇淋": "icecream", "冰激凌": "icecream", "棒棒糖": "lollipop",
    "杯子": "cup", "水杯": "cup", "瓶子": "bottle", "闹钟": "alarm_clock",
    "手机": "phone", "电视": "tv", "电脑": "computer", "台灯": "lamp",
    "椅子": "chair", "桌子": "table", "床": "bed", "窗户": "window",
    "门": "door", "书": "book", "铅笔": "pencil", "尺子": "ruler",
    "剪刀": "scissors", "钥匙": "key", "钱包": "wallet", "背包": "backpack",
    "鞋": "shoe", "鞋子": "shoe", "袜子": "sock", "手套": "glove",
    "围巾": "scarf", "眼镜": "glasses", "雨伞": "umbrella", "气球": "balloon",
    "风筝": "kite", "篮球": "basketball", "排球": "volleyball", "乒乓球": "pingpong",
    "网球": "tennis", "棒球": "baseball", "吉他": "guitar", "钢琴": "piano",
    "小提琴": "violin", "鼓": "drum", "话筒": "microphone", "麦克风": "microphone",
    "喇叭": "speaker", "相机": "camera", "摄像机": "video_camera", "冰箱": "refrigerator",
    "洗衣机": "washing_machine", "空调": "air_conditioner", "风扇": "fan",
    "吹风机": "hair_dryer", "熨斗": "iron", "热水壶": "kettle", "锅": "pot",
    "碗": "bowl", "盘子": "plate", "筷子": "chopsticks", "勺子": "spoon",
    "刀": "knife", "叉子": "fork", "煎蛋": "fried_egg", "鸡蛋": "egg",
    "汉堡": "hamburger", "薯条": "fries", "披萨": "pizza", "热狗": "hotdog",
    "面条": "noodles", "米饭": "rice", "面包": "bread", "饼干": "cookie",
    "糖果": "candy", "巧克力": "chocolate", "牛奶": "milk", "咖啡": "coffee",
    "茶": "tea", "果汁": "juice", "可乐": "cola", "雪糕": "icecream",
    "玉米": "corn", "胡萝卜": "carrot", "蘑菇": "mushroom", "西红柿": "tomato",
    "土豆": "potato", "青椒": "pepper", "洋葱": "onion", "白菜": "cabbage",
    "葡萄": "grape", "草莓": "strawberry", "樱桃": "cherry", "桃子": "peach",
    "梨": "pear", "橘子": "orange", "柠檬": "lemon", "菠萝": "pineapple",
    "芒果": "mango", "椰子": "coconut", "猕猴桃": "kiwi", "火": "fire",
    "水": "water", "石头": "stone", "花盆": "flowerpot", "灯笼": "lantern",
    "红包": "red_envelope", "钟": "clock", "电话": "telephone", "铅笔刀": "sharpener",
    "橡皮": "eraser", "牙刷": "toothbrush", "牙膏": "toothpaste", "梳子": "comb",
    "镜子": "mirror", "剃须刀": "shaver", "刮胡刀": "shaver", "口红": "lipstick",
    "香水": "perfume", "戒指": "ring", "项链": "necklace", "手表": "watch",
    "耳环": "earrings", "纽扣": "button", "针": "needle", "线": "thread",
    "锤子": "hammer", "螺丝刀": "screwdriver", "扳手": "wrench", "斧头": "axe",
    "锯子": "saw", "梯子": "ladder", "扫帚": "broom", "拖把": "mop",
    "垃圾桶": "trash_can", "垃圾箱": "trash_bin", "灭火器": "fire_extinguisher",
    "警车": "police_car", "救护车": "ambulance", "消防车": "fire_truck",
    "卡车": "truck", "挖土机": "excavator", "推土机": "bulldozer", "拖拉机": "tractor",
    "直升机": "helicopter", "火箭": "rocket", "热气球": "hot_air_balloon",
    "帆船": "sailboat", "潜艇": "submarine", "独木舟": "canoe", "竹筏": "raft",
    "鱿鱼": "squid", "海豹": "seal", "企鹅": "penguin", "猫头鹰": "owl",
    "鹦鹉": "parrot", "鸽子": "dove", "老鹰": "eagle", "孔雀": "peacock",
    "天鹅": "swan", "长颈鹿": "giraffe", "斑马": "zebra", "犀牛": "rhino",
    "河马": "hippo", "刺猬": "hedgehog", "松鼠": "squirrel", "仓鼠": "hamster",
    "老鼠": "mouse", "蝙蝠": "bat", "恐龙": "dinosaur", "独角兽": "unicorn",
    "绵羊": "sheep", "山羊": "goat", "毛驴": "donkey", "豹子": "leopard",
    "狼": "wolf", "狐狸": "fox", "熊": "bear", "猩猩": "gorilla",
    "公鸡": "rooster", "母鸡": "hen", "小鸡": "chick", "玫瑰": "rose",
    "向日葵": "sunflower", "仙人掌": "cactus", "竹子": "bamboo", "莲花": "lotus",
    "苹果树": "apple_tree", "松树": "pine", "圣诞树": "christmas_tree", "稻草人": "scarecrow",
    "圣诞老人": "santa", "雪人": "snowman", "南瓜": "pumpkin", "鬼": "ghost",
    "骷髅": "skull", "皇冠": "crown", "奖杯": "trophy", "金牌": "gold_medal",
    "钻石": "diamond", "宝石": "gem", "珍珠": "pearl", "珊瑚": "coral",
    "贝壳": "shell", "无烟": "no_smoking", "禁止吸烟": "no_smoking",
}


def parse_captcha_question(question, images):
    """从验证码题目和图片文件名推导点击顺序的索引列表（需3个）"""
    import re
    parts = re.split(r"[：→>、,，\s]+", question)
    idxs = []
    for p in parts:
        p = p.strip()
        if p and p in CN2EN:
            target = CN2EN[p]
            for i, img in enumerate(images):
                name = img.split("/")[-1].split(".")[0].lower()
                if name in (target, target.replace("_", ""), target.replace("_", "-")):
                    idxs.append(i)
                    break
    return idxs


def yyb_get_code(ref, host_port):
    """通过 YYB GO 获取微信登录 code"""
    if not ref or not host_port:
        return None
    if not host_port.startswith("http://") and not host_port.startswith("https://"):
        host = "http://" + host_port
    else:
        host = host_port
    try:
        resp = requests.post(f"{host}/wxapp/getCode",
                             json={"ref": ref, "app_id": YYB_APPID}, timeout=15)
        if resp.status_code == 200:
            code = resp.json().get("data", {}).get("result", {}).get("code")
            if code:
                return code
        log(f"  ⚠️ YYB getCode 失败: {resp.status_code} - {resp.text[:100]}")
    except Exception as e:
        log(f"  ⚠️ YYB getCode 异常: {e}")
    return None


def yyb_get_phone_code(ref, host_port):
    """通过 YYB GO 获取手机号授权 code"""
    if not ref or not host_port:
        return None
    if not host_port.startswith("http://") and not host_port.startswith("https://"):
        host = "http://" + host_port
    else:
        host = host_port
    try:
        resp = requests.post(f"{host}/wxapp/getPhoneNumber",
                             json={"ref": ref, "app_id": YYB_APPID}, timeout=15)
        if resp.status_code == 200:
            code = resp.json().get("data", {}).get("result", {}).get("code")
            if code:
                return code
        log(f"  ⚠️ YYB getPhoneNumber 失败: {resp.status_code} - {resp.text[:100]}")
    except Exception as e:
        log(f"  ⚠️ YYB getPhoneNumber 异常: {e}")
    return None


def parse_yyb_go_env(line):
    """
    解析单条 YYB_GO：
      host:port@ref
      host:port@ref#备注
    返回 (host_port, ref, note)
    """
    line = (line or "").strip()
    if not line:
        return None, None, ""
    note = ""
    if "#" in line:
        left, maybe_note = line.rsplit("#", 1)
        if "@" in left and maybe_note.strip():
            line, note = left.strip(), maybe_note.strip()
    if "@" not in line:
        return None, None, ""
    host_port, ref = line.split("@", 1)
    host_port, ref = host_port.strip(), ref.strip()
    if not host_port or not ref:
        return None, None, ""
    return host_port, ref, note


def _split_yyb_raw(raw):
    """支持换行与 & 分隔多账号；以 # 开头的整行视为注释。"""
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    parts = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "&" in line:
            parts.extend(p.strip() for p in line.split("&") if p.strip())
        else:
            parts.append(line)
    return parts


# ---------- 账号来源 ----------
def load_accounts():
    """从 YYB_GO 解析多账号：host:port@ref[#备注]"""
    accounts = []
    raw = os.environ.get("YYB_GO", "").strip()
    for i, line in enumerate(_split_yyb_raw(raw), 1):
        host_port, ref, note = parse_yyb_go_env(line)
        if ref and host_port:
            short = (ref[:8] + "...") if len(ref) > 8 else ref
            display = note or short
            accounts.append({
                "ref": ref,
                "host_port": host_port,
                "note": note,
                "display_name": display,
                "source": "yyb_go",
            })
            if note:
                log(f"  📥 YYB_GO 账号{i}: {note}（ref={short}）")
            else:
                log(f"  📥 YYB_GO 账号{i}: {short}")
        else:
            log(f"  ⚠️ YYB_GO 第 {i} 段格式错误（需要 host:port@ref[#备注]）: {line[:60]}")
    return accounts


# ---------- 账号类 ----------
class BaFuV2:
    def __init__(self, acc, index, cache):
        self.ref = acc.get("ref") or ""
        self.host_port = acc.get("host_port") or ""
        self.openid = self.ref
        self.display_name = acc.get("display_name") or self.ref[:8] + "..." or f"账号{index}"
        self.index = index
        self.cache = cache
        self.session = requests.Session()
        _mount_retry(self.session)
        self.jsessionid = ""
        self.tenant_id = ""
        self.user_id = ""
        self.token = ""
        self.code = None
        self.device = {}
        self.err = ""

    # ---------- 小程序侧（portal）请求 ----------
    def _build_url(self, path):
        url = PORTAL + path
        if self.jsessionid:
            if "?" in url:
                url = url.replace("?", f";jsessionid={self.jsessionid}?", 1)
            else:
                url += f";jsessionid={self.jsessionid}"
        return url

    def _headers(self):
        h = {
            "User-Agent": WX_UA,
            "xweb_xhr": "1",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://servicewechat.com/wxb9be8e4f98c3fbe5/32/page-frame.html",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if self.tenant_id:
            h["X-Tenant-ID"] = self.tenant_id
        return h

    def _req(self, method, path, params=None, json=None):
        url = self._build_url(path)
        try:
            r = self.session.request(method, url, params=params, json=json,
                                      headers=self._headers(), timeout=20)
        except Exception as e:
            return None, {}, str(e)
        sid = r.headers.get("sid") or r.headers.get("Sid")
        if not sid:
            for c in self.session.cookies:
                if "JSESSIONID" in c.name.upper():
                    sid = c.value
                    break
        if sid:
            self.jsessionid = sid
            self.session.cookies.clear()
        try:
            data = r.json()
        except Exception:
            data = {"_error": f"非JSON:{r.status_code}", "_text": r.text[:200]}
        return data, r.headers, None

    # ---------- YYB 微信登录链路 ----------
    def _load_tenant(self):
        cfg, _, _ = self._req("GET", "/user/getMallConfigAnon",
                              params={"code": "1001", "clientType": "mp-weixin"})
        if ok_resp(cfg) and isinstance(cfg.get("data"), dict):
            self.tenant_id = cfg["data"].get("$tenantId", "") or ""
        if not self.tenant_id:
            self.tenant_id = TENANT_ID
        return True

    def _get_base_info(self):
        data, _, err = self._req("GET", "/user/getBaseInfoAnon")
        if err or data.get("_error"):
            return None
        if ok_resp(data):
            return data.get("data") or {}
        return None

    def _get_wechat_code(self):
        return yyb_get_code(self.ref, self.host_port)

    def _get_phone_code(self):
        return yyb_get_phone_code(self.ref, self.host_port)

    def _open_anon_session(self, code):
        data, _, err = self._req("GET", "/platform-user/getOpenidAnon",
                                 params={"code": code, "gzh": "false"})
        if err or data.get("_error"):
            self.err = f"getOpenidAnon 失败: {err or data.get('_error')}"
            return False
        if not self.jsessionid:
            self.err = "getOpenidAnon 未返回 jsessionid"
            return False
        return True

    def _phone_login(self):
        wxcode = self._get_phone_code()
        if not wxcode:
            log(f"  ⚠️ {self.display_name} 未获取到手机号授权 code，尝试匿名账号")
            return False
        log(f"  📱 {self.display_name} 获取到手机号授权 code: {wxcode[:20]}...")
        payload = {"wxCode": wxcode, "type": "N", "parentId": "", "clientType": "mp-weixin"}
        data, _, err = self._req("POST", "/phoneLogin", json=payload)
        if err:
            log(f"  ⚠️ phoneLogin 请求异常: {err}")
            return False
        if ok_resp(data):
            log(f"  ✅ {self.display_name} phoneLogin 成功")
            return True
        log(f"  ⚠️ phoneLogin 失败: {data.get('msg') or data.get('code')}")
        return False

    def _get_captcha_token(self, force=False):
        """自动过广告人机验证，返回 captchaToken（当天有效）；失败返回 None"""
        # 优先用缓存（按日期校验：captchaToken 第二段为 yyyyMMdd）
        if not force and self.ref in self.cache:
            ct = self.cache[self.ref].get("captchaToken")
            if ct:
                parts = ct.split("|")
                if len(parts) >= 2 and parts[1] == datetime.now().strftime("%Y%m%d"):
                    log(f"  🎫 {self.display_name} 使用缓存 captchaToken")
                    return ct
        if not self.host_port or not self.ref:
            log(f"  ⚠️ {self.display_name} 未配置 host_port/ref，无法过验证码")
            return None
        for attempt in range(3):
            data, _, err = self._req("GET", "/ad/captcha/issue")
            if err or data.get("_error"):
                log(f"  ⚠️ issue 请求异常: {err or data.get('_error')}")
                return None
            if data.get("code") != 200:
                log(f"  ⚠️ issue 失败: {data.get('msg')}")
                return None
            d = data.get("data") or {}
            token = d.get("token")
            question = d.get("question", "")
            images = d.get("images") or []
            idxs = parse_captcha_question(question, images)
            log(f"  🔍 {self.display_name} 验证码: {question} | 点击索引={idxs}")
            if len(idxs) != 3:
                log("  ⚠️ 无法解析出3个点击索引，重试")
                time.sleep(1)
                continue
            code = yyb_get_code(self.ref, self.host_port)
            if not code:
                log(f"  ⚠️ {self.display_name} 获取微信 code 失败")
                return None
            t0 = time.time() * 1000
            time.sleep(1.5)
            params = {
                "token": token,
                "clicks": ",".join(str(i) for i in idxs),
                "duration": str(int(time.time() * 1000 - t0)),
                "code": code,
            }
            data2, _, err2 = self._req("POST", "/ad/captcha/verify", params=params, json={})
            if err2 or data2.get("_error"):
                log(f"  ⚠️ verify 请求异常: {err2 or data2.get('_error')}")
                return None
            if data2.get("code") == 200:
                ct = (data2.get("data") or {}).get("captchaToken")
                if ct:
                    self.cache.setdefault(self.ref, {})["captchaToken"] = ct
                    save_cache(self.cache)
                    log(f"  ✅ {self.display_name} 验证码通过")
                    return ct
            log(f"  ⚠️ verify 失败: {data2.get('msg')}")
            time.sleep(1)
        return None

    def _load_injected(self):
        raw = os.environ.get("BFSH_SESSION", "").strip()
        if not raw:
            return False
        try:
            try:
                data = json.loads(raw)
            except Exception:
                with open(raw, "r", encoding="utf-8") as f:
                    data = json.load(f)
        except Exception:
            return False
        entry = data.get(self.ref) if self.ref else None
        if not isinstance(entry, dict) and len(data) == 1:
            entry = list(data.values())[0]
        if isinstance(entry, dict) and entry.get("jsessionid") and entry.get("user_id"):
            self.jsessionid = entry["jsessionid"]
            self.tenant_id = entry.get("tenant_id", "")
            self.user_id = str(entry["user_id"])
            log("  🔑 使用注入会话 (BFSH_SESSION)")
            return True
        return False

    def _save(self):
        self.cache[self.ref] = {
            "jsessionid": self.jsessionid,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "token": self.token,
            "device": self.device,
            "time": str(datetime.now()),
        }
        save_cache(self.cache)

    def login(self, force=False):
        cache = load_cache()
        if not force and self.ref and self.ref in cache:
            c = cache[self.ref]
            if c.get("jsessionid") and c.get("user_id"):
                self.jsessionid = c["jsessionid"]
                self.tenant_id = c.get("tenant_id", "")
                self.user_id = c["user_id"]
                if self._get_base_info() is not None and self.user_id:
                    log(f"  🔑 {self.display_name} 使用缓存会话 (JSESSIONID)")
                    return True
                log("  🔄 缓存会话失效，重新登录")

        # 1. 获取微信登录 code
        code = self._get_wechat_code()
        if not code:
            log(f"  ❌ {self.display_name} 无法获取 wx.login code（检查 YYB_GO 配置）")
        else:
            self.code = code
            log(f"  ✅ {self.display_name} 获取到 wx.login code: {code[:10]}...")

            # 2. 建立匿名会话
            if self._open_anon_session(code):
                self._load_tenant()

                # 3. 手机号登录
                if self._phone_login():
                    info = self._get_base_info()
                    if info and info.get("id"):
                        self.user_id = str(info["id"])
                        self._save()
                        log(f"  ✅ {self.display_name} 登录成功，user_id={self.user_id}")
                        return True
                    log(f"  ⚠️ {self.display_name} phoneLogin 后未返回用户 id")

                # 4. 如果手机号登录失败，尝试获取匿名用户信息
                info = self._get_base_info()
                if info and info.get("id"):
                    self.user_id = str(info["id"])
                    self._save()
                    log(f"  ✅ {self.display_name} 匿名登录成功，user_id={self.user_id}")
                    return True
                log(f"  ⚠️ {self.display_name} 未获取到 user_id")

        # 5. 尝试注入会话
        if self._load_injected():
            return True

        # 6. 尝试从缓存恢复 user_id
        if self.ref and self.ref in cache:
            c = cache[self.ref]
            if c.get("user_id"):
                self.user_id = c["user_id"]
                return True

        self.err = f"无法获得用户 id：请检查 YYB_GO 配置"
        log(f"  ❌ {self.err}")
        return False

    def _get_inviter(self):
        data, _, err = self._req("GET", "/user/getInviter")
        if err or data.get("_error"):
            return "error", err or data.get("_error")
        code = data.get("code")
        if code == 200 and data.get("data"):
            return "bound", data["data"]
        if code in (401, "401"):
            return "unauth", None
        return "unbound", None

    def _set_inviter(self, code=INVITER_CODE):
        data, _, err = self._req("POST", "/user/setInviter", params={"code": code})
        if err or data.get("_error"):
            return False, err or data.get("_error")
        if data.get("code") == 200:
            return True, data.get("msg") or "ok"
        return False, data.get("msg") or str(data.get("code"))

    def ensure_inviter(self):
        kind, payload = self._get_inviter()
        if kind == "unauth":
            self.login(force=True)
            kind, payload = self._get_inviter()
        if kind == "error":
            log(f"  ⚠️ 查询邀请人失败: {payload}")
            return "查询失败"

        already = payload if kind == "bound" else None
        if already and not FORCE_REBIND:
            name = already.get("nickname") or already.get("phone") or "?"
            log(f"  🤝 已绑定: {name}")
            return f"已绑定:{name}"

        if already:
            name = already.get("nickname") or already.get("phone") or "?"
        else:
            log(f"  🔗 未绑定邀请人")

        if DRY_RUN:
            return "待绑定(查)"
        ok, msg = self._set_inviter()
        if ok:
            k2, d2 = self._get_inviter()
            if k2 == "bound":
                nm = d2.get("nickname") or d2.get("phone") or "?"
                log(f"  ✅ 已绑定邀请人: {nm}")
                return f"已绑定:{nm}"
            return "绑定存疑"
        if "hasCycleInvite" in str(msg):
            log(f"  ℹ️ 本账号即邀请码持有者（{INVITER_CODE}），无需绑定，跳过")
            return "本人邀请码"
        if "errorReq" in str(msg):
            return "不可改绑"
        log(f"  ⚠️ 绑定邀请人失败: {msg}")
        return f"绑定失败:{msg}"

    # ---------- 广告（新 /ad/complete 接口） ----------
    def _use_captcha_token(self):
        """返回当前有效的 captchaToken，无则自动获取"""
        if self.ref in self.cache:
            ct = self.cache[self.ref].get("captchaToken")
            if ct:
                parts = ct.split("|")
                if len(parts) >= 2 and parts[1] == datetime.now().strftime("%Y%m%d"):
                    return ct
        return self._get_captcha_token()

    def check_limit(self):
        ct = self._use_captcha_token()
        if not ct:
            log(f"  ⚠️ {self.display_name} 无可用 captchaToken，跳过 checkLimit")
            return None
        data, _, err = self._req("GET", "/ad/checkLimit",
                                 params={"adpid": ADPID, "captchaToken": ct})
        if err or data.get("_error"):
            log(f"  ⚠️ {self.display_name} check_limit 请求异常: {err or data.get('_error')}")
            return None
        if data.get("code") == 200:
            d = data.get("data", {})
            return {
                "count": int(d.get("count", 0)),
                "totalAds": int(d.get("totalAds", 0)),
                "id": d.get("id"),
                "adProfit": d.get("adProfit", 0),
                "needLogin": bool(d.get("needLogin", False)),
                "needCaptcha": bool(d.get("needCaptcha", False)),
                "limited": bool(d.get("limited", False)),
                "msg": data.get("msg", ""),
            }
        log(f"  ⚠️ {self.display_name} checkLimit 返回: {data.get('msg', data.get('code'))}")
        return None

    def complete(self, ad_id):
  
        ct = self._use_captcha_token()
        if not ct:
            return False, "无captchaToken"
        token = feistel_encrypt(ad_id, self.user_id)
        params = {
            "token": token,
            "adpid": ADPID,
            "captchaToken": ct,
        }
        data, _, err = self._req("POST", "/ad/complete", params=params, json={})
        if err or data.get("_error"):
            log(f"  ⚠️ {self.display_name} complete 请求异常: {err or data.get('_error')}")
            return False, f"req_err:{err}"
        if data.get("code") == 200:
            d = data.get("data", {})
            log(f"  📺 {self.display_name} complete 成功 | count={d.get('count')} "
                f"adProfit={d.get('adProfit')} limited={d.get('limited')}")
            return True, ""
        msg = data.get("msg") or f"code={data.get('code')}"
        if "验证" in msg or "人机" in msg:
            log(f"  🔄 {self.display_name} captchaToken 失效，重新获取")
            ct_new = self._get_captcha_token(force=True)
            if ct_new:
                token = feistel_encrypt(ad_id, self.user_id)
                params["captchaToken"] = ct_new
                data, _, err = self._req("POST", "/ad/complete", params=params, json={})
                if data and data.get("code") == 200:
                    d = data.get("data", {})
                    log(f"  📺 {self.display_name} 重试 complete 成功 | count={d.get('count')}")
                    return True, ""
                msg = data.get("msg") or f"code={data.get('code')}" if data else "重试失败"
        log(f"  ⚠️ {self.display_name} complete 失败: {msg}")
        return False, msg

    def run_ads(self):
        watched = 0
        while True:
            info = self.check_limit()
            if not info:
                log(f"  ⚠️ {self.display_name}：未获取广告信息，结束当前账号")
                break
            count = info["count"]
            total = info["totalAds"]
            log(f"  📺 {self.display_name} 广告进度 {count}/{total} | limited={info['limited']} "
                f"| adProfit={info['adProfit']} | needLogin={info['needLogin']} needCaptcha={info['needCaptcha']}")
            if info["needCaptcha"]:
                log(f"  🔄 {self.display_name} needCaptcha=true，重新获取 captchaToken")
                if not self._get_captcha_token(force=True):
                    log(f"  ⚠️ {self.display_name} 重新获取 captchaToken 失败，跳过")
                    break
                continue
            if info["needLogin"]:
                log(f"  🔄 {self.display_name} needLogin=true，重新登录")
                self.login(force=True)
            if info["limited"] or count >= total:
                log(f"  ✅ {self.display_name}：今日广告已达上限{total}个，账号任务完成！")
                break
            ad_id = info["id"]
            sleep_t = random.randint(AD_WATCH_MIN, AD_WATCH_MIN + AD_WATCH_EXTRA)
            log(f"  ⏳ {self.display_name} 等待 {sleep_t}s 模拟观看广告")
            time.sleep(sleep_t)

            if DRY_RUN:
                log(f"  🔍 DRY_RUN 模式，跳过 complete")
                continue

            ok, msg = self.complete(ad_id)
            if ok:
                watched += 1
                log(f"  ✅ {self.display_name} 完成第 {watched} 个广告")
            else:
                log(f"  ⚠️ {self.display_name} 本单未完成: {msg}")
                # 若 complete 返回未达上限且失败，可能 token 失效，尝试下一次循环
            gap_t = random.randint(AD_GAP_MIN, AD_GAP_MIN + AD_GAP_EXTRA)
            log(f"  💤 {self.display_name} 间隔 {gap_t}s")
            time.sleep(gap_t)
        return watched

    # ---------- 主流程 ----------
    def run(self):
        result = {"name": self.display_name, "watched": 0, "errors": []}
        if self.ref in self.cache and self.cache[self.ref].get("device"):
            self.device = self.cache[self.ref]["device"]
        else:
            self.device = create_device()
            log(f"  📱 {self.display_name} 生成新设备: {self.device['market']} | device_id={self.device['device_id'][:8]}")

        if not self.login():
            err_msg = f"{self.display_name} 登录失败: {self.err or '未知原因'}"
            log(f"  ❌ {err_msg}")
            result["errors"].append(err_msg)
            return result

        self._save()
        result["inviter"] = self.ensure_inviter()
        watched = self.run_ads()
        result["watched"] = watched
        return result


# ---------- 汇总推送 ----------
def push_summary(results):
    log("")
    log("📣 八富生活 · 小程序任务汇总")
    log("─" * 28)

    n = len(results)
    ok_n = sum(1 for r in results if not r.get("errors"))
    total_watched = sum(int(r.get("watched") or 0) for r in results)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    body_lines = []
    body_lines.append("🎬 八富生活 · 小程序看广告")
    if GLOBAL_NOTE:
        body_lines.append(f"🏷️ 备注：{GLOBAL_NOTE}")
    body_lines.append(f"📅 {now}")
    body_lines.append("────────────────")
    body_lines.append("")

    for i, r in enumerate(results):
        icon = ACCOUNT_ICONS[i % len(ACCOUNT_ICONS)]
        name = r.get("name", "?")
        errs = r.get("errors", [])
        watched = int(r.get("watched") or 0)
        inviter = r.get("inviter")

        if errs:
            err = "; ".join(str(x) for x in errs)
            if len(err) > 80:
                err = err[:77] + "…"
            line = f"{icon} 【{name}】 ❌ {err}"
            body_lines.append(f"{icon} 【{name}】")
            body_lines.append("   ❌ 状态：异常")
            body_lines.append(f"   💬 {err}")
        else:
            line = f"{icon} 【{name}】 ✅ 观看{watched}个广告"
            body_lines.append(f"{icon} 【{name}】")
            if watched > 0:
                body_lines.append(f"   ✅ 本次完成：{watched} 条广告")
            else:
                body_lines.append("   ✅ 状态：正常（已满或无需再看）")
        if inviter:
            line += f" | 邀请人:{inviter}"
            body_lines.append(f"   🤝 邀请：{inviter}")
        body_lines.append("")
        log(line)
        log("─" * 28)

    body_lines.append("────────────────")
    body_lines.append(f"📊 账号：成功 {ok_n}/{n} · 本次共看 {total_watched} 条")
    if DRY_RUN:
        body_lines.append("🧪 模式：DRY_RUN")

    body = "\n".join(body_lines).rstrip() + "\n"
    title = bark_title(ok_all=(ok_n == n and n > 0), n=n, ok_n=ok_n)
    send_bark(title, body)

    if QYWX_KEY:
        text = "📣 八富生活 · 小程序汇总\n" + "\n".join(ln for ln in body_lines if ln)
        try:
            resp = requests.post(
                "https://qyapi.weixin.qq.com/cgi-bin/webhook/send",
                params={"key": QYWX_KEY},
                json={"msgtype": "text", "text": {"content": text}},
                timeout=10,
            )
            if resp.json().get("errcode") == 0:
                log("  ✅ 企业微信推送成功")
            else:
                log(f"  ⚠️ 企业微信推送失败: {resp.text[:120]}")
        except Exception as e:
            log(f"  ⚠️ 企业微信推送异常: {e}")
    else:
        log("  ℹ️ 未配置 QYWX_KEY（可选）")


def main():
    log("🚀 开始八富生活 · 小程序自动任务")
    
    accounts = load_accounts()
    cache = load_cache()
    if not accounts:
        log("❌ 未获取到任何账号：请配置 YYB_GO 环境变量")
        log("   格式: host:port@ref  或  host:port@ref#备注")
        log("   例: 192.168.2.199:8000@owNAXHSWnZNI#iPhone")
        send_bark(bark_title(False, 0, 0), "❌ 未配置 YYB_GO\n格式: host:port@ref#备注")
        return
    src = accounts[0]["source"]
    log(f"📋 获取到 {len(accounts)} 个账号（来源：{src}）")
    results = []
    for idx, acc in enumerate(accounts, 1):
        app = BaFuV2(acc, idx, cache)
        try:
            res = app.run()
        except Exception as e:
            res = {"name": app.display_name, "watched": 0, "errors": [f"脚本异常:{e}"]}
            log(f"  ❌ {app.display_name} 发生异常: {e}")
        results.append(res)
        log(f"===== {app.display_name} 执行完毕 =====\n")
        if idx < len(accounts):
            sleep_gap = random.randint(30, 60)
            log(f"💤 等待 {sleep_gap}s 切换下一账号")
            time.sleep(sleep_gap)
    push_summary(results)
    log("🏁 全部账号处理完成，脚本正常结束！")
    sys.exit(0)


if __name__ == "__main__":
    main()
