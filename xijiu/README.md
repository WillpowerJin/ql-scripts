# 习酒 · 君品荟

[← 返回脚本总览](../README.md)

微信小程序 **习酒君品荟** 自动任务：

| 模块 | 说明 |
|------|------|
| **每日签到领积分** | `fm.exijiu.com` `/api/customer/daily/*`（手机 UI 可见） |
| **习酒文旅 → 酒谷** | 滑块验证、酒谷签到、种养、任务、制曲/制酒/收酒 |
| 可选 | 酒兑积分 |

基于公开 Surge 脚本思路重写为 Python（对齐本仓库 `hifiti` / `wangchao` 结构），并做了：

- 浇水/施肥 **最大次数**，避免死循环刷接口  
- 土地解锁失败（未达收酒条件）时 **跳过后续未开垦地**  
- 登录 / 业务错误结构化返回  
- 滑块：远程 OCR 或本地 `ddddocr`  
- 青龙字符串/JSON 环境变量 + 本地 yaml  
- Bark 通知与 hifiti 共用  

> 仅供学习研究。需自行抓包维护凭据，注意平台规则与风控。

## 快速开始

```bash
cd xijiu
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml
# 填写 accounts[].login_code（酒谷）
# 填写 accounts[].access_token（积分签到，见下）

python daily.py --info-only   # 只登录查积分/酒
python daily.py               # 积分签到 + 酒谷
python daily.py --no-garden   # 仅积分签到
python daily.py --exchange    # 额外酒兑积分
```

## 凭据怎么拿

### 1. login_code（酒谷必填）

1. 手机开抓包（Reqable / Stream 等），**勾选抓小程序**，过滤域名 `exijiu.com`  
2. 打开 **微信 → 习酒君品荟**（进一次酒谷页面）  
3. 找 **`xcx.exijiu.com`** 请求头里的 **`login_code`**（JWT 形态）  
4. **不要**把业务接口的 `Authorization` 误当成 login_code  
5. 填入 `config.yaml` / `XIJIU_LOGIN_CODE`  

脚本会用 `login_code` 调 `getJwt` 换酒谷 JWT。

### 2. access_token（每日签到领积分）

旧接口 `/member/Signin/sign` 已下线；手机上能用的是 **「每日签到领积分」**。  
真实小程序 AppID 见代码内 `_MINI_APPID` / `APPID`（公开标识，不是密钥；与旧脚本 `wx673f…` 不同）。

**每个账号各自一份 token，不能混用。** 失效时接口返回 `401 用户未登录`（摘要会显示「access_token 已失效」，不是「没配置」）。

**方式 A（root 安卓 + adb，`pull_access_token.py`）：**

这是辅助脚本：从**当前手机、当前微信**的 MMKV 缓存里抠出 `accessToken`，不是给「配置里所有账号」批量刷新的。

| 能做什么 | 不能做什么 |
|----------|------------|
| root 安卓 + 已登录的微信 → 拉出该号 token | iPhone / 未 root |
| `--account 名称` 写入 config 对应号 | 一台手机一次变出多号 token |
| 多台安卓用 `--serial` 指定设备 | 代替抓包拿 `login_code` |

```bash
# 1）手机用【主号微信】打开君品荟签到页
python pull_access_token.py --write-config --account 主号

# 2）换【另一个微信号】登录（或另一台 root 手机），再打开签到页
python pull_access_token.py --write-config --account iPhone

# 只打印、不写配置
python pull_access_token.py
python pull_access_token.py --list   # 看 MMKV 里扫到几条
```

**多账号正确姿势：** 每个习酒账号对应一个微信；每个微信各自拉一次（或抓包一次），写到 config 里**同名**的那条 `access_token`。  
**iPhone 号**一般没有 root adb → 用下面方式 B 抓包即可。

**方式 B（抓包；iPhone / 多账号都适用）：**

1. 用 **该账号登录的微信** 开抓包  
2. 过滤 **`fm.exijiu.com`**  
3. 打开 **签到** 页  
4. 请求头 **`X-access-token`** → 填到 **该账号** 的 `accounts[].access_token`  

`fillSignIn` 还会带 **`code`**（`wx.login` 临时码，约 5 分钟）。  
- **当天已签**：只需有效的 `access_token`，`checkTodaySignIn` 返回 `data:true`  
- **未签要自动签**：需额外抓 `fillSignIn` 的 body.`code` 填 `wx_code`，或手机点签到  

**常见误判：**

| 摘要文案 | 实际含义 |
|----------|----------|
| 未配置 access_token | 配置里该字段为空 |
| access_token 已失效 | 填了，但过期/错误/串了别的号的 token → **重新抓包** |

**方式 C（iPhone + Quantumult X 全自动抓）：**

比方式 B 少一步「手动复制粘贴」——每次打开签到页时脚本自动把 `X-access-token` 存到本地键值，可选 Bark 通知，也可回传青龙 webhook 自动写 config。

脚本：[`quantumultx/xijiu_access_token.js`](quantumultx/xijiu_access_token.js)  
配置片段：[`quantumultx/xijiu_access_token.snippet.conf`](quantumultx/xijiu_access_token.snippet.conf)

