# PCIe UDIF probe之前的SCU时钟状态前沿

当前不能单凭恢复PCI DMA initcall报告clean通过：真实IRQ198/200/202/204/206已安装，但原proc父目录缺失造成五个WARN。独立partial核验在`native-init-partial-validation.json`，原auto ok=true不回填。

正常父目录由PCIe UDIF `pcie_init31d2d0`及`pcie_probe31d300`创建。probe首先调用`pcie_clkreq_init31d1d0`，按五个channel的SCU PA f1388310 bits3/11/7/15/19决定是否进一步调用HCLK／DEVCLK控制以及wrapper+20380h bit4操作。`verify_pcie_proc_dependency.py`的21pins、exported udif_pcie描述符／设备vector／ops／五channel数据已经主会话实际核验通过。

## 内存路由校正

早先根据legacy `sony-cxd-bus-stub`源码将该地址归为all-ones读，结论不准确：stub位于priority-1000，native大小的普通RAM能覆盖它。主会话另启动**无guest／无kernel、CPU暂停**的相同candidate／24GiB／timer+DMA330+PCIe TEST profile，在owned QMP读SCU word、`info mtree -f`后正常quit，返回码0。

实际system／cpu-memory FlatView显示f1058000..f13a0fff属于priority0的`mach-virt.ram`，包含f1388310；该未启动guest配置下读回00000000。证据保存在本机`/var/tmp/a7c2-scu-memmap-p3oib7jm/`，不混入Sony资产或公开原始运行包。

这只证明**当前内存路由和无guest初始值**，没有证明真实时钟关闭、silicon reset或原guest之后没有写此地址。RAM0与legacy FF都不能作为SCU clock状态证据，不能靠这些值跳过或满足正常probe。

## 已知合同与未定事项

99代理已交付可运行初步检查，恢复HCLK与DEVCLK两个selector写目标及五通道one-hot bit；主会话暂未在其继续调查期间重写同一scratch证据。selector1/0的实际时钟使能极性、STATUS与SET/CLEAR硬件联系以及silicon reset仍须额外原provider／状态消费者证据。

后续需要显式有状态的有限SCU模型，读值来自真实模型状态、写入实际更新状态，默认板策略与silicon事实分别报告。

## 后续原Image交叉绑定已闭合

主会话找到另一份本地4.9.337 GPL源码后继续展开原reset provider，确认这里的UDIF DEVCLK字段实际上接**PCIe APB reset bank1**，不是clock bank。`verify_scu_binding.py`实际27pins、官方reset资源base300h／五个rst_apb ID与UDIF表的31x寄存器完全一致：STATUS310h bit1表示reset asserted，314h断言、318h解除；真正HCLK在80h/84h/88h。详细合同与有限模型策略见[SCU-REGISTER-CONTRACT.md](SCU-REGISTER-CONTRACT.md)。

后续有限SCU模型硬件qtest与main独立重放已通过，基于它的原两UDIF生命周期trial-0hsp37ju已清洁通过：无WARN、真实proc路径／IRQ及五组实际SCU序列，engine仍0，见`scu-hardware-validation.json`与`native-udif-init-validation.json`。没有手工创建proc目录、修改私有flags、通知或提交DMA；DW SoC OF host／PHY／数据仍未验。
