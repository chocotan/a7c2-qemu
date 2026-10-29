# LIF gate清零后的完整返回条件

FLAGB=0只足以证明selector清零前缀，不能单独证明后继函数不调用其他逻辑。新增必要输入为Q=u8[1b18cd5]。若本次显式Q=0或9..255，完整后继路径保持首字节0并正常返回；Q的实际运行来源仍未知，因此不提升published zeros。

范围为公开CP只读静态核对；不运行VM、网络、硬件或物理SD，不使用private/full，不改变ready或3003准入。代码地址为CP VA，raw=VA-108000。

## 最小完整条件路径

令P=169ec58，外部串行化并提供可访问内存。在本次实际输入FLAGA=1、FLAGB=0、Q=0的条件下：

1. 3e6872因getter为0跳到清零分支；3e6892在P[0]非零时STRB零。
2. 3e6896无条件调用3e6ad4(P)。它先读取Q，不先检查P[0]。
3. Q不在1..8时进入default，只清Q并返回1。
4. selector重读P[0]==0，在3e68a4跳共享epilogue 3e6a94返回，跳过50ff1c。

该条件路径不消费P+77cb8、selector第二参数或mode，没有不透明调用。Q=9..255同样进入default；这是对显式输入的CFG结论，不证明原RAM中的Q已知0。

## 其他Q分支为何不能省略

| Q | 已闭合的直接分支或首个未知调用 |
|---|---|
| 1 | P+77cb8非零时return0并保留Q；否则3e6b16调用3e8aac(P)，后者调用3b6484/3b60b8，完整副作用未闭合 |
| 2 | G83或G84非零可避开调用；其他路径a4e2d4→3b6484/3b60b8 |
| 3 | a4e2f4只清G85，随后清Q |
| 4 | G84!=1或S==0可避开；其他路径9b71d4→510fdc |
| 5/6 | G85或G86非零可避开；其他路径a4e3e2→3b6484/3b60b8 |
| 7 | a4e408只清G83，随后清Q |
| 8 | G86!=1或S==0可避开；其他路径9b71d4→510fdc |

G83..87为1b18383..87，S为1abb653。这些直接store均不写P[0]，但未闭合helper不能因名称推成无副作用。

Q=1尤其容易误读：调用前写P+77cb8=1，调用后清固定全局对象的同一偏移。该地址是**1716910**，不是首字节；分支返回0使selector直接返回，也不会再重读P[0]。不能把该return0当作禁用完成证据。

## 原字节与剩余边界

3e6ad4无循环，default分类由跳表04191c1f22262a2d及无符号Q-1>7证明。selector实际50ff1c位于3e6a8a，最小条件路径在此前跳过。8窗口626字节见[source-pins.json](source-pins.json)，主会话独立重读摘要；全256个Q的default分类及Q3/7叶函数已静态核对。

E1（selector清零/重读/epilogue）→F1（FLAGB0的前缀效果）；E2（后继命令分支）→F2（Q为额外实际输入）；E3（Q1回调与偏移clear）→F3（未闭合路径不得当禁用）。selector与worker138908的先后关系及其间更新仍未知。

`source_gate_at_return_known_zero`仅对上述显式条件snapshot成立；`gate_at_worker_call_known=false`、`published_zero_projection_verified=false`、`capture_verified=false`保持。
