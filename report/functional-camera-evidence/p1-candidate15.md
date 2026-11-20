# P1 第十五跑：UIPC 公共池碎片化与远端消息所有权缺口

本轮只调查并运行原样模型，不修改产品、固件或 OSAL 池容量，不清 pending、不缩小 Backup 回复、不伪造成功。已确定原 UIPC 的公共变量池为 **512 KiB**，4096B Backup 回复在动态 source queue 路径实际需要 **4224B** 连续空间。实际池快照出现“总空闲 **116,288B**、最大连续空闲仅 **1,536B**”，证实本环境会发生阻止这类分配的碎片化。还确认产品公共 sender 对非 UDATE/Backup 的远端消息返回 0，却没有消费、保存或释放出口；三个相关队列的 outstanding allocation 持续增长。

**本轮没有重现第十四跑的同一 Backup 等待现场。** 同样的按键重放在不同调度时序下进入拍摄 HUD，`ENTER_REC_STILL`、Imaging 三连接的 commit 及原 AP reply-free 都已出现；三组 AP 样本的 pending 都为 0。随后发生 `infra_wrapper_imaging_ipsx_sp_pp_branch.cpp:3109` 断言，mailbox/debugger/broker 仍未接通，拍摄写卡未通过。因此碎片化是已实测的资源缺口，不能把本轮快照倒填为第十四跑等待时刻的池读回，也不能声称已修复该阻塞。

证据根：`scratch/a7c2-capture-p1-runtime-20261115-candidate15/`；实际运行材料在 `retry-1/`，原 run 为 `runtime/analysis/menu-runs/097e/`。核收入口为 `assessment.json`、`storage.json`、`module-provenance.json`、`pool-static.json`、`pool-analysis-4.json`。授权范围为隔离本机 QEMU 诊断，不接真实设备、不执行真实 CP，不进一步委派。

## 池身份、容量和等待语义

这里的 allocator 是 **原 `osal_uipc.ko`**，并非 QEMU 或 preload 里新造的消息池。原模块由既有驱动 `insmod /usr/kmod/osal_uipc.ko` 装载，无池容量覆盖参数。QEMU 提供 RAM，OSAL 在 guest 内实现池、消息队列、引用计数、分配和释放。

对所用 CPIO 逐成员哈希验证：`osal_uipc.ko` SHA256 `f0eb3a32a9d339066600e012aa3e91de31419c173e3fe5c1cc44aa9188763095`；`backup.ko` 为 `167715ebd8086b0751e95396ecc214c4d65ec54e11a9f2737a05664e03ad237b`；公共 sender 模块为 `1300b44c53834e1cbb9492e53641a894b42002a909231662792faa99b637b9b5`，与第十四跑相同。三者均与实际准入的 CPIO 成员相同，详见 `module-provenance.json`。所给 GPL 内核源码中未找到专有 OSAL 的 `vpool/msgq/kif` 实现，以下按原模块反汇编核定，不冒称已有对应源文件。

| 原模块位置 | 已核定语义 |
| --- | --- |
| `k_uipc_init@0x25f8`，`+0x4c` | 申请 order 9 的 2 MiB 消息共享区域 |
| `0x2704..0x2738` | 公共 `vpool` 初始化为 `0x80000` 字节；不是固定 4096B 块池 |
| `.bss+0x3cc0` | 公共 `vpool`，56B 结构；`+0x10` 空闲链，`+0x20` 容量，`+0x28` 等待链，`+0x30` 当前空闲，`+0x34` 最低空闲 |
| `.bss+0x98` 起 | 196 个专用变量池，共 883,200B；完整 queue-low→容量表见 `pool-static.json` |
| `osal_valloc_msg_wait@0x44c0` → helper `0x3248` | 检查 payload 不超过 4096B；根据目的队列属性决定专用池或公共池 |
| helper `0x34b8..0x34ec` | `0x803e....` 动态 source 回复路径将 4096 加 `0x83`，向下对齐至 64：`0x1080=4224B` |
| helper `0x32d8..0x32ec` | 公共 `vpool` 分配入口；第十四跑栈中的 `uipc_oom+0xa84` 对应这里的返回点 |
| `vpool_alloc@0x6998` | 空闲链寻找足够大的连续区，分割或摘除；没有合适区且 wait 非零则排入等待链并 `schedule`，不是按总空闲字节判断成功 |
| `vpool_free@0x6bb8` | 按地址插回、合并相邻空闲区、更新计数、唤醒等待者；不能移动仍被持有的裸指针来压紧空间 |

`vpool_dump` 的括号数字是“capacity−最低空闲”，即历史最高使用量，并非当前使用量。当前总空闲按完整 free-list 长度求和。解析器对每块的 64B 对齐、长度、顺序、无重叠和总量上界做 assert，传输 gzip CRC 及读回 SHA 均保留。

## 实际池读回与持有队列

