# 自有DW兼容上下文的显式TEST host

本目录为独立实验，不启用旧`pci-core-adapter/`的opaque原型。当前已通过主机控制／普通模块ABI和**原kernel的显式TEST PCI枚举**，不代表Sony host／PHY或原PCI DMA API通过。

首次原kernel实验实际得到domain0/bus1的TEST设备和BAR10000000h，原控制写入序列也已落盘；整体实验因观察器把CPUtrace的绝对PA误作MR offset而失败，在sysfs／QMP阶段前停止，VM正常退出。原失败result保留不改，另有`main-observer-failure-review.json`核定原因。观察器按命名region严格归一化地址并通过7个测试，第二次`trial-e1omcmml`完成全部后续检查，主会话另执行`../verifiers/verify_kernel_enum.py`独立核保存字节通过。

实测：实际BDF `0000:01:00.0`、身份`1b36:0005`／class00ff00；原sysfs BAR资源10000000h..10ffffffh（16MiB，flags40200h）与独立QMP一致；322次配置读取／72次写入；原kernel quirk真实解锁／写PCIe flags及Slot Capability／恢复序列共46条Root MMIO写；Root Port类型仍4。CPU恢复输出与owned VM退出均已核。归档`../kernel-enum-validation.json`。

同次被动采样的**read/write engine均为0，IRQ198／PCIeDMAC未列出**；原PCIe／PCI DMA initcall仍被诊断启动配置blacklist。这是明确的后续阻塞证据，尚未提交connect或DMA。

原kernel的通配Root Port quirk会把bus.sysdata当ctrl+20h，读取ctrl+0、+8、+158h、+160h。自有结构提供实际host bridge device、DBI mapping、非NULL默认ops表及wrapper mapping；ops中的读写回调为NULL，原kernel自行走已核的默认MMIO实现。没有调用未export helper。

* ECAM物理4010000000h，16MiB，bus0..15。
* DBI物理f7000000h，4KiB，连接真实QEMU Root Port配置和有限RO控制。
* Wrapper物理f11c0000h，256KiB，只实现已验的20380h控制字。

普通`pci_scan_root_bus`、资源size/assign、设备publish及`pci_get_domain_bus_and_slot`提供真实对象。domain须实际为0；不强写domain或全局计数。配置回调在常驻`.text`；ctrl、ops、资源、名称、三个mapping、rootbus及设备reference保留至VM退出，无卸载入口。

`build.sh`交叉编译并执行14个ASan／UBSan情形；`check_client.py`检查普通metadata、12个真实imports、ABS64/CALL26 relocation及常驻回调。模块9192B，当前SHA256：

```text
2d62cd0c51361b0a91e47e71ffae1e45b098e459cb3eb3dc94d87e8edb36e2d3
```

`../observe_dw_host.py`与runner的`--dw-test-host`为单独原kernel实验入口：检查装载返回码／真实Live行／实际BDF和BAR，读原sysfs资源，再用独立QMP读取配置、Root Port类型及控制恢复状态，最后验证CPU恢复和正常退出。仅支持已含显式TEST DBI模型的候选，默认关闭。

没有PCI INTx/MSI路由、Sony PHY初始化或CP身份验收，不改IRQ整数表、SoC通知、ASPM策略或业务ready；不调用PCI DMA connect/submit。原PCI DMA API及CMOS第一帧保持未完成。
