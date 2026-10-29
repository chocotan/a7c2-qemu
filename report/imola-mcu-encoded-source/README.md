# MCU编码结果上游：8880、AVC记录与字节计数

原S88/P结果构造的上游已追到MCU的8880消息、AVC结果回调和一个真实CPU字节计数writer。尚未找到输入结果包的硬件生产者、codec kick寄存器或源像素布局，不能据此把libx264接作原编码后端。native gaps=63、capture=false。

本次只读公开VCD固件，不执行MCU/VM、不访问网络/硬件/物理SD/private/full。VA=80000000+raw仅用于已证RAM区间；ROM不按此映射。完整身份和12窗口1084B在[source-pins.json](source-pins.json)。Kuna曾因错误选项未产生有效结果，本合同只使用实际MIPS指令和延迟槽核对，不使用未解释IPSX语义。

## 8880与实际AVC分支

80169b14将selector8880送到80169bb8；后者要求u16[M+6]==128，令S=M+8，在80169e04调用8016a204，延迟槽给a1=S。128十六进制=296字节，含8字节头的信封为130字节。

四个真实构造点为raw efe24/f1e48/111284/1238fc。源assert路径区分HEVC（800efac8）、AVC（**80110f3c**）与MPEG2（8012361c），不能把第一分支当作H.264。

AVC回调收到a0=O、a1=channel低16位、a2=W（d0字节记录）、a3=J（排队job）；从u32[*u32(J+2c)]及u32[*u32(J+10)]分别做范围检查/地址转换取得工作状态与参数状态。801110dc经801c6ab4把W复制到S+58；后续serializer保留该子记录。

| 下游S字段 | W来源 |
|---|---|
| +88/+8c/+90 | +30/+34/+38 |
| +9c/+a0/+a4 | +44/+48/+4c |
| +118/+11c/+120 | +c0/+c4/+c8 |

这些是实际buffer descriptor与计数，不是编码像素。

## W真实接口与AVC虚调用

801578b8保存传入W，在80157964..cc送入O+f348的四项d0-stride环，相关cursor/count位于+340/+344/+348/+34c。80158230..58把选中W传a2、J传a3，调用vtable+40。AVC vtable802408bc的该槽是80110f3c；+1c为80110e6c，其wrapper调用801578b8。静态接口身份已匹配，实际capture选择此vtable未观察。

## 实际CPU计数writer

raw81240..812b0令Q=u32[B+724+384]、C=u32[Q+10]，要求队列+38c非零、+388为正，否则原assert路径。实际u32 load/store：

```text
u32[C+c28] += u32[P+0] + u32[P+4]
u32[C+c38] += u32[P+0] + u32[P+c8]
u32[C+c30]  = u32[P+14]
u32[C+c34]  = u32[P+18]
u32[C+c50] += u32[P+4] - u32[P+c8]
u32[C+c80]  = u32[P+a0]
call80081318(B,P)
```

P是CPU packet指针，不是已证明的MMIO地址。HEVC工作区R=C+bc0，因此R+68正是C+c28；HEVC构造比较该计数与O+f9e0，取较大值写S+18，必要时写W+b8差值，并取R+70/+74写S+30/+14。AVC有对应读取，但其工作区初始化尚未充分固定，不能直接跨函数认定同一C。

另一个packet consumer800873d0由raw23c85c的vtable字引用；87784读取P+0/P+4更新C+2b40+4*i和C+2b60+4*i，证明上游字节计数接口存在。没有证明是谁填P或写对应ES字节。

E1（8880/AVC构造）→F1（下游结果接口）；E2（d0环和vtable）→F2（真实record传递）；E3（CPU状态store）→F3（实际计数writer）。最前未闭合生产者是传入MBP-proxy消费者的P及它与W offset/length的绑定。尺寸、YC plane、stride、format enum、编码启动opcode、BE32码流writer均未恢复，因此不启用codec、不发完成或ACK。
