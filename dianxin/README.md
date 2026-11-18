# 电信 AI 奇遇

基于社区脚本「电信AI奇遇」（原作者 Alexin）重写为仓库统一风格：
账密登录 → 电信统一认证换 Ticket → 爱音乐 SSO → 自动创作任务赚积分 →
满 1000 分兑换 10 元话费（或全抽奖），中奖 1 元话费自动领取，**Bark 美化通知**。

**同一份 `daily.py`：** 电脑本地用 `config.yaml`，青龙用环境变量。

> 仅供学习。账号与资产风险自负。脚本需要**电信营业厅 App 的登录密码**（走官方
> `appgologin.189.cn` 统一认证，密码经 RSA 加密后提交）。
> 默认沿用原脚本内置的活动邀请码（`DIANXIN_INVITE_CODE` 可覆盖）——官方会把
> 拉新归因给该邀请人，不影响你自己的任务收益。

活动截止：2027-01-12（脚本写死，最后一期攒不满 1000 会自动抽光防清零）。

---

## 本地（电脑）

```bash
cd dianxin
pip install -r requirements.txt
cp config.example.yaml config.yaml
# 编辑 mobile / password
python3 daily.py
```

新账号建议先只查询验证登录链路：

```bash
python3 daily.py --observe
```

指定配置文件：`python3 daily.py -c /path/to/config.yaml`

本地状态目录默认 `dianxin/state/`（电信凭证缓存 + 领奖记录，已 gitignore，不要提交）。

---

## 青龙

### 订阅

白名单加上 **`dianxin`**：

```text
hifiti|xijiu|quark|bilibili|fanghua|fun|tuiguangbao|aliyun_dev|kuailefeng|dianxin
```

### 依赖

```text
requests
pycryptodome
certifi
```

青龙只用环境变量时不必装 PyYAML。

### 环境变量

**账号 `DIANXIN`（必填）**

```text
手机号#密码
手机号#密码#AndroidID
手机号#密码#AndroidID#备注
手机号#密码##备注
```

多账号用 `&` 或换行。AndroidID 是 16 位十六进制（手机真实设备 ID），带上后模拟
小米设备登录，**全新环境可避开电信 3006 风控，强烈建议提供**；不带则每次随机
生成 iPhone 指纹，新 IP 首次登录更容易被风控。

兼容原脚本变量名：`chinaTelecomAccount` / `AI096_ACCOUNTS` / `CAILING_ACCOUNTS`。

**模式 `DIANXIN_MODE`：**

| 值 | 行为 |
|----|------|
| `auto`（默认） | 每期免费额度做满 340 分；满 1000 兑换 10 元话费；兑换后多余积分抽奖；最后一期攒不满自动抽光 |
| `draw` | 全抽奖，不兑换 |
| `save` | 只攒分，满 1000 兑换，不抽奖 |
| `observe` | 只查询不动手，建议首次先用它验证登录 |

**Bark（与其它项目共用）：**

```text
BARK_KEY=你的Key
# 或 BARK_URL=https://api.day.app/你的Key/
```

**可选：**

| 变量 | 说明 |
|------|------|
| `DIANXIN_MAKE_COUNT` | 单轮制作上限，默认 17（每期 340 分 / 每次 20 分） |
| `DIANXIN_MAKE_INTERVAL` | 制作最小间隔秒，默认 20（防 10007 频控） |
| `DIANXIN_MAX_DRAWS` | 单轮抽奖上限，默认 10 |
| `DIANXIN_PROXY_API` | 代理提取 API，一号一 IP；不配置直连 |
| `DIANXIN_INVITE_CODE` | 覆盖内置活动邀请码 |
| `DIANXIN_NOTE` | 全局备注，进 Bark 标题 |
| `DIANXIN_STATE_DIR` | 状态目录；青龙默认 `/ql/data/dianxin` |

### 定时

| 名称 | 命令 | cron |
|------|------|------|
| 电信AI奇遇 | `python3 -u .../dianxin/daily.py` | `0 */6 * * *` |

每 6 小时一轮：服务端免费制作额度按时间发放，多轮才能做满每期 340 分上限。
状态与电信登录凭证缓存在 `/ql/data/dianxin`（订阅更新不会覆盖）。

---

## 配置优先级

1. `python3 daily.py -c 某文件.yaml` → 只用该文件（Bark 等仍可被环境变量覆盖）
2. 已设置环境变量 `DIANXIN`（或兼容旧变量）→ 青龙模式，忽略旁边的 `config.yaml`
3. 否则读 `dianxin/config.yaml`

## Bark 示例

```text
📶 电信 AI 奇遇 · 任务汇总
📅 10-26 09:00
────────────────

📱 【138****0000】
   📌 期数：第12期
   💰 积分：120 → 340（累计 1200）
   🎬 制作：11 次
   🎰 抽奖：3 次
   🎁 话费：领取 1 笔

────────────────
📦 账号 1 · ✅1  ❌0
🎉 全部顺利
```

## 文件

```text
dianxin/
  daily.py
  config.example.yaml
  requirements.txt
  README.md
```

状态缓存（不进仓库）：青龙 `/ql/data/dianxin/`，本地 `dianxin/state/`  
账号配置（不进仓库）：本地 `dianxin/config.yaml`
