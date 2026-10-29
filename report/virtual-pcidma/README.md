# PCI DMA真实传输：实施中

原DMA330单请求与原ATU一次窗口数据访问分别已在`../virtual-dma330/`、`../virtual-atu/`验收；原PCI DMA API另有256B双向运行证据。新增完整Backup长度的独立QEMU数据/ATU/GIC验收见[Backup传输](../backup-transport.md)。native原Backup、CP端点和CMOS帧仍未运行验收。

原kernel PCI DMA编程和IRQ合同见[硬件记录](../imaging-pixel-contract/PCIDMA-HARDWARE.md)。主会话已另复验122条原指令锚点，闭合channel+18的原软件producer：在ASPM policy==3的路径，原提交使请求计数0→1并唤醒worker；worker读取wrapper+20268的bits20:15，实际状态11h或12h才使channel1..7可运行并调用原run；最后请求退休时清除这些channel字段、恢复config。channel0初始条件不同，但不能借此绕过connect所需的真实PCI设备枚举。

原导出表及`pcie.aspm0..4`参数已独立复验：640ec8是ASPM策略数组，初值全1，**不是host/endpoint模式**。先前host-mode标签已在[启动条件报告](../imaging-pixel-contract/PCIDMA-READINESS.md)纠正；不强制改policy为3或把policy1当endpoint角色。

connect必须经原`pci_get_domain_bus_and_slot(domain=controller_id,bus=1,devfn=0)`找到设备；缺失会走fatal。PCI枚举、config访问和wrapper link状态行为是下一门槛，不能直接写channel flag或用常数ready补齐。

## 有限LLI数据消费者

`hardware/lli.c`按原ICDT已核的24B LE数据记录消费`control/length/src/dst`，不转换或截断地址。AP本地和PCI地址空间为独立callback domain。data1/final9与终止link6的CB行为得到公开Linux v6.12 eDMA代码的兼容性佐证；这份新代码未执行原kernel，也未接QEMU MMIO／IRQ。

已实际通过ASan/UBSan测试：两向真实owned-memory数据与guards、cycle bit暂停、LLP toggle、descriptor/source/target访问失败、64位高地址不截断、overflow／零长度、未支持remote IRQ拒绝、明确步数／字节预算，以及后续写失败时保留先前实际写入、不产生正常完成。CB mismatch是暂停，不能自行当固件完成。

```bash
bash hardware/verify.sh
```

这是有限诊断消费者。步数与字节预算是调用者显式边界，不是宣称silicon限制；MemoryTx失败可能留下部分写入，不能假装事务回滚。LIE仅在实际数据消费后、当前消费停止时报告为待处理local interrupt请求。

## 寄存器与中断待处理位：host测试通过

`hardware/registers.c`接入相同真实数据消费者，按原寄存器合同实现write/read两组8通道、直接length/SAR/DAR和LLE/CCS/LLP编程、global mask、只读pending status、W1C确认及done/abort位分离。CPU写channel-control不能改硬件状态bits6:5，不能通过CPU写status制造完成。IRQ level由两bank的真实pending与mask计算。

已实际执行ASan/UBSan：16个直接通道均搬动实际独立owned-memory数据并核guards；原300h与9/6风格LLI完成数据消费；mask、unmask、W1C及两bank隔离通过；64位不可达目标产生abort位而无done位，低地址peer未被误写。先前LLI的故障、部分写入和预算测试仍通过。

reset masked、要求原提交序列写engine enable与per-channel first-word=1，是此有限模型的明确策略，未宣称已复刻所有Sony冷复位值。未支持的doorbell/mode/寄存器访问拒绝；没有空ACK。

## Backup 大块传输接入前检查

