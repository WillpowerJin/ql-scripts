# 习酒 · 君品荟（酒谷）

[← 返回脚本总览](../README.md)

微信小程序 **习酒君品荟** 的酒谷自动任务：

| 模块 | 说明 |
|------|------|
| **习酒文旅 → 酒谷** | 滑块验证、酒谷签到、土地种养、任务、制曲/制酒/收酒 |
| 可选 | 酒兑积分 |

> 原「每日签到领积分」（`fm.exijiu.com`，需 `access_token` / `wx_code`）**已移除**：
> `access_token` 频繁失效，维护成本高；该改动只删除签到链路，酒谷任务完全保留。

基于公开 Surge 脚本思路重写为 Python（对齐本仓库 `hifiti` / `quark` 结构），并做了：

- 浇水/施肥 **最大次数**，避免死循环刷接口
- 土地解锁失败（未达收酒条件）时 **跳过后续未开垦地**
- 登录 / 业务错误结构化返回
- 滑块：远程 OCR 或本地 `ddddocr`
- 青龙字符串/JSON 环境变量 + 本地 yaml
- Bark 通知与 hifiti 共用

> 仅供学习研究。需自行抓包维护 `login_code`，注意平台规则与风控。

## 快速开始

```bash
cd xijiu
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml
# 填写 accounts[].login_code（酒谷）

python daily.py --info-only   # 只登录查资产
python daily.py               # 酒谷任务
python daily.py --exchange    # 额外酒兑积分
```

## 凭据怎么拿（login_code，酒谷必填）

1. 手机开抓包（Reqable / Stream 等），**勾选抓小程序**，过滤域名 `exijiu.com`
2. 打开 **微信 → 习酒君品荟**（进一次酒谷页面）
3. 找 **`xcx.exijiu.com`** 请求头里的 **`login_code`**（JWT 形态）
4. **不要**把业务接口的 `Authorization` 误当成 login_code
5. 填入 `config.yaml` / `XIJIU_LOGIN_CODE`

脚本会用 `login_code` 调 `getJwt` 换酒谷 JWT。

## 抓包重点接口

| 用途 | 域名 / 路径 |
|------|-------------|
| 酒谷换票 | `xcx.exijiu.com` … `/Member/getJwt`（头 `login_code`） |
| 酒谷签到 | `apimallwm.exijiu.com` `/garden/Sign/dailySign`（**S** 大写） |
| 土地 | `/garden/Sorghum/*`（**S** 大写） |
| 资产 | `/garden/Gardenmemberinfo/getMemberInfo` |

路径大小写错误会假报「请从小程序重新进入」，**不是** `login_code` 失效。

## 青龙

**定时任务**（脚本头已写，订阅拉取后自动带上）：

```text
0 */2 * * *
```

**环境变量（账号）：**

```text
XIJIU_ACCOUNTS=[{"name":"主号","login_code":"eyJ..."},{"name":"iPhone","login_code":"eyJ..."}]
```

要求：

- 必须是 **JSON 数组**（以 `[` 开头、`]` 结尾）
- 键名用 **英文双引号**，不要中文引号 `“”`
- **不要**把 `config.yaml` 整份贴进 `XIJIU_ACCOUNTS`（那是 yaml，不是 JSON）
- 多个账号对象之间用 **英文逗号** `,`
- 青龙若报 `Expecting value: line …`：就是这个变量 JSON 写坏了，按上面重写

或拆字段（更不容易写错）：

```text
XIJIU_LOGIN_CODE = code1&code2
XIJIU_NAME = 主号&iPhone
```

**可选：**

| 变量 | 说明 |
|------|------|
| `XIJIU_DO_GARDEN=0` | 关酒谷 |
| `XIJIU_EXCHANGE=1` | 开酒兑积分 |
| `XIJIU_OCR_SERVER` | 滑块 OCR，如 `http://ip:7777`（POST `/capcode`） |
| `BARK_URL` / `BARK_KEY` | 通知 |

> `XIJIU_DO_SIGN` / `XIJIU_ACCESS_TOKEN` 已废弃，不再读取。

## 日志示例

```text
📅 07-27 17:00

✅ 主号
   🌾 酒谷签到：今日已签 ✅
   🧩 酒谷验证：无需 / 已过
   💰 积分 5 · 酒 0 · 高粱 100 · 小麦 0 · 酒曲 10
   🪴 地块：1 块已处理
   📋 任务：完成约 3/4 项
```

## 酒谷滑块

每日酒谷可能要求滑块：

1. 配置 `XIJIU_OCR_SERVER` → `POST /capcode`
2. 或本机 `pip install ddddocr`
3. **都不配：** 打日志并尽量继续；若接口强制验证则酒谷相关会失败

青龙（Alpine/musl）装不了本地 `ddddocr`/`opencv`，推荐用外部 OCR 服务，
把 `XIJIU_OCR_SERVER` 指向服务地址即可。

## 说明

- 酒谷登录使用 `login_code` 换 JWT，与已移除的积分签到 `access_token` 无关
- 未解锁土地需要收酒量达标，脚本遇「无法开垦」会停止继续刷解锁
- 原 `pull_access_token.py` 与 Quantumult X token 抓取脚本已随签到任务一起删除
