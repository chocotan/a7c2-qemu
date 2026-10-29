# CP注册回调：共有前缀的有限核验

原11d7914表注册到1a7e968后，两个Thumb入口为bee174、bee17a。主会话继续追到共同入口56a994，实际执行`verify_registered_hook_prefix.py`通过：原CP SHA、262B有限代码、36条指令锚点和5条typed edges。只读原ALLLANG CP；没有执行guest回调或写CP状态。

两入口保持传入r0/r1，分别将r2设为0和1，然后tail至56a994。不是只有第一入口；两个入口也不是payload/source-length数据记录。

定义`A=传入r0`、`M=传入r1`、`H=M-40h`。56a994的已读前缀保存A/M/mode，拒绝M=0；bec28e读取u32[M-8]，若该值大于100000h则进入错误返回。这里确认的是**对象前面的原字段与实际比较值**，尚不能仅凭比较把它命名为备份长度或图像长度。

前缀逐字节构造little-endian字段：

|位置|写入值|
|---|---|
|H+00|M|
|H+04|0|
|H+08|u32[M-8]|
|H+0c|A|
|H+10|bec02a读取的u32[M-ch]|
|H+14|1|

它使用输入对象之前的64B区域；该64B不是backup payload长度。A的队列／目标／命令语义、两个metadata字段的生产者、mode的全程效果仍未知。共有函数后半段尚未在本次核验中覆盖，不能据此前缀认定传输完成、资源归还或04000000已有数据。

这将下一步范围收窄到：谁以什么A/M调用注册表、谁分配并写入M-8/M-ch，以及共有函数后续如何消费前缀。**CP启动备份数据的source、length、PCI目标域与Backup_init前的完成证据仍未闭合。** 不提升shadow bank，不据此ACK3006。

从本目录运行：

```bash
python3 -B verify_registered_hook_prefix.py
```

原件：cpapp-b.bin 18090880B，SHA `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，CPVA=raw+108000h。核验窗口为56a994..56aa76前缀、bee174..bee180两个完整小入口、bec28e..bec2a0及bec02a..bec030两个完整getter；不含共有函数后半段。
