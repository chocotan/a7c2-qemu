# CP 启动停点、观察器修正与 GPIO18 功能模型

> **勘误与当前状态**：v38 的 CP 未执行 `cont`，其零 MMIO 计数不能证明缺失设备已排除；原探针记录虚拟地址，也不能单凭地址范围判断物理 MMIO。`0x55e010` 是 `BK4\0` 数据，真正注册函数入口 `0x55e014` 由 `0x55dcf4` 直接调用，故“注册器不可达、必须外部样本”的判断撤回。现有实验仅加载官方 PP 的 `ed000` 单条记录；完整 PP 原件包含从偏移 0 和 `0xed000` 开始的两条记录。完整 PP 的隔离实验已全量读回输入并实际执行原CP，越过旧 `0xbe9a14` 停点，新首次 data abort 为 `0x595cfc`，寄存器表明尝试写 `0xf1388f4c=0x101`；receiver 和观察窗口仍未完成。原CP代码将 `0xf1388f48..58` 用于 DFS 初始化、请求、目标、触发和状态；新的 CP 虚拟功能模型只实现该可观察子集，不改变时钟，不声称物理兼容。MSC 是否同因尚未证明。P1 更新的原始失败另有明确的 SPI 节点缺失、pcidma 驱动未建模和 link 未就绪证据，不能归因于此 DFS 停点。

当前任务继续本机硬件启动链，使用未修改的 CP 镜像、显式虚拟设备和独立实例。原固件、私有镜像和原始运行日志不进入产品源码；不连接真实相机、物理盘或 SD。源码、host 测试和原 CP 实际执行分开记账。

独立静态追踪已将 `0x595c44` 连接到 `USER_TSK_INIT2` 初始化项：`0x1535f4 → 0x596a98 → 0xc0beb0 → 0x595c44`。若 DFS 写成功，该分支返回后先更新 RAM 并注册软件回调；后续回调在计数达到 `0x4e20` 且一次性标志未置位时，可能读 `0xf5410244`。原 CP 的地址与字符串传参将它明确命名为 `MTG_REG_CDC_FCS_OFST`，相邻 `0xf5410240` 为 `MTG_REG_CDC_FCS_SEL`；原 setter 写 OFST 的低 26 位和 bit31，随后读回并执行 DSB。修正后的原始表采集（`scratch/cp-f5410244-attribution-20261114/tables-v2-readback.json`）还发现 `mtg_fcs_cdc_param_test` 指向此前四组配置/读回循环，故这些测试输入不能当作硬件复位值或启动必经配置。当前已核 CP stage 未发现该地址映射，其物理译码、复位值、回调是否执行及实际读值仍未知，不添加假状态，也不将其预测为下一次故障。指令窗口及输入身份分别见 `scratch/cp-dfs-static-followup-20261114/README.md` 和 `scratch/cp-f5410244-attribution-20261114/`。

六份意外 `/tmp` 原日志及一个旧测试 socket 的引用审计仍存在 unknown，均保留。新产生的日志均已与项目内私有副本逐文件完整 SHA256 读回；保留原因与回收条件见各自任务目录的 storage 或 preservation 收据。

BKSB 静态候选另补有 `scratch/a7c2-bksb-static-candidate-20261114/test_candidate_builder.py`：计划以原 PP 与原列表检查输入身份、拒绝切片和修改，并用独立属性索引逐项检查描述符、原值与填充；该测试尚未执行，原 `bksb.elf` 输出也尚未对照。

