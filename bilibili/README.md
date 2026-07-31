# B 站每日任务（扫码 Cookie + 青龙）

对齐 [ClydeTime/BiliBili.js](https://raw.githubusercontent.com/ClydeTime/Quantumult/main/Script/Task/BiliBili.js) 的日常能力，**无需 App 抓包**。

| 脚本 | 说明 | 运行方式 |
|------|------|----------|
| [`get_cookie.py`](./get_cookie.py) | 手机 B 站**扫码**拿 Cookie | **手动**（失效时跑） |
| [`daily.py`](./daily.py) | 每日经验 / 扩展任务 | **定时** cron |

> 仅供学习研究。请遵守 B 站用户协议。

---

## 正确流程（本地 / 青龙一样）

```text
┌─────────────────┐     扫码成功      ┌──────────────────────────┐
│  get_cookie.py  │ ───────────────► │ bilibili_cookie_cache.json│
│  （手动，偶尔）  │                   │ 或 BILI_COOKIE_FILE      │
└─────────────────┘                   └────────────┬─────────────┘
                                                   │ 读取
                                                   ▼
                                          ┌─────────────────┐
                                          │   daily.py      │
                                          │ （每天定时）     │
                                          └─────────────────┘
```

1. **先**运行 `get_cookie.py`，手机扫码，Cookie 写入缓存文件  
2. **再**跑 `daily.py` 做任务；有 Cookie 就直接干  
3. 若 Cookie 过期：`daily.py` **不会**傻等扫码，而是通知你去跑 `get_cookie.py`  
4. 重新扫码成功后，下次 / 再跑一次 `daily.py` 即可  

不推荐把扫码绑在每天的 cron 里（没人看日志扫码会超时）。

---

## 青龙订阅

仓库：`https://github.com/WillpowerJin/ql-scripts.git`

| 字段 | 建议 |
|------|------|
| 白名单 | `bilibili`（或含在 `checkin\|read_gift\|xijiu\|bilibili`） |
| 黑名单 | `README\|config\|example\|requirements\|\.md\|\.yaml\|cookie_cache\|login_qr` |
| 扩展名 | `py` |

依赖：青龙「依赖管理」安装 `requests` `cryptography` `qrcode` `Pillow` `PyYAML`（或任务里 `pip install`）。

### 任务建议

| 任务名 | 命令 | 定时 |
|--------|------|------|
| B站获取Cookie | `task .../bilibili/get_cookie.py` | **禁用定时**，需要时手动运行 |
| B站每日任务 | `task .../bilibili/daily.py` | `30 7 * * *` |

**脚本调试没有日志时：**

1. 确认同目录有 `daily.py`（订阅白名单含 `bilibili`）  
2. 依赖管理安装：`requests` `cryptography` `qrcode` `Pillow` `PyYAML`  
3. 命令建议加无缓冲：`python3 -u get_cookie.py`（或任务前缀 `python3 -u`）  
4. 成功启动时日志**第一行**应是：`[get_cookie] start`  
   - 若连这行都没有：看的是旧文件 / 跑错任务 / 未保存订阅  
   - 若有 start 随后报 import：按提示装依赖

可选环境变量：

```text
BILI_NAME=主号
BILI_COOKIE_FILE=/ql/data/bilibili_cookie_cache.json   # 不设也有默认
BILI_COIN_NUM=5
BILI_SILVER2COIN=1
BILI_MANGA_SIGN=1
BILI_VIP_TASKS=1
BILI_LIVE_SIGN=0          # 直播签到多已下线

BARK_URL / BARK_KEY       # 通知（扫码图、任务结果）
```

### Cookie 存哪

| 环境 | 默认路径 |
|------|----------|
| 青龙 | `/ql/data/bilibili_cookie_cache.json`（**不在**仓库目录，更新订阅不会冲掉） |
| 本地 | `bilibili/cookie_cache.json` |
| 自定义 | 环境变量 `BILI_COOKIE_FILE` |

也支持直接设 `BILI_COOKIE=SESSDATA=...; bili_jct=...`（见下），优先于缓存文件。

---

## 本地使用

```bash
cd bilibili
uv pip install -r requirements.txt   # 或 pip install -r requirements.txt

# 1）扫码拿 Cookie（只需偶尔做）
uv run get_cookie.py

# 2）每日任务
uv run daily.py
uv run daily.py --info-only
```

扫码时（`get_cookie.py`）：

1. **任务日志 / 终端里直接画出 ASCII 二维码** → 手机 B 站对着屏幕扫  
2. 同时打印**在线图片链接**；若配置了 Bark 也会推送该链接  
3. **不要**用浏览器打开 `passport.../auth?auth_code=...` 登录链接本身  

兼容：`uv run daily.py --qr`（更推荐单独跑 `get_cookie.py`）。

---

## 任务清单

### 主站经验（脚本会标【完成度】）

| 项目 | 经验 |
|------|------|
| 登录 | +5 |
| 观看 | +5 |
| 分享 | +5 |
| 投币最多 5 枚 | +50 |

满做约 **+65/天**（Lv6 后经验条显示 `--` 仍可做）。

### 扩展

| 任务 | 默认 | 备注 |
|------|------|------|
| 银瓜子兑硬币 | 开 | 余额不足会提示，正常 |
| 漫画签到 | 开 | 与主站经验无关 |
| 直播签到 | **关** | 官方多已下线 |
| 大会员额外经验 / 大积分 | 开 | 需扫码拿到的 access_token |
| 每月 1/15 大会员福利 | 开 | 有大会员才试 |

---

## 浏览器粘贴 Cookie（可选）

```yaml
# config.yaml
accounts:
  - name: "主号"
    cookie: "SESSDATA=xxx; bili_jct=yyy; DedeUserID=zzz"
```

或环境变量 `BILI_COOKIE` / `BILI_ACCOUNTS` JSON。

账密登录接口仍在，但 **强制极验**，不保证自动过；请用扫码。

---

## 文件

| 文件 | 说明 |
|------|------|
| `get_cookie.py` | 扫码获取 Cookie |
| `daily.py` | 每日任务 |
| `config.example.yaml` | 配置模板 |
| `requirements.txt` | 依赖 |
