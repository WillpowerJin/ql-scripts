/**
 * 推广宝自动看广告领奖
 *
 * cron: 0 9 * * *
 * new Env('推广宝每日广告');
 *
 * 青龙环境变量（账号）：
 *   TGB_ACCOUNTS  推荐。JSON 数组，支持 name 备注，多账号
 *   或 TGB = 手机号#密码，一行一个账号（& 或换行分隔）
 *   或下列按索引对齐的变量（& 分隔多账号）：
 *     TGB_USER / TGB_PASS / TGB_NAME（可选）
 *
 * 青龙环境变量（Bark 通知）：
 *   BARK_URL   完整推送地址，如 https://api.day.app/你的Key/
 *   或 BARK_KEY + 可选 BARK_SERVER（默认 https://api.day.app）
 *   可选：BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL
 *
 * 其他环境变量：
 *   TGB_INVITE_CODE   邀请码（默认 000GHFAV）
 *   TGB_TIMEOUT       请求超时毫秒（默认 15000）
 *   TGB_MAX_RETRIES   网络错误重试次数（默认 3）
 *   TGB_RETRY_INTERVAL 重试间隔秒（默认 10）
 *   TGB_AD_WATCH_SECONDS 广告模拟观看秒数（默认 22）
 *   TGB_INTER_ACCOUNT_DELAY 账号间隔秒（默认 6）
 *
 * 依赖：axios
 *   青龙：依赖管理里添加 axios
 *   本地：npm install axios
 */

const axios = require('axios');
const fs = require('fs');
const path = require('path');
const { URLSearchParams } = require('url');

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------

const DEFAULT_UA = 'Mozilla/5.0 (Linux; Android 16; V2426A Build/BP2A.250605.031.A3_V000L1; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/134.0.6998.135 Mobile Safari/537.36 TuiGuangBaoAndroid/1.0.2';
const DEFAULT_BARK_SERVER = 'https://api.day.app';
const DEFAULT_INVITE_CODE = '000GHFAV';
const SCRIPT_DIR = path.dirname(require.main.filename);

const BASE_PLUGIN = 'https://tg.suewammes.com/plugin.php?id=view&modac=sign';
const LOGIN_URL = 'https://tg.suewammes.com/member.php?mod=logging&action=login&loginsubmit=yes&mobile=2';
const BIND_YQ_URL = 'https://tg.suewammes.com/plugin.php?id=xigua_hh:bindcode';
const LOGIN_PAGE_URL = 'https://tg.suewammes.com/member.php?mod=logging&action=login&mobile=2';

// ---------------------------------------------------------------------------
// 日志
// ---------------------------------------------------------------------------

function nowStr() {
    const d = new Date();
    return d.toLocaleString('zh-CN', { hour12: false });
}

function log(level, ...args) {
    const prefix = `[${nowStr()}] [${level}]`;
    if (level === 'ERROR') {
        console.error(prefix, ...args);
    } else if (level === 'WARN') {
        console.warn(prefix, ...args);
    } else {
        console.log(prefix, ...args);
    }
}

const logger = {
    debug: (...args) => { if (process.env.TGB_DEBUG === '1') log('DEBUG', ...args); },
    info: (...args) => log('INFO', ...args),
    warn: (...args) => log('WARN', ...args),
    error: (...args) => log('ERROR', ...args),
};

// ---------------------------------------------------------------------------
// 配置
// ---------------------------------------------------------------------------

function env(name, defaultValue = '') {
    return (process.env[name] || defaultValue).trim();
}

function splitMulti(value) {
    if (!value) return [];
    return value.split(/[&\n]/).map(s => s.trim()).filter(Boolean);
}

