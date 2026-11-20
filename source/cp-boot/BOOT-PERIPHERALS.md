# CP 启动外围与原生 AP/CP 配对批次

本批面向隔离本机 QEMU。源码集中在本目录；全部模块接好后统一构建、两个工作线程回归，再做原 CP / 原 AP 综合观察。这里的“源码已接”不代表原固件已经消费成功。

## 本批新增功能模型（待验收）

- 完整官方PP输入实测使CP越过旧 `0xbe9a14`，新首次故障为写 `0xf1388f4c=0x101`。CP原指令使用 `0xf1388f48..58` 进行DFS初始化/请求/目标/触发/状态；CP专用虚拟状态机与AP状态分离，支持目标0..6及同步/异步位，虚拟延时1000ns，不改变实际频率、不生成IRQ，物理复位和时序均未知。
- `QEMU_NATIVE_P1_SPI_COMPONENT=virtual-p1-pl022-component-v1` 为默认关闭的native AP组件profile，映射官方QEMU上游PL022到 `0xf1017000` 并连接GIC SPI193；官方11.1.2归档源SHA完整核对。该profile还把AP eDMA单次上限从默认8MiB调整为原P1消费者的24MiB，必须完整搬运并读回，超预算报错；它不是物理性能或时序声明。未建立原P1设备树绑定、复位时钟、SPI BootROM从设备、应答、下载执行或PCIDMA更新，因此不能据组件存在宣称 `/dev/spidev0.0`、P1链路或安装通过。
- 新外围stage schema为 `a7c2-cp-peripherals-stage-v6`，要求DFS地址和非物理边界、P1组件profile/default-off/no-peer字段。历史v5收据只证明其原构建，不自动升级为新组件验收。

## 问题与依据

原 CP 在正确读取官方 BK4 后，首个确定故障是 `0xbef42a` 写 `0xf1388054`：I2C0 时钟门。下游地址逐项对应 DW I2C、PL330、PL080、PL011 和 TPU/PWM/phase，不能用整页常量 ready 或写入空 ACK 代替。

原 AP/CP 的四组通道各有两个 ring。相同低地址的两端本地内存分别保存不同方向的请求/完成，必须使用 **AP_RAM、CP_RAM 两个独立 backing**；跨端信封、计数器、唤醒字和正文都由真正的 eDMA 内存事务搬运。

## 实现

| 模块 | 本批源码合同 | 尚未覆盖 |
|---|---|---|
| SCU | 9 组 CLK、已命名 SRST 的完整32位 DATA/SET/CLR | 硅片复位值、未证明的 ready 位 |
| DW I2C ×5 | 原 upstream 引擎，真实 clock/reset 门控，INTID429–433 | 没有接入的从设备返回 NACK；不造 ACK |
| PL330 ×2 | 原 upstream 引擎，8 event/控制器，abort344/377，SRST3 bits14/15 | 未接请求端的外设握手 |
| PL080 ×2 | 原 upstream 8通道引擎；masked TC/error 位逐通道送 INTID378–393 | SCU clock/reset 路由未知；stock 总线错误 IRQ 链不完整 |
| PL011 ×5 | 原 upstream 字符设备，真实文件后端消费 TX；显式虚拟12MHz输入 | stock 对 TXE=0 仅告警仍输出；UART IRQ编号、完整时钟树未证 |
| TPU ×6 | 16位配置槽、时钟门控和复位；首次 configure→start 的已核顺序 | active status/count、事件、IRQ、PWM/phase运行与 PTSR 时序 |
| 共享 SRST4 | bit18 委托原 watchdog；bits20–25只控制对应 TPU | 不扩展其它位；WDT_MISC `0x3a0`仍归原 watchdog |
| native eDMA | 复用既有 `registers/lli` 核心，真实 local/PCI AddressSpace、LLP、预算、完成/失败 IRQ | PCIe物理时序和带宽 |
| native peer RAM | 普通共享文件、准确窗口、FD/偏移/inode/角色校验 | 真实 Sony 物理别名及配对迁移 |
| GPIO native 扩展 | 输入只来自有效对端 GPIO18 latch；双root；有效翻转产生门铃边沿 | GPIO16虚拟复位和物理边沿编码未证 |
| 普通键盘 GPIO | ports6/7/11 的四个全32位 latch 与官方18条初始配置原写；port17三条独立键线 | 新功能profile待整批验收；物理按键名称、电平极性、NOR实际执行未证 |
| native AP GPIO 输出回读 | native-only port18/pins9/8 RDATA从本机WDATA锁存读回；未配置为对应输出时拒绝 | functional loopback待host/device整批验收；其它位 RAZ、真实pad电平与物理兼容未证 |

