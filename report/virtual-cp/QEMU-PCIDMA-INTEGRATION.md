# QEMU PCI DMA 引擎集成进 menu UI QEMU（Task #80）

目标：让原 kernel 的 `pcidma_transfer_async` PCI DMA 引擎在 menu UI QEMU 可用——这是虚拟 CP
帧传输（AP↔CP）的传输使能件。env 门控，默认不影响 menu。

## Probe 机制（worker 追清，main 核源）

pcidma 驱动**无 of_match / platform_probe / DTB 依赖**。它是 UDIF 驱动：
`late_initcall(__udif_init_pcidma)` → `udif_driver_register` → `pcidma_init()`
（`drivers/misc/pciedma/module.c`）。寄存器地址**编译期静态**：
`pcie_dmacs[PCIDMA_PCIE_I].dmac = IO_ADDRESSP(PCIE_CTRL_I=0xf7000000) + DMA_OFFSET(0x380000)`
= phys **0xf7380000**（mach 静态 iotable，platform.c/platform.h/regs.h）。IRQ 硬编码
Linux **198 = GIC SPI 166**（`pcidma_irq_setup` 的 request_irq）。引擎使能经
`pcie_host_register_cb(pcidma_host_cb)`，mach glue（`drivers/udif/mach-cxd900xx/pcie.c`）在
RC start 时触发 → `pcidma_enable()` 写 DMAWR_EN 等。**不需要 DTB 节点**。

## 集成编辑（main 应用，工作树 source/build/qemu-pcidma-work/qemu-11.1.2）

- `hw/misc/meson.build`：加 `sony-pcidma/{sony_pcidma,registers,lli}.c`（只要引擎，不带
  phy/scu/ccf/test 件）。
- `hw/arm/virt.c` 在 `create_pcie(vms)` 之后、`QEMU_SONY_PCIDMA` env 门控：
  `qdev_new("sony-virtual-pcidma")` + local-memory=sysmem + pci-memory=`vms->bus->address_space_mem`
  + realize + MMIO overlap `0xf7380000` prio 2 + IRQ→`gic` SPI 166。

## 模型来源

`report/virtual-pcidma/candidate-mw33q1n1/qemu-11.1.2/hw/misc/sony-pcidma/`（Task77 PASS
candidate，原始 pcidma_transfer_async 256B 双向传输已验）。

## 待验证 / 诚实边界

- 构建进行中（后台）。**未验证**：引擎在 menu guest 被原 pcidma 驱动 probe、真实传输。
- **设计备注**：pci-memory 现为宿主 PCI 内存空间，够"引擎可 probe"首里程碑；但虚拟 CP 在
  AP 上时"CP 内存"即 AP 内存，帧传输的 pci 侧地址是 CP 物理（=AP 物理−0x400000000，op2a 段
  约定），需 CP物理→AP物理 别名映射才正确——**帧传输验证时必须复核此映射**。
- 本集成只让引擎可用，**不冒充帧已传输或成像会话已建**（那还需 icdt/liro/帧格式/通知协议）。

## 集成+probe验证结果（本轮，真实运行）

**构建**：menu QEMU + PCI DMA 引擎重建成功（qemu-system-aarch64，模型 3 个目标文件编入，设备注册，二进制可运行）。

**回归**：默认 menu（无 env）用新二进制启动正常——0 崩溃、MENU_ROOT_READY/OBSERVER_CHECK/READMEM/uxengine_init2 全正常；`QEMU_SONY_PCIDMA` 未设时引擎设备不创建（env 门控正确）。

**blacklist 修复**：发现 menu 内核命令行 blacklist 了 `__udif_init_pcidma`（qemu-kernel-probe.sh:153）；已加 `QEMU_SONY_PCIDMA` env 条件移除（仿 sony_timers 模式）。另证实 DMM 池在 `0x41e000000`（memrsv）。

