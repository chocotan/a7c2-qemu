# 录像异步消息：外层运输与API指针边界

原Infra消息经用户态封装、OSAL ioctl和内核队列后，内核只重定位外层消息指针，内部API指针仍保留。没有闭合把P+30指向的98字节复制成原K incoming+28内联参数的消费者操作。该结果不解除录像缺口16/32，native gap mask=63、capture=false。

本次只读公开ALLLANG I/F/O/U资产，不运行VM、网络或真实设备，不读取private/full。I为libInfraAvbbc，F为dataflowInfraFramework，O为libosal_uipc，U为osal_uipc.ko。完整身份和原窗口在[source-pins.json](source-pins.json)。

## 实际命令与目的地

ConvertCid(5)=2003写入P+0 u16；ConvertCmdMid(5,520)=0201写P+2 u16；P+4 u16=38。CID/MID不是队列目的地。原SetParameter根据u16[P+22]==1选择805720f9，否则805700f9；I b2390构造函数将第五参数存入执行对象+28，I b22b4从这里读取发送目的地。ConvertOsalSendQid为单条ret。

I b34f4位于SetParameter内部，读取API参数指针并调整部分API字段，不是把参数展开到内核消息的serializer。

## 实际复制与重定位

以下offset为十六进制。M表示OSAL分配的外层payload，A=u64[P+30]：

```text
F SetDataflowMsg: memcpy(envelope+18, P, 38)，总长50
F SendASync:     memcpy(M, envelope, 50)，于是u64[M+48]=A
O u_osal_snd_msg: D+0 u32=destination；D+8 u64=M
                 ioctl(fd,80000004,&D)
U dispatcher:    copy_from_user(kernel_stack,D,10)
                 op=command&7fffffff=4，调用table[4]
U handler:       delta=M-u64[process_context+30]，要求delta<=1fffff
                 M_kernel=delta+u64[G+40]
                 osal_snd_msg(destination,M_kernel)
```

G为模块.bss+50。这个handler不读M+48，不转换A，不复制A指向的98字节。U是relocatable ELF；原relocation将.data+610绑定到.text+4d8 dispatcher，.rodata+3c0的操作4绑定到.text+13c0。未应用relocation的文件零值不能当运行指针。

805720f9与805700f9均不进入destination&70000000非零的特殊间接回调。正常查队列使用低16位20f9/00f9，把M_kernel-18节点连到队列head/tail。节点和内部u64[M_kernel+48]保留，没有展开API参数。ioctl/入队状态不等于该指针已消费、编码或发布完成。

## 精确剩余交接

```text
kernel queue 00f9 / 20f9
payload=M_kernel；inline command=M_kernel+18，长度38
retained API pointer=M_kernel+48
    -> 未识别的消费者/专用展开器
    -> 尚缺从A读取98字节的实际操作
    -> K incoming+28的98字节内联体
```

MPR早期48字节请求如何形成Infra38字节command，在这次外层运输调查中未闭合；后续[包坐标核查](../native-video-packet-coordinates/README.md)已找到实际copy到CMD+8，并区分CMD+10原地址域与CMD+30用户映射域。它没有闭合kernel转换或最终inline身份。上层、内核两端布局对应见[共享字段合同](../native-video-shared-binding/README.md)，不能将该对应自动当作完整跨消息身份。

E1（实际浅copy和命令转换）→F1（内部指针被原样封装）；E2（ioctl与module handler）→F2（只重定位M）；E3（队列节点连入）→F3（API参数消费者仍缺）。10窗口共5536字节已从完整原件计算并由主会话独立读回，不是负向grep缺失推断。未继续展开UDIF公共入口或所有队列任务，不宣称原生产、lease或固件写卡完成。
