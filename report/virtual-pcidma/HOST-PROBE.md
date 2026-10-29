# 原host probe、连接通知与枚举顺序

主会话已补齐并实际运行`verifiers/verify_host_probe.py`：原Image SHA、42条指令锚点、6个原export名称，以及driver／OF／host-ops指针通过。它证明静态顺序，不表示当前kernel已经probe或枚举到设备。

Image5c8d20..2c将driver table6285b0交给原`__platform_driver_register`。table首项为probe249770，name指向547040的`dw-pcie`；OF match表460030的compatible字段为`snps,dw-pcie`。probe在249f44保存host-ops45ff68，在249f4c进入247a30；后者247d98调用ops+20h，即24a508。

## 通知早于设备扫描

24a508中经过248610(controller,0)、248110，条件执行2469b8(controller,1)和2467b0，再调用2479b0，最后24a5a0调用31de10(id,1)。通知可被缓存，并在pcie_host_register_cb注册后回放。

回到247a30之后，才在247f38调用根总线扫描路径229060，继而原`pci_bus_size_bridges@235b10`、`pci_bus_assign_resources@235d38`，最后247f98调用原`pci_bus_add_devices@226250`。

尤其需要保留的失败语义是：2467b0最多尝试10次link predicate，失败返回-110；24a58c的调用返回值被下一条`mov x0,x19`覆盖，没有分支检查，随后仍通知。因此**连接通知不证明链路、config事务或下游设备存在**，也不能作为调用pcidma_connect的充分门槛。

Task79追加主会话实际60pins／4range核定：原probe安装ops45FED0，其+18非空回调249330读取**W+201B8.bit1**。dispatcher246768仅在回调NULL时回退DBI+72C；正常原SoC host不能只靠通用DBI link谓词。详见[SOC0-POST-UPLOAD.md](SOC0-POST-UPLOAD.md)，不等该硬件link状态已实现。

pcidma_connect本身已由原export table57fe40和name5a02e7确认，入口2a2230。其正常新连接路径调用2a39b8，必须实际找到domain=controller、bus1、devfn0的PCI device，缺失fatal。运行验收须核真实PCI对象及其实际数据路由，不依赖通知或返回的vendor/device数值。

## OF创建门槛与未解部分

30bf84调用原`of_device_is_available@308b70`，若返回零，30bf8c跳至30c010，置返回指针为NULL，跳过platform-device创建。官方DTB五组host/EP均disabled已由独立枚举verifier核定，现有证据还没有找到原正常启动的enable producer或其输入DT修订来源。

probe中的reset／clock获取和PHY等待路径仍需按实际寄存器与失败分支实现；不能用恒报ready替代。ASPM策略是另一条路径，640ec8／pcie_aspm_policy不是主从角色选择器。

## 当前实验边界

PCI DMA硬件测试已经通过，原SoC host PHY／probe尚未恢复。新增显式PCIe TEST peer原型提供真实QEMU rootport、PCIe capability和RAM BAR，供正常配置／BAR／桥窗口数据消费验证；它不是CP身份或Sony PHY模型。正常PCI core适配器的ABI可行性正在独立核对，尚未宣称采用或完成原driver恢复。

现有基线kernel日志未见PCI host枚举，原Image检索未见generic ECAM/CAM compatible字符串；这些阴性观测不等于排除所有PCI host路径。实验不改原镜像、ASPM参数或软件业务gate，不将测试端点或普通PCI core替代路径冒称原SoC probe验收。
