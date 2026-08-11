# 快乐蜂抽奖脚本

将原 `快乐蜂.js`（`klekey = z-token#cookie`）改写为 Python，支持**手机号 + 密码**登录。

## 功能

1. RSA 加密密码 → `POST /auth/password/login` 获取 `token` + Cookie  
2. 免费抽奖：`POST /v1/turntables/free` × 3（默认间隔随机 5–8s）  
3. 剩余抽奖：`GET /v1/turntables/check` 取 `idHash`（必要时再 `/ad`）→ `POST /v1/turntables/{idHash}`  
4. Token 本地缓存，失效自动重登  
5. Bark 推送汇总（可选，与 hifiti / quark 等共用 `BARK_*`）

## 依赖

```bash
pip install -r requirements.txt
```

## 配置

### 方式 A：环境变量（青龙推荐）

```bash
# JSON 多账号
KLF_ACCOUNTS='[{"name":"主号","phone":"13800138000","password":"xxx"}]'

# 或 手机号#密码（多账号 & / 换行）
KLF=13800138000#your_password

# 或平行变量
KLF_PHONE=13800138000
KLF_PASSWORD=your_password
```

兼容原 JS：

```bash
klekey='z-token值#acw_tc=...'
```

### 方式 B：本地 yaml

```bash
cp config.example.yaml config.yaml
# 编辑 phone / password
python3 daily.py
```

### 可选参数

| 变量 | 说明 | 默认 |
|------|------|------|
| `KLF_FREE_TIMES` | 免费次数 | 3 |
| `KLF_AD_TIMES` | 广告抽奖上限；`0`=按 `/check` 自适应抽到用完 | 0 |
| `KLF_AD_INTERVAL_MIN` | 每轮抽奖随机间隔下限(秒) | 5 |
| `KLF_AD_INTERVAL_MAX` | 每轮抽奖随机间隔上限(秒) | 8 |
| `KLF_AD_INTERVAL` | 固定间隔(秒)；`>0` 时覆盖 min/max | 0 |
| `DRY_RUN=1` | 只登录不抽奖 | off |

### Bark 通知（可选，与其它项目共用）

| 变量 | 说明 |
|------|------|
| `BARK_URL` | App 完整推送地址，如 `https://api.day.app/你的Key/` |
| 或 `BARK_KEY` | 仅 Key |
| `BARK_SERVER` | 自建服务器，默认 `https://api.day.app` |
| `BARK_GROUP` | 分组，默认 `快乐蜂抽奖` |
| `BARK_SOUND` / `BARK_ICON` / `BARK_LEVEL` | 可选 |

未配置 `BARK_*` 时只打日志、不推送。也可在 `config.yaml` 的 `notify:` 段写 `bark_url` / `bark_key`。

## 运行

```bash
python3 daily.py              # 读环境变量或 config.yaml
python3 daily.py --dry-run    # 只测登录
python3 daily.py -v           # 详细日志
```

## 说明

- 密码使用 H5 同款 RSA 公钥加密后提交  
- 密码登录后的业务请求需：**`z-client: 2` + `Bearer` token + App 设备头**（`z-device` / `z-os` / `z-version` 等）  
- **抽奖以 `GET /v1/turntables/check` 为准**：返回 `idHash` 再开奖；`state=3` 可抽，`state=5` 今日已用完  
- **广告抽奖自适应**：`ad_times=0`（默认）时循环到 `/check` 提示用完为止；`>0` 仅作安全上限  
- **防检测间隔**：每轮抽奖默认随机等待 5–8 秒  
- 不要写死 `POST /ad` 的 `advertisementId`/`stepId`。参数不匹配会 `code=5000 系统异常!`，手机端走 `/check` 仍可抽  
- 仅当 `/check` 给出 `stepId` 时才调用 `/ad` 换 `idHash`  
- 免费抽奖 / 开奖 body 用原脚本固定密文  
- 常见业务码：`5621` 免费次数用完；`5612` 该次抽奖已使用；`5000` 多为参数/设备头错误  
- 仅供学习交流，账号风险自负  

### 其它可选环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `KLF_ADVERTISEMENT_ID` | 仅 /check 返回 stepId 时使用的广告位 id | 1 |
| `KLF_STEP_ID` | /check 无 stepId 时的回退值（一般用不到） | 110 |
