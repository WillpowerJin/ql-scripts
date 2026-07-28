/*
 * 习酒 · 查看已缓存的 access_token（手动运行）
 *
 * 用法（Quantumult X）：
 *   首页 → 工具 → 脚本运行 → 新建 → 粘贴本脚本 → 运行
 * 或把本文件托管后用 task 方式执行。
 *
 * 作用：把上次抓到的完整 token 再弹一次通知 + 打日志，方便复制到 config.yaml。
 * 若从未抓到过，会提示先打开君品荟签到页。
 */
(function () {
  const KEY_TOKEN = "xijiu_access_token";
  const KEY_TS = "xijiu_access_token_ts";
  const KEY_YAML = "xijiu_access_token_yaml";

  function pref(key) {
    try {
      const v = $prefs.valueForKey(key);
      return v == null ? "" : String(v);
    } catch (e) {
      return "";
    }
  }

  function fmt(ts) {
    if (!ts) return "—";
    const n = Number(ts);
    const d = new Date(isNaN(n) ? ts : n);
    if (isNaN(d.getTime())) return String(ts);
    const pad = (x) => (x < 10 ? "0" + x : "" + x);
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

  const token = pref(KEY_TOKEN);
  const name = pref("xijiu_account_name") || "iPhone";
  const when = fmt(pref(KEY_TS));
  let yml = pref(KEY_YAML);
  if (!yml && token) {
    yml = 'access_token: "' + token.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
  }

  if (!token || token.length < 20) {
    const tip =
      "还没有缓存 token。\n\n请先：\n1) 配置 rewrite + MitM\n2) 打开微信 → 习酒君品荟 → 签到页\n3) 再运行本脚本";
    console.log("[xijiu-show] " + tip);
    $notify("习酒 access_token", "无缓存", tip);
    $done();
    return;
  }

  const body = [
    "账号: " + name,
    "抓取时间: " + when,
    "长度: " + token.length,
    "",
    "—— 完整 token（整段复制）——",
    token,
    "",
    "—— 粘贴到 config.yaml ——",
    yml,
    "",
    "提示: 长按本通知正文可拷贝；也可到 QX 日志搜索 [xijiu]",
  ].join("\n");

  console.log("[xijiu-show] ========== 缓存的 access_token ==========");
  console.log("[xijiu-show] account=" + name);
  console.log("[xijiu-show] time=" + when);
  console.log("[xijiu-show] token=" + token);
  console.log("[xijiu-show] yaml=" + yml);
  console.log("[xijiu-show] ========================================");

  $notify("习酒 access_token · " + name + "（查看）", when + " · " + token.length + "字", body);

  // 若配置了 Bark，查看时也推一份方便复制
  let barkUrl = pref("xijiu_bark_url");
  const barkKey = pref("xijiu_bark_key");
  if (!barkUrl && barkKey) barkUrl = "https://api.day.app/" + barkKey;
  if (barkUrl) {
    $task
      .fetch({
        url: barkUrl.replace(/\/$/, ""),
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          title: "习酒 access_token · " + name,
          body: body,
          group: "习酒君品荟",
          copy: token,
          autoCopy: "1",
        }),
      })
      .then(
        () => console.log("[xijiu-show] Bark ok"),
        (e) => console.log("[xijiu-show] Bark fail " + e)
      );
  }

  $done();
})();
