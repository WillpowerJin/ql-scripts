/*
 * 习酒 · 君品荟 —— Quantumult X 抓 access_token（v3）
 *
 * 解决：
 *   · 连弹多条相同通知 → 只处理 checkTodaySignIn；全局 3 分钟最多 1 条通知
 *   · token 显示不全 → 通知正文「只放 token 本身」（iOS 会截断长正文，
 *     前面若再加说明，token 更容易被砍掉）
 *
 * 复制方式：
 *   1) 通知：长按正文 → 拷贝（正文=完整 token）
 *   2) 日志：搜 [xijiu] → 复制 token= 后整行
 *   3) show 脚本再弹一次
 *
 * rewrite 请用（务必改掉整站匹配）：
 *   ^https?:\/\/fm\.exijiu\.com\/api\/customer\/daily\/checkTodaySignIn
 */
(function () {
  const VERSION = "v3";
  // 任意成功通知后，3 分钟内不再弹（彻底防刷）
  const COOLDOWN_MS = 3 * 60 * 1000;

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
    const safe = String(token).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    return 'access_token: "' + safe + '"';
  }

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

  // 始终静默更新缓存
  setPref(KEY_TOKEN, token);
  setPref(KEY_TS, now);
  setPref(KEY_YAML, yml);
  const ua = pickHeader(headers, "User-Agent");
  if (ua) setPref(KEY_UA, ua);

  // 仅对「今日是否已签」接口发通知，其它带 token 的请求只缓存
  // （签到页会打很多 fm 接口，只认这一个可从源头少触发）
  const isPrimary =
    /\/api\/customer\/daily\/checkTodaySignIn/i.test(url) ||
    // 兼容 query 写在 path 后、或大小写差异
    /checkTodaySignIn/i.test(url);

  // 全局冷却：3 分钟内无论多少请求只通知 1 次
  const coolUntil = Number(pref(KEY_COOLDOWN_UNTIL, "0")) || 0;
  const inCooldown = now < coolUntil;
  const force = pref("xijiu_notify_always", "") === "1";

  let shouldNotify = isPrimary && (!inCooldown || force);
  // 强制模式下仍避免 10 秒内连发
  if (force && inCool && coolUntil - now > COOLDOWN_MS - 10 * 1000) {
    shouldNotify = false;
  }

  if (!shouldNotify) {
    console.log(
      "[xijiu " +
        VERSION +
        "] cache only | primary=" +
        isPrimary +
        " cool=" +
        inCool +
        " changed=" +
        changed +
        " len=" +
        token.length
    );
    $done({});
    return;
  }

  // 先写冷却，降低并发双发概率
  setPref(KEY_COOLDOWN_UNTIL, now + COOLDOWN_MS);

  // 日志：完整 token + yaml（日志一般不截断，优先从这里复制最稳）
  console.log("[xijiu " + VERSION + "] ===== COPY TOKEN BELOW =====");
  console.log("[xijiu] account=" + name);
  console.log("[xijiu] changed=" + changed + " len=" + token.length);
  console.log("[xijiu] token=" + token);
  console.log("[xijiu] yaml=" + yml);
  console.log("[xijiu] url=" + url);
  console.log("[xijiu " + VERSION + "] ===== END =====");

  // 通知正文 = 纯 token（不要加前后缀，否则 iOS 截断时先砍掉 token）
  // 标题里带长度，方便确认是否完整（常见约 80～100 字符）
  $notify(
    "习酒token·" + name + "·" + VERSION,
    "长按正文拷贝 · " + token.length + "字" + (changed ? " · 新" : " · 同"),
    token
  );

  // Bark：用 copy 字段，比通知更适合一键复制完整串
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
          title: "习酒token·" + name,
          // body 尽量短；真正要复制的放 copy
          body: token.length + "字 · 已自动复制字段\n" + yml,
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
        }),
      })
      .then(
        () => console.log("[xijiu] webhook ok"),
        (e) => console.log("[xijiu] webhook fail " + e)
      );
  }

  $done({});
})();
