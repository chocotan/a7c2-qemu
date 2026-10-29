# 正常host初始化的clock/reset及启动顺序前提

010代理提供4个新helper的局部反汇编及官方OF属性提取，没有完成独立verifier或报告。主会话补写并实际执行`verifiers/verify_host_dependencies.py`，36条指令锚点、原Kernel／DTB身份及controller0 provider/specifier检查全部通过。以下为静态结论，未验收真实provider或原host初始化。

probe249770在硬件初始化前依次取得六个reset和七个clock。任一lookup失败返回-19，包括lookup层本来的-517；不能靠“缺失时延迟一下”或省略provider获得正常启动。

* reset0..3：`__devm_reset_control_get(dev,name,0,0,0)`。
* reset4..5：shared参数为1，optional仍为0。shared不等于optional。
* clock：七次`devm_clk_get`；底层`clk_get`对OF的-517保持返回，其它OF错误才转`clk_get_sys`。probe又将lookup错误归为-19。

官方controller0的clock provider phandle2兼容`cxd,900xx-clock`，`#clock-cells=1`，索引按name顺序为3e/3f/40/41/42/1d/1e；reset provider phandle3兼容`cxd900xx,reset`，`#reset-cells=1`，索引20/21/22/23/76/77。消费者lookup不直接检查Sony compatible字符串，但另一个实际provider能否满足完整初始化语义未证，不能用成功桩代替。

所有name被查找，不意味着所有后续enable/assert/deassert无条件相同；handover与共享reset状态影响后续操作。更早的63pins局部PHY报告仍适用，完整clock/reset/PHY行为仍未恢复。

## 诊断VM启动顺序

首次DW兼容host实验的原console明确记录：`__boottime___udif_init_udif_pcie`与`__boottime___udif_init_pcidma`被命令行blacklist跳过。该VM完成的部分Kernel枚举不证明这些原driver、IRQ或host callback已初始化。

第二次`trial-e1omcmml`完整TEST枚举通过，同次QMP直接读read/write engine均0，原`/proc/interrupts`没有IRQ198或PCIeDMAC；启动blacklist仍在。主会话`verify_kernel_enum.py`同时核定正向枚举证据与这些否定证据。没有因PCI设备已存在而提前提交DMA。

后续恢复必须同时闭合正常UDIF初始化／生命周期与早期固定I/O映射。当前运行后装载的普通mapper证明了指定页可正确映射，不证明那些页在原boottime initcall之前已经存在。不得直接取消blacklist后在缺少模型／映射时让原driver访问未定义硬件，也不得硬调用已释放的`.init`函数补启动。

主会话已进一步找到原`setup_arch -> map_io -> iomap`节点的正常早期路线并实际核30pins。派生五窄窗口＋只读PAR的原guest实验及独立原字节核验已通过，见[BOOT-IOMAP.md](BOOT-IOMAP.md)与`early-iomap-validation.json`；保留GIC别名和重叠保护。恢复仅PCI DMA initcall的独立正常boot实验b3091c84c已安装五条IRQ，两个engine仍0；原PCIe诊断父目录缺失造成五个WARN，整体验收为partial，详见`native-init-partial-validation.json`。PCIe host黑名单保留，不靠占位时钟状态恢复其probe。
