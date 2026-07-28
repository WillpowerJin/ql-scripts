/*
 * 习酒 · 君品荟 —— QuantumultX 抓 access_token
 *
 * 用法：在 QuantumultX 配置里加一条 rewrite_local 规则，把
 *   fm.exijiu.com 上带 X-access-token 头的请求转发给本脚本，
 *   脚本会：
 *     1) 把完整 token 存进 QuantumultX 本地键值 xijiu_access_token
 *     2) 仅当 token 发生变化时，弹一条 QX 通知（正文含完整 token）
 *        并可选推 Bark、可选回传青龙 webhook
 *
 * 见同目录 xijiu_access_token.snippet.conf。
 *
 * 可选参数（本地键值，用 $prefs.setValueForKey 提前写入即可，全部可留空）：
 *
 *    xijiu_account_name   通知里显示的账号名，默认 "iPhone"
 *    xijiu_bark_url       Bark 完整 URL，例如 https://api.day.app/xxxxx
 *    xijiu_bark_key       只填 key 时用 https://api.day.app/{key}
 *    xijiu_webhook_url    青龙 / 自建服务回传 URL，POST JSON
 *                         { name, access_token, ua, ts }
 *    xijiu_webhook_token  会加到 Authorization: Bearer <token>
 */
(function () {
  const KEY_TOKEN = "xijiu_access_token";
  const KEY_TS = "xijiu_access_token_ts";
  const KEY_UA = "xijiu_access_token_ua";

  const req = typeof $request !== "undefined" ? $request : {};
  const headers = req.headers || {};

  function pickHeader(h, name) {
    const target = name.toLowerCase();
    for (const k of Object.keys(h)) {
      if (k.toLowerCase() === target) return h[k];
    }
    return "";
  }

  function pref(key, fallback) {
    const v = $prefs.valueForKey(key);
    return v == null || v === "" ? (fallback == null ? "" : fallback) : v;
  }

  function fmt(ts) {
    const d = new Date(ts);
    const pad = (n) => (n < 10 ? "0" + n : "" + n);
    return (
      d.getFullYear() +
      "-" + pad(d.getMonth() + 1) +
      "-" + pad(d.getDate()) +
      " " + pad(d.getHours()) +
      ":" + pad(d.getMinutes()) +
      ":" + pad(d.getSeconds())
    );
  }

  const token = pickHeader(headers, "X-access-token");
  const ua = pickHeader(headers, "User-Agent");

  if (!token || token.length < 20) {
    $done({});
    return;
  }

  const oldToken = pref(KEY_TOKEN);
  const changed = token !== oldToken;

  // token 没变就静默放行，避免签到页反复请求刷屏
  if (!changed) {
    $done({});
    return;
  }

  const now = Date.now();
  const name = pref("xijiu_account_name", "iPhone");

  $prefs.setValueForKey(token, KEY_TOKEN);
  $prefs.setValueForKey(String(now), KEY_TS);
  if (ua) $prefs.setValueForKey(ua, KEY_UA);

  // 完整 token 塞进正文，方便从通知中心长按复制
  $notify(
    "习酒 · access_token 已更新",
    name + " · " + fmt(now) + " · len=" + token.length,
    token
  );

  // 可选：Bark 推一份（含完整 token）
  const barkUrl = pref("xijiu_bark_url");
  const barkKey = pref("xijiu_bark_key");
  const barkBase = barkUrl || (barkKey ? "https://api.day.app/" + barkKey : "");
  if (barkBase) {
    const title = encodeURIComponent("习酒 access_token · " + name);
    const bodyEnc = encodeURIComponent(token);
    const u = barkBase.replace(/\/$/, "") + "/" + title + "/" + bodyEnc +
      "?group=" + encodeURIComponent("习酒君品荟") +
      "&copy=" + encodeURIComponent(token) +
      "&autoCopy=1";
    $task.fetch({ url: u, method: "GET" }).then(() => {}, () => {});
  }

  // 可选：回传自建服务 / 青龙
  const hookUrl = pref("xijiu_webhook_url");
  if (hookUrl) {
    const hookToken = pref("xijiu_webhook_token");
    const h = { "Content-Type": "application/json" };
    if (hookToken) h["Authorization"] = "Bearer " + hookToken;
    $task.fetch({
      url: hookUrl,
      method: "POST",
      headers: h,
      body: JSON.stringify({
        name: name,
        access_token: token,
        ua: ua,
        ts: now,
      }),
    }).then(() => {}, () => {});
  }

  $done({});
})();
