/*
 * 习酒 · 查看缓存 token · v4
 * QX → 工具 → 脚本运行 → 运行本脚本
 * 标题须含 v4；正文 = 完整 token（无省略号）
 */
(function () {
  const VERSION = "v4";
  function pref(k) {
    try {
      const v = $prefs.valueForKey(k);
      return v == null ? "" : String(v);
    } catch (e) {
      return "";
    }
  }
  const token = pref("xijiu_access_token");
  const name = pref("xijiu_account_name") || "iPhone";
  if (!token || token.length < 20) {
    $notify("习酒TK·无缓存·" + VERSION, "请先打开签到页触发抓取", "无 token");
    console.log("[xijiu-show] empty");
    $done();
    return;
  }
  console.log("########## xijiu-show " + VERSION + " ##########");
  console.log(token);
  console.log("########## len=" + token.length + " ##########");
  $notify(
    "习酒TK·" + name + "·查看·" + VERSION,
    "len=" + token.length + " · 长按正文拷贝",
    token
  );
  $done();
})();
