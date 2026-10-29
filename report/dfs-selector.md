# UPM DFS：独立有状态的虚拟选择器

2026-10-25。公开 ALLLANG 2.01；本机隔离 QEMU。

已实现严格的虚拟选择器，不模拟 AVB/CPU 实际降频，不改变 QEMU 执行速率、
`arch_sys_counter` 或中断源频率。当前已完成主机单元、同一候选设备qtest与原固件联合运行的阶段验证，
三次原驱动形状的请求分别消费到目标6、0、6。未单独探测每笔原UPM返回或事件3，
不把选择器完成替代该层证据。拍照/录像仍未完成。

## 原因和观察边界

`runtime/analysis/menu-runs/run-4hvp1_ue` 已消费 TCIN，原mode2f/Still流程进入，
快门前出现两次CPU0的RCU stall，运行任务为pid197 `UPM_DFS`。
没有保留该线程现场PC，所以**未证明本轮停在某个精确DFS指令**。
同时存在VEF0149路径1请求；两者分别调查，不以时间相邻代替因果。

已确定的设备模型缺口是 `f1388f50..f1388f60` 在旧候选中落入普通RAM：
它会将驱动写入的101原样读回，永远不满足驱动的 `(value & 101)==1`。
现有PCI SCU/CCF窗口只到 `f1388380`，没有覆盖这组寄存器。
该缺口的静态证明不能回填成旧run的现场PC证明。

旧失败实例的原Fsys刷新/SD导出未完成。匿名overlay与宿主INPUT已保存为部分故障证据，
普通SIGINT退出后所有进程/双锁释放，没有SIGKILL；详见
[TCIN报告](tcin-inactive-config.md)。不能把它描述为已保存完整SD。

## 原始模块和软件合同

官方 `runtime/analysis/menu-root/usr/kmod/upm.ko` SHA256：
`a8b16e1484be48d32c4a401897d13378cf45e5ef6654ebdcfdef5fc593da32eb`。
下列地址为ET_REL `.text` 偏移。

- `222f0` 创建UPM_DFS，`22440` 重定位入口到 `226b0`，配置type4/priority6。
  原 `osal_utm.ko` 包装器将其设为SCHED_FIFO、优先级6。运行时policy未另行读取。
- 正常收包 `227d8` 本身阻塞；不是这个接收循环自发busy。
- `b250 → b018` 实现模式请求；循环调用schedule但未设置睡眠状态，
  FIFO任务仍runnable时不保证低优先级任务取得CPU。

| 步骤 | 原操作 | 原始锚点 |
|---|---|---|
| 初始化 | W32(f1388f54,101) | `aff4:61158e92 20208052 0127bef2 200000b9` |
| 准备本笔 | W32(f1388f50,101) | `b05c:e1158e92 20208052 0127bef2 200000b9` |
| 等旧事务 | R32(f1388f60).bit8必须为0 | `b07c:600240b9`，`b08c:60ff4737` |
| 锁存目标 | W32(f1388f5c,mode\|(arg1<<8)) | `b090:9422152a`、`b0a8:200000b9` |
| 触发消费 | W32(f1388f58,1) | `b0b0:e1148e92 20008052 0127bef2 200000b9` |
| 等本笔 | R32(f1388f50)&101必须为1 | `b114:a20240b9`，`b13c:0000140a1f04007161feff54` |
| 软件检查 | 整个CK_STATUS必须等于mode | `2358c:9f02136b` |

**准备写50时不能立即把CK_STATUS.bit8置忙**，原驱动紧接着要等它清零，
此时目标和trigger还没有提交。

正常状态机四个调用点 `239b0/23e20/24100/24250` 都传arg1=1。
公开seed模式表 `009200a4` 的前32项取值集合为0..6；模型只支持这个正常子集，
不继承调试入口的任意字节。原底层函数没有自己的范围检查。

slow→slow先提交mode0，读回0后再提交最终目标，是两个独立事务。
`23550` 若已读到目标，由原软件自己分派事件3 `DFS_EVENT_MODE_CHANGE_CMP`；
否则通过原定时服务00910040、参数50轮询，回调22da0再比较并发送同一事件。
无需合成DFS IRQ或直接投递原软件完成事件。

原字符串模式标签对应AVB/CPU比例：
0=(1,1)、1=(1/2,1)、2=(1,1/2)、3=(1/2,1/2)、
4=(1/4,1/2)、5=(1/2,1/4)、6=(1/4,1/4)。这只是原标签依据，
当前模型不执行这些真实频率变化。已查路径没有CPU/计时器重编程调用；
运行使用62.5MHz arch_sys_counter，但更广时钟消费者尚未穷尽。

## 实现和准入

权威源码均在 `report/virtual-pcidma/`：

- `hardware/dfs.{c,h}`：独立可测试的phase、目标锁存、事务generation和完成generation。
- `hardware/qemu_dfs.c`：独立SysBus设备 `a7c2-virtual-dfs-selector`，20B MMIO，虚拟timer。
- `hardware/virt-pcie-scu.inc`：只在显式 `QEMU_SONY_DFS_TEST=1` 时映射，优先级4；不改已有PHY门控。
- `stage_hardware.py`：将三个新源文件加入native和诊断候选的同一源码身份清单。

