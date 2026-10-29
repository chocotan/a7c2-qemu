# 原PCI DMA启动条件及权限回收

已闭合原软件路径，未恢复PCIe硬件或运行PCI DMA。主会话独立运行原字节验证器：原Image SHA、122条指令锚点、64个状态取值、channel数组／清除别名和原诊断字符串通过。最终可复现脚本在`../virtual-pcidma/verifiers/verify_readiness.py`，`--capture`只生成本机排除的证据，不带Sony镜像或raw字节包发布。

原Image offset2a33b0的`str w25,[x20,#18h]`发布值1。worker 2a31d0中x20从controller+550h起，stride1d8h、终止1238h，实际覆盖channel1..7，随后逐个调用原`pcidma_run`。channel+18、controller+18(ASPM policy==3的布尔量)和request+18(callback指针)是不同对象。

**语义纠正：** 最初调查将controller+18称为host mode，证据不足。后续原export表明确31c780名为`pcie_aspm_policy`，其数组640ec8是ASPM策略；不是主从角色选择器。参数`pcie.aspm0..4`经原setter/API到writer31ddf0，主会话已复验24条原pin和参数／导出表。旧capture另外保留，不改写历史证据；以这里的纠正为准，policy1/2/3的细分含义尚未核定。

原helper2a3098读取`controller[1250h]`指向wrapper的+20268h，提取bits20:15。两路径均按32位无符号`state-11h <= 1`判断，仅接受11h、12h。原日志称`wait for L0 timeout`和`LTSSM`，但未再强套私有silicon状态名称。

worker在轮询前保存config base+80h的u16到controller+24h，清bit1；wrapper+20264h置bit5，调用原PCI config write31c950。条件满足后清wrapper bit5，才发布channel字段；超时仍失败走诊断及`brk #800h`，没有失败后照常发布的路径。10000是原timeout参数，转换单位未核，不把它直接当毫秒或秒。

policy==3时的自然请求链是：原异步submit→2a3718令非零channel outstanding count+1→0到1时在已connect且尚不可运行条件下调用2a3178→设置active/pending并唤醒原worker→读真实wrapper条件→publish→原run。初始2a38f0在policy==3时令channel0为1、1..7为0，其他policy令各channel为1；不能据此另选channel或强改policy绕过正常连接。原数组初值全1，不能把该默认值解释为endpoint角色。

connect先调用2a39b8，经原`pci_get_domain_bus_and_slot(domain=controller_id,bus=1,devfn=0)`取得设备，缺失fatal；保存PCI device并由其结构byte+4ch加10h得到config offset。这个对象字段不是直接读取配置空间byte4ch的证明。

最后请求IRQ退休令count从1到0后，2a3874以controller+560h为循环起点写+8清零。这实际上是channel1+18h，并逐个清channel1..7，**不是清锁字段**。随后唤醒完成等待者、恢复config、清active。下一次idle→busy必须重做硬件检查。另一个helper2a1e38清的是connected+14h；teardown重新初始化可运行字段并要求无outstanding/active才释放PCI设备。

因此当前硬件门槛是：真实PCI枚举／config事务及对应wrapper link行为。ATU数据访问通过不能满足它，不能直接写channel flag、计数或业务gate；stock QEMU DesignWare的恒报link-up也不能作为这里的证据。
