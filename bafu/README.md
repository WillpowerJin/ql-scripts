# 八富生活

| 脚本 | 说明 | 依赖 |
|------|------|------|
| **[`ads_mp.py`](./ads_mp.py)** | **小程序协议**看广告（YYB GO + `/ad/complete`） | 环境变量 `YYB_GO` |

> 仅供学习。账号安全与封禁风险自负。

---

## 青龙：`ads_mp.py`

逻辑：

1. YYB GO 取 `wx.login` / 手机号 code  
2. `getOpenidAnon` → `phoneLogin`  
3. 人机 captcha → `checkLimit` → `POST /ad/complete`（Feistel token）

### 订阅

白名单加上 **`bafu`**（或 `ads_mp`）。

会拉到：`bafu/ads_mp.py`。

### 依赖

```text
requests
```

### 环境变量

**账号（必填）：**

```text
YYB_GO=host:port@ref
```

多账号换行或 `&`；**自定义备注**写在最后一个 `#` 后（日志 / Bark 显示名）：

```text
YYB_GO=192.168.2.199:8000@owNAXHSWnZNI#iPhone
192.168.2.199:8000@owNAxxxxxxxx#家里
```

或一行：

```text
YYB_GO=192.168.2.199:8000@ref1#iPhone & 192.168.2.199:8000@ref2#Android
```

不写备注时，显示名为 `ref` 前 8 位 + `...`。

**全局备注**（进 Bark 标题，区分多台青龙）：

```text
BAFU_NOTE=家里青龙
```

**通知（与其它脚本共用）：**

```text
BARK_KEY=你的Key
# 或 BARK_URL=https://api.day.app/你的Key/
# 可选 BARK_GROUP=八富生活小程序
# 可选 BARK_SOUND=bell
```

**可选：**

```text
BFSH_INVITER_CODE=U75803F7   # 邀请码
BFSH_FORCE_REBIND=0          # 已绑定则不改绑（默认会尝试 setInviter）
DRY_RUN=1                    # 只查询进度，不 complete
QYWX_KEY=...                 # 可选，企业微信机器人
```

### 定时任务

| 名称 | 命令 | cron 建议 |
|------|------|-----------|
| 八富生活小程序 | `python3 -u .../bafu/ads_mp.py` | `0 9-23/2 * * *` |

任务超时建议 ≥ 30 分钟。跑完会 **Bark** 推送汇总（未配置则只打日志）。

### 注意

1. 账号来自 **YYB GO 的微信 ref**，不是 App 手机号密码。  
2. 已达当日上限会自动结束该号。  
3. captchaToken 按日缓存到 `bfsh_v2_cache.json`（脚本同目录）。  
4. 邀请绑定失败一般不挡看广告。

---

## 目录

```text
bafu/
  ads_mp.py          # 青龙入口（小程序协议 + YYB_GO 备注 + Bark）
  requirements.txt
  README.md
```
