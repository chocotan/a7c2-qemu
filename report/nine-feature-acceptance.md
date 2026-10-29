# 九项交付与验收清单

本清单区分现有证据与完整交付要求。当前尚无已验收的原固件照片、录像或真实合焦。
所有运行只用本机隔离QEMU与虚拟磁盘；不接真机、真实无线或物理SD。

最新已发布独立包提交为 **d69e839b07d8d6df39b17522036ceff6d56ac0f8**：单卡热插拔已正式选择性移交、默认启用并完成包内两轮真实GTK/四状态导出/原完整文件内容消费，以及默认profile沿上一卡的补验；完整host279pass/33skip/73subtests。首次失败与安全恢复保留。Task45/64已完成该有限范围；照片录像、镜头/CMOS/AF/编码与REC高层状态仍未通过。下文基线提交与“进行中”段落按历史阶段保留。

最新独立包 `final/a7c2-qemu/` 已完成自身 QEMU 构建/安装、实际单 GTK 中文首设与原 HUD/MENU、原 SD 数据库/XML 写入保存、同 VM 网络后端 ON/OFF/ON 和两轮跨 VM 卡回载。main 直接核画面和原 manifest，三份 128 MiB 卡整 SHA 一致、原输入未变、独立 fsck 全部 0。源码及验收记录已推送 `01b59eab958ed8f80b0122296671a87e88ff6799`；本成果后续 SD WIP 未移入该快照。下文历史实验按当时范围保留。

后续配置快照/稳定实例恢复/真实GTK确认重初始化也已选择性移交并在独立包实际三轮验收，提交47a780e；内部恢复环境变量隔离修复三项host回归与包内262 passed/33 skipped/71 subtests后发布421cda8。随后包内实际原菜单25/2改值、完整关闭并重开GTK已由main核原API/file、实际选用cpio两seed、SD摘要/fsck，有限说明发布b350961；第二GTK截图过早，原页面视觉复验不计通过。首设完成状态和全部设置覆盖仍未完成。旧摘要对应当时阶段；SD热插拔正在另做Task64选择性移交，不能把native结果称为独立包已验。

| 项目 | 当前已证范围 | 剩余验收 | 任务 |
|---|---|---|---|
| 启动进入主界面 | 官方BODYDATA启动，真实简中首设后原HUD；新独立包实际复验通过 | 完整自然启动与长期稳定性；闲置恢复仍有暂停项 |23已完成；2、31 |
| 显示菜单页面 | 原MENU显示及部分导航；新独立包原中文MENU已人工核验 | 全部控件与长时间稳定性 |14、36；23已完成 |
| SD拔插和写入 | native三轮、包内两轮真实Unmount/Mount与原free通过；退休/在卡四状态导出同SHA；重插后原完整DB/XML消费匹配卡字节；原API4KiB显式诊断另过；默认profile旧卡回载实测并已发布 | 当前同卡热插拔范围已验；运行中另选镜像界面未提供，诊断不冒原拍摄，照片录像/高层REC状态另验 |15、41、44、45、63、64已完成；35、50为高层媒体缺口 |
| 镜头模拟 | 有限服务与输入/静态合同 | 原镜头状态、焦距/光圈参数、驱动及AF请求/完成闭环 |19、40 |
| CMOS输入模拟 | 有限buffer/消息边与原consumer定位 | 像素输入、真实请求消费、DMA完成、freshness、所有权回收与原编码链 |19、34 |
| overwrite目录自测 | 安全派生/拒绝/故障矩阵43tests46subtests；原厂脚本实际返回1→7，再无覆盖启动恢复1；原件/manifest/SD核验通过 | 其它实质补丁、ELF布局/ABI及固定地址探针兼容须逐项另验 |46已完成有限自测 |
| 声音输出到操作系统 | guest服务、SysSound128KiB及有限路由/消费 | 原数据来源、格式、长度、租期，导出到宿主音频设备，实际消费证据 |47 |
| 快门模拟 | 半按/全按由原固件消费 | 曝光/镜头/帧/编码/原文件保存完整链；按键消费不等拍摄成功 |14、16、19、20、39、40 |
| Wi-Fi模拟 | 隔离USB以太网+宿主peer新ICMP、原接口UP/DOWN；正式UI已接；新独立包同VM后端ON/OFF/ON复验通过 | 宿主系统ping路由和真实无线关联不在已验范围；新包这轮未另点GTK开关 |48、54、57已完成 |

## SD动态插拔的UI硬验收

最终唯一camera_ui.py GTK窗口必须提供SD卡插入/拔出控件，在同一相机VM
运行中操作，不依赖重启。仅一个物理卡槽，仅操作本机虚拟镜像，不接真实SD。
状态由后端实际操作和回读决定，显示未插卡、插入中、已插入、拔出中或失败。
不允许只修改按钮、AP有卡标志或录像选槽来冒充介质变化。

默认安全拔出：处理在途I/O、Flush和SD租约，无法安全完成时明确失败而非
强断镜像。原固件必须收到真实介质变化并完成相应处理。重插保留原内容，
由原固件重新识别、挂载和读写。验收包含写入→拔出→重插→再次读写、
内容摘要与文件系统核验，且重复插拔不泄漏消息或租约。

两位首轮调查对变化通知source/free归属、挂载与拔出次序有分歧，均未运行
热插拔验收；暂不将任何猜测通知包、直接close镜像或按钮外观变化作为实现。

