# 青龙脚本集合

个人维护的青龙面板订阅脚本。文档与配置说明在各子目录中查看；**订阅时只拉取脚本文件**，不把说明文档同步进青龙。

## 脚本列表

| 脚本 | 说明 | 文档 |
|------|------|------|
| [hifiti](./hifiti/) | [HiFiNi 音乐磁场](https://www.hifiti.com/) 自动签到（Cookie 优先，失效可密码重登） | [使用说明 →](./hifiti/README.md) |
| [wangchao](./wangchao/) | 望潮 App「阅读有礼」：手机号密码登录，自动阅读满 12 篇并抽奖 | [使用说明 →](./wangchao/README.md) |

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
| **白名单** | `checkin\|read_gift` |
| **黑名单** | `README\|config\|example\|requirements\|\.md\|\.yaml\|\.yml\|\.txt` |
| 扩展名 | `py` |
| 定时规则 | 按需，例如 `30 8 * * *`（仅自动拉库，不是跑任务） |

> **白名单必须带上 `read_gift`**，否则只会拉到 `hifiti/checkin.py`，不会拉 `wangchao/read_gift.py`。  
> 白名单匹配的是**路径里是否包含关键字**，多个用 `\|` 分隔。

### 已有订阅（只点「运行」不够）

若你以前是按旧文档只填了白名单 `checkin`：

1. 打开该订阅 → **编辑**
2. 把白名单改成：`checkin|read_gift`
3. **保存**后再点运行

只点「运行」会沿用旧参数，**不会**自动读本仓库 README，也**不会**自动加上望潮脚本。

### 命令行等价写法

```bash
ql repo https://github.com/WillpowerJin/ql-scripts.git "checkin|read_gift" "README|config|example|requirements|\.md|\.yaml|\.yml|\.txt" "" "main" "py"
```

参数含义：

| 位置 | 含义 | 本仓库取值 |
|------|------|------------|
| 1 | 仓库地址 | 见上 |
| 2 | 白名单（路径包含即拉取） | `checkin\|read_gift` |
| 3 | 黑名单（路径包含则跳过） | 文档/配置等 |
| 4 | 依赖文件 | 空 |
| 5 | 分支 | `main` |
| 6 | 扩展名 | `py` |

拉取成功后，脚本管理中应能看到类似：

```text
…/hifiti/checkin.py
…/wangchao/read_gift.py
```

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
