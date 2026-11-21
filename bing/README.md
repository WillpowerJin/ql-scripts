# 必应积分助手（国内版）

[← 返回脚本总览](../README.md)

基于社区脚本「必应积分助手 v1.4.1」（作者 满天星 / By-cyt）重写为仓库统一风格。

脚本只依赖 **`cn.bing.com` 的登录 Cookie**，不需要账号密码。

## 会做什么

1. **每日搜索**：先读页面已得积分，按积分缺口补搜（每次 +3 分，每日上限 15 分）

> **2026-11 修复**：必应的搜索积分不是「请求 `/search` 就给分」。实测（真机抓包）
> 计分依赖 SERP 页面的上报链：`POST /rewardsapp/ncheader` +
> `POST /rewardsapp/reportActivity`（body 带二次编码的搜索 URL），随后页面还会
> `rdr=1&rdrig=<IG>` 二次跳转再上报一轮。脚本已按此链路重写；旧版只发
> `GET /search`，青龙跑满 15 次进度仍为 0/15。积分约 1 分钟后到账。
2. **每日集**：解析活动并上报，兼容新版 Server Action 与旧接口
3. **每日问答**：自动提取正确答案并答题
4. **每日精选任务**：每日箴言 / 图片搜索等 5 分小任务
5. **领取积分**：把「可领取」积分领成可用积分；action id 失效时自动从线上 JS 重新提取
6. **签到 / 连续打卡**：查询必应搜索、每日集、Edge、必应 App 等进度
7. **未完成任务汇总**：结束时列出今日仍未完成的项目
8. **通知**：青龙统一通知 / Bark / PushPlus

> 签到需在**必应 App**完成，网页接口通常只能尝试、不一定生效，脚本会如实提示。

---

## 获取 Cookie（必填）

推荐用 **Network 请求头复制**，这样能拿到 HttpOnly 的 `_U`，不会漏：

1. 浏览器登录 <https://cn.bing.com/>，确认右上角显示你的头像/账号名。
2. 按 `F12` 打开开发者工具，切到 **Network（网络）**。
3. 刷新页面，点第一条 `cn.bing.com` 的请求（类型是 `document`）。
4. 在 **Headers → Request Headers** 里找到 `Cookie:`。
5. 复制 `Cookie:` 冒号后面的**整行内容**，例如：

```text
MUID=xxxx; _U=xxxx; SRCHD=xxxx; SRCHUID=xxxx; SRCHUSR=xxxx; _EDGE_S=xxxx; ...
```

> 关键：必须包含 `_U`（登录态，通常是 HttpOnly）。如果只有
> `_EDGE_S`、`_SS`、`_RwBf` 等而没有 `_U`，说明只复制了一部分，脚本会提示
> “Cookie 缺少 _U 登录态”。

> **rewards.bing.com 还需要单独登录**：如果 `--check` 提示
> 「rewards.bing.com 仍要求登录」，说明 `cn.bing.com` 已登录但 Rewards 会话没建立。
> 请在浏览器打开 <https://rewards.bing.com/earn>（必要时先点登录），确认能看到
> 积分/任务后，按同样的 Network 方法复制**该页请求**的 `Cookie` 请求头。
> 这份 Cookie 通常还要包含 `_C_Auth`、`.AspNetCore...`、`MSPAuth` 等 Rewards 会话字段。

也可以用 **Application（应用） → Cookies → https://cn.bing.com** 逐行复制；
每行是一个 `name=value`，用 `; ` 拼成一行即可。但表格容易漏行，建议优先用
Network 请求头。

Cookie 会过期，失效后脚本会提示重新抓取。建议每隔几周检查一次。

---

## 青龙

### 订阅

白名单加上 **`bing`**：

```text
hifiti|xijiu|quark|bilibili|fanghua|fun|tuiguangbao|aliyun_dev|kuailefeng|dianxin|jinpinghu|tianyi|bing|huazhu|ikea|sfsy
```

### 依赖

```text
requests
```

青龙只用环境变量时不必装 PyYAML。

### 环境变量

