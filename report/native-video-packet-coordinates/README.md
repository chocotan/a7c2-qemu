# MPR到Infra包坐标：8字节前缀与固定区两地址

已找到MPR48B请求进入Infra38h/56B command的实际copy操作，不再仅按相似offset推断。请求中存在同一区域的两种地址：**MPR+8→CMD+10**与**MPR+28→CMD+30**。不能把两字段要求为同数值，也不能只追CMD+30就宣称内核会从它读API参数。内核对前一种地址的转换、queue到最终inline体身份仍缺，gap63/capture=false。

本次为公开M/I/W/F只读源核对，未执行固件、系统VM、设备、网络或private/full。15窗口3677B及4件完整身份在[source-pins.json](source-pins.json)，均在各ELF首个PT_LOAD，VA=file offset；第二load不能套用此等式。独立于3249/381冻结轮，不倒算native执行。

## 固定区的两个地址如何产生

M2c3a58 memory::init输入B/length，调用memory::Mmap(B,length,0,0)。Mmap把B作为mmap offset输入，返回映射V或0。初段写入fixed-area context+20=V、+28=B、+30 u32=200h、+38=V-B。

GetFixedArea(type2)的5项跳表原字节`070d001319`，index2跳到M2c38e0：第一个void**输出来自context+28，第二个来自+20，size来自+30。故本报告称两者P（mmap-offset/原地址域）与V（用户映射域）；没有读取BSS实际地址，也没有证明某次allocation成功或当前可用extent。200h是此slice的源声明容量，不是VideoInfo/ES分配大小。

## 原EncOpen真的复制了参数

M280bc8完整Codec::EncOpen将原API参数保存在x19，x20=FP+a0的PayloadMpr。其正常路径调整API内地址字段后，280f8c调用CreateMessage。CreateMessage M27be38固定调用GetFixedArea(type2)，将P写到payload+8、V写到payload+28；message ID写+24、codec type写+18、view ID写+1a。

280f90随后读取`FP+c8`，它**就是payload+28**，并在280f9c从原x19复制`zeroextend(count)*unit_size`字节。选定单个EncOpen参数单元为98h。不能把这个memcpy当作向payload+8数值地址做host解引用；原代码写的是V。

M27c058 SendMsgToAvbbc分配30h消息，以3次u64-pair load/store复制全部48B，保留上述两地址，再按原osal source/destination发送。函数返回0/1是它的原运输状态，不是编码或写卡完成。

## Infra前缀由实际copy建立

I139b64 ReceiveCommand使用DataflowInfraReceiver::ReceiveASync；I139bc0把目的设为`CMD+8`，I139bc4长度30h，I139bd0调用真实DataflowInfraMsg::GetMsg；接着写CMD的8字节头，length38h。完整正常48B输入下：

| MPR48字段 | Infra CMD38字段 | 值域 |
|---|---|---|
| +08 | +10 | P，固定区第一地址 |
| +28 | +30 | V，固定区映射地址 |
| +24 | +2c | 原message ID，EncOpen可为210h |
| +18 | +20 | codec type |
| +1a | +22 | view ID |

GetMsg F32330不是无限copy：type1按内部message length检查容量后复制，type2复制min(该payload长度,请求capacity)。ReceiveCommand没有检查GetMsg返回后再完整性分支；因此本合同要求真实正常输入恰有48B，不能用“调用过GetMsg”证明短包已写满CMD或把剩余字节清零。

## ParameterControl不神秘移动20h

I b34a4的完整SetParameter源恢复和原前缀表明，它以size38h存入ParameterControl ID1001，另从输入+30读取V、从+22选择目的队列。这里的上层输入与实际wire command应分别跟踪；不能因都叫P就抵消20h差异。

ParameterControl::SetValue(id,ptr,size) I a41b0先复制源bytes，再经MWF::Struct::SetValue；W2f778分配正长度缓冲并memcpy原data，GetValue W2f740返回保存的指针，不剥20h前缀。I a46e4正常路径返回这个data pointer。I b21e0取ID1001，设置CID/MID/length，按38h发送。输入copy本身不改变+10/+30两字段。

## 仍未闭合的真正下游

候选接收方法K169174的selected0201/210路径在K169260读取**input+10**，copy98h到receiver+50后重写header内指针。它在此之前还调用receiver+10上下文的vtable+28；[后继绑定](../native-video-receive-logger/README.md)已确认该方法是performance logger，**不转换P地址或读取参数体**。后续[原指针转换合同](../native-video-pointer-conversion/README.md)已找到更早的dispatcher Q+10→arch_phys_to_noncache→写回，以及type1/805720f9到169174的条件绑定。type0/default分支、完整98B跨度/lease与原运行选择仍未验。这里不把新候选升级为已连上的consumer。

此前[外层运输](../native-video-async-transport/README.md)的“CMD+30被完整保留”仍成立；本报告补出CMD+10的另一地址来源，说明只寻找从+30直接dereference可能选错了地址域。最终[状态动作](../native-video-state-action/README.md)已有inline28h+98h，但从上述packet/alias到该inline的完整生命周期、SDS/lease和源内容仍未认证。

E1（fixed-area init/Get）→F1（两地址配对与声明容量）；E2（原EncOpen及send）→F2（真正写V、实际48Bcopy）；E3（ReceiveCommand/GetMsg）→F3（实8B前缀和字段关系）；E4（原Set/Get）→F4（不存在假定的20h自动剥离）。不授权host访问logical地址，不把返回码/消息出现当完成，不生成ACK、帧或独立媒体。
