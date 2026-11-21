# 1KF 会员中心 · 每日签到

[← 返回脚本总览](../README.md)

[1KF 会员中心](https://vip.1kf.com)（传奇开服第一站）：Cookie 登录 → 每日签到 → 可选积分抽奖 → 积分够线自动兑换余额（1 元 = 20 积分）。

逻辑参考 ql.xmox.cn 脚本库《1KF每日低保》，**端点与页面结构已按现网（2026-11）实测修正**。

> ⚠️ **站点规则：一人一号，多号必封**。虽然脚本支持多账号，请只配一个。

## 策略

1. **Cookie 登录**（微信扫码登录后，浏览器 F12 复制 `vip.1kf.com` 的完整 Cookie，至少含 `session_token`）
2. 打开 `/qiandao` 校验登录态（`VIP-username` 拿 uid），解析签到状态和 `csrf_token`
3. 未签到则 `POST /public/sign_ajax.php`（+10 积分 +1 成长值，连签 7 天额外 +100 积分）
4. 可选积分抽奖：`POST /choujiang` `action=draw`（每次 10 积分，**默认关闭**，积分留着兑现金更划算）
5. 兑换：`POST /exchange_logs` `exchange_submit=1&points=N`（默认开启，≥20 积分自动兑成余额）
6. 结果推送 **Bark** / Server酱 / Webhook，含**积分与余额变化**

## 仓库内文件

| 文件 | 是否进青龙 | 说明 |
|------|------------|------|
| `daily.py` | ✅ 拉取 | **主脚本（请用这个建任务）** |
| `README.md` | ❌ 不拉 | 本文档 |
| `config.example.yaml` | ❌ 不拉 | 本地配置示例 |
| `requirements.txt` | ❌ 不拉 | 本地依赖 |

青龙依赖管理 → Python3 → 添加：`requests`。

## 定时任务

脚本头：

```
0 8 * * *
```

| 项 | 建议 |
|----|------|
| 命令 | `task …/1kf/daily.py`（以青龙实际路径为准） |
| 定时 | `0 8 * * *` 或自定 |
| 超时 | ≥ 5 分钟 |

## 环境变量（账号）

### 方式 A（推荐）：`KF_ACCOUNTS` JSON

```json
[
  {
    "name": "主号",
    "cookie": "session_token=xxx; PHPSESSID=xxx; 其它字段原样粘贴"
  }
]
```

### 方式 B：兼容旧脚本 `KF_COOKIE`

```text
KF_COOKIE=session_token=xxx; PHPSESSID=xxx
```

多账号用 `&` 或换行分隔（**不建议**，多号必封）。

Cookie 获取：微信扫码登录 <https://vip.1kf.com> 后，F12 → Network → 任意请求 → 复制 `Cookie` 报头整串。失效后脚本会报「Cookie 已失效或未登录」，重新复制即可。

## 可选其它变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `KF_LOTTERY` | `1`=开启积分抽奖（每次 10 积分） | `0` |
| `KF_LOTTERY_TIMES` | 每次最多抽几轮（上限 30） | `1` |
| `KF_EXCHANGE` | `1`=积分够线自动兑换余额 | `1` |
| `KF_EXCHANGE_MIN` | 兑换门槛（积分） | `20` |
| `KF_EXCHANGE_ALL` | `1`=全部兑光；`0`=只兑 20 的整数倍留零头 | `0` |
| `KF_TIMEOUT` | 请求超时秒 | `20` |
| `KF_INTER_ACCOUNT_DELAY` | 多账号间隔秒 | `5` |

## 环境变量（Bark，可选）

与仓库其它脚本共用：

| 变量 | 说明 |
|------|------|
| `BARK_URL` | 完整地址，如 `https://api.day.app/你的Key/` |
| 或 `BARK_KEY` | 仅 Key |
| `BARK_SERVER` | 默认 `https://api.day.app` |
| `BARK_GROUP` | 默认 `1KF签到` |
| `BARK_SOUND` / `BARK_ICON` / `BARK_LEVEL` | 可选 |
| `SERVERCHAN_KEY` / `WEBHOOK_URL` | Server酱 / 自定义 Webhook |

## 本地运行

```bash
cd 1kf
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填写后不要 git add
python daily.py
python daily.py --check              # 只校验 Cookie 登录态，不签到
```

## 通知示例

```text
✅ 主号（uid 14011）
   ✅ 签到成功：签到成功！获得 +10 积分 +1 成长值（连续1天）
   💰 积分：10（+10）
   💵 余额：¥0.00
   💱 积分 10 < 20，未达兑换线
```

## 接口备忘（现网实测 2026-11）

| 步骤 | 方法 | 说明 |
|------|------|------|
| 签到页 | GET `/qiandao` | `VIP-username` 取 uid；未签到有 `name="sign_submit"`「立即签到」按钮 |
| 签到 | POST `/public/sign_ajax.php` | `csrf_token`（页面 hidden input） |
| 抽奖 | POST `/choujiang` | `action=draw`；`code=0` 成功，返回 `prize.prize_type/prize_value` |
| 资产 | GET `/exchange_logs` | 统计卡片：当前积分 / 当前余额 / 当前活动点；比例 `1元=<strong>20</strong>积分` |
| 兑换 | POST `/exchange_logs` | `exchange_submit=1&points=N`，`success` 为 true 成功 |

## 依赖

- 青龙：只需 `requests`
- 本地 yaml：`requests` + `PyYAML`
