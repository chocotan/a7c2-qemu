# PCIe UDIF实际使用的是HCLK和APB复位两组寄存器

主会话在`analysis/reference/qemu-kernel-source/linux-kernel/`找到此前未使用的4.9.337 GPL源码。`drivers/udif/mach-cxd900xx/platform.c`把PCIe UDIF的HCLK字段接到`PCIE_CLK_SET/CLR`，但名为dclk／DEVCLK的字段接到`PCIE_RST_SET/CLR`。`platform.h`将RESET bank定义为SCU+300h+bank*10h。源码是定位线索，最终判据仍为原Image／官方DTB。

主会话实际执行`verify_udif_controls.py`和`verify_clock_provider.py`复验代理已交付的软件写合同，继续核原clock构造器、reset status/assert/deassert/probe及DTB资源，`verify_scu_binding.py`的**27pins／原Image与DTB身份／五通道绑定全部通过**。

| 物理寄存器 | 原软件实际语义 |
|---|---|
|F1388080h|HCLK STATUS，CCF选中bit非零表示enabled|
|F1388084h|HCLK enable／one-hot set|
|F1388088h|HCLK disable／one-hot clear|
|F1388310h|RESET bank1 STATUS，选中bit1表示asserted|
|F1388314h|RESET bank1 assert／one-hot set|
|F1388318h|RESET bank1 deassert／one-hot clear|

HCLK的五个PCIe APB gate对应CCF ID62/67/72/77/82、register80h、bit1/7/13/19/25，原构造器把status/set/clear offsets填为80h/84h/88h。syscon DTB资源为F1388000h..F1389fffh。

Reset provider从`rst@300/reg`取相对base300h；status读base+(id>>5)*10h，assert再+4，deassert再+8。官方五个PCIe节点的`rst_apb`为ID35/43/39/47/51，正好落在310h的bit3/11/7/15/19，与原UDIF记录的314h/318h和bits完全一致。不能将这些bit解释为DEVCLK clock-enable。

原`pcie_clkreq_init`的bit-set分支因此为：APB处于reset asserted→打开对应HCLK→解除APB reset→延时→wrapper+20380h置bit4→延时→关闭HCLK。bit-clear时跳过这段；前面RAM0或FF都没有提供真实复位状态。

## 有限TEST模型的范围

当前实现目标只覆盖这两个12字节bank和五个wrapper控制word。模型状态必须由真正的one-hot操作更新；wrapper访问要求对应HCLK开启且APB reset已解除，错误顺序返回事务错误，不吞写入。该模型不提供link／PHY-ready或DMA完成值。

硅片cold-reset值仍未知。TEST板明确选择HCLK全关、五个APB reset初始asserted、wrapper控制为0，以使原UDIF路径实际完成上述操作，而非用零值跳过。该选择属于虚拟板策略，不宣称Sony silicon reset校准。原`pcie` UDIF与DW SoC OF host仍是不同层，不能把clean诊断目录／IRQ注册计为host连接或CMOS消费。

模型核心已由独立worker交付，主会话负责QEMU集成与核验。核对实际文件发现worker最初把HCLK位号写成0..4／mask1fh，测试也沿用该错误；原实现保留在scratch。权威`hardware/scu.c/.h`已修为原Image的1/7/13/19/25／mask02082082h，加入独立原位号断言并实际重跑ASan／UBSan通过。

`test_pcie_scu.c`适配真实QEMU MemoryRegion，两个12B bank及五个controlword覆盖普通RAM；wrapper事务经对应HCLK／APB reset实际状态门槛，失败返回MemTx错误。`test_scu_hardware.py`核实际one-hot状态读回／无效写不改状态／五controller隔离及system_reset。

新独立candidate构建b6119010a已成功：`candidate-9mb7ee8z`，binary SHA256 `321ddc112e9868fd70a9891c3c7f36d64bd1b95501d245ea0f5f6c30711bd0d2`。

硬件qtest b91d04887／`pcie-scu-qtest-flzciiwo`已通过，主会话另实际执行`verify_scu_hardware.py`重放原qtest数据：五controller实际受门槛控制写入／读回、22次无效写无状态变化、42次实际状态读回及QMP reset效果通过；默认关闭另验。证据在`scu-hardware-validation.json`，只覆盖有限TEST硬件，不等原UDIF或SoC host／PHY。

基于该硬件候选的原两个UDIF正常生命周期实验b79e59410／trial-0hsp37ju已通过，主会话另执行`verify_native_clean_init.py`独立核验：无kernel WARN、五组真实proc inode／IRQ、五组原guest SCU序列共20次MMIO写和最终backend状态一致，CPU恢复／VM退出正常；见`native-udif-init-validation.json`。两个engine仍0，无connect-submit，不代表DW SoC OF host／link／PHY／原DMA数据已恢复。
