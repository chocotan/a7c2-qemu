# M/C的新条件writer：来自16字节输入，不是初始化值

已正向找到可与M/C相交的一字节writer，尚无M/C初值或启动实际执行证据。**不新增InitScalar/default，不构造debug载荷，不选择索引或M=2来推进3003。** M/C仍unknown，原data0/4、capture=false。

只读公开CP原件，完整SHA/18090880B、4窗口442B在[source-pins.json](source-pins.json)。原worker提供3窗口378B；主会话补核原指针表64B。原CP未执行，无系统VM/网络/设备或private/full；source增量不回填3249/381冻结轮。

## 实际字节写入

完整叶函数a3c50e..a3c51a是4条指令/12B：

```text
a3c50e MOVW r2,830b
a3c512 MOVT r2,1b1
a3c516 STRB r1,[r2,r0]
a3c518 BX LR
```

实际目的为`1b1830b + full r0`，写low8(r1)，不是只因附近出现地址就推断pointee被写。index=2ch时覆盖M1b18337，index=4eh时覆盖C1b18359。这里只计算相交条件，没有生成任何该index/value输入。

## 已闭合的两个直接caller

3de7fc..3de8da完整222B，79条reachable指令/216B与6B TBB表，inline表排除为data。r4=1b16271，先比较16字节`[r4+8]`与10e3b80，61e53c返回0则直接退出；非零后61e60c更新cache。selector=u8[r4+8]，selector6分支到3de8ce，r0=u8[r4+9]、r1=u8[r4+a]，3de8d2调用该writer。此选定路径未见index range check。

所以完整局部predicate是caller被调用、compare非零、selector6、输入index满足目标等式。它没有给出输入record内容、首次writer时序或startup reachability。不能用“存在setter”代替当前值。

另一完整caller a3c6c2..a3c752共144B/54指令，显式indices仅0..5（含tail paths），其写范围1b1830b..1b18311不含M/C。这个caller的有限域不能推广给input-conditioned caller。

## 原输入记录的可写暴露

主会话从原pointer table实际读回16项：`10fedf0+4*d0 = 10ff130`开始64B，entries d0..df恰为1b16279..1b16288，即上述16B record。这里不是新猜出的event namespace；已有[release callback合同](../cp-release-callback-selection/README.md)固定了这张表的**registry type4**、registration131bd0→b22f1e(4,10fedf0,100h)及**adjustment request selector5**的b2491e。

旧合同还证明opFF会按所选pointee复制payload，且前有b25aa8、后有9944f6工作。此次只增加表中record暴露位置，不扩展整个handler准入或把它简化成copy+ACK；没有观察注册、调整请求、输入内容或后续sideeffects。registry type4、adjustment selector5与普通AP type5配置是不同编号域，不能把普通启动前缀当成执行过该debug写入。

## 搜索与当前边界

worker对region1b18000..1b18400得到578个paired MOVW/MOVT候选，其中261个在1b18300..1b18380。有限constant-alias跟踪在control transfer、IT或未知transform处停止；唯一额外immediate constant-overlap是已知C getter写。本次新增的正向事实是input-indexed a3c516，不是all-writer completeness，也不是“未找到其它writer所以零”。

E1（完整叶函数）→F1（精确width/address/value）；E2（两个完整CFG）→F2（分别input-conditioned与有限0..5）；E3（原pointer table/既有adjustment合同）→F3（可写输入来源域，实际交付仍缺）。更新字段必须等待实际有来源的输入与时序，不能由模板、BSS或外部debug能力合成M/C。该写入本身也未证明LIFworker publication、CP START业务或任何像素消费。
