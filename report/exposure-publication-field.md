# 曝光2036字段：快照来源与侧向通知时序

两路曝光调查中的发布侧已交付一条具体字段合同。只查固定原CP
18090880B/SHA256f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428，
未执行原代码或写guest状态。正常4073/2040整包generation链沿用既有独立报告，
此次不把单字段验证扩大成整包所有前提已证。

## 原快照源

opcode2036对应getter8d68d2。实际D=*(context+10)，发布取u8(D+113/+114)，
先写静态1659020+8/+9，再把完整12B缓存复制到借用cursor，返回0c。
较早32f7f6会copy(D+f2,S+2c8,3de)，包含ISO字节；但发布时不再直接读S。
所以S的更新、真实周期生产D及newgeneration必须分开验证，不能仅写S就
宣称原2040已刷新。getter借用输出cursor，本地没有为字段分配/释放消息。

## 比较影子与真实通知

1aa9f86对D113，1206c0a对D114；不同就更新两者及1aa9f87=(D114==0)，
构造一个12B侧向记录，然后调用8d9f4e。main核该helper为实际allocate/copy/send：
目标028d07f3，源90030001，分配565204；send564b38失败时以真实payload指针
调用565300清理，再返回send error；分配失败返回allocation error。
成功send移交ownership，但没有证明端点consumer或硬件曝光结果。

因此“非0则本次字段长度0”是IO失败分支，不是已证的曝光无效/硬件拒绝。
比较影子在发送前提交，失败没有回滚；下一次同D查询可以跳过这个通知，
不能擅改为成功才提交、自动重发、永久拒绝或forced绕过。12B侧record只证
u16+0=2/u32+4=2/u16+8 packed值，未初始化padding不能要求0。

另有context+4指向word与186f4cc的差>0b或forced1门槛；它不是root+d5c的
2040generation。缓存相同且非forced可返回0，forced1也绕不过当次通知IO失败。
完整返回路径与次序仍需保留，不能用requested=returned或空2040替代。

main固定原窗口核验：getter8d68d2/228B SHA256
bb9c8c4defac4bd730cd9a0f28f672f918ab0c9c1fc3dfadb97eef057efbef8a；
helper8d9f4e/138B SHA25618f34f615b5f94ec720387e5e1c5cb37296d09e0363da7076b217874c1c3a7be。
上游真实写入/周期有效性由另一调查独立核对，尚未新增曝光backend或拍摄通过。

## 与上游调查对照

GLM侧3403f8候选实际保存r0=S、r1=T，从1658480刷新对象把14个halfword
写T+1680..169a，并在条件分支保存T指针；没有闭合所需S+2e9/+2ea真实setter。
main核该380B原窗口SHA256
b7d58eca51b20bdccbc17eef6958e12fcd17e89c88108d5d88b10194cac44c35，
及86f91e/44B的40Bcopyhelper（SHA256
025c7a22a4a81f60660bd5d7e0cd6e2903d6f0241cf6e2cd5f4b8102261a65e7）。
这排除一个直接源写入假设，不能凭未见直接写和静态xref0证明全部alias无副作用。
代理的BL扫描J1/J2计算错误已明确排除，空结果不证明caller不存在。

两侧目前不能闭合为S更新→真实周期D生产→newgeneration→原2040消费的可用协议。
后续只能选一个已知source候选或实际生产点继续，暂不通过固定值写入或通知ACK
绕过。该任务保持未完成，已有精确字节与失败边界归档。

## 写入侧收窄到两条路径（main已核代理取证，本轮）

代理（kimi）取证`scratch/exposure-bidirectional-kimi/`（REPORT.md），main独立复核CP原字节（Thumb，CPVA=raw+0x108000）确认属实。发布/有效性侧此前已钉（2036 getter 8d68d2 读 u8(D+0x113/0x114)、shadow比对、8d9f4e notify、0x165b47c→HS 8dad54 generation链）。写入侧本轮收窄到**两条具体路径**，但都未闭合到最终源：

- **路径1（已知）**：`32f7f6` = copy(D+0xf2, S+0x2c8, 0x3de)，D+113/114 ← S+0x2e9/0x2ea = 0x2015979/7A；S+0x2e9/0x2ea 的写入者仍未知。
- **路径2（本轮新钉）**：函数 `0x384b14`（main已核入口字节 f0b5/03af/2de9000f）内 `0x385bb4 strb.w r0,[r2,#0x113]`（←ldrb[r0,#0x110]）与 `0x385bbc strb.w r0,[r2,#0x114]`（←ldrb[r8,#0x30e]），r2=[sp,#0x2c]=arg1，源是**静态RAM表字节**（0x1ab5c4e+idx、0x1ab5e4c），非S。唯一调用方 BL @ `0x934e1e`（在 0x934df0 内，全镜像BL扫描仅此一处，无函数指针引用；main已核该BL）。

**未闭合（诚实）**：①arg1==D 的绑定未闭合（0x934df0 只是转发自己的 arg1）；②所有源表（0x1ab5b3e…0x1ab5e4c、0x18aea40）在 VA≥0x1249000 = **超出 cpapp-b.bin 文件末尾**（文件覆盖 0x108000..0x1249000），是运行时RAM、静态不可读，故"经此路径落到 D+0x113/0x114 的具体值"静态不可得。下一步：xref 0x934df0 的调用方绑定 arg1==D，查未触碰的 0x94d25e/266 点。这是**写入侧收窄、最终源未闭合**的部分进展，不冒充曝光源已闭合。
