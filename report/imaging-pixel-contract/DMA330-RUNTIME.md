# 原DMA资源、地址域与PL330实验范围

当前已证原模块装载、真实资源表及地址转换；原驱动传输、LIRO图像消费和拍摄仍未验收。

## 原kernel运行资源

kernel-only `trial-3l3vi7ab`在guest核原DMA330模块完整SHA和Uid/Gid全0，读取实际`udif_devices`符号及其+240h设备记录。经专属QMP暂停，只读设备和18项通道记录后恢复CPU；新guest命令输出证明实际恢复，随后QMP正常退出。未启动相机、挂SD、发送DMA或请求批量启动驱动。

|通道|实际MMIO／大小|原GIC中断|用途|
|---|---|---|---|
|0..7|F1056000 / 1000h|112..119|controller0传输|
|8..15|F1057000 / 1000h|145..152|controller1传输|
|16|无MMIO记录|144|controller0 abort|
|17|无MMIO记录|177|controller1 abort|

每项IRQ名、实际handler指针和cookie随表读回，cookie为0..17；`/proc/interrupts`独立列出相同18项。资源存在和IRQ注册不代替中断已触发或传输已完成。

首轮资源探针`trial-7h2kklgy`错误把设备记录+28h当count；实际+18h为18、+20h为通道指针，+28h为0。探针拒绝并正常恢复/退出，原失败和独立main review保留。修复观察器，5个解析测试通过后重验上述记录。不能把观察器布局错误写成kernel资源缺失。

## 32位总线地址域

原kernel镜像SHA为`620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2`。由运行UDIF符号/inline设备名绑定此镜像链接基址`ffffff8008080000`，再核原绝对导出表，而非把AP/CP换算套给kernel：

|导出|原镜像file offset|
|---|---|
|arch_p32_to_p64|31b780|
|arch_phys_to_va|31b608|
|arch_phys_to_noncache|31b298|

`arch_p32_to_p64`的正常返回域：

- p32≤FDFFFFFF：zero-extend后置bit34，即DRAM窗口`400000000+p32`。
- FE000000..FEFFFFFF：zero-extend原值。
- FF000000..FFFFFFFF：进入原错误处理路径，不是正常地址转换。

`verify_kernel_dma_domain.py`核完整SHA、4项实际导出指针和p32分支原字节，主会话已实际运行通过。名称字符串在诊断文本和导出字符串区都出现；搜索必须取真正的name-pointer/value配对，不能用第一次字符串命中当导出。上表链接VA只用于此镜像核验，运行实例地址仍须分别绑定。

## QEMU实验

`scratch/sony-pl330/`从固定QEMU11.1.2归档和既有native/USB补丁构建独立候选，不覆盖稳定二进制。新opt-in把两个stock PL330连到已证MMIO/GIC资源；为DMA创建独立总线地址空间，其alias指向实际system backing，按上述p32域访问高位DRAM。

stock模型原本忽略四处`dma_memory_read/write`的MemTx结果。候选补读指令、读数据、写数据错误处理，取消该tag的队列/FIFO，进入真实fault状态及abort IRQ；错误不能继续发正常SEV。没有预填destination或无条件完成回调。

定向qtest通过debug指令启动真实PL330微码，从源搬运256B到目的，核前后哨兵、源未改、event/clear及GICpending；覆盖两控制器全部16通道。错误域另核指令fetch/read/write，不以返回0作完成。构造失败、未通过项保留独立原始结果；整体结果以实际测试为准。

首轮16项正常微码搬运及read-fault分项通过，但后续write-fault在复用QMP reset后未达预期，原失败保留。重验改为每项fault独立冷启动，`pl330-qtest-3ptv0_5s`的16正常通道及read/write/fetch三项错误均实际通过，main另读完整result核对；此范围不含QMP reset后的控制器状态合同。默认关闭的负对照也通过。

这次硬件测试的候选binary SHA为`b2ca2ed78d8dd156d2448de4c9acd73fae6da78fa324f09033767ad506d6a0a1`。它仅供bwrap内qtest；原kernel入口要求`-sandbox on`，因此另加seccomp配置重建、保留旧binary/proof并重跑相同测试。不得删除原入口的sandbox参数来迁就候选构建。新binary与原kernel运行仍分别验收。

这些是硬件模型范围。还需原DMA请求/描述/完成所有权闭合，再执行原kernel驱动消费；即使qtest全部通过，也不计原CMOS、AF、编码或照片录像完成。

## 原kernel映射阻塞与诊断模块

