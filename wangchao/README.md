# 望潮 · 阅读有礼

纯 Python 脚本，通过 HTTP 完成台州「望潮」App 的 **阅读有礼** 日常：

- 手机号 + 密码登录（自动换取 session，无需抓包）
- 拉取当日任务，自动完成 **12 篇** 阅读上报
- **默认不自动抽奖**；满额后请在 App 内手动抽（见下方 **【重点】**）

风格与本仓库 [hifiti](../hifiti/) 一致：**只调接口，不操控手机 UI**。

---

## ★【重点】抽奖策略（默认）

> 抽奖站会按 **出口公网 IP / 设备会话** 做风控，常见文案包括  
> 「同一设备一天只能抽一次」「检测到账号异常，请今日到 APP 重新登录…」。  
> **多号同脚本同出口时，没有长期稳固的自动抽奖方案。**

| 账号 | 自动阅读 12 篇 | 自动抽奖 | 抽奖怎么办 |
|------|----------------|----------|------------|
| **全部账号（默认）** | ✅ | ❌ | **请手动**：手机流量 + 望潮 App |
| 任意号 `lottery: false` / 未写 | ✅ | ❌ | 手动 / 不抽 |
| 任意号 `lottery: true` **且** 全局 `lottery.enable: true` | ✅ | ✅ | 脚本自动（仍有风控风险；建议独立 proxy + `app_unique_id`） |

启动日志会打印醒目的 `★【重点】抽奖策略` 区块，标明本轮谁抽奖、谁只阅读。

---

## 功能流程

1. `POST /api/account/init` 匿名 session（SHA256 签名）
2. `passport.tmuyun.com` RSA 加密密码 → `credential_auth`
3. `POST /api/zbtxz/login` 换正式 `account_id` / `session_id`
4. **缓存 session 到本地**（默认 7 天），下次直接复用，避免每天重新登录换票
5. 登录阅读有礼 H5 → 任务列表 → SM2 上报已读
6. **默认跳过抽奖**；仅当全局开关 + 账号 `lottery: true` 时执行 `loginWC` + `saveUpdate`

> 若你仍要脚本抽奖：抽奖接口会尽量模拟 App（含 `xsb_wangchao` 的 UA + 包名 `X-Requested-With` + vapp 签名头，去掉外部 H5 的 `Referer/Origin`）；并优先使用 App 内抓包的 `app_unique_id` 作为 `loginWC` 的 `sessionId`。这只能降概率，**不能保证不触发账号异常**。

## 本地运行

```bash
cd wangchao
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml
# 编辑 phone / password

python read_gift.py --dry-run      # 登录 + 列任务
python read_gift.py                # 仅阅读（默认不抽奖）
python read_gift.py --no-lottery   # 显式只阅读（与默认相同）
python read_gift.py --lottery-only # 只抽奖（需全局开启 + 账号 lottery: true）
python read_gift.py --only 主号    # 只跑配置里 name=主号 的账号
python read_gift.py --only iPhone --no-lottery
```

### config.yaml 示例

```yaml
accounts:
  # 默认：阅读；抽奖请 App 手动
  - name: "主号"
    phone: "13800138000"
    password: "your_password"
  - name: "号2"
    phone: "13900139000"
    password: "your_password2"
  - name: "号3"
    phone: "13700137000"
    password: "your_password3"

lottery:
  enable: false   # 默认关闭自动抽奖
```

`config.yaml` 已在仓库 `.gitignore` 中，勿提交。

> **多账号注意（很重要）：**
>
> | 环节 | 怎么识别「设备」 | 多号怎么办 |
> |------|------------------|------------|
> | 阅读有礼 | 请求里的 `deviceId` + UA | 脚本已按账号自动生成，互不相同 |
> | **抽奖** | **出口 IP + 会话/行为** | **默认全不自动抽**；请 App 手动。若硬开脚本抽奖，每号需独立出口与 `app_unique_id`，仍不保证稳定 |

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

跑完会推送摘要：各账号阅读进度、抽奖结果（若开启）、错误信息。  
未配置 `BARK_*` 时只打日志、不推送。

其它可选：

