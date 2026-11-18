# 今平湖阅读红包

[← 返回脚本总览](../README.md)

原脚本 `今平湖支持外部ddddocr版.py` 重写为仓库统一风格：`daily.py`。

纯帐密登录，零抓包依赖：

```text
passport /web/init
 → /web/oauth/credential_auth（RSA 加密密码）→ authorization_code
 → vapp /api/account/init → /api/zbtxz/login → session.id / account.id
 → ya /api/aosbase/_auth_appuserinit（MD5 签名）→ access_token（约 115 天）
 → 每篇新闻上报约 3 分钟阅读时长 → task_done → 抽奖（ac_sub 提交手机号）
```

> 仅供学习。账号与资产风险自负。账号密码由脚本 RSA 加密后提交官方 passport，
> 登录态只缓存在本地/青龙状态目录，不入仓库。

## 上车前置（手动做一次）

1. 下载今平湖 App，**验证码登录**；登录后清除后台、重新打开 App：
   点「头像」→「账户信息」→「重置密码」。
2. 把重置后的 **手机号 + 密码** 填进 `config.yaml` 或青龙环境变量。
3. 首次提现前必须手动绑定微信：
   首页 → 右下角悬浮框 → 阅读任务 →「首次提现请绑定微信」。
   未绑定时 `ac_sub` 会被拒但**仍扣抽奖次数**，脚本会先检测，未绑定则直接跳过。

## 会做什么

1. 帐密登录（或复用本地缓存的 access_token，失效自动重登）
2. 自动发现**当天任务集**与**当前轮次主活动**（id 每天/每轮都会换，不写死）
3. 逐条创建任务 → 上报约 3 分钟阅读时长 → `task_done` 领抽奖次数
4. 过滑块（cv2 / ddddocr / 外部 ddddocr 服务）→ 检测微信绑定 → `ac_sub` 抽奖
5. 汇总日志 + 青龙统一通知 / Bark / PushPlus

## 本地（电脑）

```bash
cd jinpinghu
pip install -r requirements.txt
cp config.example.yaml config.yaml
# 编辑 phone / password
python3 daily.py --dry-run    # 只读核验
python3 daily.py --check      # 仅登录并输出账号信息
python3 daily.py              # 正常跑
```

指定配置：`python3 daily.py -c /path/to/config.yaml`

登录态缓存在 `jinpinghu/state/`（已 gitignore，不要提交）。

## 青龙

### 订阅

白名单加上 **`jinpinghu`**：

```text
hifiti|xijiu|quark|bilibili|fanghua|fun|tuiguangbao|aliyun_dev|kuailefeng|dianxin|jd|jinpinghu
```

### 依赖

```text
requests
cryptography
opencv-python-headless
numpy
```

只用外部 OCR 服务（`JPH_OCR=remote`）时，青龙里可不装 cv2 / numpy；
用 `JPH_OCR=ddddocr` 则装 `ddddocr`。青龙只用环境变量时不必装 PyYAML。

### 环境变量

**账号（必填）**

| 名称 | 值 |
|------|----|
| `JPH` | `手机号#密码`，多账号用 `&` 或换行 |
| 或 `JPH_ACCOUNTS` | 兼容旧格式 `手机号@密码&手机号@密码`（密码可含 `@`） |
| 或 `JPH_ACCOUNTS` | JSON 数组，可带备注：`[{"name":"主号","phone":"159...","password":"..."}]` |

**可选：**

