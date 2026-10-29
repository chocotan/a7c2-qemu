# 原packet+10转换与type1队列接收绑定

已正向闭合真正的参数地址转换及constructor-bound type1路径：dispatcher把packet+10的原地址转为noncache指针后写回，再按实际guards提交接收对象。**没有运行时选择、完整98B extent或lease消费证明。** 不把此source闭合提升为native完成，gap63/capture=false。

公开K=av-cam.bin、L=liro.ko，完整身份和10窗口5240B见[source-pins.json](source-pins.json)。K为raw、KVA=ffffffc001000000+raw；L是ET_REL，按sections/relocations核对。只读，无固件执行、系统VM、网络、硬件或private/full；不倒算3249/381冻结轮。

## 实际转换，不是logger

A1470 dispatcher令Q=x1。CID2003/MID0201、transport metadata identifier不同于本地destination时，A1850读取u64[Q+10]。A1864..88c按raw332258的4项table检查`base<=P<base+size`；匹配项到A1a48调用2f500，A1a4c将返回结果写回同一Q+10。非零地址未匹配则先diagnostic，再把该字段写0，不保留一个看似合法地址。

2f500尾调module API+620；L `.rela.init.data+5d8` relocation给出provider `arch_phys_to_noncache`，`.init.text+4b0..4c4`复制API表到base+48，5d8+48=620。这里不猜数字KVA、不host解引用logical地址。**原range gate只检查地址起点，不检查P+98h或生命周期。**

前一[接收logger报告](../native-video-receive-logger/README.md)的16919c callback不做转换；实际operation在本节更早的dispatcher。local traffic有明确skip分支，不能把转换施加给全部packet。

## 队列到receiver的正向对象链

shared constructor A5b14把destination写context C+c；其type1 caller计算805700fa+1fff=**805720f9**。receive object R=C+358保存C到R+8；A3b54从[C+c]收件，copy body到Q=R+1a8=C+500，并调用A1470。R+328=C+680保存dispatcher D=C+308，D+18=C+320保存由A6264构造的aggregate。

constructor type非零时A6408..10把selected aggregate绑定到A71a8对象；12c864通过该aggregate vtable+10调用168da8。168e80是直接virtual submitter，通过active receiver slot0转交同一Q；raw364078对应169174。这是actual dataflow/object binding，不仅是同尺寸或相似消息ID。

**805700f9/type0选择不同aggregate，本报告没有证明它继承上述type1目标。** 不能因为两个queue都在同一constructor出现，就宣布default stream也已闭合。

## guard和参数变更必须保留

在0201/210/subtype0路径，168e14读取converted Q+10，168e24再读取parameter byte+88。非零选aggregate+690，零选+18；实际读值未观察。dispatcher另有`first_u64[convertedP]==0`或a8aa8返回true时绕过12c864的路径，也不能默认为false。

转换后首个参数读是A1a6c的u64[convertedP]，然后可到168e24，再到已有169260的98B copy。A1ab0还可能在selected command、metadata ID!=808b0768时把parameter byte+67清零。因此最终inline参数不是“原始输入始终逐byte不变”；未来resolver/验证必须记录该已证修改以及发生条件。

[包坐标合同](../native-video-packet-coordinates/README.md)固定MPR固定区双地址、CPU实际写V和48B→CMD+8的上层关系。本报告连接了下层Q+10转换与一个队列分支，不给出runtime映射、分支值或成功消费证据，也不将CMD+30映射域和CMD+10转换结果数值相等。

E1（原range/read/call/writeback）→F1（真正converter）；E2（liro relocation/API copy）→F2（provider）；E3（constructor/recv/dispatch/vtables）→F3（type1 receiver route）；E4（实际reads/guards/mutation）→F4（必要branch条件和最终字节差异）。后续需type0独立绑定、coherent98B完整跨度/owner、原运行读入及release证据，才可认证同一输入被消费。没有新增Ready、ACK、IRQ或独立媒体来代替它。
