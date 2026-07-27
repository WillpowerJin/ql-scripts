# 青龙脚本集合

个人维护的青龙面板订阅脚本。文档与配置说明在各子目录中查看；**订阅时只拉取脚本文件**，不把说明文档同步进青龙。

## 脚本列表

| 脚本 | 说明 | 文档 |
|------|------|------|
| [hifiti](./hifiti/) | [HiFiNi 音乐磁场](https://www.hifiti.com/) 自动签到（Cookie 优先，失效可密码重登） | [使用说明 →](./hifiti/README.md) |
| [wangchao](./wangchao/) | 望潮 App「阅读有礼」：手机号密码登录，自动阅读满 12 篇并抽奖 | [使用说明 →](./wangchao/README.md) |

后续新脚本会以同级目录形式增加，并在本表登记。

## 青龙订阅

在青龙「订阅管理」添加，或 SSH 执行：

```bash
# 只拉取 .py 脚本；黑名单排除文档与示例配置
ql repo https://github.com/WillpowerJin/ql-scripts.git "checkin|read_gift" "README|config|example|requirements|\.md|\.yaml|\.yml|\.txt" "" "main" "py"
```

说明：

- **白名单** `checkin|read_gift`：匹配 HiFiNi 签到与望潮阅读脚本
- **黑名单**：排除 README、示例配置等，避免进青龙任务列表
- **扩展名** `py`：仅同步 Python 文件
- 分支默认 `main`

账号、Cookie、密码等**不要写进仓库**，在青龙「环境变量」中配置。各脚本所需变量见对应文档页。

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
