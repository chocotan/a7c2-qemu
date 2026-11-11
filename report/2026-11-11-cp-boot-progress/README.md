# CP 启动停点、观察器修正与 GPIO18 功能模型

当前任务继续本机硬件启动链，使用未修改的 CP 镜像、显式虚拟设备和独立实例。原固件、私有镜像和原始运行日志不进入产品源码；不连接真实相机、物理盘或 SD。源码、host 测试和原 CP 实际执行分开记账。

## 先纠正前轮结论

此前矩阵使用“300 秒 gdbstub 断开”“最高物理 PC 0x6347c4 表示最后进度”“0x6333cc 是初始化途中且只需等待”等说法，现撤回：

- `check-cp-progress.py` 曾固定 `RLIMIT_CPU=(250,250)`。这个限额累加四个 TCG 核的 CPU 时间，不能支持任意 300 秒墙钟窗口。无 gdb 的两个对照脚本同时取消了资源限额，因此不能据它们存活就锁定 gdbstub 故障。旧运行的确切致死信号未单独捕获，保留未知。
- 原 trace 在 `0x6333cc` 写入后立刻经过 `0x128190 → 0x1282f0` Data Abort 路径，再返回重试。该轮没有启用看门狗设备，地址 `0xf1388344` 未映射。
- 数值最高 PC 不等于时间上最后一条指令，地址差也不能换算执行进度。TB 翻译记录不计为逐指令消费证明。
- QMP 只在状态查询边界读取排队的事件；没有最终边界查询的失败轮，不能据未读取事件称“无 RESET”。

原报告和失败收据不覆盖；新结论依据原 trace、观察器代码、设备映射和 Sony OSS 寄存器定义复核。

## 观察器的最小修复

- 观察窗口限 1..300 秒，累计 CPU 预算为 `max(250,4*(window+60))`，另留 10 秒硬限额；固定日志上限仍为 8MiB。
- 断点/观察点停止后额外采集四个核的寄存器和 RAM，而不是只保留运行前快照。
- QMP 始终用于 owner 收尾，只发正常 `quit` 并等待返回码；不再 terminate/kill。失败保留原错误和 owner 状态，不标正常退出。
- 记录实际父进程已回收子进程 CPU 用量和墙钟，区分资源限制与 guest 执行。

已有设备完整启用后的独立 `cp-progress-hyhsb_sw`：60 秒观察内 28 组 WATCHDOG(reset)/RESET，核01位于异常记录路径 `0x631724`（目标 `0x9a21e00`），另三核原 `0x5f58c0` 空闲；task153仍未激活。QMP quit返回、owner rc0、无VM信号。该轮没有宣称 receiver 到达。

## 下一片：显式 GPIO18 输出状态

profile 为 `virtual-gpio18-loader-state-v1`，默认关闭。它定义虚拟寄存器 reset=0，再顺序执行已核官方 BK4 record ed000 的 `f9014a` 中六个 GPIO18 写入：

| 顺序 | 寄存器 | 值 |
| --- | --- | --- |
| 1 | WDATA_SET +44h | 2 |
| 2 | WDATA_CLR +48h | ch |
| 3 | PORTSEL_SET +34h | eh |
| 4 | PORTSEL_CLR +38h | 1 |
| 5 | DIR_SET +04h | fh |
| 6 | INEN_SET +24h | fh |

由此模型初态为 DIR=f、INEN=f、PORTSEL=e、WDATA=2。该**完整寄存器字是虚拟定义**；原脚本只确定被写位，未证明物理其余位或真实 loader 执行时序。模型不假称已执行 NOR，不修改原 CP 参数。

只实现 DIR/INEN/PORTSEL/WDATA 的 DATA/SET/CLR 自持状态。RDATA、pull、IRQ、未知寄存器均拒绝；没有 peer 输入、PCIe link/ready、UIPC 成功回复或看门狗抑制。运行前核 QEMU 与 stage 摘要，运行后核 guest 实际写入和读回，不能只核初始化表。

源码位于 `source/cp-boot/`，仅能接入已固定身份的私有 CP 诊断板，不替代产品默认机器。原 firmware、原镜像和旧失败均只读保留。

## 进度与证据

