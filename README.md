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
| [wangchao](./wangchao/) | `read_gift.py` | 望潮「阅读有礼」：多号自动阅读；**默认仅第 1 号自动抽奖** | [说明](./wangchao/README.md) |
| [xijiu](./xijiu/) | `daily.py` | 习酒君品荟：积分相关 + 文旅酒谷（种养/任务等） | [说明](./xijiu/README.md) |
| [quark](./quark/) | `quark_checkin.py` | 夸克网盘每日签到领空间（需抓包参数） | [说明](./quark/README.md) |
| [bilibili](./bilibili/) | `get_cookie.py` + `daily.py` | B 站：扫码获取 Cookie + 每日经验任务（无需 App 抓包） | [说明](./bilibili/README.md) |
| [fanghua](./fanghua/) | `main.py` | 芳华未来：手机号密码登录 + 签到/刷视频挂机 | [说明](./fanghua/README.md) |

### 入口与定时建议

| 脚本 | 青龙任务建议 | 备注 |
|------|----------------|------|
| `hifiti/checkin.py` | 每天定时 | 环境变量见子目录 README |
| `wangchao/read_gift.py` | 每天定时 | 多号抽奖策略见文档 |
| `xijiu/daily.py` | 每天定时 | `pull_access_token.py` 仅本地 root 安卓用，订阅已排除 |
| `quark/quark_checkin.py` | 每天定时 | `COOKIE_QUARK` 等 |
| `bilibili/get_cookie.py` | **手动**（Cookie 失效时） | 手机 B 站扫码 |
| `bilibili/daily.py` | 每天定时 | 依赖扫码缓存的 Cookie |
| `fanghua/main.py` | 每天定时 | 单号默认最长约 2h，任务超时请调大 |

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
白名单：   hifiti|wangchao|xijiu|quark|bilibili|fanghua
黑名单：   pull_access_token
扩展名：   py
定时规则： 30 8 * * *
```

**只复制黑名单（不要加 crypto_api，否则芳华 main 会缺文件）：**

```text
pull_access_token
```

**只复制白名单：**

```text
hifiti|wangchao|xijiu|quark|bilibili|fanghua
```

| 字段 | 说明 |
|------|------|
| 链接 | 只要 git 地址；不要填 README 网页，也不要整段 `ql repo ...` |
| 白名单 | 用**目录名**，一次拉齐该目录下入口脚本 |
| 黑名单 | 仅 `pull_access_token`（习酒本地抠 token）。**不要**把 `crypto_api` 写进黑名单——那是芳华库文件，黑了会不下载，`main.py` 直接报错 |
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
ql repo https://github.com/WillpowerJin/ql-scripts.git "hifiti|wangchao|xijiu|quark|bilibili|fanghua" "pull_access_token" "" "main" "py"
```

拉取成功后，脚本管理中应类似：

```text
…/hifiti/checkin.py
…/wangchao/read_gift.py
…/xijiu/daily.py
…/quark/quark_checkin.py
…/bilibili/daily.py
…/bilibili/get_cookie.py
…/fanghua/main.py
…/fanghua/crypto_api.py      ← 库文件，若自动生成任务请「禁用」勿删
```

不应把 `pull_access_token.py` 建成任务（黑名单已排除）。

### 公共通知（Bark）

多数脚本共用：

- `BARK_URL` 完整推送地址，或  
- `BARK_KEY` + 可选 `BARK_SERVER`  

细节见 [hifiti/README.md](./hifiti/README.md)、[wangchao/README.md](./wangchao/README.md)。

---

## 目录结构（与 main 分支一致）

```text
.
├── README.md                 # 本页
├── hifiti/
│   ├── checkin.py
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── README.md
├── wangchao/
│   ├── read_gift.py
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
│   ├── daily.py              # 每日任务（定时）
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── README.md
└── fanghua/
    ├── main.py               # 芳华未来挂机入口
    ├── crypto_api.py         # 加解密 / API
    ├── config.example.yaml
    ├── requirements.txt
    └── README.md
```

---

## 本地开发

```bash
git clone https://github.com/WillpowerJin/ql-scripts.git
cd ql-scripts

# 示例：B 站
cd bilibili
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python get_cookie.py          # 扫码
python daily.py               # 任务

# 示例：望潮
cd ../wangchao
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填写后勿提交
python read_gift.py --dry-run
```

`config.yaml`、Cookie 缓存等已在 `.gitignore` 中忽略。

---

## License

仅供学习交流，请遵守目标网站 / App 服务条款与当地法律法规。
