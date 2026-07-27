# 望潮 · 阅读有礼

纯 Python 脚本，通过 HTTP 完成台州「望潮」App 的 **阅读有礼** 日常：

- 手机号 + 密码登录（自动换取 session，无需抓包）
- 拉取当日任务，自动完成 **12 篇** 阅读上报
- 满额后调用抽奖接口（`activityId=67`）

风格与本仓库 [hifiti](../hifiti/) 一致：**只调接口，不操控手机 UI**。

## 功能流程

1. `POST /api/account/init` 匿名 session（SHA256 签名）
2. `passport.tmuyun.com` RSA 加密密码 → `credential_auth`
3. `POST /api/zbtxz/login` 换正式 `account_id` / `session_id`
4. 登录阅读有礼 H5 → 任务列表 → SM2 上报已读
5. `loginWC` + `saveUpdate` 抽奖（旧接口 `/save` 已废弃）

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
```

### config.yaml 示例

```yaml
accounts:
  - name: "主号"
    phone: "13800138000"
    password: "your_password"
```

`config.yaml` 已在仓库 `.gitignore` 中，勿提交。

## 青龙面板

**依赖管理** 添加：`requests`、`gmssl`、`pycryptodomex`（本地 yaml 可选 `PyYAML`）

**环境变量（推荐）：**

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

可选：

```text
WANGCHAO_LOTTERY=0    # 关闭抽奖
```

**定时示例：** `30 8 * * *`  
**任务命令：** `task wangchao/read_gift.py`（按青龙实际路径调整）

## 备用：抓包 session

密码登录异常时，可改用抓包字段：

```yaml
accounts:
  - name: "主号"
    account_id: "..."
    session_id: "..."
    device_id: "1"
```

过滤：`xmt.taizhou.com.cn/prod-api/user-read/app/login`。

## 常见问题

| 现象 | 处理 |
|------|------|
| 账号不存在 / 密码错误 | 使用望潮注册的手机号与密码 |
| needYz=true | 先在 App 内完成人机验证 |
| 已读失败 | 重跑即可（会重新密码登录） |
| 当天已抽过奖 | 正常，明日再跑 |
| 请重新打开 APP 参与抽奖 | 旧接口文案；请使用最新 `read_gift.py`（`saveUpdate`） |
| 抽奖没有次数 | 当日未满 12 篇 |

## 依赖

见 [requirements.txt](./requirements.txt)：

- `requests`
- `gmssl`（阅读上报 SM2）
- `pycryptodomex`（密码 RSA）
- `PyYAML`（本地 config.yaml，可选）

## 免责声明

仅供学习交流，请遵守 App 用户协议与当地法规；请勿高频刷接口。