后续 main 已把单 worker、原 Mount/Unmount 卷表观察、Front owner/destination 分离和 GTK 按钮接上实验 profile。`run-9isvuc6s` 原 Mount/Flush 与变化通知按 owner 释放已证，但 45 秒未见 Unmount，试验失败并正常保存退出；不算拔出。独立审查的六项边界已修，host 回归和原 ABI 重建通过。首次“首设后插拔”调度因外层运行锁等待冲突在新 guest 启动前超时，无新 SD 消费证据；下一轮单独调度，详见 `sd-hotplug-progress.md`。

修正调度后 `run-nksugd_8` 完成中文首设/原 MENU 并实际点击 GTK SD 按钮；原 Flush 与通知 free 再次通过，仍未见原 Unmount，验收失败。没有反向插入或伪完成，随后正常保存退出。下一步需要原 Callback/Parse/Update 的同一消息处理证据，当前按用户许可暂放该难点，不重复无差别重跑。

后续已从该入口恢复并核实：旧opcode9 rec+4固定1使原MediaInfo.mask选择R0，实际RM2通知改变R1。只改设备配置回复为对应通道bit2后，原Init/Update自然产生上层通知及Unmount；两份独立原字节审查确认，M0与R0不要求同号。`run-rqiyv09k`一轮、`run-oe74q3vt`三轮实际GTK卸载/重挂载通过，计数1/1/2/2/3/3、逻辑盘符A→B→C→D，只有同一张虚拟卡。`run-h7tn8rmu`重插后原AP完整Read 9670656B/406B，返回数据与独立FAT解析文件相同；`run-atvy5ajv`显式原API写入诊断4096B、Flush/Close/Read及跨通道全字节也通过。所有SD独立摘要/fsck/owner恢复均通过，原失败不改写。文件`/C883B25C.BIN`作为诊断证据有意保留，不冒作相机生成的照片。详见sd-hotplug-progress.md及sd-reinsert-api/；最终包内移交与验收仍由Task64继续。

## Wi-Fi开关与网络硬验收

最终唯一camera_ui.py GTK机身窗口必须有Wi-Fi开启/关闭按钮。用户操作进入
开启中或关闭中状态，后端实际操作和回读才决定已开启/已关闭；错误显示失败。
不得只改按钮外观或依赖host伪相机代答。

显式隔离网络仅连接host与camera guest，无真实无线、外网或物理网桥。
当前-nic none只能在审查隔离配置后替换。开启并就绪后，宿主能ping通相机IP；
guest协议栈实际收ICMP并回包。关闭后ping失败，重复启停不泄漏链路或owner；
相机OFF按生命周期清理。核双端抓包、guest计数及链路关闭负对照。

IP连通、原Wi-Fi控制/关联是不同验收结果。仅用虚拟以太网ping通不能宣称
原无线扫描、关联、认证或所有Sony无线业务已完成。

## 配置持久化与销毁重初始化

用户追加要求：正常重启和重新打开UI后保留相机配置，最终单窗口提供
销毁并重新初始化选项。任务49跟踪实现，当前尚未完成。

当前状态更新：最终窗口已默认绑定私有实例，正常OFF先核配置快照及独立guestSHA、SD保存、租约内CAS发布；启动由该代派生两份seed恢复。真实GTK两轮ON/OFF加确认reset第三次启动在native和独立包均通过，重置代、旧代/SD保留和三卡fsck均已main核；包内非默认25/2跨整个GTK进程也已有限核验。剩余是首设完成状态、全参数提交覆盖、重开后原页面视觉复验，不再把全部配置功能统称“尚未接线”。下述早期设计描述按历史范围保留。

当前默认启动脚本将/setting挂tmpfs，从seed复制Backup.bin和setting，
以Backup_load=1、Backup_save=0加载原备份驱动。menu_control的停止路径
只导出SD，尚无相机配置导出/恢复。因此不能将SD内容持久化当作配置持久化。

`Backup_save=0` 不是已证全局写入开关；单改为 1 的原 API 对照没有得到目标记录提交，原模块存在返回 0 但不保存文件的路径。宿主 store 48 项测试通过；生命周期租约候选 19 项经 main 与 store 合计独立复测 67 项通过。其逻辑重置保留历史和 SD，不据此宣称原配置跨 VM 恢复完成，后续接线范围见下段。

后续 main 已将生命周期组件和测试放入权威 runtime，并接入 `VM(instance=...)` 可选路径及停止后 host 逻辑重置接口。启动前获取租约，确认 owned 进程组退出后才释放；清理失败保留租约，重试关闭后确认释放。集成 99 项测试通过；默认 UI/启动/快照兼容组合首轮 47 过、1 个旧裸 Mock 夹具因未设置串口失同步标志而失败，夹具修正后相关控制通道/VM/快照组合31项、2子场景通过。默认最终 UI 尚未启用稳定实例或配置导出/恢复，不能把这个 host 生命周期接线当成配置持久化完成。

配置需经原固件正常提交、保存到host实例并校验后原子发布；下一次启动
按同一固件身份恢复，不能再被seed覆盖。验收通过原固件修改参数、正常
退出、重建VM以及关闭并重开UI后，原API和UI读回一致。崩溃时尚未提交
的数据是否可恢复单独列明，不承诺无条件零丢失。