`scu.c` 的纯寄存器核心继续拒绝 SRST4；`scu-qemu.c` 在该地址组合两个既有所有者。九个 stock 控制器分别使用独立 AddressSpace 转发实际 MMIO，包括 DW I2C 内部的寄存器子区域；对容器直接调用 `memory_region_dispatch_read/write` 会返回 `MEMTX_DECODE_ERROR`，不能用一个常量类型字掩盖。TPU SET/CLR 不会重置 watchdog 的 CR/TORR/计数器；真正的 bit18 写入仍执行原 watchdog 模型的动作。不可把组合代理描述为关闭或绕过 watchdog。

TPU 的 configure/start 在 enable 前读 `+10`，start 后只读 `+2c`。调试 dump、stop 后重启及生产 `0x6af6ce` 的 status.bit7/count 查询仍不支持。六路静态 INTID 已证为 `442,443,438,439,440,441`，事件与 ISR 链未知，本批不主动生成这些 IRQ。`0xf1050000` 本页没有已闭合消费者，不扩大地址覆盖。

PL330 组件用例为两控制器各 **通道0的八个 EVENT**，不计为八通道覆盖；完成要求 STOP、无通道/manager fault、实际字节和 guard 及源保持，复位要求非零 INTEN/SAR/DAR/CCR 实际清零。带 pending IRQ/fault 的 reset 未验。两个 stock DMA 模型均有忽略搬运访存错误返回的限制，不记失败地址的总线错误 IRQ 已支持。PL011 的 TXE 禁用样本按 stock 的实际继续输出记录，`txe_gating_supported=false`；不修改已锁定上游源码来使断言变绿。

## 配对内存与地址

`native-link.py` 只创建三个独立、owned、0600、nlink=1 的稀疏普通文件：

| 文件 | 逻辑容量 | CPU / 导出含义 |
|---|---:|---|
| `ap-ram.bin` | 24GiB | 标准 virt RAM 基址 `0x40000000`；Sony DDR `0x400000000` 对应文件偏移15GiB |
| `cp-ram.bin` | 128MiB | CP 本地从0开始；这是诊断容量选择 |
| `cp-oom.bin` | `0x101000` | CP独立缓冲页 `0x0ca21000`；物理别名未证 |

创建前按全部逻辑容量加512MiB日志和64GiB余量计算空间，未知或不足则拒绝。稀疏创建不等于预留存储；运行期间仍由父 owner 保留租约和 backing。失败文件和原始收据保留，不自动删掉或重绑 inode。

AP PCI视图把 CP_RAM 映射在 `0` 与 `0x400000000`；CP PCI视图把 AP_DDR 导出窗口映射在 `0x400000000` 与 `0x800000000`。每个窗口之外仍不可访问。四组 ring 本地基址分别为 AP `0x403f80000+g*0x20000`、CP `0x03f80000+g*0x20000`；两个本地 backing 绝不合并。

`native-notify-qemu.c` 是本批增强适配器；`notify-qemu.c` 保留父stage的冻结版本，使已接受的 GPIO 基线及从两个输入干净重建的父身份不变。子stage只替换实际编译目标中的适配器，不同时注册两个同名 QOM 类型。

## 接口和运行顺序

需要原官方 A7C2 2.01 ALLLANG 的 BODYDATA 派生资产和匹配 QEMU11.1.2 源码。不得使用完整 dump、真机设置或物理磁盘代替。`stage-peripherals.py` 叠加在精确 `cp-notify-stage.json` 上，冻结父源、upstream源、所选共享核心和全部输出。

构建与输入身份验收通过后，使用绝对 canonical 路径：

```bash
python3 source/cp-boot/native-link.py prepare /OWNED/NEW-PAIR --binary /MATCHED/build-cp/qemu-system-aarch64
python3 source/cp-boot/run-native-ap.py --pair /OWNED/NEW-PAIR --binary /MATCHED/build-cp/qemu-system-aarch64 --seconds 240
```

AP入口清除旧 CP provider 环境，只选择原 `osal_uipc/pcieatu/pcie-if`、原 bootin 和本批硬件。它使用配对专属锁、board目录、run目录和最新run指针；不改变用户已运行窗口的全局 probe 锁或 run 指针。这个入口是 headless 诊断，仍不是完整官方启动链一致性验收。

