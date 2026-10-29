# TCIN 0429：未激活虚拟检测器的关闭配置

日期：2026-10-25。范围：公开 ALLLANG 2.01、隔离 native QEMU。

当前已完成原始合同分析、限定模型和主机测试，联合运行消费仍待验收。
`capture_verified=false`：尚无原固件 JPEG/MP4。启用检测、外部时间码信号、
活动 genlock 的停止都不在这个子集内。

## 为什么需要这个接口

`runtime/analysis/menu-runs/run-pxhs_10h/ee-post-shutter.json` 是自然快门后、
SD export quiesce 前的无暂停观测：group0 当前 `0x1b2`、stop=0、queued=46，
前后组字节一致。Common 的原内核栈在 `osal_rcv_msg_tmo`；用户栈候选含
`34e5788 ← 34ef634 ← 34c8884 ← 34b8b9c`。同期 Backup pending=0、EE=0。

这与原序列 `sequence_sys_set_timecode_set_tcin_accessory_connection_det`
及其实际 `200d:0429` 请求互相印证。快照是顺序读取、候选栈字扫描，
不是持锁的原子快照或完整 unwind；原始采集器的 `current_blocker_proven=false`
保留，没有回填成更强结论。运行已退出，owner/进程组、全局锁、目录租约和
全部三个 SD 文件的读回见同目录 `tcin-observation-cleanup-assessment.json`。

## 原始字节合同

CP `cpapp-b.bin` SHA256：
`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，
下表 CP 地址均为 VA，文件偏移为 `VA−0x108000`。
AP `appFw.so` SHA256：
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。

| 原始锚点 | 含义 |
|---|---|
| AP `34ef5cc → 34e552c` | 向 `92840747` 发 10B；期望 12B 回复；非零输入规范成 byte+8=1 |
| CP `d16ba0: 2904000013ac6900` | `0429 → Thumb 69ac12` 配置 handler |
| CP `69ac16: 027a`、`69ac24: c0f88c26` | 读请求 byte+8，写 accessor+68c，即 requested u32 `01ff3b54` |
| CP `1c5534: e702 → 1c5ab0: 8320` | 线协议 `0429 → 内部请求83`，传给 `92840748` |
| CP `1c182c: 4108 → 1c27b8: 1821` | 内部83选择 TC operation18 |
| CP `1d22c6: 40f22940`、`1d22ca: 0021` | 完成命令0429，原始状态0；经 `699556` 提交 |
| CP `1c5de4: 40f28220` | 完成编号282，最终调 `69dc40` 构造回复 |
| CP `69dc5e: 41f22940`、`69dc80: 0395` | 回复命令1429；保留传入状态 |
| CP `1d22da: 41f08061` | 提交完成之后才设置 pending `04000000` |
| CP `1d3454 / 1d3460 / 1d3462 / 1d3468` | worker复制 requested→applied `0178927c`，调 `6a008c`，再清 pending |
| AP `34ef634 → 34e349c` | 读取回复+8；raw0映射到API0 |

已测请求：`0d2029040a0001800000`。
该成功路径的精确回复：`0d2029140c00018000000000`。
回复1429/status0来自具体构造器和状态生产者，不是通用“命令加1000”推断。

`6a008c` 在 condition u32 `01789220==0` 且 applied不等于1时：
若 active byte `01acad0b==1`，先清它，再投递事件ef；随后清 connection byte
`012315b0`。**若 active 本来为0，关闭不需要新时间码样本或物理事件。**
原 condition 字段的含义、原 CP 的实时 condition/active 值尚未证明。

active=1 的额外路径到 `SequenceAsync_DisableExtTcGenlock` (`1abafc`)，
向 `92330662` 发送 `{0b,1}` 和 `{0d,context}`，每次都等回复并检查+4。
其消费者另行调查；仅清 active 字节不能证明完成停止。

原 CP 通过每命令 source FIFO 保留动态 caller；`1c78e0` 为它单独分配12B，
设置 source=`92840747` 后发送。原请求在入口解析/复制后释放；回复由 AP 的
scoped waiter 接收、复制、释放。不得把 caller 固定为某次运行的 `81cf61c4`。

## 实现的虚拟子集

权威代码：`runtime/analysis/device-models/tcin-device.{c,h}`，接入现有
`menu-observe.c` 用户态消息入口，未增加第二个 kernel public sender。
默认关闭，仅 `A7C2_TCIN_DETECT=virtual-inactive-v1` 显式开启，并要求
已验证的 guarded Backup 自然启动 profile。

这声明一个**自身 condition=0、active=0、connection=0 的未激活虚拟接口**，
不是推断原 CP 的开机值，不写原 CP RAM，也不修改 AP 的 EE 或其他 gate。
只消费匹配的10B关闭请求；启用、非布尔、保留字非零、尺寸/头不符、
非本地 caller、非inactive状态及不确定的所有权均不产生正常完成回复。
没有推测上述拒绝形态的原生错误状态，使用虚拟传输错误返回。

模型保存不可变请求快照；持锁更新 requested、pending、applied和connection，
读回检查后才允许单独的12B回复入队。原生成功是较早的接受状态，模型的
“应用后回复”是更严格的虚拟策略，二者在日志中明确分开：

1. `FULL_TCIN_REQUEST`：精确请求、动态 source、原请求指针。
2. `FULL_TCIN_APPLIED`：自身配置消费和读回，`original_cp_executed=0`。
3. `FULL_TCIN_REPLY_QUEUED`：独立回复和租约。
4. `FULL_TCIN_COMMIT`：原请求释放结果；仍标 `hardware_tcin_verified=0`、`capture_verified=0`。
5. `FULL_TCIN_REPLY_FREE`：原 waiter 的释放结果，错误会保留租约并锁存故障。

入队前失败保留 caller 对原请求的所有权；入队后原请求释放失败会保留指针，
返回0只表示已完成所有权转交，`clean_completion` 仍为0。发送失败不回滚已应用
的虚拟配置。未入队回复若清理失败，单独保存指针、动态owner和返回码，
不会被旧的已入队回复释放失败覆盖；恢复释放也不计作原 waiter 消费。

## 联合验收入口

先按 native 构建步骤得到包含 guarded Backup 的组合候选，保存其
`pci-hardware-build.json` 并核对 binary SHA；本次沿用的候选 SHA 为
`e5d8acdf8afcdeea74fa351ae87734d90e38a0e7e8d9963011f2ff390a04aeb3`。
不得覆盖已验收生产 binary。进入 `runtime/analysis/` 后，令 `build_stage`
指向本机相应组合候选目录，`card_dir` 指向本机实验目录中新建的空目录，再运行：

```sh
A7C2_BACKUP_SYNC=virtual-primary-v1 \
A7C2_BACKUP_BUILD="$build_stage" \
A7C2_CP_BACKGROUND=virtual-mode3-cold-v1 \
A7C2_UDATE_DISTRIBUTION=virtual-roundtrip-v1 \
A7C2_TOUCH_PANEL=virtual-config-v1 \
A7C2_TCIN_DETECT=virtual-inactive-v1 \
A7C2_EE_PASSIVE_SNAPSHOT=1 \
A7C2_EE_PASSIVE_AFTER_SHUTTER=1 \
A7C2_JPEG_REQUEST_TRACE=1 \
A7C2_NATURAL_START_TRACE=1 \
A7C2_INPUT_ROUTE_TRACE=1 A7C2_INPUT_ROUTE_DETAIL=flow \
A7C2_FSYS_ASYNC_OBSERVE=1 \
python3 -B check-natural-gtk-input.py --candidate-build "$build_stage" \
  --host-sd-dir "$card_dir" --new-ui --firstboot --simplified-chinese \
  --natural-shutter --export-sd
