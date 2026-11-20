# 第二十二跑：404e 单笔接管后推进到4070拒绝，FC业务未完成

本轮独立审查并精确集成 CP 异步族五文件候选，完整重建 preload/CPIO/生产 RAM 卡 binding，宿主两组两线程回归通过。实际 guest 记录首笔404e pending，原 AP 随后继续4043、4070；4070原发送返回−1020并触发原Imaging3109。没有第二笔404e busy、没有FC完成等待现场，未进入HUD、未发快门、未生成JPEG或写卡。404e的gate/handler/内部0901/completion均仍为0。QEMU quit/rc0、无信号、租约保留到退出；本轮业务状态为失败，不能记shooting-ready通过。

范围来自本轮审查→集成→第二十二跑委托；不再委派，不连接真实设备。沿用既有 direct-bootin、虚拟CP与原App32输入路线，没有执行原Sony loader、原物理CP或完整冷启动。本报告 flavor=null。已有更早P1/Fsys通过收据保持原结论，本轮没有复验或覆盖它们。

## 审查结论与原AP等待语义

独立审查报告：[main-independent-review-v1.md](../../../../scratch/a7c2-cp-async-family-20261115-candidate1/main-independent-review-v1.md)。无必修P1/P2，candidate1以诊断保留范围集成，无candidate2。

原AP独立原字节、全文件SHA及Capstone反汇编：[main-review-ap-pins-v2.json](../../../../scratch/a7c2-cp-async-family-20261115-candidate1/main-review-ap-pins-v2.json)、[main-review-ap-disassembly-v2.txt](../../../../scratch/a7c2-cp-async-family-20261115-candidate1/main-review-ap-disassembly-v2.txt)。appFw+3543288构造type5/404e/8B；35432c8/cc把x5/x4设零，35432dc调用35358b8。公共执行器以x22=x4，3535970跳过回复登记，3535af8跳过接收/复制/free。因此该404e发送不等直接AP完成回复，rc0后继续返回。反之发送非零会走3109断言。

候选只保存一笔request/source/8B wire与generation，rc0表示所有权交给pending；后续404e busy、继承PID、错误source/size、owner fault和意外free均拒绝。没有猜config gate、执行FC0901、释放pending或构造ACK。4023/4070/4077保留原委派，缺失后端精确记录。cp302c历史审计仍先于dispatch，未增加白名单。

重要证据边界：现有旁路send-trace只记录实际委派到下层的发送，没有单独打印被模型直接接管的404e返回值。本轮对404e rc0的验证是已部署代码/完整哈希、真实pending、同一AP线程继续4043/4070及原发送失败必断言路径的联合证据，不伪称存在独立P18_OSAL_RESULT/404e/rc0原日志。没有通过发空ACK补足这项日志。

## 集成和宿主验证

集成目录：[a7c2-cp-async-integration-20261115](../../../../scratch/a7c2-cp-async-integration-20261115/)。先对97个冻结输入核SHA，备份、读回并保存原mode，再git apply --check及最小五文件补丁；五文件集成后SHA逐项一致。没有复制候选整树或覆盖原有产品集成。

- 新preload SHA256：`a148bb0f9833d1ff785b8e7699513111a7bf3511e5b9c0a03656278201c40c0c`。
- 新基础CPIO SHA256：`8869efee21871b086121ae4b1abe735d67e5b74062654b8aa7404ad982b6c4c1`。
- 生产binding：`derive-prod-ed7c4e2ea5b871ac`，RAM CPIO SHA256 `bb977b349688e2592b5faee0524ab3b8fbb365bd741b09ad990f4f9069426db8`，1,492,640,296B。
- KO内容未变，SHA256 `b60437dbac70e287fc2a75d2e162578e71b011476f325dd3e89f7d7195d1ebc5`。

CPIO仅simulation/menu-observe.so内容变化，member set及mode完全保留。真实fsck经既有恢复owner协议执行，rc0、前后seed SHA一致，seed仍`71362dfd3446d9de01fc59f1614d1dd7944a88cae19f2d70261f16e41e7e7888`。见cpio-delta.json、source-readback.json、derive/derive-result.json。

产品宿主回归为两组、两线程：CP/history **5 pytest方法+100 subtests**；UDATE/Backup/BB **6方法+69 subtests**；另运行6个CP40b8与5个BB0159场景，均通过，ASan/UBSan开启。新增async的9场景在产品入口中实编译执行，包含fork、1600并发请求、busy、重入、free保护及无假完成。`product-regression.json`中120这一预填logical_scenarios字段不是权威计数；本报告仅引用原pytest输出与逐场景rc，不把不同层级计数相加作新功能通过。

另有既有USB宿主回归两组/两线程，22+78方法及39 subtests通过，输入源码稳定，原收据位于`analysis/scratch/cp-wait-20261111/usb-msc-host-batch-v4/run-zedo3b9f/`。没有新增USB VM。

