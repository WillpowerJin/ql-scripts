# HiFiNi 自动签到（青龙 + Bark）

[← 返回脚本总览](../README.md)

针对 [https://www.hifiti.com](https://www.hifiti.com/)（音乐磁场）的每日签到脚本。

> 账号 / Cookie / Bark 等敏感信息只写在**青龙环境变量**（或本地不提交的 `config.yaml`），不要提交到 Git。

## 策略

1. **优先 Cookie 签到**
2. Cookie 返回「请登录」且配置了账号密码 → **自动重新登录再签**
3. 配置优先读 **青龙 / 系统环境变量**（本地也可 `config.yaml`）
4. 结果可推送 **Bark**（可选，稍后配置即可）

## 仓库内文件

| 文件 | 是否进青龙 | 说明 |
|------|------------|------|
| `checkin.py` | ✅ 拉取 | 签到主脚本 |
| `README.md` | ❌ 不拉 | 本文档（GitHub 二级页） |
| `config.example.yaml` | ❌ 不拉 | 本地配置示例 |
| `requirements.txt` | ❌ 不拉 | 本地依赖清单 |

青龙侧依赖在「依赖管理」手动添加：`requests`。

## 青龙订阅

在仓库根目录 [README](../README.md) 有通用订阅命令。若只拉本脚本，可用：

```bash
ql repo https://github.com/WillpowerJin/ql-scripts.git "checkin" "README|config|example|requirements|\.md|\.yaml|\.yml|\.txt" "" "main" "py"
```

订阅成功后应只出现 `checkin.py` 相关定时任务，而不是一堆 md/yaml。

定时（脚本头已写，也可自行改）：

```
0 8 * * *
```

## 环境变量（账号）

### 方式 A（推荐）：`HIFINI_ACCOUNTS` JSON

Cookie + 密码备用，多账号最清晰：

```json
[
  {
    "name": "主号",
    "domain": "www.hifiti.com",
    "cookie": "bbs_sid=xxx; bbs_token=yyy",
    "username": "你的用户名或邮箱",
    "password": "你的密码"
  }
]
```

- 只填 `cookie`：纯 Cookie 签到  
- 只填 `username` + `password`：每次登录签到  
- **两者都填**：Cookie 优先，失效后自动密码重登（推荐）

青龙里注意 JSON 合法；密码中若有 `"` 需转义。

### 方式 B：平行变量（`&` 分隔多账号）

| 变量 | 说明 |
|------|------|
| `HIFINI_COOKIE` | Cookie，多账号 `&` 分隔 |
| `HIFINI_USERNAME` | 用户名，与 Cookie **按下标对齐** |
| `HIFINI_PASSWORD` | 密码，与上面对齐 |
| `HIFINI_NAME` | 可选备注 |
| `HIFINI_DOMAIN` | 可选，默认 `www.hifiti.com` |

示例（单账号 Cookie + 备用密码）：

```text
HIFINI_COOKIE=bbs_sid=aaa; bbs_token=bbb
HIFINI_USERNAME=myuser
HIFINI_PASSWORD=mypass
HIFINI_NAME=主号
```

### 方式 C：仅密码 `HIFINI_LOGIN`

```text
域名|用户名|密码
```

多账号用 `&` 连接。

## 环境变量（Bark，可选）

| 变量 | 说明 |
|------|------|
| `BARK_URL` | App 里复制的完整地址，如 `https://api.day.app/你的Key/` |
| 或 `BARK_KEY` | 仅 Key |
| `BARK_SERVER` | 可选，自建服务器，默认 `https://api.day.app` |
| `BARK_GROUP` | 可选，通知分组，默认 `HiFiNi` |
| `BARK_SOUND` | 可选，铃声 |
| `BARK_ICON` | 可选，图标 URL |
| `BARK_LEVEL` | 可选：`active` / `timeSensitive` / `passive` |

获取：iOS 安装 [Bark](https://github.com/Finb/Bark) → 打开 App 复制推送 URL。

## 可选其它变量

| 变量 | 说明 |
|------|------|
| `HIFINI_TIMEOUT` | 请求超时秒数，默认 20 |
| `HIFINI_MAX_RETRIES` | 重试次数，默认 3 |
| `HIFINI_RETRY_INTERVAL` | 重试间隔秒，默认 15 |
| `SERVERCHAN_KEY` | 可选，Server酱 |
| `WEBHOOK_URL` | 可选，自定义 Webhook |

## 本地运行

```bash
cd hifiti
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填写后不要 git add
python checkin.py
```

或导出与青龙相同的环境变量后直接运行：

```bash
export HIFINI_ACCOUNTS='[...]'
export BARK_URL='https://api.day.app/xxxx/'
python checkin.py
```

## 获取 Cookie

1. 登录 https://www.hifiti.com  
2. F12 → Network → 复制 `Cookie`（需含 `bbs_sid`、`bbs_token`）  
3. **不要点网站「退出」**，否则 Cookie 立刻失效  

## 日志含义

| 标记 | 含义 |
|------|------|
| `[cookie]` | Cookie 签到成功 |
| `[cookie→password]` | Cookie 失效后，密码重登再签成功 |
| `[password]` | 仅密码登录签到 |
| `[cookie→login_failed]` | Cookie 挂了，密码登录也失败 |
| `金币: N` | 签到成功后从个人中心读取的当前金币余额 |

## 接口说明

| 步骤 | 方法 | URL | 说明 |
|------|------|-----|------|
| 登录 | POST | `/user-login.htm` | `email` + `password`(MD5) |
| 签到 | POST | `/sg_sign.htm` | 携带登录 Cookie，AJAX POST |

## 依赖

- 青龙：只需 `requests`
- 本地 yaml：`requests` + `PyYAML`
