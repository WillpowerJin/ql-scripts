/*
 * B 站每日任务 · Quantumult X · v1
 *
 * 对齐 Python daily.py：登录 / 观看 / 分享 / 投币（默认 0 保硬币）/
 * 银瓜子兑硬币 / 漫画签到 / 大会员月度福利（1、15 日）。
 *
 * Cookie 来源（按优先级）：
 *   1) 任务 argument：cookie=SESSDATA=...; bili_jct=...
 *   2) $prefs.bili_cookie（配合 bilibili_cookie.js 自动抓）
 *   3) $prefs.bili_accounts JSON 数组
 *
 * [task_local]
 * 30 7 * * * bilibili_daily.js, tag=B站每日任务, enabled=true
 *
 * 可选 argument：coin=0&silver2coin=1&manga=1&vip=1
 * $prefs：bili_coin_num / bili_silver2coin / bili_manga_sign / bili_vip_tasks
 */
const VERSION = "v1";
const UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_4_1 like Mac OS X) " +
  "AppleWebKit/621.1.15.10.7 (KHTML, like Gecko) Mobile/22E252 " +
  "BiliApp/84400100 os/ios model/iPhone mobi_app/iphone build/84400100";

const APPKEY = "27eb53fc9058f8c3";
const APPSEC = "c2ed53a74eeefe3cf99fbd01d8c9c375";

(async () => {
  try {
    await main();
  } catch (e) {
    console.log("[bili-daily] " + e);
    notify("B站每日任务", "异常", String(e && e.message ? e.message : e));
  } finally {
    $done();
  }
})();

function pref(key, fallback) {
  let v = "";
  try {
    v = $prefs.valueForKey(key);
  } catch (e) {}
  if (v == null || v === "") return fallback == null ? "" : String(fallback);
  return String(v);
}

function argMap() {
  const out = {};
  String(typeof $argument === "undefined" ? "" : $argument || "")
    .split("&")
    .forEach(function (p) {
      const i = p.indexOf("=");
      if (i < 0) return;
      const k = decodeURIComponent(p.slice(0, i).trim());
      const val = decodeURIComponent(p.slice(i + 1).trim());
      if (k) out[k] = val;
    });
  return out;
}

