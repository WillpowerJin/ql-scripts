/*
 * 习酒 · 君品荟 —— Quantumult X 自动抓 access_token
 *
 * 作用：命中 fm.exijiu.com 且请求头带 X-access-token 时：
 *   1) 完整 token 写入本地键值 xijiu_access_token（可随时用 show 脚本再读）
 *   2) console 日志打印完整 token + 可粘贴 YAML
 *   3) 系统通知正文里放完整 token（长按通知可复制）
 *   4) 可选 Bark（带 autoCopy）/ webhook
 *
 * 配置片段：xijiu_access_token.snippet.conf
 *
 * 本地键值（可选，$prefs.setValueForKey("值","键")）：
 *   xijiu_account_name   账号名，默认 iPhone（通知标题用）
 *   xijiu_notify_always  填 1 时 token 未变也通知（默认仅变化时通知）
 *   xijiu_bark_url / xijiu_bark_key
 *   xijiu_webhook_url / xijiu_webhook_token
 */
(function () {
  const KEY_TOKEN = "xijiu_access_token";
  const KEY_TS = "xijiu_access_token_ts";
  const KEY_UA = "xijiu_access_token_ua";
  const KEY_YAML = "xijiu_access_token_yaml";

  const req = typeof $request !== "undefined" ? $request : {};
  const headers = req.headers || {};

  function pickHeader(h, name) {
    const target = name.toLowerCase();
    for (const k of Object.keys(h || {})) {
      if (k.toLowerCase() === target) return String(h[k] || "");
    }
    return "";
  }

  function pref(key, fallback) {
    let v = "";
    try {
      v = $prefs.valueForKey(key);
    } catch (e) {}
    if (v == null || v === "") return fallback == null ? "" : fallback;
    return String(v);
  }

  function fmt(ts) {
    const d = new Date(ts);
    const pad = (n) => (n < 10 ? "0" + n : "" + n);
    return (
      d.getFullYear() +
      "-" +
      pad(d.getMonth() + 1) +
      "-" +
      pad(d.getDate()) +
      " " +
      pad(d.getHours()) +
      ":" +
      pad(d.getMinutes()) +
      ":" +
      pad(d.getSeconds())
    );
  }

  /** 拼成 config.yaml 可直接粘贴的一行 */
  function yamlLine(token) {
    // 双引号包裹，内部 " 极少出现；若有则简单转义
    const safe = String(token).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    return 'access_token: "' + safe + '"';
  }

  /** 通知 / 日志用的完整正文（方便复制） */
  function copyBody(name, token, when, changed) {
    const lines = [
      "账号: " + name,
      "时间: " + when,
      "长度: " + token.length,
      "状态: " + (changed ? "已更新" : "与缓存相同"),
      "",
      "—— 完整 token（整段复制）——",
      token,
      "",
      "—— 粘贴到 config.yaml（该账号下）——",
      yamlLine(token),
    ];
    return lines.join("\n");
  }

  const token = pickHeader(headers, "X-access-token").trim();
  const ua = pickHeader(headers, "User-Agent");

  if (!token || token.length < 20) {
    $done({});
    return;
  }

  const oldToken = pref(KEY_TOKEN, "");
  const changed = token !== oldToken;
  const notifyAlways = pref("xijiu_notify_always", "") === "1";
  const name = pref("xijiu_account_name", "iPhone");
  const now = Date.now();
  const when = fmt(now);
  const yml = yamlLine(token);
  const body = copyBody(name, token, when, changed);

  // 始终写入本地（即使未变也刷新时间戳可选：仅变化时写）
  $prefs.setValueForKey(token, KEY_TOKEN);
  $prefs.setValueForKey(String(now), KEY_TS);
  $prefs.setValueForKey(yml, KEY_YAML);
  if (ua) $prefs.setValueForKey(ua, KEY_UA);

  // —— 日志：Quantumult X → 首页 → 工具 → 日志 / 脚本日志 ——
  // 完整 token 一定打出来，方便从日志里复制
  console.log("[xijiu] ========== access_token ==========");
  console.log("[xijiu] account=" + name);
  console.log("[xijiu] time=" + when);
  console.log("[xijiu] len=" + token.length + " changed=" + changed);
  console.log("[xijiu] token=" + token);
  console.log("[xijiu] yaml=" + yml);
  console.log("[xijiu] url=" + (req.url || ""));
  console.log("[xijiu] ==================================");

  if (!changed && !notifyAlways) {
    // 未变化：只写日志，不弹通知（避免刷屏）
    console.log("[xijiu] token 未变化，跳过通知（设 xijiu_notify_always=1 可强制通知）");
    $done({});
    return;
  }

  // —— 系统通知：正文 = 完整 token + yaml 行，长按通知「拷贝」——
  $notify(
    "习酒 access_token · " + name,
    (changed ? "已更新 · " : "未变化 · ") + when + " · " + token.length + "字",
    body
  );

  // —— 可选 Bark：copy 参数便于一键复制 ——
  const barkUrl = pref("xijiu_bark_url", "");
  const barkKey = pref("xijiu_bark_key", "");
  const barkBase = barkUrl || (barkKey ? "https://api.day.app/" + barkKey : "");
  if (barkBase) {
    // POST JSON 比 URL 长度限制更稳，完整 token 不易被截断
    const endpoint = barkBase.replace(/\/$/, "");
    $task
      .fetch({
        url: endpoint,
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          title: "习酒 access_token · " + name,
          body: body,
          group: "习酒君品荟",
          copy: token,
          autoCopy: "1",
          level: "active",
        }),
      })
      .then(
        () => console.log("[xijiu] Bark 已推送"),
        (e) => console.log("[xijiu] Bark 失败: " + e)
      );
  }

  // —— 可选 webhook ——
  const hookUrl = pref("xijiu_webhook_url", "");
  if (hookUrl) {
    const hookToken = pref("xijiu_webhook_token", "");
    const h = { "Content-Type": "application/json" };
    if (hookToken) h["Authorization"] = "Bearer " + hookToken;
    $task
      .fetch({
        url: hookUrl,
        method: "POST",
        headers: h,
        body: JSON.stringify({
          name: name,
          access_token: token,
          yaml: yml,
          ua: ua,
          ts: now,
          time: when,
        }),
      })
      .then(
        () => console.log("[xijiu] webhook 已推送"),
        (e) => console.log("[xijiu] webhook 失败: " + e)
      );
  }

  $done({});
})();
