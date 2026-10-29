# PHY SRAM 数据消费子层

Task78的原CXD CCFprovider／七clock组件已通过，见`native-ccf-validation.json`。Task79先分开验证SRAM输入，保留未知的INIT_DONE／lane／link硬件producer；不提前启动原DW OFhost。

## 合同与范围

原firm-id1表及上传循环由`verify_phy_sram_contract.py`核定：8192B／4096个u16，每项零扩展为u32，写W+18000..1BFFC，包括尾部900个零。原表SHA256为`6133a8e7fb95e2ac83119517c00a306d485dcf3bf4afd814411317af64439f95`；扩展事务流SHA256为`963669fdc92d57141fa41095ecd7c5a1b972162d2e699a702ebfc8b6c1ef64dc`。Sony原字节不装入公开源码。

`hardware/phy_sram.c/.h`只接收4096次有序4B写入，检查高16位为零、偏移、越界及apply时序；拒绝时保留实际前缀并锁存失败。清理函数实际清零存储。apply不等完整性认证：它可在timeout后由原代码置位，只有完整无错的数据可导出供摘要核验。核心不产生INIT_DONE、lane-ready或link-ready。

新`hardware/qemu_phy_sram.c`为显式TEST数据适配层：

- 每次data访问核实际CCF gate状态80h bits1..5全部开启、reset状态310h bits0..3全部解除；不把RAM0当clock。
- W+18000/4000真实接收并存储扩展word。原表经实际导出LE字节后由GLib SHA256核验，错误内容／少最后一个零／提前apply都不能image-match。
- W+200AC只支持bits0/1控制latch，**bit2始终不发布**；即使匹配全部数据，也不冒充PHY初始化完成。
- data读回是TEST观察扩展，不声称原Sony SRAM读ABI；checksum字段表示存储内容匹配，不表示微码已执行或电气PHY已校准。
- default-off `QEMU_SONY_PHY_SRAM_TEST`要求显式CCF／SCU／peer profile；所有初值及reset行为属于该有限TEST模型，非已校准silicon事实。

## 已运行与待验

主会话受admission锁运行`hardware/verify_phy_sram.sh`：ASan／UBSan及严格编译通过，覆盖完整4096word、900零尾、提前apply、错误顺序／位宽／高位／越界、前缀保留及导出哨兵。bb7e87c3d构建已成功，candidate-x85xiphj binary SHA256 `7267e27da5f121ef89d840155e6d4eef4fa5bc14c38f2360d847f7fdbeb0c01a`，16个C/header输入冻结。

`test_phy_sram_hardware.py`／bad9318b7／phy-sram-qtest-bhqtrlfe已实际通过，主会话另执行`verifiers/verify_phy_sram_hardware.py`独立重放PASS：4096次原表顺序MMIO写、16384B实际读回、8192B raw SHA、空apply／内容错误／少最后一个零／后写／clock-reset门槛阴性。`phy-sram-hardware-validation.json`为有限数据子层证据，bit2始终0，未运行原OFprobe。

下一项独立TEST profile是[分步清理规则](PHY-CLEAR-POLICY.md)：模型完成真实清理作业后可产生TEST初始化状态，以探索原probe实际上传；旧数据profile不改。这不是原硅片producer或PHY校准证据。

## 下一项阻塞

原W+200AC bit2硬件producer／初始化时序、上传后PHY寄存器与lane状态因果、LTSSM与真实PCI配置ATU仍需闭合。7bda研究代理已结束，只交付有限静态partial；主会话另实际补核60pins／4range及安装的原平台link callback W+201B8.bit1，见[SOC0-POST-UPLOAD.md](SOC0-POST-UPLOAD.md)。状态producer仍未闭合。此处数据子层不解封原host，也不等原PCI DMA、ICDT或CMOS帧消费。