function flag(v, defaultOn) {
  if (v == null || v === "") return defaultOn;
  return !("0" === String(v) || "false" === String(v).toLowerCase());
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

function sleep(ms) {
  return new Promise(function (r) {
    setTimeout(r, ms);
  });
}

function md5(s) {
  function cmn(q, a, b, x, s, t) {
    a = add(add(a, q), add(x, t));
    return add((a << s) | (a >>> (32 - s)), b);
  }
  function ff(a, b, c, d, x, s, t) {
    return cmn((b & c) | (~b & d), a, b, x, s, t);
  }
  function gg(a, b, c, d, x, s, t) {
    return cmn((b & d) | (c & ~d), a, b, x, s, t);
  }
  function hh(a, b, c, d, x, s, t) {
    return cmn(b ^ c ^ d, a, b, x, s, t);
  }
  function ii(a, b, c, d, x, s, t) {
    return cmn(c ^ (b | ~d), a, b, x, s, t);
  }
  function add(x, y) {
    const lsw = (x & 0xffff) + (y & 0xffff);
    const msw = (x >> 16) + (y >> 16) + (lsw >> 16);
    return (msw << 16) | (lsw & 0xffff);
  }
  function num(n) {
    let s = "";
    for (let j = 0; j < 4; j++) {
      s += ("0" + ((n >> (j * 8)) & 0xff).toString(16)).slice(-2);
    }
    return s;
  }
  const msg = unescape(encodeURIComponent(s));
  const n = msg.length;
  const x = [];
  for (let i = 0; i < n; i++) {
    x[i >> 2] |= msg.charCodeAt(i) << ((i % 4) * 8);
  }
  x[n >> 2] |= 0x80 << ((n % 4) * 8);
  x[(((n + 8) >> 6) << 4) + 14] = n * 8;
  let a = 1732584193;
  let b = -271733879;
  let c = -1732584194;
  let d = 271733878;
  for (let i = 0; i < x.length; i += 16) {
    const oa = a,
      ob = b,
      oc = c,
      od = d;
    a = ff(a, b, c, d, x[i], 7, -680876936);
    d = ff(d, a, b, c, x[i + 1], 12, -389564586);
    c = ff(c, d, a, b, x[i + 2], 17, 606105819);
    b = ff(b, c, d, a, x[i + 3], 22, -1044525330);
    a = ff(a, b, c, d, x[i + 4], 7, -176418897);
    d = ff(d, a, b, c, x[i + 5], 12, 1200080426);
    c = ff(c, d, a, b, x[i + 6], 17, -1473231341);
    b = ff(b, c, d, a, x[i + 7], 22, -45705983);
    a = ff(a, b, c, d, x[i + 8], 7, 1770035416);
    d = ff(d, a, b, c, x[i + 9], 12, -1958414417);
    c = ff(c, d, a, b, x[i + 10], 17, -42063);
    b = ff(b, c, d, a, x[i + 11], 22, -1990404162);
    a = ff(a, b, c, d, x[i + 12], 7, 1804603682);
    d = ff(d, a, b, c, x[i + 13], 12, -40341101);
    c = ff(c, d, a, b, x[i + 14], 17, -1502002290);
    b = ff(b, c, d, a, x[i + 15], 22, 1236535329);
    a = gg(a, b, c, d, x[i + 1], 5, -165796510);
    d = gg(d, a, b, c, x[i + 6], 9, -1069501632);
    c = gg(c, d, a, b, x[i + 11], 14, 643717713);
    b = gg(b, c, d, a, x[i], 20, -373897302);
    a = gg(a, b, c, d, x[i + 5], 5, -701558691);
    d = gg(d, a, b, c, x[i + 10], 9, 38016083);
    c = gg(c, d, a, b, x[i + 15], 14, -660478335);
    b = gg(b, c, d, a, x[i + 4], 20, -405537848);
    a = gg(a, b, c, d, x[i + 9], 5, 568446438);
    d = gg(d, a, b, c, x[i + 14], 9, -1019803690);
    c = gg(c, d, a, b, x[i + 3], 14, -187363961);
    b = gg(b, c, d, a, x[i + 8], 20, 1163531501);
    a = gg(a, b, c, d, x[i + 13], 5, -1444681467);
    d = gg(d, a, b, c, x[i + 2], 9, -51403784);
    c = gg(c, d, a, b, x[i + 7], 14, 1735328473);
    b = gg(b, c, d, a, x[i + 12], 20, -1926607734);
    a = hh(a, b, c, d, x[i + 5], 4, -378558);
    d = hh(d, a, b, c, x[i + 8], 11, -2022574463);
    c = hh(c, d, a, b, x[i + 11], 16, 1839030562);
    b = hh(b, c, d, a, x[i + 14], 23, -35309556);
    a = hh(a, b, c, d, x[i + 1], 4, -1530992060);
    d = hh(d, a, b, c, x[i + 4], 11, 1272893353);
    c = hh(c, d, a, b, x[i + 7], 16, -155497632);
    b = hh(b, c, d, a, x[i + 10], 23, -1094730640);
    a = hh(a, b, c, d, x[i + 13], 4, 681279174);
    d = hh(d, a, b, c, x[i], 11, -358537222);
    c = hh(c, d, a, b, x[i + 3], 16, -722521979);
    b = hh(b, c, d, a, x[i + 6], 23, 76029189);
    a = hh(a, b, c, d, x[i + 9], 4, -640364487);
    d = hh(d, a, b, c, x[i + 12], 11, -421815835);
    c = hh(c, d, a, b, x[i + 15], 16, 530742520);
    b = hh(b, c, d, a, x[i + 2], 23, -995338651);
    a = ii(a, b, c, d, x[i], 6, -198630844);
    d = ii(d, a, b, c, x[i + 7], 10, 1126891415);
    c = ii(c, d, a, b, x[i + 14], 15, -1416354905);
    b = ii(b, c, d, a, x[i + 5], 21, -57434055);
    a = ii(a, b, c, d, x[i + 12], 6, 1700485571);
    d = ii(d, a, b, c, x[i + 3], 10, -1894986606);
    c = ii(c, d, a, b, x[i + 10], 15, -1051523);
    b = ii(b, c, d, a, x[i + 1], 21, -2054922799);
    a = ii(a, b, c, d, x[i + 8], 6, 1873313359);
    d = ii(d, a, b, c, x[i + 15], 10, -30611744);
    c = ii(c, d, a, b, x[i + 6], 15, -1560198380);
    b = ii(b, c, d, a, x[i + 13], 21, 1309151649);
    a = ii(a, b, c, d, x[i + 4], 6, -145523070);
    d = ii(d, a, b, c, x[i + 11], 10, -1120210379);
    c = ii(c, d, a, b, x[i + 2], 15, 718787259);
    b = ii(b, c, d, a, x[i + 9], 21, -343485551);
    a = add(a, oa);
    b = add(b, ob);
    c = add(c, oc);
    d = add(d, od);
  }
  return num(a) + num(b) + num(c) + num(d);
}

function appSign(params) {
  const body = {};
  Object.keys(params).forEach(function (k) {
    if (params[k] != null) body[k] = String(params[k]);
  });
  const qs = Object.keys(body)
    .sort()
    .map(function (k) {
      return k + "=" + body[k];
    })
    .join("&");
  body.sign = md5(qs + APPSEC);
  return body;
}

function fetchRaw(opts) {
  if (typeof $task !== "undefined" && $task.fetch) {
    return $task.fetch(opts);
  }
  return new Promise(function (resolve, reject) {
    const method = (opts.method || "GET").toUpperCase();
    const cb = function (err, resp, body) {
      if (err) reject(err);
      else
        resolve({
          statusCode: (resp && (resp.status || resp.statusCode)) || 0,
          headers: (resp && resp.headers) || {},
          body: body,
        });
    };
    if (typeof $httpClient === "undefined") {
      reject(new Error("需要 Quantumult X / Surge / Loon"));
      return;
    }
    if (method === "POST") $httpClient.post(opts, cb);
    else $httpClient.get(opts, cb);
  });
}

function notify(title, sub, body) {
  try {
    $notify(title, sub || "", body || "");
  } catch (e) {
    console.log(title + " " + sub + "\n" + body);
  }
}

function mark(ok, title, detail) {
  return "  " + (ok ? "✅" : "⚠️") + " " + title + (detail ? "：" + detail : "");
}

function Client(cookie, accessToken) {
  this.cookie = cookie;
  this.jar = parseCookie(cookie);
  this.accessToken = accessToken || "";
  this.user = {};
}

Client.prototype.req = function (method, url, opts) {
  opts = opts || {};
  let full = url;
  if (opts.params) {
    const qs = Object.keys(opts.params)
      .map(function (k) {
        return (
          encodeURIComponent(k) +
          "=" +
          encodeURIComponent(String(opts.params[k] == null ? "" : opts.params[k]))
        );
      })
      .join("&");
    full += (url.indexOf("?") >= 0 ? "&" : "?") + qs;
  }
  const headers = Object.assign(
    {
      "User-Agent": UA,
      Accept: "application/json, text/plain, */*",
      "Accept-Language": "zh-CN,zh;q=0.9",
      Cookie: this.cookie,
    },
    opts.headers || {}
  );
  const req = { url: full, method: method, headers: headers };
  if (opts.json != null) {
    req.body = JSON.stringify(opts.json);
    headers["Content-Type"] = "application/json";
  } else if (opts.data) {
    if (typeof opts.data === "string") req.body = opts.data;
    else {
      req.body = Object.keys(opts.data)
        .map(function (k) {
          return (
            encodeURIComponent(k) +
            "=" +
            encodeURIComponent(
              String(opts.data[k] == null ? "" : opts.data[k])
            )
          );
        })
        .join("&");
    }
    if (!headers["Content-Type"]) {
      headers["Content-Type"] = "application/x-www-form-urlencoded";
    }
  }
  return fetchRaw(req).then(
    function (resp) {
      try {
        return JSON.parse(resp.body);
      } catch (e) {
        return {
          code: -1,
          message: "非 JSON HTTP " + (resp.statusCode || ""),
          data: null,
        };
      }
    },
    function (err) {
      return { code: -1, message: "网络错误: " + err, data: null };
    }
  );
};

Client.prototype.me = async function () {
  const resp = await this.req(
    "GET",
    "https://api.bilibili.com/x/web-interface/nav"
  );
  if (resp.code !== 0 && resp.code !== "0") {
    return false;
  }
  this.user = resp.data || {};
  return !!this.user.isLogin;
};

Client.prototype.expReward = async function () {
  const resp = await this.req(
    "GET",
    "https://api.bilibili.com/x/member/web/exp/reward"
  );
  if (resp.code !== 0) return {};
  return resp.data || {};
};

Client.prototype.dynamicVideos = async function () {
  const mid = this.jar.DedeUserID || this.user.mid;
  const resp = await this.req(
    "GET",
    "https://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/dynamic_new",
    {
      params: { uid: mid, type_list: 8, from: "", platform: "web" },
    }
  );
  const cards = (resp.data || {}).cards || [];
  return Array.isArray(cards) ? cards : [];
};

Client.prototype.watch = async function (aid, bvid, cid) {
  const resp = await this.req(
    "POST",
    "https://api.bilibili.com/x/click-interface/web/heartbeat",
    {
      data: {
        aid: aid,
        cid: cid,
        bvid: bvid,
        mid: this.user.mid,
        csrf: this.jar.bili_jct,
        played_time: 1,
        real_played_time: 1,
        realtime: 1,
        start_ts: Math.floor(Date.now() / 1000),
        type: 3,
        dt: 2,
        play_type: 0,
        from_spmid: 0,
        spmid: 0,
        auto_continued_play: 0,
        refer_url: "https%3A%2F%2Ft.bilibili.com%2F",
        bsource: "",
      },
      headers: { Referer: "https://www.bilibili.com/video/" + bvid },
    }
  );
  return resp.code === 0;
};

Client.prototype.share = async function (aid) {
  const resp = await this.req(
    "POST",
    "https://api.bilibili.com/x/web-interface/share/add",
    { data: { aid: aid, csrf: this.jar.bili_jct } }
  );
  return resp.code === 0;
};

Client.prototype.followings = async function () {
  const mid = this.jar.DedeUserID || this.user.mid;
  const resp = await this.req(
    "GET",
    "https://api.bilibili.com/x/relation/followings",
    { params: { vmid: mid, ps: 20, order_type: "attention" } }
  );
  if (resp.code !== 0) return [];
  const lst = (resp.data || {}).list || [];
  return lst.map(function (x) {
    return Number(x.mid);
  }).filter(Boolean);
};

Client.prototype.randomAid = async function (mid) {
  const resp = await this.req(
    "GET",
    "https://api.bilibili.com/x/space/arc/search",
    {
      params: { mid: mid, ps: 10, pn: 1, order: "pubdate" },
      headers: { Referer: "https://space.bilibili.com/" + mid },
    }
  );
  if (resp.code !== 0) return 0;
  const vlist = (((resp.data || {}).list || {}).vlist) || [];
  if (!vlist.length) return 0;
  const item = vlist[Math.floor(Math.random() * vlist.length)];
  return Number(item.aid || 0);
};

Client.prototype.coinAdd = async function (aid) {
  let resp;
  if (this.accessToken) {
    resp = await this.req("POST", "https://app.bilibili.com/x/v2/view/coin/add", {
      data: {
        access_key: this.accessToken,
        aid: aid,
        multiply: 1,
        select_like: 0,
      },
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "app-key": "iphone",
      },
    });
  } else {
    resp = await this.req(
      "POST",
      "https://api.bilibili.com/x/web-interface/coin/add",
      {
        data: {
          aid: aid,
          multiply: 1,
          select_like: 0,
          cross_domain: "true",
          csrf: this.jar.bili_jct,
        },
        headers: { Referer: "https://www.bilibili.com" },
      }
    );
  }
  return resp.code === 0;
};

