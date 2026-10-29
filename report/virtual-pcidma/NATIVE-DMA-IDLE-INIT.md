# 原PCI DMA空闲初始化边界

276代理交付两个函数的partial调查及10pin脚本，主会话实际重跑通过；五个resource record的engine／wrapper指针均非零，因此当前没有正常controller0-only init输入的证据，不能清零另外四项来缩小启动范围。

主会话继续展开原符号及未闭合的小函数，保存`verifiers/verify_native_idle_init.py`并实际通过21pins、4个真实export、五项resource值及默认ASPM数组检查。它是静态边界证据，不是正常原boot init或IRQ验收。

## 语义纠正与新增证据

* 2a2e20的被调165140真实export为`proc_create_data`（record580490），**不是workqueue分配**；返回值保存controller+1260h，函数本体没有直接MMIO。
* 2a1fb0的原符号是`pcidma_latency_mon_init`，本体初始化普通kernel数据并打印，无直接MMIO。
* 2a4048的原符号`stallmon_init`，通过正常`kthread_create_on_node`／`wake_up_process`建立监视线程2a3ec8。
* 该监视线程逐controller先查engine指针、driver flags.bit0和connected+0ch；connected为0时跳过统计路径。原init5cbdb0明确初始化connected为0。不能将这个空闲分支泛化为connected后的无硬件访问。
* ASPM初始化2a3a50只在原策略为3时建立／唤醒aspmd；原Image策略数组全1，当前实验不改策略。已有worker在pending+50h为0时等待；非零后的wrapper／config访问仍受原门槛约束。
* 5cbf04为`pcidma_cdev_init`，调用真实export `udif_cdev_register@317280`；错误仍会brk，不伪造成功。

原初始化经正常boottime machinery注册，五个controller的IRQ申请、数据结构、诊断proc/cdev和worker初始化不能用自造metadata替代。`pcie_host_register_cb`仅重放非零cache的先前状态；没有真实host初始化事件不能开启原engine。

`request_threaded_irq`本体另行读过：其chip资源回调与GIC启动仍属正常IRQ core路径，不将“函数名／register返回”当作实际IRQ安装证明。只有早期页表验证通过、初始化所需范围明确后，才恢复正常boot入口，并以guest IRQ列表、原回调及hardware状态验收。此前早期映射实验保持PCIe／PCI DMA blacklist，无DMA提交；后续单独初始化实验如下。

## 启动准入的补充核验

a51独立评审展开原`__setup_irq`、hard handler和`irq_startup`，没有发现注册阶段的`DEBUG_SHIRQ`合成hard-handler调用；指出真实hard IRQ一旦发生就会无条件读取engine+4ch/a0h，另外四个未建模engine不能接收IRQ或冒充可用。该限制保留。

评审没有闭合新IRQ thread首次wake的run gate。主会话继续读取原`irq_thread`／`setup_irq_thread`以及实际`set_bit`／`test_and_clear_bit`实现，新增并实际运行`verify_irq_thread_gate.py`：21pins及2个真实export通过。创建设置action+40h的bit2；执行设备callback前必须原子消费bit0，未置位则schedule并继续等候。一次线程wake本身不等于执行设备thread callback，不伪造bit0。

原早期I/O映射现已单独实证通过。`--native-pcidma-init-only`的b3091c84c／trial-u4nfaxxj通过正常boot machinery执行原boottime注册及udm_pcidma worker；实际安装IRQ198/200/202/204/206，QMP两个engine为0，CPU恢复／owned VM退出通过。不connect、不submit，不宣称其它controller硬件或PHY完成。

## 本轮仅部分通过：五个proc WARN

自动观察器原先只查initcall返回／IRQ／engine而记录ok=true。主会话读完整console发现五条`fs/proc/generic.c:160 __xlate_proc_name` WARN，对应`driver/pcie/0..4/dma`路径，调用栈来自原`pcidma_proc_create -> pcidma_init -> __udif_driver_init`。原自动result保留不改；另存私有`main-native-init-warning-review.json`及公开`native-init-partial-validation.json`，`verify_native_init_partial.py`已实际独立核验。**原IRQ注册是事实，完整无警告初始化未通过。**

原PCIe UDIF入口仍在黑名单，诊断父目录尚未创建。主会话已修观察器：任何kernel WARN／BUG／panic拒绝clean结果，四项测试通过。不会重写原kernel返回值或吞警告。

这里的`__boottime___udif_init_udif_pcie`注册exported数据对象`udif_pcie`（driver名pciephy），其init/probe是下面的诊断目录／clkreq逻辑；它与DW SoC host的OF probe249770是不同层。恢复前者不等恢复后者，也不提供真实host连接通知。

`verify_pcie_proc_dependency.py`实际通过21pins及descriptor/五channel数据检查：正常`pcie_init31d2d0`创建`driver/pcie`，`pcie_probe31d300`创建controller子目录。probe前调用`pcie_clkreq_init31d1d0`，从SCU PA f1388310读取bits3/11/7/15/19；置位时会启用clock／修改wrapper+20380h bit4。不能靠手工造proc目录、直接调用隐藏probe，或把legacy all-ones bus shim当合法时钟状态绕过这条依赖。需先补正常时钟寄存器合同和真实有限模型，才能恢复原PCIe UDIF生命周期。

## 后续原生命周期清洁验收通过

SCU合同已由原Image／DTB／本地4.9.337 GPL交叉绑定，310h实际是APB复位状态而不是DEVCLK clock-enable。有限有状态模型的真实QEMU事务及独立日志重放已通过，见[SCU-REGISTER-CONTRACT.md](SCU-REGISTER-CONTRACT.md)。

b79e59410／trial-0hsp37ju实际运行原两个boottime UDIF入口，主会话另执行`verify_native_clean_init.py`独立核原记录通过：**kernel WARN为0，五组真实proc inode／五条IRQ、五组原SCU操作（20次MMIO写）及最终backend状态一致**；HCLK最终0、APB reset最终0、五wrapper均10h，两个DMA engine仍0。CPU恢复／owned VM退出正常，结果在`native-udif-init-validation.json`。

原b309的五WARN／auto ok=true及partial review仍保留，不回填。本次只证明PCIe UDIF与PCI DMA注册／空闲初始化，未调用connect／submit，未恢复DW SoC OF host／link／PHY，没有数据传输或图像消费验收。