function parseAccountsJson(raw) {
    const data = JSON.parse(raw);
    if (!Array.isArray(data)) {
        throw new Error('TGB_ACCOUNTS 必须是 JSON 数组');
    }
    return data.map((item, i) => {
        if (typeof item !== 'object' || item === null) {
            throw new Error(`TGB_ACCOUNTS[${i}] 必须是对象`);
        }
        const phone = String(item.phone || item.username || item.user || '');
        const pwd = String(item.password || item.pwd || item.pass || '');
        if (!phone || !pwd) {
            throw new Error(`TGB_ACCOUNTS[${i}] 缺少手机号或密码`);
        }
        return {
            name: String(item.name || phone),
            phone,
            password: pwd,
        };
    });
}

function parseAccountsFromEnv() {
    const accounts = [];

    // 1) JSON（推荐）
    const accountsJson = env('TGB_ACCOUNTS');
    if (accountsJson) {
        accounts.push(...parseAccountsJson(accountsJson));
        return accounts;
    }

    // 2) TGB 单行/多行：手机号#密码（& 或换行分隔）
    const tgb = env('TGB');
    if (tgb) {
        for (const line of splitMulti(tgb)) {
            const [phone, pwd] = line.split('#');
            if (!phone || !pwd) {
                throw new Error(`TGB 格式错误：${line}，应为 手机号#密码`);
            }
            accounts.push({ name: phone.trim(), phone: phone.trim(), password: pwd.trim() });
        }
        return accounts;
    }

    // 3) 按索引对齐：TGB_USER / TGB_PASS / TGB_NAME
    const users = splitMulti(env('TGB_USER') || env('TGB_USERNAME'));
    const passes = splitMulti(env('TGB_PASS') || env('TGB_PASSWORD'));
    const names = splitMulti(env('TGB_NAME'));
    const n = Math.max(users.length, passes.length);
    if (n > 0) {
        for (let i = 0; i < n; i++) {
            const phone = users[i];
            const pwd = passes[i];
            if (!phone || !pwd) {
                throw new Error(`TGB_USER/TGB_PASS 第 ${i + 1} 个账号信息不完整`);
            }
            accounts.push({
                name: names[i] || phone,
                phone,
                password: pwd,
            });
        }
        return accounts;
    }

    return accounts;
}

function loadNotifyFromEnv() {
    let barkUrl = env('BARK_URL') || env('BARK_PUSH');
    let barkKey = env('BARK_KEY') || env('BARK_DEVICE_KEY');

    if (barkUrl && !barkUrl.startsWith('http')) {
        barkKey = barkKey || barkUrl;
        barkUrl = '';
    }

    return {
        barkUrl,
        barkKey,
        barkServer: (env('BARK_SERVER', DEFAULT_BARK_SERVER)).replace(/\/$/, ''),
        barkGroup: env('BARK_GROUP', '推广宝'),
        barkSound: env('BARK_SOUND'),
        barkIcon: env('BARK_ICON'),
        barkLevel: env('BARK_LEVEL'),
    };
}

function loadConfigFromEnv() {
    const accounts = parseAccountsFromEnv();
    if (accounts.length === 0) {
        return null;
    }

    return {
        accounts,
        inviteCode: env('TGB_INVITE_CODE', DEFAULT_INVITE_CODE),
        timeout: parseInt(env('TGB_TIMEOUT', '15000'), 10),
        maxRetries: parseInt(env('TGB_MAX_RETRIES', '3'), 10),
        retryInterval: parseInt(env('TGB_RETRY_INTERVAL', '10'), 10),
        adWatchSeconds: parseInt(env('TGB_AD_WATCH_SECONDS', '22'), 10),
        interAccountDelay: parseInt(env('TGB_INTER_ACCOUNT_DELAY', '6'), 10),
        userAgent: env('TGB_UA', DEFAULT_UA),
        notify: loadNotifyFromEnv(),
    };
}

