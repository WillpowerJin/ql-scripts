/*
 * B 站 Cookie 抓取 · Quantumult X · v2
 *
 * 打开哔哩哔哩 App（先从后台划掉再进首页 /「我的」）后，
 * 从请求头抠 SESSDATA / bili_jct / DedeUserID。
 * 即使 Cookie 不完整也会弹通知，方便判断重写有没有跑到。
 *
 * $prefs：bili_cookie / bili_cookie_full / bili_access_token / bili_mid
 */
(function () {
  const VERSION = "v2";
  const OK_COOL_MS = 5 * 60 * 1000;
  const BAD_COOL_MS = 60 * 1000;

  const KEY_COOKIE = "bili_cookie";
  const KEY_FULL = "bili_cookie_full";
  const KEY_TOKEN = "bili_access_token";
  const KEY_MID = "bili_mid";
  const KEY_TS = "bili_cookie_ts";
  const KEY_COOL = "bili_cookie_cool_until";
  const KEY_BAD_COOL = "bili_cookie_bad_cool";

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
        if (k) {
          out[k] = v;
          out[k.toLowerCase()] = v;
        }
      });
    return out;
  }

  function queryVal(u, name) {
    const m = new RegExp("[?&]" + name + "=([^&#]*)", "i").exec(u);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function pathOf(u) {
    const m = String(u).match(/^https?:\/\/[^/]+(\/[^?#]*)/i);
    return m ? m[1] : u.slice(0, 80);
  }

  const raw = pickHeader(headers, "Cookie");
  const jar = parseCookie(raw);
  const sess = jar.SESSDATA || jar.sessdata || "";
  const jct = jar.bili_jct || "";
  const mid =
    jar.DedeUserID ||
    jar.dedeuserid ||
    queryVal(url, "mid") ||
    queryVal(url, "uid") ||
    "";
  const token = queryVal(url, "access_key") || queryVal(url, "access_token");
  const path = pathOf(url);
  const complete = !!(sess && jct);

  console.log("");
  console.log("########## bili-cookie " + VERSION + " ##########");
  console.log("path=" + path);
  console.log(
    "hasCookie=" +
      !!raw +
      " SESSDATA=" +
      !!sess +
      " bili_jct=" +
      !!jct +
      " DedeUserID=" +
      !!mid +
      " access_key=" +
      !!token
  );
  if (raw) console.log("cookie_len=" + raw.length);
  console.log("########## END ##########");
  console.log("");

  if (token) setPref(KEY_TOKEN, token);
  if (mid) setPref(KEY_MID, mid);
  if (raw) setPref(KEY_FULL, raw);

  if (!complete) {
    const now = Date.now();
    const coolUntil = Number(pref(KEY_BAD_COOL, "0")) || 0;
    if (now < coolUntil) {
      $done({});
      return;
    }
    setPref(KEY_BAD_COOL, now + BAD_COOL_MS);
    const reason = token
      ? "这是 App 原生接口，只带 access_key，没有网页 SESSDATA（正常）"
      : "这次请求里没有 SESSDATA / bili_jct";
    $notify(
      "📺 B站Cookie·" + VERSION,
      "重写已命中，但还不是网页 Cookie",
      [
        reason,
        "",
        "路径: " + path,
        "Cookie头: " + (raw ? "有(" + raw.length + "字，多半是 buvid)" : "无"),
        "SESSDATA: " + (sess ? "有" : "无") + "  bili_jct: " + (jct ? "有" : "无"),
        "access_key: " + (token ? "有（已缓存）" : "无"),
        "",
        "请再打开 App 里带网页的页面：",
        "直播 / 漫画 / 我的→大会员",
        "出现「已缓存/已更新」才算抓到。",
      ].join("\n")
    );
    $done({});
    return;
  }

  const slim = [
    "SESSDATA=" + sess,
    "bili_jct=" + jct,
    mid ? "DedeUserID=" + mid : "",
    jar.DedeUserID__ckMd5 || jar.dedeuserid__ckmd5
      ? "DedeUserID__ckMd5=" + (jar.DedeUserID__ckMd5 || jar.dedeuserid__ckmd5)
      : "",
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
  setPref(KEY_TS, now);

  console.log("cookie=" + slim);
  if (token) console.log("access_key=" + token);

  if (inCool) {
    $done({});
    return;
  }
  setPref(KEY_COOL, now + OK_COOL_MS);

  $notify(
    "📺 B站Cookie·" + VERSION,
    (changed ? "已更新" : "已缓存") + (mid ? " · mid=" + mid : ""),
    slim
  );

  $done({});
})();