`hardware/test_backup_transfer.c` 已按原 Backup 的 `0x15a8f8`（1,419,512）字节长度
实际调用同一寄存器/复制实现，并经 ASan/UBSan 通过。使用独立 AP/PCI 数组，两域均有
数值地址 `0x404000000`；数据只从 PCI 侧搬到 AP 的 `0x4040ed000`，完整源、AP root及
目标前后guard逐字节不变。显式2MiB预算下全部内容匹配；当前默认1MiB预算按设计拒绝，
没有搬运或done。错误高地址不截断，末尾源读取失败保留已发生的部分搬运，只产生abort；
mask/unmask/W1C均核对。这是主机模型数据证据，尚非kernel/CP运行或Backup同步成功。

**默认预算保持1MiB：** `sony_pcidma.c` 默认 `max-bytes=0x100000`。
新增默认关闭的 `QEMU_SONY_BACKUP_TEST` 在real TEST peer分支绑定2MiB的固定高PCI primary窗口、
同后端ATU，并只在该profile设2MiB预算；完整长度channel4 QEMU测试已通过。
这不是原kernel Backup路径；普通PCI连接、初始内容、严格服务和实际保存仍需接入。
测试复用 `bash hardware/verify.sh`，既有LLI与16通道寄存器回归也通过。

## QEMU实际数据／GIC硬件测试已通过

`hardware/sony_pcidma.c`已接入真实QEMU MemoryRegion、AP／PCI两个AddressSpace及GIC IRQ198（SPI input166）。MemoryTx错误产生abort，不走正常完成。DMA写入本引擎MMIO时拒绝递归重入，并将外层请求作为真实事务失败处理。

独立候选SHA `87dda374b5a02bc94bbe4c624dcb3f900fc03443e62d25b2832147c37083117d` 已实际通过16个直接通道和2个9/6描述符风格请求：实际source／destination字节、前后guards、source不变、masked时无GIC pending、unmask后真实GIC pending、W1C后IRQ撤销均检查。descriptor fetch、source和高64位PCI target三类事务失败均只有abort位，没有done位，实际peer整页未被误写／截断别名。

主会话另以`verifiers/verify_hardware.py`独立重放原qtest日志：从实际源写入提取payload，核doorbell后的目的读回与guards，拒绝在doorbell与读回之间用主机write伪造结果；核实际GIC 0→pending→0和status/W1C，以及源不变和三个失败peer页。见`hardware-validation.json`。两个qtest VM均正常QMP退出；没有运行原kernel、相机app或SD。

```bash
python3 -B build_candidate.py
python3 -B test_hardware.py "$candidate"
python3 -B verifiers/verify_hardware.py "$candidate" "$qtest_run"
```

模型默认关闭，测试显式开启`QEMU_SONY_ATU_TEST=1`与`QEMU_SONY_PCIDMA_TEST=1`以建立同一个owned TESTPCI peer。它不是完整PCI枚举／链路，也不是CP端点；**原PCI DMA API／callback、ICDT、LIRO和CMOS尚未验收**。当前推进原host probe、OF节点消费及原连接通知前提。

该87dda候选的兼容回归另通过：旧PL330 16通道、3类故障、预取剩余／跨tag退休及原完整微码fixture重放，未改变原通过范围或默认入口。

## 正常PCIe对象与原probe调查

[HOST-PROBE.md](HOST-PROBE.md)记录主会话补验的42条原指令及6个export：原host初始化先发通知，随后才扫描和发布PCI设备；link等待失败也可能继续通知。因此不能把通知当枚举成功。

另有默认关闭的`QEMU_SONY_PCIE_PEER_TEST`：实际QEMU GPEX/rootport和PCIe TEST function，其16MiB RAM由真实BAR映射，eDMA链接实际PCIbus地址空间。`test_pcie_peer.py`已实际通过ECAM／capability／BAR size，以及command和bridge window控制双向DMA与GIC的正负测试。此profile与裸ATU peer互斥，TEST身份不冒充Sony/CP。