## 实际运行结果

运行目录：[candidate22](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate22/)，原run为`runtime/analysis/menu-runs/bf42`。原console SHA256 `8140dcab0c3f402358fa2745ef199d5ed8d0defbcc8d5bee10cdd00bb8cd4a38`。归档逐文件与原run全SHA相同，guest读回preload/KO SHA与计划相符，全1GiB卡SHA在guest内匹配。QEMU b369身份符合accepted build，未新复制QEMU。

下列行号使用原文件以LF划分的物理行；runtime-summary的Python通用换行计数可能因串口CR产生不同数字，引用时以原文件为准。

| 原console物理行 | 实际事件 | 结论 |
| --- | --- | --- |
| 5628–5631 | sequence6/8B `05004e4004000080`，恰一条ASYNC_PENDING | 原404e被接管；handler/internal0901/apply/completion仍0 |
| 5632–5633 | 同tid371继续sequence7/4043 | AP跨过404e发送边界，没有在该处等完成 |
| 5636–5643 | sequence8/4070，缺worker+bracketing+AP1010，委派rc−1020，原12B `050070400600008000000000` | 当前首个真实新拒绝是4070，不是第二笔404e busy |
| 5657 | `infra_wrapper_imaging_ipsx_sp_pp_branch.cpp:3109` | Imaging3109仍复现，触发命令由404e变为4070 |
| 5513 | 0118 pending_mask3，request_retained1，applied/completion0 | LCD/EVF后端未完成，不能发1118 |
| 5549 | 0159参数7，lower0302记录但lower_sent0，pending1 | VDF0302下层尚未发送/应用 |
| 5580 | 0500参数1、原请求free，completion0 | 没有1500及模式后端完成；该行与AP日志串口交织 |

现有trace另记录0118/0159/042b/0500原send rc0，仍只证明传输/配置边界。404e pending只有一条，unsupported/free-refused为0；未观察到额外释放pending的证据，但没有在异常后强行读取该指针。4023/4077未在本次失败前获guest覆盖。三条Imaging commit均0，ENTER_REC_STILL未出现，mailbox/broker未接入，快门条件不成立，未执行快门。

初始OSAL池只读采样保存在pools-initial.txt及transport.raw，发生在404e之前。异常后串口边界未知，诊断器拒绝追加串口读写；不能把初始池快照当成404e后的生命周期读回。本次明确是4070发送拒绝，未捕获FC completion wait，因此没有伪造“FC精确等待PC”。

## 收尾、恢复与下一步

QEMU身份pid2290254/starttime126429501已退出，launcher2290224不存在，原run无socket/FIFO及/proc/net/unix残留。QMP quit使用唯一ID `619bc6fa8d8da9d8946e2453f2443e8f`，rc0、runner closed、lease到退出；driver rc2保存业务失败。没有发送任何信号。未重试：当前首个新拒绝与原断言已有足够证据，不为重复相同结果再启VM。

恢复前像在集成目录restore，逐文件全SHA回读，目录0700、文件0600，restore-manifest保留原路径/mode。回退应在无活消费者后恢复三个原有源码/fixture、移除两个新增测试，再沿相同构建链重建；若需要直接恢复本轮之前产物，manifest也保存旧preload、CPIO和构建收据。尚未执行回退。

当前四个主目录逐文件st_blocks合计新增/保留 **3,013,513,216B**，实际回收0B；可用 **1,941,573,869,568B**，满足64GiB余量。该值包含恢复前像和当前derive，reflink共享区可能重复计数，不能等同底层独占新增。另有USB合成回归目录及小型报告/脚本，最终补充账本单独列出。完整SHA、路径、owner、下一消费者与回收条件见各storage.json及final-audit.json。未执行回收；恢复前像、当前binding、原失败、检查重放品留给父会话核收，核收后按精确白名单和引用检查处理，不能凭目录名删除。

| Evidence | Finding | Path |
| --- | --- | --- |
| 原AP3543288构造器、35358b8条件分支 | 404e不等独立AP回复，rc0只让AP继续 | 单笔pending诊断→观测下一请求，不能计FC完成 |
| 部署SHA、5631 pending、5633后续4043 | 404e发送边界已推进，FC后端仍缺 | 权威config gate→FC0901→真实消费者及正确退役 |
| 5643原4070 rc−1020、5657原3109 | 当前业务阻塞为4070异步worker/bracketing族 | 精确worker状态、条件1010目的/消费/free合同；不得generic ACK |
| 0118/0159/0500原pending/partial行 | 显示/VDF/模式完成仍不成立 | 各自下层后端和原AP完成消费独立验收 |
| quit/rc0、SHA归档、无活owner/socket | 失败已保全且自有VM生命周期闭合 | 父会话核收→下一后端实现，保持旧失败记录 |
