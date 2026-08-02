# 推广宝 · 每日看广告领奖

[← 返回脚本总览](../README.md)

Discuz 插件「推广宝」每日任务：登录 → 绑邀请码 → 模拟看广告 → 满额领奖。

逻辑对齐《推广宝每日 2.5 修复版》；工程完整度对齐本仓库 [hifiti](../hifiti/)。

> 账号 / 密码 / Bark 等敏感信息只写在**青龙环境变量**（或本地不提交的 `config.yaml`），不要提交到 Git。

## 策略

1. **密码登录** Discuz（Cookie 含 `*_auth` 即成功）
2. 可选：配置 / 缓存 Cookie 复用会话，失效自动重登
3. 查进度 `status` → 冷却 → `next_ad` → 模拟观看 → `complete_ad` → 满 5 条 `claim`
4. 配置优先读 **青龙 / 系统环境变量**（本地也可 `config.yaml`）
5. 结果可推送 **Bark** / Server酱 / Webhook

## 仓库内文件

| 文件 | 是否进青龙 | 说明 |
|------|------------|------|
| `daily.py` | ✅ 拉取 | 主脚本（推荐） |
| `main.py` | 可选 | 兼容入口，转发 `daily.py` |
| `README.md` | ❌ 不拉 | 本文档 |
| `config.example.yaml` | ❌ 不拉 | 本地配置示例 |
| `requirements.txt` | ❌ 不拉 | 本地依赖 |

青龙依赖管理添加：`requests`。

## 青龙订阅

仓库根 [README](../README.md) 有通用订阅。若只拉本脚本：

```bash
ql repo https://github.com/WillpowerJin/ql-scripts.git "daily" "README|config|example|requirements|\.md|\.yaml|\.yml|\.txt|\.js" "" "main" "py"
```

定时（脚本头已写）：

```
0 9 * * *
```

## 环境变量（账号）

### 方式 A（推荐）：`TGB_ACCOUNTS` JSON

```json
[
  {
    "name": "主号",
    "phone": "13800138000",
    "password": "your_password"
  }
]
```

可选字段：`cookie`（已有 Discuz 会话时免登）。

### 方式 B：兼容原 JS `TGB`

```text
TGB=手机号#密码&手机号2#密码2
```

也支持换行分隔。

### 方式 C：平行变量（`&` 分隔）

| 变量 | 说明 |
|------|------|
| `TGB_USER` / `TGB_PHONE` | 手机号 |
| `TGB_PASS` / `TGB_PASSWORD` | 密码 |
| `TGB_NAME` | 可选备注 |
| `TGB_COOKIE` | 可选会话 |

## 环境变量（Bark，可选）

| 变量 | 说明 |
|------|------|
| `BARK_URL` | 完整地址，如 `https://api.day.app/你的Key/` |
| 或 `BARK_KEY` | 仅 Key |
| `BARK_SERVER` | 默认 `https://api.day.app` |
| `BARK_GROUP` | 默认 `推广宝` |
| `BARK_SOUND` / `BARK_ICON` / `BARK_LEVEL` | 可选 |

## 可选其它变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `TGB_INVITE_CODE` | 邀请码 | `000GHFAV` |
| `TGB_TIMEOUT` | 请求超时秒 | `15` |
| `TGB_MAX_RETRIES` | 网络重试 | `3` |
| `TGB_RETRY_INTERVAL` | 重试间隔秒 | `10` |
| `TGB_AD_WATCH_SECONDS` | 单条广告模拟观看秒 | `22` |
| `TGB_INTER_ACCOUNT_DELAY` | 账号间隔秒 | `6` |
| `TGB_INTER_AD_DELAY_MIN` / `MAX` | 广告间隔随机秒 | `3` / `6` |
| `TGB_MAX_AD_LOOPS` | 单号最大循环 | `50` |
| `TGB_UA` | User-Agent | 内置安卓 UA |
| `TGB_SESSION_CACHE` | 会话缓存路径 | 脚本目录 / 青龙 `/ql/data` |
| `DRY_RUN=1` | 只登录+查进度 | 关 |
| `SERVERCHAN_KEY` | Server酱 | |
| `WEBHOOK_URL` | 自定义 Webhook | |

## 本地运行

```bash
cd tuiguangbao
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填写后不要 git add
python daily.py
python daily.py --login-only         # 只测登录
python daily.py --dry-run -v         # 查进度
```

## 业务流程 / 接口

| 步骤 | 方法 | URL | 说明 |
|------|------|-----|------|
| 登录页 | GET | `/member.php?mod=logging&action=login&mobile=2` | 取 formhash |
| 登录 | POST | `/member.php?...&loginsubmit=yes&mobile=2` | username+password，需 `*_auth` Cookie |
| formhash | GET | `/plugin.php?id=view&modac=sign` | 后续 POST 用 |
| 绑邀请码 | POST | `/plugin.php?id=xigua_hh:bindcode` | `yqcode` |
| 进度 | GET | `...&modac=sign&submodac=status` | viewed/target/can_claim |
| 下一条广告 | POST | `...&submodac=next_ad` | 返回 token |
| 上报完成 | POST | `...&submodac=complete_ad` | token |
| 领奖 | POST | `...&submodac=claim` | 满 target 后 |

单广告模拟观看默认 **22 秒**；满 **5** 条（以接口 `target_count` 为准）自动领奖。

## 日志含义

| 标记 | 含义 |
|------|------|
| `auth:password` | 密码登录 |
| `auth:cache` | 会话缓存复用 |
| `auth:cookie` | 配置 Cookie |
| `📊 进度 a/b` | 已看 / 目标 |
| `▶ Token` | 开始模拟观看 |
| `🎁 领奖` | claim 接口返回 |
| `今日已领取` | 当天已 claim 过 |

## 依赖

- 青龙：`requests`
- 本地 yaml：`requests` + `PyYAML`
