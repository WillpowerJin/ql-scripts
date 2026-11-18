/**
 * 宜家 (IKEA) App / 小程序凭证自动抓取 (Quantumult X)
 *
 * 作用：打开宜家 App 或微信小程序，拦截会员中心请求，
 *       自动提取 Authorization Token 并弹窗通知与复制。
 */

const $ = new Env("宜家 Token 抓取");
const TOKEN_KEY = "IKEA_TOKEN";

!(async () => {
    if (typeof $request === "undefined") {
        $.msg($.name, "错误", "请在 rewrite_local 中调用本脚本");
        return;
    }

    let auth = "";

    // 从请求头 Header 提取 Authorization
    if ($request.headers) {
        auth = $request.headers["Authorization"] || $request.headers["authorization"] || "";
    }

    if (auth) {
        let token = auth.replace(/^Bearer\s+/i, "").trim();
        if (token.startsWith("eyJ")) {
            const oldToken = $.getdata(TOKEN_KEY);
            if (oldToken !== token) {
                $.setdata(token, TOKEN_KEY);
                $.msg(
                    "宜家 Token 抓取成功 🎉",
                    "已自动复制到手机剪贴板 📋",
                    "完整 Token 已直接写入系统剪贴板，可前往青龙或配置文件长按粘贴！",
                    { "update-pasteboard": token }
                );
                $.log(`[宜家] 获取到完整 Token:\n${token}`);
            }
        }
    }
})()
.catch((e) => {
    $.log(`[宜家] 抓包异常: ${e}`);
})
.finally(() => {
    $.done();
});

function Env(name) {
    return {
        name: name,
        log: (msg) => console.log(`[${name}] ${msg}`),
        msg: (title, sub, body, opts) => $notify(title, sub, body, opts),
        getdata: (key) => $prefs.valueForKey(key),
        setdata: (val, key) => $prefs.setValueForKey(val, key),
        done: () => $done({})
    };
}
