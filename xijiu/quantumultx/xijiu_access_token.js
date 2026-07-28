/*
 * 习酒 access_token 抓取 · Quantumult X · v4
 *
 * ★ 通知标题必须是：习酒TK·iPhone·v4
 *   若标题没有「v4」，说明 QX 还在跑旧脚本（远程缓存），请改用下方「本地脚本」或带 ?v=4 的 URL。
 *
 * 通知正文 = 纯 86 位 token（无省略号、无「账号/时间」多行）
 * 完整值同时写入日志：搜 [xijiu] 看 token=
 *
 * rewrite（二选一）：
 *   远程（防缓存）：
 *   .../xijiu_access_token.js?v=4
 *   本地：script-request-header xijiu_access_token.js
 */
(function () {
  const VERSION = "v4";
  const COOLDOWN_MS = 5 * 60 * 1000; // 5 分钟最多 1 条通知

  const KEY_TOKEN = "xijiu_access_token";
  const KEY_TS = "xijiu_access_token_ts";
  const KEY_UA = "xijiu_access_token_ua";
  const KEY_YAML = "xijiu_access_token_yaml";
  const KEY_COOLDOWN_UNTIL = "xijiu_access_token_cool_until";

  const req = typeof $request !== "undefined" ? $request : {};
  const headers = req.headers || {};
  const url = String(req.url || "");

  function pickHeader(h, name) {
    const target = name.toLowerCase();
    for (const k of Object.keys(h || {})) {
      if (k.toLowerCase() === target) return String(h[k] || "").trim();
    }
    return "";
  }

  function pref(key, fallback) {
    let v = "";
    try {
      v = $prefs.valueForKey(key);
    } catch (e) {}
    if (v == null || v === "") return fallback == null ? "" : String(fallback);
    return String(v);
  }

  function setPref(key, val) {
    try {
      $prefs.setValueForKey(String(val), key);
    } catch (e) {}
  }

  function yamlLine(token) {
    return (
      'access_token: "' +
      String(token).replace(/\\/g, "\\\\").replace(/"/g, '\\"') +
      '"'
    );
  }

  // 绝不对 token 做中间省略；通知/日志只用完整串
  const token = pickHeader(headers, "X-access-token");
  if (!token || token.length < 20) {
    $done({});
    return;
  }

  const now = Date.now();
  const name = pref("xijiu_account_name", "iPhone");
  const yml = yamlLine(token);
  const oldToken = pref(KEY_TOKEN, "");
  const changed = token !== oldToken;
  const ua = pickHeader(headers, "User-Agent");

  setPref(KEY_TOKEN, token);
  setPref(KEY_TS, now);
  setPref(KEY_YAML, yml);
  if (ua) setPref(KEY_UA, ua);

  // 只对 checkTodaySignIn 弹通知（其它请求只缓存）
  const isPrimary = /checkTodaySignIn/i.test(url);
  const coolUntil = Number(pref(KEY_COOLDOWN_UNTIL, "0")) || 0;
  const inCool = now < coolUntil;

  if (!isPrimary || inCool) {
    console.log(
      "[xijiu " +
        VERSION +
        "] silent | primary=" +
        isPrimary +
        " cool=" +
        inCool +
        " len=" +
        token.length
    );
    $done({});
    return;
  }

  setPref(KEY_COOLDOWN_UNTIL, now + COOLDOWN_MS);

  // ========== 日志：复制最稳的地方 ==========
  console.log("");
  console.log("########## xijiu " + VERSION + " FULL TOKEN ##########");
  console.log(token);
  console.log("########## len=" + token.length + " account=" + name + " ##########");
  console.log(yml);
  console.log("########## END ##########");
  console.log("");

  // ========== 通知：正文只有完整 token，禁止任何省略 ==========
  // 标题带 v4，方便你确认不是旧脚本
  $notify(
    "习酒TK·" + name + "·" + VERSION,
    "len=" + token.length + (changed ? " 新token" : " 同token") + " · 长按正文拷贝",
    token
  );

  const barkUrl = pref("xijiu_bark_url", "");
  const barkKey = pref("xijiu_bark_key", "");
  const barkBase = barkUrl || (barkKey ? "https://api.day.app/" + barkKey : "");
  if (barkBase) {
    $task
      .fetch({
        url: barkBase.replace(/\/$/, ""),
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          title: "习酒TK·" + name + "·" + VERSION,
          body: token,
          group: "习酒君品荟",
          copy: token,
          autoCopy: "1",
          level: "active",
        }),
      })
      .then(
        () => console.log("[xijiu] Bark ok"),
        (e) => console.log("[xijiu] Bark fail " + e)
      );
  }

  $done({});
})();