AP 的 `notify.sock` 建立后，由 `run-native-cp.py` 启动原 CP：输入为固定身份的原 CP、741字节原 tomco 和官方 PP；必须显式选择 `rec0|ed000|full`，不修改 tomco、BK4、内核或原 loader/crypto 业务逻辑。启动前跨 GDB 全量读回 CP/tomco/BK4；只使用硬件观察断点。两端 owner 独立负责正常 QMP quit；父会话在确认两端 rc0、无信号且全部实际进程退出之前不得释放配对租约。

`check-native-qemu.py` 是整批设备级 qtest：数据由检查器产生，验证真实搬运与中断，不是原 AP/CP 业务证明。原固件综合运行需要另记实际消费者、源码/资产身份、原始事件和正常退出。

## 普通键盘 GPIO 与 native AP 解包预算

原固件 v1 的 `r2=0xf101d000` 是通用基址。原 Thumb `bf7376: ldr r0,[r2,r0]` 与停止的 `r0=0x6000` 闭合有效 VA **`0xf1023000`（port6 DIR/pin3）**，不称 GPIO0 fault；现存旧 stderr 没有 invalid-access 行，物理 PA/DFSR 不回填为已测。原15项 kbd GPIO 表与官方 BK4 `0x01120000` 的960字节一致，输入位会经过取反和去抖后发布本地事件，不能以常量让它继续。

新 `virtual-cp-key-gpio-v1` 仅由 native CP 显式启用：`native-key-gpio-init.h` 原样保留官方 `f9014a` 的18条四latch写，虚拟 reset 为0且不宣称物理初态。`native-key-gpio-qemu.c` 注册真正 QEMU KEY handler：F1–F9 对应 `6/3,6/4,7/18,7/19,7/20,11/20,17/9,17/12,17/18`，F10–F13 是 `7/17,11/9,11/18,11/27` 四条同脚本已使能的辅助虚拟开关。pressed-low / released-high 是明确功能约定，四条辅助线也有可变 producer，不填未知电平。RDATA 来自这些开关的独立状态；未驱动、错误门控、其它已使能而无来源的 GPIO 输入均拒绝。CP17 键位与 peer17/2 分开合成，原双端线仍必须来自另一侧 GPIO18 latch，键事件不生成门铃或 ACK。不是原生菜单按键映射已完成。

`native-ap-output-readback` 是另一独立、仅 native AP 的功能profile，不改变上面的 GPIO17 peer输入合同：它只在 port18 pins9/8 的 RDATA访问时检查两位仍为GPIO output；返回内容按virtual convention取本AP本地 WDATA latch的这两位，不能反向从CP输入或其他服务填值，RDATA其它未实现位按明示profile返回零。pin方向或选择变为input/peripheral时拒绝；native profile默认关，普通/旧profile仍拒绝。原 `pcie-if` 消费者实际只读取pin9/8并基于结果切换同一输出锁存，因此此模型的业务位值来自实际可变输出状态；它只是虚拟loopback，不证明真实pad电平、原物理回读或电气极性，`physical_compatible=false`维持。


原 AP v1 在 `populate_rootfs→unpack_to_rootfs→do_copy/xwrite` OOM，尚未执行用户态。其24GiB backing中 Sony DDR 位于文件15GiB，DTB只声明6GiB，解包前仅约759MiB可用而原 cpio 输入约1423MiB。新改动只为 native DTB 声明8GiB（文件15–23GiB，仍在24GiB backing与既有8GiB peer视图内），不移动原 kernel/initrd，不修改原内核；普通路线仍6GiB。native shell窗口120秒、普通25秒，仍需实际解包和串口往返证明，不能凭配置标记启动通过。

## 原生 v2 的实际推进与传输页表

同一已过十组设备/26键事件/整机复位回归的 build6（`9846c66a…`）原固件 v2 实际通过原内核8GiB声明（`2845496K/8388608K available`）、initramfs解包、shell与137字节串口往返，devno、osal_utm、osal_uipc、dma330原模块加载成功。随后 `pcieatu` 初始化读固定 VA `0xfffffffff7300004`，发生 level-2 translation fault，PMD=0；尚未 bootin/AP。AP quit比CP RESUME早66.6003ms，CP随后在port17 RDATA拒绝已断开的对端。这不构成新的GPIO缺模型；v2没有普通键盘bank的原CP读日志，不能用首故障变化把键盘原消费记为通过。

新增 native-only 页表 helper 只覆盖两个已存在设备：ATU `VA fffffffff7300000→PA f7300000/1000`；eDMA `VA fffffffff7380000→PA f7380000/2000`。eDMA设备实际仍为`1200`，第二页尾部不补寄存器。保留GIC真正PA `08000000`，不引入原整段identity map、旧TEST的80000 ATU宽窗口、未证BAR固定VA、未实现DBI/wrapper或第二硬件root。消息root1是priority分组，不据此复制另一PCI host。

