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

### 入口与定时建议

| 脚本 | 青龙任务建议 | 备注 |
|------|----------------|------|
| `hifiti/checkin.py` | 每天定时 | 环境变量见子目录 README |
| `wangchao/read_gift.py` | 每天定时 | 多号抽奖策略见文档 |
| `xijiu/daily.py` | 每天定时 | `pull_access_token.py` 仅本地 root 安卓用，订阅已排除 |
| `quark/quark_checkin.py` | 每天定时 | `COOKIE_QUARK` 等 |
| `bilibili/get_cookie.py` | **手动**（Cookie 失效时） | 手机 B 站扫码 |
| `bilibili/daily.py` | 每天定时 | 依赖扫码缓存的 Cookie |

---

## 青龙订阅

### 面板填写

青龙 → **订阅管理** → **创建订阅**：

| 字段 | 填写 |
|------|------|
| 名称 | `ql-scripts`（随意） |
| 类型 | 公开仓库 |
| 链接 | `https://github.com/WillpowerJin/ql-scripts.git` |
| 分支 | `main` |
| **白名单** | `checkin\|read_gift\|xijiu\|quark\|bilibili` |
| **黑名单** | `README\|config\|example\|requirements\|pull_access_token\|cookie_cache\|login_qr\|quantumultx\|\.md\|\.yaml\|\.yml\|\.txt\|\.js\|\.conf` |
| 扩展名 | `py` |
| 定时规则 | 仅控制「自动拉库」，例如 `30 8 * * *`（不是各个业务任务的 cron） |

说明：

- **白名单**：路径包含关键字即拉取，多个用 `\|` 分隔。  
- **黑名单**：跳过文档、示例配置、本地专用脚本与 Cookie 缓存文件名。  
- 改完白名单/黑名单后需 **保存再运行** 订阅；只点运行不会自动读本 README。

### 命令行等价

```bash
ql repo https://github.com/WillpowerJin/ql-scripts.git \
  "checkin|read_gift|xijiu|quark|bilibili" \
  "README|config|example|requirements|pull_access_token|cookie_cache|login_qr|quantumultx|\.md|\.yaml|\.yml|\.txt|\.js|\.conf" \
  "" "main" "py"
```

拉取成功后，脚本管理中大致可见：

```text
…/hifiti/checkin.py
…/wangchao/read_gift.py
…/xijiu/daily.py
…/quark/quark_checkin.py
…/bilibili/daily.py
…/bilibili/get_cookie.py
```

不应出现：`pull_access_token.py`、各类 `README.md`、`config.example.yaml`。

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
└── bilibili/
    ├── get_cookie.py         # 扫码拿 Cookie（手动）
    ├── daily.py              # 每日任务（定时）
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
