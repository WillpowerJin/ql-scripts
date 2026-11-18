# 酷狗概念版金币任务

[← 返回脚本总览](../README.md)

基于社区脚本「酷狗概念版跑25W金币多账号 v3.5」重写为仓库统一风格：

- 签到
- 全量任务「满链翻倍」
- 1105 定时领取循环
- 翻牌活动
- 福利中心（盲盒 / 抽奖 / 新人 VIP / 排行榜）
- 听歌上报
- 多账号并发
- Bark / PushPlus / 青龙统一通知

> 收益与账号风险自负。这个脚本会高频请求酷狗接口，并尝试把每日任务做到上限；
> 是否使用、用到什么程度，请自行判断。

---

## 需要准备什么

只需要 **Kugou 账号的 token 与 userid**，不需要手机号和密码。

| 字段 | 必填 | 说明 |
|------|------|------|
| `token` | 是 | 酷狗登录 token |
| `userid` | 是 | 数字 userid |
| `mid` | 可选 | 设备 mid，新版通常 40 位；不填按 token 推导 |
| `dfid` | 可选 | 设备 dfid；不填按 token 推导 |
| `devid` | 可选 | `KG-DEVID` 设备标识 |
| `t2` | 可选 | 部分账号需要 |
| `uni_verify_str` | 可选 | 部分账号需要 |
| `appid` | 可选 | App id，默认 `3114`（新版） |
| `clientver` | 可选 | 客户端版本，默认 `12520`（新版） |
| `channel` | 可选 | 渠道号，默认 `12520` |

获取方式：

1. 手机抓包酷狗概念版 App 的请求（登录后任意接口的 query），取
   `token`、`userid`、`mid`、`dfid`、`devid`。
2. 或使用原脚本作者提供的扫码/发码方式获取。
3. 先只填 `token` + `userid` 也能跑，脚本会自动推导 mid/dfid；但真实设备
   参数通常更稳定。
4. 抓包 URL 里如果 `appid` / `clientver` / `channel` 不是 `3114` / `12520`，
   在 JSON 或 `config.yaml` 里把这三个字段改成抓包值。

当前默认参数：

```text
appid=3114
clientver=12520
channel=12520
```

原脚本写死的 `appid=3116 / clientver=11571` 已过旧，新版概念版需要上面这组。

---

## 青龙环境变量

### 方式 A（推荐）：`KUGOU_ACCOUNTS` JSON

```text
名称：KUGOU_ACCOUNTS
值：
[
  {"name":"主号","token":"xxx","userid":"2247744797","mid":"5e8f...","dfid":"2lOn...","appid":"3114","clientver":"12520","channel":"12520"}
]
```

### 方式 B：兼容原脚本 `KGGNB`

```text
名称：KGGNB
值：备注#token#userid#mid#dfid#devid
```

多账号用 `&` 或换行：

```text
主号#token1#userid1#mid1#dfid1#devid1&小号#token2#userid2
```

简写也支持：

```text
备注#token#userid
token#userid
token=xxx;userid=yyy;mid=zzz;dfid=www
```

也兼容 `kggnb` / `KGGNB_TASK` / `kugou_token` / `kwtx` / `KWTX`。

### 其他可选变量

| 变量 | 说明 |
|------|------|
| `KUGOU_SERIAL=1` | 多账号串行（默认并发） |
| `KUGOU_MAX_WORKERS` | 并发账号数，默认 10 |
| `KUGOU_LOOP_ROUNDS` | 1105 最大轮数，默认 40 |
| `KUGOU_LOOP_MAX_WAIT` | 1105 单次最大等待秒，默认 1200 |
| `KUGOU_DOUBLE_MAX` | 翻倍链上限，默认 12 |
| `KUGOU_DELAY` | 任务间隔，默认 `1.2-2.5` |
| `KUGOU_TIMEOUT` | 请求超时，默认 25 |
| `KUGOU_RETRY` | 重试次数，默认 1 |
| `KUGOU_LOCK=0` | 关闭防重复运行锁 |

---

## 运行模式

| 命令 | 行为 |
|------|------|
| `python3 daily.py` | 默认：任务 + 1105 循环 + 翻牌（可能持续数小时） |
| `python3 daily.py --once` | 只做一轮任务，跳过 1105 循环（较快） |
| `python3 daily.py --info` | 仅查询金币、签到、任务进度 |
| `python3 daily.py --flip` | 仅翻牌 |
| `python3 daily.py --welfare` | 仅福利中心 |
| `python3 daily.py --assist <share_code>` | 翻牌助力 |
| `python3 daily.py --test` | 签名自检 |
| `python3 daily.py --serial` | 多账号串行 |

首次建议：

```bash
python3 daily.py --info
```

确认 token/userid 能读到余额和任务，再跑任务。

---

## 青龙定时

```text
5 0 * * *
```

默认模式包含 1105 循环，可能需要数小时；青龙任务超时要设得足够大
（建议 ≥ 6 小时或按你的账号数量调整）。

如果只想快速跑一轮，把命令改成：

```text
python3 kugou/daily.py --once
```

并把超时设到 20～30 分钟。

---

## 通知

| 变量 | 说明 |
|------|------|
| `BARK_URL` / `BARK_KEY` | 与仓库其它脚本共用同一套 Bark |
| `BARK_GROUP` | 默认 `酷狗概念版` |
| `PUSHPLUS_TOKEN` / `PUSHPLUS_TOPIC` | 可选 |

青龙环境会自动调用 `notify.py`；本地则走 Bark / PushPlus。

---

## 本地运行

```bash
cd kugou
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填写 token / userid
python3 daily.py --test
python3 daily.py --info
python3 daily.py --once
python3 daily.py                     # 完整模式
```

指定配置：

```bash
python3 daily.py -c /path/to/config.yaml
```

---

## 防重复运行

脚本默认在 `/tmp/kugou_task_v3.lock` 写 PID 锁，防止青龙任务重叠导致同一账号
并发请求。确认没有其它实例时，可以设：

```text
KUGOU_LOCK=0
```

---

## 文件夹

| 文件 | 说明 |
|------|------|
| `daily.py` | 任务入口 |
| `config.example.yaml` | 本地配置示例 |
| `requirements.txt` | `requests` |
| `README.md` | 本说明 |

---

## 常见问题

### `--info` 提示读取余额失败

通常是 `token` 或 `userid` 失效、`mid/dfid` 不对，或账号被风控。建议重新抓包，
补全 `mid/dfid/devid` 后再试。

### 任务没有收益 / 翻倍链很短

酷狗会按账号、设备、风控状态动态限制。先确认 `--info` 能正常读取任务，
再尝试补全真实设备参数；不要频繁短时间重复运行。

### 默认模式跑很久

默认会执行 1105 定时领取循环，单账号可能持续数小时。只想快速跑任务请用
`--once`。

### 多账号会不会串号

每个账号使用独立的 `KugouClient` 和 HTTP Session，并发执行互不共享 token。

### 收益真的能到 25W 金币吗

脚本保留原作者的满链翻倍逻辑，但实际收益受账号等级、任务开放情况、风控和
活动变化影响，不保证固定收益。
