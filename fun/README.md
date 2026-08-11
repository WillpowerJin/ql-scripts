# FUN 矿池

基于社区脚本「FUN 自动爬墙」重写：登录 → 收矿 → 查状态 → 可选升级，**Bark 美化通知**。

API：`https://exchange.acmes.dev/api/v1`  
注册（示例）：`https://mexchange.acmes.dev`（邀请码以平台为准）

> 仅供学习。平台与资产风险自负。

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

### 环境变量

**账号 `FUN`（必填）**

```text
手机号#密码#收矿#升级
手机号#密码#收矿#升级#备注
```

| 段 | 含义 | 建议 |
|----|------|------|
| 收矿 | `1` 开 / `0` 关 | 新手 **1** |
| 升级 | `1` 开 / `0` 关 | 新手 **0**（避免乱花币） |
| 备注 | 可选，如 iPhone | 进日志和 Bark |

多账号用 `&` 或换行：

```text
FUN=13800138000#pass#1#0#iPhone&13900139000#pass#1#0#Android
```

**全局备注（标题）：**

```text
FUN_NOTE=家里青龙
```

**Bark（与其它项目共用）：**

```text
BARK_KEY=你的Key
# 或 BARK_URL=https://api.day.app/你的Key/
```

可选：`FUN_BASE_URL`（默认官方 API）

### 定时

| 名称 | 命令 | cron |
|------|------|------|
| FUN矿池 | `python3 -u .../fun/mine.py` | `10 8 * * *` |

## 本地

```bash
cd fun
pip install -r requirements.txt
export FUN='手机#密码#1#0#备注'
export BARK_KEY=xxx
python mine.py
```

## Bark 示例

```text
⛏️ FUN 矿池 · 任务汇总
🏷️ 备注：家里青龙
📅 07-31 15:30
────────────────

⛏️ 【iPhone】
   📱 138****2453
   🏭 矿机：LV1
   💎 可领：0
   💰 收矿：暂无可领取 ℹ️
   🚀 升级：已关闭 ⏭️

────────────────
📦 账号 1 · ✅1  ❌0
🎉 全部顺利
```

## 文件

```text
fun/
  mine.py
  requirements.txt
  README.md
```
