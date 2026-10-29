# 普通PCI core中的SoC Root Port quirk阻塞

主会话复验代理的6个完整hook body／17个call pins后，继续展开root OF／MSI两个前沿。2436f8在真实root且parent／OF node为空的路径返回NULL；243798在bus OF node为空时返回NULL，未读取sysdata。publication pre-hook2261c0也是ret。这些局部安全条件**不等于整个PCI扫描接受任意opaque context**。

继续按原239d78 matcher枚举实际fixup记录，发现early范围573cb8..573fd0中的573fb8：vendor=ffff、device=ffff、class=ffffffff、shift=0、hook=249578。它对QEMU test vendor同样生效，不能凭“不是Sony device ID”排除。

249578读取pci_dev+52h中的PCIe flags，提取bits7:4；值4（Root Port）时进入SoC路径：

```text
device+10h -> bus
bus+d0h -> pp/sysdata
pp-20h -> controller
controller+160h -> wrapper mapping（由245d60消费）
pp-18h（controller+8）-> DBI mapping
```

然后真实RMW wrapper+20380h bit6，DBI+8bch bit0，写PCIe flags／Slot Capability，再恢复这两控制位并读取31deb0的IRQ整数表，后续可进入22d290资源使能路径。**纠正：22d290不是IRQ分配。** 一个无关opaque结构不满足这些读访问，原型不能执行。主会话已实际运行`verifiers/verify_rootport_quirk.py`：原Image SHA、52条指令、early通配表及强制cast通过；结论是**BLOCKED**，没有进行故障性kernel尝试。

`pci_get_domain_bus_and_slot`还经231288→原`bus_find_device@27e2a8`搜索已注册设备。通知不等于枚举，扫描对象也不能未经核对就当作已发布设备来调用connect；这些阶段分别验收。

原型的kernel入口已改为无条件打印block，不执行合同函数；主机fixture仍测试正常API调用约定和资源持有，ABI checker核init只调用printk。不能通过改Root Port type或假capability绕开原quirk，也不能直接调用未export函数。

后续调查针对quirk实际要求的上下文／DBI helpers／IRQ路径。QEMU新增的显式TEST DBI窗口已完成下面列出的有限硬件验收；完整Sony host／PHY依然未恢复。

## 显式TEST DBI模型边界

`hardware/test_root_dbi.c`提供与真实QEMU Root Port配置关联的DBI镜像，以及只支持本quirk控制字的wrapper窗口。候选`f2ec9a2723e49756c2a052cf68b9df1315a0bba769da265d812c606985b0cbf2`已实际通过`test_pcie_peer.py --dbi`，主会话另执行`verifiers/verify_dbi_compat.py`独立核原trace，结果在`dbi-compat-validation.json`。

模型明确采用有限虚拟板策略：wrapper+20380h初值40h，只有bit6控制序列清除且DBI+8bch bit0打开时，Slot Capability和slot-implemented flags的只读写入才生效，并由实际Root Port ECAM读回。这两个控制字不是PHY-ready；未实现的vendor CSR（含link/PHY状态）返回事务错误，不借用PCI保留字段的零值假装完成。

实际ECAM Slot Capabilities及slot-implemented flags在正确序列下改变，locked或只开8bch但未清wrapper控制的写入保持原值；原值已恢复、控制已relock。相同候选的真实BAR／command／bridge双向DMA与GIC正负数据测试也通过。57bb原无DBI候选的校验和本次候选分别归档，未覆盖其原证据。

这只验证有限DBI RO-write行为，不证明所有SoC位的硅片语义。原opaque原型的kernel运行入口继续封闭。

## 兼容上下文的独立实验

代理512交付的43pins／6个helper body经主会话复验。主会话再补齐245c40默认读函数，`verifiers/verify_quirk_context.py`实际通过**62pins／7个有界函数**：默认读1/2/4字节使用真实load及`dsb ld`，无效宽度写零输出并返回87h；默认写使用真实store及`dsb st`。ctrl+158h的ops指针必须非NULL，其+8/+10读写回调各自允许NULL以选择默认路径。ctrl+0是错误日志消费的实际device指针。

31deb0只读640ff0的五项IRQ值，原初值均-1；22d290转发给2335f8，后者按已选资源使能PCI Command I/O/MEM，没有分配IRQ或增加bus-master位。尚未提供PCI INTx/MSI路由，不改该表。

独立`dw-test-host/`在自有常驻存储中提供上述局部布局，sysdata指向ctrl+20h，非NULL默认ops表常驻，实际root host bridge device由已pin的bus+120h指针取得；Root Port配置通过真实DBI窗口，其他配置通过实际ECAM。14个ASan／UBSan主机控制情形和普通模块ABI已通过。第二次原kernel实验已完成真实BDF／16MiB BAR／sysfs／独立QMP／实际guest控制序列／CPU恢复及owned VM退出，主会话另执行`verify_kernel_enum.py`独立核验通过；首次观察器地址误判的failed结果仍保留。

当前仍未执行原PCI DMA API：实测engine均0、IRQ198／PCIeDMAC缺失，原boottime PCIe／PCI DMA initcall被诊断配置blacklist。上述成功证明局部兼容context被原kernel实际消费并完成TEST枚举，不替代原SoC host／PHY／DMA初始化。
