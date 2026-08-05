# 八富生活

| 脚本 | 说明 | 依赖 |
|------|------|------|
| **[`ads_app.py`](./ads_app.py)** | **新版 App 协议**（手机号密码 + markmedia） | 环境变量 `BAFU` |

> 仅供学习。账号安全与封禁风险自负。

---

## 青龙：App 协议看广告 `ads_app.py`

基于新版 App 登录与 markmedia 激励上报，**不依赖 YYB / 微信**。

### 订阅

白名单加上 **`bafu`**（或 `ads_app`）。

会拉到：`bafu/ads_app.py`。

### 依赖

```text
requests
```

### 环境变量

**账号（必填）：**

```text
BAFU=手机号#密码
```

多账号换行或 `&`；**备注**写在第三个 `#` 后（日志 / Bark 显示名）：

```text
BAFU=13800138000#pass123#主号
13900139000#pass456#副号
```

**全局备注**（进 Bark 标题，区分多台青龙）：

```text
BAFU_NOTE=家里青龙
```

**通知（与其它脚本共用）：**

```text
BARK_KEY=你的Key
# 或 BARK_URL=https://api.day.app/你的Key/
# 可选 BARK_GROUP=八富秒得
# 可选 BARK_SOUND=bell
```

**可选：**

```text
BFSH_INVITER_CODE=U75803F7   # 邀请码（未绑定时尝试绑定）
DRY_RUN=1                    # 只登录查进度，不刷广告
BAFU_AD_WAIT=32              # 模拟观看秒数，默认 32
BAFU_AD_INTERVAL=5           # 条间间隔秒数，默认 5
```

### 定时任务

| 名称 | 命令 | cron 建议 |
|------|------|-----------|
| 八富秒得App | `python3 -u .../bafu/ads_app.py` | `0 9-23/2 * * *` |

任务超时建议 ≥ 30 分钟（多号 × 每号可能多条广告，每条约 35s+）。

跑完会 **Bark** 推送汇总（未配置则只打日志）。

### 注意

1. 账号格式为 **App 手机号 + 密码**，与小程序 openid 无关。  
2. 已达当日上限会自动结束该号。  
3. 连续失败（物料/计数不涨）会中止该号，避免死循环。  
4. 邀请绑定失败一般不挡看广告。

---

## 目录

```text
bafu/
  ads_app.py         # 青龙入口（App 协议 + Bark）
  requirements.txt
  README.md
```