该原型的首次编译缺少QEMU11完整`pci_device.h`，失败记录保留。随后构造阶段的16MiB RAM检查拒绝空链接；新增诊断确认`set=0`，并追到QOM `object_property_set_link`使用canonical path，未parent的RAM owner使路径为空。修复顺序为先将PCIe function挂入Machine，再创建／链接RAM，另读回链接作断言。没有放松RAM尺寸检查或构造成功条件，原失败binary／proof均保留。

修后候选SHA `57bbbd1b624126cbebe596d31bff85c40e98539defa86be183bb2964cc7276c6` 已实际通过。主会话另执行`verifiers/verify_pcie_peer.py`独立核原trace：function的测试身份1b36:0005、PCIe capability和16MiB BAR size；BAR未enable、command关闭或桥窗口关闭均产生真实abort并保持peer原页；配置有效时实际双向DMA、CPU BAR访问、guards、GIC／W1C正确。见`pcie-peer-validation.json`。这闭合测试硬件配置与数据路由，不表示原kernel已经枚举或Sony PHY／CP恢复。

原PHY名称表及状态子集已有[63条原pin核验](PHY-PREREQUISITES.md)，完整reset／clock／timing实现仍未完成。

## 原kernel I/O映射准备

`fixed-map/`是单独的普通自有模块，仅通过原export映射F7380000的两个4KiB页到原固定IOVA；映射前逐页拒绝已有translation，之后读取PAR验证两页物理目标。错误后如出现部分映射，保持模块resident且不报通过。它不设置PCI连接、软件可运行字段或发送DMA。

8个主机控制case／ASan／UBSan和正常模块ABI交叉检查已实际通过，ELF3672B，SHA `116d7b1ed73669082ff588d3a3c4e41324a5e74403614ea3119e8a9e537b0a2a`。guest `trial-gfgm554r`已实际通过：普通insmod，两个页的原export／PAR实际物理地址检查，root及正常退出；主会话复核原始console和source identity。见`fixed-map-validation.json`。这只计映射，不表示PCI连接或数据通过：

```bash
bash fixed-map/build.sh
python3 -B ../virtual-dma330/dma330-probe/run_probe.py \
  --pcidma-map-only --pl330-candidate "$candidate"
```

## 普通PCI core ABI与适配器主机原型

主会话已独立执行21个原export／75条ABI pin复验：normal`pci_scan_root_bus@229148`、resource APIs及parent=NULL自动domain路径存在。未export的内部229060不能直接调用；domain来自正常分配且必须检查实时结果，初始全局值不代替live证据。

已完成[测试host适配器主机原型](pci-core-adapter/README.md)，10个控制情形／ASan／UBSan及模块ABI通过。但进一步原字节核验发现[确定阻塞](ROOTPORT-QUIRK.md)：通配early quirk249578在Root Port上强制把sysdata当DW context并访问MMIO。opaque原型不兼容，**kernel入口已封闭只打印block，不会扫描／发布**；52条独立pin及blocked-init检查已通过，未在guest加载。不能把主机合同测试当原host或PCI DMA API完成。

为支持该真实调用而新增的有限DBI硬件窗口已在独立候选通过控制序列／实际只读配置变化／ECAM读回／restore-relock测试，并独立核trace；没有虚构PHY-ready。局部兼容context已在下面的独立新host中核定并运行；旧opaque原型的运行阻塞不解除。

局部helper ABI已由主会话扩展至62pins／7个有界函数核验，独立[`dw-test-host/`](dw-test-host/README.md)提供自有常驻兼容context和实际DBI映射，14个主机控制情形／模块ABI／7个观测测试通过。第二次原kernel实验已实际通过真实BDF0000:01:00.0／16MiB BAR／sysfs／独立QMP／原guest控制序列／CPU恢复及owned VM退出，并执行`verifiers/verify_kernel_enum.py`独立重验，见`kernel-enum-validation.json`。首次观察器地址错误的failed结果仍保留，未回填成功。旧opaque原型继续封闭。