销毁只针对已停止且SD/配置租约已安全结束的当前owned虚拟相机实例，
执行前显示清理范围并二次确认。原固件包、共享解包缓存、overwrite源、
外部SD源和其他实例不删除。虚拟SD默认保留，清卡须单独明确选择；
不能带活VM删除，也不能在保存失败后伪称已安全重置。

## 执行与复核

用户要求同一任务由两位代理独立调查，不互读或互补分工。主会话逐项比较
原证据与结论并核原代码；一致不是证明，有分歧不投票。代理仅在独立scratch
落盘，主会话负责生产集成与验证。VM、构建及安装串行，保留既有锁和SD租约。

首写实验b3b3decbd仅等待外部VM至30分钟上限退出，没有启动本会话VM，
没有首写证据；其任务仍未完成，不能描述为继续运行或硬件失败。

### Wi-Fi 通道：原 kernel USB 以太网绑定（已通过，host 侧 ICMP 仍未做）

`scratch/wifi-sysbus/probe-w_sab8mh`（候选 QEMU `ba891b29…`，原 kernel + 原 guest shell + 派生 DTB，
`-nic none`，无相机 app／无 SD）实际结果 `result.json`：
`original_usb_driver_bound: true`、`vm_exited: true`、`host_ping_verified: false`（探针范围外）。

guest 串口证据（`usb-binding.txt`）：

```
USB_MOD_OK mii / usbnet / cdc_ether / rndis_host / xhci-hcd / xhci-plat-hcd
xhci-hcd b000000.usb: xHCI Host Controller ... hub 1-0:1.0: 4 ports detected
usb 1-1: new full-speed USB device number 2 using xhci-hcd
cdc_ether 1-1:1.0 usb0: register 'cdc_ether' at usb-b000000.usb-1,
          CDC Ethernet Device, 52:54:00:12:34:56
/sys/class/net/usb0/device/driver -> .../bus/usb/drivers/cdc_ether
```

所以**原固件的 USB 宿主控制器 + 标准 USB 网卡驱动栈可以在这个机型上真实绑定**，
并且平台是 `b000000.usb`（与既定 sysbus xHCI/MMIO `0x0b000000`、SPI180 的候选一致）。

边界（不要误读）：这只是“驱动绑定 + 网络接口出现”，**不是** Wi-Fi 关联，也**不是** ping 通。
下一步：host 侧自建以太网对端（Unix socket netdev，不继承 host netns、不用 host TAP fd），
给 `usb0` 配地址后做真实 ARP + ICMP echo request/reply；通过后再接最终 UI 的 Wi-Fi 开关。

### Wi-Fi 通道：ICMP 第一次尝试失败及根因（`-netdev stream` 是带长度前缀的）

`probe-j8bm2rdd`（`--icmp`）结果：`original_usb_driver_bound: true`，但
`host_ping_verified: false`、`error: Guest did not answer ARP on the isolated link`。
guest 侧 `ifconfig usb0 10.0.0.2 … up` 成功、`UP BROADCAST RUNNING`，但
`usb0 RX packets:0 TX bytes:0`——**一个帧都没过链路**。

根因（读 QEMU 源码，不是猜测）：`-netdev stream` **不是裸以太网帧**。`net/socket.c`：

```
net_socket_send()            // 流式分支
    size = recv(s->fd, buf1, sizeof(buf1), 0);
    ret = net_fill_rstate(&s->rs, buf, size);
```

`net_fill_rstate` 先读 **4 字节大端长度**再读该长度的载荷。我们发裸帧时，QEMU 把帧首 4 字节
（`ff ff ff ff …`）当成长度约 4 GiB，于是一直等数据、永不投递——正好对上 RX=0。

修复：`ethernet_peer.py` 改为长度前缀协议（发送 `struct.pack('!I', len(frame)) + frame`，
接收按前缀切帧并拒绝 >64 KiB 的荒谬长度）；`test_ethernet_peer.py` 的伪 guest 同步改造，
无 VM 自检 **1 passed**。

同时保留的另一条观察：枚举期出现
`usbnet: failed control transaction: request 0x8006 value 0x600 index 0x0 length 0xa` ×3。
`dev-network.c` 里 `USB_CDC_SET_ETHERNET_PACKET_FILTER(0x43)` 只有在 `is_rndis(s)` 时才 STALL，
所以这更像 `rndis_host` 先探测 CDC 设备时的预期失败；不作为故障结论，等 ICMP 结果再判。

### Wi-Fi 通道：ICMP 第二次尝试——通了但 guest 侧 100% 丢包，查出两个宿主端 bug

`probe-q4pd0mkm`（长度前缀修复后）首次出现双向流量：
`host_ping_verified: true`（RTT 200 ms、payload 匹配）、`arp_replies:1`、
`echo_requests:2 / answered_requests:2`。但 guest 自己的 `ping` 打印：

```
PING 10.0.0.1 (10.0.0.1): 56 data bytes
--- 10.0.0.1 ping statistics ---
2 packets transmitted, 0 packets received, 100% packet loss
```

即“我们回了、它不收”。逐帧核对后发现两个宿主端 bug（都在 `ethernet_peer.py`）：

1. **应答帧把 IP 源地址当目的 MAC**：`_ipv4_frame(src, …)` 里的 `src` 是 4 字节 IP 地址，
   结果帧长 96 而非 98，目的硬件地址错误 —— guest 直接丢弃。
