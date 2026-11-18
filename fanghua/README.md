# 芳华未来挂机

对应 App：**芳华未来**（包名 `com.mytek.rtlive`）  
API：`https://api.cdwjyyh.com`

登录方式：**Token 复用 / 短信验证码登录**。服务端已关闭「手机号 + 密码登录」（返回 `暂不支持密码登录111`），密码字段仅为兼容保留。拿到 `AppToken` 后：签到、刷视频、领积分、心跳。

> 仅供学习自用。勿将密码 / Token 提交到 Git。

## 功能

| 功能 | 说明 |
|------|------|
| Token 登录 | 直接复用 `token` / 缓存，不重复登录，避免顶掉 App 端会话 |
| 短信登录 | `POST /app/app/sendCode` → `POST /app/app/loginByPhone`（`loginType=2`） |
| 密码登录 | `POST /app/app/login`（`loginType=1`）——**服务端目前已关闭** |
| Token 缓存 | 登录后写入缓存，下次复用（青龙：`/ql/data/fanghua_token_cache.json`） |
| 多账号设备隔离 | 每号独立稳定的 `device_id` / `jpush_id` |
| 每日签到 | `/app/integral/sign` |
| 刷视频领币 | 列表 → PLAY / PLAY_3S / COMPLETE + `addIntegral` |
| 心跳 | `/app/portrait/heartbeat` |
| Bark | 跑完推送摘要 |

## 首次登录（重要）

服务端已关闭密码登录（任何账号都返回 `暂不支持密码登录111`），首次需要拿一个有效期较长的 `AppToken`。

**方式 A：本机交互短信登录（推荐）**

```bash
python3 -u main.py --sms-login
```

脚本会向 `config.yaml` 里的手机号发送验证码，终端输入 6 位码即可；成功后日志显示「验证码登录成功」，Token 写入 `token_cache.json`。

**方式 B：分两步（适合脚本/远程）**

```bash
python3 -u main.py --send-code          # 只发验证码
python3 -u main.py --login-only --sms-code 123456   # 输入收到的码并登录
```

之后正常跑定时任务即可，脚本优先用缓存 Token，不会每次重登。  
若 Token 失效（`AppToken失效，请重新登录`），或你在 App 内重新登录把它顶掉，重跑一次 `--sms-login` 即可。

**青龙面板**里收不到短信：在本地登录成功后，把 `token_cache.json` 传到 `/ql/data/fanghua_token_cache.json`，或直接把 Token 填进环境变量 `FANGHUA_TOKEN` / `FANGHUA_ACCOUNTS` 的 `token` 字段。

## 青龙面板

### 订阅

仓库：`https://github.com/WillpowerJin/ql-scripts.git`  

白名单加上 **`fanghua`**（与其它脚本用 `|` 拼接），扩展名 `py`。

会拉到：

```text
…/fanghua/main.py          ← 定时任务只启用这个
…/fanghua/crypto_api.py    ← 库文件，main 运行时会 import，必须存在
```

**不要把 `crypto_api` 写进订阅黑名单。**  
青龙黑名单 = **不下载该文件**，不是「下载但不建任务」。  
黑了以后 `main.py` 会报 `No module named 'crypto_api'`。

若订阅后多出「crypto_api / 芳华crypto库」任务：在面板改为 **手动执行** 或禁用即可，**不要删脚本文件**。

整仓推荐黑名单（仅排除习酒本地脚本）：

```text
pull_access_token
```### 依赖

青龙「依赖管理」→ 类型选 **python3** → 名称填：

```text
requests
pycryptodome
```

注意：

| 正确 | 错误 |
|------|------|
| 模块名 **`pycryptodome`** | 填 `Crypto` / `crypto`（容易装错包） |
| 装完后 `import Crypto` 应成功 | 装了别的 `crypto` 仍报 `No module named 'Crypto'` |

装完可在青龙依赖里看是否显示 `pycryptodome`；或任务日志不再报 `Crypto` 缺失。

### 环境变量（账号）

**推荐 JSON（Token）**：

```text
FANGHUA_ACCOUNTS=[{"name":"主号","token":"AppToken..."}]
```

多账号：

```text
FANGHUA_ACCOUNTS=[{"name":"主号","token":"..."},{"name":"号2","token":"..."}]
```

短信验证码（一次性，几分钟内有效；多账号用 `&` 对齐）：

```text
FANGHUA_ACCOUNTS=[{"name":"主号","phone":"138...","sms_code":"123456"}]
# 或
FANGHUA_PHONE=138...&139...
FANGHUA_SMS_CODE=123456&654321
FANGHUA_NAME=主号&号2
```

也可用对齐 Token：`FANGHUA_TOKEN=tok1&tok2`。

> 密码登录已关闭：`FANGHUA_PASSWORD` / JSON 的 `password` 保留兼容，目前请勿依赖。

可选：

```text
# 单账号最长挂机小时（默认 2，可改成 1 / 0.5 / 3 等）
FANGHUA_MAX_RUN_HOURS=2

FANGHUA_TOKEN_CACHE=/ql/data/fanghua_token_cache.json
```

也可用命令行覆盖：`python3 -u main.py --max-hours 1`  
或本地 `config.yaml` 里：`max_run_hours: 2`

### 通知（与仓库其它脚本共用）

```text
BARK_KEY=你的Key
# 或
BARK_URL=https://api.day.app/你的Key/
```

### 定时任务

| 名称 | 命令 | 建议 cron | 备注 |
|------|------|-----------|------|
| 芳华未来挂机 | `task .../fanghua/main.py` 或 `python3 -u .../fanghua/main.py` | `0 8 * * *` | 单号默认最多约 2 小时，注意任务超时设置 |

调试只登录：

```bash
python3 -u main.py --login-only
```

首次或 Token 失效时：

```bash
python3 -u main.py --sms-login          # 交互式：发码 + 输入验证码
python3 -u main.py --send-code          # 只发码，配合 --sms-code 使用
```

限制时长（调试）：

```bash
python3 -u main.py --max-hours 0.1
```

### 缓存路径

| 环境 | Token 缓存 |
|------|------------|
| 青龙 | `/ql/data/fanghua_token_cache.json` |
| 本地 | `fanghua/token_cache.json` |
| 自定义 | `FANGHUA_TOKEN_CACHE` |

---

## 本地运行

```bash
cd fanghua
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填 phone/password，勿提交
python main.py --login-only
python main.py
```

## 目录（仓库内）

```text
fanghua/
  main.py
  crypto_api.py
  config.example.yaml
  requirements.txt
  README.md
```

## 注意

1. 遵守 App 协议与当地法律。  
2. 服务端若轮换 RSA 密钥，需重新从 App 导出（见本地 `reverse/`，不随仓库发布）。  
3. 挂机任务时间较长，青龙任务超时请设大一些（例如 3 小时以上）。
