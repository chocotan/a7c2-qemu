# 独立 TEST SRAM 分步清理规则

当前原Image没有给出W+200AC.bit2的真实硬件producer／timing。新profile是**显式虚拟板功能规则**，不能称“恢复了Sony PHY初始化”，不能以它关闭原PHY／link任务。旧`QEMU_SONY_PHY_SRAM_TEST`数据profile继续不发布bit2。

## 规则与实际作业

`hardware/phy_clear_job.c/.h`保存4096个halfword的真实存储。只有观察过powerup reset、五个CCF gate bit1..5均开启、四个reset bit0..3均解除、选择external SRAM后才进入清理；每个虚拟tick实际清64个halfword。清理前存储为明确TEST poison FFFF，部分清理保留后半poison；4096项全部实际清完才进入DONE。bit2在新适配层中只读地映射这个TEST作业状态，软件写bit2不能设置它。时序1us/tick、吞吐64word/tick均为TEST规则，未校准实际硅片。

断钟／重新复位／bypass会阻止或中止作业，断钟后需要新的powerup reset才能启动；DONE后不能再次tick抹除已上传数据。原表仍须4096次有序32位零扩展写并独立SHA核验，apply bit1本身不是上传成功。

`qemu_phy_init.c`是独立类型，复用已核CCF状态但不改旧CCF适配层。显式冷启动初值为reset bank1 `8888F`（原APB TEST初值额外assert port0 powerup/button/PE）；由原reset-status正常生成cold handover分支，不写kernel的handover字段。wrapper／DBI窗口的未知访问拒绝。只读debug alias `602000000/2000`保留实际apply时导出的8KiB数据，供错误／suspend后的观察，不是固件照片或新生成图像。

## 保留的失败边界

lane debug状态明确保持F（四lane未校准）、link保持down；已验证的原ops callback读W+201B8.bit1，不用DBI默认检查替代。计划只观察原probe上传后触发真实lane-timeout错误路径及正常suspend，**期待probe失败**，不称host启用成功，也不产生host-notify／DMA请求。

若发生未知MMIO、WARN／BUG／panic、SRAM timeout、handover skip、意外PHY-ready／host扫描，一律拒绝本项上传验收。原固件4096写、实际字节摘要、硬件作业记录、normal provider／复位绑定、失败／CPU恢复／owned VM退出均须独立核验。

## 当前验证状态

- 主会话受锁运行`verify_phy_clear_job.sh`，严格C11／ASan／UBSan通过：冷复位门槛、缺clock／bypass、部分清理／全清理、断钟与复位恢复、无重复清理。
- b928fa55a新19输入候选构建已成功：candidate-p9xwefxd binary SHA256 `8c885bc497fbe39e6038409fc407d83d64a0ad129ef43840afc863f4ccab8129`。C/header/board片段冻结；be95a959d真实qtest已启动，尚无该profile的QEMU硬件PASS。
- `test_phy_init_hardware.py`和独立`verify_phy_init_hardware.py`已备，覆盖实际partial/full clear、64tick、readonly bit2、原表输入／snapshot、clock-loss／bypass阴性、lane/link保持未就绪。
- 派生controller0输入已过主机全树保持／phandle／GIC地址cell映射检查，保留firm-id1／lanes4、六reset／七clock及原resource属性。真实最终preparer和原probe尚未运行。
- `--native-phy-upload-only`要求该exact binary的独立hardware报告才放行；观察器只接受“原上传成功＋预期lane失败”，不会把它标为host／silicon PHY完成。
- 已准备`observe_phy_upload.py`与独立`verify_native_phy_upload.py`，要求原CPU4096写／bit2观测在首写之前／末写后的apply6／8192B readonly snapshot摘要、无未知MMIO／无DBI访问／无WARN／engine0／预期probe -1和unbound／CPU恢复退出。现阶段只有Python语法和动态导入检查通过，尚未执行原probe或这些runtime判据。
- 独立计划评审47cfcf7a已返回：无P0，条件性认可受限TEST原上传实验；P1验收义务为持续有效输入、失效／过期timer隔离、真实清理／NativeCPU上传／strict MMIO证据、emptyapply不成功。只读评审未重跑tests或VM，不视为这些义务已通过。
- 主会话据此增加mid-bypass／mid-APB-reset／DeviceReset取消pendingtimer／earlyapply后清理完成仍不得上传成功等QEMU测试及独立重放；Python语法通过，尚未执行新profile。
- 47cfcf7a冻结C实现评审已完成，未发现confirmed P0/P1；认可BQL／persistent device／无迁移热拔插范围内的timer与失效处理。评审未跑VM或tests，runtime判据仍须主会话执行。原probe尚未启动。
- 评审指出validity层可在callback之前拒绝位宽／对齐，故不能只看`rejected-accesses=0`。主会话已为原上传模式加入`invalid_mem`日志并检查critical region拒绝行，另保存CPU flatview／验证明确设备覆盖SRAM、control、SCU、DBI与snapshot，拒绝RAM fallback或错误address-space。5个相关解析／阴性单元测试实际通过，非原runtime证明。
- 原Image追加核定reset-provider注册在arch init3，DW注册在device init6（原vector与normal-register call已核）；只证明注册顺序，不等runtime lookup／shared reset完成。