2. **ICMP 校验和没重算**：应答只把 type/code 改成 `0/0`，沿用了请求里的校验和字段；
   `_ipv4_frame` 只重算 IP 头。校验和错误 → 内核丢包（正是 100% loss 的直接原因）。

两者已修复（按 `self.guest_mac` 定址；应答校验和按实际发送字节重算并 `assert checksum(reply)==0`）。
新增两条无 VM 回归：`test_peer_answers_guest_echo_with_valid_checksum` 等，`test_ethernet_peer.py`
**2 passed**。

**判据同时收紧**（这条更重要）：`guest_ping_verified` 原来用“我们收到过 guest 的 echo 请求并回过”
来判定，这只能证明宿主回了、不能证明 guest 收到。现改为解析 guest 自己 `ping` 输出的
`N packets transmitted, M packets received`，要求 `M>=1`；否则一律 false。上一轮的
`guest_ping_verified: true` 因此作废。

### Wi-Fi 通道：隔离 USB 以太网双向 ICMP **已通过**（`probe-ujy0z9yb`）

修复两处宿主端 bug 后重跑，判据（宿主侧 + guest 自身）同时成立：

```
USB_KERNEL_PROBE_RESULT ok=true
  host_ping_verified: true           # 宿主→guest，payload 匹配，RTT 200 ms
  guest_ping_verified: true          # 判据取自 guest 自己的 ping 统计
  guest_ping_transmitted: 2 / guest_ping_received: 2
  peer_counters: frames_in 4, frames_out 4, arp_replies 1, echo_requests 2, answered_requests 2
  original_usb_driver_bound: true
```

guest 侧原文（`icmp.txt`）：

```
PING 10.0.0.1 (10.0.0.1): 56 data bytes
64 bytes from 10.0.0.1: seq=0 ttl=64 time=2.567 ms
64 bytes from 10.0.0.1: seq=1 ttl=64 time=0.616 ms
2 packets transmitted, 2 packets received, 0% packet loss
```

**边界（必须保留）**：

- 这是**原 kernel 驱动的 USB 以太网**上的真实 ICMP，链路只存在于本进程与 guest 之间；
  `-nic none`、无 host TAP、无 host netns 继承、无物理网卡。
- **不是** Wi-Fi 关联：`wifi_association_verified: false`；bcmdhd 仍需真芯片，本轮没有也不声称。
- 该探针里**没有**相机 app、没有 SD（`camera_app_started: false`、`sd_attached: false`），
  所以还不能说明最终 UI 里的 Wi-Fi 开关可用。

下一步：把这条链路接进正常相机 run，并让最终 UI 的 Wi-Fi 开关真实启停该接口，
验收判据 = 开关 ON 后宿主能 ping 通、OFF 后 ping 失败（同一 run 内）。

### Wi-Fi 通道：把隔离链路接进正常相机 run（opt-in）

集成方式全部**默认关闭**，不改动任何既有 run 的行为：

| 开关 | 作用 |
|---|---|
| `MENU_USB_NET=1` | 相机 run 内在启动后加载原 kernel 模块栈（`mii/usbnet/cdc_ether/rndis_host/xhci-hcd/xhci-plat-hcd`）、给 `usb0` 配 `10.0.0.2/24`，并在 SD 导出后做双向 ICMP 验收，写 `usb-net-icmp.json` |
| `MENU_KERNEL_SCRIPT` / `MENU_DTB` | 指向派生启动脚本与派生 DTB（默认仍是 `qemu-kernel-probe.sh` 与 `qemu-virt-board/virt-packed.dtb`） |
| `QEMU_SYSTEM_DIR` | 指向带 sysbus xHCI + `usb-net` 的候选构建（已在启动器里 `env.setdefault` 支持） |

派生由 `scratch/wifi-sysbus/prepare_camera_usb.py` 生成，只做两件事：启动脚本加
`--setenv QEMU_SONY_USB_NET 1` 与 `-netdev stream,…,addr.path=/out/ethernet.sock,server=on`
`-device usb-net,…`；DTB 增加 `/usb@b000000`（MMIO `0x0b000000`、size `0x4000`、SPI180、
`compatible=generic-xhci`）。**不触碰** `QEMU_OUTPUT_DIR`，因此 run 目录布局与相机启动器一致。

`start-menu.profile_environment()` 原先会剥掉所有 `MENU_*`，已显式转发这三个开关
（与 `MENU_RM_SLOT1` 同样处理），并有回归覆盖。

判据：run 内 `usb-net-icmp.json` 的 `ok=true`（`configured` + 宿主 ping 通且 payload 匹配 +
guest 自身 `ping` 收到 ≥1 个回复），且该 run 仍完成原 SD 导出与首设/主界面。

### 教训：`profile_environment()` 会剥掉 `MENU_*`/`QEMU_*`/`SONY_*`（同类问题出现三次）

`start-menu.profile_environment()` 出于安全会把继承环境里的 `MENU_*`、`QEMU_*`、`SONY_*`
**全部剔除**，再写入自己的白名单。任何新的 opt-in 开关若只在包装器里设置，都会静默失效：

| 次数 | 开关 | 症状 |
|---|---|---|
| 1 | `MENU_RM_SLOT1` | 以为“改报 RM1 无效”，其实开关从未到达 guest（manifest 仍是 rm2） |
| 2 | `MENU_USB_NET`/`MENU_KERNEL_SCRIPT`/`MENU_DTB` | 派生脚本/DTB 未被采用 |
| 3 | `QEMU_SYSTEM_DIR` | 相机 run 仍用 `build-sony-ui`，`-device usb-net` 报 `No 'usb-bus' bus found`（清单里能看到实际二进制） |