同次原guest实测read/write engine均0、IRQ198／PCIeDMAC缺失，原PCIe／PCI DMA initcall被诊断启动配置blacklist。新增[原API启动门槛](ORIGINAL-API-ADMISSION.md)：主会话实际28pins及3exports核验确认connect／submit不替代正常host callback的engine／中断初始化，隐藏通知入口不能硬调用；真实TEST枚举不等Sony host／PHY或原DMA API完成。

后续早期窄I/O映射已原boot／AT/PAR实证通过。仅恢复PCIDMA boottime入口的b309实验进一步安装了五条真实IRQ，engine仍0；原PCIe UDIF未注册导致五个诊断proc WARN，独立核验记为`native-init-partial-validation.json`，不是clean init通过。当时仍需补正常PCIe UDIF的SCU时钟及目录前提，不用legacy all-ones MMIO作为ready；UDIF诊断probe与DW SoC OF host probe分别验收。详见[NATIVE-DMA-IDLE-INIT.md](NATIVE-DMA-IDLE-INIT.md)。

上述依赖的后继实验b79／trial-0hsp37ju现已清洁通过：有状态SCU HCLK/APB-reset门槛下，原两个UDIF ctor、五组proc inode／IRQ、五组实际SCU序列共20MMIO写／最终backend状态、CPU恢复／owned VM退出均由main独立核原记录，WARN=0，见`native-udif-init-validation.json`。首轮partial原样保留。**两个DMA engine仍0，正常DW SoC OF host／PHY／link、原connect／async数据与ICDT／CMOS仍是后续范围。**

Task78后继原CCF组件trial-db4bp47v亦已实际PASS：原CXDprovider及七个normal clock API／rate／硬件0→1→0／SET-CLEAR事务／QMP最终0／CPU退出由main独立核验，`native-ccf-validation.json`；只覆盖controller0七clocks，NULL-parent rate0不等物理频率0。Task79继续正常SoC OFhost／PHY／SRAM真实数据输入，不以此计为host-link、DMA传输或CMOS第一帧。

Task79首个里程碑已实际PASS（trial-8o7queo2，`native-phy-upload-validation.json`）：显式TEST分步清理模型下，原controller0 probe真实走通clock/reset→SRAM初始化观测→4096次原表上传→apply，快照与官方firm-id1表SHA一致；随后因lane未校准按原逻辑超时失败（probe -1、unbound、engine0/0、无WARN）。**lane校准／link训练／DBI配置与原host绑定仍未闭合**，下一步需要闭合这些producer才能让原host正常枚举。

原PHY／reset／clock合同与普通PCI core适配器ABI可行性分别在调查。后者只是评估普通导出API可否支持显式虚拟测试硬件，尚未决定或宣称其替代原SoC probe；没有手写PCI对象或改软件ready字段。

## 参考边界

公开参考用于比较寄存器布局和bit定义，不能替代原4.9.337 Image或原驱动ABI：

- https://raw.githubusercontent.com/torvalds/linux/v6.12/drivers/dma/dw-edma/dw-edma-v0-regs.h
- https://raw.githubusercontent.com/torvalds/linux/v6.12/drivers/dma/dw-edma/dw-edma-v0-core.c

QEMU11.1.2现有`hw/pci-host/designware.c`没有DMA实现，采用viewport ATU，部分link寄存器恒报up／特征值。它可以作为PCI bus plumbing的参考，不能原样当本任务的真实link-state恢复证据。原Sony枚举/config路径正在独立调查，主会话负责硬件实现、数据和集成核对。

Task77核心已实际PASS：原SoC host绑定枚举（native-soc0-host-validation.json）后，原`pcidma_connect`/`pcidma_transfer_async`完成256B双向传输，真实IRQ/线程/callback/退休全链，数据guest+QEMU双端核验，见`native-pcidma-transfer-validation.json`。提交路径61pins（verify_pcidma_submit.py）与原Image一致。LLI/并发/大帧/相机路径未验；ICDT/LIRO/CMOS帧消费仍是后续。
