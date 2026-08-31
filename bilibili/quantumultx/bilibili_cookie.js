/*
 * B 站 Cookie 抓取 · Quantumult X · v1
 *
 * 打开哔哩哔哩 App（MITM 已开）后自动从请求头抠 SESSDATA / bili_jct / DedeUserID，
 * 写入 $prefs，并弹通知方便贴到青龙 BILI_COOKIE。
 *
 * rewrite：
 *   ^https?:\/\/app\.bilibili\.com\/x\/(resource\/fingerprint|v2\/account\/myinfo)
 *   url script-request-header bilibili_cookie.js
 *
 * MITM：app.bilibili.com
 *
 * $prefs：
 *   bili_cookie          精简 Cookie（青龙直接贴）
 *   bili_cookie_full     原始 Cookie
 *   bili_access_token    URL 里的 access_key（有则写入）
 *   bili_mid
 */
(function () {
  const VERSION = "v1";
  const COOLDOWN_MS = 5 * 60 * 1000;

  const KEY_COOKIE = "bili_cookie";
  const KEY_FULL = "bili_cookie_full";
  const KEY_TOKEN = "bili_access_token";
  const KEY_MID = "bili_mid";
  const KEY_TS = "bili_cookie_ts";
  const KEY_COOL = "bili_cookie_cool_until";

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

  function parseCookie(str) {
    const out = {};
    String(str || "")
      .split(";")
      .forEach(function (part) {
        const i = part.indexOf("=");
        if (i < 0) return;
        const k = part.slice(0, i).trim();
        const v = part.slice(i + 1).trim();
        if (k) out[k] = v;
      });
    return out;
  }

  function queryVal(u, name) {
    const m = new RegExp("[?&]" + name + "=([^&#]*)", "i").exec(u);
    return m ? decodeURIComponent(m[1]) : "";
  }

  const raw = pickHeader(headers, "Cookie");
  const jar = parseCookie(raw);
  const sess = jar.SESSDATA || "";
  const jct = jar.bili_jct || "";
  const mid = jar.DedeUserID || queryVal(url, "mid") || "";
  const token = queryVal(url, "access_key") || queryVal(url, "access_token");

  if (!sess || !jct) {
    $done({});
    return;
  }

  const slim = [
    "SESSDATA=" + sess,
    "bili_jct=" + jct,
    mid ? "DedeUserID=" + mid : "",
    jar.DedeUserID__ckMd5 ? "DedeUserID__ckMd5=" + jar.DedeUserID__ckMd5 : "",
    jar.sid ? "sid=" + jar.sid : "",
  ]
    .filter(Boolean)
    .join("; ");

  const now = Date.now();
  const old = pref(KEY_COOKIE, "");
  const changed = slim !== old;
  const coolUntil = Number(pref(KEY_COOL, "0")) || 0;
  const inCool = now < coolUntil && !changed;

  setPref(KEY_COOKIE, slim);
  setPref(KEY_FULL, raw);
  setPref(KEY_MID, mid);
  setPref(KEY_TS, now);
  if (token) setPref(KEY_TOKEN, token);

  console.log("");
  console.log("########## bili-cookie " + VERSION + " ##########");
  console.log("mid=" + mid);
  console.log("changed=" + changed);
  console.log("cookie=" + slim);
  if (token) console.log("access_key=" + token);
  console.log("########## END ##########");
  console.log("");

  if (inCool) {
    $done({});
    return;
  }
  setPref(KEY_COOL, now + COOLDOWN_MS);

  $notify(
    "📺 B站Cookie·" + VERSION,
    (changed ? "已更新" : "已缓存") + (mid ? " · mid=" + mid : ""),
    slim
  );

  $done({});
})();
