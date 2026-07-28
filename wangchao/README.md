# 望潮 · 阅读有礼

纯 Python 脚本，通过 HTTP 完成台州「望潮」App 的 **阅读有礼** 日常：

- 手机号 + 密码登录（自动换取 session，无需抓包）
- 拉取当日任务，自动完成 **12 篇** 阅读上报
- 满额后：按策略自动抽奖（见下方 **【重点】**）

风格与本仓库 [hifiti](../hifiti/) 一致：**只调接口，不操控手机 UI**。

---

## ★【重点】多账号抽奖策略（默认）

> 抽奖站按 **出口公网 IP** 限制「同一设备一天只能抽一次」，与阅读 `deviceId` 无关。  
> 同一台电脑 / 同一宽带跑多号时，**不能**指望每个号都自动抽奖成功。

| 账号顺序（config 列表） | 自动阅读 12 篇 | 自动抽奖 | 抽奖怎么办 |
|-------------------------|----------------|----------|------------|
| **第 1 个** | ✅ | ✅ 默认开启 | 脚本自动 |
| **第 2、第 3… 个** | ✅ | ❌ **默认关闭** | **请手动**：手机流量 + 望潮 App |
| 任意号 `lottery: false` | ✅ | ❌ | 手动 / 不抽 |
| 任意号 `lottery: true`（如有独立 proxy） | ✅ | ✅ | 脚本自动（需不同出口 IP） |

启动日志会打印醒目的 `★【重点】抽奖策略` 区块，标明本轮谁抽奖、谁只阅读。

---

## 功能流程

1. `POST /api/account/init` 匿名 session（SHA256 签名）
2. `passport.tmuyun.com` RSA 加密密码 → `credential_auth`
3. `POST /api/zbtxz/login` 换正式 `account_id` / `session_id`
4. 登录阅读有礼 H5 → 任务列表 → SM2 上报已读
5. **仅允许抽奖的账号**执行 `loginWC` + `saveUpdate`（默认只有第 1 个号）

## 本地运行

```bash
cd wangchao
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml
# 编辑 phone / password

python read_gift.py --dry-run      # 登录 + 列任务
python read_gift.py                # 阅读 + 抽奖
python read_gift.py --no-lottery   # 只阅读
python read_gift.py --lottery-only # 只抽奖
python read_gift.py --only 主号    # 只跑配置里 name=主号 的账号
python read_gift.py --only iPhone --no-lottery
```

### config.yaml 示例

```yaml
accounts:
  # 第 1 个：阅读 + 自动抽奖
  - name: "主号"
    phone: "13800138000"
    password: "your_password"
  # 第 2 个起：默认只阅读，抽奖请 App 手动
  - name: "号2"
    phone: "13900139000"
    password: "your_password2"
  - name: "号3"
    phone: "13700137000"
    password: "your_password3"
```

`config.yaml` 已在仓库 `.gitignore` 中，勿提交。

> **多账号注意（很重要）：**
>
> | 环节 | 怎么识别「设备」 | 多号怎么办 |
> |------|------------------|------------|
> | 阅读有礼 | 请求里的 `deviceId` + UA | 脚本已按账号自动生成，互不相同 |
> | **抽奖** | **主要看出网 IP** | **默认仅第 1 号自动抽**；副号手动（App + 流量）或配独立 `proxy` 后写 `lottery: true` |

## 青龙面板

### 1. 订阅拉取（必做：白名单含 `read_gift`）

本脚本文件名为 `read_gift.py`。若订阅白名单只有 `checkin`，**永远拉不到本脚本**。

在仓库订阅里把白名单设为：

```text
checkin|read_gift
```

