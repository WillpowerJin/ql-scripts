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

**推荐：**

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
    device_id: "1"
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

## 依赖

见 [requirements.txt](./requirements.txt)：

- `requests`
- `gmssl`（阅读上报 SM2）
- `pycryptodomex`（密码 RSA）
- `PyYAML`（本地 config.yaml，可选）

## 免责声明

仅供学习交流，请遵守 App 用户协议与当地法规；请勿高频刷接口。