function loadConfigJson(filePath) {
    const raw = fs.readFileSync(filePath, 'utf-8');
    const cfg = JSON.parse(raw);
    if (!Array.isArray(cfg.accounts) || cfg.accounts.length === 0) {
        throw new Error('本地配置缺少 accounts 数组');
    }
    const envNotify = loadNotifyFromEnv();
    const envCfg = loadConfigFromEnv();
    return {
        accounts: cfg.accounts.map((a, i) => {
            const phone = String(a.phone || a.username || a.user || '');
            const pwd = String(a.password || a.pwd || a.pass || '');
            if (!phone || !pwd) {
                throw new Error(`本地配置 accounts[${i}] 缺少手机号或密码`);
            }
            return { name: String(a.name || phone), phone, password: pwd };
        }),
        inviteCode: env('TGB_INVITE_CODE') || cfg.inviteCode || DEFAULT_INVITE_CODE,
        timeout: parseInt(env('TGB_TIMEOUT') || cfg.timeout || '15000', 10),
        maxRetries: parseInt(env('TGB_MAX_RETRIES') || cfg.maxRetries || '3', 10),
        retryInterval: parseInt(env('TGB_RETRY_INTERVAL') || cfg.retryInterval || '10', 10),
        adWatchSeconds: parseInt(env('TGB_AD_WATCH_SECONDS') || cfg.adWatchSeconds || '22', 10),
        interAccountDelay: parseInt(env('TGB_INTER_ACCOUNT_DELAY') || cfg.interAccountDelay || '6', 10),
        userAgent: env('TGB_UA') || cfg.userAgent || DEFAULT_UA,
        notify: {
            barkUrl: envNotify.barkUrl || cfg.notify?.barkUrl || '',
            barkKey: envNotify.barkKey || cfg.notify?.barkKey || '',
            barkServer: (envNotify.barkServer || cfg.notify?.barkServer || DEFAULT_BARK_SERVER).replace(/\/$/, ''),
            barkGroup: env('BARK_GROUP') || cfg.notify?.barkGroup || '推广宝',
            barkSound: envNotify.barkSound || cfg.notify?.barkSound || '',
            barkIcon: envNotify.barkIcon || cfg.notify?.barkIcon || '',
            barkLevel: envNotify.barkLevel || cfg.notify?.barkLevel || '',
        },
    };
}