处理：在该函数**两个分支**（natural / 非 natural）都显式转发这些键，并加断言
（`QEMU_SYSTEM_DIR` 只有在 `MENU_USB_NET=1` 时才下传，不会无条件泄漏 research 开关）。

判据提醒：验证“开关是否真的生效”，看 **run 清单里的实际二进制/脚本/DTB**，不要只看
包装器打印的命令行。

### 运维：失败 run 会留下占槽的 VM（已加护栏）

两次“跑了一小时”的任务并不是在执行，而是**失败后进程树没被收掉**：

| 任务 | 真实情况 |
|---|---|
| `b39372207`（相机+USB 第 5 次） | 早已 `RuntimeError: ... ethernet_peer`（我把 USB 验收误放进 SD 导出路径）；泄漏的 QEMU 持有输出管道，任务直到 **2400s 超时**才结束 |
| `be284db05`（REC slot1 rerun） | 早已 `Simplified Chinese font was not selected`；同样泄漏 |

结论：**`bg` 的 `running` 不能当证据**。判断标准改为三项：
`pid 是否存活` + `qemu-system-aarch64 计数` + `输出末尾是否有终态`。
两条僵尸记录已就地改判为 `failed`（附原因），当前只剩真正在跑的一个。

根因护栏（包装器 `wait_and_run.py`）：起跑前记录已有相机 pid 集合，子任务退出后
**只回收本次新增的**相机进程（先 `SIGTERM`，10 秒后仍在则 `SIGKILL`），并打印
`REAPED_LEAKED_VM`。这样失败不会再占住单 VM 槽或拖住输出管道。

### 宿主声音：PCM 落盘组件完成 + SysSound.bin 结构初查（Task #47）

**已完成（可离线验证）**：`device-models/pcm-sink.c` / `.h`
- `pcm_sink_open(path, rate, channels, bits, cap)`：写标准 44B WAV 头（占位尺寸），
  校验采样率 8k–192k、通道 1–8、位深 8/16/24/32、必须给容量上限
- `pcm_sink_write()`：未打开一律 `EORDER`；**非整帧长度拒绝**；**超过容量上限拒绝**
  （避免写满宿主磁盘）；只有真正写入才累加 `bytes/frames`；同时统计**峰值**
  （8/16-bit），让“静音”无法冒充“有声音”
- `pcm_sink_close()`：回填 RIFF/data 尺寸并关闭；关闭后再写仍 `EORDER`
- 宿主测试 `test_pcm_sink.py`（ASan/UBSan）：**2 passed**，含 1 kHz 正弦写入后
  **重新解析 WAV 校验头部与逐字节数据一致**、容量拒绝、顺序错误

连同合成成像源，`pytest test_pcm_sink.py test_cmos_source.py` = **4 passed**。

**SysSound.bin 初查（66368B，SHA `5d94c660…`）**：
- 无 `RIFF/WAVE/fmt /data/Ssnd/ADPCM` 等任何音频容器魔数；
- 头部是**32 字节步长**的表项，首字段递减 `0x17,0x16,0x15…`（0x00/0x20/0x40…）；
- 全文件几乎无 ≥64 字节的零区（63452/66368 非零）。
⇒ 它是**参数表**而不是 PCM 音频；提示音很可能是固件按参数**合成**的。
因此宿主声音的下一步不是“播放文件”，而是**按 SysSound 参数合成 PCM**，
再交给 `pcm-sink` 落盘，用来证明原固件的播放请求（`0x0203`）真的到达。

**当前阻塞点**：音频设备模型仍显式拒绝 `0x0203`/`0x032b`（`playback-not-supported`），
在合成器与参数解析闭合前不解除该拒绝，也不宣称有声音。

#### SysSound.bin 进一步解码（续）

`usr/share/avsystemsound/SysSound.bin`（66368B）按 32 字节步长看：

| 偏移 | u32 值 |
|---|---|
| `0x00` | `0x17` (23) |
| `0x20` | `0x16` (22) |
| `0x40` | `0x15` (21) |
| `0x60` | `0x00` |
| `0x80` 起 | 高熵数据（末 66368-128=66240 字节） |

- 前 4 个 32B 记录除首 u32 外全为 0，且序列为 23/22/21/0 → **三组数量头**（共 66 个音）；
- `0x80` 之后没有零区长段，字节值集中在 ±0x80 附近，符合**压缩音频（8-bit 或 4-bit ADPCM）**，
  每音平均约 1000 字节；文件内**没有** RIFF/WAVE 容器或明文偏移表。

⇒ 播放路径应为：固件按音 id 取 ADPCM 段 → 解码为 PCM → 送音频设备。要把宿主声音真正接通，
还需要（a）三组 ID→段边界的解析规则，（b）ADPCM 解码器与其状态字段。
两者都尚未闭合；在此之前 `0x0203/0x032b` 保持拒绝，不宣称有声音。

#### 宿主声音：SysSound 索引与 16-bit PCM 已解出，提取工具完成

**索引文件找到了**：`/usr/share/avsystemsound/beeplist.txt`（appFw 内有该字符串）。每行给出
`BeepID名, 编号, 内存类型(APP/PIN), 文件名, Size, FileOffset, RsrcAcsType, Priority, KindID,
continuous, contLength, contFirstLength`，例如：

