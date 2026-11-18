# 宜家家居 (IKEA) 每日自动签到脚本 (Python)

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-green.svg)](https://opensource.org/licenses/GPL-3.0)

基于宜家家居 App（IKEA China）前端逆向工程开发的自动化每日签到打卡脚本，支持获取宜家会员成长乐园签到奖励、积分与连续签到天数。

---

## 🌟 功能特性

- **纯 HTTP 驱动**：脱离手机与模拟器，青龙面板、VPS、本地均可无参定时运行。
- **协议逆向还原**：完整还原了宜家前端对签到请求载荷的 **XOR 动态密钥混淆加密算法**（`partyUid` 异或加密 + Base64 编码）。
- **智能免配置 UID**：只需提供登录 Token（JWT），脚本会自动解析提取对应的 `partyUid` 用户标识。
- **一键提取 Token**：连接已 root 的安卓手机时，运行 `python3 ikea/pull_token.py --write-config` 即可秒级自动提取 Token 存入配置。
- **美观卡片日志与多端通知**：
  - 控制台以清晰卡片式排版、Emoji 状态标记输出。
  - 原生支持 **青龙统一通知 (notify.py)**、**iOS Bark**、**PushPlus 微信推送**。

---

## 🔑 凭据获取方式

宜家签到仅需要一个 **`IKEA_TOKEN`**（CIAM 授权 JWT 令牌，通常长达数周至数月有效）。

### 方式 A：已 root 安卓机一键提取（最方便）
手机开启 USB 调试并插上电脑（已打开过宜家 App 并进入过积分商城），在项目根目录运行：
```bash
python3 ikea/pull_token.py --write-config
```
脚本会自动读取手机 App 本地数据库，提取 Token 并直接保存至 `ikea/config.yaml`。

### 方式 B：手机抓包工具（iOS / 未 root 手机）
1. 手机打开抓包工具（iOS 推荐 Stream / Reqable，安卓推荐 Reqable / 小黄鸟）；
2. 手机打开宜家 App → 点击「我的」→「会员中心」→「可用积分」→「签到赚积分」；
3. 在抓包记录中过滤 `bff.app.ikea.cn`，查看任意请求的 Request Header：
   ```text
   Authorization: Bearer eyJraWQi...
   ```
4. 复制 `Bearer ` 后面的 `eyJ...` 完整字符串，即为所需 Token。

---

## ⚙️ 配置说明

### 1. 本地 / VPS 运行（YAML 配置）
复制示例配置文件：
```bash
cp ikea/config.example.yaml ikea/config.yaml
```
编辑 `config.yaml` 填入 Token（若已用 `pull_token.py` 则已自动填好）。

### 2. 青龙面板环境变量
在青龙面板「环境变量」中添加：
| 变量名 | 说明 | 示例 |
|---|---|---|
| `IKEA_TOKEN` | 必填，JWT Token 字符串（多账号用 `&` 或换行分隔） | `eyJraWQi...` |
| `IKEA_ACCOUNTS` | 可选，JSON 格式多账号配置 | `[{"name":"主号","token":"xxx"}]` |
| `RANDOM_DELAY` | 可选，任务执行前随机错峰秒数上限（默认 0 不延迟） | `300` |

---

## 🚀 运行方法

### 青龙面板定时任务（推荐无参运行）
定时命令直接填写：
```bash
task ikea/daily.py
```
定时规则例如每天上午 8:35：`35 8 * * *`。

### 本地终端常用命令
```bash
# 1. 默认执行单次签到（无需任何参数）
python3 ikea/daily.py

# 2. 仅查询当前积分与连签天数（不触发打卡）
python3 ikea/daily.py --check

# 3. 指定自定义配置文件路径
python3 ikea/daily.py --config /path/to/custom_config.yaml

# 4. 常驻后台自带定时调度模式
python3 ikea/daily.py --loop

# 5. 输出调试日志
python3 ikea/daily.py --debug
```
