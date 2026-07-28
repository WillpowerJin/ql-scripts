/*
 * 习酒 · 君品荟 —— QuantumultX 抓 access_token
 *
 * 用法：在 QuantumultX 配置里加一条 rewrite_local 规则，把
 *   fm.exijiu.com 上带 X-access-token 头的请求转发给本脚本，
 *   脚本会：
 *     1) 把 token 存进 QuantumultX 本地键值 xijiu_access_token
 *     2) 发一条 QuantumultX 通知（可选 Bark、可选回传 webhook）
 *
 * 见同目录 xijiu_access_token.snippet.conf。
 *
 * 可选参数（在 QuantumultX「BoxJs / 本地键值」或直接用
 *  $prefs.setValueForKey(...) 提前写入即可，全部可留空）：
 *
 *    xijiu_account_name   通知里显示的账号名，默认 "iPhone"
 *    xijiu_bark_url       Bark 完整 URL，例如 https://api.day.app/xxxxx
 *    xijiu_bark_key       只填 key 时用 https://api.day.app/{key}
 *    xijiu_webhook_url    青龙 / 自建服务回传 URL，POST JSON
 *                         { name, access_token, ua, ts }
 *    xijiu_webhook_token  会加到 Authorization: Bearer <token>
 *
 * 不需要修改脚本本体。
 */

(function () {
  const KEY_TOKEN = "xijiu_access_token";
  const KEY_TS = "xijiu_access_token_ts";
  const KEY_UA = "xijiu_access_token_ua";

  const req = typeof $request !== "undefined" ? $request : {};
  const headers = req.headers || {};

  // 请求头大小写不敏感：兼容 X-access-token / x-access-token / X-Access-Token
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
    // 没抓到就直接放行，别提示，避免刷屏
    $done({});
    return;
  }

  const oldToken = pref(KEY_TOKEN);
  const now = Date.now();
  const name = pref("xijiu_account_name", "iPhone");

  $prefs.setValueForKey(token, KEY_TOKEN);
  $prefs.setValueForKey(String(now), KEY_TS);
  if (ua) $prefs.setValueForKey(ua, KEY_UA);

  const changed = token !== oldToken;
  const preview = token.slice(0, 12) + "…" + token.slice(-6);
  const subtitle = changed ? "已更新 access_token" : "token 未变化";
  const body =
    "账号：" + name + "\n" +
    "时间：" + fmt(now) + "\n" +
    "token：" + preview + "\n" +
    "长度：" + token.length;

  $notify("习酒 · access_token", subtitle, body);

  // 可选：Bark 推一份到手机通知栏
  const barkUrl = pref("xijiu_bark_url");
  const barkKey = pref("xijiu_bark_key");
  const barkBase = barkUrl || (barkKey ? "https://api.day.app/" + barkKey : "");
  if (changed && barkBase) {
    const title = encodeURIComponent("习酒 access_token");
    const bodyEnc = encodeURIComponent(
      name + " 已更新 " + preview + "（" + fmt(now) + "）"
    );
    const u = barkBase.replace(/\/$/, "") + "/" + title + "/" + bodyEnc +
      "?group=" + encodeURIComponent("习酒君品荟");
    $task.fetch({ url: u, method: "GET" }).then(() => {}, () => {});
  }

  // 可选：把 token 回传给自建服务 / 青龙
  const hookUrl = pref("xijiu_webhook_url");
  if (changed && hookUrl) {
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
