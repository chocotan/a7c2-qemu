# 原PHY前置条件：有限静态核验

代理交付为partial，原扩展提取脚本没有成功完成，也没有执行其独立PHY verifier。主会话重新从原Image核对并补齐`verifiers/verify_phy_prerequisites.py`，已实际通过SHA、63条指令锚点和名称表。这只闭合下列子集；完整reset／clock顺序、时序和原host运行仍未验收。

probe引用的两个连续表：

|表内序号|reset（45ff00）|clock（45ff30）|
|---|---|---|
|0|rst_pwrup|apb_pclk|
|1|rst_button|dbi_aclk|
|2|rst_pe|slv_aclk|
|3|rst_apb|mstr_aclk|
|4|rst_axi2avb_pci|aux_clk|
|5|rst_axi2avb_pci_i0|axi2avb_pcie0|
|6|—|axi2avb_pcie1|

这是代码表内的精确字符串；后续主会话36pins及官方DTB验证已确认probe依次lookup全部6／7项，任何lookup错误转-19，末两reset为shared而非optional。后续enable/assert/deassert仍有条件分支，不代表所有操作无条件相同，见[NATIVE-HOST-DEPENDENCIES.md](NATIVE-HOST-DEPENDENCIES.md)。

令W为原helper从controller+160h取出的映射。245d60执行W+offset的u32读取并dsb ld；对应写helper执行32位写入。已核：

- 248610对W+20380h bit0作RMW：arg=0置1，其他值清0，然后调用31e0b8(id,arg)。此函数不执行PHY-ready轮询，不据名称猜成完成通知。
- 2469b8先清W+201ach bit2，若enable参数非零，再读并置bit2。硬件位名称未在这里提升为硅片定义。
- probe的条件SRAM路径以200为counter，每次调用delay helper后读取W+200ach bit2，未置位继续。后续主会话已27pins及原descriptor/hash核定firm-id1的4096个halfword／8192B及完整u32上传范围，见[PHY-SRAM-INPUT.md](PHY-SRAM-INPUT.md)。**timeout也会跳到bit1写入，故bit1不能证明上传成功**；真实bit2 producer与完整物理因果仍未闭合，不用空数据或虚构上传代替。
- probe还按条件清W+20018h bit29，以及W+20380h bit4。

## 主会话补闭合的状态判据

246cc0先RMW置W+20380h的1f0000h，再读取W+2038ch。输入参数为1／2／4时分别检查mask1／3／fh，**masked status为零时写出1，非零时写出0**；其他输入返回-22。该输出由probe等待逻辑消费。

probe先调用一次helper，失败后最多再调用200次；到counter耗尽路径24a0fc仍会重读输出，若最后一次已经成功则退出等待，不能把“先减counter”误报为忽略最后一次成功。完整控制／时序模型必须消费这些条件，不能用恒定全零状态冒充PHY初始化。

## 地址约定纠正

本Image链接base是ffffff8008080000。代理用VA标签命名的delay／sleep提取文件偏了80000h；主会话首次pin检查在249b5c实际失败后，重新按raw offset解码确认：

- 249b5c的BL目标是Image+1efb88，对应VA ffffff800826fb88。
- 249d34／249d50的目标是Image+7b850，对应VA ffffff80080fb850。

原失败和代理附件保留。没有把错误范围中的函数当延时实现；这里不凭10c7h字面值推断delay单位。MSleep等原export调用与控制次序应继续按同一Image核定。
