# 电信营业厅（天翼）签到 + 金豆任务 + 转盘

[← 返回脚本总览](../README.md)

基于社区脚本「电信任务加转盘」重写为仓库统一风格：手机号 + 服务密码 + AndroidID
走电信营业厅统一认证（`appgologin.189.cn`），换取 jt-sign Ticket 后依次执行：

1. **每日签到**，并领取连签 7 天、累签 15 / 28 天奖励
2. **任务列表**：领奖、开宝箱、分享得金豆、观看直播、聚合任务
3. **宠物喂食**，查询宠物等级与成长进度
4. **金豆余额**查询与月底过期提醒
5. **金豆转盘**：按剩余次数自动抽完
6. **通知**：青龙统一通知 / Bark / PushPlus

> 账号、服务密码、AndroidID 只写在**青龙环境变量**（或本地不提交的
> `config.yaml`），不要提交到 Git。Token 缓存在状态目录，已 gitignore。

---

## 账号格式

青龙 → 环境变量 → 新建。

### 方式 A（推荐）：JSON 数组

```text
名称：TIANYI_ACCOUNTS
值：
[
  {"name":"主号","phone":"13800000000","password":"服务密码","android_id":"0123456789abcdef"}
]
```

`name` / `note` / `remark` 都当备注。

### 方式 B：分隔字符串（兼容原脚本）

```text
名称：chinaTelecomAccount
值：  手机号#服务密码#AndroidID[#备注]
```

多账号用 `&` 或换行分隔：

```text
13800000000#服务密码#0123456789abcdef#主号&13900000000#服务密码#fedcba9876543210#小号
```

不带 AndroidID 但带备注时中间留空：`手机号#服务密码##备注`。
也可用 `TIANYI_ACCOUNT` / `TELECOM_ACCOUNTS`。

> AndroidID 是手机设备的 16 位十六进制 ID。首次登录必须提供；登录成功后
> Token 会缓存，后续定时任务可不填。获取方式：输入手机号后点「刷新验证码」，
> 多刷几次，站点接入 Cloudflare 可能较慢：<https://telecom.nufe.ccwu.cc>

---

## 青龙

### 订阅

白名单加上 **`tianyi`**：

```text
hifiti|xijiu|quark|bilibili|fanghua|fun|tuiguangbao|aliyun_dev|kuailefeng|dianxin|jd|tianyi
```

### 依赖

```text
requests
pycryptodome
certifi
```

青龙只用环境变量时不必装 PyYAML。

### 环境变量

| 变量 | 说明 |
|------|------|
| `TIANYI_ACCOUNTS` | 推荐，JSON 数组多账号 |
| `chinaTelecomAccount` | 兼容原脚本：`手机号#服务密码#AndroidID[#备注]` |
| `TIANYI_ACCOUNT` / `TELECOM_ACCOUNTS` | 同上，别名 |
| `TIANYI_TIMEOUT` | 请求超时秒，默认 15 |
| `TIANYI_LIVE_ROUNDS` | 直播观看轮数，默认 11；`0` 关闭 |
| `TIANYI_LIVE_INTERVAL` | 每轮间隔秒，默认 15 |
| `TIANYI_FEED_TIMES` | 喂食次数上限，默认 10 |
| `TIANYI_INTER_ACCOUNT_DELAY` | 账号间隔秒，默认 3 |
| `TIANYI_STATE_DIR` | 状态目录，青龙默认 `/ql/data/tianyi` |

### 定时

```text
30 8 * * *
```

直播任务每账号约 `11 × 15` 秒，多账号请把任务超时调到 **≥ 20 分钟**。

### 通知

| 变量 | 说明 |
|------|------|
| `BARK_URL` | App 里复制的完整地址 |
| 或 `BARK_KEY` | 仅 Key |
| `BARK_SERVER` | 自建服务器，默认 `https://api.day.app` |
| `BARK_GROUP` | 默认 `电信营业厅` |
| `BARK_SOUND` / `BARK_ICON` / `BARK_LEVEL` | 可选 |
| `PUSHPLUS_TOKEN` / `PUSHPLUS_TOPIC` | 可选 |

青龙环境下脚本会自动调用 `notify.py`；本地则走 Bark / PushPlus。

---

## 本地运行

```bash
cd tianyi
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填写 phone / password / android_id
python3 daily.py
```

新账号建议先只查询，验证登录链路：

```bash
python3 daily.py --check
```

指定配置文件或调试：

```bash
python3 daily.py -c /path/to/config.yaml
python3 daily.py --debug
```

---

## 文件夹

| 文件 | 说明 |
|------|------|
| `daily.py` | 签到 / 任务 / 宠物 / 金豆 / 转盘入口 |
| `config.example.yaml` | 本地配置示例 |
| `requirements.txt` | `requests` + `pycryptodome` + `certifi` |
| `state/token_cache.json` | 本地 Token 缓存，已 gitignore |

---

## 说明

- 登录走官方统一认证，服务密码经 RSA 加密后提交；脚本不保存密码。
- Token 失效会自动清除缓存并用 AndroidID 重新登录。
- 转盘依赖统一登录换到的 Bearer；若该步失败，仅跳过抽奖，其它任务照常执行。
- 仅供学习交流，请遵守电信服务条款；账号与资产风险自负。