| 项 | 状态 |
| --- | --- |
| 旧 trace 的 Data Abort 顺序与缺映射 | 主会话已复核 |
| 观察器预算、分核快照、QMP退出 | 32项host/25子测试及三轮原CP正常退出通过 |
| GPIO18核心/适配/构建 | 4项host通过（含132个C检查和ASan/UBSan），私有QEMU增量构建通过 |
| 原 CP 消费 GPIO18 并推进 | 通过：原SET写8，latch由2变a且完整读回 |
| 原 CP GPIO17输入 | 双端功能模型中实际读取RDATA，已越过PCIEIF_INIT |
| 当前首异常 | BACKUP_INIT（索引7）：原PC55dfb6访问备份缓冲0x04000000+0xc |
| 双端GPIO与AP IRQ | 两个QEMU实例及实际AP GIC通过；原AP软件未运行，CP IRQ/CP16仍未接线 |
| receiver 创建/执行和合法回包 | 未验收 |
| SPI/PCIe更新、完整硬件启动链 | 未完成 |

私有证据目录为 `analysis/scratch/cp-wait-20261111/`；历史原件见 `analysis/scratch/cp-progress-20261111/` 及各 `cp-progress-*` 运行目录。

## 复现入口（显式诊断）

新增模型默认不会进入普通产品窗口。`source/cp-boot/stage.py` 只接受其内固定SHA的私有CP板级源，保留修改前两个小源码文件，未知基准拒绝。它不是一份可直接应用于 vanilla QEMU 的完整 CP 板移植。

在上述基准与原有GIC/timer/watchdog/eDMA模型已经具备时，主会话完成：

```sh
python3 source/cp-boot/stage.py /path/to/private-cp-qemu-source
cd /path/to/private-cp-qemu-source/build-cp
ninja -j2 qemu-system-aarch64
```

本轮模型二进制SHA为 `9113a04a50f1a4da616c5522b3e551a5fa765a3eeb174ec538a5983ff8c0bf75`，旧二进制 `981594ee…` 已完整摘要读回保全。探针额外核 `cp-gpio18-build.json`、stage摘要和全部修改后源码，不把仅设置环境变量当成已安装设备。开启开关为 `--gpio18-loader-state`，其它原参数不变，看门狗仍按原功能运行。

## 原 CP 实际消费与下一首故障

[`validation.json`](validation.json) 绑定三轮原始收据全文SHA：

- `cp-progress-1wy2sgmh` 中，初始 WDATA=2，原 CP 向 `0xf102f044`（WDATA_SET）写8，随后读回 **WDATA=a**。DIR/INEN/PORTSEL分别仍为f/f/e。探针没有寄存器写入，唯一相关写操作来自原 CP；模型消费通过。60秒内仍有27组WATCHDOG/RESET，receiver断点未命中。
- `cp-progress-270movni` 在第一次 Data Abort 的原A32向量 `0x128190` 停止，**此前没有RESET/WATCHDOG事件**。ABT LR=`bf737e`，故障PC=`bf7376`，原始半字 `5810` 为 Thumb `ldr r0,[r2,r0]`。现场 r2=`f101d000`、r0=`11000`，地址为 **f102e000**，即 GPIO17 的 DIR，pin r1=2。该轮 GPIO18 已读回a。
- 这把首故障从GPIO18推进到GPIO17，未补未知输入电平或peer响应，也没有消除看门狗到期来掩盖阻塞。

三轮原CP的18,090,880B guest加载全文摘要一致，断点均正确移除；每轮QMP quit确认、owner返回0、未发送VM信号。task153仍是原记录、state0，接收器/原合法回包、AP↔CP传输、SPI/PCIe更新和完整硬件启动保持未完成。

观察器集中host为32项/25子测试，GPIO核心与接线为4项，两个worker并行；它们不代替原CP消费。不以空ACK或手工激活任务冒充原业务完成。

## GPIO17：输入消费者与配置依据已闭合

停止于轮次上限的调查代理已留下 `analysis/scratch/cp-wait-20261111/gpio17-review/HANDOFF.md`；该代理没有最终输出。主会话重新核了原CP全文SHA、关键Thumb分支、两份官方PP属性全文SHA和逐项脚本数据，以下是已核收事实，未将代理状态改记为成功。

- `PCIEIF_INIT` 的 `56a960/56a962/56a964` 直接传 `(17,2)` 调用 `bf7838`，不来自不明表项。该函数先读DIR，方向位值为0时尾调 `bf73c4` 读取 **RDATA `f102e010` bit2**。
- `56a968` 比较返回值是否为1；等于1才调用 `56c6c4`，置一次性标志并唤醒两组本地事件。原IRQ handler `bee790` 也调用该路径。因而0和1不是等价的占位输入。
- 同一个 `f9014a` 属性在CP候选 record ed000 的行171–177配置port17；DIR_SET=8、DIR_CLR=fff357、INEN_SET=fff357、INEN_CLR=8。对任意原复位字，**pin2方向为输入且输入使能**。AP候选 record0的行91–98也对pin2给出同样方向/使能结论，PORTSEL不同。
- 脚本表语义不证明原NOR已执行或记录绑定已由真实loader完成；这些写入不提供RDATA电平，原栈残留的 `bee819` 也不能当成本轮直接caller。

