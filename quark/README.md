# 夸克网盘自动签到（青龙 + Bark）

[← 返回脚本总览](../README.md)

针对 [夸克网盘](https://pan.quark.cn/) 每日签到领取免费存储容量的脚本。走的是 App 端接口 `drive-m.quark.cn/1/clouddrive/capacity/growth/{info,sign}`，用抓包得到的 `kps` / `sign` / `vcode` 作签名鉴权。

> 账号参数与 Bark 等敏感信息只写在**青龙环境变量**（或本地不提交的 `config.yaml`），不要提交到 Git。

## 策略

1. 从环境变量 `COOKIE_QUARK` 读取账号列表（本地也可用 `config.yaml` 兜底）
2. 支持两种写法：**整段 URL**（推荐）或 `kps; sign; vcode` 拆开写
3. 先请求 `growth/info` 查容量、身份、今日是否签过
4. 未签过 → `growth/sign` 触发签到 → 拿到今日奖励字节 + 连签进度
5. Bark 推送汇总（可选，与 hifiti / quark 共用同一套环境变量）

## 仓库内文件

| 文件 | 是否进青龙 | 说明 |
|------|------------|------|
| `quark_checkin.py` | ✅ 拉取 | 签到主脚本 |
| `quantumultx/quark_reward_capture.js` | ❌ 不拉 | iOS Quantumult X 抓包脚本 |
| `quantumultx/quark_reward_capture.snippet.conf` | ❌ 不拉 | QX rewrite 片段 |
| `README.md` | ❌ 不拉 | 本文档 |
| `config.example.yaml` | ❌ 不拉 | 本地配置示例 |
| `requirements.txt` | ❌ 不拉 | 本地依赖清单 |

青龙侧依赖在「依赖管理」手动添加：`requests`。

## 青龙订阅

根 [README](../README.md) 里的白名单包含 `checkin`，本脚本文件名为 `quark_checkin.py`，会一起被拉下来。

定时（脚本头已写，也可自行改）：

```
0 9 * * *
```

## 抓取签到参数（一次性）

夸克 App 端签到接口要 `kps` / `sign` / `vcode` 三个签名参数，网页 Cookie 里没有，只能从 App 请求里抓。

### 方式 A（推荐 · iOS）：仓库自带的 QX 脚本

仓库里 [`quantumultx/quark_reward_capture.js`](./quantumultx/quark_reward_capture.js) + [`quantumultx/quark_reward_capture.snippet.conf`](./quantumultx/quark_reward_capture.snippet.conf) 已经写好一整套抓包 + 通知逻辑：

1. 把 `quark_reward_capture.js` 放进 QX 的 `Scripts` 目录  
   （「文件」App → iCloud 云盘 或 我的 iPhone → **Quantumult X → Scripts**）
2. QX → 重写：粘贴 `.snippet.conf` 里的 `[rewrite_local]` + `[mitm]`，右下角刷新
3. 打开夸克 App，进入「我的 → 会员中心 / 抽奖页」，触发一次 `growth/reward` 请求
4. iPhone 顶部会弹通知「🚀 夸克签名·v3」，正文三行：
   ```
   🔑 kps=xxx
   ✍️ sign=yyy
   🔢 vcode=zzz
   ```
5. 长按通知拷贝，把三个值粘到青龙环境变量（下节）

冷却 60 秒/URL，同一次点会员中心只弹一条。三个值也会同步缓存到 `$prefs.quark_kps / quark_sign / quark_vcode`。

### 方式 B（通用 · Charles / Stream / mitmproxy 等）

1. 手机开启抓包代理，安装并信任对应 CA 证书
2. 打开夸克 App，进入「我的 → 会员中心 / 抽奖页」
3. 抓到 URL 为 `https://drive-m.quark.cn/1/clouddrive/act/growth/reward` 的请求
4. 复制该请求「完整 URL」（后面必须带 `kps`、`sign`、`vcode` 三个参数）

### 参数有效期

按经验一般能用几周到几个月，App 端**退登、换设备、清缓存**会失效；一旦签到接口返回类似「登录已过期」或 41008 之类，重抓一次即可。

## 环境变量（账号）

支持两种写法，二选一。同时存在时 **`QUARK_ACCOUNTS` 优先**。

### 方式 A（推荐）：`QUARK_ACCOUNTS` JSON 数组

多账号最清晰，字段与 `config.yaml` 对齐：

```json
[
  {
    "name": "张三",
    "url": "https://drive-m.quark.cn/1/clouddrive/act/growth/reward?xxxx=xxxx&kps=abc&sign=def&vcode=123"
  },
  {
    "name": "李四",
    "kps": "abc",
    "sign": "def",
    "vcode": "123"
  }
]
```

- `name` 是自定义备注（也可写成 `user`），多账号方便区分
- `url` 与 `kps/sign/vcode` 二选一：写 `url` 时脚本自动解析；两种都写时以三个字段为准
- 青龙里粘贴时必须是**一整行合法 JSON**，包含 `"` 的字段要转义

### 方式 B（兼容旧格式）：`COOKIE_QUARK` 分号字段

多账号用「回车」或「`&&`」分隔。

推荐子写法（URL 整段贴进来，脚本自动解析）：

```text
user=张三; url=https://drive-m.quark.cn/1/clouddrive/act/growth/reward?xxxx=xxxx&kps=abc&sign=def&vcode=123
```

多账号：

```text
user=张三; url=https://drive-m.quark.cn/1/clouddrive/act/growth/reward?...&kps=aaa&sign=bbb&vcode=ccc
&&
user=李四; url=https://drive-m.quark.cn/1/clouddrive/act/growth/reward?...&kps=xxx&sign=yyy&vcode=zzz
```

兼容子写法（拆开三个字段）：

```text
user=张三; kps=abc; sign=def; vcode=123
```

三个签名值保留 URL 编码原样即可，脚本会直接透传给夸克接口。

## 环境变量（Bark，可选，与 hifiti / quark 共用）

| 变量 | 说明 |
|------|------|
| `BARK_URL` | App 里复制的完整地址，如 `https://api.day.app/你的Key/` |
| 或 `BARK_KEY` | 仅 Key |
| `BARK_SERVER` | 可选，自建服务器，默认 `https://api.day.app` |
| `BARK_GROUP` | 可选，通知分组，默认 `夸克签到` |
| `BARK_SOUND` | 可选，铃声 |
| `BARK_ICON` | 可选，图标 URL |
| `BARK_LEVEL` | 可选：`active` / `timeSensitive` / `passive` |

未配置 Bark 时脚本自动跳过推送；若青龙里有 `notify.py`，会同时走一次原生青龙通知。

## 其它可选变量

| 变量 | 说明 |
|------|------|
| （暂无） | 超时/重试等默认写在脚本常量里，如需修改可直接改源码 |

## 本地运行

```bash
cd quark
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填写后不要 git add
python quark_checkin.py
```

或导出与青龙相同的环境变量后直接运行：

```bash
export COOKIE_QUARK='user=张三; url=https://drive-m.quark.cn/1/clouddrive/act/growth/reward?...&kps=...&sign=...&vcode=...'
export BARK_URL='https://api.day.app/xxxx/'
python quark_checkin.py
```

## 日志示例

```
════════════════════════════════════════════════
  🐬 夸克网盘 · 自动签到
════════════════════════════════════════════════
🔍 检测到 1 个账号

┌─ 🙍 账号 1/1 · 张三
│  🏷️  身份：普通用户
│  💾 网盘总容量：11.00 TB
│  📦 签到累计：3.24 GB
│  ✅ 签到成功：+100.00 MB  连签 4/7
└───────────────────────────────────────────────

════════════════════════════════════════════════
  📝 签到汇总
════════════════════════════════════════════════
📅 2026-07-29 09:00

✅ #1 张三
   🏷️ 普通用户 · 💾 11.00 TB
   📦 累计 3.24 GB
   ✨ 签到成功 +100.00 MB · 连签 4/7

────────
📊 合计：1/1 全部成功 🎉
════════════════════════════════════════════════
📣 Bark 已推送（HTTP 200）
```

## 接口说明

| 步骤 | 方法 | URL | 说明 |
|------|------|-----|------|
| 查询容量 | GET | `/1/clouddrive/capacity/growth/info` | `pr=ucpro&fr=android` + `kps/sign/vcode` |
| 签到 | POST | `/1/clouddrive/capacity/growth/sign` | 同上 query，body `{"sign_cyclic": true}` |

`info` 响应关键字段：

```jsonc
{
  "data": {
    "88VIP": false,                       // 是否 88VIP
    "total_capacity": 12094627905536,     // 网盘总容量（字节）
    "cap_composition": {
      "sign_reward": 3480000000           // 签到累计容量（字节）
    },
    "cap_sign": {
      "sign_daily": false,                // 今日是否签过
      "sign_daily_reward": 104857600,     // 今日奖励字节
      "sign_progress": 3,                 // 已连签天数
      "sign_target": 7                    // 目标（每 7 天翻倍）
    }
  }
}
```

## 常见错误

| 现象 | 原因 / 处理 |
|------|-------------|
| `❌ 未添加 COOKIE_QUARK 变量` | 青龙里没配环境变量，或本地没 `config.yaml` |
| `获取成长信息失败（kps/sign/vcode 可能已过期）` | 三个签名参数失效，App 里重新触发 `growth/reward` 抓一次 |
| `member_type=NORMAL` 但奖励 0 MB | 官方偶发风控，第二天恢复；或该账号未通过实名 |
| Bark 一直 400 / 无推送 | `BARK_URL` 少加尾部 `/` 或 Key 拼错，可只填 `BARK_KEY` |

## 依赖

- 青龙：只需 `requests`
- 本地 yaml：`requests` + `PyYAML`
