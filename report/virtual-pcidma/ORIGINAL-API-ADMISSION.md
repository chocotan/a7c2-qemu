# 原PCI DMA API的请求合同与启动门槛

代理0ff交付的是调查文字和未执行的inline verifier，没有落盘文件。主会话据此新增并实际运行`verifiers/verify_api_admission.py`：原Image身份、三个真实export及28个关键ABI／host callback硬件写指令锚点全部通过。静态pins不替代当前guest状态或实际DMA。

`pcidma_connect(controller, connected)`的两个输入为w0/w1；不依赖其返回值。controller须0..4，新连接需要实际`domain=controller,bus=1,devfn=0`的PCI设备，缺失fatal；随后连接全部八个通道。原`pci_ep_cp.ko`先调用正常`pci_enable_device`，成功后传controller0、connected1。不能用channel0特殊诊断路径绕门槛。

`pcidma_transfer_async(request*)`输入x0，返回0表示接受／入队，-22表示参数拒绝。可写请求至少3ch字节，后续client用8字节对齐40h存储：

| 偏移 | 字段 |
|---|---|
|00/01/02/03|u8 controller/channel/direction/未定保留字节|
|04|u32长度；零表示LLI模式|
|08|u64 source；LLI模式为AP物理list地址|
|10|u64 destination|
|18/20|callback／cookie|
|28..37|driver覆盖的双向链表links|
|38..3b|driver写入提交者metadata|

direction1为AP→PCI，原caller的0用于PCI→AP；不利用其未验证其它值。LLI地址要求8字节对齐，ICDT通过正常`arch_va_to_phys`取得AP物理地址，不能放CPU指针或BAR地址。LLI格式24字节，见原ICDT合同；8字节以外的silicon对齐要求未泛化。callback仍不等owner／count退休。

## Connect不完成原host初始化

原host callback2a2538接到非零state，按controller+1248h映射写全局write/read enable的B+0ch／2ch为1，W1C pending、设置错误控制并解除中断mask；同时更新其自身正常driver flags。connect与submit不替代这些写入。

31de10是原host状态producer，2a2538是注册callback；在已核export区间570000h..58ffffh中二者均没有export。**不硬调用这两个隐藏地址、不直接写私有flags、不把虚拟硬件reset改成已enable来制造成功。** 已有原producer24a5a0来自正常SoC host probe，相关PHY、clock/reset及配置事务仍需真实模型支持。

因此，即便独立`dw-test-host`将来完成真实PCI对象枚举，也不能据此向尚未完成原host初始化的controller提交请求并把返回0算通过。应先验证正常原host路径实际开启engine并装好IRQ，再推进数据／callback／退休。该门槛当前是静态调查结论，尚未测得本次guest的engine状态。

## IRQ范围

原DMA初始化使用`request_threaded_irq(controller+1238h, 2a1df0, 2a2670, 10080h, "PCIeDMAC", controller)`，controller0为LinuxIRQ198，与PCI INTx分别处理。静态调用不证明当前guest安装成功；后续须核`/proc/interrupts`及真实IRQ／thread／ACK行为。不得补假的PCI IRQ或改全局IRQ值表。

首次DW host实验console进一步确认原PCIe／PCI DMA boottime initcall在当前诊断配置中被显式blacklist；不只是尚未收到通知，原初始化自身也未执行。正常启动顺序、provider和早期映射的后续前提见[NATIVE-HOST-DEPENDENCIES.md](NATIVE-HOST-DEPENDENCIES.md)。
