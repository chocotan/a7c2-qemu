# 编码VideoInfo缓冲与MPR双控制区

原参数到内核描述符的字段布局已经闭合：96字节VideoInfo槽基址、容量及读/写控制区分别对应。读游标和写游标来自**两个独立的控制基址**，不能同时绑定到C+8b3c0。跨异步消息的完整指针身份尚未闭合，native完成/发布缺口16/32仍保留，总gap mask=63。

本次为公开ALLLANG只读静态分析，未运行VM、网络、真机或物理SD，未读取private/full数据。该目录只保存字段合同及原字节复核，不增加缓冲映射、成功ACK或硬件完成。

## 实际字段对应

令A为AvbbcApi_EncOpen原参数，H为交给K15ebbc的描述符。MPR保存原虚拟侧值，再原地转换A内指针。M/I均为ELF VA（下列窗口VA等于文件offset）；K为av-cam raw，原KVA=ffffffc001000000+K。

| 用途 | A字段 | MPR stream0 / stream1保存位置 | H字段→内核实例 |
|---|---|---|---|
| VideoInfo槽基址 | +30 u64 | 3b7f70 / 3b7ef0 | +58 u64→C+8b3f0 |
| 槽容量 | +38 u16 | 3b80b0 / 3b8080（u32） | +60 u16→u32[C+8b3f8] |
| 读控制基址 | +50 u64 | 3b7e58 / 3b7e08，保存原base+0 | +78 u64→C+8b3c8 |
| 写控制基址 | +58 u64 | 3b7e68 / 3b7e18，保存原base+4 | +80 u64→C+8b3c0，发布写mapped base+4 |
| 辅助输出基址 | +20 u64 | stream0 BufferAreaInfo位于3b8048 | +48 u64→C+8b420 |
| 辅助容量 | +28 u16 | stream0位于3b8050（u32） | +50 u16→u32[C+8b428] |

K194cf4把incoming前28字节复制到H，再把incoming+28开始的98字节复制到H+28；这里28/98均为十六进制。K194dc4..194de0将H+8设为H+28、H+10设为98并调用K1454f8，沿14550c→1345fc→14f854→15ebbc保留H参数。这是实际前缀复制证据，因此H+58等于内联A+30，不是从偏移相似性推断。

M280d48..280d68保存A+30和零扩展A+38。M280e1c..280e30保存A+50；M280e80..280e98把读base写入3b7e58。M280e40..280e60保存A+58；M280f18..280f34执行`str wzr,[x1],#4`后把base+4存到3b7e68。EncOpen2对第二个98字节参数块执行相应操作；M281448/281508保存stream1读/写指针。

## 地址修正与容量边界

M280650 ChangeVirtToPhysAddr调用DmmMemInfo::GetUnitInfo，成功时以zero_extend(out32)+out64代替输入指针，返回old-converted；失败返回0。MPR在调用前保存原虚拟base，并把修正保存在BufferAreaInfo+10。故上述字段属于同一分配的两个地址域，不能要求数值相同或授权host直接解引用。

VideoInfo所需长度是N*60。读控制声明长度294，写控制声明长度330（十六进制）；这些是BufferAreaInfo的原声明，不是独立测量的实际分配extent。内核内部发布队列Q的N与supplied count分别来源，尚未证明相等。完整实例与实际映射仍由调用方提供，纯[元数据发布计划](../native-video-producer-contract/README.md)不能替代它。

## 第一处未闭合的异步边

Infra I0b21e0经ParameterControl vtable+b0取得参数1001的command指针P，置P+4 u16=38，经ConvertCid(5)/ConvertCmdMid(5,520)选目标后，I0b22c0调用OsalSndMsg(destination,P,38)。对应movie路径在I139374调用DataflowInfraMsg::SetDataflowMsg(P,38)，正常分支在I139620调用DataflowInfraSender::SendASync。

I0b34f4的setup序列从P+30读取API参数指针。尚未追完serializer/receiver如何把该指针指向的98字节复制成K incoming+28的内联内容。MPR早期48字节请求+28如何对应Infra38字节请求+30在本次未独立闭合；后续[包坐标合同](../native-video-packet-coordinates/README.md)已证原48B被复制到CMD+8，以及CMD+10/CMD+30是fixed area两种地址。最终kernel转换与同一runtime lease仍未认证。不能将字段布局相符直接提升为同一runtime消息/lease已交付。

[source-pins.json](source-pins.json)保存3个完整公开资产身份、10窗口及4条内核分支锚点，共4040字节。`test_source.py`核这些原字节，并保留16/32缺口；源码 globals 3b…为BSS位置，只用代码writer证明，不当作文件内容读取。

E1（MPR保存/转换）→F1（虚拟侧游标与地址修正）；E2（实际28前缀和内核setter）→F2（对应字段、双控制基址）；E3（Infra异步发送）→F3（精确消息边界，尚无完整指针传输证明）。实际像素/ES生产、MMIO/IRQ、硬件同步、lease及原文件输出均未因此通过。
