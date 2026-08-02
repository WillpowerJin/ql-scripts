# 阿里云开发者社区日常任务

[← 返回脚本总览](../README.md)

[阿里云开发者社区](https://developer.aliyun.com/) 签到 / 互动 / 领积分。  
可读 Python 重写，逻辑参考 [leiyiyan/aliyun_web.js](https://raw.githubusercontent.com/leiyiyan/resource/main/script/aliyun_web/aliyun_web.js)；完整度对齐 [hifiti](../hifiti/)。

> 账号 / 密码 / Cookie / Bark **不要写进仓库**，用青龙环境变量或本地 `config.yaml`。

## 策略

1. **Cookie 优先**（密码登录易被滑块拦截，不推荐当主路径）  
2. **每次运行都做赚分**（不再「下午只清理」）：  
   - 社区签到  
   - 文章点赞 / 收藏 / 分享 / 评论（约 8 篇）  
   - 电子书评价、问答点赞  
   - 轻量场景体验 + 直播心跳（可用环境变量关闭）  
   - 自动收取「待领取」积分  
3. **12 点后**额外清理收藏/点赞，释放次日额度  
4. Bark / Server酱 / Webhook 推送结果  

> 今日若已签到，再跑只会跳过签到；互动类有日限额，重复跑增量会变少。

## 仓库文件

| 文件 | 青龙 | 说明 |
|------|------|------|
| `daily.py` | ✅ | 主脚本 |
| `README.md` | ❌ | 本文档 |
| `config.example.yaml` | ❌ | 本地示例 |
| `requirements.txt` | ❌ | 依赖 |
| `origin_aliyun_web.js` | ❌ | 原混淆脚本对照 |

青龙依赖：`requests`。

## 青龙部署（复制即用）

### 1. 订阅白名单

在原有白名单末尾加上 `aliyun_dev`：

```text
hifiti|wangchao|xijiu|quark|bilibili|fanghua|bafu|fun|junpinhui|tuiguangbao|duoxiang|aliyun_dev
```

| 字段 | 值 |
|------|-----|
| 黑名单 | `pull_access_token` |
| 扩展名 | `py` |
| 分支 | `main` |

保存后点 **运行** 订阅，应出现 `…/aliyun_dev/daily.py`。

只拉本项目：

```bash
ql repo https://github.com/WillpowerJin/ql-scripts.git "aliyun_dev" "pull_access_token" "" "main" "py"
```

### 2. 依赖

依赖管理 → Python3 → 添加：`requests`

### 3. 环境变量（Cookie，推荐）

**方式 A — 整段 Cookie（兼容原脚本名）：**

```text
名称：aliyunWeb_data
值：  c_csrf=...; login_aliyunid_ticket=...; isg=...; ...
```

**方式 B — JSON（支持备注名）：**

```text
名称：ALIYUN_ACCOUNTS
值：
[{"name":"主号","token":"c_csrf=...; login_aliyunid_ticket=...; isg=..."}]
```

> `token` 字段即整段 Cookie（与手机抓包格式一致）。  
> **不要**只配 username/password（会触发滑块，脚本会报未登录）。  
> 环境变量优先于本地 `config.yaml`；Cookie 过期后更新此变量即可。

可选：`BARK_URL` 或 `BARK_KEY`（推送结果）。

### 4. 定时任务

| 项 | 建议 |
|----|------|
| 脚本 | `aliyun_dev/daily.py` |
| 定时 | `0 7,13 * * *` |
| 超时 | **≥ 20 分钟** |
| 参数 | 无需参数（默认完整版） |

| 时间 | 完整版内容 |
|------|------------|
| **07:00** | 签到 + 互动 + 电子书/问答 + 场景/视频 + **领取待收积分** + 清理 |
| **13:00** | 同上（补领延迟入账积分 + 再清理） |

`python daily.py` = 完整版（已含领取积分）。一般不必加 `--phase`。

## 环境变量（账号）

### A. 推荐 `ALIYUN_ACCOUNTS` JSON

```json
[
  {
    "name": "主号",
    "username": "你的用户名或邮箱",
    "password": "密码"
  },
  {
    "name": "手机号登录",
    "phone": "13800138000",
    "password": "密码"
  },
  {
    "name": "Cookie号",
    "cookie": "login_aliyunid_ticket=xxx; cna=yyy; ..."
  }
]
```

也兼容**手机抓包 / 原脚本**数组（`token` 字段就是 Cookie）：

```json
[
  {
    "userId": "aliyunxxxx",
    "userName": "aliyunxxxx",
    "token": "login_aliyunid_ticket=...; c_csrf=...; cna=...; isg=..."
  }
]
```

- 只填 `username`/`phone` + `password`：走通行证登录（易被滑块拦截）  
- 只填 `cookie` 或 `token`：**推荐**  
- 都填：Cookie 优先，失效再试密码  

**实测说明**：阿里云网页密码登录多数环境会强制滑块/短信，脚本无法自动过验证码；日常请用 APP/浏览器抓 Cookie，过期后重新抓。

### B. 兼容原脚本 Cookie

```text
aliyunWeb_data=你的Cookie
# 或多账号 @ / & 分隔
```

也可用 `ALIYUN_WEB_DATA` / `ALIYUN_COOKIE`。

### C. 平行变量（`&` 分隔多账号）

| 变量 | 说明 |
|------|------|
| `ALIYUN_USER` / `ALIYUN_USERNAME` | 用户名或邮箱 |
| `ALIYUN_PHONE` | 手机号 |
| `ALIYUN_PASS` / `ALIYUN_PASSWORD` | 密码 |
| `ALIYUN_COOKIE` | Cookie |
| `ALIYUN_NAME` | 备注 |

单账号示例：

```text
ALIYUN_USER=myname
ALIYUN_PASS=mypassword
```

或：

```text
ALIYUN_PHONE=13800138000
ALIYUN_PASS=mypassword
```

## 获取 Cookie（密码滑块时）

1. 浏览器登录 https://developer.aliyun.com  
2. F12 → Network → 任意 `developer.aliyun.com` 请求 → 复制 `Cookie`  
3. 或：阿里云 APP → 首页 → 积分商城（配合 Quantumult X / 抓包）  
4. 写入 `ALIYUN_ACCOUNTS` 的 `cookie` 或 `aliyunWeb_data`  

**不要在网站点退出**，否则 Cookie 立即失效。

## 可选变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `ALIYUN_TIME` / `aliyunWeb_time` | 上下午分界小时 | `12` |
| `ALIYUN_SCENE` / `aliyunWeb_scene` | 场景实验 | 关 |
| `ALIYUN_VIDEO` / `aliyunWeb_video` | 视频任务 | 关 |
| `ALIYUN_STOCK` / `aliyunWeb_stock` | 打印商城库存 | 关 |
| `ALIYUN_TIMEOUT` | 超时秒 | `30` |
| `ALIYUN_SESSION_CACHE` | 会话缓存路径 | `/ql/data` 或脚本目录 |
| `DRY_RUN=1` | 只验登录与积分 | 关 |
| `BARK_URL` / `BARK_KEY` | Bark 通知 | |

## 本地运行

```bash
cd aliyun_dev
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填账号，勿 git add
python daily.py
python daily.py --login-only -v
python daily.py --dry-run
python daily.py --phase am           # 强制上午任务
python daily.py --phase pm           # 强制下午任务
```

## 接口概览

| 用途 | 路径 |
|------|------|
| 用户 | `/developer/api/my/user/getUser` |
| 积分 | `/developer/api/my/score/getUserScore` |
| 待领/收取 | `/score/pending/getUserTotalPendingScore` · `receiveAllPendingScore` |
| 签到详情 | `/sign/getUserSpaceSignInDetail` |
| 任务 | `/task/getTaskGroup` · `/task/actionLog` |
| 签到奖 | `/sign/assessSignInBonusQualification` · `receiveSignInBonus` |
| 互动 | `ucc.aliyun.com/uccPagingComponent/likeOrNotLike` · `addComment` |

## 注意事项

1. **评论需审核**，故建议按 7 点 / 13 点拆成两次跑（与原作者说明一致）。  
2. 密码登录接口可能变更或强制滑块，**生产环境更推荐 Cookie**。  
3. 场景 / 视频任务默认关闭（不稳定、耗时长）。  

## 依赖

- 青龙：`requests`  
- 本地 yaml：`requests` + `PyYAML`  