独立 OFD 加共享 `flock` 可避免 AP 对自身描述符解锁时同时解除 CP 的独立锁，但交接前父进程仍有各自 OFD 别名，不能证明活 VM 租约必然保留。现有 guard 只认 WRITE 锁，且不适配 AP 的 PID namespace；真实 wrapper、FD 移交和双 VM 放行屏障仍缺。QEMU 11.1.2 的 `system/vl.c` 自动启动路径还可直接调用 `qmp_cont(NULL)`，不经过 QMP dispatcher；GDB 可以直接调用 `vm_start()` 或 `vm_prepare_start()`，复位和唤醒路径还会直接调用 `resume_all_vcpus()`。仅限制 QMP 分发或 `qmp_cont()` 都不足以建立完整启动屏障。QEMU 内部自行 `openat` 的独立锁方案也仍有获取锁前的父进程崩溃窗口，两方案均保持阻塞。审查见 `scratch/a7c2-independent-sh-ofd-review-20261114-v1/README.md` 和 `scratch/a7c2-inprocess-openat-sh-review-20261114-v1/README.md`。

host 测试的 audit-first 登记、一次性 basetemp 和失败材料保全也已有关闭态候选 `analysis/scratch/cp-wait-20261111/host-runner-registry-retention-v1/`。PEP 578 hook 只覆盖当前解释器的受审计调用，child、native 和 ctypes 仍未证明覆盖；候选套件入口在资源创建之前拒绝启动，低层类不能被绕过入口用于运行；功能断言不能当作环境合规。

新 `analysis/scratch/a7c2-qmp-independent-sh-cont-closed-candidate-v1/` 已包含独立 SH 守卫和多层 CPU 防线的源码候选，但 profile 在 machine 创建前永久拒绝，尚未编译或验证；它不能推进要求 `running:true` 的 DFS qtest。单 CP `scu_i2c` 静态配方已确认原检查不消费 AP，但持久 owner、租约和故障恢复仍缺。现有 `dfs_transactions()` 在 `cont` 返回后才记录 running，因此请求生效而回包丢失时运行状态未知，不能沿用同一失同步通道假设已暂停；该路径须保留 owner 或由独立可信控制通道处理。双 VM 放行协议仍在开发。双端顺序放行时若中途失败，应保留并报告部分启动状态、持有锁和 owner，禁止将其记为成功；本任务不额外要求两端原子启动。上述内容不能用空闲连接代替真实 AP 执行。

四类直接 socket 测试夹具已有后续源码候选 `analysis/scratch/cp-wait-20261111/direct-socket-fixtures-followup-v1/`，其中 FIFO/目录仍走真实 `admit()`；原 socket 作为 RAM 文件的完整准入场景在 F/S 分离下尚无真实 provider，新增 `_regular()` 单测不能继承原场景通过。冻结 bridge 仍使用外置插件候选，权限测试和 QMP 监听线程的完整接管尚未验收。

原通知设备的输出帧固定 16 字节：`OPENED` 及设备 reset 会强制发送快照，GPIO18 成功写入会按变化发送；`scu_i2c` 所选断言本身不写 GPIO18。具体启动事件次数、socket 缓冲和设备消费仍未运行验证，空闲对端不可发送 AP 数据。MTG 的 `0xf5410240..247` 在已核 v8 `null-machine.c` 明确列出的 MMIO 映射中未出现；这是源码检查，不代替 QEMU 实例实际地址空间读回。

MTG 地址有默认关闭的纯 C 和 QEMU 功能模型候选 `scratch/cp-mtg-functional-candidate-20261114/`：两字均只在完整 32 位写入后回读，未知复位状态的首次读返回错误，不提供 IRQ、PLL 或 ready。纯 C 核心已在独立主机批次中编译并通过合成测试；QEMU 包装仍未构建、模型未接入产品，原 setter 先读后写，因此不能宣称它能越过首次未知读取；stage/schema 和最终 MMIO flatview 仍需合批核收。

若 UPM 初始化及其先行调用均返回，`USER_TSK_INIT2` 的 `0x7a748c` 路径还会写 `0xf49300ec=0/1`、`0xf49300e4=0`、`0xf49300e8=23`，并对 `0xf4830000/0xf4840000/0xf4850000` 三组基址写 `+0x100=0` 与 `+0xf8=0x3ff`。原始指令及基址表已独立读回；这些地址未见于 v8 的已核显式板级映射，设备含义、MMU 别名、运行是否到达和硬件副作用均未知，不能用无行为的写入桩冒充设备已初始化。详细证据见 `scratch/cp-init2-static-deps-20261114/README.md`。

