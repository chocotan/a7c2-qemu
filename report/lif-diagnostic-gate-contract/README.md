# LIF晚期异步调用的FIRSTBYTE门

找到实际对象构造零写以及受条件控制的写一，但仍不能证明138908调用时gate为零。因此不能把normal worker的局部六字段clear提升成已发布零快照。本次只读公开CP，不改运行时、不运行VM/网络或真实设备，不读private/full数据。

## 实际构造与写者

包装入口a5bc38在a5bc3c/40构造对象地址169ec58，a5bc46调用真正constructor **a59124**，随后登记a59555清理回调。a59130置r0=0，a59134执行**strh r0,[r4]**，清首字节及+1；a59136清+2，a59402清+77cb8。完整正常路径到a5947e返回，没有再次显式写首字节；嵌套构造的参数均为对象内部偏移。这支持独立的显式构造存储操作，不证明原构造已执行或之后没有启用历史。

启用函数a595d0先调用a595ee(obj)，读取a96d5c返回的u32[1107178]。仅mode==1时调用3e679c(obj)，然后a595e8/e a写首字节1。即使3e679c自身提前返回，后面的写一仍执行。

3e6850..3e6894的选择前缀为：

```c
if ((u8[0x1ac0354] & 1) != 0 &&
    u8[0x169e018] != 0 && obj[0x77cb8] == 0) {
    if (obj[0] == 0) sub_a595d0(obj);
} else {
    if (obj[0] != 0) obj[0] = 0;
}
sub_3e6ad4(obj);  /* subsequent history not closed here */
```

169e018由a4dfd4的实际base169df18+100读取；选择条件为**非零**。3e679c要求该字节恰好1，不能把它的更严格条件挪到启用store前。原字符串`ALH:lensAttach`与`ALH:updCamVD_S`只是名称锚点，不能据此将整个对象当成可默认关闭的debug功能。

## 被阻断的发布证明

1388fc/138904把r0设为169ec58，138908调用a59d78。其开头ldrb读取首字节，若零直接跳到a59e5e返回；非零路径在a59e42调用50ff1c，可进入原调度器。因此，只有该次读取的实际值已知零，才能排除这一次异步构造/发送。

当前u8[1ac0354] bit0的来源和值仍未知，u8[169e018]的实际配置也未闭合。mode=1不能证明禁用，因为启用store恰好要求mode1。global BSS clear不证明构造后时刻，profile字节0不等于上下文全零，未找到其他writer也不构成全程序缺失证明。

E1（实际constructor）→F1（返回边界的显式零store合同）；E2（启用/清除条件及读取helper）→F2（后续可能写一）；E3（精确调用和early return）→F3（调用时gate值仍缺）。[source-pins.json](source-pins.json)给出8窗口1450字节与完整原件身份。主会话独立读回窗口摘要；不新增ready、六状态发布或3003成功。

`gate_at_worker_call_known=false`、`published_zero_projection_verified=false`、`capture_verified=false`保持。