## 首次硬件失败与复验

be95a959d／phy-init-qtest-dyoi04qr在第一个1000ns步进后的partial-clear断言失败，实际读回仍全FFFF；原失败日志及`main-failure-review.json`保留，没有硬件PASS。主会话核QEMU原源码：共享Machine以`-S`启动，VIRTUAL clock禁用；`clock_step`推进时间数值但disabled timerlist不执行callback。qtest accel使用dummy vCPU，不执行guest指令。

修复仅在该timer-dependent fixture开始program前执行QMP cont并确认running，让VIRTUAL timer开启；不改C模型／bit2／clear数据／任何原判据，不修改既有PL330等测试的默认状态。同一p9／8c885bc binary由b5c188396／phy-init-qtest-t8pw8947复验通过，主会话独立`verify_phy_init_hardware.py`重放PASS：partial/full清理、4096原表写入与摘要、clock-loss／bypass／reset-pending／early-apply阴性、lane=F／link=0保持。归档`phy-init-hardware-validation.json`。

## 首次原probe失败与修复

be92bda75／trial-85fheds1：模型清理完成后原代码读到bit2、发出4096次表写入和apply(6)，随后在`dw_pcie_set_Mode`写W+201AC值0x40（RC模式字段bits7:4）时被模型拒绝，同步外部abort（PC ffffff80082c6b98），kernel Internal error，未到shell，VM正常退出。该轮判FAILED并保留`main-failure-review.json`——尽管全表写入已出现在trace，abort即不满足验收，不计上传PASS。

主会话从原Image补核`set_Mode` 0x246b60..0x246bc4（清~0xf0后OR mode<<4），`verify_soc0_post_upload.py`扩至65pins/5ranges并实际PASS。修复：W+201AC掩码0x404→0x4f4（含mode字段，LTSSM bit2仍不产生link）；模型新增`ready-read-before-upload`／`apply-after-upload`计数器，原probe模式的读侧证据改用QOM计数，去掉`memory_region_ops_read`全局trace（失败轮10.5GB日志99%是pl011轮询）。be8b4e360重建为candidate-atw2lews（7d840745…），硬件复验b291dc709/o1vwf4vu＋独立重放PASS。

## 原probe上传验收（当前里程碑）

b31cd560e／trial-8o7queo2已实际通过，主会话独立`verify_native_phy_upload.py`复核PASS并归档`native-phy-upload-validation.json`：原CPU在TEST清理完成后读到bit2（计数器证）、发出4096次有序表写入、apply(6)，快照8192B SHA与官方firm-id1表一致；随后lane状态保持F、link保持0，probe按原逻辑超时以error -1失败、设备unbound，五个PCIeDMAC IRQ在位，engine0/0，无WARN／invalid_mem，CPU恢复／VM正常退出。

