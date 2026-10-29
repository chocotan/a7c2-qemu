# ATU固定地址与数据窗口：实施中

前置[原DMA成果](../virtual-dma330/README.md)已按有限范围验收。此项继续解决LIRO的`pciatu_map/unmap`与实际PCI aperture访问；目前尚未恢复原ATU数据通路或LIRO。

## 固定I/O映射基线已通过

原ATU模块使用硬编码I/O虚拟地址，UDIF nr_devs=0，不能套用DMA的资源virtual字段适配。主会话在原kernel实际绝对导出表确认`ioremap_page_range`，并从原`__ioremap_caller`调用点核四个参数：virtual start/end、physical、pgprot。设备页保护值来自同一kernel的UDIF路径，未使用4.9.186参考头文件或非export地址调用。

`fixed-map/`首先仅映射已证虚拟设备F1056000的单个4KB页到原固定VA `fffffffff1056000`：原生AT指令先确认无现存translation；普通导出API映射后由kernel读取真实PID30。已有mapping拒绝，mapper错误传播，PID不符时保持模块/映射resident而不报通过。没有页表字节patch、MMU旁路、AP/CP状态或DMA请求。

host ASan/UBSan控制测试、A64模块描述/导入/重定位检查通过；原guest `trial-5hliwo1j`普通insmod、真实`FIXED_IO_PASS`、原module身份/Uid/Gid、正常退出均已观察到。该基线仅证这种正常固定IO映射方式可行，不表示ATU寄存器或窗口已实现。

从本成果环境中构建（先确认没有项目VM读取源码/模块）：

```bash
bash fixed-map/build.sh
python3 -B ../virtual-dma330/dma330-probe/run_probe.py \
  --fixed-io-baseline --pl330-candidate "$candidate"
```

`candidate`为原DMA成果构建输出的显式本地目录，必须有匹配的build-proof；不自动替换稳定二进制。

## 虚拟8窗口硬件：实际数据测试已通过

`hardware/atu_core.c`实现8槽寄存器、64位PCI目标及C0000000..DFFFFFFF aperture。`sony_atu.c`将其接到QEMU的正常MemoryRegion事务：映射命中后实际访问显式PCI AddressSpace，未映射、越界、重叠和目标事务错误返回总线错误。没有回落到同地址下层RAM的成功路径。

这次测试端点是独立16MiB虚拟RAM，PCI地址04000000、只供核对的宿主物理观察alias600000000。**它是测试backing，未绑定CP或CMOS。** reset时槽禁用、重叠拒绝是本虚拟板明确策略，尚未证明为Sony硬件reset值或优先级。

主会话已核8个槽分别经aperture读peer数据、经aperture写入后从peer读回的实际字节，以及前后guards、关闭窗口后peer不再被写入、64位高目标不被截断到低位。见`hardware-validation.json`。候选binary SHA `3fb9f757ae0890a8306379357c8a64f36cb6b8c8ad7b771f13a8f334d7963b86`。这不表示原`pciatu_map/unmap`数据验收已通过。

新候选从固定QEMU归档、原native/USB补丁和已验收DMA delta独立构建，默认关闭`QEMU_SONY_ATU_TEST`。不安装到稳定入口：

```bash
python3 -B build_candidate.py
python3 -B test_hardware.py "$atu_candidate"
```

首次构建因QEMU11头文件移至`hw/core/`失败，修后成功；首次启用模型时，RAM migration owner为Machine触发QOM断言，已按实际QEMU API改为ATU Device。两次失败均保留，后续测试独立记录。

## 原厂驱动与一次原API数据窗口已通过

旧原件合同在研究区`native-frame-encoder/PCIEATU-CONTRACT.md`，已证8槽、默认pcie_ctrl3、MMIO F7300000及固定VA，allocator区间C0000000..DFFFFFFF；这些是源代码行为，不能把map返回槽号当作PCI数据已消费。

`fixed-map/build.sh`还生成`sony_atu_map.ko`：它经原export正常映射单个F7300000页。此profile的通过标记只表示translation存在，不冒用DMA的PID30或宣称ATU数据通过。两profile的host控制测试和正常模块ABI检查已通过。

```bash
python3 -B ../virtual-dma330/dma330-probe/run_probe.py \
  --atu-provider --pl330-candidate "$atu_candidate"
```

`trial-fxzqq_18`已实际通过上述provider模式：原件SHA读回、root Uid/Gid、普通insmod RC0、pcieatu Live、实际`pciatu_map/unmap [pcieatu]`符号及正常退出。F7300000固定页profile已在同一guest中生效，未改原module字节。这仍只计装载门槛通过。

已通过[自有普通客户端](original-client/README.md)核原`pciatu_map/unmap`的实际数据和释放失效，另核QMP peer全页及物理control；运行入口增加`--atu-client`。其38个host控制测试、10个ELF检查和8个观测测试已通过。

`trial-0f21_yef`实际map1MiB PCI04000000→slot0/C0000000，aperture读取256B与全页guards匹配，aperture写不同256B后peer读回匹配；原unmap RC0、同槽control清enable。主会话再次核实际QMP 4096B快照与全部guards，SHA `1ecc5711bb77b2d4500e9b800087eb3a59332b147d602bc58e7d30293ab875ac`，独立物理control=0，新guest CPU输出及正常退出通过。见`original-api-validation.json`。Task76按此有限范围完成；不泛化原驱动所有slot、并发或reset。

原interchip正常完成静态合同已另见[ICDT报告](../imaging-pixel-contract/ICDT-REQUEST-COMPLETION.md)，实际PCI DMA及CP启动传输源仍未闭合；不得先假定其地址域或用空ACK让LIRO表面装载。
