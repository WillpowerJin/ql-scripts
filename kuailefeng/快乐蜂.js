// 当前脚本来自于  http://ql.xmox.cn 脚本库下载！
// 脚本库官方QQ群：1079418419
// 脚本库中的所有脚本文件均来自热心网友上传和互联网收集。
// 脚本库仅提供文件上传和下载服务，不提供脚本文件的审核。
// 您在使用脚本库下载的脚本时自行检查判断风险。
// 所涉及到的 账号安全、数据泄露、设备故障、软件违规封禁、财产损失等问题及法律风险，与脚本库无关！均由开发者、上传者、使用者自行承担。

//快乐蜂下载链接:https://h5.jisiba.com/yinliu/drainage.html
//配置环境变量klekey = z-tokem#cookie
//抓好包杀后台别上线不然要重新抓等一个月差不多了上去提5米起提低保项目只写了抽奖
// 延迟函数
function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ---------- 从青龙面板环境变量读取配置 ----------
const klekey = process.env.klekey;
if (!klekey) {
  console.error("错误：未找到环境变量 klekey，请按格式 'z-token#mycookie' 设置");
  process.exit(1);
}
const [zTokenRaw, myCookieRaw] = klekey.split('#');
if (!zTokenRaw || !myCookieRaw) {
  console.error("错误：klekey 格式不正确，应为 'z-token#mycookie'");
  process.exit(1);
}
const zToken = zTokenRaw.trim();
const myCookie = myCookieRaw.trim();

// 公共请求头（不含 Cookie，Cookie 在每次 fetch 中单独传入）
const baseHeaders = {
  "Host": "klf-api.lingdangshuo.com",
  "z-os-version": "26.5",
  "z-store": "1",
  "Accept": "*/*",
  "Accept-Language": "zh-Hans-CN;q=1",
  "Accept-Encoding": "gzip, deflate, br",
  "z-client": "1",
  "Content-Type": "application/json",
  "User-Agent": "BuzzBee/1.1.9 (iPhone; iOS 26.5; Scale/3.00)",
  "Connection": "keep-alive",
  "z-device": "209076",
  "z-version": "1.1.9",
  "z-token": zToken,
  "z-os": "2",
};

// ---------- 第一个任务：请求 /free 三次，间隔 6 秒 ----------
async function requestFreeTimes(times = 3, intervalSec = 6) {
  const freeUrl = "https://klf-api.lingdangshuo.com/v1/turntables/free";
  const freeBody = "GCTkzi72o4/SXui0WOkH3Q==";
  
  for (let i = 1; i <= times; i++) {
    console.log(`\n[FREE ${i}/${times}] 开始请求 ${freeUrl}`);
    try {
      const resp = await fetch(freeUrl, {
        method: "POST",
        headers: {
          ...baseHeaders,
          "Cookie": myCookie,
        },
        body: freeBody,
      });
      const data = await resp.json();
      console.log(`[FREE ${i}] 状态码: ${resp.status}, 返回数据:`, data);
    } catch (err) {
      console.error(`[FREE ${i}] 请求失败:`, err);
    }
    if (i < times) {
      console.log(`等待 ${intervalSec} 秒后继续下一个 /free 请求...`);
      await delay(intervalSec * 1000);
    }
  }
  console.log("\n/free 三次请求完成。\n");
}

// ---------- 第二个任务：原来的循环（30次，每次请求 /ad -> 获取 idHash -> 请求 /turntables/{idHash}，间隔2秒）----------
async function originalLoop() {
  const firstUrl = "https://klf-api.lingdangshuo.com/v1/turntables/ad";
  const firstBody = "oTsfhQ1rlHJLiKvNQwcTSn7txy+ryqMmXy3xgPc4N0igUN7X2AbLfJqz8QUPmkI+";
  const secondBody = "GCTkzi72o4/SXui0WOkH3Q==";
  const times = 25;
  const intervalMs = 2000;

  for (let i = 1; i <= times; i++) {
    console.log(`\n========== 原循环 第 ${i}/${times} 次 ==========`);

    try {
      // 1. 获取 idHash
      console.log(`[${i}] 请求 /ad 获取 idHash...`);
      const firstResp = await fetch(firstUrl, {
        method: "POST",
        headers: {
          ...baseHeaders,
          "Cookie": myCookie,
        },
        body: firstBody,
      });
      if (!firstResp.ok) {
        console.error(`[${i}] /ad 请求失败，状态码: ${firstResp.status}`);
        continue;
      }
      const firstData = await firstResp.json();
      console.log(`[${i}] /ad 返回:`, firstData);
      const idHash = firstData?.data?.idHash;
      if (!idHash) {
        console.error(`[${i}] 未获取到 idHash`);
        continue;
      }
      console.log(`[${i}] idHash: ${idHash}`);

      // 2. 请求第二个接口
      const secondUrl = `https://klf-api.lingdangshuo.com/v1/turntables/${idHash}`;
      console.log(`[${i}] 请求: ${secondUrl}`);
      const secondResp = await fetch(secondUrl, {
        method: "POST",
        headers: {
          ...baseHeaders,
          "Cookie": myCookie,
        },
        body: secondBody,
      });
      if (!secondResp.ok) {
        console.error(`[${i}] 第二个请求失败，状态码: ${secondResp.status}`);
      } else {
        const secondData = await secondResp.json();
        console.log(`[${i}] 第二个请求返回:`, secondData);
      }
    } catch (err) {
      console.error(`[${i}] 原循环出错:`, err);
    }

    if (i < times) {
      console.log(`等待 ${intervalMs/1000} 秒后继续...`);
      await delay(intervalMs);
    }
  }
  console.log("\n原循环全部完成。");
}

// ---------- 主流程：先执行 /free 三次（间隔6秒），再执行原来的循环（30次，间隔2秒） ----------
async function main() {
  console.log("=== 开始执行：先请求 /free 三次（间隔6秒） ===");
  await requestFreeTimes(3, 6);
  console.log("=== /free 部分结束，开始执行原循环（30次，间隔2秒） ===");
  await originalLoop();
  console.log("=== 全部任务执行完毕 ===");
}

// 启动
main().catch(err => {
  console.error("脚本异常退出:", err);
  process.exit(1);
});

// === 脚本来自于 http://ql.xmox.cn 脚本库 ===
