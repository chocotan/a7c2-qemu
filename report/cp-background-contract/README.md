# CP3007：slot0当前实施边界

`verify.py`用纯stdlib只读原CP，拒绝未知尺寸/摘要，核cold模块序列、完整u16身份、局部参数、TBH实际分支及SyncResMgr资源表。默认原件位置为本成果`runtime/analysis/menu-root/cp/cpapp-b.bin`，也可用`--cp`指定同一支持原件。不执行固件，不写其RAM/文件，不生成成功回复。

```sh
python3 report/cp-background-contract/verify.py
```

当前闭合部分：

- descriptor高字节h对应slot h−1，0108比较完整u16，不截成8；8001只比较slot0。
- 0100/0108解码为原局部12B参数，借用CP root持久结构，无独立IPC包。
- `b28b6c`只可能对0112返回1，不能作为0108/0100完成来源。
- `4bf4c0`的TBH中0108→`4bf846`→`b2741e`，其非零才选择请求值；失败保留旧completion。0100也必须先通过共同准备条件，不能直接回显。
- `b2741e`检查CPVA1a539a8的72条、stride40(hex)，跳过0c(SGC1)；其它条目u16+0及u8+5均须零。名字表为e79c90，含HEAD/DEV/图像处理中间资源及IIB别名。
- 错误字符串`FW: SyncResMgr::Free: %s acquireId:%d line:%d err:0x%02x`将其确认为资源管理，不是泛化ready位。原`4bbc18`释放路径在检查引用/force、资源专用清理、同acquireId别名匹配与相关buffer释放之后，才清backing标志等字段。不能强行清表来使idle条件通过。

## 有限冷态的共同准备

后续静态调查已闭合针对0100/0108参数的有限路径：`C+b9e&7=2`经`4e3edc`映射0，选中`b09436`，它查询原同步模式word是否0；word1 bit3=0自然跳过另一谓词。`C+88==0`时的`4bf3dc/4bf27c`是恢复检查，不设置这个字段；DEV_LV/DEV_0/DEV_1实际backing为空时自然早退。活跃资源分支仍有原事件旗标轮询、丢失检测/恢复、SyncFree及计数副作用，不能空实现。共同入口还消费一次性latch及deferred回调列表；真实非空列表必须执行回调、相关对象释放和节点归池，不能直接清空。

这只支持基于实际资源、同步模式和待办状态的冷态实施，不证明当前guest满足这些条件。原完整准备分支与其它模块操作仍需各自消费者；资源名称不是72种已完成的模拟器。

## 新增有限资源backing

权威源码为`runtime/analysis/device-models/cp-sync-resources.c/.h`；`runtime/analysis/test_cp_sync_resources.py`编译并执行实际C生命周期测试，使用ASan/UBSan。这是新虚拟backing策略，**不是原Sony分配ABI，也尚未连接原CP3007消息consumer**。

- 分配实际有预算的字节内存；资源别名共享同一backing。检查过的lease执行复制读写，不暴露内部指针；成功额外acquire/alias后永久冻结该分配的写入，引用退到1或0再重开也不解除冻结，仅free后新分配恢复可写。
- reference release只退引用，不清backing。因此引用均退完但内存尚存时，原idle条件仍不成立。
- free必须同时匹配创建时的分配身份，且整个别名组引用均为0，才实际释放并解除关联。迟到free不能释放复用同一resource ID的新分配。
- lease在进程内跨bank唯一且不回绕复用；过期、跨bank、重复release、越界和容量耗尽拒绝。fork继承实例拒绝使用；销毁前调用方必须让并发调用静止。
- idle按原72项/SGC1例外计算；SGC1仍占用时idle可true，但destroy仍拒绝泄漏。它仅是0108的一个前提，不代表初始化、参数消费或拍摄成功。

