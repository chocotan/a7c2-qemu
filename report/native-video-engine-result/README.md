# Imola BSO_DONE到620结果快照

原回调对象注册、实际虚调用者以及620字节结果快照的CPU构造已经闭合。它来自BSO_DONE事件携带的结果指针。尚未找到发送原0500消息、填P/Q结果内存及向ES缓冲写出真实编码字节的生产者；不能据此宣布编码完成，native gap mask=63、capture=false。

范围为公开av-cam.bin只读静态分析，无VM、网络、硬件、物理SD或private/full。K为raw offset，原KVA=ffffffc001000000+K。完整身份与12窗口4348字节在[source-pins.json](source-pins.json)。

## 已绑定的真实回调

K245ab8写vptr37b0a8到O+2ac78，K245ac4写O到O+2ac80。K247744..247758以O+18通道号和O+2ac78对象登记，经22825c→22cea8→2255dc→224260取得该通道encoder handler C；K22308c保存callback到C+1140。

K223094从C+1140取对象，经vptr+10尾调用，实际目标24cf88→2471e8。此前这只是单独的虚函数入口，现在注册与调用对象身份已经接上。

## 真正调用者与620构造

K224ab0从事件E取D=E+10，在E+12==2的BSO_DONE和encode-mode条件通过后，清零局部R[620]，调用221630(C,R,D)，然后223094(C,R)。**原代码没有先检查221630返回值再决定是否通知**，回调发生不等于有效结果。

| R字段 | 源实际读取 |
|---|---|
| +0 u8、+2 u16、+4 u8、+6 u16、+8 u8 | D+3、+4、+a、+8、+b |
| +618/+61c u32 | D+20/+24 |
| +10..5af的90个10字节段槽 | P=u64[D+10]，特殊分支另用Q=u64[D+18] |
| +5b0..617的两份34元数据 | 2221c0按索引0/1，从P+18..4b逐字段复制 |
| +c u32 | 90个段的u32长度按W32加法求和 |

例如C+10b2<=1且C+ddb8==0分支，令B=u64[C+ddc0]，会写segment0.address=B+zero_extend(u32[P+8])、length=u32[P+c]、byte_c=1。其他普通分支读取P+0/+4、+8/+c、+10/+14形成两段或三段。这是实际结果内存的offset/length，不是把初始化数组当输出。

B由21b790从C+1080写入参数块+48，再在21b7d0保存到C+ddc0；其实际物理总线映射仍未闭合。C+e128==8走221dc8，Q首u32给输入descriptor数，后续每项c字节（offset u32、length u32、tag u16）；接受项形成B+u32[P+8]+offset。循环有容量5a限制，末尾还调用22343c，不能把输入数量当最终有效段数。

## 已追到的事件入口

```text
K2961bc接收循环
  ->296438从原消息取最多180十进制字节至G+1b0
  ->29649c检查u16[G+1b2]==0500
  ->2964bc复制90十六进制字节事件
  ->227a08 ->22cb78 ->224ab0
  ->221630构造620 ->登记的callback
```

22cb78本路径要求事件+a==0、+8==0、+9!=0、+b<8，另排除+12==e的独立分支。原日志`Get BSO_DONE when not encode mode`及源文件`common/imola_common_state.cpp`、`common/imola2/imola_common_api_enc_handler.cpp`与此路径对应，不能将它们视为硬件IRQ定义。

E1（注册/虚调用）→F1（实际对象身份）；E2（620 CPU writer）→F2（结果字段来源）；E3（0500接收路径）→F3（真实结果消息入口）。精确剩余生产点是0500发送者、P/Q结果内存writer、ES B+offset字节writer及它们的完成/可见性绑定。未证明CMOS/YC输入格式、编码寄存器/ISA、完成IRQ或缓存同步。

本合同推进了[实际S88 writer](../native-video-record-fill/README.md)之前的CPU结果构造边；仍不足以驱动host codec冒充原硬件编码。只消费完整、有源、可访问的结果快照，错误或未知状态继续拒绝，不发送原生完成。
