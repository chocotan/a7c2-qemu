# 先恢复服务依赖：正常运行中LIRO未装载

## 最新有限验收

- 原DMA330单channel0／256B请求已通过：原API编译微码、实际数据、IRQ／callback0、guards、无迟发abort、END退休、CPU恢复及正常退出。见[DMA成果](../virtual-dma330/README.md)及[请求合同](DMA330-REQUEST-COMPLETION.md)，Task75完成。不是仅有模块装载。
- 原`pciatu_map/unmap`一次1MiB映射／slot0已通过实际256B payload、全页guards、独立QMP peer全页、原unmap及control清enable、CPU恢复／正常退出。8槽虚拟硬件另经qtest逐槽核验。见[ATU成果](../virtual-atu/README.md)，Task76完成。
- PCI DMA的QEMU硬件qtest已通过：16个直接通道、2个LLI请求的实际bytes／guards／GIC198／mask-W1C及3类事务失败abort，主会话独立重放原trace核内容。
- 原kernel经独立DW兼容TEST host真实发布0000:01:00.0，16MiB BAR与原sysfs／独立QMP一致，原quirk实际控制写入／CPU恢复／owned VM退出已main独立核验；该范围为TEST PCI枚举。实测两个engine仍0、IRQ198／PCIeDMAC缺失，原PCIe／PCI DMA boottime initcall被诊断配置blacklist。原SoC host初始化、原DMA连接／传输与ICDT实际DMM交付仍未验收。见[当前实施](../virtual-pcidma/README.md)，Task77进行中。
- 原`setup_arch/map_io`已在独立派生板正常建立五个窄I/O窗口，原boot日志、最终DTB／GIC别名／无重叠、仅printk导入的AT/PAR检查模块十项翻译、CPU恢复及owned VM退出经main独立核验通过。见[早期映射](../virtual-pcidma/BOOT-IOMAP.md)。原driver黑名单未在该验收中取消，不抵扣IRQ安装或原API传输。
- 后续仅恢复原PCI DMA boottime入口的实验已真实安装IRQ198/200/202/204/206，两个engine仍0，CPU／VM退出正常；原PCIe UDIF诊断父目录缺失引出五个WARN，整体验收仅partial，原auto ok=true保留并另作否定review。见[native-init partial记录](../virtual-pcidma/native-init-partial-validation.json)。需补正常PCIe UDIF时钟／目录依赖；不能把该层与DW SoC OF probe或真实传输合并。
- SCU真实状态模型硬件验过后，后继原两个UDIF正常生命周期实验已无WARN通过：五组proc inode／IRQ、五组原SCU序列（20MMIO写）与backend状态、CPU恢复／VM退出经main独立核验，见[清洁生命周期记录](../virtual-pcidma/native-udif-init-validation.json)。先前partial保留，engine仍0／无connect-submit；不能据此关闭原SoC host／原DMA／ICDT／图像消费任务。
- 原CXD CCFprovider与controller0七clocks组件现已实际PASS：原lookup／rate／prepare-enable／硬件0→1→0／disable、7组实际SCU SET/CLEAR、最终QMP bank读回／CPU退出经main独立核记录，见[CCF组件记录](../virtual-pcidma/native-ccf-validation.json)，Task78有限完成。NULL-parent两项rate API0不等物理0Hz；SoC OF host／PHY SRAM／link与原DMA数据仍需Task79／77继续。
- Task79首个里程碑已PASS：原controller0 probe在显式TEST清理模型下完成真实clock/reset→SRAM全表上传（4096写／快照SHA一致）→按原逻辑lane超时失败退出，见[上传验收](../virtual-pcidma/native-phy-upload-validation.json)。bit2是虚拟作业产物而非Sony硅片producer；lane/link/DBI/host绑定与原DMA仍未闭合。
- 已纠正一个静态语义错误：`pcie_aspm_policy`及640ec8是ASPM策略，不是主从角色；相关条件和原通知链以[修正报告](PCIDMA-READINESS.md)为准。没有改guest策略／gate来制造连接。