Client.prototype.silver2coin = async function () {
  const resp = await this.req(
    "POST",
    "https://api.live.bilibili.com/xlive/revenue/v1/wallet/silver2coin",
    {
      data: {
        csrf: this.jar.bili_jct,
        csrf_token: this.jar.bili_jct,
      },
    }
  );
  if (resp.code === 0) {
    const d = resp.data || {};
    return "兑换成功 +" + (d.coin != null ? d.coin : 1) + " 硬币";
  }
  if (resp.code === 403) return "未兑换: " + (resp.message || "");
  return "失败: " + (resp.message || resp.code);
};

Client.prototype.mangaSign = async function () {
  const resp = await this.req(
    "POST",
    "https://manga.bilibili.com/twirp/activity.v1.Activity/ClockIn",
    {
      data: { platform: "android" },
      headers: { Referer: "https://manga.bilibili.com" },
    }
  );
  const msg = String(resp.msg || resp.message || "");
  if (resp.code === 0) return "成功";
  if (/duplicate/i.test(msg) || msg.indexOf("已") >= 0) {
    return "今日已签 (" + (msg || resp.code) + ")";
  }
  return String(msg || resp.code);
};

Client.prototype.vipExtraExp = async function () {
  if (!this.accessToken) return "跳过(需 access_token)";
  const body = appSign({
    csrf: this.jar.bili_jct,
    ts: Math.floor(Date.now() / 1000),
    buvid: this.jar.Buvid || this.jar.buvid3 || "",
    mobi_app: "iphone",
    platform: "ios",
    appkey: APPKEY,
    access_key: this.accessToken,
  });
  const resp = await this.req(
    "POST",
    "https://api.bilibili.com/x/vip/experience/add",
    {
      data: body,
      headers: { "app-key": "iphone" },
    }
  );
  if (resp.code === 0) return "额外经验 +10";
  return "额外经验: " + (resp.message || resp.code);
};

