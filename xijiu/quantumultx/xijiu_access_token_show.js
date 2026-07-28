/*
 * 习酒 · 查看已缓存 access_token（手动运行）v3
 *
 * QX → 工具 → 脚本运行 → 粘贴本脚本或填 raw URL → 运行
 * 通知正文 = 纯 token，方便长按拷贝完整串
 */
(function () {
  const VERSION = "v3-show";

  function pref(key) {
    try {
      const v = $prefs.valueForKey(key);
      return v == null ? "" : String(v);
    } catch (e) {
      return "";
    }
  }

  const token = pref("xijiu_access_token");
  const name = pref("xijiu_account_name") || "iPhone";
  let yml = pref("xijiu_access_token_yaml");
  if (!yml && token) {
    yml =
      'access_token: "' +
      token.replace(/\\/g, "\\\\").replace(/"/g, '\\"') +
      '"';
  }

  if (!token || token.length < 20) {
    const tip =
      "无缓存。请先配置 rewrite（checkTodaySignIn）并打开君品荟签到页。";
    console.log("[xijiu-show] " + tip);
    $notify("习酒token", "无缓存", tip);
    $done();
    return;
  }

  console.log("[xijiu-show " + VERSION + "] token=" + token);
  console.log("[xijiu-show] yaml=" + yml);
  console.log("[xijiu-show] len=" + token.length);

  // 正文只有 token，避免被 iOS 截断
  $notify(
    "习酒token·" + name + "·查看",
    "长按正文拷贝 · " + token.length + "字",
    token
  );

  const barkUrl = pref("xijiu_bark_url");
  const barkKey = pref("xijiu_bark_key");
  const base = barkUrl || (barkKey ? "https://api.day.app/" + barkKey : "");
  if (base) {
    $task
      .fetch({
        url: base.replace(/\/$/, ""),
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          title: "习酒token·" + name,
          body: token.length + "字\n" + yml,
          group: "习酒君品荟",
          copy: token,
          autoCopy: "1",
        }),
      })
      .then(
        () => {},
        () => {}
      );
  }

  $done();
})();
