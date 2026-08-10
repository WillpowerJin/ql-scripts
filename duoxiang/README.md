# 多象 · 签到 / 领活跃收益 / 提现

[← 返回脚本总览](../README.md)

[多象](https://dx.qqdd.top) 每日任务：登录 → 签到 → 领取昨天/前天活跃收益 → 整元自动提现。

逻辑对齐《多象全自动.py》；工程完整度对齐本仓库 [hifiti](../hifiti/)。

> 账号 / 密码 / Bark 等敏感信息只写在**青龙环境变量**（或本地不提交的 `config.yaml`），不要提交到 Git。

## 策略

1. 手机号 + 密码登录（Android HMAC 签名）
2. 每日签到（`/api/growth/checkin`）
3. 邀请概览后领取昨天/前天活跃奖（`canClaim`）
4. 余额 **整元** 自动提现（最低 1 元；需绑定支付宝 + 实名；可关）
5. 配置优先读 **青龙环境变量**（本地也可 `config.yaml`）
6. 结果可推送 **Bark** / Server酱 / Webhook

## 仓库内文件

| 文件 | 是否进青龙 | 说明 |
|------|------------|------|
| `daily.py` | ✅ 拉取 | 主脚本 |
| `README.md` | ❌ 不拉 | 本文档 |
| `config.example.yaml` | ❌ 不拉 | 本地配置示例 |
| `requirements.txt` | ❌ 不拉 | 本地依赖 |
| `origin_fullauto.py` | ❌ 不拉 | 原脚本对照 |

青龙依赖管理 → Python3 → 添加：`requests`。

## 青龙订阅

根目录 [README](../README.md) 通用订阅。白名单加入 `duoxiang`：

```text
hifiti|wangchao|xijiu|quark|bilibili|fanghua|bafu|fun|tuiguangbao|duoxiang
```

黑名单保持：`pull_access_token`  
扩展名：`py`  
改完后：**保存 → 运行**订阅。

### 只拉本项目

```bash
ql repo https://github.com/WillpowerJin/ql-scripts.git "duoxiang" "pull_access_token" "" "main" "py"
```

## 定时任务

```
0 10 * * *
```

| 项 | 建议 |
|----|------|
| 脚本 | `duoxiang/daily.py` |
| 超时 | ≥ 5～10 分钟（多账号间隔默认 30～60s） |

## 环境变量（账号）

### 方式 A（推荐）：`DX_ACCOUNTS` JSON

```json
[
  {
    "name": "主号",
    "phone": "13800138000",
    "password": "your_password"
  }
]
```

可选：`token`（已有 Bearer 时免登）。

### 方式 B：兼容原脚本 `DX`

```text
DX=18812345678#123456@18812345678#123456
```

多账号用 `@`、`&` 或换行；单账号格式 `手机号#密码`。

### 方式 C：平行变量（`&` 分隔）

| 变量 | 说明 |
|------|------|
| `DX_USER` / `DX_PHONE` | 手机号 |
| `DX_PASS` / `DX_PASSWORD` | 密码 |
| `DX_NAME` | 可选备注 |
| `DX_TOKEN` | 可选 token |

## 环境变量（Bark，可选）

| 变量 | 说明 |
|------|------|
| `BARK_URL` | 完整地址 |
| 或 `BARK_KEY` | 仅 Key |
| `BARK_SERVER` | 默认 `https://api.day.app` |
| `BARK_GROUP` | 默认 `多象` |

## 可选其它变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `DX_WITHDRAW` | `0` 关闭自动提现 | 开 |
| `DX_TIMEOUT` | 请求超时秒 | `15` |
| `DX_MAX_RETRIES` | 网络重试 | `3` |
| `DX_RETRY_INTERVAL` | 重试间隔秒 | `10` |
| `DX_INTER_ACCOUNT_DELAY_MIN` / `MAX` | 账号间隔秒 | `30` / `60` |
| `DX_DEVICE_ID` | 设备 ID | 内置 |
| `DX_TOKEN_CACHE` | token 缓存路径 | `/ql/data/duoxiang_token_cache.json` 或脚本目录 |
| `DRY_RUN=1` | 只登录查资料 | 关 |
| `SERVERCHAN_KEY` / `WEBHOOK_URL` | 其它通知 | |

## 本地运行

```bash
cd duoxiang
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填写后不要 git add
python daily.py
python daily.py --login-only
python daily.py --dry-run -v
python daily.py --no-withdraw        # 本次不提现
```

## 业务流程 / 接口

| 步骤 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 登录 | POST | `/api/user/login` | phone + password → token |
| 签到 | POST | `/api/growth/checkin` | Bearer |
| 邀请概览 | GET | `/api/invite/overview` | stats / canClaim |
| 领活跃奖 | POST | `/api/invite/active-reward/claim` | `offsetDays` 1=昨天 2=前天 |
| 资料 | GET | `/api/user/profile` | balance / 支付宝 / 实名 |
| 提现 | POST | `/api/balance/withdraw` | amount 单位：分，整元 |

请求需 HMAC：`X-Timestamp` / `X-Nonce` / `X-Sign`（与原脚本一致）。

注册邀请：<https://dx.qqdd.top/i/fWT7zC>

## 日志含义

| 标记 | 含义 |
|------|------|
| `auth:password` | 密码登录 |
| `auth:cache` | token 缓存 |
| `✍️ 签到` | 签到结果 |
| `🎁 领取昨天/前天` | 活跃收益 |
| `💸 提现` | 整元提现 / 跳过原因 |

## 依赖

- 青龙：`requests`
- 本地 yaml：`requests` + `PyYAML`
