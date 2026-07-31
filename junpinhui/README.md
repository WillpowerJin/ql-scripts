# 君品荟 · 每日签到（YYB Go + 青龙）

[← 返回脚本总览](../README.md)

微信小程序 **习酒君品荟** ·「**每日签到领积分**」：

| 凭据 | 来源 |
|------|------|
| `access_token` | 抓包 `fm.exijiu.com` 头 `X-access-token`（QX / root adb 等） |
| `wx.login` code | 脚本运行时自动请求 **YYB Go**（`app_id=wx8d41cdc44c8aeaab`） |

**不做**酒谷种养（见 [`xijiu`](../xijiu/)）。  
跑完会推送 **美化 Bark 汇总**（账号卡片 + 连续天数 + 积分）。

> 仅供学习。注意平台规则。

---

## 青龙适配

| 项 | 说明 |
|----|------|
| 入口 | `junpinhui/daily.py` |
| 日志 | 双写 stdout/stderr，启动即有输出，避免「无日志」 |
| 定时建议 | `25 8 * * *`（脚本头 `cron` 同此） |
| 任务名 | 君品荟签到（`new Env`） |
| 超时 | 默认够用；多号可 ≥ 5 分钟 |
| 依赖 | `requests`；本地 yaml 需 `PyYAML` |

### 订阅

白名单加上 **`junpinhui`**（根 README 已写）。

```text
白名单： …|junpinhui
扩展名： py
```

### 新建定时任务

| 字段 | 建议 |
|------|------|
| 名称 | 君品荟签到 |
| 命令 | `task …/junpinhui/daily.py` 或 `python3 -u …/junpinhui/daily.py` |
| 定时 | `25 8 * * *` |

---

## 环境变量

### 账号（三选一）

**① 推荐 · 一行一号（多行）**

```text
名称：JUNPINHUI
值：
http://192.168.3.137:8000@openid1|access_token1#主号
http://192.168.3.137:8000@openid2|access_token2#安卓
```

公网 YYB：

```text
http://104.223.57.15:18000@openid|token#备注
```

**② JSON**

```text
名称：JUNPINHUI_ACCOUNTS
值：[{"name":"主号","yyb":"http://192.168.3.137:8000@openid","access_token":"..."}]
```

**③ 与八富共用 YYB 行**

```text
YYB_GO=http://192.168.3.137:8000@openid#主号
JUNPINHUI_ACCESS_TOKEN=你的access_token
```

多号：`YYB_GO` 多行，`JUNPINHUI_ACCESS_TOKEN` 用换行或 `&` **按顺序对齐**。

### 通知与其它

| 变量 | 说明 |
|------|------|
| `BARK_URL` 或 `BARK_KEY` | 与 hifiti / bafu 等共用即可 |
| `BARK_SERVER` | 默认 `https://api.day.app` |
| `BARK_GROUP` | 默认「君品荟签到」 |
| `BARK_SOUND` | 可选提示音 |
| `JUNPINHUI_NOTE` | 全局备注，进 **Bark 标题**（如「家里青龙」） |
| `DRY_RUN=1` | 只查是否已签，不 getCode / 不签到 |

---

## Bark 通知长什么样

标题示例：

```text
君品荟 ✅ 2/2 · 家里青龙
君品荟 ⚠️ 1/2
君品荟 ❌
```

正文结构（示意）：

```text
🍶 习酒君品荟 · 签到汇总
🏷️ 备注：家里青龙
📅 07-31 08:25
────────────────

🍶 【主号】
   🔑 owNAX6uqd6n3…
   ✅ 状态：今日已签
   🔥 连续：12 天

🥂 【安卓】
   🔑 owNAX6aaaa…
   ✅ 状态：签到成功
   🎁 积分：+5
   🔥 连续：3 天

────────────────
📦 账号 2 · ✅2  ❌0
📌 其中已签：1
✍️ 本次新签：1
🎯 本次积分：+5
🎉 全部顺利
```

未配置 Bark 时只打日志，不中断任务。

---

## 流程（脚本自动）

```text
checkTodaySignIn(access_token)
  ├─ 已签 → 查连续天数 → 记成功
  └─ 未签 → POST YYB /wxapp/getCode → fillSignIn → 汇总 Bark
```

**不用**在 YYB 网页手动点 getCode。

---

## 凭据准备

1. **YYB**：扫码绑定 → 复制 openid（见 [`yyb-go`](../yyb-go/)）  
2. **access_token**  
   - iPhone：Quantumult X（[`xijiu/quantumultx`](../xijiu/quantumultx/)）  
   - Android root：`xijiu/pull_access_token.py`  
   - 其它：抓包 `fm.exijiu.com` → `X-access-token`  

token **一号一份**，401 后需重抓。

---

## 本地

```bash
cd junpinhui
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 可选
export JUNPINHUI='http://127.0.0.1:8000@openid|token#测'
export BARK_KEY='你的key'            # 可选
python3 -u daily.py
```

---

## 故障排查

| 现象 | 处理 |
|------|------|
| 青龙无日志 | 用 `python3 -u`；本脚本已双写 stderr |
| 未配置账号 | 检查 `JUNPINHUI` 是否含 `\|token`，多行是否保留 |
| access_token 失效 | 重抓该号 token |
| YYB 无 code | 服务是否通、是否重新扫码 |
| 已签不调 YYB | 正常 |
| Bark 没推 | 查 `BARK_URL`/`BARK_KEY`，看日志「Bark 已配置」 |

---

## 相关

| 目录 | 说明 |
|------|------|
| [yyb-go](../yyb-go/) | 自建 code 服务 |
| [xijiu](../xijiu/) | 酒谷全套 + QX/adb 抠 token |
| [bafu](../bafu/) | 同样用 `YYB_GO` 的八富脚本 |
