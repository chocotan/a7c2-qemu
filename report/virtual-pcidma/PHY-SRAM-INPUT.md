# 原PHY SRAM输入、上传数据与失败路径

f954代理完成了选择／数据范围调查和checkpoint，但没有交付独立verifier。主会话已继续逐原字节核验，并实际运行`verifiers/verify_phy_sram_contract.py`：27条指令锚点、原Image／官方DTB身份、descriptor／输入摘要全部通过。以下为静态输入合同，尚未运行原SoC host／PHY上传。

| 项 | 原输入 |
|---|---|
|官方controller0|firm-id1，num-lanes4|
|firm-id1 descriptor|Image45ffc0h，stride10h|
|原table指针|VAffffff80084e01c0，Image4601c0h|
|计数|4096个u16，raw8192字节|
|raw范围|4601c0h..4621bfh|
|raw SHA256|6133a8e7fb95e2ac83119517c00a306d485dcf3bf4afd814411317af64439f95|
|上传形式|LDRH零扩展成u32，逐4字节MMIO写|
|MMIO offset范围|18000h..1bffch，共4000h字节|
|零扩展u32 stream SHA256|963669fdc92d57141fa41095ecd7c5a1b972162d2e699a702ebfc8b6c1ef64dc|
|尾部零半字|900个，原循环仍全部写入|

程序从firm-id选择descriptor；num-lanes不是表选择器，另用于后续lane状态。原raw table保留在只读Image中，交付脚本按摘要校验，不把Sony原始firmware bytes加入公开模型包。

## 后续handover与pre-poll顺序已核

f954续查交付的`verify_prepoll.py`经主会话实际重跑通过，移交`verifiers/verify_phy_prepoll.py`：12pins／3范围摘要／19个symbol绑定调用／5gate记录。原Image与完整本地4.9.337参考源码交叉确认context+20h是`dw_pcie.pp.handover`，不是root_bus_nr；pp从controller+20h起，root_bus_nr另在controller+40h。

原probe先清handover，只有`reset_control_status(rst_pwrup)==0`才写1；非零包括错误值均不写1。上传跳过条件准确为`handover!=0 || firm_id==0`。因此检测prior-reset状态不等真实初始化已经完成，错误也不能被当成合法cold状态；不强写字段选择上传路径。

non-handover／firm-id1路径：assert APB reset→依次尝试prepare/enable APB、DBI、SLV、MSTR、AUX clock→delay→deassert APB→清W200ach bits0/1（保留bit2，选择external SRAM）→依次deassert pwrup、button、pe→barrier/delay→轮询bit2。原clock prepare／enable错误按源路径累计，不能因程序继续就认为clock真实可用。

## bit1不是上传完成证据

原249b44起最多200次观察wrapper+200ach bit2。只有成功观察后才进入半字上传循环；此循环没有SRAM readback。

耗尽走24a170，将w19设为-1，再跳回249bd8，仍然读改写200ach bit1，之后才按w19转超时日志。因此“bit1置位”“程序到了apply点”甚至后面通知不能替代实际数据消费。旧PHY局部报告的bit1操作只保留为独立控制写，不能升级为成功条件。

未来有限模型的有界验收须同时满足：先有合法的bit2观察、4096次有序对齐u32事务且高16位为零／低16位逐项匹配原表摘要（包括尾部900个零）、独立记录随后bit1写入、拒绝timeout后空apply；后续四lane状态和真实配置／link另验。

pre-poll软件序列没有置bit2；该位在参考源码名为PHY_SRAM_INIT_DONE。reset释放后的硬件SRAM初始化是候选触发，但真实producer、reset值、latency和与后续lane-ready的因果联系仍未闭合。2469b8控制的是**W201ach.bit2 LTSSM**，不是这里W200ach.bit2。当前只有静态输入／pre-poll验证，不提供恒bit2、恒ready、跳循环、伪upload ACK、PLL锁定或全PHY完成结论。