原LIRO及原图像帧消费仍未通过。以下保留的是更早的服务缺失和装载探针记录，其“尚未闭合”按当时run的证据范围理解，不覆盖上面的后续验收。

## 历史：原正常run的缺失服务

正常原生`run-47bjx6nj`的原console（1114..1118）实际记录`liro.ko`的四项Unknown symbol：

```text
dma330_mem_transfer_async
pciatu_unmap
pciatu_map
interchip_transfer_async
```

这是该run复用原内核图像服务的一项明确前置失败；不能把静态`av-cam.bin`调用链当作该轮已经执行。AP-only软件OSD、原输入及SD验收是另外的通路，保持其原范围。

## DMA provider已找到

主会话初次只查120个`usr/kmod`，漏掉根文件系统`/kmod`。原`insmod_drv1`为：

```text
insmod /kmod/devno.ko
insmod /kmod/dma330.ko phy_inst_area=0x4102E4000
```

原`kmod/dma330.ko`为607336B，SHA `9ba277f011b3ddcfbc3fa610d22b63ae3be1e0ded385b42ff2c7cf0a83e520ab`，vermagic=`4.9.337-scel+ SMP preempt mod_unload aarch64`。`.rela__ksymtab`明确导出`dma330_mem_transfer_async`，入口`.text+87c8`。这更正了“官方包缺dma330”的推断；不能只用`usr/kmod`扫描或kernel明文字符串阴性证明缺资产。

该入口先校验请求，再读请求+4并限制≤256，成功路径清请求+10的u64后调用8418；count单位及完成ABI尚未闭合，不借用interchip/pcidma结构。原初始化通过`udif_driver_register`及原回调表，不能因为导出存在就称硬件服务已就绪。

## PCI／芯片间路径仍不能盲恢复

原`pcieatu.ko`有map/unmap实现，原`icdt.ko`有interchip实现；map/unmap实际触碰ATU MMIO，interchip向pcidma提交描述符。当前safe/no-pcie配置有明确理由排除PCIe三模块，旧记录的udm_pciatu线程无模型NULL访问不能忽略。需要继续核地址域、完整传输、回调／所有权和设备初始化，绝不提供四个“返回0”桩来让liro表面装载。

## 有界运行探针

`scratch/dma330-probe/run_probe.py`只在本机隔离kernel VM中检查原DMA330装载/导出，启动前核模块SHA，使用原phy_inst_area。没有相机app、SD挂载、传输请求、UDIF批量启动或图像完成通知；专属QMP正常退出，不强杀未知owner。

结果以其独立`result.json`和原始console为准。即使装载通过，也只能计为模块/符号范围，不抵扣真实DMA、原图像消费、IRQ/lease或拍摄验收。当前不修改默认稳定入口。

## 严格重验已完成

首轮`trial-n857x_3k`实际模块加载0且`/proc/modules`为Live，但guest grep错误地用`$`排除了模块名后缀，host又把命令回显当符号内容；其自动ok=true不作符号证明。原result保留，独立`main-module-load-review.json`只采纳加载范围。解析器新增3项测试，明确拒绝命令／SHA回显。

重验`trial-nkt9yik5`改成严格实际输出行核对，main再读原始观察文件，确认：

```text
Uid: 0 0 0 0 / Gid: 0 0 0 0
DMA330_LOAD_RC=0
dma330 598016 0 - Live ...
ffffff80004be7c8 T dma330_mem_transfer_async [dma330]
```

guest加载前完整模块SHA匹配原件，独立QMP正常退出；`main-strict-symbol-review.json`明确`dma_executed=false`、`liro_loaded_or_image_consumption_verified=false`。这闭合了原DMA330的**存在／装载／导出可见**，没有闭合请求完成ABI或另外三项依赖，更没有执行DMA。符号地址仅属于这次VM，不当作固定入口。
