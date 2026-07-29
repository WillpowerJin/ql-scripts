/*
 * 夸克 growth/reward 抓 kps/sign/vcode · Quantumult X · v3
 *
 * 目标 URL：
 *   https://drive-m.quark.cn/1/clouddrive/act/growth/reward?...&kps=...&sign=...&vcode=...
 *
 * 通知里只显示三个值（分行 + emoji）：
 *   🔑 kps=...
 *   ✍️ sign=...
 *   🔢 vcode=...
 *
 * 同时缓存到 $prefs：quark_kps / quark_sign / quark_vcode / quark_reward_ts
 * 完整 URL 打日志（搜 quark-reward v3）
 *
 * rewrite（贴到 [rewrite_local]）：
 *   ^https?:\/\/drive-m\.quark\.cn\/1\/clouddrive\/act\/growth\/reward
 *   url script-request-header quark_reward_capture.js
 *
 * MITM：drive-m.quark.cn
 */
(function () {
  const VERSION = "v3";
  const COOLDOWN_MS = 60 * 1000; // 同一 URL 60 秒内只弹一次

  const KEY_KPS = "quark_kps";
  const KEY_SIGN = "quark_sign";
  const KEY_VCODE = "quark_vcode";
  const KEY_TS = "quark_reward_ts";
  const KEY_COOLDOWN_UNTIL = "quark_reward_cool_until";

  const req = typeof $request !== "undefined" ? $request : {};
  const url = String(req.url || "");

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

  // 从 query 里抠单个参数（原始编码值）
  function getQuery(u, name) {
    const m = new RegExp("[?&]" + name + "=([^&#]*)").exec(u);
    return m ? m[1] : "";
  }

  // 只处理目标接口
  if (!/drive-m\.quark\.cn\/1\/clouddrive\/act\/growth\/reward/i.test(url)) {
    $done({});
    return;
  }

  // 三个值都保留 URL 编码原样，方便直接拼回请求 / 贴到青龙
  const kps = getQuery(url, "kps");
  const sign = getQuery(url, "sign");
  const vcode = getQuery(url, "vcode");

  if (!kps && !sign && !vcode) {
    console.log("[quark-reward " + VERSION + "] URL 里没有 kps/sign/vcode");
    $done({});
    return;
  }

  const now = Date.now();
  const coolUntil = Number(pref(KEY_COOLDOWN_UNTIL, "0")) || 0;
  const inCool = now < coolUntil;

  // 写缓存（即使冷却也更新，保证 $prefs 是最新的）
  if (kps) setPref(KEY_KPS, kps);
  if (sign) setPref(KEY_SIGN, sign);
  if (vcode) setPref(KEY_VCODE, vcode);
  setPref(KEY_TS, now);

  if (inCool) {
    console.log(
      "[quark-reward " + VERSION + "] silent (cool) kps_len=" + kps.length
    );
    $done({});
    return;
  }
  setPref(KEY_COOLDOWN_UNTIL, now + COOLDOWN_MS);

  // 通知正文：三行 + emoji（值保留原样，方便一次拷贝一行）
  const body =
    "🔑 kps=" + kps + "\n" +
    "✍️ sign=" + sign + "\n" +
    "🔢 vcode=" + vcode;

  // 日志：搜 quark-reward v3 拿完整值
  console.log("");
  console.log("########## quark-reward " + VERSION + " ##########");
  console.log("🔑 kps=" + kps);
  console.log("✍️ sign=" + sign);
  console.log("🔢 vcode=" + vcode);
  console.log("URL: " + url);
  console.log("########## END ##########");
  console.log("");

  $notify(
    "🚀 夸克签名·" + VERSION,
    "长按正文拷贝 · 三行分别对应 kps/sign/vcode",
    body
  );

  $done({});
})();
