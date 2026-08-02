# 推广宝每日广告

自动登录、看广告、领奖（Python 版）。

## 青龙部署

1. 将 `main.py` 放入青龙脚本目录。
2. 青龙依赖管理 → Python → 添加 `requests`（可选 `PyYAML`）。
3. 新建环境变量：

```bash
export TGB='手机号#密码&手机号2#密码2'
# 或
export TGB_ACCOUNTS='[{"name":"账号1","phone":"138xxxx","password":"pwd"}]'
# 或
export TGB_USER='138xxxx&139xxxx'
export TGB_PASS='pwd1&pwd2'
export TGB_NAME='账号1&账号2'
```

4. Bark 通知（可选）：

```bash
export BARK_URL='https://api.day.app/你的Key/'
# 或
export BARK_KEY='你的Key'
export BARK_SERVER='https://api.day.app'
export BARK_GROUP='推广宝'
```

5. 定时：`0 9 * * *`

## 本地运行

```bash
pip install requests pyyaml
cp config.example.yaml config.yaml
# 编辑 config.yaml
python main.py

# 仅测试登录（不执行广告任务）
python main.py --login-only
```

## 配置项

| 环境变量 | 说明 | 默认 |
|----------|------|------|
| `TGB_INVITE_CODE` | 邀请码 | `000GHFAV` |
| `TGB_TIMEOUT` | 请求超时（秒） | `15` |
| `TGB_MAX_RETRIES` | 网络错误重试次数 | `3` |
| `TGB_RETRY_INTERVAL` | 重试间隔（秒） | `10` |
| `TGB_AD_WATCH_SECONDS` | 广告模拟观看秒数 | `22` |
| `TGB_INTER_ACCOUNT_DELAY` | 账号间隔（秒） | `6` |
| `TGB_UA` | User-Agent | 内置安卓 UA |

## 文件说明

- `main.py`：主脚本（推荐）
- `main.js`：Node.js 备用版本
- `config.example.yaml`：本地配置示例
- `config.yaml`：本地配置（已 gitignore，请自行复制填写）