MTG/P1 联合源码候选 `scratch/cp-mtg-p1-static-merge-20261114/` 使用唯一候选 schema，保留两项诊断 profile 默认关闭；其 `stage()` 仍在任何 staging IO 前硬阻塞，尚不能应用或构建。若以后替换当前 recipe，`check-notify-qemu.py:contract()` 会使用新 schema 校验旧 v8 的外围收据；旧二进制不能自动继承新配方身份。因此在确定 v8 单组补验及新 build 的先后和隔离方案前，不覆盖现有 stage，也不更新旧收据。

已核 `102/103/104` 的前置路径还分别向 `0xf5400e10/20/30` 和 `0xf5400610/20/30` 写 `1`，每次同地址读回并执行 DSB，但不比较 readback 或等待 ready/ACK。三 bank 的两条实际软件路径分别是读 `+4` 后将原值写 `+8` 再按低 8 位分派，及读 `+0xf4` 后按低 10 位向 `+0xfc` 写单 bit 并分派；这些指令不能单独证明硬件清位、IRQ 连接或时钟语义。完整边界见 `scratch/cp-f493-banks-attribution-20261114/README.md`。

匿名 RAM 单 CP 组件机的源码方案见 [cp-local-component-proposal.md](cp-local-component-proposal.md)：它可免除 AP/notify 及共享磁盘，但必须保留 SCU realize 所需的 DMA、TPU 等原有设备，且要新构建；owner、租约和未知 `cont` 恢复仍未闭合，不继承 v8 或原 CP 执行通过。

后续 `scratch/cp-peripherals-consumers-20261114/` 已补充 stage/build/source checker 及测试夹具的 29 文件源码候选，但 diagnostic realize 仍固定拒绝，单 CP profile 与该补丁的 schema、header 和 secure-GIC 守卫冲突尚未合并；其中候选来源清单也不能在 v8 补验前写入产品。该补丁未执行 staging、编译或测试。

## 官方 loader 与本轮合规状态

官方 `loader_nor.bin` 长 94,176 字节，SHA-256 为 `5887ce4e6ca5fe1acdf6b675457f70e9798c61686f1d62c95190158855c96b22`。原指令 `0xfe04909c..0xfe0490ac` 以 MPIDR Aff0 计算每核栈顶 `0xfe160000-(Aff0<<16)`；这不是已证明的最大栈深或物理 SRAM 边界。原 scatter 记录指定 `[0xfe05ffe0,0xfe061af8)`，由 `0xfe04c678` 的原代码清零。官方 `pformat_config.txt` 指定 `LdrBkup.bin` 的 `ldrinfo=2`、加载地址 `0xfe048800`；官方脚本以原 `bksb.elf` 从备份及列表生成该数据，实际默认输出和完整头仍未验证。`source/cp-boot/official_loader_page_tables.py` 新增从同版原 loader 或官方 `loader_nor.tar` 直接静态重建页表的入口，归档和全部成员按完整 SHA256 校验、无需落盘解包；该入口尚未完成本批测试。它不拼造 NOR 前缀，也不证明 loader、BootROM 或物理别名已执行。

原始 `bksb.elf` 的静态候选进一步定位了 `BKSB` 项目表：按官方列表顺序记录属性 ID、相对数据偏移和原始长度，属性数据按四字节以 `0x30` 填充；从完整 PP 按原 `-c` 逻辑选用第二条记录。候选推导长度为 1,104 字节，但尚未执行官方生成器或对照其输出，默认备份选择亦未闭合；**不能把该候选当作已验证的启动输入**，也未合成 BK4 头、ACK 或 NOR 前缀。候选和原指令索引位于 `scratch/a7c2-bksb-static-candidate-20261114/`。运行根中已只读确认原 `libosal_uipc.so` 存在；生成器的实际 IPC 分支、沙箱与原生输出仍未执行验证。

