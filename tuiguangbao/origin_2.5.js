// 当前脚本来自于  http://ql.xmox.cn 脚本库下载！
// 脚本库官方QQ群：1079418419
// 脚本库中的所有脚本文件均来自热心网友上传和互联网收集。
// 脚本库仅提供文件上传和下载服务，不提供脚本文件的审核。
// 您在使用脚本库下载的脚本时自行检查判断风险。
// 所涉及到的 账号安全、数据泄露、设备故障、软件违规封禁、财产损失等问题及法律风险，与脚本库无关！均由开发者、上传者、使用者自行承担。

/*
推广宝 完整版
环境变量 TGB：手机号#密码，一行一个账号
依赖：axios
单广告模拟观看22秒，满5条自动领奖
注册地址：https://tg.suewammes.com/plugin.php?id=xigua_hh&ac=invite&idu=23253622
*/
const axios = require('axios');
const UA = 'Mozilla/5.0 (Linux; Android 16; V2426A Build/BP2A.250605.031.A3_V000L1; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/134.0.6998.135 Mobile Safari/537.36 TuiGuangBaoAndroid/1.0.2';
const BASE_PLUGIN = 'https://tg.suewammes.com/plugin.php?id=view&modac=sign';
const LOGIN_URL = 'https://tg.suewammes.com/member.php?mod=logging&action=login&loginsubmit=yes&mobile=2';
const BIND_YQ_URL = 'https://tg.suewammes.com/plugin.php?id=xigua_hh:bindcode';
const INVITE_CODE = "000GHFAV";

axios.defaults.timeout = 15000;

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// 通用请求头
function getHeaders(cookie = '') {
    return {
        'User-Agent': UA,
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
        'Referer': 'https://tg.suewammes.com/plugin.php?id=xigua_hh&ac=invite'
    }
}

