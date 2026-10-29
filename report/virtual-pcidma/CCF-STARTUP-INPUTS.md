# 原CCF provider的启动输入与controller0七个时钟

a6调查只交付身份检查和checkpoint，新增函数查看额度0/4，未得到合同。主会话继续直接读取原fixed/divider/mux注册循环、callback及save-init，恢复107条clock数据并实际运行`verifiers/verify_ccf_startup_inputs.py`：**37pins、原Image身份、17 fixed／5 divider／15 mux／70 gate记录和七个目标parent全部通过**。当前未运行原CCF provider实验。

|ID|名字|STATUS offset/bit|父源与内核静态rate|
|---|---|---|---|
|62|gate_pcie_i_p|80h/1|fix_pll3_99，99 MHz|
|63|gate_pcie_i_dbi|80h/2|fix_pll3_396，396 MHz|
|64|gate_pcie_i_slv|80h/3|fix_pll3_396，396 MHz|
|65|gate_pcie_i_mst|80h/4|fix_pll3_396，396 MHz|
|66|gate_pcie_i_aux|80h/5|fix_pll4_1，1 MHz|
|29|gate_x2v_pcie0|30h/18|parent指针NULL，不能伪造rate|
|30|gate_x2v_pcie1|30h/19|parent指针NULL，不能伪造rate|

五个有parent的PCIe输入不经过divider或mux。两条NULL-parent clock即使内核rate查询返回0，也只表示该树缺少parent rate信息，不可报告物理时钟0 Hz。

## 整个provider注册的输入范围

原provider会注册完整107项，故不能只支持七个lookup就忽略其他callback可能读取的寄存器。Gate status bank为0/20/30/40/50/80h，enable／disable别名+4/+8；原70项的每bank允许mask由验证器计算。

五个divider读10ch/110h/114h/118h/11ch的低8位，shift0，原flags0且无divider表。原`_get_div`走encoded+1分支，故encoding0是合法divisor1。它们属于sdio/emmc/sdif/ms树，不参与上表五个固定父源；这不是任何存储吞吐或拍摄时序验收。

十五个mux分布于210h/220h/230h，字段mask分别1f000000h／11111h／3ffh，parent数量2或4。原get_parent对encoding0返回有效parent0；虚拟板可以显式选择合法编码0，但不能把未建模RAM0当作已实现的选择器。

## 保存表不等注册期硬件读取

`cxd_clk_save_init@25fa60`仅存x1 table、w2 count、x0 regmap到普通kernel数据，没有任何read调用。实际save table是62a398h、count25，不是先前任务提示里的629398h。这不能作为注册期必须预置25个硬件值的理由，也不说明未来syscore suspend/resume无需模型。

后续Task78只恢复正常provider/consumer并核lookup、rate、prepare-enable、硬件状态变化及disable；必须先提供有状态gate／mux／divider／reset寄存器，未知访问拒绝，不能用固定成功ACK。硅片启动值仍未知，任何虚拟板初值单独报告；没有CCF runtime、DW SoC host／PHY或DMA通过结论。

## 当前实现状态

独立worker交付的纯C core已经主会话核对并移交`hardware/ccf.c/.h/test_ccf.c`，真实mask／边界／原HCLK位号与状态操作通过主会话ASan／UBSan复验。20个status bank／5个divider的W1S/W1C、直接写和非法混合bits拒绝均有确定性测试。

新`test_ccf_scu.c`把这些状态与已验wrapper门槛组合，保持基础SCU profile不改。派生DTB保留基准树，新增generic syscon父、原CXD clock/reset子节点和7clock consumer，采用新phandle避免冲突；已有主机全树／属性检查。正常API `ccf-client`已过7个控制情形、5512B普通module ABI及真实export验证；观察器另过3个实际输出/回显/硬件状态错误测试。

离线candidate构建b1091f9b6已成功，`candidate-w29iqj8g` binary SHA256 `4bc13601cca24666b897de9c7d36f4a9b30fd234099b41575563efc669a42c64`。扩展寄存器真实qtest bd03fa1c6／pcie-scu-qtest-9lrt2ex5已通过，主会话另运行`verify_ccf_hardware.py`独立重放PASS：20状态bank／5 divider、131实际读回、36拒写无变、五wrapper门槛／system_reset／defaultoff。归档`ccf-hardware-validation.json`，仅覆盖有限TEST硬件。

启动前独立评审993已完成，未发现本次受限实验的confirmed P0/P1；确认OF/syscon/resource、已知注册期寄存器覆盖、正常API client引用释放及trace地址约定。评审本身未跑VM／unit，已有tests与硬件证据来自主会话。

原provider／七normalAPI组件b9d4465e7／trial-db4bp47v已实际通过，主会话另执行`verify_native_ccf.py`独立核原记录：原CXDprovider／consumer绑定、7个真实lookup及rate、prepare-enable、硬件0→1→0／disable、client-MMIO片段7组原SET/CLEAR／最终QMP Gate30和80均0、CPU恢复／owned VM退出通过。原UDIF／五IRQ前提保持，无WARN、两个DMA engine仍0，无connect-submit。归档`native-ccf-validation.json`，Task78有限目标完成。

两项NULL-parent gate的rate API值0不报告为物理0 Hz；结果不泛化107项全部rate／操作、silicon reset/PLL校准、DW SoC OF host／PHY／link、原DMA或图像消费。原镜像、基础virt板与之前所有partial／PASS运行证据保持不改。Task79继续正常controller0 host／PHY数据前提。