隔离 observer v7 已由受保护 initramfs 比对过的 `0600` 私有库副本构建，原运行根文件和权限未修改；全树摘要读回通过，observer SHA-256 为 `3d358fa8cfd5e3dfcf6ba4c15222306f893233358148e725f889abdd1f7766ee`。两组、两线程的主机回归中，product-host 为 548 通过/49 跳过，public-models 为 38,513 通过/275 跳过，失败及错误均为零；但事后发现部分旧测试在项目临时目录创建 pathname socket，不符合本项目短 socket 路径合同，因此仅记功能断言通过，**不记环境合规验收**。旧收据不改写，独立偏差记录见 `analysis/scratch/cp-wait-20261111/host-socket-policy-incident-v1.json`。

真实 AP/CP 配对和 DFS 单组设备补验由本任务协调器保持阻塞：短 socket 需迁至专属 `/run/user/<uid>/` 目录，并完整保留 QMP peer、原有 inode/owner 校验和父进程异常时的租约事实；这些阻塞尚未接入所有旧产品入口，不能直接运行旧脚本绕过。QEMU 11.1.2 的 `monitor_fd_param()` 可以解释数字 FD，不将租约 FD 注册进 fdset 并不足以证明它不能被任意 QMP 命令消费；现有 AP `bwrap --die-with-parent` 也不能作为正常 QMP 退出证明。无 pathname 的 socketpair 有上游源码支持，但 keeper、FD 交接和异常恢复尚未验收。一项旧测试 socket 和六份工具自动生成的临时输出因全引用审计尚不完整而保留；六份输出均已在项目私有目录完整摘要读回，未发送信号或执行回收。新的源码、候选及所列历史通过均不证明 CP receiver、完整启动、真实更新或物理兼容。

新增两线程合成基础设施批次 `scratch/infra-two-worker-runs/run-pmisnl0v/`：两组确实并发，源码前后摘要一致；MTG、f540、P1 SSI 及 P1 SSI 扩展共四组纯 C 检查通过，OS 组 24 项合成锁、0600 短 socket 和真实子进程凭据检查通过，登记子进程均正常退出且未发信号。`attempt.json` SHA-256 为 `3294d5a5f8d1b554d73ee14481021f22c3cab4d8e647c2c9a8146b0948cc2c89`；总状态有意为 **partial**，进程返回码 2。父进程异常死亡、持久 keeper、真实 QMP/QEMU、原 AP/CP 和固件启动均未执行；这批结果不能解除真实配对启动门。短 socket 和测试产物保留，待完整引用审计。

## 本轮设备验收和原 NOR 交接

新 CP 二进制 `b04d212b...` 已完成一次独立 qtest 组件批次，未执行原 AP/CP 软件；AP 和 CP owner 均正常 QMP quit、rc0、无信号。原 CP 镜像静态指令中，首故障所在函数入口为 `0x595c44`，`0x595cfc` 的 DFS 写入之后执行 `movs r0,#0`，并从 `0x595d18` 恢复栈返回；该尾部和调用者后续仅为静态路径，尚未实际观察到执行。11 组中 10 组有通过结果，`scu_i2c` 在 DFS 完成读回处失败：该测试在 QEMU 暂停时调用 `clock_step`，QEMU 虚拟时钟禁用，定时器回调未执行；后续键盘组恢复运行后日志才出现 `CP_DFS complete target=0x102`。第二目标没有执行，不能将 DFS 组件记为通过。检查器已改为确认运行态后推进虚拟时钟、在 `finally` 恢复暂停，并新增仅选单组的补验边界；修正后尚未执行设备补验。原失败和两个 owner 收据保留在 `analysis/scratch/cp-wait-20261111/native-device-v10-first-qtest-cp-build-v8/`。更早的启动器因错误超时在启动设备前中止，另有不可覆盖失败收据，未发生 QEMU 信号。