**结论范围**：原controller0 OF probe的真实clock/reset/SRAM上传路径已在显式TEST功能模型下执行成功。bit2来自“实际清4096半字”的虚拟作业而非Sony硅片producer；lane校准与link训练未闭合，所以这不是PHY就绪、host绑定、PCI枚举或DMA传输的证据。中间两次失败（set_Mode掩码遗漏、观察器换行锚定）均归档保留。

## lane/link 显式功能策略（进行中）

为继续向host推进，新增`phy_calib.c/.h`显式TEST功能策略（**非硅片校准/SerDes训练**）：lane状态从15变0需要〔真实表已apply且SHA匹配、PHY_POWERDOWN已清、五clock/四reset/external输入持续保持〕全部成立后再计16个tick；link的W+201B8.bit1需要已校准＋LTSSM bit2已置＋本profile真实TEST peer存在，再计8个tick。任何输入丢失（suspend复位、断钟、迟后非法写）立即使lane回15、link回0。Host侧ASan/UBSan用例已实际PASS（16+8拍转换、所有丢失路径、无tick无幻影进度）。QEMU适配已接线，bf3aedab9重建为candidate-_ywye2o5（fdc8d244…），b9aefe73b硬件复验进行中：powerdown未清不启动、16拍边界、无LTSSM无link、8拍边界、suspend后回落、set_Mode字段。lane/link仍不代表硅片校准/训练已恢复。

## DBI 前沿（下一里程碑）

原Image已核清PHY-ready后的第一段DBI序列（80pins/6ranges PASS）：W+20380 bit6清→DBI+8BC|=1（4B RMW）→16位写D+0=0x104d（VID）/D+2=0x911d（DID）→DBI+8BC&=~1→bit6置；之后weak AXI hook返回-1跳过D+8D4。当前模型仍拒绝全部DBI访问，因此frontier证据轮（`--native-phy-frontier`，`observe_phy_frontier.py`／`verify_native_phy_frontier.py`）预期probe过lane gate后在第一个DBI读（原245ea0..245f20区间）按预期abort并采集完整证据，证明下一未知边界恰好是DBI。后续按soc0-dbi-path白名单组合真实DBI模型。

## frontier 证据轮已通过（当前边界确认）

b71c290f7／trial-dijfmif_实际通过，main独立`verify_native_phy_frontier.py`复核PASS并归档`native-phy-frontier-validation.json`：原probe在TEST功能模型下真实通过lane gate（console打印`PCI0: PHY ready in 908601`），随后精确在第一个未建模DBI读abort——fault VA页内偏移恰为`0x8bc`（ro_wr_en的DBI+8BC读），PC符号化`dw_pcie_read.part.0+0x50`（raw 245c90内层定时load）、LR`__dw_pcie_read_dbi+0x74`。QMP证据：lane-status=0、link-status=0（LTSSM使能在DBI阶段之后，link保持down）、4096写/快照SHA/计数器/engine0/无invalid_mem/DBI region无写事件。

**结论**：lane/link功能模型行为与原代码消费路径一致，原host路径当前唯一下一缺口确认为DBI模型。这仍不是host绑定、link、枚举或DMA证据；lane/link为显式TEST功能策略而非硅片校准/训练。中间一次observer PC判层失败已归档（trial-g_yrp2ku/main-failure-review.json），核验器元组bug修复后重放通过。

下一步：按soc0-dbi-path的290-pin白名单组合真实DBI模型（config header RO-write许可、16/8位访问、AER W1C、iATU viewport/unroll、viewport下游CFG0/CFG1），使probe继续走VID/DID→setup_rc→host_init→LTSSM→link→notify→scan枚举真实TEST peer。

## 真实 DBI 组合（进行中）

