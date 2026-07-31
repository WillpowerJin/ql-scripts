# 芳华未来挂机

对应 App：**芳华未来**（包名 `com.mytek.rtlive`）  
API：`https://api.cdwjyyh.com`

支持 **手机号 + 密码登录**，自动获取 `AppToken` 后：签到、刷视频、领积分、心跳。

> 仅供学习自用。勿将密码 / Token 提交到 Git。

## 功能

| 功能 | 说明 |
|------|------|
| 密码登录 | `POST /app/app/login`，`loginType=1` |
| Token 缓存 | 登录后写入缓存，下次复用（青龙：`/ql/data/fanghua_token_cache.json`） |
| 多账号设备隔离 | 每号独立稳定的 `device_id` / `jpush_id` |
| 每日签到 | `/app/integral/sign` |
| 刷视频领币 | 列表 → PLAY / PLAY_3S / COMPLETE + `addIntegral` |
| 心跳 | `/app/portrait/heartbeat` |
| Bark | 跑完推送摘要 |

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

若订阅后多出「crypto_api」定时任务：在定时任务里 **禁用** 即可，**不要删脚本文件**。

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

推荐 JSON：

```text
FANGHUA_ACCOUNTS=[{"name":"主号","phone":"13800138000","password":"你的密码"}]
```

多账号：

```text
FANGHUA_ACCOUNTS=[{"name":"主号","phone":"138...","password":"..."},{"name":"号2","phone":"139...","password":"..."}]
```

或对齐写法：

```text
FANGHUA_PHONE=138...&139...
FANGHUA_PASSWORD=pass1&pass2
FANGHUA_NAME=主号&号2
```

也可用 Token：`FANGHUA_TOKEN=...`（或写在 JSON 的 `token` 字段）。

可选：

```text
FANGHUA_MAX_RUN_HOURS=2
FANGHUA_TOKEN_CACHE=/ql/data/fanghua_token_cache.json
```

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