使用原 `/proc/osal/uipc` 的前两次 read：第一阶段给 kernel global/pool，第二阶段给 global message queue 的首个 chunk。**在进入原 proc 的用户进程诊断 RPC 阶段前停止**，不向各 AP 线程发同步诊断请求。池清单完整；queue 清单只有 601 行，是受限子集，不能将其中 allocation 合计叫作全局消息总量。`/proc/kallsyms` 同时读出池符号；本机 guest 没有 `/proc/kcore` 或 `/dev/kmem`，没有尝试打开写内存通道。

| 重放动作后标签 | 当前总空闲 B | 最大连续空闲 B | 历史最高使用 B | AP pending |
| --- | ---: | ---: | ---: | ---: |
| `after-32` | 199,680 | 14,528 | 325,888 | 0 |
| `after-36` | 140,352 | 8,128 | 384,320 | 0 |
| `after-date`（实际为动作37后的旧标签） | 116,288 | 1,536 | 412,224 | 0 |

最后一组有约 113.6 KiB 空闲，却没有能容纳 4224B 的区块。**这是碎片化，不是公共池全部字节用完。** 旧标签 `after-date` 沿用重放脚本的采样名，本轮没有第二次 UDATE 完成，不能解释成“第二次日期确认后的同一事务”。动作32 LCD 为触控功能介绍，动作37原 LCD 为拍摄 HUD。调度和诊断耗时可能改变相同按键落到的页面；按键序列本身不能证明原首设语义完全相同。

三个主要远端 low queue 的 `A`（尚未最终释放的 allocation 个数）变化：

| queue low | 既有协议证据对应的远端目的 | 动作32 | 动作36 | 动作37 | 最后 M/C/S |
| --- | --- | ---: | ---: | ---: | --- |
| `0x8fc` | `0x92a208fc` | 205 | 229 | 235 | 0/0/0 |
| `0x83f` | `0x9092083f` | 192 | 208 | 212 | 0/0/0 |
| `0x86f` | `0x92b4086f` | 158 | 191 | 205 | 0/0/0，F=1 |

这些数是 outstanding 对象个数，不是分配累计次数或字节。M/C/S 为消息排队、callback、同步等待相关计数；这三个队列没有本地待取消息，却有大量 allocation 未被释放。目的 ID 的已有捕获证据见 [CP 捕获协议记录](../virtual-cp/CAPTURE-PROTOCOL.md)；本轮没有启用 capture sender 去逐笔记录全部消息，不能将旧捕获中的每条 payload 长度直接乘到本轮 allocation 上得到精确占用。

## 产品生命周期缺口与修复输入

[公共 sender](../virtual-cp/udate-distribution/client.c) 的 `udate_sender` 只分派 `BACKUP_TARGET` 和 `UDATE_TARGET1`。其他 qid 直接 `return 0`。同一实际模块 `.text+0x800..0x824` 已反汇编确认这个分支无 `osal_free_msg`、无 retained list、无转发处理。原 `osal_snd_msg@0x3d94` 调公共回调后，经 `0x3d98` 直接到返回出口，也不会隐式释放输入消息。这是具体的**非服务远端发送返回成功但所有权无人接管的产品缺口**，不只是“池可能太小”的猜测。

三个持续增长的队列恰好都不属于两个已服务目的，且对应原 sender 的无处理分支。当前证据链支持先处理这些远端消息的生命周期，再观察池能否恢复。尚未逐地址追踪每次原分配、发送、最终释放；未证明所有未释放对象都只由这一个分支产生，也未将第十四跑等待时刻的 pool 指针与该 free-list 做同现场绑定。

修复候选应先明确各目的的业务合同：`0x9092083f` 有设置 publication 证据，`0x92b4086f` 有 1504B 周期消息证据，`0x92a208fc` 有指针相关消息证据。必须验证输入、目标、源、payload 和所有权后执行对应的虚拟接收/更新/释放行为，并对未服务消息明确返回不可用或受管保留；不能把所有未知消息一概 `free + return 0` 当成已完成 CP 业务。改变默认返回码也需审原调用方的失败所有权，避免双重释放或让等待对端的调用永久卡住。

本轮**不建议**改大公共池或专用池来掩盖问题，不改变 Backup 的4096B回复，不预清 pending，不将普通 kmalloc 指针充当 OSAL message。若后续要给 Backup 预留回复或异步发送，仍需独立验证原 pool provenance、动态 source、type、冻结→DMA→解锁顺序、回复消费和所有失败出口。

早期 Backup stage3/0 本身没有已证泄漏：虚拟 endpoint 每次成功发送回复后释放原请求；原 `backup.ko` 通用同步 helper 在 `0x1520` 接收回复，于 `0x1568` 调 `osal_free_msg`，再于 `0x157c` 释放动态 queue。由于未逐笔插桩，本轮把“原代码存在正确释放出口”与“每个对象确实走过出口”分开记录。

