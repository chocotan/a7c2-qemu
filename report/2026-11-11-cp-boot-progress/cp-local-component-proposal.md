# 匿名 RAM 单 CP 组件机：可行性与精确阻塞

**状态：源码候选已交付，blocked-not-executed。没有修改产品，没有执行测试、QEMU、socket、flock 或设备操作。**

本次仅核对现有 stage 和 none machine，提出新的显式诊断 profile。现有板级结构支持不带 AP、native peer RAM 或 notify 的单 CP qtest 组件机；但旧 v8 的 secure GIC fixture 入口要求 native link，不能直接复用。候选通过独立、默认关闭的 profile 授权该 fixture，不改原 native guard、GIC 安全扩展、IRQ 接线或 SCU/I²C/DFS 模型。候选必须编译为新身份，不能声称仍为 v8。运行仍被持久 owner/父死亡/未知状态处理缺口阻塞。

## 交付源码

候选目录：`analysis/scratch/cp-wait-20261111/cp-local-component-candidate-v1/`。

- `cp-local-component-board.h`：新 profile 的板级准入守卫，严格校验 qtest、四核 A53、128 MiB 私有匿名 RAM 以及确切环境；拒绝 native link、notify、UIPC/EDMA/KEY/TIMERS 等额外硬件开关和已知共享内存对象。
- `stage_delta.py`：对固定 SHA 的当前 `stage-peripherals.py` 做纯文本变换，返回候选 stage，不写产品、不执行 stage。新增 header 纳入 FILES/source/output SHA；机器初始化在创建 CPU 前检查新 profile；secure GIC guard 接受原 native profile 或独立新 profile。`execute()` 无条件拒绝，参数不能解除。
- `test_stage_delta_draft.py`：未执行测试草案，检查 stage 可解析、原 INSERT 包括真实 IRQ 接线逐字保留、错 preimage 拒绝、启动硬门不可放行。不能代替 C 编译、QEMU 启动负例或设备断言验收。
- `seal_static.py`、`source-pins.json`、`SHA256SUMS`、`storage.json`：只做元数据、完整摘要读回和账本，不 import 候选，不运行测试。摘要清单不含自身；seal 输出给出清单和账本自身摘要。

本报告使用 docs-generator 的适用 Base 结构（flavor=null）。其 `../tool-index.md` 和 `../ops/evidence-finding-path.md` 在当前树缺失；没有安装依赖。任务范围来自本次委派及“优先交付单机方案/精确阻塞，不运行测试”。

## Evidence → finding → path

路径相对项目根；实读完整 SHA 在 source-pins.json。

| Evidence | Finding | Path |
| --- | --- | --- |
| `source/build/cp-native-batch-v8/tree/hw/core/null-machine.c:249`（前缀为 `final/a7c2-qemu/`） | 默认 RAM 映射在 0；只有启用 native link 才创建 peer view；notify 需要独立环境开关 | 单 CP 选 `none`，不设 native/notify/UIPC 开关，不传共享 RAM 对象 |
| 同树 `hw/core/machine.c:1024`、`:1612` 与 `include/system/hostmem.h` | 不传 mem-path 时默认 RAM backend 是匿名 `memory-backend-ram`，board init 前已消费 | 校验真实 backend 类型、share=false 和 128 MiB，不把 memfd/file backend 冒充匿名 RAM |
| `source/cp-boot/stage-peripherals.py:268` | secure GIC group fixture 的现有 board guard 强制 native link | 新显式 `virtual-cp-local-scu-i2c-dfs-component-v1` 独立准入；旧 profile 不变，缺 profile 不授权 |
| `source/cp-boot/component-gic-groups-qemu.c` | 只在 qtest 中对真实 GICD_IGROUPR 做 secure 32-bit访问，窗口 64 字节，不暴露 pending/IRQ | 文件内容保持；原 group 配置、非安全 RAZ 读回检查仍执行 |
| `source/cp-boot/scu-qemu.c:267` | realize 强制需要 5 I²C、2 PL330、2 PL080 router、6 TPU 和原 watchdog | 保留完整原 peripheral composition；不能以删除 link/空桩实现“只有五个设备” |
| `source/cp-boot/check-native-qemu.py:317`、`:342`、`:476` | 原 SCU/I²C/DFS 检查只消费 CP，但当前 selected run 仍创建 AP+CP 并准备共享文件 | 单 CP 新入口只能调用未修改的原 helper/用例；不能直接调用旧 `run(...only='scu_i2c')` |
| `source/cp-boot/native-qtest.py` | 旧 endpoint 强制三份 file RAM/native pair/notify；Python RETAINED 不是独立 owner | 需要独立单 CP admission/owner，不能把假的 pair 或 idle peer 塞回旧构造函数 |

