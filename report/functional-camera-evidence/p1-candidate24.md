# 第二十四跑：4028 接管通过，4037 功能路径缺口成为新前沿

已独立审查并精确集成剩余六槽的七文件补丁，重建 preload、CPIO 和生产 RAM 卡 binding，宿主回归通过。实际 guest 保留一笔 4028 请求，同一原 AP 线程随后继续 409c、403d 和 4037；新的首个负 send 是 capture SID 的 type5/4037/16B，返回 -1020 后触发 Imaging3109。未进入 HUD、未发快门、未生成 JPEG 或写卡，mailbox/broker 尚未通过。

本轮范围为审查→集成→第二十四跑，没有继续委派或访问真实设备。使用 direct-bootin、虚拟 CP 与原 App32 输入诊断路线，不执行 Sony loader、WBI 恢复、原 CP RTOS 或完整冷启动。历史 HUD/Fsys 收据保持原结论，本轮不追认覆盖。

## 审查与集成

[独立审查](../../../../scratch/a7c2-cp-remainder-20261115-candidate1/main-independent-review-v1.md)未发现补丁必修项；两线程、两检查组重跑新增 75 与历史 134 场景，共 209 场景，另有 pytest 入口与 AArch64 共享库交叉编译，全部通过。开启严格 C11/Werror、ASan/UBSan。原候选首次编译失败和修正后的收据均保留，独立检查另立 `checks-independent-review1.json`。

直接核对三份 AP/CP 原字节证据窗口及合同中的 AP 指令字节，见[读回收据](../../../../scratch/a7c2-cp-remainder-integration-20261115/review-readback.json)。六个构造器的 x4/x5 为零，只证明不登记/等待同步回复；4028 gate、旧值、有符号增量和 u16 参数不被猜测。六槽只保留完整 wire 和所有权，handler/apply/completion 仍为零，每命令每进程只接收一次，没有退役 API。

集成目录为 [a7c2-cp-remainder-integration-20261115](../../../../scratch/a7c2-cp-remainder-integration-20261115/)。按冻结输入和七目标 before SHA 核对，保存恢复前像并完整 SHA 读回，先 `git apply --check` 再应用补丁，after SHA 全部匹配。修改仅涉及 CP background C/H、menu-observe 的一个目的 SID 条件、两份既有 fixture，新增 C fixture 与 Python 测试入口；产品其它既有修改保留。

沿原 `build-observers.sh → prepare-menu-initramfs.sh → production derive` 重建，真实只读 fsck 由已有恢复 owner 执行。CPIO 只有 `simulation/menu-observe.so` 内容变化，成员列表和 mode 全部保持一致；KO 内容未变。

| 产物 | SHA-256 / 身份 |
| --- | --- |
| preload | `4e67c1b190cbd0cb3de29008bf82b4c273aed2abb1937b28907ff045a191a6cc` |
| base CPIO | `0126f80fb72fd2f32a5155fabe1f30fd9adb4c109c2ce3055578a00a81a5209d` |
| binding | `derive-prod-8ae906975284b421` |
| derivation.json | `f3ce26e98996e8cabffa2561f9850ca742794aae13ffd086cf20d4f1ed5141ec` |
| RAM CPIO | `655fef6bc86b7c82910a7c3e8b609f10c019b1d00bf4ff2267ddce76325b4526` |
| KO | `b60437dbac70e287fc2a75d2e162578e71b011476f325dd3e89f7d7195d1ebc5` |

产品回归分两组、两线程：CP 为 **7 pytest 方法、100 subtests**；UDATE/Backup/BB 为 **6 方法、69 subtests**，另有 CP40b8 六场景及 BB0159 五场景，全部通过。新增 remainder pytest 方法内实际编译重放 75 场景。集成脚本预填的 logical_scenarios 字段不替代实际计数，不把不同层级简单相加。未改的 USB 重型回归未重复运行。七文件 `git diff --check` 通过。

## 实际 guest 的新前沿

运行目录为 [candidate24](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate24/)，原 run 为 `runtime/analysis/menu-runs/6051`。原日志与归档逐文件完整 SHA 一致；guest 的 preload/KO SHA 匹配新部署，1GiB 卡全卡 SHA 匹配生产 seed `71362dfd3446d9de01fc59f1614d1dd7944a88cae19f2d70261f16e41e7e7888`。

以下为原 console 按 LF 划分的物理行；[运行汇总](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate24/runtime-summary.json)和[前沿核验](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate24/frontier-readback.json)使用同一口径。