```text
WANGCHAO_LOTTERY=1           # 打开全局抽奖开关（默认关；仍需账号 lottery: true）
WANGCHAO_NOTIFY_DRY_RUN=1    # dry-run 时也推送（默认 dry-run 不推）
WANGCHAO_ACCOUNT_INTERVAL=20 # 多账号间隔秒数（默认 20，防限流）
WANGCHAO_INIT_RETRIES=5      # init 限流重试次数
WANGCHAO_START_JITTER=300    # 启动随机抖动秒数（默认 300，错开多账号请求）
WANGCHAO_PROXY=http://u:p@ip1:port&socks5://127.0.0.1:1080  # 与账号一一对应（可选）
WANGCHAO_APP_UNIQUE_ID=xxx&yyy   # 仅脚本抽奖时建议；App 内抓包的设备唯一 sessionId
```

多账号 yaml：**默认不用写 `lottery`**——全部只阅读。

若某号有独立代理、仍要脚本抽奖（不推荐，仅兼容）：

```yaml
lottery:
  enable: true                              # 先开全局

accounts:
  - name: "号2"
    phone: "1yyyyyyyyyy"
    password: "yyy"
    proxy: "http://user:pass@代理IP:端口"   # 与其它号不同出口
    lottery: true                           # 显式打开
    app_unique_id: "从 App 抓包 loginWC 的 sessionId"
```

SOCKS 代理需：`pip install "requests[socks]"`（或 `PySocks`）。

### 4. 定时任务

| 项 | 建议 |
|----|------|
| 定时 | `30 8 * * *`（每天 8:30） |
| 命令 | `task …/wangchao/read_gift.py`（以脚本管理中实际路径为准） |

## 备用：抓包 session / 设备唯一 ID

密码登录异常时，可改用抓包字段：

```yaml
accounts:
  - name: "主号"
    account_id: "..."
    session_id: "..."
    device_id: "从抓包 login 的 deviceId 参数复制"  # 多号务必不同
```

过滤：`xmt.taizhou.com.cn/prod-api/user-read/app/login`。

如果**坚持**脚本抽奖且仍提示「账号异常」，建议补充抓取 App 内的**设备唯一 sessionId**（`loginWC` 的 `sessionId` 参数，不是 vapp session）：

```yaml
accounts:
  - name: "主号"
    phone: "1xxxxxxxxxx"
    password: "xxx"
    lottery: true
    app_unique_id: "从抓包 /tzrb/user/loginWC 的 sessionId 复制"
```

过滤：`srv-app.taizhou.com.cn/tzrb/user/loginWC`。

## 常见问题

| 现象 | 处理 |
|------|------|
| 订阅后没有 `read_gift.py` | 白名单改为 `checkin\|read_gift` 并保存后再运行订阅 |
| 账号不存在 / 密码错误 | 使用望潮注册的手机号与密码 |
| needYz=true | 先在 App 内完成人机验证 |
| 已读失败 | 重跑即可（会重新密码登录） |
| 当天已抽过奖 | 正常，明日再跑（仅手动/显式开启时） |
| 请重新打开 APP 参与抽奖 | 旧接口文案；请使用最新 `read_gift.py`（`saveUpdate`） |
| 抽奖没有次数 | 当日未满 12 篇 |
| 跑完没有 Bark | 配置 `BARK_URL` 或 `BARK_KEY`（可与 hifiti 相同） |
| 第二账号 init「操作过于频繁」 | 同 IP 连登限流；已自动间隔+重试，可加大 `WANGCHAO_ACCOUNT_INTERVAL` |
| 脚本抽奖「同一设备只能参加一次」 | **不是**阅读 `deviceId` 的问题。抽奖站按**出口 IP** 限制。**默认已关闭自动抽奖**；请用手机流量在 App 内手动抽 |
| 阅读有礼「同一设备」 | 脚本已为每号生成独立 `deviceId`/UA；与抽奖 IP 限制是两套逻辑 |
| 抽奖「检测到账号异常，请今日到APP重新登录，明日可参与抽奖」 | **推荐：脚本只阅读，App 手动抽。** 若曾用脚本抽中招：先在 App 内重新登录并手动抽一次清标记；勿再同 IP 多号自动抽 |
| 每天早上固定时间跑后异常 | 启用 `WANGCHAO_START_JITTER` 错开请求，并把 cron 分散到 8:00~9:30 |

## 依赖

见 [requirements.txt](./requirements.txt)：

- `requests`
- `gmssl`（阅读上报 SM2）
- `pycryptodomex`（密码 RSA）
- `PyYAML`（本地 config.yaml，可选）

## 免责声明

仅供学习交流，请遵守 App 用户协议与当地法规；请勿高频刷接口。