## 确切机器与环境配方

这是供实现评审的参数集合，**不是可直接运行命令**。新 launcher 必须白名单固定 argv，拒绝额外 `-device loader`、`-object`、`-mem-path`、文件/物理盘、net、chardev 等；板级 guard 不声称可排除任意用户追加 QOM 设备。旧 launcher 的 admission 不能沿用。

- 机器：`-M none -m 128M -cpu cortex-a53 -smp 4 -accel qtest -S`。
- 隔离：`-nodefaults -display none -nic none -audio none -monitor none -serial none -sandbox on`。
- 不传 `-object memory-backend-file`、native memory-backend 机器参数、notify chardev、AP 启动参数或任何固件/磁盘。匿名 RAM 不能跨进程恢复，未知活 QEMU 仍要保全。
- QMP/qtest 仅使用 owner 专属 `/run/user/<uid>/<短目录>/` 下的 QEMU listener；证据、日志和 TMPDIR 留项目任务根。必须校验 UID、0700、目录/socket device/inode、长度与 SO_PEERCRED/PID/starttime/exe/pidfd，不能仅校验字符串。
- 只设置五个 hardware 环境值：`QEMU_CP_LOCAL_COMPONENT=virtual-cp-local-scu-i2c-dfs-component-v1`、`QEMU_CP_GIC=1`、`QEMU_CP_WATCHDOG=1`、`QEMU_CP_BOOT_PERIPHERALS=virtual-cp-boot-peripherals-v1`、`QEMU_NATIVE_COMPONENT_GIC_GROUPS=virtual-native-component-gic-groups-v1`。
- 不设 CP_TIMERS（所选用例不依赖）、EDMA_GATE、UIPC、native link、GPIO/KEY 或任何假 peer。保留 INSERT 内 SCU 强制依赖的真实 DMA、TPU、UART 设备；这些是 composition 依赖，本场景不宣称它们通过验收。严格“只存在 SCU/I²C/DFS/GIC/watchdog”的解释与当前 SCU realize 合同不兼容，不能靠偷偷放宽 realize 达成。

## 精确 stage 与 schema 改动

