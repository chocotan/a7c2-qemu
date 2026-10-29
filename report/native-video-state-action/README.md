# 原状态动作与内联参数：没有闭合retained pointer展开

新增正向证据是36df18状态动作表→19d7e0→194cf4的实际调用，以及来自`input_object+18`的嵌入字节。原API指针A如何变成该inline内容仍未证明，不能构建同源resolver或清除native gap。`gap_mask=63`、capture=false。

范围为公开av-cam.bin只读，无固件执行、系统VM、网络、硬件或private/full。8个窗口1292B及原件身份在[source-pins.json](source-pins.json)，不套用CP+108000或ELF映射。此为3249/381冻结轮后source补充，不计入原运行。

## 实际状态动作

198344保存输入x1→x21，从object+8读取原状态；1983b0设置表基36dee0，步长18h。1984b8..4d4读`[table+original_state*18h+8]`，恢复x1=x21后BLR。当原状态2时槽正为36df18，其完整8B为ffffffc00119d7e0。**这是状态动作表，不是对象vptr。** 忙标志、准备动作与状态迁移结果也参与guard，不能由entry存在宣称已执行。

完整19d7e0..19d7f8保存LR、LDR x0,[x0]、BL194cf4、return1，x1保留。再上一层19d2cc令x1=input_object+18、x0=u64[input_object+10]，尾调198344。这提供嵌入数据来源，不证明input_object来自CID2003/MID0201。

194cf4先将incoming+28的98B存this+38，然后把原incoming前28B与同一inline98B复制到H=sp+8，设H+8=H+28、H+10=98，调用既有1454bc/1454f8。该copy没有读取retained A。双控制区对应仍见[shared binding](../native-video-shared-binding/README.md)，不新增指针等值断言。

## 排除一个相似copy候选

1899f0属于完整函数189964：其两源分别this+320/this+348，copy宽度28h/98h。前一完整函数18985c已把输入连续d4h字节保存this+320；这是已有inline布局再复制，不是加载某个API pointer再展开。不能因同长度0x98就闭合传输。

193d98窗口还核得owner构造时x1=this调用19cd00，把返回对象存this+478。它仅提供对象绑定，没有将外层队列消息绑定到这个动作。原队列00f9/20f9、command2003/0201、状态parameter1001仍各自需要来源证据，不合并编号域。

## 下一具体缺口

第一处缺的是**谁填充19d2cc输入对象+18**，怎样把Mkernel+48保存的逻辑A所指98B放进对应inline区。MPR48B到Infra38B前缀现由[后继包坐标核查](../native-video-packet-coordinates/README.md)闭合；实际consumer command ID、SDS及地址转换到此inline体仍未证明。[外层transport](../native-video-async-transport/README.md)只能证明浅copy/relocation/enqueue，不能替代这个read/copy。

E1（表和BLR）→F1（原state2对应真实动作）；E2（19d2cc与194cf4）→F2（嵌入源和精确copy）；E3（18985c/189964）→F3（相似候选不是pointer-expander）。后续仅从该input对象的构造/提交入口继续，原帧/ES/IRQ与真实写卡仍另验。不添加未消费helper、default或success ACK。
