# StillCa 初始等待：先核原通知，再判媒体阻塞

当前拍摄主界面仍未恢复。`run-oow6rsz4`的StillCa327栈停在`34ae0cc`，
只能证明在等待初始媒体条件，不能单凭栈认定必须增加虚拟磁盘或filesystem服务。
本调查不改固件状态、不制造媒体完成事件，只添加本机QEMU只读字段观察。

以下appFw地址均为ELF VA，样本SHA256为
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。

| 证据 | 结论 | 后续路径 |
|---|---|---|
| `34adfc8`锁O+2a0，`349d250`谓词；`34ae0c8`等CV O+430 | 初始snapshot到达和按状态条件化的mount completion是独立字段 | 读取O+427、O+428/42c及O+425/426，不凭线程名判断 |
| 旧controller退出slot+28；rep_boot=`205fcd0→25252d0→2525270→349ea18` | 正常离开rep_boot时产生初始媒体snapshot，可能仍在等Common boot完成 | 若initial_arrived0，先观察自然boot出口；不手调notify |
| `349ea18`仅O+3cc==0时保存slot states并置O+427、notify CV | 未接受初始snapshot与缺mount有不同含义 | 记录initialized，避免把生命周期不同阶段混在一起 |
| `34a8f18(O,index)`在同mutex及O+3cc==0时设置O+425/426 | mount completion到达不独立证明挂载成功；setter不检查包装函数第三参数 | 需要条件时分别核真实Fsys结果、事件和setter消费 |
| `3381eb8→337ac38`执行mount，`33820f8→24cb2d4`发01000146/147 | 真正mount涉及InfraMediaMount b08170及独立Fsys_Mount路径 | 只在初始状态1/2且对应completion0时继续该链 |

原谓词为：

```c
pass = initial_arrived
    && (!(slot0 == 1 || slot0 == 2) || completion0)
    && (!(slot1 == 1 || slot1 == 2) || completion1);
```

slot state0不要求对应mount完成位。通过后原线程在`34ae148`发送01000205，
然后置O+3cc=1。不能手写缺失位来代替这些原执行步骤。

## 只读字段快照

`MENU_QUEUE_STACKS=1`已有诊断对SeqQueueStillCa调用`menu-regs <tid> --stillca`。
采集器从该tid的maps读取appFw bias，要求连续匹配等待返回`34ae0cc`与run返回`3209e48`，
再从run_fp+70读取O、run_fp+80读取mutex指针。必须核mutex==O+2a0、vptr==B+5b47d38，
才使用`pread`读取O+3cc和O+425..42f。

两次原始读取必须一致，避免stdio缓存造成虚假的二次核对；这仍然不是跨线程原子快照，
日志明确`atomic_snapshot=0`。对象/栈不匹配、映射不可读或两次值不同均输出
`STILLCA_STATE_UNAVAILABLE`，不猜状态，不写回。原有ptrace采寄存器会短暂停线程，
detach之后的字段读取是只读诊断，不能由此宣称固件行为完全未受调度影响。

测试`stillca-state.c`/`test-stillca-state.c`已核正常字段读回、错误mutex、错误vtable、
零bias、非法frame和截断拒绝。

`run-v5hf37qm`已取得实际字段：StillCa327、O=`0x7f64171a80`、run_fp=`0x7f0f82b800`，
正确vptr及mutex交叉核通过，两次pread值一致：initialized0、initial_arrived0、
slot0/slot1均0、completion0/completion1均0、predicate0。选定cpio内helper SHA256为
`8aad45156c8557c37e74b8a0a35655a13842b5c83882e0d23aef9494cf8cc227`，
console SHA256=`ff9a6215a879910b278c27803420950bb2241373e32c6a08db8a97b284103ecf`。
见`stillca-initial-native-proof.json`。该时刻缺已接受的初始snapshot，两slot状态均不要求挂载完成位；
不能据此新增虚拟存储来代替rep_boot的原通知。Common325仍停四任务完成join，UI287仍等boot future。

## 尚未证实

静态mount事件01000146/147到特定控制器回调2744dc4的完整活跃dispatch尚未闭合。
`run-oow6rsz4`已存在模型线程发出的01000004/01000002，不能继续沿用“没有媒体事件”的旧描述；
生产日志仍不证明UI消费或MediaConfig更新。当前没有新证据证明虚拟存储是紧接着的唯一阻塞。
