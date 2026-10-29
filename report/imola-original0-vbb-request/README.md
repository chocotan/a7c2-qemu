# original0到VBB8420：实际像素动作仍缺

已闭合同一original0 Y/C句柄分配、地址赋值与后续VBB8420请求的连接，尚未找到像素writer。请求接收器、传输源/目的和pitch/格式的解释仍未闭合，不能把分配、cache flush或queue signal当作帧到达。

本次只读公开Imola2，未执行MCU/系统VM、网络或真实设备。完整原件身份及8个RAM0窗口6676B见[source-pins.json](source-pins.json)。继承[派生AVC同B绑定](../imola-source-frame-binding/README.md)，不重查已证manager/helper链，也不倒算进此前3234/381冻结代码轮。

## 同一对象与请求

```text
801317b0(controller,D)
  descriptor=D+8c
  801317d0 ->801324d4(controller,descriptor)  [original0 acquisition]
  acquisition成功后80131808 ->80131e74(controller,descriptor,D)

80131e74映射descriptor+10的handle为S
  80131f18 ->801338c4(controller,S,D,request)
    ->80133e3c ->80133ee0
  80131f44 ->801aa768(endpoint,0,8420,channel,80h,request)
```

主会话独立核原指令：80131f34装入**0x80（十进制128）**，存到stack+10；其语义未命名，不能从该常量认定字节长度。endpoint来自8000cc28(lhu[s3+2])，channel为lhu[s3]，具体recipient尚缺。

801aa768把8420写进queue头，copy的是24字节request descriptor；它保留nested handle、条件cache maintenance并signal。嵌套98字节工作记录含original0地址对，但尚未证明接收器将其当作输入、输出或in-place缓冲。

## 分配与几何字段

普通分支在80132ce8/80132940调用8005ef3c，并在S+478/+47c保存分开的original0 Y/C handle。u16[V+c4]/u16[V+cc]提供pool ID，pool属性helper8005e47c返回object u32+c、8005e504返回u16+10；分配count使用这些值做unsigned division。未证明这些字段是字节stride。

V必须保持为mflo得到的未知结果：80132c2c和80132884在mtlo/mflo之间含word0222001c。当前普通MIPS32工具未解释其语义，不静默按MIPS64 DMULT、乘加或NOP处理，因此不认证`V=registry+channel*5c`。

地址仍为已证`S470=*Yhandle+u32[be000064]`、`S474=*Chandle+u32[be000064]`；另一支直接取channel esram_addr记录word0/2。80133f28/34读取这同一对值，80133f44/48写工作子record+0/+4；部分mode在80134470/74先加计算/ESRAM值，所以不能把base word通用地当最终byte pointer。

特定controller+1d==2、second-record分支且所选pool非零时，8013454c..598将`(((u16[S+4]+3)&~3)*u16[S+8])<<8`交给800667f8..800669d8。后者按mode跳表给出两个对齐数值，没有pixel-copy loop或像素缓冲解引用。数值输出不能作实际像素生产证据。

## 下一条必须证明的动作

当前最前缺口是**所选8420 recipient如何消费这份嵌套记录**。需要沿同一lease观察或静态闭合真正transfer source/destination、pitch/format寄存器或原VBB/ASIC格式合同。多一层handle复制或完成ACK不能解决它。

RC selector0 K2cff84→K2d8c60、SA1564e及parameter1054尚未与此S/lease建立正向同一数据连接；不能推断已经汇合，也不能断言仅硬件能够写入。stride、plane extent、packing、bit depth和ARM/QEMU physical translation都仍未知。

E1（成功acquisition才submit）→F1（同一original0工作）；E2（普通load/store）→F2（地址进入8420 nested record）；E3（仅descriptor copy/数值helper）→F3（未证明pixel action）。`actual_origin_pixels_consumed=false`、gap63、`capture_verified=false`。
