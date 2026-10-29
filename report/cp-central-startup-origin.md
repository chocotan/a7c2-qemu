# 中央 sequencer 初始化与启动来源

本次静态证据已闭合中央`current`的显式清零源边，以及执行`fff418`构造表项的真正ARM遍历函数。**清零后的内部start/commit历史尚未闭合，302c仍未完成。** 不从首次已知0推导本次请求前已到6或8。

仅使用公开ALLLANG CP原件：18,090,880B，SHA256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。文件映射区间为CPVA `[108000,1248b80)`；中央RAM `1a52ad4`不在其中。下述RAM结论来自真实映射和store指令，未对RAM地址做CPVA减108000的文件切片。20个窗口见[bytepins](cp-central-startup-origin-bytepins.json)，主会话已独立运行[验证器](verify_cp_central_startup.py)通过。

## 显式清零产生初始current0

源入口主核路径：`108000→108010→108048`检查`MPIDR&3==0`，经`108054→10806c→108398`。`1083bc`从128000复制17cB到108da0；描述块首项为ARM619ea0，`10875c`间接调用后进入`619ea0→619f40→60d324`。此前`1083a0→108974`有handoff字节等待；这里只证明到达调用时的行为，不声称本轮原CP已满足该等待。

描述块原始值和消费者：

| 描述位置 | 值 | 消费者 |
|---|---:|---|
| 128148 | 010e2000 | 10850c取物理偏移 |
| 12814c | 0097bf5c | 108510取长度 |
| 128150 | 0120a000 | 108514取虚拟基址 |
| 12816c | 00128000 | 1083c0取bootstrap物理基址 |

`108518..108520`调用108768，建立VA与PA均为`[120a000,1b85f5c)`的映射。`60d334..60d354`构造r0=`120a418`、r1=`97bb44`，调用61ed00；该ARM例程显式将填充值置零，通过STRD/STR/STRB循环清除`[120a418,1b85f5c)`。

区间完整覆盖中央current的四字节`[1a52ad4,1a52ad8)`。具体store也已定位：current相对clear起点为8486bc，所在128B迭代起点偏移848680；61ed70的`STRDGE r2,r3,[ip],#8`在该迭代ip=`1a52ad0`时，将r3中的零写到1a52ad4。因此可合法建立：

```text
source_initial_current_at_clear_return = 0
source_initialization_edge_known = true
```

这是显式写入的源码证据，范围仅限清零返回时点，不是BSS惯例，也不是post-constructor或302c前的实际RAM读回。该清零区间不自动覆盖其它模块的heap/bank；不能用它为其它未知buffer补零。

## 真正的构造表执行器

ARM60d220从`ffe444`取函数指针，经BLX调用，迭代至第一个0。数组有1111个非零项，第一个0在fff5a0；中央构造器表项fff418是零基index1013，指针b1f329指向Thumb b1f328。包括首个0的数组SHA为`82ca4bafcd65a0ab5932ca847eb55032e78cb324ab53f11ea36024b520ffd6c0`。

调用者属于已验证的USER_TSK_INIT分派链`634780→6347e8→634844`：表EB55C4的record0为`(flags0,argument0,function601c48,mode_maskffffffff,id_mask1)`。601c48进入601db8，601dcc恢复caller frame，601dd0跳到60d220。表的实际mode/ID gate仍未观测，不能用旧模型mode3代入。

正常主核路径在60d354清零，之后60d46c→5f6124进入kernel启动；USER_TSK_INIT中的构造遍历属于后续阶段。函数表顺序不证明内部异步任务完成顺序，前1013个构造器对中央状态的间接影响也未全部审计。

另一张`ffe434`数组只有`61057c,619ddc,0,0`，由60d398..60d3bc处理；它不会遍历到fff418，必须与ffe444数组分开。

## 内部3000/3003生产者

已发现CP内部调用`739a2a→739b98→4b28d8`。选择3000/3003的分支要求：`u16[input+26]==0`、`u8[1acbf74]==1`、`u16[input+24]`为0480或0404。随后739b52清该pending字节，读取`u32[17922b8]`：等于8选3000，否则选3003，r1=0后调用中央start。

pending/saved word的一个生产者位于同函数：739b7a设置pending=1，739b86调用b1f2b0读取`u32[1a52ae0]`，739b92存入17922b8，再以r0=r6调用start。保存的是中间字段1a52ae0，不能命名为global current 1a52ad4的快照。

一个具体上游是b23396：将输入150B复制到RAM1725870，b23400设置r0为该副本，b23408调用739a2a；另有739bea及b2407a调用。第一次输入记录、pending历史、具体执行时点和模块消费仍未闭合；不能把这个带条件分支当作自动开机转换。

已知静态中央路径为`0--3000→8`，或`0--3003→2--3007→6`；3011只经过0b后回2。正常start/commit仍必须实际完成选中模块和boundary的完整u16相等判据。

## 下一边与限制

最小残余边已具体化：

- 清零后60d370的SEV释放其它核，secondary路线进入614808；并发启动影响尚未关闭。
- 主核60d374→61ccbc后，61ccd2→61dbb8会调用613714、613728、61354c；首个尚未深入的callee为61dbbe→613714。
- 第一次内部start需要追b23396输入的生产者、739a2a的pending/saved-word历史；不能注入外部3000或直接设置current。
- 首次start后的真实module/boundary/commit仍为独立门槛。实际variant0只决定起态8时的descriptor，不生产state8。

混合ARM/Thumb立即数调用扫描定位到4b28d8的直接调用者47550e、739b98和b21718；没有更多ARM立即分支命中，也没有这些地址的原样四字节常量命中。此否定结果不能排除相对地址、包装器、间接计算或批量writer，不是唯一性证明。

```text
source_initial_current_at_clear_return = 0
constructor_executor_known = true
source_post_constructor_current = unknown
first_internal_start_history_complete = false
first_commit_history_complete = false
runtime_current_before_302c = unknown
302c_native_verified = false
capture_verified = false
```

本调查与主会话复核没有执行原CP代码、启动VM或接触真机。先前全部13图连接验收范围保持；当前没有新302c回复或拍摄成功声明。

从本成果目录运行只读复核：

```bash
python3 -B report/verify_cp_central_startup.py
```
