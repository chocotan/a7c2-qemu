# 原CP的官方BK4输入承载

`virtual-official-cp-bk4-input-v1` 为显式、默认关闭的输入诊断。原CP `55dcc2` 将 `r0=0x04000000` 交给 `55df9c`，后者从 `base+0xc` 比较三个字节 `BK4`，再读取 `base+0x10` 的子系统数并建立6B索引表。该地址来自原代码，不来自tomco或本机新增参数。

官方ALLLANG PP文件的完整身份固定为2390264B / `3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47`。

| 选择 | 原文件切片 | 字节 | SHA256 |
| --- | --- | ---: | --- |
| rec0 | 0..ed000h | 970752 | a6d0b73062731fbec2c556509b70ac794a23b33c135f491fb2338e992702ec8b |
| ed000 | ed000h..2478f8h | 1419512 | a90b46ae1d0fa054daeba321c52dc9d44d6bf32ca6eefcd1efb84fab2116e977 |
| full | 0..2478f8h | 2390264 | 3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47 |

`run-native-cp.py --backup full` 为显式诊断选择，完整PP及其中两条BK4均校验SHA和头字段，未修改数据。完整PP隔离实验已观测到CP越过旧 `0xbe9a14` 停点，但随后在 `0x595cfc` 向 `0xf1388f4c` 写入时触发新异常；receiver尚未验证。实际loader选择、物理地址别名及硬件兼容性仍未知。

两记录的前20B相同，均有 `+0xc=BK4`、`+0x10=819`；首差在+0x14。因此初始签名/计数检查不能区分它们。选择 `ed000` 是本次功能仿真决定，**真实loader选记录和0x804000000↔0x04000000物理关系仍未证**。

`official-backup.py` 限制源文件类型、大小、完整SHA、切片完整SHA及原头字段，只返回原样字节。不会生成头、修补校验和、写BKUP握手、发送ACK、改tomco或混入设备私有setting。

```sh
python3 source/cp-boot/official-backup.py \
  --pp /path/to/CX89701_ALLLANG.bin --record ed000 \
  --out /path/to/new-record.bin
```

输出必须新建并全摘要读回。源PP保持只读；切片是一次诊断输入，不是新的发布资产，也不得放进公开仓库。

原CP观察器的显式选项为 `--official-cp-backup rec0|ed000`。启用时将当前诊断RAM backing由64MiB扩为128MiB，使用QEMU原loader把整记录装入0x04000000；这只是**本机功能RAM布局**，不宣称Sony CP物理总RAM或真实loader搬运过程。宿主切片只读绑定，guest中为可写RAM副本，没有持久NVRAM写入器。

继续原CP前必须跨GDB通道完整读回所有记录字节并比对SHA；窗口结束再次核原PP来源。此后guest可由原代码修改自己的临时副本，不会写回PP或真实设备。通用调试窗口仍保守限制在低64MiB；备份的越界预加载读回仅对固定已验证范围开放。

新增输入守卫测试与原CP观察器按两个worker验收；原CP实际消费、新首异常、双方QMP退出和剩余阻塞另立收据，不由头部检查或静态字节匹配推断完整启动通过。原GPIO通知切片、原失败收据和默认产品窗口保持各自原状态。