1. FILES 新增 `cp-local-component-board.h`；包含文件进入 `hw/misc/a7c2-cp/`、source SHA、output SHA 与编译依赖。header-only，不增加独立 meson TU。
2. null-machine 生成代码增加 include；`machine_none_init` 的 CPU 创建前调用 `cp_local_component_enabled(mch)`。profile 缺失返回 false，旧场景保持。
3. group fixture guard 从 `... || !native_link_enabled("cp")` 改为 `... || (!native_link_enabled("cp") && !cp_local_component_enabled(mch))`。fixture 自身仍强制 qtest，真实 GIC 安全扩展保持开启；不映射假 GIC、不设置虚构 pending。
4. 新 stage schema 暂用 `a7c2-cp-peripherals-stage-v7-cp-local-component-candidate-v1`，不接纳旧 v6 receipt 作为新构建。新增完整 `cp_local_component_contract` 对象，canonical JSON 比较保持 bool/int 区别。父 stage、基础源码和原有 source/output 校验不变。**主会话必须与 MTG/P1/owner 变更合成一个最终 schema，不能把并行候选互相覆盖。**
5. 新 build receipt 绑定实际新 stage 输出/源文件/工具链/二进制 SHA、profile、schema。旧 v8 SHA `b04d212b4f0295988238129e99e9a35d7e9665f60f0140a0cf5f963b75146553` 保持原身份；旧二进制不会接受新单机 profile。
6. 独立组件结果建议 `schema=a7c2-cp-local-component-result-v1`，`machine_profile` 为新 profile，`owners` 仅含 cp，`executed_checks=['scu_i2c']`。记录原用例/helper 整段 SHA、secure group 全部 16 words 与非 secure 读回、真实 NACK/IRQ/reset/gate/DFS 原始输出。`verified/current_full_batch/original_ap_consumption_verified/original_cp_consumption_verified/receiver_entry_observed/full_boot_verified/physical_compatible=false`；只有实际执行全部原断言、owner 正常退出且材料核收后，才可 `selected_checks_verified=true`。blocked 不能填空 owner 或伪造成功字段。

## 原断言保留与未覆盖事项

原 `scu_i2c`、`dfs_transactions`、`setup_irq`、`irq`、`clear_irq`、`rejected` 不删、不重写。保留 full32 latch、五 bank 的真实 I²C TYPE/enable/空总线 NACK/abort pending/clear/disable/reset/gate、两个 DFS target 的 busy/clock-step/completion/paused 回验。secure fixture 仍把 16 个真实 IGROUPR words 写/读回为 0xffffffff，非 secure view 必须 RAZ；不伪造 IRQ/ACK。

旧 v8 配对补验、旧失败和十组历史通过不能被新结果继承为“同一批全部通过”。新 stage 必须新构建、新 host gate、新组件运行收据；这不是 receiver、原 CP 指令执行、AP/CP 联动或完整启动证据。

## 运行仍被哪些缺口阻塞

- **持久 owner 与连续租约**：单 CP 消除了 AP/notify 双端生命周期依赖，但没有实现独立 keeper、出生前 handoff、活 QEMU 的不可提前释放租约及父死亡接管。不能把 `RETAINED=[]`、共享 OFD/LOCK_UN、fdset 或重取锁当作已证明的持续持有。
- **未知 cont/stop 状态**：原 `dfs_transactions` 在 `cont` 回包后才设置 running；请求已生效但回包丢失时可能不 stop。必须由同一代 QEMU 的独立可信 QMP 路径恢复暂停，或由 owner 保留未知现场并结束验收。不能为单 CP 放宽此边界或吞掉异常。
- **正常退出合同未实现**：仍需同代 peer 的 QMP quit 回复、host-qmp-quit SHUTDOWN、wait rc0 和 pidfd 退出证据。连接失败、超时、父死亡或不可读资源一律 blocked/retained，不发 signal、不解锁、不删 socket，不假写正常退出。
- **源码尚未编译/运行验证**：candidate header 与生成 stage 仅为审查稿；本次没执行候选、测试、编译或设备用例。新 profile 的正反准入和缺依赖启动错误还需主会话统一两线程验收。

## 材料与空间

只新增小型源码、摘要、文档和一次工具截断日志的保全副本。没有 RAM 文件、镜像、固件或构建产物；回收 0 字节，未执行回收。逐项逻辑长度、实占、SHA、保留原因、下一消费者、回收条件和文件系统可用字节见候选 `storage.json`。下一消费者为主会话静态审查与合批，不是 QEMU 执行器。

一次递归文件名搜索输出超限，工具自动产生 `/tmp/pi-bash-16251d61a21ac4a6.log`；它是本任务违规遗留项。保全副本为 `tool-output-retained.raw`，完整 SHA 读回；原文件活引用尚未核清，未删除，保持 blocked，不记路径合规通过。