**probe**：`QEMU_SONY_PCIDMA=1` 时 `initcall __udif_init_pcidma returned 0`，pcidma 驱动初始化成功，注册 5 个 PCIe DMA channel（`driver/pcie/0..4/dma`）。无崩溃。`/proc` 命名的 WARNING（__xlate_proc_name）是良性问题，非引擎失败。

**诚实边界（未闭合）**：
- 引擎**在场但未使能**：无 `pcidma_enable`/RC-start 活动。引擎使能需 `pcie_host_register_cb` 回调，由 **DW host 模型的 RC start** 触发——本轮只集成引擎、未集成 DW host。**这是下一缺口**。
- **无 PCI DMA 传输**：成像链走队列消息；ICDT 帧传输需成像会话激活。
- **未证明引擎模型真被访问**（vs cxd_bus_stub 全 1 兜底）：init 返回 0 可能来自 stub；需 MMIO trace 或真实传输作证据。
- 传输需 **CP endpoint**（PCI 对端内存），menu QEMU 尚无。

**下一步**：集成 DW host 模型（使能引擎）+ CP endpoint（传输对端）+ 真实传输验证（证明引擎模型真被访问）。

## 引擎使能路径（main 核原 kernel 源，本轮）

pcidma 引擎使能链（全部原 kernel 源核实）：
`pcie-designware-plat.c:513`（DW host 链路起来时）调 `pcie_dwc_host_notify(ch,1)` →
mach glue（`drivers/udif/mach-cxd900xx/pcie.c` 的 `pcie_dwc_host_notify`，设 `pcie_host_state[ch]`
并调注册的 `pcie_cb`）→ `pcidma_host_cb(ch,1)`（pcie_dma.c:558，state=1 即 RC start）→
`pcidma_enable(p)`（pcie_dma.c:443，写 DMAWR_EN 等）。注册点：`module.c:100`
`pcie_host_register_cb(pcidma_host_cb)`（UDIF late_initcall）。

**故引擎使能需**：① DW PCIe host 控制器模型（QEMU 内置 designware.c 或 candidate 的 SoC 模型）
在 `0xF7000000`；② DTB 节点（compatible `snps,dw-pcie`）让 DW host 驱动 probe；③ **链路与对端
（CP endpoint）起来**才会触发 link-up → 引擎使能。这是完整 PCIe host 集成（Task79 域），非仅引擎。

**结论**：probe 里程碑（引擎在场+驱动识别）已达成；**使能+传输需 DW host + CP endpoint + link-up**，
是下一大件。menu QEMU 用 virt.dtb（无 PCIe 节点），需加节点或改用含节点的 DTB。

## 更正：bwrap --clearenv 导致引擎设备未创建（worker 发现，main 核 qemu-kernel-probe.sh 证实）

menu probe 经 `qemu-kernel-probe.sh` 在 `bwrap --unshare-all --clearenv`（345 行）下启动 QEMU——**env 必须经 `--setenv` 显式传**。我之前的 `QEMU_SONY_PCIDMA` 没传给 QEMU 进程，故 **probe 验证 run-zwpfbk7s 里引擎设备根本没创建**：blacklist 移除生效是因 bash 脚本拿到 env（cmdline 由脚本构建），但 QEMU 进程没拿到，virt.c 的 `g_getenv("QEMU_SONY_PCIDMA")` 为假、设备没建。驱动 init 返回 0 是读到 **cxd_bus_stub 全 1 兜底**，不是引擎模型。**此前"probe 成功（5 通道）"降级为"不确定"**——驱动初始化了但引擎模型未被访问。

**修正**：①加 `pcidma_environment=(--setenv QEMU_SONY_PCIDMA 1)` 传入 bwrap；②同时解除 `__udif_init_udif_pcie` blacklist（worker 发现遗漏）；③派生 `virt-pcidma.dtb`（iomap_board.prepare，ccf_provider+phy_upload+dma_window，base=menu 的 virt-packed.dtb，official=cxd90057.dtb，sha `ac33748d…`）含 PCIe 节点+syscon，经 `MENU_DTB` 选用。

这是关键的诚实更正——未修正前的"probe 里程碑"不算数。
