# 京东每日签到（京豆）

把**目前（2026-10）网上仍可查证、真实在跑**的京东签到任务转写为 Python。
任务流程逐行对齐两个仍在维护的来源：

- [LazingLuo/LazingLuo_Loon-Rules](https://github.com/LazingLuo/LazingLuo_Loon-Rules)（iOS Loon 脚本，**可读源码**，2026-10-31 仍在更新）——任务接口、参数、判定逻辑的来源
- [cyuni1996/jdpro](https://github.com/cyuni1996/jdpro)（青龙 Node 脚本维护版）——其[逐日维护日志](https://github.com/cyuni1996/jdpro/blob/main/docs/maintenance.md)证实：2026-10 上旬「天天领豆」「hs/ys 每日签到」「积分签到」等签到任务在真实定时运行中**持续领取成功**（1 京豆/次）

> 调研中排除的方案：网上大量 2021–2023 年的「20 行 Python 调 `signBeanAct`」教程
> （含 GitHub 上最新的 [Monster-XTF/jd-sign](https://github.com/Monster-XTF/jd-sign)）
> 调用的老签到接口已被风控接管——jdpro 维护日志 2026-10-12 实测该接口持续返回
> `code 1714002 排队中`，**已不可用**。农场/种豆/汪汪等完整任务生态依赖混淆 Node
> 脚本与动态 h5st 环境，不适合忠实转写为 Python，想要全量任务请直接用
> [青龙面板](https://github.com/whyour/qinglong) + jdpro（Node.js）。

## 任务清单

| 任务 | 说明 | 签名 | 接口 |
|------|------|------|------|
| `hs` / `ys` | 健康系每日签到（约 1 京豆/天/个） | 无 | `jdh_bm_getKitTask` / `jdh_msoa_doTaskGw` |
| `delivery` | 天天领豆（活动 2775/5358，签到+连签奖励） | h5st | `bean_deliverySign_home/sign/continue_award` |
| `game` | 互动游戏签到 | h5st | `weGameHome` / `weGameLottery` |
| `jxzy` | 京喜签到（京豆+优惠券） | claim 需 h5st | `jxzy_active_querySign` / `jxzy_active_drawSign` |
| `home` | 家电家居签到 | 同上 | 同上（不同 craftId） |
| `index` | 京东指数签到 | 同上 | 同上（不同 craftId） |

每天合计大约 3–6 京豆（几分钱），别指望发财，胜在全自动。

## h5st 签名怎么实现的

`h5st` 是京东 H5 接口的风控签名。本项目不逆向它，而是：

1. 用 Python 内嵌的 [quickjs](https://pypi.org/project/quickjs/) 引擎补一份浏览器环境
   （navigator / document / localStorage / XMLHttpRequest …）；
2. 在沙箱里运行**京东官方 SDK**（`vendor/js_security_v3_lite_0.1.5.js`，
   来自京东 CDN `storage.360buyimg.com`，即每个京东 H5 页面加载的同一份文件）；
3. SDK 初始化时只被允许访问京东官方 `https://cactus.jd.com/request_algo`
   （算法 bootstrap，**不携带 Cookie**），之后 `signSync()` 纯本地出签名。

设备指纹（fp）通过 `.sdk_storage.json` 持久化，同一账号跨天表现为同一台
"手机"，降低风控概率。首次运行会调用一次 `request_algo`，属于京东网页的
正常加载行为。

## 依赖安装

```bash
cd jd
pip install -r requirements.txt        # requests / PyYAML / quickjs
# 若系统 Python 受 PEP 668 限制，用 uv：
# uv venv .venv && uv pip install -p .venv/bin/python -r requirements.txt
```

## 配置

### 1. 拿 Cookie（约 30 天有效，失效要重取）

1. 电脑浏览器打开 [www.jd.com](https://www.jd.com) 并登录；
2. `F12` → 应用(Application) → Cookies → `https://www.jd.com`；
3. 复制 `pt_key` 和 `pt_pin` 两项；
4. **直接关掉浏览器，不要点退出登录**（退出会让 pt_key 立即失效）。

> 也可以手机开飞行模式抓 m.jd.com，但浏览器方式最省事。

### 2. 二选一填入

**青龙 / 环境变量方式（推荐，与仓库其他脚本一致）：**

```bash
export JD_COOKIE='pt_key=AAJxxxx;pt_pin=jd_xxxxx;'
# 多账号用 & 或换行分隔
```

**本地配置文件方式：**

```bash
cp config.example.yaml config.yaml   # 然后编辑 config.yaml 填入 cookies
```

`config.yaml` 里还能开关任务、调整任务间隔、`eid_token`（可选，一般留空）。

## 运行

```bash
python3 jd_sign.py                # 跑全部启用的任务
python3 jd_sign.py hs ys          # 只跑指定任务
python3 jd_sign.py --tasks hs,ys,delivery
```

签名器自检（不碰业务接口，只验证 h5st 能生成）：

```bash
python3 h5st.py
```

### 定时

- 本机 cron：`30 8 * * * cd /path/to/scripts/jd && /usr/bin/python3 jd_sign.py >> jd.log 2>&1`
- 通知（可选，与 huazhu / kuailefeng 等项目一致）：
  - 青龙面板内运行优先走**青龙统一通知**（自动检测 `notify.py`）；
  - **Bark**：`config.yaml` 的 `bark:` 段，或环境变量 `BARK_KEY` / `BARK_URL` / `BARK_SERVER` / `BARK_GROUP` / `BARK_SOUND` / `BARK_ICON` / `BARK_LEVEL`；
  - **PushPlus**：`pushplus:` 段，或 `PUSHPLUS_TOKEN` / `PUSHPLUS_TOPIC`。

### 青龙面板

1. **镜像选择**：`quickjs` 没有 musllinux 预编译包——
   - **Debian 镜像**（`whyour/qinglong:debian`，推荐）：依赖管理直接装 Python 依赖即可；
   - **Alpine 镜像**（默认 tag）：需先在「依赖管理 → Linux」安装 `build-base`、`python3-dev`，
     quickjs 会从源码编译（一次性，几分钟）。
2. **依赖管理 → Python3**：添加 `requests`、`PyYAML`、`quickjs`。
3. **订阅**拉取本仓库（README 根目录的订阅配置白名单已含 `jd`）；若订阅只同步了
   py 文件，首次运行时脚本会自动从京东 CDN 补齐 `vendor/` 里的签名 SDK。
4. **环境变量**：`JD_COOKIE` = `pt_key=xxx;pt_pin=xxx;`（多账号用 `&` 或换行分隔）。
5. **定时任务**：命令 `task jd/jd_sign.py`，定时 `30 8 * * *`（避开整点）。
6. 状态文件（设备指纹 `.sdk_storage.json` 等）写在脚本目录，订阅更新不会清除。

## 状态文件（都在 jd/ 下，已加入 .gitignore）

| 文件 | 作用 |
|------|------|
| `.sdk_storage.json` | 签名 SDK 的 localStorage（设备指纹），删了等于换新设备 |
| `.jd_device.json` | 每个账号固定的 UA / uuid |
| `.jd_journal.json` | 当日提交记录，防止重复领取 |

## 诚实声明

- 签到接口由京东控制，任何时候都可能改参数或加强风控。任务返回的
  `code` / `bizCode` 非 0 时脚本会原样报错，不会假装成功。
- hs/ys/delivery 三个任务有 2026-10 的真实成功日志佐证；jxzy/home/index
  流程与可读源码逐行一致，但京东 App 端会额外携带 `x-api-eid-token`，
  留空时若被拒可在 config.yaml 里抓包补填。
- 频繁自动化有账号风控风险，低调使用，后果自负。
