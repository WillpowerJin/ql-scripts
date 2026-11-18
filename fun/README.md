# FUN 矿池

基于社区脚本「FUN 自动爬墙」重写：登录 → 收矿 → 查状态 → 可选升级，**Bark 美化通知**。

**同一份 `mine.py`：** 电脑本地用 `config.yaml`，青龙用环境变量。

API：`https://exchange.acmes.dev/api/v1`  
注册（示例）：`https://mexchange.acmes.dev`（邀请码以平台为准）

> 仅供学习。平台与资产风险自负。

平台会识别登录设备。青龙 / 新电脑都属于「新设备」，**第一次必须用短信验证码绑定**；绑定后同一设备指纹可直接账密登录，定时任务不再要验证码。

本地和青龙的设备缓存是两份文件，**各绑一次**（两边各收一条短信）。

---

## 本地（电脑）

```bash
cd fun
pip install -r requirements.txt
cp config.example.yaml config.yaml
# 编辑 mobile / password
python3 mine.py
```

首次新设备：

```bash
python3 mine.py                  # 触发短信
python3 mine.py --captcha 123456 # 立刻用验证码再跑
# 绑定成功后不要再带 --captcha
```

也可把验证码临时写进 `config.yaml` 该账号的 `captcha`，跑通后删掉。

指定配置文件：

```bash
python3 mine.py -c /path/to/config.yaml
```

本地设备缓存默认 `fun/device_cache.json`（已 gitignore，不要提交）。

`config.yaml` 示例见 `config.example.yaml`。Bark 可写在 `notify:` 段，也可用环境变量 `BARK_KEY` / `BARK_URL`（与仓库其它项目共用）。

---

## 青龙

### 订阅

白名单加上 **`fun`**：

```text
hifiti|xijiu|quark|bilibili|fanghua|bafu|fun|tuiguangbao|aliyun_dev|kuailefeng
```

会拉到：`fun/mine.py`

### 依赖

```text
requests
```

本地 yaml 才需要 PyYAML；青龙只用环境变量时不必装。

### 环境变量

**账号 `FUN`（必填）**

```text
手机号#密码#收矿#升级
手机号#密码#收矿#升级#备注
手机号#密码#收矿#升级#备注#短信验证码
```

| 段 | 含义 | 建议 |
|----|------|------|
| 收矿 | `1` 开 / `0` 关 | 新手 **1** |
| 升级 | `1` 开 / `0` 关 | 新手 **0**（避免乱花币） |
| 备注 | 可选，如 iPhone | 进日志和 Bark |
| 短信验证码 | 可选第 6 段 | 仅首次绑定用，成功后删掉 |

多账号用 `&` 或换行：

```text
FUN=13800138000#pass#1#0#iPhone&13900139000#pass#1#0#Android
```

**首次绑定（必做一次）：**

1. 更新订阅后，先**手动运行**一次 `FUN矿池`
2. 日志出现 `新设备需短信验证码`，手机会收到短信（登录接口自动发，不必另调短信接口）
3. 青龙新增环境变量（验证码几分钟内过期，马上做第 4 步）：

```text
FUN_CAPTCHA=123456
```

也可写在账号第 6 段：`手机号#密码#1#0#备注#123456`

4. **立刻再运行一次**本任务
5. 日志出现 `设备已绑定` 后，**删掉 `FUN_CAPTCHA`（以及第 6 段验证码）**
6. 之后每天定时即可，不要再填验证码

绑定缓存写在青龙 **`/ql/data/fun_device_cache.json`**（订阅更新不会覆盖）。删掉这个文件 = 设备丢失，会再要一次短信。

若青龙里同时有环境变量 `FUN` 和脚本目录下的 `config.yaml`，**以环境变量为准**。

**全局备注（标题）：**

```text
FUN_NOTE=家里青龙
```

**Bark（与其它项目共用）：**

```text
BARK_KEY=你的Key
# 或 BARK_URL=https://api.day.app/你的Key/
```

可选：

| 变量 | 说明 |
|------|------|
| `FUN_BASE_URL` | 默认官方 API |
| `FUN_CAPTCHA` / `FUN_SMS` | 本轮短信验证码，绑定成功后删除 |
| `FUN_DEVICE_CACHE` | 设备缓存路径；青龙默认 `/ql/data/fun_device_cache.json` |

### 定时

| 名称 | 命令 | cron |
|------|------|------|
| FUN矿池 | `python3 -u .../fun/mine.py` | `10 8 * * *` |

首次绑定请**手动运行**，不要干等第二天定时。

---

## 配置优先级

1. `python3 mine.py -c 某文件.yaml` → 只用该文件（Bark 等仍可被环境变量覆盖）
2. 已设置环境变量 `FUN` → 青龙模式，忽略旁边的 `config.yaml`
3. 否则读 `fun/config.yaml`

## Bark 示例

```text
⛏️ FUN 矿池 · 任务汇总
🏷️ 备注：家里青龙
📅 07-31 15:30
────────────────

⛏️ 【iPhone】
   📱 138****2453
   🏭 矿机：LV1
   💰 余额：16.05 FU
   💎 可领：0
   📈 日产：2.8
   ⬆️ 升级费：13
   💰 收矿：暂无可领取 ℹ️
   🚀 升级：已关闭 ⏭️

────────────────
📦 账号 1 · ✅1  ❌0
🎉 全部顺利
```

新设备未绑定时，Bark 会提示填验证码后立刻再跑一次。

## 文件

```text
fun/
  mine.py
  config.example.yaml
  requirements.txt
  README.md
```

设备缓存（不进仓库）：青龙 `/ql/data/fun_device_cache.json`，本地 `fun/device_cache.json`  
账号配置（不进仓库）：本地 `fun/config.yaml`