当前原 CP 路线仍由 QEMU 通用 loader 直接把 `cpapp-b.bin` 放到 `0x108000`，**没有执行 Sony BootROM 或 NOR loader**。独立只读调查在原 NOR loader 中找到了 BKUP、KRNE、ESCP 的条件消费者；KRNE 由 AP 配置步骤发布，不是 CP 回复。原 loader 还包含 A64 EL3 到 A32 SVC 的交接及次核放行代码，但真实 reset/strap 选路、高位邮箱与本地内存别名、原 B0 生产者及完整 SRAM/设备环境仍未知。已形成树外的输入与证据解析候选，尚未接入产品、运行 loader 或证明 BootROM 执行；不以主机写标记、改 PC 或虚拟 ready 代替原消费者。

## P1 SPI 参考边界

现有 A7 IV Cetus 参考 BootROM 的 SHA-256 为 `27a06e28a2ae8a7107589b441d0c9aad06889be42e674cb63037dda8e1392b89`，并非已确认的 A7C II ROM；其 SPI monitor 命令与 A7C II 原更新器的 16 字节请求、双 ready、逐块 ACK 和带序号响应相互对应。原更新器的流程是先按顺序下载 `nor_ldr.img` 与 `loader_spi.bin`，再请求跳转并等待后续 PCIe/CP updater，不等同于已启动的 `cpapp-b.bin`。

QEMU 11.1.2 的上游 PL022 未实现 peripheral/slave 模式；当前新增的 AP PL022 只是默认关闭的无对端组件。原参考 ROM 还依赖 CP 侧 FIFO、主机时钟消费和 reset/strap，跨实例背压及真实 loader/PCIe 交接尚未实现。SPI token 或传输成功不能单独证明原 CP 代码执行、link-ready、驱动绑定或固件安装成功。原始调查路径见 `analysis/reference/ILCE-7M4-RE/bootrom/README.md`；参考 ROM 本身不复制进产品。

隔离目录中另有未集成、未编译的 SSI monitor 候选：以传输开始时的状态决定输入输出，避免最后一拍误收 MOSI，并显式使用默认关闭的虚拟片选；独立审查发现失败日志无界，已有独立限额修正候选。这些均未通过本批测试，真实片选、原驱动绑定、CP ROM/loader 执行与更新成功仍未验证。

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
| 当前首异常 | USER_TSK_DRV_INIT（保存索引12）：原PCbef42a向SCU f1388054写40000h |
| 原BK4输入 | 原样官方记录全段读回，原CP实际建立04000000/04000100/04001432索引 |
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

该轮新的阻塞是尚未承载的原备份缓冲，后续原样数据承载见下一节。没有给它造BK4头或ACK，也未改原参数。

原CP这一轮的对端是**寄存器模型，无原AP软件**。双端设备、AP GIC及原CP GPIO消费通过；原AP↔原CP、CP IRQ、receiver、完整启动、P1安装完成、拍摄成片仍未通过。默认产品窗口与旧失败没有改动。

## 后续：原样官方BK4输入已被原CP绑定

[`source/cp-boot/BACKUP.md`](../../source/cp-boot/BACKUP.md) 描述 `virtual-official-cp-bk4-input-v1` 的限定与复现，原样加载工具为 `official-backup.py`；[`backup-validation.json`](backup-validation.json) 绑定本轮两份原始收据与源码。

主会话核原指令 `55dcc2 mov.w r0,#0x4000000`、`55dcc6 bl55df9c`，以及原 `55df9c` 的BK4签名和819项索引构建；这不是tomco新增参数。官方PP的两个记录头前20B相同，初始检查不能决定原loader选择哪份。此次显式选 `ed000`：**1419512B，SHA a90b46ae…**，整记录原样装入0x04000000，宿主只读绑定并跨GDB完整读回。诊断RAM backing由64MiB扩大到128MiB，guest仅修改自己的临时RAM；它不是Sony物理总RAM测量或真实地址别名证明，也没有持久NVRAM写入器。