1. **放脚本**：把 `xijiu_access_token.js` 传到你自己的 GitHub raw / jsdelivr / iCloud Drive；或者用 Quantumult X 「本地脚本编辑」直接粘贴。
2. **加规则**（Quantumult X → 首页 → 「重写」右上角编辑器）：
   ```
   [rewrite_local]
   ^https?:\/\/fm\.exijiu\.com\/ url script-request-header 你的脚本URL

   [mitm]
   hostname = fm.exijiu.com   # 追加到你已有的 hostname 后面，别覆盖
   ```
3. **信任证书**：Quantumult X 首页 → 「MitM」→ 生成 CA 证书 → 在 iOS「设置 → 已下载描述文件」安装 → 「关于本机 → 证书信任设置」勾选。
4. **触发**：打开微信 → 「习酒君品荟」小程序 → 签到页；脚本命中后弹通知「习酒 · access_token 已更新」。
5. **拿到 token**：
   - 通知里的预览是缩略；完整值去 **BoxJs**（若装了）→ 应用列表拉到底看 `App Rewrite Panel` 或直接搜键名，或
   - 打开 Quantumult X → 首页 → 「工具」→ 「脚本运行」→ 新建一个「取值」测试脚本读 `xijiu_access_token`，或
   - **推荐**：脚本自带 Bark 推送和 webhook 回传，见下方「本地键值」段。

**本地键值**（Quantumult X 首页 → 「工具」→「BoxJs 订阅」也能可视化设置；全部可留空）：

| 键 | 说明 |
|----|------|
| `xijiu_account_name` | 通知里显示的账号名，默认 `iPhone` |
| `xijiu_bark_url` | Bark 完整 URL，如 `https://api.day.app/xxxxx`，脚本会主动 push |
| `xijiu_bark_key` | 只填 key 时用 `https://api.day.app/{key}` |
| `xijiu_webhook_url` | POST JSON `{name, access_token, ua, ts}` 到该地址（青龙 API / 自建服务） |
| `xijiu_webhook_token` | 上面 URL 的 `Authorization: Bearer` |

设置方法（任选其一）：
- Quantumult X → 「工具」→「运行脚本」→ 粘贴 `$prefs.setValueForKey("iPhone","xijiu_account_name")` 执行一次；
- 或者装 BoxJs（https://raw.githubusercontent.com/chavyleung/scripts/master/box/chavy.boxjs.json）里手动改。

**多账号（多微信）：** iPhone 上一次只登录一个微信，逐个切换微信号 → 打开签到页 → 通知触发；每次触发前先把 `xijiu_account_name` 改成对应账号名，或直接把 token 复制到 config 里同名账号的 `access_token`。

### 抓包重点接口

| 用途 | 域名 / 路径 |
|------|-------------|
| 酒谷换票 | `xcx.exijiu.com` … `/Member/getJwt`（头 `login_code`） |
| 酒谷签到 | `apimallwm.exijiu.com` `/garden/Sign/dailySign`（**S** 大写） |
| 土地 | `/garden/Sorghum/*`（**S** 大写） |
| 资产 | `/garden/Gardenmemberinfo/getMemberInfo` |
| **积分签到状态** | `fm.exijiu.com` `POST /api/customer/daily/checkTodaySignIn` |
| **积分签到** | `POST /api/customer/daily/fillSignIn` body `{code, channelCode:xj_mall_wx_applet}` |
| 奖励配置 | `POST /api/customer/daily/getRewards`（可无登录） |

路径大小写错误会假报「请从小程序重新进入」，**不是** login_code 失效。

## 青龙

**环境变量（账号）：**

```text
XIJIU_ACCOUNTS = [{"name":"主号","login_code":"xxx","access_token":"yyy"}]
```

或：

```text
XIJIU_LOGIN_CODE = code1&code2
XIJIU_ACCESS_TOKEN = token1&token2
XIJIU_NAME = 主号&备号
```

**可选：**

| 变量 | 说明 |
|------|------|
| `XIJIU_DO_SIGN=0` | 关积分签到 |
| `XIJIU_DO_GARDEN=0` | 关酒谷 |
| `XIJIU_EXCHANGE=1` | 开酒兑积分 |
| `XIJIU_OCR_SERVER` | 滑块 OCR，如 `http://ip:8000` |
| `BARK_URL` / `BARK_KEY` | 通知 |

## 日志示例

```text
📅 07-27 17:00

✅ 主号
   ✍️ 每日签到领积分：今日已签 ✅
   🌾 酒谷签到：今日已签 ✅
   🧩 酒谷验证：无需 / 已过
   💰 积分 5 · 酒 0 · 高粱 100 · 小麦 0 · 酒曲 10
   🪴 地块：1 块已处理
   📋 任务：完成约 3/4 项
```

## 酒谷滑块

每日酒谷可能要求滑块：

1. 配置 `ocr_server` → `POST /capcode`  
2. 或本机 `pip install ddddocr`  
3. **都不配：** 打日志并尽量继续；若接口强制验证则酒谷相关会失败  

## 说明

- **酒谷 JWT**（`Authorization`）与 **积分 accessToken**（`X-access-token`）是两套登录，互不通用  
- 手机 UI「今日已签到 +5积分」= `fm` 体系；酒谷资产里的「积分」字段也可能同步显示  
- 未解锁土地需要收酒量达标，脚本遇「无法开垦」会停止继续刷解锁  