| 原 console 行 | 原事件 | 可支持的结论 |
| --- | --- | --- |
| 7317 | 403d lock=1，request_free_rc=0 | 既有 functional interlock 路径被实际消费 |
| 7325、7333 | 404e、4070 各一笔 pending | 旧保留槽仍工作，业务后端未完成 |
| 7337 | 4028/16B，wire=`05002840070000800000000000000000`，一笔 remainder pending | 新 4028 槽接管原请求；handler/apply/completion=0 |
| 7338–7341 | 同 tid387 sequence10/409c，request_free_rc=0 | AP 越过 4028 的同步发送边界 |
| 7342–7344 | 同 tid387 sequence11/403d，lock=0，request_free_rc=0 | 原 interlock 解锁路径保持 |
| 7345–7348 | sequence12/4037，目的90040193、源80020002，type5/16B，原 send rc=-1020 | 首个观测负 send 前移至 4037 |
| 7349–7352 | ASSERT_CALLER、lib_assert.cpp:46、Imaging3109 | Imaging3109 仍复现，触发命令已由 4028 变为 4037 |

4028 的 rc0 由已部署源码的 result=0、真实 pending、同一原 AP 发送线程继续 sequence10/11/12 共同支持。旁路 send-trace 只打印委派给底层的发送，被模型直接接管的 4028 没有独立 `P18_OSAL_RESULT/4028/rc0` 行，不虚构这一层证据。

其余五个新槽 **4022/4023/4077/4039/40a5 未在 guest 触发**，仍只有宿主覆盖；没有重复 4028 busy，也没有 remainder 提前 free。三条 Imaging commit=0、ENTER_REC_STILL=0，未完成首设/HUD；原按键工作流预置 37 步，但异常发生后未继续输入或强改状态，快门守卫没有通过。

BB 状态仍 partial：0118 在 7234 行 `pending_mask=3 request_retained=1 applied=0 completion=0`；0159 在 7264 行 `lower_pending=1 lower_sent=0`；0500 在 7284 行原 send rc0、7289 行 request 消费/free，`completion=0`。未捕获独立 0500_CONFIG 行，不推断 1500 或模式后端完成。

## 4037 已有实现为什么没有接住

运行后增加了[审查补充](../../../../scratch/a7c2-cp-remainder-20261115-candidate1/main-independent-review-runtime-addendum-v1.md)，澄清“已有专用接收器”只代表源码存在。`device-models/imaging-device.c:174` 的旧 `full_imaging_dispatch()` 确实包含 4037/still_unlock，但当前 analysis 范围内没有生产 C 调用者，只有测试调用。实际 `menu-observe.c:10552` 调用 `full_imaging_functional_dispatch()`，其过滤条件没有 4037；本轮 remainder 也按合同将它委派，最终落到底层无接收端，返回 -1020。

这是既有功能模型覆盖缺口，被本次 4028 成功接管暴露，不能判为新七文件补丁破坏专用路径。下一消费者应将适当的 4037 语义接入 **functional** 状态/guard/所有权及 focus-control 流程，并验证副作用及请求 free；不能简单启用旧私有状态分支、把 4037 加到永久保留表，或用零回复构造器推导业务无操作。0118/0159/0500 及六槽退休仍独立待实现。

## 生命周期、恢复与空间

QEMU pid2340020/starttime126698507 已退出，launcher2339981 不存在；原 run 无 socket/FIFO，`/proc/net/unix` 无该 run 引用。唯一 QMP quit ID `056583dadf366228e03d0b65d09a17be` 的原响应为同 ID 的 `return:{}`，完整 wire SHA 与退出收据一致；QEMU rc0、runner closed、租约保留至退出，无信号。driver rc2 保留业务失败。新部署、pending 与下一负 send 已完整取得，未进行无增益重试。

恢复前像保存在集成目录 `restore/`，目录0700、文件0600，manifest 保存原路径、原 mode 与完整 SHA。无活消费者后可恢复五个修改目标、移除两个新增测试，或恢复原 preload/CPIO 及构建收据；也可沿原构建链重建。尚未执行回退。

四个主目录的逐文件 `st_blocks` 采样新增/保留量 **3,015,835,648 B**，实际回收 **0 B**；可用 **1,935,184,322,560 B**，保留64GiB余量。此口径含恢复前像和当前 derive，reflink 共享区可能重复计数，不等同底层独占新增。集成前可用1,938,172,719,104 B，文件系统净变化单独记账，不当成回收。后续小脚本、报告和独立审查重跑文件另入补充账本，采样不递归计账本自身。**未执行回收**；当前 binding、恢复前像、唯一失败与检查重放品保留供父会话核收，下一消费者与可判定回收条件写入各 storage.json。
