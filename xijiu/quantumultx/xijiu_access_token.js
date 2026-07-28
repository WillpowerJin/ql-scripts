/*
 * 习酒 · 君品荟 —— QuantumultX access_token 调试版
 *
 * ⚠️ 临时调试用：命中 fm.exijiu.com 时无脑弹通知，列出全部请求头名字，
 *   以及疑似 token/access/auth 相关的头值前缀。用完记得换回生产版。
 */
(function () {
  const req = typeof $request !== "undefined" ? $request : {};
  const headers = req.headers || {};
  const keys = Object.keys(headers);
  const url = (req.url || "").slice(0, 80);

  let hit = "";
  for (const k of keys) {
    const lk = k.toLowerCase();
    if (lk.indexOf("token") >= 0 ||
        lk.indexOf("access") >= 0 ||
        lk.indexOf("auth") >= 0) {
      const v = String(headers[k] || "");
      hit += k + "=" + v.slice(0, 24) + "…(len=" + v.length + ")\n";
    }
  }

  $notify(
    "习酒调试",
    url || "(无 url)",
    "共 " + keys.length + " 个头\n" +
    "所有头名：" + keys.join(", ") + "\n\n" +
    "命中：\n" + (hit || "（无 token/access/auth 相关头）")
  );
  $done({});
})();