```
BEEP_ID_STARTUP, 0x0000, APP, Dslr_Emnt_High_Startup.bin, 0x2000, 0x97C0, AA_RT, 1, 14, 0, 0, 0
BEEP_ID_KA,      0x0001, PIN, Dslr_Emnt_Shutter_Ka.bin,     0x80,   0x0,    …
```

**格式已实证**（不是猜）：

1. 每个独立 `.bin` 与 `SysSound.bin[offset : offset+size]` **逐字节相同**（已对多个音校验）；
2. 每个切片开头是 **128 字节前导**（四个 32 字节记录：`0x17/0x16/0x15/0`，与容器头一致）；
3. 前导之后是 **16-bit 小端 PCM**：`BEEP_ID_STARTUP` 提取出 4032 帧（48 kHz 下 84 ms），
   **峰值 32607、RMS 14185** —— 真实音频，不是静音也不是参数表。

**工具**：`runtime/analysis/beep-extract.py`
- `--rate` **必填**（索引里没有采样率，拒绝默默假设）；
- 按 `--beep` 取切片、写标准 WAV，并输出 JSON（含 `slice_matches_standalone`）；
- 索引里 Size/Offset 为 `N/A` 的行**直接拒绝**，不做猜测。

宿主测试 `test_beep_extract.py` **4 passed**：索引解析（含 N/A 行保留为不完整）、
所有可对齐的切片与独立文件逐字节相同、提取出的 WAV 参数与切片长度一致且非静音、
不完整行被拒绝。

⇒ 音频不再需要“合成/猜测”：固件自带 PCM 可直接解出，后续只需在音频设备模型接受
`0x0203/0x032b` 时把对应 beep 的 PCM 交给 `pcm-sink` 落盘，即可证明**原固件真的请求了播放**。

#### 宿主声音：36 个音全部可解析（双源），并记录"仅头无 PCM"的条目

索引共 **36 行**：

| 来源 | 数量 | 说明 |
|---|---|---|
| 容器切片（`SysSound.bin[offset:+size]`） | **15** | 覆盖整包 `0x0–0x10340`，仅一处 14 KiB 空隙（`0x4a40–0x8240`） |
| 独立 `.bin` 回退 | **21** | 索引里 Size/Offset 为 `N/A`，但文件本体同为“128B 前导 + 16-bit PCM” |

`beep-extract.py` 改为**双源**：容器优先；两者都存在时必须**逐字节相同**，否则拒绝该行；
两者都没有则拒绝（不猜测）。

**诚实边界**：`BEEP_ID_KA`（`0x0001`）的切片正好 **128 字节 = 仅前导、无 PCM**，
提取器如实返回 0 帧并在测试中显式登记，不把“空音”当可播声音。

测试 `test_beep_extract.py` **6 passed**：索引 36 行、容器/独立逐字节一致、
不完整行走独立文件回退、双源缺失拒绝、WAV 参数与长度、以及“仅头无 PCM”必须可见。

另：音频模型已加入**只读请求记录** `FULL_AUDIO_PLAYBACK_REQUEST`（含前 48 字节原始载荷），
`0x0203` 仍保持拒绝——用它来判明请求里到底带的是音效 ID 还是 PCM。

#### 宿主声音：固件**没有**发出播放请求，原因是我们声明了"无输出能力"

`run-gqenb34z`（音频模型启用，`audio_boot_config_service: true`）实测：

| 观察 | 计数 |
|---|---|
| `FULL_AUDIO_REQUEST` / `COMMIT` / `REPLY_QUEUED` | 54 / 54 / 54 |
| `FULL_AUDIO_INPUT` | 75 |
| **`FULL_AUDIO_PLAYBACK_REQUEST`（`0x0203`）** | **0** |
| `FULL_AUDIO_UNSUPPORTED` | 0 |

该run证明控制面有54次提交、所观察的0203为0，不能由此断言固件没有任何播放入口。
此前“inputless意味着无扬声器，故不发0203”的原因判断未闭合，撤回：该能力模型描述
麦克风/处理侧；没有证明它控制提示音播放。成像也不能由缺包指定CP为唯一根因。

后续已定位原AP的16B `0x200d/0x032b` 请求，见 `audio-playback-ap-contract.md`。
应沿该真实发送路径核对BeepID转换、消费者与完成归还，而不是假定补能力位即可出声。

在此之前不解除 `0x0203/0x032b` 的拒绝，也不声称有声音；
已导出的 `report/audio-beeps/*.wav` 只是**固件自带资源**，不是仿真播放产物。

#### CP control 0x127 的诊断构造候选（正常播放路径未证）

在 `cpapp-b.bin` 里找到带0x127的构造代码（CPVA `0x192fa4` 起）；它按字符串参数转换，
经诊断表分派，不能直接命名为正常播放请求：

```
192fb2 movw r0, #0x2004      ; 帧/族标识 0x2004（与 AP 侧 0x0203 拒绝条件里的 frame 一致）
192fbc strh r0, [sp, #0x1a0]
192fc0 movw r0, #0x127       ; 控制码 0x127（音频通道控制）
192fc4 strh r0, [sp, #0x1a2]
192fc8 movs r0, #0xa8        ; 总长168，含8字节头
192fca strh r0, [sp, #0x1a4]
192fce movs r0, #1           ; 字段值1，具体语义未证
192fd0 strh r0, [sp, #0x1a6]
192fd4.. 清零其余字段（strd/str）
```