## 运行结果、失败与覆盖

首轮在 QEMU 启动前因诊断脚本预建 `budget.json` 与 base driver 的 exclusive receipt 写入重名而失败，原 stderr/返回码保留。唯一重试 `097e` 使用相同产品、QEMU b369、同一 CPIO `75ba3158...`、同一环境，只改变 TMPDIR 和诊断采样。最初 `busybox head` applet 不存在，原始空输出和 stderr 保留；在第一次 passive sampler import 前加入上述 `dd` 读法，变更及前后脚本 SHA 见 `diagnostic-correction.json`。这不是修改 guest 产品。原来的无效 `pools-initial.txt` 不能当作池水位。

重试经过 guest 整卡 SHA 比对、原 Fsys A: 挂载；出现一次 `MODE_TRANSITION`、一次 `ENTER_REC_STILL`。三条 Imaging 连接各有一次 commit，且各有原 AP `REPLY_FREE`、`ap_consumed=1`、faults=0，不能再把这些记为 0/0/0。原 LCD 动作37为拍摄 HUD，完整帧和 OCR 已保留。

只有早期 generation1 的两条 Backup 回复和一次 UDATE done；三个样本 pending 均0，AppBackupDaemon 没有停在第十四跑的 `udate_sender+0x408`。延长窗口中原程序转入 `scr0039_shutdown`，随后报 `infra_wrapper_imaging_ipsx_sp_pp_branch.cpp:3109`，并经 `lib_assert.cpp:46 notify_model_system_error` 断言。现有证据不把此断言确定归因于池碎片化；要另外核对 shutdown 的首个触发源与该成像命令的服务合同。故障发生后驱动停止输入，未完成计划中的两组延长样本，不再重试。

QMP 采用现有 `menu_live.qmp_transaction` 的随机唯一请求 ID。完成 `quit`、QEMU rc0、租约保留到退出、runner closed，无信号；QEMU owner 已消失。宿主 driver rc2 和 FirmwareFault 保留，未改成业务成功。mailbox/debugger/broker 为 false；EE 字段、LCD/池读回为被动证据。真实 CP、物理成像、拍摄/写卡、Sony loader、完整冷/热/WBI 启动均未验收。

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| 原 CPIO 成员 SHA、`osal-uipc-disassembly.txt`、`pool-static.json` | 原公共变量池512KiB，动态回复连续空间4224B | 原 Backup→public callback→原 OSAL helper→公共 vpool |
| 三份 `uipc-kernel-*.txt`、传输原件、`pool-analysis-4.json` | 总空闲仍多，最大区从14528降到1536，发生真实碎片化 | 原 proc kernel pool dump→完整 free-list→对齐/无重叠核查 |
| 三队列 A 增长、实际 sender unknown branch、原 snd 返回出口 | 非服务远端消息返回0而无所有权接管，需修产品生命周期 | 原 AP/内核发送→sole sender 非服务分支→未释放对象 |
| 原 backup 接收/释放反汇编、早期两条回复 | 没有证据把早期 Backup 回复直接定成泄漏源 | stage3/0→原接收→原 free→queue释放 |
| 被动 pending/线程、原LCD、三连接 AP-free、末尾断言 | 本轮进入拍摄态但失败，未复现同一 Backup 阻塞 | 原输入→拍摄态→三连接消费→shutdown→原断言 |

## 验收、材料与下一消费者

`finalize.py` 用两组、两个线程分别核生命周期和业务/池证据；均通过。核对原日志与 `run-1-evidence` 复制件逐文件 SHA 相同，产品源码前后稳定；额外保留宿主 finalizer 首次语法错误及修正记录，未覆盖失败。`storage.json` 统计时新增保留实占 **94,081,024B**，实际回收 **0B，未执行回收**；项目文件系统可用 **1,961,723,863,040B**。统计为写账本及本文前的 st_blocks 合计，不声称 reflink 独占空间。

私有 profile 是恢复/身份依赖，保留为 blocked；原 run 的失活 socket 路径已记账，待父会话核收引用后处理。没有遗留运行 QEMU、未释放任务租约或本轮需要继续写入的虚拟盘。原故障、静态输入、CPIO 身份、逐项账本和诊断脚本的下一消费者是父会话的公共 sender 生命周期修复与恢复依赖审查，验收接管并核引用后方可归档/回收。

复现时使用全新任务目录，阅读 `prepare.py`、`prepare-retry.py`、`verify_runtime.py` 与 `passive_backup.py`；既有 exclusive receipt 目录不可直接覆盖重跑。解析已有证据可执行 `analyze_pools.py`，只会新增编号解析收据；`finalize.py` 的 exclusive 验收收据已经存在，不能无条件重复执行。下轮应以页面状态验证输入，而非仅沿用固定动作号；在第十四跑同一阻塞现场取 pool 及未释放消息身份，再对产品候选作集中验收。
