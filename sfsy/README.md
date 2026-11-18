# 顺丰速运日常积分任务

[← 返回脚本总览](../README.md)

入口：`daily.py`（青龙只跑这个）。原 v1.3 脚本和单测仅本地保留，不入库、不由订阅拉到。

> 账号 / Cookie / Bark 等敏感信息只写在**青龙环境变量**（或本地不提交的 `config.yaml`），不要提交到 Git。

## 会做什么

1. **APP 签到** `getUnFetchPointAndDiscount`
2. **新签到** `integralSignV2Service~sign`
3. **小程序签到** `automaticSignFetchPackage`
4. **积分任务** 列表 / 完成 / 领积分，以及生活特权领券
5. **超值福利签到** `superWelfare~receiveRedPacket`（社区常规、接口仍存活）
6. **采蜜/丰蜜**、**会员日**（每月 26–28 日）：接口仍开放则做，活动结束 / 没有资格 / 不在窗口则跳过
7. 日志带 **emoji**；配置了 `BARK_URL` / `BARK_KEY` 时推送 **Bark** 摘要

过期季节活动（端午、年终集卡 YEAREND_2024、周年庆 2024、32 周年游戏）不会引入。

## 登录

内地顺丰 APP 只有**手机号 + 短信验证码**（以及微信绑定），**没有手机号 + 密码**。

日常任务只用积分中心 session，请抓 **我的 → 积分** 页：

- `sfsy_url`：积分页完整跳转 URL
- 或 `cookie`：`sessionId=...;_login_mobile_=...;_login_user_id_=...`

`daily.py` 会合并 **环境变量 + config.yaml**；同一 `_login_mobile_` 只留先出现的那条。多账号用 `&` 或换行分隔。Session 失效后重新抓一次。

## 青龙环境变量（账号）

青龙 → 环境变量 → 新建。名称、值如下。

### 方式 A（推荐）：一条变量里写 URL/cookie + 备注

| 名称 | 值（示例） |
|------|------------|
| `sfsyUrl` | 积分页完整 URL 或 cookie，**末尾 `#备注`** |

单账号：

```text
名称：sfsyUrl
值：  sessionId=xxx;_login_mobile_=15900000000;_login_user_id_=yyy#iPhone
```

或 URL：

```text
名称：sfsyUrl
值：  https://mcs-mimp-web.sf-express.com/mcs-mimp/share/weChat/shareGiftReceiveRedirect?...#iPhone
```

多账号用 `&`（或换行）分隔，每个后面自己的 `#备注`：

```text
名称：sfsyUrl
值：  sessionId=aaa;_login_mobile_=159...;_login_user_id_=u1#iPhone&sessionId=bbb;_login_mobile_=136...;_login_user_id_=u2#甜甜甜
```

也可用 `SFSY_URL` / `SFSY_COOKIE`（写法相同）。`#` 后面不要带 `/`，以免和网址混淆。

### 方式 B：平行变量 `SFSY_NAME`

不想写在同一串里时，备注单独对齐：

```text
sfsyUrl=cookie或url&cookie或url
SFSY_NAME=iPhone&甜甜甜
```

`SFSY_NAME` 优先于 `#备注`。

### 方式 C：`SFSY_ACCOUNTS` JSON

```text
名称：SFSY_ACCOUNTS
值：
[
  {"name":"iPhone","cookie":"sessionId=...;_login_mobile_=...;_login_user_id_=..."},
  {"name":"甜甜甜","sfsy_url":"https://mcs-mimp-web.sf-express.com/mcs-mimp/share/weChat/shareGiftReceiveRedirect?..."}
]
```

`name` / `note` / `remark` 都当备注。JSON 在青龙里要注意合法，cookie 里的 `"` 要转义。

## 环境变量（Bark，与 hifiti 相同）

| 变量 | 说明 |
|------|------|
| `BARK_URL` | App 里复制的完整地址 |
| 或 `BARK_KEY` | 仅 Key |
| `BARK_SERVER` | 自建服务器，默认 `https://api.day.app` |
| `BARK_GROUP` | 默认 `顺丰速运` |
| `BARK_SOUND` / `BARK_ICON` / `BARK_LEVEL` | 可选 |

## 本地运行

```bash
cd sfsy
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 填写 sfsy_url / cookie，不要 git add
python3 daily.py
```

## 获取 cookie / sfsyUrl

1. 打开顺丰 APP 或小程序 → 我的 → 积分
2. 抓包以下 URL 之一整段复制：
   - `https://mcs-mimp-web.sf-express.com/mcs-mimp/share/weChat/shareGiftReceiveRedirect`
   - `https://mcs-mimp-web.sf-express.com/mcs-mimp/share/app/shareRedirect`
3. 或从 Cookie 里取 `sessionId`、`_login_mobile_`、`_login_user_id_`

多账号：yaml 里再加一项，或环境变量 `&` 分隔；备注见上文 `#备注` / `SFSY_NAME` / `name`。

## 仓库内文件

| 文件 | 说明 |
|------|------|
| `daily.py` | 日常任务入口 |
| `config.example.yaml` | 本地配置示例 |
| `requirements.txt` | `requests` + 可选 `PyYAML` |

原版 `顺丰速运日常任务v1.3.py` 与 `test_daily.py` 只在本地保留（已 gitignore），
不参与订阅，避免青龙多建无用任务。