虚拟初态current_mode=0、触发后1000ns消费是明确的测试板策略，
不是硅片reset值或真实时序。54只接受精确101作为虚拟初始化；
其W1C/IRQ/reset别名等硅片语义未知，没有泛化这些含义。
54与58若读回则返回虚拟锁存值，未声称是原硬件的读值/自清除行为。

事务必须 `initialized → PREPARED → LATCHED → BUSY → COMPLETE`。
只有trigger1消费锁定目标，才安排timer；timer执行一次消费并发布
`request=1 / status=mode / completed_generation=current_generation`。
同值模式同样必须走新的一代，不能借用旧完成。非法宽度、对齐、参数、
顺序或busy内重写会锁存FAULT并取消timer；初始化写不能清故障，只有板级reset可重置。
不支持的访问拒绝，不伪装成原驱动已有的硬件错误码或超时协议。

`SONY_DFS_REQUEST / COMPLETE / REJECT` 日志记录目标、generation、读回、
`virtual_selector=1 clocks_changed=0`。设备层完成不是原UPM消费证明。
QOM `/machine/sony-dfs-test` 提供phase、current-mode、request-count、completion-count、faults只读属性。

自然profile另需显式 `A7C2_DFS_SELECTOR=virtual-selector-v1`，前置guarded Backup与
`A7C2_TCIN_DETECT=virtual-inactive-v1`。候选的所有模型/板级源码SHA必须与当前一致，
原e5候选不会因环境变量被误用作新增DFS候选。runtime manifest保留
`dfs_actual_clock_changes=false / dfs_silicon_timing_verified=false`。

## 验证状态

- 核心ASan/UBSan与10处原模块字节锚点：2 tests passed。
- 同加共同staging复制身份、防重复、先delta后插入检查：5 tests passed。
- 相关TCIN/Backup/自然入口/导出保留回归：58 tests + 44 subtests passed。
- 独立审查未发现可证实代码问题；未因此提升设备或原驱动验收标志。
- 新native组合候选 `source/build/qemu-SRBXNK/build/qemu-system-aarch64`：
  SHA256 `a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02`，
  GTK/原生输入smoke/libfdt及源码身份构建检查通过；生产binary和e5对照未替换。
- DFS设备首轮 `/var/tmp/dfs-selector-qtest-rm4mkzps` 失败保留：qtest Machine用-S，
  测试未cont，QEMU_CLOCK_VIRTUAL被禁用。仅修正测试前置，未改模型或binary。
  正确运行 `/var/tmp/dfs-selector-qtest-ddb9obza` 全部通过：默认关闭、14次全模式/同值请求、
  两笔slow→slow、999+1ns边界、错误状态与reset取消。qtest vCPU不执行原固件。
- 同一a0d候选 `/var/tmp/backup-pci-qtest-fp9j_kcq` 通过guarded全长/ATU/GIC/错误回归；
  `runtime/analysis/menu-runs/directory-device-ialqjlxp/proof.json` 重验256GB几何、边界、
  实际host写回/flush/clean commit与owned退出。未借用旧binary的目录SD结果。
- `dfs-pre-native-checks.json` 另核生产e235、旧候选e5摘要未变，新a0d设备收据一致、
  无QEMU且全局锁可独占。

### 原固件联合运行 run-glsda8ag

同一a0d候选、新目录卡、公开seed，显式DFS及TCIN profile身份已绑定。
原内核路径实际提交 `target=106/100/106`，generation=1/2/3，模型各消费一次，
读回request=1、CK_STATUS=6/0/6。全run未见DFS reject或先前RCU stall。
原中文HUD、四阶段自然快门和原Fsys数据库/XML导出完成；主会话已看原LCD，
中央场景仍黑。三文件全树字节/摘要与export一致，clean commit，
`dfs-cleanup-assessment.json`确认owned进程组/QEMU全退出、双锁可独占，未用SIGKILL。

这支持新增选择器解决了本次可复现的调度饥饿并恢复运行，但旧故障现场精确PC
依旧未记录；本run也未逐笔直接观测原UPM函数return或event3退休，不补写该标志。

新的 `A7C2_EE_PASSIVE_ON_STILL_ENTRY=1` 在原Still入口出现后，仅取一次Common的
proc边界/栈；原有快门后采样仍独立。两次均为相同收包链：
`34e5788 ← 34e6e58 ← 34c6d04 ← 339d59c ← 33aaa3c`，
原kernel为 `osal_rcv_msg_tmo`。EE enable/source/status=1/0/0，Backup pending=0。
这将下一等待收窄为 [VEF SetPath](vef-path-frontier.md)。

两份原group0记录保留available=false：旧collector未接受shell prompt前缀及
空current时的 `reads=4/8/4/8/-1/-1`。已按原observer逐字段含义修正准入，
保留关键group读取长度校验、AP界限与有界二次读回，并加回归；未给旧快照回填推断值。
最新观测相关17项回归通过；完整相关集在加入此修正前为62 tests + 44 subtests。

本run SD/export仍 `original_capture_verified=false`；没有JPEG/MP4。

原证据位于 `runtime/analysis/menu-runs/tcin-tests-20261025/`。
设备测试失败/通过、Backup及目录SD原始22份JSON/日志已gzip保存到
`runtime/analysis/menu-runs/dfs-device-evidence-20261025/`，`index.json`逐项列出源文件、
原始字节数和SHA256，全部解压读回校验通过（原始合计90,125,051B）。
不能把单元、设备状态或选择器成功提升为EE、CMOS、编码或JPEG/MP4写卡成功。
