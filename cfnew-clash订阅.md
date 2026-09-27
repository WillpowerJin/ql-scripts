# cfnew Clash 订阅

cfnew 和 freesub 的家宽 / 前置代理是两套订阅，不要混在同一个仓库里。

测速间隔改这一份模板，不改 freesub：

`cfnew-acl4ssr-180.ini`

自动选择、故障转移、负载均衡，以及香港 / 日本 / 美国 / 台湾 / 新加坡 / 韩国，这 9 行里 `generate_204` 后面的数字就是间隔秒数，现在是 **180**。例如：

```ini
custom_proxy_group=♻️ 自动选择`url-test`.*`http://www.gstatic.com/generate_204`180,,50
```

v1.mk 读的是这份模板的线上地址：

https://gist.githubusercontent.com/WillpowerJin/c434d2de8ba3b60cd44db67486d6f505/raw/cfnew-acl4ssr-180.ini

电视从手机发送时用这条短链，21 个字符：

https://v1.mk/eweumE6

它跳到下面这条 382 字符的长链接。旧短链 `https://v1.mk/Mpmludu` 仍是 300 秒模板，不要用。

https://api.v1.mk/sub?target=clash&url=https%3A%2F%2Fcfnew-chinese.blackjin.ggff.net%2F52e3fa9f-f211-4c25-86ee-eb538dc7fcca&insert=false&config=https%3A%2F%2Fgist.githubusercontent.com%2FWillpowerJin%2Fc434d2de8ba3b60cd44db67486d6f505%2Fraw%2Fcfnew-acl4ssr-180.ini&emoji=true&list=false&xudp=false&udp=false&tfo=false&expand=true&scv=false&fdn=false&new_name=true&diyua=ShadowRocket

已核对生成结果：9 个测速组都是 `interval: 180`，没有残留的 300。导入后把 **🚀 节点选择** 选成 **♻️ 自动选择**。

在 Clash 里把订阅地址换成上面这条，更新配置，然后把 **🚀 节点选择** 选成 **♻️ 自动选择**。规则走的是「节点选择」，第一项就是自动选择。

地区组只能匹配名字里连续写着 HK、JP、US 这类字母的节点。Mia 那批节点在字母中间夹了不可见字符，进不了日本 / 美国 / 新加坡这些组（那些组里目前只剩 DIRECT）。**♻️ 自动选择** 包含全部节点，平时用这一组。

节点源仍是：

https://cfnew-chinese.blackjin.ggff.net/52e3fa9f-f211-4c25-86ee-eb538dc7fcca

这条原始链接是 Base64 的 VLESS，给 v2rayN / v2rayNG。不要把它直接贴进 Clash。

本地整份配置（不经过 v1.mk）在：

`/home/jin/scripts/cfnew-clash.yaml`

里面是 49 个 VLESS WebSocket 节点，外加自动选择分组。Mihomo 已检查过，配置可以加载。

---

## 自动测速间隔

cfnew 的 3 分钟已经写在 `cfnew-acl4ssr-180.ini` 里，数值是 **180**。再改的话改这 9 处，然后把同一份文件更新到上面的 gist，Clash 里再更新一次订阅。

v1.mk 链接上的 `interval` 参数是订阅多久重新下载一次（单位是小时），不是节点测速间隔。

下面这张表只对本地文件 `cfnew-clash.yaml` 有用，那份文件现在仍是 30 分钟，而且不是这条 v1.mk 订阅。要用那份本地文件并且改成 3 分钟，把 `cfnew_to_clash.py` 里的 `PROBE_INTERVAL` 改成 `180` 再生成。

每次测速，组里每个节点都会向 `http://www.gstatic.com/generate_204` 发一次请求，并计入 Cloudflare Worker 额度。现在「自动选择」里有 49 个节点：

| 间隔 | 大约请求量（只算正在使用的那一个自动组） | 适用 |
| --- | --- | --- |
| 300 秒（5 分钟，Clash 常见默认） | 约 1.4 万次/天 | 节点少、想尽快换到更快的 IP |
| **1800 秒（30 分钟）** | 约 2400 次/天 | 这套 Worker 节点的默认选择 |
| 3600 秒（1 小时） | 约 1200 次/天 | 好几台设备同时开着 |
| 86400 秒（1 天） | 约 49 次/天 | 额度紧。Joey 在 cfnew 里用这个避开请求暴涨 |

30 分钟的原因：Worker 自己的优选 IP 大约 15 分钟换一批（节点名里的时间就是这次优选的时间），Clash 不必跟着几分钟全量重测一遍。30 分钟够跟上延迟变化，又不会按默认 5 分钟把请求打满。

同时写死的另外三项：

- `timeout: 3000`：单个节点 3 秒没响应就记为超时，不用干等默认的 5 秒。
- `tolerance: 100`：新节点要比当前节点快 100 毫秒以上才切换，避免两个差不多的节点来回跳。
- `lazy: true`：这个分组没被选中时不测速。平时用「节点选择 → 自动选择」，就只测「自动选择」这一组。

想改间隔：编辑 `cfnew_to_clash.py` 里的 `PROBE_INTERVAL`，重新生成配置，再导入一次。分组上的手动测速不受这个间隔限制。节点当前这条连接失败时，客户端仍会换节点；间隔只决定多久重新比较「谁更快」。

---

## 分组

默认走 **节点选择**，它的第一项是 **自动选择**。

| 分组 | 行为 |
| --- | --- |
| 节点选择 | 手动总开关。留在「自动选择」即可 |
| 自动选择 | 全部节点里挑延迟最低的 |
| 香港自动 / 日本自动 / 新加坡自动 / 美国自动 / 欧洲自动 | 只在该地区里挑 |
| 韩国自动 / 加拿大自动 / 印尼自动 / 越南自动 | 该地区目前只有 1 个节点 |
| 其他自动 | 名字里没有地区代码的 3 个节点 |
| DIRECT | 直连 |

规则：本机地址直连，中国 IP 直连，其余走「节点选择」。

---

## 导入 Clash Verge

1. 打开 Clash Verge → **订阅** → **新建**。
2. 类型选 **本地（Local）**，名称例如 `cfnew`。
3. 选择文件 `/home/jin/scripts/cfnew-clash.yaml`，保存。
4. 点这份订阅，让它成为当前配置，再打开系统代理或虚拟网卡（TUN）。
5. 打开代理组，确认 **节点选择** 停在 **自动选择**。

Verge 导入本地文件时会复制一份进自己的配置目录。之后改 `cfnew-clash.yaml` 不会自动生效，需要再导入一次，或在订阅卡片里编辑并整份替换。

手机上的 Clash Meta / FlClash：用「从文件导入」选同一份 YAML，内核需要是 Mihomo（Clash Meta）。原版 Clash 不支持 VLESS。

---

## 刷新优选 IP

Worker 每次被拉取时会给出当时的优选结果。本地 YAML 是生成那一刻的快照。

```bash
cd /home/jin/scripts
python3 cfnew_to_clash.py
```

跑完后再按上面的步骤导入一次。脚本默认拉的就是本文开头那条链接。
