# 八富生活

| 脚本 | 说明 | 是否依赖手机 |
|------|------|----------------|
| **[`ads_yyb.py`](./ads_yyb.py)** | 协议看广告（YYB 取微信 code + Feistel complete） | 依赖 **YYB_GO** 服务，不强制 adb |
| `auto_ads_ui.py` | adb UI 真看广告 | 要 adb 手机 |
| `watch_ads.py` | 手机号密码登录 / 查进度（旧协议探测） | 否（complete 多半无效） |

> 仅供学习。YYB 为第三方 code 服务，可用性与风险自负。

---

## 青龙：协议看广告 `ads_yyb.py`

### 订阅

白名单加上 **`bafu`**（或 `ads_yyb`）。

会拉到：`bafu/ads_yyb.py`（入口）。

### 依赖

```text
requests
```

### 环境变量

**账号（必填）：**

```text
YYB_GO=https://你的code服务地址@openid的ref
```

多账号换行；**每号备注**写在末尾 `#` 后（日志 / Bark 显示名）：

```text
YYB_GO=https://host@openid1#iPhone
https://host@openid2#Android
```

**全局备注**（进 Bark 标题，区分多台青龙）：

```text
BAFU_NOTE=家里青龙
```

**通知（与其它脚本共用）：**

```text
BARK_KEY=你的Key
# 或 BARK_URL=https://api.day.app/你的Key/
# 可选 BARK_GROUP=八富看广告
```

**可选：**

```text
BFSH_INVITER_CODE=U75803F7    # 邀请码
BFSH_FORCE_REBIND=0           # 不强制改绑
DRY_RUN=1                     # 只查询
BAFU_SESSION_CACHE=/ql/data/bafu_session_cache.json
```

### 定时任务

| 名称 | 命令 | cron 建议 |
|------|------|-----------|
| 八富看广告 | `python3 -u .../bafu/ads_yyb.py` | `35 6 * * *` |

任务超时建议 ≥ 30 分钟（多号 × 每号最多约 10 条广告）。

跑完会 **Bark** 推送汇总（未配置则只打日志）。

### 注意

1. 首次可能需在微信小程序内**手动看 1 次广告**（「首次验证」）。  
2. `needLogin` 时脚本会向 YYB 再要 `wx.login` code。  
3. 没被本仓库邀请码邀请过的号也能跑；绑邀请失败一般不挡看广告。  
4. YYB 挂了/openid 失效 → 登录失败，与脚本无关。

---

## 本地 UI 方案（原方案）

```bash
# adb 已连接，微信打开八富「赚红包」页
python3 auto_ads_ui.py --rounds 10
```

详见历史逆向说明：`complete` 在官方小程序里要 feistel + 有时要微信 code；纯密码脚本往往刷不动次数。

---

## 目录（进仓库）

```text
bafu/
  ads_yyb.py         # 青龙入口（YYB + Bark）
  requirements.txt
  README.md
```

本地可有 `auto_ads_ui.py`、`watch_ads.py`、`capture/` 等，默认不强制订阅。