function resolveConfig() {
    const envCfg = loadConfigFromEnv();
    if (envCfg) {
        logger.info(`📦 已从环境变量加载 ${envCfg.accounts.length} 个账号`);
        return envCfg;
    }

    const local = path.join(SCRIPT_DIR, 'config.json');
    if (fs.existsSync(local)) {
        logger.info(`📦 使用本地配置: ${local}`);
        return loadConfigJson(local);
    }

    throw new Error(
        '未找到账号配置。\n' +
        '青龙：请设置环境变量 TGB_ACCOUNTS 或 TGB 或 TGB_USER/TGB_PASS\n' +
        '本地：复制 config.example.json 为 config.json 并填写'
    );
}

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function extractFormhash(html) {
    const m = html.match(/name="formhash"[^>]*value=["']([0-9a-f]{8})["']/i)
        || html.match(/formhash["']?\s*[:=]\s*["']?([0-9a-f]{8})["']?/i);
    return m ? m[1] : null;
}

function cookiesToString(setCookie) {
    if (!setCookie || !Array.isArray(setCookie)) return '';
    return setCookie.map(c => c.split(';')[0]).filter(Boolean).join('; ');
}

function buildHeaders(cookie = '', userAgent) {
    return {
        'User-Agent': userAgent,
        'Cookie': cookie,
        'x-requested-with': 'XMLHttpRequest',
        'Accept': '*/*',
        'sec-ch-ua-platform': '"Android"',
        'sec-ch-ua': '"Chromium";v="134", "Not:A-Brand";v="24", "Android WebView";v="134"',
        'sec-ch-ua-mobile': '?1',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-mode': 'cors',
        'sec-fetch-dest': 'empty',
        'accept-encoding': 'gzip, deflate',
        'accept-language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://tg.suewammes.com/plugin.php?id=xigua_hh&ac=invite',
    };
}

async function httpRequest(cfg, method, url, options = {}) {
    const { cookie = '', data = null, contentType = null } = options;
    const headers = buildHeaders(cookie, cfg.userAgent);
    if (contentType) {
        headers['Content-Type'] = contentType;
        headers['origin'] = 'https://tg.suewammes.com';
    }

    for (let attempt = 1; attempt <= cfg.maxRetries; attempt++) {
        try {
            const res = await axios({
                method,
                url,
                headers,
                data,
                timeout: cfg.timeout,
                maxRedirects: 0,
                validateStatus: () => true,
                responseType: 'text',
                transformResponse: [data => data],
            });
            let body = res.data;
            if (typeof body === 'string' && body.trim().startsWith('{')) {
                try {
                    body = JSON.parse(body);
                } catch (_) { /* keep string */ }
            }
            return { status: res.status, headers: res.headers, data: body };
        } catch (e) {
            const isLast = attempt === cfg.maxRetries;
            logger.warn(`🌐 请求失败（${attempt}/${cfg.maxRetries}）: ${e.message}`);
            if (isLast) throw e;
            logger.info(`⏳ ${cfg.retryInterval}秒后重试…`);
            await delay(cfg.retryInterval * 1000);
        }
    }
    throw new Error('请求重试耗尽');
}

// ---------------------------------------------------------------------------
// 业务
// ---------------------------------------------------------------------------

async function loginAccount(cfg, account) {
    logger.info(`[${account.name}] 📱 开始登录`);

    try {
        const pageRes = await httpRequest(cfg, 'GET', LOGIN_PAGE_URL);
        const pageHtml = typeof pageRes.data === 'string' ? pageRes.data : '';
        const formhash = extractFormhash(pageHtml);
        if (!formhash) {
            throw new Error('获取登录 formhash 失败');
        }
        const initCookies = cookiesToString(pageRes.headers['set-cookie']);

        const formData = new URLSearchParams();
        formData.append('formhash', formhash);
        formData.append('referer', 'https://tg.suewammes.com/plugin.php?id=xigua_hb&id=xigua_hb&needlogin=1&mobile=2');
        formData.append('fastloginfield', 'username');
        formData.append('cookietime', '2592000');
        formData.append('username', account.phone);
        formData.append('password', account.password);

        const loginRes = await httpRequest(cfg, 'POST', LOGIN_URL, {
            cookie: initCookies,
            data: formData.toString(),
            contentType: 'application/x-www-form-urlencoded',
        });

        const loginCookies = cookiesToString(loginRes.headers['set-cookie']);
        const finalCookie = [initCookies, loginCookies].filter(Boolean).join('; ');

        if (!/_auth=/.test(finalCookie)) {
            const body = typeof loginRes.data === 'string' ? loginRes.data : '';
            const errKey = (body.match(/密码错误|账号不存在|登录失败|密码为空|验证码错误|登录尝试次数过多/gi) || ['未知错误'])[0];
            throw new Error(`登录验证失败：${errKey}`);
        }

        logger.info(`[${account.name}] ✅ 登录成功`);
        return finalCookie;
    } catch (e) {
        logger.error(`[${account.name}] ❌ 登录失败：${e.message}`);
        return null;
    }
}

async function getSessionFormhash(cfg, cookie) {
    try {
        const res = await httpRequest(cfg, 'GET', BASE_PLUGIN, { cookie });
        const text = typeof res.data === 'string' ? res.data : '';
        const hash = extractFormhash(text);
        if (hash) {
            logger.debug(`[formhash] ${hash}`);
            return hash;
        }
        if (text.includes('登录账号') || text.includes('loginform')) {
            throw new Error('未登录，请检查账号密码');
        }
        throw new Error('提取不到 formhash');
    } catch (e) {
        logger.error(`❌ 获取 formhash 失败: ${e.message}`);
        return null;
    }
}

async function bindYqCode(cfg, cookie, account) {
    const fh = await getSessionFormhash(cfg, cookie);
    if (!fh) return { ok: false, message: '获取 formhash 失败' };

    try {
        const params = new URLSearchParams();
        params.append('formhash', fh);
        params.append('yqcode', cfg.inviteCode);

        const res = await httpRequest(cfg, 'POST', BIND_YQ_URL, {
            cookie,
            data: params.toString(),
            contentType: 'application/x-www-form-urlencoded',
        });

        let ret;
        if (typeof res.data === 'string') {
            ret = JSON.parse(res.data);
        } else {
            ret = res.data;
        }

        if (ret.code == 0) {
            logger.info(`[${account.name}] 🎊 邀请码 ${cfg.inviteCode} 绑定成功`);
            return { ok: true, message: '绑定成功' };
        } else if (ret.msg === '不能自己') {
            logger.info(`[${account.name}] ⚠️ ${ret.msg}`);
            return { ok: true, message: ret.msg };
        } else {
            logger.info(`[${account.name}] ℹ️ 邀请码绑定结果：${ret.msg}`);
            return { ok: false, message: ret.msg };
        }
    } catch (e) {
        logger.error(`[${account.name}] ❌ 绑定邀请码接口异常：${e.message}`);
        return { ok: false, message: e.message };
    }
}

async function getTaskStatus(cfg, cookie) {
    try {
        const res = await httpRequest(cfg, 'GET', `${BASE_PLUGIN}&submodac=status`, { cookie });
        const ct = res.headers['content-type'] || '';
        if (!ct.includes('json') && typeof res.data === 'string' && res.data.includes('loginform')) {
            throw new Error('登录态失效');
        }
        const data = typeof res.data === 'string' ? JSON.parse(res.data) : res.data;
        if (data.code != 0) throw new Error(`code:${data.code}`);
        return data.data;
    } catch (e) {
        logger.error(`❌ 查任务失败：${e.message}`);
        return null;
    }
}

async function getNextAdToken(cfg, cookie) {
    try {
        const fh = await getSessionFormhash(cfg, cookie);
        if (!fh) throw new Error('获取 formhash 失败');
        const params = new URLSearchParams();
        params.append('formhash', fh);
        const res = await httpRequest(cfg, 'POST', `${BASE_PLUGIN}&submodac=next_ad`, {
            cookie,
            data: params.toString(),
            contentType: 'application/x-www-form-urlencoded',
        });
        const data = typeof res.data === 'string' ? JSON.parse(res.data) : res.data;
        if (data.code != 0) throw new Error(data.msg || '获取广告失败');
        return data.data;
    } catch (e) {
        logger.error(`❌ 获取广告 Token 失败：${e.message}`);
        return null;
    }
}

async function submitAdComplete(cfg, cookie, token) {
    try {
        const fh = await getSessionFormhash(cfg, cookie);
        if (!fh) throw new Error('获取 formhash 失败');
        const params = new URLSearchParams();
        params.append('formhash', fh);
        params.append('token', token);
        const res = await httpRequest(cfg, 'POST', `${BASE_PLUGIN}&submodac=complete_ad`, {
            cookie,
            data: params.toString(),
            contentType: 'application/x-www-form-urlencoded',
        });
        const data = typeof res.data === 'string' ? JSON.parse(res.data) : res.data;
        if (data.code != 0) throw new Error(data.msg || '广告上报失败');
        return data.data;
    } catch (e) {
        logger.error(`❌ 广告上报失败：${e.message}`);
        return null;
    }
}

async function claimReward(cfg, cookie) {
    try {
        const fh = await getSessionFormhash(cfg, cookie);
        if (!fh) throw new Error('获取 formhash 失败');
        const params = new URLSearchParams();
        params.append('formhash', fh);
        const res = await httpRequest(cfg, 'POST', `${BASE_PLUGIN}&submodac=claim`, {
            cookie,
            data: params.toString(),
            contentType: 'application/x-www-form-urlencoded',
        });
        const data = typeof res.data === 'string' ? JSON.parse(res.data) : res.data;
        logger.info(`🎁 领奖返回：${data.msg}`);
        return data.data;
    } catch (e) {
        logger.error(`❌ 领奖失败：${e.message}`);
        return null;
    }
}

async function runSingleTask(cfg, account, idx) {
    logger.info(`\n──────── [${account.name}] 开始执行 ────────`);

    const cookie = await loginAccount(cfg, account);
    if (!cookie) {
        return { ok: false, message: '登录失败', via: 'password' };
    }

    await delay(1500);
    await bindYqCode(cfg, cookie, account);

    const result = { ok: false, message: '', viewed: 0, target: 0, claimed: false, via: 'password' };
    const maxLoops = 50;

    for (let loop = 0; loop < maxLoops; loop++) {
        const taskInfo = await getTaskStatus(cfg, cookie);
        if (!taskInfo) {
            result.message = '获取任务状态失败';
            break;
        }

        const { viewed_count, target_count, countdown_seconds, can_claim, claimed } = taskInfo;
        result.viewed = viewed_count;
        result.target = target_count;
        result.claimed = claimed;

        logger.info(`[${account.name}] 📊 进度：${viewed_count}/${target_count} | 可领奖:${can_claim} | 今日已领取:${claimed}`);

        if (can_claim && !claimed) {
            logger.info(`[${account.name}] 🎉 任务已满，准备领奖`);
            await delay(2000);
            const claim = await claimReward(cfg, cookie);
            if (claim) {
                result.ok = true;
                result.message = '领奖成功';
                result.claimed = true;
            } else {
                result.message = '领奖失败';
            }
            break;
        }

        if (viewed_count >= target_count) {
            result.ok = true;
            result.message = claimed ? '今日已领取' : '任务已完成';
            logger.info(`[${account.name}] ✅ ${result.message}`);
            break;
        }

        if (claimed) {
            result.ok = true;
            result.message = '今日已领取';
            logger.info(`[${account.name}] ✅ 今日已领取`);
            break;
        }

        if (countdown_seconds > 0) {
            logger.info(`[${account.name}] ⏳ 冷却等待 ${countdown_seconds} 秒`);
            await delay(countdown_seconds * 1000);
        }

        const adData = await getNextAdToken(cfg, cookie);
        if (!adData) {
            result.message = '获取广告失败';
            break;
        }

        logger.info(`[${account.name}] ▶ 获取 Token：${adData.token}，模拟观看 ${cfg.adWatchSeconds} 秒`);
        await delay(cfg.adWatchSeconds * 1000);

        const newTask = await submitAdComplete(cfg, cookie, adData.token);
        if (!newTask) {
            result.message = '广告上报失败';
            break;
        }

        logger.info(`[${account.name}] ✅ 广告上报成功，当前完成：${newTask.viewed_count}`);
        await delay(Math.floor(Math.random() * 3000) + 3000);
    }

    if (!result.message && !result.ok) {
        result.message = '执行未完成';
    }

    logger.info(`[${account.name}] 💚 本号流程结束`);
    return result;
}

// ---------------------------------------------------------------------------
// 通知
// ---------------------------------------------------------------------------

function buildBarkEndpoint(notify) {
    if (notify.barkUrl) {
        return notify.barkUrl.replace(/\/$/, '');
    }
    if (notify.barkKey) {
        return `${notify.barkServer}/${notify.barkKey}`;
    }
    return null;
}

async function sendBark(notify, title, body) {
    const endpoint = buildBarkEndpoint(notify);
    if (!endpoint) return;

    const payload = {
        title,
        body,
        group: notify.barkGroup || '推广宝',
    };
    if (notify.barkSound) payload.sound = notify.barkSound;
    if (notify.barkIcon) payload.icon = notify.barkIcon;
    if (notify.barkLevel) payload.level = notify.barkLevel;

    const postUrl = endpoint.endsWith('/push') ? endpoint : `${endpoint}/push`;

    try {
        const r = await axios.post(postUrl, payload, { timeout: 15000 });
        logger.info(`📣 Bark 已推送（HTTP ${r.status}）`);
    } catch (e) {
        logger.warn(`📣 Bark 推送失败: ${e.message}`);
    }
}

function formatSummary(results) {
    const lines = [];
    lines.push(`📅 ${new Date().toLocaleString('zh-CN', { hour12: false })}`);
    lines.push('');

    const okN = results.filter(r => r.result.ok).length;
    const failN = results.length - okN;

    results.forEach((item, i) => {
        const { account, result } = item;
        const ok = result.ok;
        const head = `${ok ? '✅' : '❌'} ${account.name}`;
        lines.push(head);
        lines.push(`   📊 进度：${result.viewed || 0}/${result.target || 0}`);

        if (result.claimed) {
            lines.push('   💰 今日已领奖');
        } else if (ok && result.message === '任务已完成') {
            lines.push('   ✅ 任务已完成，尚未领奖');
        } else if (ok) {
            lines.push(`   ✅ ${result.message}`);
        } else {
            const short = result.message.length <= 100 ? result.message : result.message.slice(0, 97) + '…';
            lines.push(`   ❌ ${short}`);
        }

        if (i < results.length - 1) lines.push('');
    });

    lines.push('');
    lines.push('────────');
    if (failN === 0) {
        lines.push(`📊 合计：${okN}/${results.length} 全部成功 🎉`);
    } else if (okN === 0) {
        lines.push(`📊 合计：${okN}/${results.length} 全部失败`);
    } else {
        lines.push(`📊 合计：成功 ${okN} · 失败 ${failN}（共 ${results.length} 号）`);
    }

    return lines.join('\n');
}

function formatNotifyTitle(results) {
    const okN = results.filter(r => r.result.ok).length;
    const n = results.length;
    if (n === 0) return '推广宝每日广告';
    if (okN === n) return `推广宝每日广告 ✅ ${okN}/${n}`;
    if (okN === 0) return `推广宝每日广告 ❌ 0/${n}`;
    return `推广宝每日广告 ⚠️ ${okN}/${n}`;
}

async function sendNotify(cfg, results) {
    if (!cfg.notify.barkUrl && !cfg.notify.barkKey) {
        logger.info('📣 未配置 Bark，跳过推送');
        return;
    }
    const summary = formatSummary(results);
    const title = formatNotifyTitle(results);
    await sendBark(cfg.notify, title, summary);
}

// ---------------------------------------------------------------------------
// 入口
// ---------------------------------------------------------------------------

async function main() {
    logger.info('🚀 推广宝自动看广告领奖');

    let cfg;
    try {
        cfg = resolveConfig();
    } catch (e) {
        logger.error(`❌ ${e.message}`);
        process.exit(2);
    }

    logger.info(`   账号 ${cfg.accounts.length} 个 · 通知 ${cfg.notify.barkUrl || cfg.notify.barkKey ? '开' : '关'}`);
    logger.info(`   邀请码：${cfg.inviteCode} · 广告观看：${cfg.adWatchSeconds}s`);

    const results = [];

    for (let i = 0; i < cfg.accounts.length; i++) {
        const account = cfg.accounts[i];
        try {
            const result = await runSingleTask(cfg, account, i + 1);
            results.push({ account, result });
        } catch (e) {
            logger.error(`[${account.name}] 💥 未处理异常: ${e.message}`);
            results.push({ account, result: { ok: false, message: e.message, viewed: 0, target: 0, claimed: false, via: 'error' } });
        }

        if (i < cfg.accounts.length - 1) {
            logger.info(`⏳ 等待 ${cfg.interAccountDelay} 秒后执行下一账号…`);
            await delay(cfg.interAccountDelay * 1000);
        }
    }

    logger.info('\n──────── 执行结果 ────────');
    logger.info(formatSummary(results));

    await sendNotify(cfg, results);

    const anyFail = results.some(r => !r.result.ok);
    process.exit(anyFail ? 1 : 0);
}

main().catch(e => {
    logger.error(`💥 程序异常: ${e.message}`);
    process.exit(2);
});
