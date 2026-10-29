# 原boot仍在执行：当前3007背景状态转换依赖

**恢复尚未完成。** 本报告把取消队列积压接到同run的原boot等待，而不是用空回复结束等待。仅官方2.01 ALLLANG及隔离QEMU，无真机/物理SD/真实无线。

## 同run证据

`b07f3705a/run-nvmhrunq`使用已绑定UI pid217的全部task采栈，先通过76项host测试、2项subtest与独立QMP fixture。原AP SHA256 `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`，本run appFw bias=`7f26b7f000`、libObj bias=`7f66197000`。

| 实际线程 | 原帧/字段 | 仅据此成立的结论 |
| --- | --- | --- |
| AppFw302 | `1799a48`输入接收循环 | UI线程空闲，不是所有线程均无future等待 |
| SeqQueueCommon340 | `310194c←34f4f74←3535b04←3548cbc←34d1774←305eb88←3209e48` | group0 worker已进入原sequence_boot并等待成像接口 |
| CameraBackgroun275 | libObj `eda8c←ee460←ee82c` | 原背景线程在原动态回复等待路径 |
| IWrapperImaging312 | `3531540`接收等待 | 对应接收线程存在；不算收到快照 |
| SeqQueueStillCa342 | `34ae0cc←3209e48`，原双读helper：initialized0、initial_arrived0、slot0/1与completion均0、predicate0 | 另一组等待初始输入；不能由此制造完成位 |
| SeqQueueDispSwi356 / ZoomDri361 | 经`3535a5c`接口锁路径 | 不把互斥等待当作已完成曝光/显示配置 |

同run的原尝试发送日志：

```text
Common340 → 8102021f，source80020002，20B
1000000020000000000000000000000000000000

CameraBackground275 → 90030001，source810261c7，24B
000007300000000000000000000000000000000000000000
```

这与既有[AP背景接口依赖](post-boot-common-static/DEPENDENCY.md)和[原CP3007契约](post-boot-common-static/CP-3007.md)一致。本次日志、栈和bias重新绑定本run，没有复用旧328/287 tid，也不把send尝试当CP模块已消费。

前一`run-uok1g6m6`在原组锁借用点已经读到group0 active对象RTTI为`sequence_boot`、ID2a，pending队头为`sequence_set_release_lock`、ID132，count254；取消S位于后续队列。真实consumer `3209d48`在虚run返回后才删除/清active并取下项，因此不能以UI消息循环空闲、worker不存在或门控关闭解释本次取消未运行。当前等待位于最初boot future完成之后的背景收尾调用；不是重新清firstboot/error标志的理由。

## 有限虚拟接口实施边界

原CP SHA256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。main重新核原件及描述/序列，cold路径为0→57→0；原两段模块序列均非空（数字十六进制）：

```text
0→57: 0100 0200 0300 0400 0500 0600 0700 0900 0a00 0b01 0c06 0d00 8000 0108 8001
57→0: 0100 0200 0300 0400 0500 0600 0700 0900 0a00 0b01 0d00 8000
```

描述RAW c8ec20/c8ec30分别指CPVA ed875c/ed99d4，项数15/12；原路径数据CPVA eda43e为`020057000000`。冷复位早期current可为0，不代表请求当时仍0，不能每次重置或人为置6/7走捷径。requested/returned相等只是sequencer条件，不是实际模块副作用完成证据。

后续已核槽0为本地持久结构投递，无独立IPC包。原0108的实际完成分支等待SyncResMgr资源引用/backing，跳过SGC1；另一只接受0112的谓词不适用于本请求。共同准备与backing实际消费者仍未全部闭合，见[可执行原件核验与当前边界](cp-background-contract/README.md)。必须保留generation/pending和原消息owner/free，实际转换完成后才能给原3007成功f000；AP共享分支可接受f001/f002不代表本命令可伪造这些结果。有限`imaging-device.c`只覆盖90040193部分接口，不能冒充90030001背景服务。没有裸写S/D/BKP、清队列/改锁或直接调用原run/init。

## 验收边界

本轮SD独立SHA256 `b90051e5d9b0bd22d16f4c65572518de41b8ebd5f511f9f83e7890146861bad6`与export相符，fsck0、原owner resumed；这不代表成像。晚期LCD仍黑，系统恢复、虚拟CMOS/AF及原固件照片录像均未通过。原单帧、全线程栈和自动整体false proof保留在run，不回填旧失败。