另有 `0x19bb32`（同样 `movw r0,#0x127` + 0x4c 参数块 + 经由对象 vtable `+0x24` 调用）与
`0x19d71e`（对 `0x127` 做注册/使能调用）。这些事实不足以推出正常播放缺哪一分支，
也不能解释AP为何没有发0203。缓冲候选偏移为D+0xc/0x24、长度候选D+0x10/0x28，
两个字节D+0x76/0x77语义仍未知；不能把字符串转换函数的参数0x10当作缓冲地址加数。

下一步先闭合已定位的AP032b消费者和BeepID映射；未证明的0x127字段保持未实现。
只有真实请求、真实资源消费、完成/归还以及宿主实际消费全链有证据，才报告声音通过。

已就绪：`pcm-sink`（PCM→WAV，含帧/上限/峰值校验）、`beep-extract`（36 个原厂音，
按 id 取 PCM）、`report/audio-beeps/`（10 个可试听样本）。

## Wi-Fi 接线：两个真实缺陷（2026-10-20 实测）

隔离 USB 以太网传输层已验证（双向 ICMP，见上），但把它接进**正常相机 run** 连续失败。定位到两个
与本机无关、纯属我方接线的缺陷：

1. **显示分支覆盖 QEMU 构建**（`menu_control.py` 原 `_run()`）。
   `native_display` 分支无条件 `QEMU_SYSTEM_DIR=<sources>/build-sony-ui`，覆盖了
   `profile_environment()` 刚刚按 `MENU_USB_NET` 白名单保留的**带 sysbus xHCI 的候选构建**。
   后果：`-device usb-net` 报 `No 'usb-bus' bus found`，整个网络 run 在启动即失败。
   修复：抽出 `native_display_environment()`，改用 `setdefault`（只配置显示，不选构建）。
   测试：`test_menu_control.py` 4 例，含“候选构建穿过显示分支后仍是原值”。

2. **宿主 peer 的 socket 路径超出 AF_UNIX 上限**（`menu-runs/run-*` 下共约 155 字符 > 108）。
   启动器在 `bwrap` 里把 run 目录绑成 `/out`，所以 QEMU 侧 `addr.path=/out/ethernet.sock`
   实际落在 run 目录；宿主 peer 直接用该长路径 `connect` 会得到
   `AF_UNIX path too long`（本次 `usb-net-icmp-error.json` 的原文）。
   修复：`menu_live.netdev_socket_alias()` 生成短符号链接（`/tmp/a7c2-usb-<run 尾 8 字符>`）再连接，
   用完删除。测试：`test_menu_control.py` 2 例，断言“原路径 >107 字符、别名 <108、解引用到同一目录”。

判据纪律不变：`ok=true` 要求 `configured`（guest 侧 `usb0` 配到 `10.0.0.2`）+ 宿主 ping 的
payload 匹配 + **guest 自己报告的 `received ≥ 1`**；`send==0`、`exit==0`、HUD 变化都不作数。

### 结果：真实相机 run 内通过（2026-10-20）

`menu-runs/run-nknfw5cy`，`usb-net-icmp.json`：

```json
{"scope":"isolated original-kernel USB Ethernet ICMP in a camera run",
 "configured":true,
 "host_ping":{"rtt_ms":200.11,"payload_matched":true},
 "guest_transmitted":2,"guest_received":2,
 "peer_frames_in":4,"peer_frames_out":4,
 "capture_verified":false,"ok":true}
```

同一次 run 还完成了**简体中文首设**与 **SD 导出**
（`FIRSTBOOT_SD_EXPORT_PASS eb8f7539b6562412421fa27044f1b134fe2aba4b421a73aa29f709adc4c05891`）。
`runtime-manifest.json` 记录 `files.<…>/candidate-rt0tniif/build/qemu-system-aarch64 =
ba891b29f9265c8203df8456371a9d4476dd8a27947a510afb17c0746d1f769e`，证明用的是带 sysbus xHCI 的候选构建，
不是 `build-sony-ui` 回落。

判据说明：`guest_transmitted/guest_received` 取自 **guest 自己** `ping` 的统计（0% loss），
宿主侧的应答计数（`peer_frames_*`）只用于诊断，不作证据；`capture_verified` 保持 false——
Wi-Fi 与成像无关，不得混记。

**剩余**：最终 UI 的 Wi-Fi 开关本身（ON 后宿主可 ping 通、OFF 后不通，同一 run 内可切换）尚未实现。

### UI Wi-Fi 开关（实现 + 判据）

控制通道沿既有路径扩展，UI 不传任何 guest shell 文本：

```
CameraUI（Gtk.Switch）
  → VM.enqueue({'action':'wifi','enabled':bool})      # 严格 type(...) is bool
  → 有界队列 → socketpair → run_live 分支
  → wifi_toggle.WifiLink.set_enabled(bool)
       enable : serial(insmod × 6 + ifconfig usb0 10.0.0.2 up) → 起宿主 peer → ARP → ping
       disable: serial(ifconfig usb0 down) → **同一宿主 ping 必须失败** → 停 peer
  → 回复 {'type':'wifi', enabled, ok, host_ping, interface_up|interface_down, peer_frames_*}
  → run 目录 wifi-state.json + VM.wifi（status() 暴露）
```