两worker集中host **45项/29子测试** 通过。`cp-progress-_s460w5m` 首轮原样记录读回通过后，首异常已变为 `bef42a` 的 `str r1,[r0,r2]`；不能再把被调用者覆盖后的r11当作初始化索引。首次后处理因此报错，已单独保留，未改原正常运行收据。

为核真正消费和原调用方，修改只读观察器后补取 `cp-progress-2g84h8_8`，未重写首轮：

- 运行前 `1a7e85c..864` 三指针全零；运行后由原CP建立 **04000000 / 04000100 / 04001432**（根、6B索引表、819项表尾），证明原binder实际读取了原头和计数。
- 原模式r7栈保存record `eb56b4`、索引12、返回 `63505d`；对应原表名称为 **USER_TSK_DRV_INIT**，原wrapper `635054→bf7ef0`。这比当前被覆盖的r11更可靠，未据此宣称每个前置业务成功。
- 首故障原指令 `bef42a str r1,[r0,r2]`：r0=50h、r2=f1388004h、r1=40000h，因此实际写 **f1388054h，值40000h**。寄存器用途/最小模型另作原码和GPL调查，不先填ready。

两轮CP与功能peer均QMP quit确认、rc0、无VM信号，首异常前均无WATCHDOG/RESET。原CP镜像和741B tomco未修改；原PP来源再次完整核验保持不变。原loader bank选择、36位高位地址交接、BKUP握手、真实AP联动、CP IRQ及完整启动继续保持未证。

## 当前合批：外围与原生 AP/CP 配对源码

本批实现和未验边界集中在 [BOOT-PERIPHERALS.md](../../source/cp-boot/BOOT-PERIPHERALS.md)。包含 SCU/DW I2C、PL330、逐通道 PL080、PL011、TPU配置、保留 watchdog 语义的共享SRST4，以及双独立RAM/真实eDMA/原AP最小headless配置；全部源码完成后统一构建、两个工作线程验收。此段尚无新的构建、host、原CP receiver或原AP消费通过结论。

产品新增根目录 `build-cp-native.sh` 与 [platform](../../source/cp-boot/platform/README.md)：从固定官方 QEMU archive 和原产品 native patch 重建CP基板，无需提供旧研究源码树、完整dump或私有设置。干净生成父收据和历史冻结父收据各有明示SHA；新构建不复制历史失败标签，旧收据不改写。

TPU运行与IRQ、PL080外设握手及SCU复位路由、UART IRQ、完整官方启动链、P1安装和成片仍未完成。CP16初始输入使能和双沿门铃是明确功能模型选择，物理配置/沿编码未证；只有综合运行中的原事件、状态和数据消费才能提升对应层级。

## AP/CP Owner Lifecycle

F1-F3实现与336项host合同见[owner-lifecycle.md](owner-lifecycle.md)。新增v5实际pair核收见[native-pair-v5-owner-readback.json](native-pair-v5-owner-readback.json)：AP claim与真实QMP SO_PEERCRED peer绑定通过；CP QEMU已启动，原始输入完整RSP读回并pin AP owner/QEMU双pidfd；AP guest在settle中异常退出后，CP在初始`cont`前按owner guard拒绝。双方QMP均正常quit rc0/无信号，所有PID已消失，lease保留。**这证明真实fail-closed拒绝，不证明原CP已执行或AP/CP启动成功**，full boot/receiver保持false。

v5时序显示完整CP预启动读回占用AP guest异常前的窗口。当前改动只在CP专用RSP子类按已核QEMU 11.1.2 `MAX_PACKET_LENGTH=131104`扩大响应上限，保持全部原始内容SHA读回，共享camera broker/UI未改。两线程host验收已通过：桥接+CP 1,055项、产品host 512项通过/49项skip/0失败，见[host-validation-rsp-v16.json](host-validation-rsp-v16.json)。新包长边界覆盖仍未在实际QEMU测时；fresh v6 pair尚待source freeze和空间门。
