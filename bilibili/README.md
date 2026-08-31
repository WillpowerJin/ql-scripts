# B 站每日任务（扫码 Cookie + 青龙 / Quantumult X）

对齐 [ClydeTime/BiliBili.js](https://raw.githubusercontent.com/ClydeTime/Quantumult/main/Script/Task/BiliBili.js) 的日常能力。

| 脚本 | 说明 | 运行方式 |
|------|------|----------|
| [`get_cookie.py`](./get_cookie.py) | 手机 B 站**扫码**拿 Cookie（**可单独运行**） | **手动**（失效时跑） |
| [`daily.py`](./daily.py) | 每日经验 / 扩展任务 | **青龙定时** cron |
| [`quantumultx/bilibili_cookie.js`](./quantumultx/bilibili_cookie.js) | 打开 App 自动抓 Cookie | QuanX **重写** |
| [`quantumultx/bilibili_daily.js`](./quantumultx/bilibili_daily.js) | 与 Python 同套任务 | QuanX **定时任务** |

> 仅供学习研究。请遵守 B 站用户协议。

**投币默认关闭（保硬币）。** 只做登录 / 观看 / 分享 + 银瓜子兑硬币，经验约 **+15/天**，硬币不再每天 -5。  
若以后要满额经验（+65），把 `BILI_COIN_NUM` 或 `coin_num` 改成 `1`～`5`。

---

## 正确流程（本地 / 青龙一样）

```text
┌─────────────────┐     扫码成功      ┌──────────────────────────┐
│  get_cookie.py  │ ───────────────► │ bilibili_cookie_cache.json│
│  （手动，可多次）  │   按 mid 去重    │ 可存多账号               │
└─────────────────┘                   └────────────┬─────────────┘
                                                   │ 读取全部
                                                   ▼
                                          ┌─────────────────┐
                                          │   daily.py      │
                                          │ 逐个号做任务     │
                                          └─────────────────┘
```

1. **先**运行 `get_cookie.py`，手机扫码，Cookie 写入缓存文件  
2. **再**跑 `daily.py` 做任务；有 Cookie 就直接干  
3. 若 Cookie 过期：`daily.py` **不会**傻等扫码，而是通知你去跑 `get_cookie.py`  
4. 重新扫码成功后，下次 / 再跑一次 `daily.py` 即可  

iPhone 也可以用 **Quantumult X 打开 App 抓 Cookie**，再贴到青龙，或直接在 QX 里跑每日任务（见下文）。

### 多账号

| 操作 | 行为 |
|------|------|
| 再跑一次 `get_cookie.py`，**换号**后扫码 | **新增**一条（用 B 站昵称区分） |
| 同一号再扫 | 按 `mid` 判断为同一账号 → **更新** Cookie，不重复建档 |
| `get_cookie.py --account 备注` | 可用自定义备注；仍按 mid 去重 |
| `daily.py` | **自动跑缓存里全部账号**；日志标题用昵称 |
| `daily.py --account 昵称或mid` | 只跑某一个 |

不推荐把扫码绑在每天的 cron 里（没人看日志扫码会超时）。

---

## 青龙订阅

仓库：`https://github.com/WillpowerJin/ql-scripts.git`

| 字段 | 建议 |
|------|------|
| 白名单 | `bilibili`（或根 README 那条总白名单） |
| 黑名单 | `README\|config\|example\|requirements\|\.md\|\.yaml\|cookie_cache\|login_qr\|quantumultx` |
| 扩展名 | `py` |

依赖：青龙「依赖管理」加 `requests`；扫码画码可选 `qrcode` `Pillow`。本地 yaml 再加 `PyYAML`。

### 面板怎么填（复制代码块，不要带 `\`）

青龙 → **订阅管理** → **创建订阅**（若已有本仓库订阅，改白名单包含 `bilibili` 后点运行即可）。

```text
名称：     ql-scripts
类型：     公开仓库
链接：     https://github.com/WillpowerJin/ql-scripts.git
分支：     main
白名单：   hifiti|xijiu|quark|bilibili|fanghua|bafu|fun|tuiguangbao|aliyun_dev|kuailefeng
黑名单：   pull_access_token
扩展名：   py
定时规则： 30 8 * * *
```

命令行等价：

```bash
ql repo https://github.com/WillpowerJin/ql-scripts.git "hifiti|xijiu|quark|bilibili|fanghua|bafu|fun|tuiguangbao|aliyun_dev|kuailefeng" "pull_access_token" "" "main" "py"
```

直连 GitHub 失败可用镜像，例如：

```text
https://ghfast.top/https://github.com/WillpowerJin/ql-scripts.git
```

拉成功后脚本管理里应有：

```text
…/bilibili/daily.py
…/bilibili/get_cookie.py
```

`quantumultx/` 是 JS，扩展名 `py` 不会进青龙。

### 任务建议

| 任务名 | 命令 | 定时 |
|--------|------|------|
| B站获取Cookie | `python3 -u .../bilibili/get_cookie.py` | 文件内 cron 仅保证拉库建任务；请改为 **手动执行** |
| B站每日任务 | `.../bilibili/daily.py` | `30 7 * * *` |

**脚本调试没有日志时：**

1. `get_cookie.py` **可单文件运行**  
2. 命令用：`python3 -u get_cookie.py`  
3. 日志应出现：`[get_cookie] start`；若没有 → 未真正运行 / 看错面板（请用**定时任务 → 日志**）

### Cookie 存哪

| 环境 | 默认路径 |
|------|----------|
| 青龙 | `/ql/data/bilibili_cookie_cache.json`（**不在**仓库目录，更新订阅不会冲掉） |
| 本地 | `bilibili/cookie_cache.json` |
| 自定义 | 环境变量 `BILI_COOKIE_FILE` |

也支持直接设 `BILI_COOKIE=SESSDATA=...; bili_jct=...; DedeUserID=...`，优先于缓存文件。

---

## 环境变量

青龙 → **环境变量**。账号、Cookie、Bark **不要写进仓库**。

### 账号（任选一种）

| 变量 | 说明 |
|------|------|
| （推荐）扫码缓存 | 跑一次 `get_cookie.py`，无需再配 Cookie |
| `BILI_COOKIE` | `SESSDATA=...; bili_jct=...; DedeUserID=...`，多账号用 `&` 分隔 |
| `BILI_ACCOUNTS` | JSON 数组，例：`[{"name":"主号","cookie":"SESSDATA=...; bili_jct=..."}]` |
| `BILI_NAME` | 账号备注，可选 |

### 任务开关

| 变量 | 说明 | 默认 |
|------|------|------|
| `BILI_COIN_NUM` | 每日投币次数 `0`～`5`。**`0`=不投币，保硬币** | **0** |
| `BILI_SILVER2COIN` | 银瓜子兑硬币（每天最多 +1，700 银瓜子） | `1` 开 |
| `BILI_MANGA_SIGN` | 漫画签到 | `1` 开 |
| `BILI_VIP_TASKS` | 大会员额外经验 / 大积分 / 每月福利 | `1` 开 |
| `BILI_LIVE_SIGN` | 直播签到（官方多已下线） | `0` 关 |
| `BILI_COOKIE_FILE` | Cookie 缓存路径 | 青龙 `/ql/data/bilibili_cookie_cache.json` |

以前如果手动设过 `BILI_COIN_NUM=5`，拉库后仍会投 5 枚，请改成 `0` 或删掉该变量。  
本地 `config.yaml` 里若写了 `coin_num: 5` 同样会投币，改成 `0`。

临时跑一次仍要投币：`python3 daily.py --coin 5`。

### 通知（与其它脚本共用）

| 变量 | 说明 |
|------|------|
| `BARK_URL` | App 完整推送地址，如 `https://api.day.app/你的Key/` |
| 或 `BARK_KEY` | 仅 Key |
| `BARK_SERVER` | 自建，默认 `https://api.day.app` |
| `BARK_GROUP` | 分组，默认 `B站每日任务` |

未配 `BARK_*` 时只打日志、不推送。

---

## Quantumult X

### 任务图库（推荐，一键导入）

在 Quantumult X 里加这一条（jsDelivr，国内比 GitHub raw 稳）：

```text
https://cdn.jsdelivr.net/gh/WillpowerJin/ql-scripts@main/quantumultx/gallery.json
```

镜像备用：

```text
https://ghfast.top/https://raw.githubusercontent.com/WillpowerJin/ql-scripts/main/quantumultx/gallery.json
```

步骤：

1. QX 首页右下角风车 → **任务** → 右上角 **图库** → **添加** → 贴上面的链接  
2. 进入图库，打开 **B站每日任务** → 添加  
3. 提示关联重写时选 **是**（会带上「B站_获取Cookie」）  
4. **MitM** 已信任证书，且主机名含 `app.bilibili.com`  
5. **后台划掉**哔哩哔哩（不要只切到桌面）→ 再打开进首页 → 点「我的」  
6. 弹出 `📺 B站Cookie·v2` 即抓成功；再到任务列表手动跑一次每日任务  

默认不投币（保硬币）。以后要投币：任务参数填 `coin=5`。

若你已经加过旧图库：重写列表里找到 **B站_获取Cookie**，**右滑更新**；任务脚本同样更新一次。

也可以只用抓 Cookie、任务仍给青龙跑：图库添加后把重写留下、把定时任务关掉即可。

### 没有弹出 Cookie 通知时

按顺序查：

1. 重写资源 **B站_获取Cookie** 是开着的，并已「更新」（脚本地址应是 jsDelivr，不是 `raw.githubusercontent.com`）  
2. MitM 总开关打开，证书已信任，主机名有 `app.bilibili.com`（不要在「跳过 MitM」里）  
3. **从后台划掉 B 站再开**，进首页后再点「我的」（热启动往往打不出 fingerprint）  
4. 通知标题应是 `📺 B站Cookie·v2`：  
   - **已缓存 / 已更新**：成功  
   - **重写已命中，但还不是网页 Cookie**：正常。App 首页/「我的」走原生接口，只有 `access_key`，没有 `SESSDATA`。再打开 **直播、漫画、或「我的 → 大会员」**（这些是内置网页，才会带 SESSDATA）  
   - **完全没通知、日志也没有 `bili-cookie`**：重写没执行。多半是脚本没下下来，或流量没进 MitM（可在 QX 里关 HTTP/3 后再试）

---

两件事分开：**抓 Cookie**（重写）和 **跑每日任务**（定时）。下面是不走图库、手搓配置的备用写法。完整片段见 [`quantumultx/bilibili.snippet.conf`](./quantumultx/bilibili.snippet.conf)。

### 1）MitM + 重写（抓 Cookie）

1. QX → **MitM**：安装并信任证书；`hostname` **追加** `app.bilibili.com`（不要覆盖原有名单）
2. QX → **重写** → 编辑，贴上：

```text
[rewrite_local]
^https?:\/\/app\.bilibili\.com\/x\/(resource\/fingerprint|v2\/account\/myinfo) url script-request-header bilibili_cookie.js

[mitm]
hostname = app.bilibili.com
```

3. 把 `bilibili_cookie.js` 放到：文件 App → iCloud / 我的 iPhone → **Quantumult X → Scripts**
4. 右下角圆形按钮 **重载配置**
5. **后台划掉** B 站再打开，进首页并点「我的」，应弹出 `📺 B站Cookie·v2`  
   正文就是可直接贴到青龙的：

```text
SESSDATA=...; bili_jct=...; DedeUserID=...
```

通知可能被 iOS 截断：QX → 工具 → **日志** → 搜 `bili-cookie` → 复制 `cookie=` 后面整行最稳。

Cookie 写入 `$prefs.bili_cookie`；若请求 URL 带 `access_key`，同时写入 `bili_access_token`。同一 Cookie 5 分钟内不重复弹通知。

### 2）定时任务（QX 自己跑）

```text
[task_local]
30 7 * * * bilibili_daily.js, tag=B站每日任务, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/bilibili.png, enabled=true
```

把 `bilibili_daily.js` 同样放到 Scripts 目录。任务读 `$prefs.bili_cookie`，**默认不投币**。

| 想改什么 | 做法 |
|----------|------|
| 仍要投 5 枚 | 任务参数 `argument=coin=5`，或 `$prefs` 键 `bili_coin_num` = `5` |
| 关掉银瓜子兑换 | `argument=silver2coin=0` 或键 `bili_silver2coin` = `0` |
| 不抓包、手填 Cookie | 任务 `argument=cookie=SESSDATA=...; bili_jct=...` |
| 多账号 | `$prefs.bili_accounts` 填 JSON：`[{"name":"主号","cookie":"..."}]` |

手填任务参数示例（QX 任务 → 参数）：

```text
cookie=SESSDATA=xxx; bili_jct=yyy; DedeUserID=zzz&coin=0
```

### 3）QX 抓完 → 贴到青龙

通知/日志里的 Cookie 整段贴到青龙环境变量 `BILI_COOKIE`，或再跑一次 `get_cookie.py` 扫码（两套互不冲突，同一 mid 会合并）。

---

## 本地使用

```bash
cd bilibili
uv pip install -r requirements.txt   # 或 pip install -r requirements.txt

# 1）扫码拿 Cookie（只需偶尔做）
uv run get_cookie.py

# 2）每日任务（默认不投币）
uv run daily.py
uv run daily.py --info-only
uv run daily.py --coin 5          # 临时投 5 枚
```

扫码时（`get_cookie.py`）：

1. **任务日志 / 终端里直接画出 ASCII 二维码** → 手机 B 站对着屏幕扫  
2. 同时打印**在线图片链接**；若配置了 Bark 也会推送该链接  
3. **不要**用浏览器打开 `passport.../auth?auth_code=...` 登录链接本身  

兼容：`uv run daily.py --qr`（更推荐单独跑 `get_cookie.py`）。

---

## 任务清单

### 主站经验（脚本会标【完成度】）

| 项目 | 经验 | 默认 |
|------|------|------|
| 登录 | +5 | 做 |
| 观看 | +5 | 做 |
| 分享 | +5 | 做 |
| 投币最多 5 枚 | +50 | **关（保硬币）** |

默认约 **+15/天**。打开投币满做约 **+65/天**（Lv6 后经验条显示 `--` 仍可做）。

### 扩展

| 任务 | 默认 | 备注 |
|------|------|------|
| 银瓜子兑硬币 | 开 | 每天最多 +1 硬币；余额不足会提示，正常 |
| 漫画签到 | 开 | 与主站经验无关 |
| 直播签到 | **关** | 官方多已下线 |
| 大会员额外经验 / 大积分 | 开 | 需扫码或 QX 抓到的 access_token |
| 每月 1/15 大会员福利 | 开 | 有大会员才试；发的是 B 币券，不是硬币 |

硬币进出：默认不花；银瓜子兑成功时每天最多 **+1**。登录奖励由 B 站服务器自动发（官方仍写 Lv1+ 绑手机），脚本不用另领。

---

## 浏览器粘贴 Cookie（可选）

```yaml
# config.yaml
accounts:
  - name: "主号"
    cookie: "SESSDATA=xxx; bili_jct=yyy; DedeUserID=zzz"

coin_num: 0          # 保硬币；满额经验改 1～5
silver2coin: true
```

或环境变量 `BILI_COOKIE` / `BILI_ACCOUNTS` JSON。

账密登录接口仍在，但 **强制极验**，不保证自动过；请用扫码或 QX 抓包。

---

## 文件

| 文件 | 说明 |
|------|------|
| `get_cookie.py` | 扫码获取 Cookie（青龙） |
| `daily.py` | 每日任务（青龙） |
| `quantumultx/bilibili_cookie.js` | QX 抓 Cookie |
| `quantumultx/bilibili_cookie.qxrewrite` | 图库关联重写 |
| `quantumultx/bilibili_daily.js` | QX 每日任务 |
| `quantumultx/bilibili.snippet.conf` | 手搓 rewrite / task 片段 |
| [`../quantumultx/gallery.json`](../quantumultx/gallery.json) | QX 任务图库（目前仅 B 站） |
| `config.example.yaml` | 配置模板 |
| `requirements.txt` | 依赖 |
