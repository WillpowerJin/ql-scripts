# 青龙脚本集合

个人维护的青龙面板订阅脚本。文档与配置说明在各子目录中查看；**订阅时只拉取脚本文件**，不把说明文档同步进青龙。

## 脚本列表

| 脚本 | 说明 | 文档 |
|------|------|------|
| [hifiti](./hifiti/) | [HiFiNi 音乐磁场](https://www.hifiti.com/) 自动签到（Cookie 优先，失效可密码重登） | [使用说明 →](./hifiti/README.md) |
| [wangchao](./wangchao/) | 望潮「阅读有礼」：多号自动阅读 12 篇；**默认仅第 1 号自动抽奖**，其余号请 App 手动抽 | [使用说明 →](./wangchao/README.md) |
| [xijiu](./xijiu/) | 习酒君品荟小程序：签到有礼 + 文旅酒谷（种养/任务/制酒） | [使用说明 →](./xijiu/README.md) |
| [fanghua](./fanghua/) | 芳华未来 App：手机号密码登录 + 签到/刷视频领芳华币 | [使用说明 →](./fanghua/README.md) |
| [bafu](./bafu/) | 八富生活：手机号密码登录 + 自动看广告 | [使用说明 →](./bafu/README.md) |
| [quark](./quark/) | 夸克网盘：每日签到领取免费存储容量（移动端接口） | [使用说明 →](./quark/README.md) |
| [ninebot](./ninebot/) | 九号出行 App：手机号密码登录 + 签到/任务领 N 币（接口待接入） | [使用说明 →](./ninebot/README.md) |
| [bilibili](./bilibili/) | B 站：扫码获取 Cookie（`get_cookie.py`）+ 每日任务（`daily.py`，无需 App 抓包） | [使用说明 →](./bilibili/README.md) |

后续新脚本会以同级目录形式增加，并在本表登记。

## 青龙订阅

### 新建订阅（推荐按面板字段填写）

青龙 → **订阅管理** → **创建订阅**：

| 字段 | 填写 |
|------|------|
| 名称 | `ql-scripts`（随意） |
| 类型 | 公开仓库 |
| 链接 | `https://github.com/WillpowerJin/ql-scripts.git` |
| 分支 | `main` |
| **白名单** | `checkin\|read_gift\|xijiu\|bilibili` |
| **黑名单** | `README\|config\|example\|requirements\|pull_access_token\|cookie_cache\|login_qr\|\.md\|\.yaml\|\.yml\|\.txt` |
| 扩展名 | `py` |
| 定时规则 | 按需，例如 `30 8 * * *`（仅自动拉库，不是跑任务） |

> **白名单**需包含 `read_gift`、`xijiu` 等关键字，否则对应子目录不会被拉。  
> 白名单匹配的是**路径里是否包含关键字**，多个用 `\|` 分隔。  
> **黑名单**含 `pull_access_token`：该文件只给本地 root 安卓抠 token 用，青龙不需要。

### 已有订阅（只点「运行」不够）

若你以前是按旧文档只填了白名单 `checkin`：

1. 打开该订阅 → **编辑**
2. 把白名单改成：`checkin|read_gift|xijiu|bilibili`
3. 黑名单补上 `pull_access_token`（与下文一致）
4. **保存**后再点运行

只点「运行」会沿用旧参数，**不会**自动读本仓库 README，也**不会**自动加上新脚本。

### 命令行等价写法

```bash
ql repo https://github.com/WillpowerJin/ql-scripts.git "checkin|read_gift|xijiu|bilibili" "README|config|example|requirements|pull_access_token|cookie_cache|login_qr|\.md|\.yaml|\.yml|\.txt" "" "main" "py"
```

参数含义：

| 位置 | 含义 | 本仓库取值 |
|------|------|------------|
| 1 | 仓库地址 | 见上 |
| 2 | 白名单（路径包含即拉取） | `checkin\|read_gift\|xijiu\|bilibili` |
| 3 | 黑名单（路径包含则跳过） | 文档/配置 + `pull_access_token` + cookie 缓存 |
| 4 | 依赖文件 | 空 |
| 5 | 分支 | `main` |
| 6 | 扩展名 | `py` |

拉取成功后，脚本管理中应能看到类似：

```text
…/hifiti/checkin.py
…/wangchao/read_gift.py
…/xijiu/daily.py
…/bilibili/daily.py
…/bilibili/get_cookie.py
```

（不应出现 `pull_access_token.py`。）

账号、Cookie、密码、Bark 等**不要写进仓库**，在青龙「环境变量」中配置。  
Bark 与各脚本共用：`BARK_URL` 或 `BARK_KEY`（见 [hifiti](./hifiti/README.md)、[wangchao](./wangchao/README.md)）。

## 目录结构

```text
.
├── README.md              # 本页：总览与订阅方式
├── hifiti/
│   ├── README.md
│   ├── checkin.py
│   ├── config.example.yaml
│   └── requirements.txt
└── wangchao/
    ├── README.md
    ├── read_gift.py       # 望潮阅读有礼
    ├── config.example.yaml
    └── requirements.txt
```

## 本地开发

```bash
git clone https://github.com/WillpowerJin/ql-scripts.git
cd ql-scripts

# 示例：望潮
cd wangchao
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填写手机号密码
python read_gift.py --dry-run
```

## License

仅供学习交流，请遵守目标网站 / App 服务条款。