frontier 证据轮确认唯一缺口后，主会话按soc0-dbi-path 290-pin白名单把真实DBI组合进phy_init设备（13区域）：config<0x700别名真实GPEX rootport（`rp_write_config`含桥总线号更新与AER W1C），RO-write许可=DBI 8BC bit0且wrapper bit6清；viewport 900-91C真实存储+bit31读回；CFG0/CFG1按region1 type4/5分发到真实peer config，缺席BDF读全1；MSI 820/824、AUX B40、shadow BAR 100010/100014存储；未建模偏移/unroll仍拒绝。侧带中断使能W+20274/20278与Port Logic D+710/80C/890按60-pin合同mask存储。

两次模型迭代失败均归档（trial-ygvygsto缺侧带中断使能；candidate-493q8q67 realize序缺陷）。一次环境超时（b5d4f2d33，外部VM占用 admission）与模型无关，亦归档。lane/link/DBI均显式TEST策略，非硅片事实。

## 原 SoC host 绑定并真实枚举 TEST peer（里程碑3，已通过）

bea789359／trial-kmupj3xo实际通过，main独立`verify_native_soc0_host.py`复核PASS并归档`native-soc0-host-validation.json`（候选vt2qw_da／f3b91f79）。原controller0 probe完整走通：真实clock/reset→TEST清理作业→bit2观测→4096次原表上传→apply→IDDQ/CLKREQ/PERSTN控制→set_Mode RC→侧带中断使能→lane校准（TEST功能策略）→DBI ro_wr_en→16位写VID 104d/DID 911d→setup_rc（Port Logic 710/80c/890）→host_init→LTSSM使能→link up（TEST策略）→notify（回调2a2538把engine+c/+2c置1使能空闲）→scan→**pci 0000:00:00.0 [104d:911d] class 060400 root port与0000:01:00.0 [1b36:0005] class 00ff00 TEST peer均经原DBI/viewport/CFG0真实枚举**。IRQ198出现`dw-plat-pcie-msi, PCIe PME, aerdrv, PCIeDMAC`共享名列表证明host MSI handler真实注册。rejected-accesses==0（无任何未建模访问），无WARN，CPU恢复，VM正常退出。

官方DT的64K MEM窗口放不下peer的16MB BAR，BAR8/9与peer BAR0的no-space是真实合理结果，不影响枚举结论。

**边界**：lane/link是显式TEST功能策略（真实输入持续+计时），非Sony硅片校准/SerDes训练；bit2来自实际清理作业而非未知硅片producer。BAR数据通路、原connect/submit DMA传输尚未进行。中间失败轮（set_Mode掩码遗漏、侧带中断使能遗漏、QOM realize序、wmask/w1cmask重叠、observer IRQ共享名判据、测试mask取值）全部归档保留。

## 原 PCI DMA 实际传输（已通过，Task77核心）

b428555be／trial-b67wso8s实际通过，main独立`verify_native_pcidma_transfer.py`复核PASS并归档`native-pcidma-transfer-validation.json`（候选mw33q1n1／500f1e65）。在soc0 host已绑定前提下，诊断client经正常export的`pcidma_connect(0,1)`+`pcidma_transfer_async`完成256B AP→PCI写+PCI→AP读回：原驱动dma_start的引擎写序（PWR→SIZE→CTRL1=LIE→SRC→DST→doorbell，61pins核验与模型合同一致）驱动真实引擎模型，IRQ198真实触发两次（0→2），原硬中断handler 2a1df0（读INTSTAT→写屏蔽→WAKE_THREAD）与线程handler pcidma_intr（读INTSTAT+错误状态→W1C→callback(status0,cookie)→退休→unmask→启动下一请求）全链真实运行。数据双端核验：guest内核memcmp往返一致，QMP端peer RAM pattern一致。engine使能空闲[1,1]、状态清除[0,0]。

**边界**：单次256B直传、单通道、无并发；LLI模式、大帧、真实CP业务、相机路径均未验。中间失败轮（IRQ共享名判据、guest无head、侧带状态遗漏、MSI状态遗漏、引擎错误状态遗漏、cookie断言值错）全部归档保留。
