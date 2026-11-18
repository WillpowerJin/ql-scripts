# 青龙脚本集合

个人维护的 [青龙面板](https://github.com/whyour/qinglong) 订阅脚本。

- 文档在各子目录 `README.md`；**订阅时建议用黑名单跳过说明文档**，只拉 `.py`。
- 账号、Cookie、密码、Bark 等**不要写进仓库**，请用青龙「环境变量」或本地不提交的 `config.yaml`。

仓库地址：<https://github.com/WillpowerJin/ql-scripts>

---

## 脚本列表（仓库已发布）

仅列出 **GitHub 上已推送** 的目录。本地未提交的工程不会出现在下表，避免死链。

| 目录 | 入口脚本 | 说明 | 文档 |
|------|----------|------|------|
| [hifiti](./hifiti/) | `checkin.py` | [HiFiNi 音乐磁场](https://www.hifiti.com/) 每日签到（Cookie 优先，失效可密码重登） | [说明](./hifiti/README.md) |
| [xijiu](./xijiu/) | `daily.py` | 习酒君品荟：积分相关 + 文旅酒谷（种养/任务等） | [说明](./xijiu/README.md) |
| [quark](./quark/) | `quark_checkin.py` | 夸克网盘每日签到领空间（需抓包参数） | [说明](./quark/README.md) |
| [bilibili](./bilibili/) | `get_cookie.py` + `daily.py` | B 站：扫码拿 Cookie + 每日任务（**默认不投币，保硬币**） | [说明](./bilibili/README.md) |
| [fanghua](./fanghua/) | `main.py` | 芳华未来：手机号密码登录 + 签到/刷视频挂机 | [说明](./fanghua/README.md) |
| [fun](./fun/) | `mine.py` | FUN 矿池：登录收矿/可选升级 + Bark（本地 `config.yaml` 或青龙 `FUN`；首次新设备短信绑定） | [说明](./fun/README.md) |
| [tuiguangbao](./tuiguangbao/) | `daily.py` | 推广宝：登录看广告领奖（对齐 2.5 + Bark） | [说明](./tuiguangbao/README.md) |
| [aliyun_dev](./aliyun_dev/) | `daily.py` | 阿里云开发者社区：签到/互动/领积分（支持账密或 Cookie） | [说明](./aliyun_dev/README.md) |
| [kuailefeng](./kuailefeng/) | `daily.py` | 快乐蜂：手机号密码登录 + 免费/转盘抽奖（`/check` 自适应）+ Bark | [说明](./kuailefeng/README.md) |
| [dianxin](./dianxin/) | `daily.py` | 电信 AI 奇遇：账密登录 + 创作任务攒积分换话费/抽奖 + Bark | [说明](./dianxin/README.md) |
| [jinpinghu](./jinpinghu/) | `daily.py` | 今平湖：帐密登录 + 阅读任务 + 自动抽奖（多账号隔离，滑块支持 cv2/ddddocr/外部 OCR） | [说明](./jinpinghu/README.md) |
| [tianyi](./tianyi/) | `daily.py` | 电信营业厅：签到 + 金豆任务 + 宠物喂养 + 金豆转盘（手机号/服务密码/AndroidID） | [说明](./tianyi/README.md) |
| [huazhu](./huazhu/) | `daily.py` | 华住会：userToken 每日签到 + 积分/连签查询（Bark / PushPlus / 青龙通知） | [说明](./huazhu/README.md) |
| [ikea](./ikea/) | `daily.py` | 宜家家居：IKEA Token 每日签到（可选 `pull_token.py` 手机提取 Token） | [说明](./ikea/README.md) |
| [sfsy](./sfsy/) | `daily.py` | 顺丰速运：APP/小程序签到 + 积分任务 + 生活特权（积分页 Cookie） | [说明](./sfsy/README.md) |
| [shangjinlianmeng](./shangjinlianmeng/) | `赏金联盟自动看广.py` | 赏金联盟：每账号每日 3 次广告上报（`SJLM=账号#密码`） | [说明](./shangjinlianmeng/README.md) |

### 入口与定时建议

| 脚本 | 青龙任务建议 | 备注 |
|------|----------------|------|
| `hifiti/checkin.py` | 每天定时 | 环境变量见子目录 README |
| `xijiu/daily.py` | 每天定时 | `pull_access_token.py` 仅本地 root 安卓用，订阅已排除 |
| `quark/quark_checkin.py` | 每天定时 | `COOKIE_QUARK` 等 |
| `bilibili/get_cookie.py` | **手动**（Cookie 失效时） | 手机 B 站扫码 |
| `bilibili/daily.py` | 每天定时 | 依赖扫码缓存的 Cookie |
| `fanghua/main.py` | 每天定时 | 单号默认最长约 2h，任务超时请调大 |
| `fun/mine.py` | 每天定时 | 青龙 `FUN` / 本地 `config.yaml`；**首次新设备要短信绑定**（`FUN_CAPTCHA` 或 `--captcha`），之后定时即可；收矿开、升级建议先关 |
| `tuiguangbao/daily.py` | 每天定时 `0 9 * * *` | 环境变量 `TGB` 或 `TGB_ACCOUNTS`；超时建议 ≥15～20min |
| `aliyun_dev/daily.py` | 每天 **两次** `0 7,13 * * *`（都跑完整版） | Cookie：`aliyunWeb_data` / `ALIYUN_ACCOUNTS`；含领待收积分；超时 ≥15min |
| `kuailefeng/daily.py` | 每天定时 `0 9 * * *` | `KLF_ACCOUNTS` 或 `KLF=手机号#密码`；间隔默认随机 5–8s |
| `dianxin/daily.py` | 每 6 小时 `0 */6 * * *` | `DIANXIN=手机号#密码[#AndroidID][#备注]`；首次建议 `DIANXIN_MODE=observe` 试跑 |
| `jinpinghu/daily.py` | 每天定时 `5 9 * * *`（任务集 09:00 刷新） | `JPH=手机号#密码`（多账号 `&`）；首次先在 App 重置密码并绑定提现微信；滑块默认 cv2，也可 `JPH_OCR=remote` |
| `tianyi/daily.py` | 每天定时 `30 8 * * *` | `chinaTelecomAccount=手机号#服务密码#AndroidID[#备注]` 或 `TIANYI_ACCOUNTS`；直播任务较久，超时建议 ≥20min |
| `huazhu/daily.py` | 每天定时 `15 8 * * *` | `HZ_TOKEN=userToken`（多账号 `&`）；首次抓包获取 userToken |
| `ikea/daily.py` | 每天定时 `20 8 * * *` | `IKEA_TOKEN=JWT`（多账号 `&`）；`pull_token.py` 仅本地用，订阅黑名单排除 |
| `sfsy/daily.py` | 每天定时 `0 8 * * *` | `sfsyUrl` / `SFSY_COOKIE` / `SFSY_ACCOUNTS`；Cookie 失效需重新抓积分页 |
| `shangjinlianmeng/赏金联盟自动看广.py` | 每天定时 `0 9 * * *` | `SJLM=账号#密码[#账号#密码]`；每账号 3 次广告，间隔 20s |

---

## 青龙订阅

### 面板怎么填（复制下面代码块，不要带 `\`）

青龙 → **订阅管理** → **创建订阅**。

青龙的白/黑名单规则是：**路径字符串是否包含关键字**（多个用英文竖线分隔），**不是正则**。  
因此不要写 `\.md`，也不要把 Markdown 表格里的 `\|` 原样粘进去。

```text
名称：     ql-scripts
类型：     公开仓库
链接：     https://github.com/WillpowerJin/ql-scripts.git
分支：     main
白名单：   hifiti|xijiu|quark|bilibili|fanghua|fun|tuiguangbao|aliyun_dev|kuailefeng|dianxin|jinpinghu|tianyi|huazhu|ikea|sfsy|shangjinlianmeng
黑名单：   pull_access_token|pull_token
扩展名：   py
定时规则： 30 8 * * *
```

**只复制黑名单（不要加 crypto_api，否则芳华 main 会缺文件）：**

```text
pull_access_token|pull_token
```

**只复制白名单：**

```text
hifiti|xijiu|quark|bilibili|fanghua|fun|tuiguangbao|aliyun_dev|kuailefeng|dianxin|jinpinghu|tianyi|huazhu|ikea|sfsy|shangjinlianmeng
```

| 字段 | 说明 |
|------|------|
| 链接 | 只要 git 地址；不要填 README 网页，也不要整段 `ql repo ...` |
| 白名单 | 用**目录名**，一次拉齐该目录下入口脚本 |
| 黑名单 | `pull_access_token`（习酒本地抠 token）、`pull_token`（宜家本地抓 Token）。**不要**把 `crypto_api` 写进黑名单——那是芳华库文件，黑了会不下载，`main.py` 直接报错 |
| 扩展名 | 填 `py` |
| 定时 | 只控制「自动拉库」 |

改完后：**保存 → 再点运行**订阅。

芳华会拉到两个 `.py`：`main.py`（任务入口）+ `crypto_api.py`（库）。若青龙自动给 `crypto_api` 建了定时任务，**禁用即可，不要从脚本目录删文件**。

若直连 GitHub 失败，链接可改用镜像（按你环境可用的为准），例如：

```text
https://ghfast.top/https://github.com/WillpowerJin/ql-scripts.git
```

### 命令行等价

在青龙容器内：

```bash
ql repo https://github.com/WillpowerJin/ql-scripts.git "hifiti|xijiu|quark|bilibili|fanghua|fun|tuiguangbao|aliyun_dev|kuailefeng|dianxin|jinpinghu|tianyi|huazhu|ikea|sfsy|shangjinlianmeng" "pull_access_token|pull_token" "" "main" "py"
```

拉取成功后，脚本管理中应类似：

```text
…/hifiti/checkin.py
…/xijiu/daily.py
…/quark/quark_checkin.py
…/bilibili/daily.py
…/bilibili/get_cookie.py
…/fanghua/main.py
…/fanghua/crypto_api.py      ← 库文件，若自动生成任务请「禁用」勿删
…/fun/mine.py
…/tuiguangbao/daily.py       ← 推广宝任务入口
…/aliyun_dev/daily.py        ← 阿里云开发者社区
…/kuailefeng/daily.py        ← 快乐蜂抽奖
…/dianxin/daily.py          ← 电信 AI 奇遇
…/jinpinghu/daily.py        ← 今平湖阅读红包
…/tianyi/daily.py           ← 电信营业厅签到/金豆/转盘
…/huazhu/daily.py           ← 华住会签到
…/ikea/daily.py             ← 宜家签到
…/sfsy/daily.py             ← 顺丰速运积分任务
…/shangjinlianmeng/赏金联盟自动看广.py  ← 赏金联盟广告上报
```

不应把 `pull_access_token.py` / `pull_token.py` 建成任务（黑名单已排除）。

### 公共通知（Bark）

多数脚本共用：

- `BARK_URL` 完整推送地址，或  
- `BARK_KEY` + 可选 `BARK_SERVER`  

细节见 [hifiti/README.md](./hifiti/README.md)、[kuailefeng/README.md](./kuailefeng/README.md)。

---

## 目录结构（与 main 分支一致）

```text
.
├── README.md                 # 本页
├── requirements.txt          # 本地开发：根虚拟环境依赖汇总
├── .venv/                    # 本地开发用（不进 git）
├── hifiti/
│   ├── checkin.py
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── README.md
├── xijiu/
│   ├── daily.py
│   ├── pull_access_token.py  # 本地用；订阅黑名单可排除
│   ├── config.example.yaml
│   ├── requirements.txt
│   ├── quantumultx/          # 可选 QX 辅助，默认黑名单不拉
│   └── README.md
├── quark/
│   ├── quark_checkin.py
│   ├── config.example.yaml
│   ├── requirements.txt
│   ├── quantumultx/
│   └── README.md
├── bilibili/
│   ├── get_cookie.py         # 扫码拿 Cookie（手动）
│   ├── daily.py              # 每日任务（定时，默认不投币）
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── README.md
├── fanghua/
│   ├── main.py               # 芳华未来挂机入口
│   ├── crypto_api.py         # 加解密 / API
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── README.md
├── fun/
│   ├── mine.py               # FUN 矿池收矿/升级 + Bark
│   ├── config.example.yaml   # 本地复制为 config.yaml
│   ├── requirements.txt
│   └── README.md
├── tuiguangbao/
│   ├── daily.py              # 推广宝每日看广告领奖
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── README.md
├── aliyun_dev/
│   ├── daily.py              # 阿里云开发者社区日常
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── README.md
├── kuailefeng/
│   ├── daily.py              # 快乐蜂转盘抽奖（账密登录 + /check 自适应）
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── README.md
├── dianxin/
│   ├── daily.py              # 电信 AI 奇遇（创作积分换话费/抽奖）
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── README.md
├── tianyi/
│   ├── daily.py              # 电信营业厅签到 + 金豆任务 + 宠物 + 转盘
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── README.md
├── huazhu/
│   ├── daily.py              # 华住会签到（userToken）
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── README.md
├── ikea/
│   ├── daily.py              # 宜家签到（IKEA Token）
│   ├── pull_token.py         # 本地抓 Token；订阅黑名单可排除
│   ├── config.example.yaml
│   ├── requirements.txt
│   ├── quantumultx/
│   └── README.md
├── sfsy/
│   ├── daily.py              # 顺丰速运积分任务（积分页 Cookie）
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── README.md
├── shangjinlianmeng/
│   ├── 赏金联盟自动看广.py   # 广告上报入口
│   ├── requirements.txt
│   └── README.md
└── jinpinghu/
    ├── daily.py              # 今平湖阅读红包（阅读任务 + 自动抽奖）
    ├── config.example.yaml
    ├── requirements.txt
    └── README.md
```

---

## 本地开发

本仓库是多脚本 monorepo，**推荐在仓库根目录共用一个虚拟环境**（各子目录 `requirements.txt` 仍保留作清单）。

```bash
git clone https://github.com/WillpowerJin/ql-scripts.git
cd ql-scripts

# 创建根 venv 并安装全部本地依赖（推荐用 uv；也可用 python3 -m venv）
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
# 或：python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

source .venv/bin/activate

# 示例：B 站
cd bilibili
python get_cookie.py          # 扫码
python daily.py               # 任务

# 示例：快乐蜂
cd ../kuailefeng
cp config.example.yaml config.yaml   # 填写后勿提交
python daily.py --dry-run
```

青龙面板侧仍按各脚本文档用系统/容器环境安装依赖，不必使用本机的根 `.venv`。

`config.yaml`、Cookie 缓存、`.venv/` 等已在 `.gitignore` 中忽略。

---

## License

仅供学习交流，请遵守目标网站 / App 服务条款与当地法律法规。