**真值判据（写进 `wifi_toggle.py` 与 9 个单测）**：
- 开启 `ok` 仅当 guest 接口真的拿到 `10.0.0.2` **且** 宿主收到匹配应答；地址没拿到→不启 peer、不报成功。
- 关闭 `ok` 仅当接口不再报 UP/RUNNING **且** 同一宿主 ping 变成失败；若仍能 ping 通→拒绝报成功（`host could still reach the guest`）。
- 命令返回码、`send==0`、HUD 变化一律不作证据。

接口状态判定同时兼容 busybox 的 `UP BROADCAST RUNNING` 与 net-tools 的 `flags=<UP,BROADCAST,RUNNING>`。
开关仅在 `MENU_USB_NET=1` 的 run 中可用；其它 run 禁用该控件，enqueue 也会明确拒绝。

### ON/OFF/ON 首轮失败与探测修正

`run-z1o_8en9` 的结果是 ON 成功、OFF 失败、再次 ON 成功，整体 `ok=false`。
原始结果保留在该 run 的 `wifi-toggle-initial-failure.json`。
OFF 的接口回读显示 down，但宿主检查器重用了开启阶段的历史 ICMP 应答：
它每次都发送同一个 id/sequence/payload，并在整个历史列表中查找匹配。
这不能证明关闭后仍然可达，也不能据此认定 OFF 已通过。

修复后每次 ping 使用递增序号和随机 nonce，匹配本次完整 payload；新增测试让第一次
探测收到应答、第二次没有新应答，要求第二次失败。其它修正包括：只解析 usb0 的实际
ifconfig 块而不是串口命令回显；UP 与 RUNNING 分开判定；OFF 必须实际拥有可执行探测
的 peer；失败连接清理；UI 程序回退开关不再次发送动作，未启网络的 run 禁用开关。

相关宿主测试 58 项通过。重跑结果待定；新驱动器直接运行（不经 `| tail`），按真实
退出码和 `result.json` 判定，并额外要求 SD 导出成功和 VM 正常退出。步骤记录在
`wifi-events.jsonl`，最终限定范围的结果在 `wifi-toggle-proof.json`。

### 新鲜探测复验：ON/OFF通过，再次ON时VM退出

`run-p1hacpkr` 已证明首次ON后得到匹配的新应答；OFF后guest接口down，
`probe_attempted=true`、`host_ping=null`，该步通过。
但再次ON期间guest启动器意外退出、SD未导出，整体仍失败，不能标开关完成。
原结果保留于 `wifi-toggle-incomplete.json`；该run没有记录底层guest启动器退出码，
现已补 `vm-unexpected-exit.json` 记录，暂不猜测具体退出原因。

后续实现保持同一宿主peer跨ON/OFF连接，只在VM关闭时释放；驱动也只加载一次。
OFF的判据仍是实际guest接口down与新鲜无应答，而不是“拆掉peer所以不通”。
复用/关闭边界测试及相关生产回归34项通过，新一轮完整周期结果待定。

### 完整周期通过（限定网络profile，run-z3cma1bq）

同一VM三步均通过：第一次ON新鲜payload匹配，RTT200.1ms；OFF的接口down且
`probe_attempted=true/host_ping=null`；再次ON新鲜payload匹配，RTT200.09ms。
主会话独立核了三条 `wifi-events.jsonl` 与 `wifi-toggle-proof.json`，没有复用历史应答。

同run的134217728B虚拟SD正常保存，host重新计算完整 `SD/card.img` SHA256为
`61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727`，与原导出记录一致；
fsck返回0，原flush成功、owner resumed，最终state为exited。
这证明网络后端反复切换和正常关闭可共存，不证明拍摄或文件是拍摄产物。

本次驱动器调用与GTK共用的VM控制队列，GTK动作接线由宿主测试覆盖，未做该run鼠标点击验收。
网络模块与测试已移入最终runtime，生产导入不再寻找scratch；旧位置仅为兼容软链接。
普通一键UI的正式QEMU/DTB/profile整合另行验收，仍不能把试验profile通过当全部交付完成。

### 正式构建与默认profile整合（进行中）

正式构建 `build-qemu.sh` 已成功完成并安装：

- QEMU 11.1.2、GTK/SDL/pixman/libseccomp 配置通过；
- `QEMU_NATIVE_INPUT_PASS` 通过；
- GTK display backend、`qemu-aarch64 --version`、host libfdt symbols 检查通过；
- xHCI 增量补丁的 base patch、修改前后 `virt.c/Kconfig` SHA 均已在临时树复核。

已验证的网络 peer、测试和 `usb_network.py` profile 生成器已移入最终 runtime；
默认 `camera_ui.py` 现在为该窗口创建USB网络profile，开关初始保持关闭，网络硬件只在
该profile启动时存在。三项profile测试和相关网络/UI回归通过。

正式安装路径动态复验已通过，`run-ayg9rr1n` 的 `launcher_profile=packaged-default-ui`：
不使用scratch QEMU、kernel script或DTB覆盖。ON新鲜payload匹配RTT200.1ms；OFF接口down
且新探测无应答；再次ON新鲜payload匹配RTT200.1ms。三步均`ok=true`，VM正常退出。
同run SD完整导出、host复算SHA256为
`61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727`，与导出记录一致，
fsck0、原Flush0、owner resumed。证据为该run的`wifi-toggle-proof.json`、`wifi-events.jsonl`
和`SD/card.img`；`capture_verified`仍为false。