// 账号登录
async function loginAccount(phone, pwd) {
    try {
        console.log(`开始提交账号${phone}请求`);

        const loginPageUrl = 'https://tg.suewammes.com/member.php?mod=logging&action=login&mobile=2';
        const loginPageRes = await axios.get(loginPageUrl, { headers: getHeaders() });

        const pageHtml = typeof loginPageRes.data === 'string' ? loginPageRes.data : '';
        const fhMatch = pageHtml.match(/name="formhash"[^>]*value=["']([0-9a-f]{8})["']/i)
                     || pageHtml.match(/formhash["']?\s*[:=]\s*["']?([0-9a-f]{8})["']?/i);
        if (!fhMatch) {
            throw new Error('获取登录formhash失败');
        }
        const loginFormhash = fhMatch[1];

        const initCookies = (loginPageRes.headers['set-cookie'] || [])
            .map(c => c.split(';')[0]).join('; ');

        const formData = new URLSearchParams();
        formData.append('formhash', loginFormhash);
        formData.append('referer', 'https://tg.suewammes.com/plugin.php?id=xigua_hb&id=xigua_hb&needlogin=1&mobile=2');
        formData.append('fastloginfield', 'username');
        formData.append('cookietime', '2592000');
        formData.append('username', phone);
        formData.append('password', pwd);

        const loginRes = await axios({
            method: 'POST',
            url: LOGIN_URL,
            headers: {
                ...getHeaders(initCookies),
                'Content-Type': 'application/x-www-form-urlencoded',
                'origin': 'https://tg.suewammes.com',
                'upgrade-insecure-requests': '1'
            },
            data: formData.toString(),
            maxRedirects: 0,
            validateStatus: () => true
        });

        const loginCookies = (loginRes.headers['set-cookie'] || [])
            .map(c => c.split(';')[0]).join('; ');

        const finalCookie = [initCookies, loginCookies].filter(Boolean).join('; ');

        if (!/_auth=/.test(finalCookie)) {
            const body = typeof loginRes.data === 'string' ? loginRes.data : '';
            const errKey = (body.match(/密码错误|账号不存在|登录失败|密码为空|验证码错误|登录尝试次数过多/gi) || ['未知错误'])[0];
            throw new Error(`登录验证失败：${errKey}`);
        }

        console.log(`✅ ${phone} 登录成功`);
        return finalCookie;
    } catch (e) {
        console.log(`❌ ${phone} 登录失败：${e.message}`);
        return null;
    }
}

// 获取会话动态formhash
async function getSessionFormhash(cookie) {
    try {
        const res = await axios.get(BASE_PLUGIN, { headers: getHeaders(cookie) });
        const text = typeof res.data === 'string' ? res.data : '';
        const match = text.match(/name="formhash"[^>]*value=["']([0-9a-f]{8})["']/i)
                   || text.match(/formhash["']?\s*[:=]\s*["']?([0-9a-f]{8})["']?/i);
        if(match){
            const hash = match[1];
            console.log(`🔑 formhash: ${hash}`);
            return hash;
        }else{
            if (text.includes('登录账号') || text.includes('loginform')) {
                throw new Error("未登录，请检查账号密码");
            }
            throw new Error("提取不到formhash");
        }
    }catch(e){
        console.log(`❌ 获取formhash失败: ${e.message}`);
        return null;
    }
}

async function bindYqCode(cookie) {
    const fh = await getSessionFormhash(cookie);
    if(!fh) return;
    try {
        const params = new URLSearchParams();
        params.append('formhash', fh);
        params.append('yqcode', INVITE_CODE);
        const res = await axios({
            method: 'POST',
            url: BIND_YQ_URL,
            headers: {
                ...getHeaders(cookie),
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data: params.toString()
        });
        let ret;
        if(typeof res.data === 'string'){
            ret = JSON.parse(res.data);
        }else{
            ret = res.data;
        }
        if(ret.code == 0){
            console.log(`🎊 邀请码码${INVITE_CODE}绑定成功`);
        }else if(ret.msg === '不能自己'){
            console.log(`⚠️ ${ret.msg}：该账号自身就是${INVITE_CODE}，无需绑定`);
        }else{
            console.log(`ℹ️ 邀请码绑定结果 msg:${ret.msg}`);
        }
    } catch (e) {
        console.log(`❌ 绑定邀请码码接口异常：${e.message}`);
    }
}

async function getTaskStatus(cookie) {
    try {
        const res = await axios({ method: 'GET', url: `${BASE_PLUGIN}&submodac=status`, headers: getHeaders(cookie) });
        const ct = res.headers['content-type'] || '';
        if (!ct.includes('json') && typeof res.data === 'string' && res.data.includes('loginform')) {
            throw new Error('登录态失效，请重新登录');
        }
        if (res.data.code != 0) throw new Error(`code:${res.data.code}`);
        return res.data.data;
    } catch (e) {
        console.log(`❌ 查任务失败：${e.message}`);
        return null;
    }
}

async function getNextAdToken(cookie) {
    try {
        const fh = await getSessionFormhash(cookie);
        if (!fh) throw new Error('获取formhash失败');
        const params = new URLSearchParams();
        params.append('formhash', fh);
        const res = await axios({
            method: 'POST',
            url: `${BASE_PLUGIN}&submodac=next_ad`,
            headers: { ...getHeaders(cookie), 'Content-Type': 'application/x-www-form-urlencoded' },
            data: params.toString()
        });
        if (res.data.code != 0) throw new Error(res.data.msg || '获取广告失败');
        return res.data.data;
    } catch (e) {
        console.log(`❌ 获取广告Token失败：${e.message}`);
        return null;
    }
}

async function submitAdComplete(cookie, token) {
    try {
        const fh = await getSessionFormhash(cookie);
        if (!fh) throw new Error('获取formhash失败');
        const params = new URLSearchParams();
        params.append('formhash', fh);
        params.append('token', token);
        const res = await axios({
            method: 'POST',
            url: `${BASE_PLUGIN}&submodac=complete_ad`,
            headers: { ...getHeaders(cookie), 'Content-Type': 'application/x-www-form-urlencoded' },
            data: params.toString()
        });
        if (res.data.code != 0) throw new Error(res.data.msg || '广告上报失败');
        return res.data.data;
    } catch (e) {
        console.log(`❌ 广告上报失败：${e.message}`);
        return null;
    }
}

async function claimReward(cookie) {
    try {
        const fh = await getSessionFormhash(cookie);
        if (!fh) throw new Error('获取formhash失败');
        const params = new URLSearchParams();
        params.append('formhash', fh);
        const res = await axios({
            method: 'POST',
            url: `${BASE_PLUGIN}&submodac=claim`,
            headers: { ...getHeaders(cookie), 'Content-Type': 'application/x-www-form-urlencoded' },
            data: params.toString()
        });
        console.log(`🎁 领奖返回：${res.data.msg}`);
        return res.data.data;
    } catch (e) {
        console.log(`❌ 领奖失败：${e.message}`);
        return null;
    }
}

async function runSingleTask(phone, pwd, idx) {
    console.log(`\n========== 账号${idx} ${phone} 开始执行 ==========`);
    const cookie = await loginAccount(phone, pwd);
    if (!cookie) return;

    await delay(1500);
    await bindYqCode(cookie);

    while (true) {
        const taskInfo = await getTaskStatus(cookie);
        if (!taskInfo) break;
        const { viewed_count, target_count, countdown_seconds, can_claim, claimed } = taskInfo;
        console.log(`📊 进度：${viewed_count}/${target_count} | ✅可领奖:${can_claim} | 📅今日已领取:${claimed}`);

        if (can_claim && !claimed) {
            console.log(`🎉 任务已满，准备执行领奖！`);
            await delay(2000);
            await claimReward(cookie);
            console.log(`💰 ${phone}今日奖励领取完毕，任务结束`);
            break;
        }
        if (viewed_count >= target_count) {
            console.log(`✅ ${phone}今日任务全部完成`);
            break;
        }
        if (countdown_seconds > 0) {
            console.log(`⏳ 冷却等待 ${countdown_seconds} 秒`);
            await delay(countdown_seconds * 1000);
        }

        const adData = await getNextAdToken(cookie);
        if (!adData) break;
        console.log(`▶ 获取Token：${adData.token}，模拟22秒`);
        await delay(22000);

        const newTask = await submitAdComplete(cookie, adData.token);
        if (!newTask) break;
        console.log(`✅ 广告上报成功，当前完成数量：${newTask.viewed_count}`);
        await delay(Math.floor(Math.random() * 3000) + 3000);
    }
}

// 程序入口
(async function main() {
    const accountEnv = process.env.TGB || '';
    if (!accountEnv.trim()) {
        console.log('❌ 请配置环境变量 TGB，格式：手机号#密码，一行一个账号');
        process.exit(1);
    }
    const accList = accountEnv.split('\n').filter(i => i.trim());
    console.log(`成功加载账号总数：${accList.length}`);
    for (let i = 0; i < accList.length; i++) {
        const line = accList[i].trim();
        const [phone, pwd] = line.split('#');
        if (!phone || !pwd) {
            console.log(`❌ 账号${i+1}格式错误，正确格式：手机号#密码`);
            continue;
        }
        await runSingleTask(phone.trim(), pwd.trim(), i + 1);
        await delay(6000);
    }
    console.log('\n========== 全部账号执行结束 ==========');
})();