Client.prototype.vipPrivilegeMonthly = async function () {
  const day = ("0" + new Date().getDate()).slice(-2);
  if (day !== "01" && day !== "15") return [];
  const vipType = Number(this.user.vipType || 0);
  const types = vipType === 2 ? [1, 2, 3, 4, 5, 6, 7] : [6, 7];
  const out = [];
  for (let i = 0; i < types.length; i++) {
    const t = types[i];
    const resp = await this.req(
      "POST",
      "https://api.bilibili.com/x/vip/privilege/receive",
      { data: { csrf: this.jar.bili_jct, type: t } }
    );
    if (resp.code === 0) out.push("福利 type=" + t + " 领取成功");
    else out.push("福利 type=" + t + ": " + (resp.message || ""));
    await sleep(400);
  }
  return out;
};

function pickVideo(cards) {
  if (!cards || !cards.length) return null;
  const item = cards[Math.floor(Math.random() * cards.length)];
  const desc = item.desc || {};
  let card = {};
  try {
    card = JSON.parse(item.card || "{}");
  } catch (e) {}
  return {
    aid: desc.rid,
    bvid: desc.bvid || card.bvid || "",
    cid: card.cid,
  };
}

async function runAccount(acc, cfg) {
  const lines = [];
  const client = new Client(acc.cookie, acc.access_token || "");
  const okLogin = await client.me();
  if (!okLogin) {
    lines.push("📺 B站每日任务 · " + (acc.name || "账号"));
    lines.push("────────────────");
    lines.push("❌ Cookie 已失效（打开 B 站 App 刷新，或重新扫码）");
    return { ok: false, need_cookie: true, lines: lines };
  }
  const u = client.user;
  const li = u.level_info || {};
  const uname = u.uname || acc.name || "账号";
  const money0 = Number(u.money || 0);
  lines.push("📺 B站每日任务 · " + uname);
  lines.push("────────────────");
  lines.push(
    "👤 等级 Lv" +
      li.current_level +
      "  |  经验 " +
      li.current_exp +
      "/" +
      li.next_exp +
      "  |  硬币 " +
      money0
  );
  lines.push("");

  const status = await client.expReward();
  const needWatch = !status.watch;
  const needShare = !status.share;
  const coinsDone = Number(status.coins || 0);
  const target = cfg.coin_num;
  const needCoinTimes = Math.max(0, target - Math.floor(coinsDone / 10));

  let watchDetail = needWatch ? "待执行" : "今日已完成";
  let shareDetail = needShare ? "待执行" : "今日已完成";
  if (needWatch || needShare) {
    const cards = await client.dynamicVideos();
    if (!cards.length) {
      if (needWatch) watchDetail = "动态无视频，跳过";
      if (needShare) shareDetail = "动态无视频，跳过";
    } else {
      const v = pickVideo(cards);
      if (needWatch && v && v.aid && v.cid && v.bvid) {
        const ok = await client.watch(v.aid, v.bvid, v.cid);
        watchDetail = ok ? "成功 " + v.bvid : "失败";
        await sleep(1000);
      }
      if (needShare && v && v.aid) {
        const ok = await client.share(v.aid);
        shareDetail = ok ? "成功" : "失败";
        await sleep(1000);
      }
    }
  }

  let money = Number(u.money || 0);
  let coinSuccess = 0;
  let coinDetail = "";
  if (target <= 0) {
    coinDetail = "已关闭（保硬币）";
  } else if (needCoinTimes <= 0) {
    coinDetail = "今日已完成或目标为 0";
  } else if (money <= 5) {
    coinDetail = "硬币不足（≤5 停止）";
  } else {
    const mids = await client.followings();
    if (!mids.length) {
      coinDetail = "无关注列表，请先关注一些 UP";
    } else {
      let attempts = 0;
      const maxAttempts = needCoinTimes + 10;
      while (coinSuccess < needCoinTimes && attempts < maxAttempts) {
        attempts += 1;
        if (money <= 5) {
          coinDetail =
            "成功" + coinSuccess + "/" + needCoinTimes + "（硬币不足停）";
          break;
        }
        let aid = 0;
        for (let t = 0; t < 6 && !aid; t++) {
          const mid = mids[Math.floor(Math.random() * mids.length)];
          aid = await client.randomAid(mid);
        }
        if (!aid) {
          await sleep(300);
          continue;
        }
        if (await client.coinAdd(aid)) {
          coinSuccess += 1;
          money -= 1;
        }
        await sleep(500);
      }
      if (!coinDetail) {
        coinDetail =
          "本次 +" +
          coinSuccess +
          "/" +
          needCoinTimes +
          "（尝试 " +
          attempts +
          " 次）";
      }
    }
  }

  const extras = [];
  if (cfg.silver2coin) {
    const s2c = await client.silver2coin();
    extras.push(
      /成功/.test(s2c)
        ? mark(true, "银瓜子兑硬币", s2c)
        : "  ℹ️ 银瓜子兑硬币：" + s2c
    );
  }
  if (cfg.manga) {
    const ms = await client.mangaSign();
    const mangaOk = /成功|已签|重复|duplicate/i.test(ms);
    extras.push(mark(mangaOk, "漫画签到", ms));
  }
  if (cfg.vip && Number(u.vipStatus || 0) === 1) {
    const ve = await client.vipExtraExp();
    extras.push(
      /成功|\+10/.test(ve)
        ? mark(true, "大会员额外经验", ve)
        : "  ℹ️ 大会员额外经验：" + ve
    );
    const priv = await client.vipPrivilegeMonthly();
    priv.forEach(function (p) {
      extras.push(mark(/成功/.test(p), "大会员月度福利", p));
    });
  }

  const status2 = await client.expReward();
  const watchOk = !!status2.watch;
  const shareOk = !!status2.share;
  const coinsExp = Number(status2.coins || 0);
  const coinOk = coinsExp >= Math.min(50, target * 10) || target === 0;
  const loginOk = !!status2.login || watchOk;

  lines.push("📋 主站经验");
  lines.push(mark(loginOk, "登录"));
  lines.push(mark(watchOk, "观看", needWatch ? watchDetail : "今日已完成"));
  lines.push(mark(shareOk, "分享", needShare ? shareDetail : "今日已完成"));
  let coinLine;
  if (target === 0) coinLine = coinDetail || "已关闭（保硬币）";
  else {
    coinLine =
      Math.floor(coinsExp / 10) +
      "/" +
      target +
      " 枚 · 经验 " +
      coinsExp +
      "/" +
      target * 10 +
      (coinDetail ? " · " + coinDetail : "");
  }
  lines.push(mark(coinOk, "投币", coinLine));

  if (extras.length) {
    lines.push("");
    lines.push("🎁 扩展任务");
    extras.forEach(function (x) {
      lines.push(x);
    });
  }

  lines.push("");
  const core = loginOk && watchOk && shareOk && coinOk;
  if (core) {
    lines.push(
      target === 0
        ? "🏁 完成度：主站任务已完成 ✅（投币已关，保硬币）"
        : "🏁 完成度：主站经验任务已完成 ✅"
    );
  } else {
    const missing = [];
    if (!loginOk) missing.push("登录");
    if (!watchOk) missing.push("观看");
    if (!shareOk) missing.push("分享");
    if (!coinOk) missing.push("投币(" + Math.floor(coinsExp / 10) + "/" + target + ")");
    lines.push("🏁 完成度：主站未完成 ⚠️  缺 " + missing.join("、"));
  }
  return { ok: true, core_done: core, need_cookie: false, lines: lines };
}