[`verify-gpio17.py`](verify-gpio17.py) 使用标准库复算已固定SHA的原CP/PP和上述REG投影，无需IDA或Capstone。原件只读、输出必须新建；样本路径由读者显式提供：

```sh
python3 report/2026-11-11-cp-boot-progress/verify-gpio17.py \
  --cp /path/to/cpapp-b.bin --pp /path/to/CX89701_ALLLANG.bin \
  --out /path/to/new-gpio17-static.json
```

[`gpio17-static.json`](gpio17-static.json) 为本轮静态复算收据，输入值保持null。新5项host测试和原资产复算按两个worker集中执行；不与此前36项相加，也未重跑未变的旧CP窗口。本轮没有修改运行模型或提供peer电平，receiver及完整启动保持未通过。

下一步沿原AP的GPIO18通知输出及其实际MMIO消费者，建立双端状态与IRQ连接。公开AP内核 `IRQ_GPIO_BASE` 有机型条件（88或238），不能直接据此给CP注册的逻辑IRQ `0x121/0x122` 接线。该静态阶段之后的新增功能与实际消费见下一节，旧静态收据不回填。

## 新增：双端GPIO功能切片已实际消费

[`source/cp-boot/NOTIFY.md`](../../source/cp-boot/NOTIFY.md) 给出 `virtual-ap-cp-gpio-lines-v1` 的定义、协议、构建和复现入口；[`notify-validation.json`](notify-validation.json) 为本轮独立内容核收。原GP18单端与GPIO17静态结果保留。

本功能保存双方GPIO17/18寄存器，以对端GPIO18实际输出latch生成有序快照；连接无效、输入未使能、输出未驱动或坏帧时拒绝读取。AP侧GPIO17/4、17/3接到真实GIC的SPI60/59（INTID92/91）。跨芯片配对是显式功能模型约定，物理布线未验证；CP中断与CP16未建模，不生成PCIe ready、UIPC回复或其它ACK。

AP IRQ依据由主会话复核原Image `620a6a3c…` 的函数文件偏移 `31ae28` 和原通道表：GPIO17/18物理字段位于Image `6407b0/640848`。代理原写的 `640970/640a08` 属于重建ELF偏移，不能当原Image偏移；VA基址猜测未作为映射判据。原AP驱动路径为 `MENU_PCIE_IF=1`、`--load-ipc` 和PCI DMA前置；默认冷启动仍不加载这个远端sender，且它与现有虚拟sender互斥。本轮不把原模块历史加载成功提升为新模型上的原AP消费。

验收分三层：

- 两worker集中host：**41项测试、29子测试**，其中新C状态机在ASan/UBSan下197项检查通过。首次QEMU构建因QOM类型常量命名不符失败，原失败源码/日志保留；修正后增量构建通过。
- 实际QEMU配对：AP SET/CLR改变CP RDATA；CP两路输出改变AP输入并设置GIC pending；本端reset保留外部输入，断连拒绝。分片帧、错误角色、序号跳跃、未知掩码和未驱动电平负例通过。三个测试owner均QMP quit确认、rc0、无信号。
- 原CP `cp-progress-u_gpjgdl`：18,090,880B加载全文摘要仍为原值；原CP读GPIO17 DIR后实际读取RDATA（来自对端输出设备的有效快照），不再在GPIO17异常。原CP的SET8输出同时传到对端并读回GPIO17值10h。初始化从索引5 `PCIEIF_INIT` 推进至索引7 **BACKUP_INIT**；首异常为原Thumb `55dfb6` 的字节读取。原 `55dfa4` 先计算 `lr=r0+0xc`，现场r0=04000000、r3=0，故有效访问为 **0x0400000c**，不是用banked ABT LR推导。此前无RESET/WATCHDOG事件；CP与功能peer均正常QMP0退出。

新的阻塞是尚未承载的原备份缓冲，正核对其真实loader来源、地址、格式与记录选择。没有给它填零、造BK4头或改原参数。

原CP这一轮的对端是**寄存器模型，无原AP软件**。双端设备、AP GIC及原CP GPIO消费通过；原AP↔原CP、CP IRQ、receiver、完整启动、P1安装完成、拍摄成片仍未通过。默认产品窗口与旧失败没有改动。