带seccomp的新候选SHA `437a6a9b9df1f0fa3dde3ec7e260c0e15d4822f98c5e40a1b6a4abe73a0d8a2d`已在显式`-sandbox on`下重验同样16+3项。原kernel随后能装载DMA330并把16个通道软件state置2，但这不是MMIO可用证据。

原proc默认打印缓存；主会话先核`read_regs=1`分支才执行快照。`trial-zs8uy9e6`在模块.text+14读`fffffffff1056000`发生缺页，真实物理PID读取则为30，QOM存在两个PL330。这证明通用virt未建立原driver预置的静态IOVA，不能把全零缓存或软件state2当硬件读回。该轮无DMA/App/SD owner，专属QMP正常结束，原失败保留。

准备设备映射适配层：在原DMA330装载前，检查原UDIF记录并用原导出`udif_ioremap`建立两组实际4KB映射；先核两组PID，再仅发布16个资源的virtual字段，保存资源归属。不是修改通道state或AP/CP门禁。映射失败须原`udif_iounmap`撤销、不得发布；成功映射模块保持常驻直至该VM退出，不能在driver使用期间卸载。

为此独立生成了768B模块描述布局的自有marker-only诊断模块，正常insmod不绕过kernel检查。首版被原loader拒绝ADRP relocation275，保留`trial-uy5ypg4m`及旧构建。改用`-mcmodel=large -mpc-relative-literal-loads`生成CALL26/ABS64；严格ELF checker及9项破坏测试通过后，`trial-qa688ytv`实际观察到init标记、loadRC0和Live，正常退出。它没有调用DMA或MMIO；仅建立后续适配层的可加载ABI基线。

MMIO适配层自有C代码的ASan/UBSan测试已核：仅virtual字段改变；错误设备/已注册handler拒绝；第二映射或PID失败时不发布并回滚。严格原guest重验`trial-ijtxvj7e`已完成：正常装载适配层和原DMA330，原`read_regs=1`读到两项PID30，16个实际资源指向两项新映射，物理PID/QOM独立相符，CPU新命令输出及正常QMP退出通过。main另写`main-mapped-mmio-review.json`，明确没有提交DMA或成像。

该范围中曾有`trial-dfx017kx`自动证据拒绝：大段base64 tty回显与之前Uid/SHA输出交错，虽映射模块已发布但不能据污染行采纳身份。修复发端，在输入消耗后重新输出完整身份；没有放松整行解析或修改旧失败。

## 下一项原请求实验

独立resident客户端只调用原`dma330_mem_transfer_async`，自己不实现搬运。以正常kernel页分配器取得3项order0 DMA-zone页，校验实际物理地址属于原p32域，写源模式和目的哨兵、1项12B描述符，执行原cache维护后提交单个256B请求。callback仅记status/cookie/count，不睡眠或回收。

必须有原回调、status0、cookie对应、数据与整页哨兵正确，submit=0不算完成。没有callback时保留request、pages、module和VM，不能正常退出或卸载。完成后也保留页归模块所有直至该VM退出；原IRQ返回后由主会话专属QMP独立导出三页核对，不能把client日志替代数据证据。

这项客户端的host mock/ASan/UBSan仅核控制与所有权规则，mock copy不是硬件验收。

首次原请求`trial-_sxfn12n`出现一次真实callback，cookie对应、submit0、client数据正确，但status=-5，判失败。重验`trial-pl_nvwur`用native QMP `pmemsave`独立导出3个完整页，源/目的/哨兵与descriptor全匹配，仍是同一错误；原失败不得因数据正确而提升为正常完成。

启用实际PL330 fault trace后，记录`flags:0x20`及abort IRQ。stock `pl330_dmasev`对non-secure channel且INS对应bit=0明确报EVENT_ERR；原微码DMAGO为a2，qtest首版仅a0未覆盖这个差异。旧候选及proof已保留。

实验设备将8个event资源显式声明为non-secure（INS=ff），没有修改status寄存器或直接调用IRQ。定向硬件测试改用同样a2，仍须全部搬运、guard、GIC及总线fault测试通过，再执行原请求/回调/独立页面复验。该配置是这台虚拟控制器的明示策略，不声称已还原实机所有安全寄存器的reset值。

`verify_original_dma.py`是main独立整体验收：除client条件外，还要求3个完整QMP页、源/目的整页pattern和guards、12B描述与p32地址、IRQ112有计数而abort144为0、无PL330 fault trace、恢复和退出均成立。它已实际对上述abort失败作拒绝，不能只由client一句PASS提升结论。