CP继续前复核既有AP claim、同binary、owner UID/精确argv/配对环境与进程starttime，避免在输入全SHA验证期间AP已退出后仍cont；它是host生命周期校验，不产生GPIO/PCIe ready或ACK。新页表和这项guard需合并host/真实原固件新一轮验收，原v2失败保持原值；未改变C6硬件/ABI或原内核模块，已过device7不重放。

## 组件诊断的安全分组窗口

组件端点明确使用 `-accel qtest`，CP 为四核 `cortex-a53` 默认能力且不运行固件。qtest 不支持 GDB，也不接受 `aarch64=off`；普通 TCG 下的 SMP GIC MMIO 不能用无当前 CPU 的 GDB 访问代替组件总线。

`component-gic-groups-qemu.c` 只在精确 `QEMU_NATIVE_COMPONENT_GIC_GROUPS=virtual-native-component-gic-groups-v1`、完整 native CP profile、已 realize 的原 GIC 和 qtest 加速器下实例化。它把诊断地址 `0x0b020000` 的 **64字节**、4字节对齐事务，以 `MemTxAttrs.secure=true` 转给原 GICD 的 `0x80..0xbc`（16个 IGROUPR）；不暴露 pending、active、IAR 或 EOI，不生成 IRQ，不代表 Sony 总线主设备或物理地址。

该窗口是显式诊断 secure master，窗口内不再依据调用者 attrs 区分权限。fixture 无原固件执行；原 `run-native-cp.py` 仍使用 TCG、A32、`aarch64=off,cntfrq=2000000`，不启用此窗口。GIC 安全扩展保持开启；普通 nonsecure IGROUPR 视图须仍读零。检查器保存16字的写入与原控制器读回，随后设备用例依赖这些 IRQ 的 **Group1** 配置；这不验证原 CP 的 Group0/FIQ 策略。

收据 schema 为 `a7c2-cp-peripherals-stage-v5`，严格要求secure窗口profile/default-off/base/64B、键盘profile/default-off/physical false、AP native输出回读profile/default-off/mask `0x300`/local WDATA来源/physical false及全局 `physical_compatible=false`。旧schema、缺字段或漂移均拒绝。

## 验收账本

完整公共 build4 与 host231项及 device5 八组已通过：安全16字、GPIO八边/门控、I2C五组真实NACK/IRQ/复位时钟拒绝、TPU六组配置与watchdog隔离、双向eDMA/正文/LLP/高64位地址abort、PL080十六通道、PL330通道0十六EVENT、五路UART及断连拒绝。两端均QMP quit、rc0、无信号，主会话核25个stage输出和binary/stage摘要。原 v1–v4 失败全部保留，device5 不回填旧轮。

随后同binary的原固件综合 v1 完成三段官方CP/tomco/BK4全量SHA读回并实际执行，遇 port6 DIR首异常；AP遇initramfs解包OOM，receiver与原AP消费false。两端实际VM QMP ack quit/rc0/无信号，CP最终drain reset仍保留为原收尾错误。

- **v3 actual** 已越过PCIEATU（`pcieatu.ko` init return0），随后在原`pcie-if.ko` init的GPIO18 RDATA读 `VA f102f010` 触发AP external abort。原模块先由GPIO18 pin9/8读取输出状态，再反相切换同一输出锁存；原BK4已证这两脚按GPIO输出配置。新v12源加了精确native AP functional loopback：仅本机WDATA bits9/8可由RDATA读回，方向/PORTSEL不符时拒绝，不访问CP/peer、不发IRQ/ACK/ready；物理pad回读/电气行为未验证。v3原异常收据保持不变；这个修复还没有host/source、build或device回归，更没有新original-pair原固件消费证据。

- v12是C源码变化，要求**2-worker完整source/host→fresh build7→整套device8**；device8覆盖输出写/RDATA读回随真实WDATA变化、方向门控拒绝及已有10组/键/复位。仅在新binary、receipt、双owner正常退出和输出内容读回由main核收后，才能启动新native original-pair v4。尚未启动该轮；v3结果不回填，receiver、AP/菜单消费、full_boot/init2、physical/capture均false。

原 CP receiver、原 AP 请求消费和完整启动仍未通过。

`full_boot_verified`、`installation_verified`、`capture_verified`、`original_ap_consumption_verified` 和物理兼容性保持 false。迁移/快照恢复明确拒绝；TPU运行、PL080外设握手、UART IRQ和后续未建模设备仍列阻塞。不得以本批构建或host通过提升这些结论。
