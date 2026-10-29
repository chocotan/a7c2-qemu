# 普通PCI core测试host适配器：仅主机原型

这是为显式QEMU GPEX／rootport／RAM BAR测试拓扑编写的主机合同原型，**不是原Sony host PHY驱动的恢复成果**。本模块未在原kernel加载。后续已发现确定的SoC ABI阻塞：early fixup通配表573fb8调用249578，遇Root Port type4便把bus->sysdata当DW port，并访问其前后字段及MMIO。原opaque context不兼容。

**运行入口已封闭：** `init_module`现在只打印`PCI_CORE_TEST_BLOCKED`，不映射ECAM、不扫描或发布PCI；原合同逻辑保留在未export的`sony_pci_core_prototype`供主机fixture使用。没有可绕过此入口的运行参数。ABI checker额外要求init的CALL26目标只有printk，且不export原型。见上级`ROOTPORT-QUIRK.md`和52pin独立核验。

原Image的21个normal exports、75条ABI指令锚点和数据布局已经主会话独立复验，脚本在`../verifiers/verify_pci_core_abi.py`。模块只导入正常PCI core、UDIF mapper及printk，不调用未export的229060或通知函数，不改ASPM／domain全局／PCI私有可运行字段，不调用pcidma_connect或提交DMA。

代码映射与现有虚拟板DTS一致的ECAM：物理4010000000，首16MiB覆盖bus0..15。callback按原pci_bus+e0读取bus number，通过实际ECAM执行1/2/4B配置读写。原ops的read／write槽18h／20h被保留，三前置槽为NULL。normal PCI扫描接受persistent BUS和MEM资源表，成功后entry ownership交给host bridge；只有失败仍归本模块的list经原free-list API释放。

自动domain分配来自正常API，不能指定或篡改。模块检查返回bus的实际domain0／bus0；不符则保持resident并报告，不重试或强改。只有正常扫描、资源分配、发布和pci_get_domain_bus_and_slot确实找到0000:01:00.0，且实际配置事务确认QEMU TEST身份1b36:0005，才报告枚举诊断通过。没有给虚构vendor/device值来制造PCI对象。

回调存放在永久`.text`，不在`.init.text`；ECAM、ops、资源对象、名字、rootbus及取得的设备reference都保留到VM退出。无exit／热移除，未证明的stop/remove/final-release路径不调用，也不额外猜测pci_bus_put。它尚不能运行PCI DMA，枚举PASS也不能冒充数据消费。

已实际通过10个ASan/UBSan主机控制情形和模块交叉ABI检查：已有root拒绝、MMIO失败、root身份／class不符、resource不完整、scan失败、domain不符、端点缺失／身份不符，以及1/2/4B回调、边界和相邻字节保持。host fixture没有执行Linux PCI core或QEMU，不能替代guest验收。

```bash
bash build.sh
python3 -B check_client.py
```

封闭入口后的ELF为8224B，SHA `d743826eaa3cffdacc1c41acbfe53ba27ed9c022bf57cd304e0dac55880e665c`；descriptor／ordinary imports／ABS64-CALL26／permanent callback slots及blocked-init检查实际通过，10个主机合同情形仍通过，另核blocked init不产生任何scan。原7952B是未运行的旧主机原型，不能拿其控制测试当kernel可用证明。

下一步必须恢复Root Port quirk真正消费的兼容上下文及寄存器行为，而不是换port type、伪造capability或改kernel跳过quirk。默认稳定入口未使用此原型。