```

只允许一台 VM，使用现有全局锁及目录租约，不传物理盘/真实SD。完整首设只消费
公开 seed 衍生的实例；collector不得调用原setter或改EE。保留前后原LCD、manifest、
源代码身份、消息生命周期、`ee-post-shutter.json` 和 `SD/export.json`。
入队及虚拟配置日志必须与原 waiter 对同一指针/动态owner的成功释放对应，
随后检查原序列是否推进。退出后另核实进程组、双锁、目录全树摘要和clean commit。
任一模型回复成功都不足以验收 JPEG/MP4；仍需原固件实际生成、Fsys写入、宿主读回、独立解码。

## 已执行检查和边界

`runtime/analysis/menu-runs/tcin-tests-20261025/host-tests-reviewed.txt`：
**57 tests + 44 subtests passed**。包括17个 ASan/UBSan C 情形、20处原CP字节锚点、
默认关闭/错误组合拒绝，以及触屏、Backup、UDATE、晚期采样和导出保留回归。

独立首轮审查发现了清理失败指针可被覆盖、故障日志不完整两项问题，
已经拆分保留记录并补齐owner/返回码/指针日志，加入组合反例与恢复测试。
后续独立复核确认两项问题均已闭合；它另行运行全部17个 sanitizer 情形，
以及错误owner、重复清理失败、恢复后仍保持故障锁存的附加反例，全部通过。
原固件 ABI 的 `build-observers.sh` 已成功，原日志保存在同证据目录
`observer-build.txt`；其中现有 helper 的 `fopen/fread` 声明警告保留，构建退出0。
TCIN 联合运行 `run-4hvp1_ue` 已确认原 AP 消费，后述整体启动验收失败不覆盖这项阶段证据。

### 联合运行：TCIN 消费通过，整体 GUI/SD 验收失败

本轮同一 `e5d8acdf…` 候选、全新256GB目录卡、公开种子，manifest身份链一致。
`FULL_TCIN_REQUEST → APPLIED → REPLY_QUEUED → COMMIT → REPLY_FREE` 各一次，
原 Common tid381 使用动态 `81cf61c4`，原请求与新回复是不同指针，
`request_free_rc=0 / clean_completion=1 / reply free rc=0`，没有TCIN fault。
随后 `MODE_SCHEDULE` 读到group0空闲（current=`ffffffff`、queued=0），
原 worker执行 `2f`，出现 `MODE_TRANSITION` 和 `ENTER_REC_STILL` 各一次。
这已证明越过此前TCIN队列占用，但没有证明EE开始输出图像。

Still入口在成功HDMI0117/free后，发出 `200d:0149`：
`0d2049010a0001800100`。原 AP `34e6d84` 的调试名为
`infra_wrapper_bb::detail::vef_set_path`，payload是u16路径编号，**不是bool**；
本轮值1。它通过 `34e6e54 → 34e552c` 期望12B回复。CP进一步映射到
`VEF::PathProcessNoMem`，必须完成具体路径切换，不能只保存配置后回成功。
本轮尚未取得Common的晚期栈，故只保留实际请求及静态依赖证据。

测试在教程末页后、快门提交前超时；最后原LCD仍是触摸滑动教程。
内核两次RCU stall均显示CPU0运行 `UPM_DFS`（pid197）；未记录该线程现场PC，
不能把已找到的DFS轮询缺口直接说成这次已经动态证实的精确PC。
SD有实际block writes与`commit pending`，宿主最终只有INPUT.BIN，
没有完整数据库/XML提交，更没有JPEG/MP4。原GTK proof仍为`ok=false`、
`automation_completed=false`，没有 `ee-post-shutter.json` 或自然快门提交收据。

宿主保留原QMP owner；额外只读QMP客户端未准入，fd复用也被系统权限拒绝，
未提权。核实前一精确完成标记后只发送一次`true`恢复探针，无返回；
没有清除desync latch或发送普通后续guest命令。

恢复时先持有匿名qcow overlay的原inode，保存退出前后各8,480,768B并读回相同SHA256：
`f90a8ce95adfae233497988928d3ba05a8fb5491484bc8d9f40c19e9cde8bd72`。
保存宿主INPUT前后副本，再仅用普通SIGINT让QEMU退出，随后正常关闭GTK/Xvfb。
这些是**部分故障证据**，不是可独立重建的完整SD快照；guest未刷缓存没有保存，
qcow只检查头部、没有结构验收。原Fsys flush与SD export均保持未通过。

- 阶段结果：`runtime/analysis/menu-runs/run-4hvp1_ue/tcin-stage-evaluation.json`。
- 部分写入：同run的 `retained-disk-evidence/preservation.json`，没有成功媒体声明。
- 资源收尾：`failed-instance-cleanup-assessment.json` 确认无owned进程组、无QEMU、
  双锁可独占；`resource_cleanup_complete=true` 只描述资源，SD导出仍false，未用SIGKILL。
- 下一并行工作：原UPM DFS请求/完成寄存器模型；原VEF路径1实际完成合同。

### 后续 genlock 只读调查

`92330662` 消费者已定位为 `22bda4 → 726aa0 → 22b310`；命令0b/0d分别到
`22b1a8 / 22b25c`，形成 backend operation `1400 / 1403`。
成功回复分别是8B `{8000000b,0}`、`{8000000d,0}`；非零backend结果分别映射1、2。
相邻注册0c使用operation1402，非零映射4。注意原 Disable发送`{0b,1}`，
Enable发送`{0b,0}`，不得按名称猜测极性。

工厂路径 `726e52 → 726d24` 的 singleton `01791edc` 初始化vptr为 `d4b800`，
slot `d4b81c:676d7200` 指向 `726d66`。完整检查该函数 `726d66..726dd8` 后，
它对1400..1404只读取 operation、发送结构化记录，再返回0；没有读取+4的
enable/context，也没有更新这两类状态。此结论仅限这条工厂选择及检查范围，
不宣称整份固件不存在其他实现或稍后的运行时替换。
因此服务 status0仍不能提升为有效停止/注册注销；当前子集不据此扩展支持范围。

condition `01789220` 的初始清零得到静态证据：`69f802 → 69f816` 清零
`01789214` 起20B，覆盖该字段。原始锚点 `69f84e:04f1a400`、
`69f882:1421`、`69f884:7ff73cea`，后者调用已核对的zero-fill `61ed00`。
其后续写入者、字段名称、运行时当前值仍未知。

目前不能从单元测试、成功回复或配置模型推导 EE、成像、编码或写卡完成。
下一验收是同一候选 QEMU、全新目录卡下的原 AP 回复消费、group0推进，
随后分别检查自然快门执行、图像数据、原编码/封装、Fsys文件内容及独立解码。