function loadAccounts(args) {
  const accounts = [];
  if (args.cookie) {
    accounts.push({
      name: args.name || "argument",
      cookie: args.cookie,
      access_token: args.access_token || args.token || "",
    });
    return accounts;
  }
  const rawJson = pref("bili_accounts", "");
  if (rawJson) {
    try {
      const arr = JSON.parse(rawJson);
      if (Array.isArray(arr)) {
        arr.forEach(function (item, i) {
          if (!item || !item.cookie) return;
          accounts.push({
            name: item.name || "account_" + (i + 1),
            cookie: item.cookie,
            access_token: item.access_token || item.accessToken || "",
          });
        });
      }
    } catch (e) {
      console.log("[bili-daily] bili_accounts JSON 无效: " + e);
    }
  }
  const ck = pref("bili_cookie", "");
  if (ck && !accounts.length) {
    accounts.push({
      name: pref("bili_name", "主号"),
      cookie: ck,
      access_token: pref("bili_access_token", ""),
    });
  }
  return accounts;
}

async function main() {
  const args = argMap();
  const cfg = {
    coin_num: Math.max(
      0,
      Math.min(
        5,
        parseInt(args.coin != null ? args.coin : pref("bili_coin_num", "0"), 10) ||
          0
      )
    ),
    silver2coin: flag(
      args.silver2coin != null ? args.silver2coin : pref("bili_silver2coin", "1"),
      true
    ),
    manga: flag(args.manga != null ? args.manga : pref("bili_manga_sign", "1"), true),
    vip: flag(args.vip != null ? args.vip : pref("bili_vip_tasks", "1"), true),
  };
  console.log(
    "[bili-daily " +
      VERSION +
      "] 投币=" +
      cfg.coin_num +
      "（0=保硬币） 银瓜子兑换=" +
      (cfg.silver2coin ? "开" : "关")
  );

  const accounts = loadAccounts(args);
  if (!accounts.length) {
    const msg = [
      "未找到 Cookie。",
      "1) 打开 B 站 App（已配 rewrite）自动抓取",
      "2) 或任务 argument: cookie=SESSDATA=...; bili_jct=...",
    ].join("\n");
    notify("B站每日任务 · 需要 Cookie", "", msg);
    console.log(msg);
    return;
  }

  const summaries = [];
  let anyFail = false;
  let needCookie = false;
  for (let i = 0; i < accounts.length; i++) {
    const acc = accounts[i];
    const jar = parseCookie(acc.cookie);
    if (!jar.SESSDATA || !jar.bili_jct) {
      summaries.push("❌ " + (acc.name || "账号") + " Cookie 缺 SESSDATA/bili_jct");
      anyFail = true;
      needCookie = true;
      continue;
    }
    const res = await runAccount(acc, cfg);
    summaries.push((res.lines || []).join("\n"));
    if (res.need_cookie) {
      needCookie = true;
      anyFail = true;
    } else if (!res.ok || res.core_done === false) {
      anyFail = true;
    }
  }

  const body = summaries.join("\n\n");
  console.log(body);
  let title = "B站每日任务 · 完成 ✅";
  if (needCookie) title = "B站每日任务 · 需要获取 Cookie";
  else if (anyFail) title = "B站每日任务 · 有未完成项";
  notify(title, cfg.coin_num === 0 ? "投币已关 · 保硬币" : "投币 " + cfg.coin_num, body);
}
