# 华住会自动签到脚本 (Python)

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-green.svg)](https://opensource.org/licenses/GPL-3.0)

基于全网主流华住会签到机制调研与重构的 Python 自动化脚本，支持华住会 App 及微信小程序每日自动签到、积分及连签天数查询。

---

## 🌟 功能特性

- **纯 HTTP 驱动**：无需模拟器、无 ADB、无需常驻 App，任何 Linux 服务器 / VPS / 本地环境 / 青龙面板均可运行。
- **双引擎容灾**：
  - **官方主线接口**：`appgw.huazhu.com/game/sign_in`（官方 App H5 签到通道，支持获取今年累计签到天数与会员总积分）。
  - **经典备用接口**：`hweb-mbf.huazhu.com/api/signIn`（当主接口波动或维护时自动平滑回退）。
- **智能凭据识别**：支持纯 token 字符串、Cookie 格式（`userToken=xxxx; ...`）、URL 链接或请求头形式，自动提取清洗。
- **智能防风控与重试**：
  - 遇到华住接口常见的 **HTTP 429（限流）** 或 5xx 异常时，自动读取 `Retry-After` 并进行线性递增退避重试。
  - 支持随机错峰延迟（`RANDOM_DELAY`），有效防止固定时间并发被限流。
- **支持滑动续期**：服务端若在响应中下发新 `userToken`，脚本将自动捕获并持久化更新。
- **多渠道推送**：原生支持 **青龙统一通知（notify.py）**、**Bark（iOS）**、**PushPlus（微信）**。

---

## 🔑 核心凭据获取（userToken）

华住会签到仅需一个 **`userToken`** 凭证（无需密码、无需设备绑定，有效期通常长达数周至数月）。

### 抓包获取流程（通用简便）
1. 手机安装抓包软件：
   - **iOS**：Stream、Reqable、Thor、HTTP Catcher。
   - **Android**：Reqable、HttpCanary（小黄鸟）、ProxyPin。
2. 开启抓包并信任证书。
3. 打开 **华住会 App**（或微信「华住会」小程序）→ 进入 **「会员」** 或 **「签到」** 页面。
4. 在抓包记录中过滤 `huazhu.com`（如 `appgw.huazhu.com` 或 `cdn.huazhu.com`）：
   - 查看任意请求的 **请求头 Cookie**，找到：
     ```text
     userToken=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
     ```
   - 或查看请求头中的 `User-Token: xxxxxxxx`。
5. 复制 `userToken=` 后的字符（或直接整段 Cookie 复制均可，脚本会自动提取提纯）。

---

## ⚙️ 配置说明

### 方式 A：本地配置文件（推荐本地 / VPS 运行）
复制示例配置：
```bash
cp huazhu/config.example.yaml huazhu/config.yaml
```
编辑 `config.yaml`：
```yaml
accounts:
  - name: "主号"
    token: "你的_userToken"

# 可选定时与重试
run_at: "08:30"
random_delay: 0
retry_times: 3
retry_delay: 30

# 通知配置（可选）
bark:
  key: "你的BarkKey"
```

### 方式 B：青龙面板环境变量（推荐青龙用户）
在青龙面板「环境变量」中添加：
| 变量名 | 说明 | 示例 |
|---|---|---|
| `HZ_TOKEN` | 必填，`userToken` 值（多账号用 `&` 或换行分隔） | `abc123xxx&def456xxx` |
| `HUAZHU_ACCOUNTS` | 可选，JSON 格式多账号配置 | `[{"name":"主号","token":"xxx"}]` |
| `RANDOM_DELAY` | 可选，青龙运行前随机错峰秒数上限（默认 0 不延迟） | `300` |
| `RETRY_TIMES` | 可选，遇 429/5xx 异常重试次数（默认 3） | `3` |
| `RETRY_DELAY` | 可选，重试基础间隔（秒，默认 30） | `30` |

> **通知注意**：青龙环境下无需单独配置 Bark/PushPlus，脚本会自动调用青龙系统的 `notify.py` 发送通知。

---

## 🚀 运行方法

### 1. 安装依赖
```bash
pip install -r huazhu/requirements.txt
```

### 2. 执行命令
```bash
# 1. 默认签到执行（青龙面板推荐用法，完全无需加任何参数）
task huazhu/daily.py
# 或本地直接运行：
python3 huazhu/daily.py

# 2. 仅查询当前积分与账号状态（不执行签到动作）
python3 huazhu/daily.py --check

# 3. 指定自定义配置文件路径
python3 huazhu/daily.py --config /path/to/custom_config.yaml

# 4. 常驻后台自带定时调度（适合无青龙的 VPS，每天在 run_at 指定时间自动签到）
python3 huazhu/daily.py --loop

# 5. 输出详细调试日志（排错用）
python3 huazhu/daily.py --debug
```

### 3. Linux 系统 Crontab 配置示例
每天上午 8:30 自动执行：
```cron
30 8 * * * cd /home/jin/scripts && /usr/bin/python3 huazhu/daily.py --once >> /tmp/huazhu_checkin.log 2>&1
```

---

## ❓ 常见问题 (FAQ)

### Q1：`userToken` 会过期吗？需要每天重新抓吗？
**答：不需要每天抓。**  
华住会 App 的 `userToken` 是持久登录 Session，通常有效期长达数周至数月。若遇到 Token 失效，脚本会自动推送「Token 已失效，请重新更新」告警，届时重新抓一次填入即可。

### Q2：提示 `HTTP 429` 是什么意思？
**答：华住会服务器端限流。**  
在早高峰时段或批量并发请求时，华住接口可能返回 429。脚本已内置自动延迟重试；若经常遇到，可在配置中将 `random_delay` 设为 `300`（5分钟内随机错峰）即可完美避开限流。

### Q3：为什么签到返回成功但没有增加很多积分？
**答：华住会官方签到规则。**  
华住会每日签到通常赠送 1~10 不等的积分或优惠券，连续签到周期节点会有额外盲盒或积分翻倍奖励，脚本每天会自动拉取最新的会员总积分并在日志和通知中展示。
