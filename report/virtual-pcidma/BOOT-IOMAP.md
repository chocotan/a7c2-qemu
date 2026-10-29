# 原启动路径的固定I/O映射

8c与7d两项调查均为partial，无落盘报告或独立verifier；它们没有证明晚注册／调用已释放init代码安全。主会话继续核原Image，找到正常早期映射路线，并保存可执行验证器，不依赖隐藏地址调用。

`setup_arch`的Image5b3a78正常调用`map_io@5b6f80`。后者通过真实`of_find_node_by_type`遍历`device_type="iomap"`节点，使用`of_property_read_u64`读`phys/virt/size`，读一个`memtype`值并拒绝>3，再调用正常内核页映射实现16c78。不是`arch_phys_to_noncache`建立这些映射，后者只查已有翻译。

官方DTB原本包含：

```text
/iomem@0xf0000000
device_type = "iomap"
phys        = 00000000f0000000
virt        = fffffffff0000000
size        = 000000000e000000
memtype     = 1
```

它覆盖DMA330、ATU及PCI DMA的固定I/O地址。memtype1由原kernel依据其CPU特征选择自己的page protection，没有从宿主参考头复制PTE值。

主会话实际运行`verifiers/verify_boot_iomap.py`，30条指令、原Kernel／DTB身份、selector及官方属性检查通过。`verify_native_init_entries.py`另外恢复并核定41265个压缩kallsyms，匹配已知export及setup_arch／map_io／两个boottime入口，12条注册调用锚点通过。

## 独立运行实验

`iomap_board.py`向派生的虚拟板DTB增加五个窄窗口，使用原iomap schema及官方memtype1；保留原DTB所有已有node／property及reserve map，二进制插入后逐项全树比对，重复iomap拒绝，不依赖额外安装dtc。原官方DTB和基础virt板输入均保持只读。

| 物理起点 | 固定VA低32位相同 | 尺寸 |
|---|---|---|
|f1056000h|fffffffff1056000h|2000h|
|f11c0000h|fffffffff11c0000h|40000h|
|f7000000h|fffffffff7000000h|1000h|
|f7300000h|fffffffff7300000h|1000h|
|f7380000h|fffffffff7380000h|2000h|

初版主机生成检查因本机缺少dtc而失败，未启动guest；随后采用标准FDT二进制节点插入并重新检查通过，保留全部原节点属性及重复声明拒绝判据。

首轮b092dec17／trial-v_8sxvs1在QEMU启动前被真实准备器以`Overlapping iomap virtual ranges`拒绝：官方整段identity区间与既有GIC VA f13a1000h→PA08000000h别名重叠。未启动guest、未执行翻译检查；旧failed result及旧cfa0...检查模块保留。不能取消重叠检查或用identity映射覆盖GIC。

当前改为上表五个不重叠实验窗口，保持原准备器的GIC／GPIO／SCU／timer别名和重叠保护。`early-map-check/`模块只导入`printk`，对DMA330两页及页末、wrapper、DBI、ATU、PCI DMA两页及页末共十个地址执行AT/PAR，确认进入模块前已有正确翻译。没有mapper调用、PTE写入或MMIO数据读写。四个ASan／UBSan控制情形与普通模块ABI通过：3368B，SHA256 `cbfef1041664bccadd7d6da74333bed41a1cf6da88eb6d3b31bbebd480392e32`。

runner显式`--early-iomap-only`先调用实际准备器的prepare-only路径，通过重叠检查后才启动VM；仍保留原PCIe／PCI DMA boottime blacklist，不启动相机／SD／DMA。

窄窗口复验b35ee0295／trial-v3v06rqw已实际通过。主会话另执行`verifiers/verify_early_iomap.py`独立核定：最终DTB五窗口／原GIC非identity别名／无重叠、原map_io打印出现在Kernel cmdline前、guest加载的只读检查模块摘要、实际AT/PAR opcode且imports仅printk、十项既有翻译、CPU恢复及owned VM退出。归档`early-iomap-validation.json`；driver初始化和DMA均为false。

## 正常driver入口与尚未闭合项

原boottime PCI DMA入口5cbed0通过正常`udif_driver_register`注册描述符62e7b0，原PCIe入口5d0304注册exported数据对象`udif_pcie@640f58`。PCI DMA的实际init5cbd3c按5个controller／每个8channel建立状态，装IRQ并注册host callback。晚启动对象和init代码生命周期未证明，不重建私有描述符或硬调用它们。

取消黑名单前还需核init对全部controller的实际硬件访问；当前QEMU PCI DMA模型只有controller0，不能把另外四个controller的空ACK当初始化完成。正常SoC host仍有clock/reset／PHY／配置事务依赖；早期页表建立不等这些硬件就绪，更不等CMOS或拍摄验收。

后续独立入口`--native-pcidma-init-only`只从诊断kernel命令行副本移除PCI DMA的黑名单项，保留PCIe host黑名单，通过原boot machinery执行原注册／init。b3091c84c已实际注册五条IRQ且engine0仍禁用／CPU退出；主会话发现缺失原PCIe诊断父目录导致五个WARN，另存partial核验，不把原auto ok=true作为clean init通过。后续补正常PCIeUDIF／SCU时钟依赖，见[NATIVE-DMA-IDLE-INIT.md](NATIVE-DMA-IDLE-INIT.md)。无connect／submit。
