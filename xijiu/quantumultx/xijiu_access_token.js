/*
 * 习酒 · 君品荟 —— Quantumult X 自动抓 access_token
 *
 * 为何会「连弹很多条一样的通知」？
 *   签到页会对 fm.exijiu.com 同时发多路请求，每条都带同一个 X-access-token。
 *   并发时多个脚本实例都读到「旧缓存为空/旧值」，都以为 token 变了 → 连弹。
 *
 * 本版处理：
 *   1) 建议 rewrite 只匹配签到相关路径（见 snippet，减少触发次数）
 *   2) 防抖：同一 token 在 DEBOUNCE_MS 内只通知 / Bark / webhook 一次
 *   3) 未变化且在防抖窗内：静默写缓存，不刷屏
 *
 * 本地键值（可选）：
 *   xijiu_account_name   默认 iPhone
 *   xijiu_notify_always  1 = 防抖窗外也强制通知（仍防抖）
 *   xijiu_bark_url / xijiu_bark_key
 *   xijiu_webhook_url / xijiu_webhook_token
 */
(function () {
  // 同一 token 两分钟内只弹一次通知
  const DEBOUNCE_MS = 120 * 1000;

  const KEY_TOKEN = "xijiu_access_token";
  const KEY_TS = "xijiu_access_token_ts";
  const KEY_UA = "xijiu_access_token_ua";
  const KEY_YAML = "xijiu_access_token_yaml";
  // 防抖：上次「已发通知」的 token + 时间
  const KEY_NOTIFIED_TOKEN = "xijiu_access_token_notified";
  const KEY_NOTIFIED_TS = "xijiu_access_token_notified_ts";
  // 抢占锁：毫秒时间戳，避免并发双发
  const KEY_LOCK = "xijiu_access_token_lock";

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

  function setPref(key, val) {
    try {
      $prefs.setValueForKey(String(val), key);
    } catch (e) {}
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

  function yamlLine(token) {
    const safe = String(token).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    return 'access_token: "' + safe + '"';
  }

  function copyBody(name, token, when, changed) {
    return [
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
      "",
      "（同一 token 2 分钟内只通知一次，避免刷屏）",
    ].join("\n");
  }

  const token = pickHeader(headers, "X-access-token").trim();
  const ua = pickHeader(headers, "User-Agent");
  const url = req.url || "";

  if (!token || token.length < 20) {
    $done({});
    return;
  }

  const now = Date.now();
  const oldToken = pref(KEY_TOKEN, "");
  const changed = token !== oldToken;
  const name = pref("xijiu_account_name", "iPhone");
  const when = fmt(now);
  const yml = yamlLine(token);

  // 始终更新缓存（静默），方便 show 脚本随时复制
  setPref(KEY_TOKEN, token);
  setPref(KEY_TS, now);
  setPref(KEY_YAML, yml);
  if (ua) setPref(KEY_UA, ua);

  // —— 防抖 / 并发锁 ——
  const lastNotifiedToken = pref(KEY_NOTIFIED_TOKEN, "");
  const lastNotifiedTs = Number(pref(KEY_NOTIFIED_TS, "0")) || 0;
  const withinDebounce =
    lastNotifiedToken === token && now - lastNotifiedTs < DEBOUNCE_MS;

  const lockTs = Number(pref(KEY_LOCK, "0")) || 0;
  // 3 秒内已有实例在处理通知 → 本实例只缓存
  const locked = lockTs > 0 && now - lockTs < 3000;

  const notifyAlways = pref("xijiu_notify_always", "") === "1";

  // 默认：token 变了才通知；notify_always 时只要不在防抖窗也可通知
  let shouldNotify = changed || notifyAlways;
  if (withinDebounce || locked) {
    shouldNotify = false;
  }

  if (!shouldNotify) {
    // 精简日志，避免签到页十几条请求刷爆日志
    console.log(
      "[xijiu] skip notify | changed=" +
        changed +
        " debounce=" +
        withinDebounce +
        " lock=" +
        locked +
        " len=" +
        token.length
    );
    $done({});
    return;
  }

  // 先占锁 + 记防抖，尽量挡住并发兄弟实例
  setPref(KEY_LOCK, now);
  setPref(KEY_NOTIFIED_TOKEN, token);
  setPref(KEY_NOTIFIED_TS, now);

  const body = copyBody(name, token, when, changed);

  console.log("[xijiu] ========== access_token（通知 1 次）==========");
  console.log("[xijiu] account=" + name);
  console.log("[xijiu] time=" + when);
  console.log("[xijiu] len=" + token.length + " changed=" + changed);
  console.log("[xijiu] token=" + token);
  console.log("[xijiu] yaml=" + yml);
  console.log("[xijiu] url=" + url);
  console.log("[xijiu] ==============================================");

  $notify(
    "习酒 access_token · " + name,
    (changed ? "已更新 · " : "未变化 · ") + when + " · " + token.length + "字",
    body
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
          title: "习酒 access_token · " + name,
          body: body,
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
        () => console.log("[xijiu] webhook ok"),
        (e) => console.log("[xijiu] webhook fail " + e)
      );
  }

  $done({});
})();