完整订阅说明见 [根目录 README](../README.md#青龙订阅)。

- **新建订阅**：白名单直接填 `checkin|read_gift`
- **已有订阅**：必须 **编辑 → 改白名单 → 保存 → 再运行**；只点「运行」不会更新参数

成功后脚本路径类似：`…/wangchao/read_gift.py`。

### 2. 依赖

依赖管理添加：`requests`、`gmssl`、`pycryptodomex`（本地 yaml 可选 `PyYAML`）

### 3. 环境变量

**账号（推荐）：**

```text
WANGCHAO_ACCOUNTS=[{"name":"主号","phone":"1xxxxxxxxxx","password":"xxx"}]
```

或：

```text
WANGCHAO_PHONE=1xxxxxxxxxx
WANGCHAO_PASSWORD=xxx
WANGCHAO_NAME=主号
```

多账号用 `&` 分隔对齐字段。

**Bark 通知（与 hifiti 共用，可选）：**

```text
BARK_URL=https://api.day.app/你的Key/
```

或：

```text
BARK_KEY=你的Key
BARK_SERVER=https://api.day.app
BARK_GROUP=望潮阅读有礼
```

跑完会推送摘要：各账号阅读进度、抽奖结果、错误信息。  
未配置 `BARK_*` 时只打日志、不推送。

其它可选：

```text
WANGCHAO_LOTTERY=0           # 关闭抽奖
WANGCHAO_NOTIFY_DRY_RUN=1    # dry-run 时也推送（默认 dry-run 不推）
WANGCHAO_ACCOUNT_INTERVAL=20 # 多账号间隔秒数（默认 20，防限流）
WANGCHAO_INIT_RETRIES=5      # init 限流重试次数
WANGCHAO_PROXY=http://u:p@ip1:port&socks5://127.0.0.1:1080  # 与账号一一对应（可选）
```

多账号 yaml：**默认不用写 `lottery`**——第 1 号自动抽，其余只阅读。

若副号有独立代理、要脚本抽奖：

```yaml
  - name: "号2"
    phone: "1yyyyyyyyyy"
    password: "yyy"
    proxy: "http://user:pass@代理IP:端口"   # 与主号不同出口
    lottery: true                           # 显式打开（覆盖「非首号不抽」）
```

SOCKS 代理需：`pip install "requests[socks]"`（或 `PySocks`）。

### 4. 定时任务

| 项 | 建议 |
|----|------|
| 定时 | `30 8 * * *`（每天 8:30） |
| 命令 | `task …/wangchao/read_gift.py`（以脚本管理中实际路径为准） |

## 备用：抓包 session

密码登录异常时，可改用抓包字段：

```yaml
accounts:
  - name: "主号"
    account_id: "..."
    session_id: "..."
    device_id: "从抓包 login 的 deviceId 参数复制"  # 多号务必不同
```

过滤：`xmt.taizhou.com.cn/prod-api/user-read/app/login`。

## 常见问题

| 现象 | 处理 |
|------|------|
| 订阅后没有 `read_gift.py` | 白名单改为 `checkin\|read_gift` 并保存后再运行订阅 |
| 账号不存在 / 密码错误 | 使用望潮注册的手机号与密码 |
| needYz=true | 先在 App 内完成人机验证 |
| 已读失败 | 重跑即可（会重新密码登录） |
| 当天已抽过奖 | 正常，明日再跑 |
| 请重新打开 APP 参与抽奖 | 旧接口文案；请使用最新 `read_gift.py`（`saveUpdate`） |
| 抽奖没有次数 | 当日未满 12 篇 |
| 跑完没有 Bark | 配置 `BARK_URL` 或 `BARK_KEY`（可与 hifiti 相同） |
| 第二账号 init「操作过于频繁」 | 同 IP 连登限流；已自动间隔+重试，可加大 `WANGCHAO_ACCOUNT_INTERVAL` |
| 第二账号抽奖「同一设备只能参加一次」 | **不是**阅读 `deviceId` 的问题。抽奖站按**出口 IP** 限制。脚本**默认已不对第 2/3… 号自动抽奖**；副号请用手机流量在 App 内手动抽，或配独立 `proxy` 后写 `lottery: true` |
| 阅读有礼「同一设备」 | 脚本已为每号生成独立 `deviceId`/UA；与抽奖 IP 限制是两套逻辑 |

## 依赖

见 [requirements.txt](./requirements.txt)：

- `requests`
- `gmssl`（阅读上报 SM2）
- `pycryptodomex`（密码 RSA）
- `PyYAML`（本地 config.yaml，可选）

## 免责声明

仅供学习交流，请遵守 App 用户协议与当地法规；请勿高频刷接口。