| 变量 | 说明 |
|------|------|
| `BING_COOKIE` | 必填，完整 Cookie（多账号用 `&`、换行或 `#` 分隔） |
| `by` | 兼容原脚本变量名，写法相同 |
| `BING_ACCOUNTS` | 可选，JSON 数组：`[{"name":"主号","cookie":"..."}]` |
| `BING_SEARCH_TIMES` | 每日搜索最多尝试次数，默认 15（最多 20）；实际按积分缺口 ÷3 换算，一般 5 次即满 |
| `BING_DELAY` | 任务间间隔，默认 `3-8` |
| `BING_SEARCH_DELAY` | 每日搜索之间的间隔，默认 `100-150` 秒（搜索积分约 1 分钟到账，间隔太短会被丢弃不计分） |
| `BING_WAIT_SECONDS` | 最终查积分前等待秒，默认 60 |
| `BING_OFFERS` | 是否做每日精选任务，默认 1 |
| `BING_CHECKIN` | 是否尝试签到，默认 1 |
| `BING_CLAIM` | 是否领取待领取积分，默认 1 |
| `BING_TIMEOUT` | 请求超时秒，默认 20 |
| `BING_INTER_ACCOUNT_DELAY` | 账号间隔秒，默认 5 |

多账号示例：

```text
BING_COOKIE=账号1完整Cookie&账号2完整Cookie
```

或使用 JSON：

```text
BING_ACCOUNTS=[{"name":"主号","cookie":"..."},{"name":"小号","cookie":"..."}]
```

### 定时

```text
20 8,20 * * *
```

建议**每天跑两次**：第一次做完任务，晚上再跑一次可以领到当天延迟到账的
「待领取」积分。青龙任务超时建议 ≥ 20 分钟。

### 通知

| 变量 | 说明 |
|------|------|
| `BARK_URL` / `BARK_KEY` | 与仓库其它脚本共用同一套 Bark |
| `BARK_GROUP` | 默认 `必应积分` |
| `PUSHPLUS_TOKEN` / `PUSHPLUS_TOPIC` | 可选 |

---

## 本地运行

```bash
cd bing
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填写 cookie
python3 daily.py --check             # 先验证 Cookie 是否有效
python3 daily.py                     # 正式执行
```

指定配置或调试：

```bash
python3 daily.py -c /path/to/config.yaml
python3 daily.py --debug
```

---

## 文件夹

| 文件 | 说明 |
|------|------|
| `daily.py` | 必应积分日常任务入口 |
| `config.example.yaml` | 本地配置示例 |
| `requirements.txt` | `requests` |
| `README.md` | 本说明 |

---

## 常见问题

### `--check` 提示「Cookie 缺少 _U 登录态」

说明只复制了部分 Cookie。请用 Network → Request Headers → `Cookie:` 整行复制，
不要逐行抄 Application 表格。

### `--check` 提示「rewards.bing.com 仍要求登录」

`cn.bing.com` 已登录，但 Microsoft Rewards 是另一个登录会话。请在浏览器打开
<https://rewards.bing.com/earn>，必要时先登录，确认能看到积分/任务后，再复制
**该页请求**的 `Cookie` 请求头。

### 签到一直显示「未生效」

必应签到需要在**必应 App**里完成，网页接口无法真正签到，脚本会如实提示。
不想每次都尝试可以设：

```text
BING_CHECKIN=0
```

### 积分没有马上到账

Bing 积分有延迟。脚本默认在结束前等 60 秒再查积分；如果仍显示「待领取」，
晚上再跑一次脚本即可领取。

### Cookie 多久失效

通常数周到数月。失效后 `--check` 会提示 Cookie 无效或 Rewards 需要登录，
按上面的方法重新抓取即可。

---

## 说明

- 本脚本不会登录微软账号，只使用你提供的 Cookie；请不要把 Cookie 提交到 Git。
- 每日搜索上限、任务结构可能随微软发版变化，解析失败时会记录到「未完成」汇总。
- 仅用于学习交流，请遵守微软 Rewards 与必应的服务条款。
