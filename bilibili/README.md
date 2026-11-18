# B 站每日任务（青龙 / 本地）

扫码拿 Cookie，定时做登录 / 观看 / 分享 / 银瓜子兑硬币 / 漫画签到。  
**投币默认关（保硬币）**，经验约 +15/天；要满额 +65 再把 `BILI_COIN_NUM` 设成 `1`～`5`。

| 脚本 | 说明 | 怎么跑 |
|------|------|--------|
| [`get_cookie.py`](./get_cookie.py) | 手机 B 站扫码拿 Cookie | **手动**（失效时） |
| [`daily.py`](./daily.py) | 每日任务 | 本地先测，再挂青龙 cron |

> 仅供学习研究。请遵守 B 站用户协议。

---

## 本地测试

```bash
cd bilibili
uv pip install -r requirements.txt   # 或 pip install -r requirements.txt
```

```text
1) 看缓存里有没有号
   uv run daily.py --list
   # 没有 → uv run get_cookie.py   （终端出码，手机 B 站扫一扫）

2) 只查登录，不跑任务、不推送
   uv run daily.py --info-only

3) 真跑一轮（默认不投币；本地可不推 Bark）
   uv run daily.py --no-notify
```

扫码注意：对着终端 ASCII 码或日志里的图片链接扫；**不要**用浏览器打开 `passport.../auth?auth_code=...`。

Cookie 默认写在本目录 `cookie_cache.json`（已 gitignore）。同一号再扫按 mid 更新，换号再扫会新增。

临时投 5 枚：`uv run daily.py --coin 5 --no-notify`。  
只跑某一个：`uv run daily.py --account 昵称或mid`。

可选本地配置：

```bash
cp config.example.yaml config.yaml   # 勿提交
```

```yaml
coin_num: 0          # 保硬币；满额经验改 1～5
silver2coin: true
manga_sign: true
accounts:
  - name: "主号"
    cookie: "SESSDATA=xxx; bili_jct=yyy; DedeUserID=zzz"
```

不配 `accounts` 也行，`daily.py` 会读扫码缓存。

---

## 青龙订阅

仓库：`https://github.com/WillpowerJin/ql-scripts.git`

已有总订阅时，白名单包含 `bilibili` 后点运行即可。单独拉：

```text
链接：     https://github.com/WillpowerJin/ql-scripts.git
分支：     main
白名单：   bilibili
黑名单：   README|config|example|requirements|cookie_cache|login_qr
扩展名：   py
```

直连失败可用：`https://ghfast.top/https://github.com/WillpowerJin/ql-scripts.git`

依赖：`requests`；扫码画码可选 `qrcode` `Pillow`。

| 任务 | 命令 | 定时 |
|------|------|------|
| B站获取Cookie | `python3 -u .../bilibili/get_cookie.py` | **手动** |
| B站每日任务 | `.../bilibili/daily.py` | `30 7 * * *` |

Cookie 在青龙默认写 `/ql/data/bilibili_cookie_cache.json`（不在仓库目录，更新订阅不会冲掉）。

`get_cookie.py` 无日志时：命令加 `-u`，看**定时任务 → 日志**，应出现 `[get_cookie] start`。

---

## 环境变量

账号、Cookie、Bark 只写青龙环境变量或本地 `config.yaml`，不要进仓库。

| 变量 | 说明 | 默认 |
|------|------|------|
| （推荐）扫码缓存 | 跑一次 `get_cookie.py` | |
| `BILI_COOKIE` | `SESSDATA=...; bili_jct=...; DedeUserID=...`，多账号 `&` | |
| `BILI_ACCOUNTS` | JSON：`[{"name":"主号","cookie":"..."}]` | |
| `BILI_COOKIE_FILE` | 缓存路径 | 青龙 `/ql/data/bilibili_cookie_cache.json` |
| `BILI_COIN_NUM` | 投币 `0`～`5`，**0=保硬币** | **0** |
| `BILI_SILVER2COIN` | 银瓜子兑硬币（每天最多 +1） | `1` |
| `BILI_MANGA_SIGN` | 漫画签到 | `1` |
| `BILI_VIP_TASKS` | 大会员经验 / 大积分 / 月度福利 | `1` |
| `BILI_LIVE_SIGN` | 直播签到（多已下线） | `0` |
| `BARK_URL` 或 `BARK_KEY` | 通知，与其它脚本共用 | 不配则只打日志 |

以前设过 `BILI_COIN_NUM=5` 或 `config.yaml` 里 `coin_num: 5` 仍会投币，改成 `0` 或删掉。

---

## 任务清单

| 项目 | 经验 / 说明 | 默认 |
|------|-------------|------|
| 登录 | +5 | 做 |
| 观看 | +5 | 做 |
| 分享 | +5 | 做 |
| 投币最多 5 枚 | +50 | **关（保硬币）** |
| 银瓜子兑硬币 | 每天最多 +1 硬币 | 开 |
| 漫画签到 | 卡券，与主站经验无关 | 开 |
| 大会员额外经验 / 大积分 / 1·15 福利 | 福利是 B 币券，不是硬币 | 开（需扫码带上的 access_token） |
| 直播签到 | 官方多已下线 | 关 |

摘要末尾会打 `💰 硬币 改前 → 改后`。银瓜子不够兑时提示「未兑换」是正常的。

账密登录仍会撞极验，请用扫码。