资源库测试只用显式256B主机fixture，经别名读回逐字节比对；它不是CMOS数据，也不是原固件照片。后续命令级overlay已在原guest完成**3007有限控制消费与正确free**，见[传输验收范围](TRANSPORT.md)。其它非零模块0b01实际writer、0c06 mode3快照发布已收窄，见[有限模块合同](MODE3-MODULES.md)；未知硬件仍pending、不回填observed。后续3006与初始输入未恢复，整体仍黑屏，不把原控制成功推广为图像链ready。

```sh
cd runtime/analysis
python3 -m pytest test_cp_sync_resources.py -q
```

分配身份版本的门控`bfa531299`曾通过3项pytest（实际C ASan/UBSan及2项源码快照），C源SHA256为`665a412eeba1a35b7bbda1bea39fde3775b79942885649520dfdc2dd09259a17`。独立评审随后指出：额外lease发布、原持有者release后，剩余引用变1可能恢复写入；旧测试没有覆盖该场景，不能用旧通过结果否定此问题。当前已改为持久frozen标志，并补接收方改写/零引用重开均被拒绝、读回字节不变的实际C回归；新hash-bound host+源码快照+原固件libc交叉链接门控为`b2a6cdf06`，结果按该轮输出记录，不回填旧版本。`ba06e3357`还早于分配身份API；`b09f91525`只确认冻结修订前的AArch64原libc/pthread链接，无原件写入或guest运行。独立评审复核另记，不将host/链接通过推广到guest消息消费。

**当前永久冻结版本已验证**：`b2a6cdf06`为3 passed，含实际C ASan/UBSan及源码快照；同一组源在原固件libc/pthread/loader下完成AArch64 `-nostdlib -mno-outline-atomics --no-undefined`交叉链接，无额外atomic libcall。main重新hash当前源与产物，相符：C=`3631fd345cfd10b88b9d76ded3bb2a4294e595e83ed7dba3c1b78b51f2ca78ae`，ELF=`ac0fa3db59cc93443659eb0ee45e50ab64c6bebc0241d6a2be636ccc102718d2`。独立评审复核静态确认原P2已修，未见同类逃逸；并发交错、64位token耗尽和持锁fork没有动态验证（256句柄容量耗尽已有C用例）。这些证据只覆盖资源库；原guest消费者与拍摄仍未通过。

交叉链接可在本成果根目录复现，仅输出到自己创建的临时目录：

```sh
out=$(mktemp -d)
lib=runtime/analysis/menu-root/lib
clang --target=aarch64-linux-gnu -fuse-ld=lld -nostdlib -O2 \
  -mno-outline-atomics -fPIC -shared -Wl,--no-undefined \
  -isystem /usr/aarch64-linux-gnu/include \
  runtime/analysis/device-models/cp-sync-resources.c \
  "$lib/libc-2.25.so" "$lib/libpthread-2.25.so" "$lib/ld-2.25.so" \
  -o "$out/cp-sync-resources.so"
readelf -h -Ws -d "$out/cp-sync-resources.so"
```

最终事件链及新增有限引擎见[控制完成判据](COMPLETION.md)：原event304没有generation字段，未选模块的旧returned不追加阻塞；启动/prepare/owner生命周期仍必须保留。新引擎尚无AP成功回复与原消费者注册。

后续实验transport/hook、原AP两池所有权及host-only验证见[消息链接入边界](TRANSPORT.md)。实验开关默认关闭，未知原observer未作为no-op验收；完整编译/私有guest证据另记。

`verify.py`输出的`verified`只证明离线原件合同，runtime恢复/成功后端字段仍为false；它的共同准备字段保留为全路径尚未闭合，而非否定上述有限冷态路径。

原boot等待、同run线程及SD验收见[boot依赖报告](../boot-cp-background-blocker.md)。完整阶段转录保留在工作区`scratch/cp3007-cold-contract/`；该目录属于研究记录，不能替代本目录的可执行原件核验，也不随公开包包含固件本体。
