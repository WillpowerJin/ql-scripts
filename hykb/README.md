# 好游快爆 · 翻滚吧爆米花

[← 返回脚本总览](../README.md)

好游快爆（4399 快爆）活动协议脚本：爆米花农场 + 每日任务 + 爆爆口令 + 爆爆战令 + 爆友分 + 偷玉米。

> **奖励是「爆米花」虚拟积分，不是现金，不能提现。**
> 爆米花只能在[爆米花商店](https://shop.3839.com/)换游戏礼包/激活码、视频会员、云游戏时长、实物周边等，热门商品有库存限制。

## 策略

1. 用 `scookie` 登录活动（`GET 活动首页` 拿 pageToken → `ac=login`）
2. 阶段 A：打小游戏/开App/分类启动标记 → 分享 → 答题（答案本自动积累）→ 爆爆口令 → 爆友分 → 偷玉米 → 战令
3. 等 `HYKB_WAIT_SECONDS`（默认 345 秒，让小游戏 5 分钟任务走完）
4. 阶段 B：领取每日任务奖励 → 收割/播种/产爆米花 → 买种子 → 浇水
5. 汇总每个账号的爆米花变化、种子/玉米/成熟度、战令、爆友分、已领奖励、还差什么

**三条铁律**（沿用原脚本）：

1. 不花爆米花买爆友分（500 换 2 那条已剔除）
2. 不重复刷快玩（`HYKB_FARM_ROUNDS=0` 默认关）
3. 请求随机间隔（安全模式下 4~12 秒，任务组 15~40 秒）

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
10 8 * * *
```

| 项 | 建议 |
|----|------|
| 命令 | `task …/hykb/daily.py`（以青龙实际路径为准） |
| 定时 | `10 8 * * *` 或自定 |
| 超时 | **≥ 30 分钟**（默认等待 345s + 安全模式请求间隔） |

## 必须提供的参数

### `HYKB_COOKIE`（或 `HYKB_ACCOUNTS`）—— 唯一必填

这里要的是**活动请求里的 `scookie` 参数**，不是浏览器 Cookie 头：

```text
抓包步骤：
1. 手机装好游快爆，登录
2. 打开「翻滚吧爆米花」活动页
3. 用抓包工具（HttpCanary / Stream / Charles 等）抓
   https://huodong3.3839.com/n/hykb/cornfarm/ajax.php 的 POST 请求
4. 看 form data 里的 scookie 参数，复制它的值
```

青龙环境变量二选一：

**方式 A（推荐，JSON）**

```text
HYKB_ACCOUNTS=[{"name":"主号","cookie":"你的scookie值"}]
```

**方式 B（兼容旧脚本）**

```text
HYKB_COOKIE=你的scookie值
```

多账号用 `&` 或换行分隔（**不建议**，多号容易风控）。脚本也兼容带 `scookie=` 前缀的写法，会自动剥掉。

### 可选参数

| 变量 | 说明 | 默认 |
|------|------|------|
| `HYKB_SAFE` | `1`=安全模式（慢但稳）；`0`=快 | `1` |
| `HYKB_FARM_ROUNDS` | 快玩重复领取轮数 | `0` |
| `HYKB_WAIT_SECONDS` | 阶段 A→B 等待秒 | `345` |
| `HYKB_ANSWER_BANK` | 答题答案本路径 | 脚本目录 `hykb_answers.json` |
| `HYKB_SMID` | 数美设备指纹（一般不用改） | 内置默认值 |
| `HYKB_TIMEOUT` | 请求超时秒 | `20` |
| `HYKB_INTER_ACCOUNT_DELAY` | 多账号间隔秒 | `10` |

> 如果爆爆口令返回 `shumei_black`，说明数美指纹和 App 设备不一致：把抓包请求里的
> `sm_device_id` 值填到 `HYKB_SMID`（同一台手机抓一次即可）。

### 通知（可选）

与仓库其它脚本共用：

| 变量 | 说明 |
|------|------|
| `BARK_URL` | 完整地址，如 `https://api.day.app/你的Key/` |
| 或 `BARK_KEY` | 仅 Key |
| `BARK_SERVER` | 默认 `https://api.day.app` |
| `BARK_GROUP` | 默认 `好游快爆` |
| `BARK_SOUND` / `BARK_ICON` / `BARK_LEVEL` | 可选 |
| `SERVERCHAN_KEY` / `WEBHOOK_URL` | Server酱 / 自定义 Webhook |

## 本地运行

```bash
cd hykb
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填写后不要 git add
python daily.py --check              # 只校验 scookie，不做任务
python daily.py --dry-run            # 登录 + 发现任务，不做写操作
python daily.py                      # 正式跑（默认等 345 秒）
python daily.py --nowait             # 跳过等待（会少拿小游戏 5 分钟任务）
```

## 通知示例

```text
✅ 主号（快爆昵称）
   ✅ 完成 14 个奖励，还差 2 个
   🍿 爆米花：1230（+86）
   🌱 种子：4 · 玉米：0 · 成熟度：100%
   🏆 战令：Lv3 / 经验 5200
   👥 爆友分：180（今日 8/12） Lv2
   ✅ 领到：小游戏#… 成熟度+10 爆米花+3；…
   ⚠️ 还差：#… 下载试玩（要真下载过）；…
```

## 说明 / 风险

- 爆米花**不是现金**，不能提现；实物兑换需要库存和人工填写地址/邮费。
- 买种子会消耗爆米花（5 个/颗），纯攒爆米花时净收益会被吃掉一部分。
- 脚本来自 ql.xmox.cn 脚本库，本仓库版本仅统一了配置/通知格式并修正了部分落点；协议逻辑沿用原脚本。
- 自动化操作可能违反平台规则，账号风险自负；建议只挂自己的号、别多号。
- 首次运行会生成 `hykb_answers.json`（答题答案本），已加入 `.gitignore`。

## 接口备忘

| 步骤 | 地址 | 说明 |
|------|------|------|
| 活动首页 | `GET /n/hykb/cornfarm/index.php?imm=0` | 拿 `pageToken` / `pageRandomStr` / 服务器时间 |
| 登录 | `POST ajax.php ac=login` | `scookie` 认证，返回 config（爆米花/种子/玉米） |
| 签到浇水 | `POST ajax_sign.php ac=Sign` | |
| 收割/播种 | `POST ajax_plant.php ac=Harvest/Plant` | |
| 玉米→爆米花 | `POST ajax_bag.php ac=Produce` | |
| 每日任务领取 | `POST ajax_daily.php Daily*Ling` | 返回成熟度/爆米花 |
| 爆爆口令 | `POST ajax_more.php ac=Secretorder` | 口令来自 onebiji 工具页 |
| 爆爆战令 | `POST ajax_season.php` | 经验/等级奖励 |
| 爆友分 | `POST baoyoudiantang2026/ajax.php` | 只领不花资源的任务 |
| 买种子 | `shop.3839.com` 虚拟商品下单 | 5 爆米花/颗 |