| 变量 | 说明 | 默认 |
|------|------|------|
| `JPH_THREADS` | 并发线程数；`0`=全并发，`1`=串行 | 3 |
| `JPH_DO_LOTTERY` | `1`=自动抽奖并提交手机号；`0`=只刷次数、绝不发 `ac_sub` | 1 |
| `JPH_FORCE_LOTTERY` | `1`=忽略微信绑定检测强制抽奖（会白扣次数） | 0 |
| `JPH_LOTTERY_PHONE` | 抽奖弹窗手机号；**仅单账号生效** | 登录号 |
| `JPH_LOTTERY_PHONE_MAP` | 按账号指定：`登录号=抽奖号,登录号=抽奖号` | 空 |
| `JPH_OCR` | `cv2` / `ddddocr` / `remote` | cv2 |
| `JPH_OCR_URL` | 外部 ddddocr 服务地址 | `http://127.0.0.1:7777` |
| `JPH_SLIDE_RETRY` | 滑块最大尝试轮数 | 6 |
| `JPH_READ_MS` | 强制阅读时长(毫秒)，`0`=每篇约 3 分钟 | 0 |
| `JPH_USE_AUDIO_DURATION` | `1`=按该篇 `audio_duration` 计算 | 0 |
| `JPH_REAL_WAIT` | 真实等待秒数上限 | 0 |
| `JPH_AC_DETAIL` | `0`=跳过活动详情请求 | 1 |
| `JPH_ACTIVITY_ID` | 强制当天任务集 id | 自动发现 |
| `JPH_MAIN_ACTIVITY_ID` | 强制主活动 id | 自动发现 |
| `JPH_CLIENT_ID` | passport client_id | `10040` |
| `JPH_TIMEOUT` | 请求超时秒 | 25 |
| `JPH_STATE_DIR` | 登录态缓存目录 | 青龙 `/ql/data/jinpinghu` |
| `JPH_DEBUG` / `--debug` | 打印详细响应 | 关 |
| `DRY_RUN=1` / `--dry-run` | 只读核验 | 关 |

**通知（与其它项目共用）：**

```text
BARK_URL=完整推送地址
# 或 BARK_KEY=设备Key
# 可选 BARK_SERVER / BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL
PUSHPLUS_TOKEN=...
```

未配置时只打日志、不推送。也可写在 `config.yaml` 的 `bark:` / `pushplus:` 段。

### 定时

| 名称 | 命令 | cron |
|------|------|------|
| 今平湖阅读红包 | `python3 -u .../jinpinghu/daily.py` | `5 9 * * *` |

**任务每天 09:00 刷新**（实测 `_optionp_list` 当天任务集有效期为
`09:00 ~ 23:59`，标题按日期变化，如「11月18日 新闻任务」），每天一轮。
建议 09:00 后几分钟运行；红包按整点限量发放，越晚抽越可能只剩积分。
脚本在 09:00 前运行会检测到任务集未生效，只读模式可看任务、正式模式跳过写操作。

## 滑块识别

三种方案，失败会自动回退 cv2：

| 方案 | 配置 | 依赖 |
|------|------|------|
| cv2 边缘模板匹配（默认） | `JPH_OCR=cv2` | `opencv-python-headless` + `numpy` |
| 本地 ddddocr | `JPH_OCR=ddddocr` | `ddddocr`（青龙常见） |
| 外部 ddddocr 服务 | `JPH_OCR=remote` + `JPH_OCR_URL` | 客户端不需要 cv2 |

外部服务接口（本脚本沿用原「支持外部 ddddocr 版」的协议）：

```text
POST {JPH_OCR_URL}/capcode
Content-Type: application/json
{"backImage": "<背景图 base64>", "slidingImage": "<滑块图 base64>"}

-> {"result": <缺口 x，原图坐标>}
```

## 抽奖说明

抽奖前先跑 `_ac_detail` 拿验证配置与手机号表单字段，再过滑块拿 `afs_tokenid`，
发 `lotteryTake` 埋点，最后 `ac_sub` 提交手机号。`1007` 只是通用业务码，`msg` 才是原因：

- `none times`：抽奖次数已耗尽
- `o a d w` / `o d d w`：**未中奖暗号**（前端 `checkPrizeIsEmpty` 明确判为未中奖），
  次数正常消耗、不生成中奖记录，属概率/奖品池结果，不是请求错误

多账号隔离：抽奖手机号在实例创建时按账号冻结，`ac_sub` 前硬校验手机号、登录态、
`device_token`、滑块凭证都属于本账号；任何一项不符立即中止。

## 文件

```text
jinpinghu/
  daily.py              # 任务入口（青龙定时跑这个）
  config.example.yaml   # 本地示例配置
  config.yaml           # 本地实际配置（gitignore，勿提交）
  requirements.txt
  README.md
  state/                # 本地登录态缓存（gitignore）
```

青龙状态缓存目录 `/ql/data/jinpinghu/`，订阅更新不会覆盖。
