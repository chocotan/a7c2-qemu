# P1 第二十跑：402a/40af 已接收，下一拒绝为 BB042b

本轮完成16入口批量候选的独立审查、五文件精确集成、完整 guest 构建、CPIO/生产 derive 和宿主回归。两轮实际 guest 均观察到 `40b8 → 402a → 40af` 的参数接收及请求释放，上一轮402a拒绝后的Imaging3109未复现；接着 BB 端点 `0x92840747` 的 type13/`0x042b` 返回 `-1020`，触发原 `infra_wrapper_bb_ipsx_sp_pp_branch.cpp:949`。因此只证明前缀推进，不能声称Imaging、BB、首设或拍摄链已闭合。两轮未进入HUD、未发送快门、未出现mailbox，整体运行状态仍failed。

授权范围为父会话三段委托：审查→集成→第二十跑，一次诊断重试；未继续委派、未连接真实设备、未对QEMU发送信号。路线仍为既有direct-bootin/AP诊断，不是原Sony loader、整机冷启动、hotboot或WBI验收；未执行原CP固件。使用ponytail、ida-reverse与docs-generator证据要求，flavor=null；技能相邻tool-index/precedent缺失，现场使用已安装Capstone和原CP字节，不声称使用不存在的IDA工具。

## 审查与集成

[独立审查](../../../../scratch/a7c2-cp-opcode-batch-20261115-candidate1/main-independent-review-v1.md)未发现P1必修，不需要candidate2。重新读取原CP全SHA、参数表、handler/checker原字节和产品输入身份；[独立反汇编](../../../../scratch/a7c2-cp-opcode-batch-integration-20261115/independent-handler-readback.txt)核对4001混合宽度、401c有符号增量、409c字节回绕、4139的176B复制以及全部普通字段。原CP SHA256仍为`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。

仅按候选integration.json应用五文件：cp-background-device.c/.h、test_cp_40b8.c、新增test_cp_opcode_batch.c及test_cp_opcode_batch.py。`git apply --check -p3`及实际apply通过，逐文件SHA读回一致；其余冻结产品源码在收尾复核时保持不变，没有整目录覆盖现有集成。

同一PID/mutex owner保存参数与known位，相对更新不冒充绝对初值；共同APPLY只置pending，无ACK或硬件应用。release失败保留请求并锁定fault，未知命令仍委派/拒绝；3007、BB0118/0159及cp302c原边界不扩大。4022/4028门控未绑定，4023/404e/4070/4077异步合同仍明确延后。

恢复前像及原模式在[restore-manifest.json](../../../../scratch/a7c2-cp-opcode-batch-integration-20261115/restore-manifest.json)；恢复副本目录0700、文件0600，完整SHA读回见restore-protection-readback.json。回退时先验证前像、恢复本批三个原文件并移除本批两个新增测试，再按同一构建链重建preload/KO/CPIO/derive；禁止覆盖其它产品改动或只替换单个二进制。

## 构建与宿主验证

完整build-observers.sh重建preload及KO；KO内容未变。CPIO成员及权限不变，内容仅`simulation/menu-observe.so`改变。生产derive通过真实只读fsck和恢复owner协议。

| 产物 | SHA256 |
| --- | --- |
| preload | `294d6fd43a749f742963635bffdcef2ce60ec8ca8afcb35d7927291bdd777f75` |
| KO（未变） | `b4733732904b00641e7bef9900decffb090f5756389f977afe10ecd1c1ea21ab` |
| derive binding | `4d6bae0b3bad2252e0a11643c10fea71db6209f1477f105743ede00ed80be4c9` |
| RAM CPIO | `a9f90413b84d6790b9b56fe3b04dfb759351977cb7dce8c8d19968169cce5bd5` |
| QEMU（未变） | `b36998138a65b1bd2645ca24bf0dde0c0801d868d1291ec6f9e83ff707d64bad` |

当前binding为`runtime/analysis/functional-camera-profiles/derive-prod-26c3a0feae0734c3/derivation.json`。完整stdout/stderr/rc与构建读回位于[集成目录](../../../../scratch/a7c2-cp-opcode-batch-integration-20261115/)。

产品验收为2组/2线程：CP/history **4方法、100 subtest**通过，其中新入口fixture内部83场景；旧40b8另6场景通过。kernel **5方法、69 subtest**通过，0159另5场景通过。新fixture启用ASan/UBSan与NDEBUG，显式CHECK仍有效。既有USB runner另2组/2线程通过，原收据位于`analysis/scratch/cp-wait-20261111/usb-msc-host-batch-v4/run-4t3k6djk/`；这些host结果不替代guest、实际APPLY、原CP或拍摄验收。

## 实际运行与唯一重试

首轮run=`7515`，一次诊断重试run=`d2ea`；原现场分别位于`runtime/analysis/menu-runs/`。任务目录[首轮及重试证据](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate20/)保留driver rc、console、原输入、原帧导出、异常记录及全摘要归档。两个console与归档完整读回一致；guest实际输出的新preload/KO SHA和1GiB RAM卡SHA均匹配本轮生产输入。

重试仅提高dmesg console级别1→7，并纠正诊断grep的P18_OSAL_RESULT前缀；产品、binding、原App32路线和按键清单相同。首轮早期异常后输入停止；重试同样在首设动作前失败。无更多重试。

重试原console的关键证据（行号按原LF统计；JSON summary按规范化splitlines统计，保留源路径）：

| 原行 | 观察 | 结论 |
| --- | --- | --- |
| 5958 | 0118/22B source81cf618b send rc0 | 接收成立，非面板完成 |
| 5978 | BB_K_PANEL_PENDING generation1 selector3 pending_mask3 request_retained1 applied0 completion0 | 0118仍保留，LCD/EVF与1118后端未闭合；原行前有VmLck文本插入，未修改原日志 |
| 6014 | 40b8 generation1 value0 free_rc0 apply_pending1 | 原已有参数入口保持 |
| 6020 | 402a generation2 value0 free_rc0 apply_marked0 apply_pending1 | 上一轮拒绝已推进；不清先前dirty |
| 6032 | 40af generation3 value0 free_rc0 apply_pending1 | 本批第二个新入口实际到达 |
| 6050、6053–6054 | 0159原send rc0；lower_pending1 lower_sent0 applied0；CONSUMED command159 freed1 | 接收/释放保持，无VDF应用或完成 |
| 6118、6120 | BB_K_REJECT command42b caller_owns1；同tid395原send rc-1020 | 新首个发送缺口；完整wire=`0d202b040a0001800000` |
| 6336–6338 | notify_model_system_error；原bb:949 | 与新拒绝相接的异常链；Imaging3109本轮未复现 |

16入口中只有 **40b8、402a、40af三项**实际观察到接收与free_rc0；其余13项guest未到达，不能算运行覆盖。既有追踪器在模型已直接接收时不一定经过real-send符号，故summary的send_observed=false不等于拒绝，也不能虚构独立原send rc0；这里使用模型接管日志与精确源码返回合同证明有限接收。

两轮均无ENTER_REC_STILL、三Imaging连接commit、mailbox或4038；未发送快门，JPEG/写卡未验证。原UI导出未提供有效帧，不把创建widget或空导出记成可交互首设/HUD。

## 下一缺失合同

042b在BB目标，而非90030001/type5参数表。当前bb-receiver.c的bb_index只允许0142/015a/0160/0500/033b/0159，另有0118保留路径；042b因index<0返回-1020，请求仍归调用方。原请求为type13、10B、header200d/8001、payload u16=0；**其原CP消费者、字段含义、应用副作用、是否回包及释放生命周期尚未绑定**。下一批应先核对该BB命令的原件合同，再补接收/实际消费者；不能套用16参数入口或generic ACK。

4023/404e/4070等延后合同本轮未执行到。原共同APPLY、0118面板应用/1118、0159 VDF0302与014c布局实际应用仍需各自验收。042b解除后才有依据推进首设、HUD、快门和写卡。

| Evidence | Finding | Path |
| --- | --- | --- |
| 原CP全SHA/表/独立反汇编+五文件读回 | 16个有限参数入口与原字段操作一致 | 原字节→限定owner→产品构建/derive→guest身份读回 |
| 两轮40b8/402a/40af接收free_rc0，pending未伪造完成 | 402a前缀确实推进，但只有3入口运行覆盖 | 原AP发送→虚拟owner接管→参数/pending→未来APPLY消费者 |
| BB042b内核拒绝+同tid原send -1020+bb949 | 新明确前沿在另一BB命令 | 原source→92840747/type13/042b→严格接收器拒绝→原错误处理 |
| 0118保留pending、0159 lower_sent0 | 既有完成边界保持 | 接收不等于实际应用/1118/VDF完成 |
| 两轮QMP quit/rc0、wait及租约退出收据 | 失败现场保留，未用信号结束VM | 停止输入→唯一QMP id→quit→wait→退租 |

## 资源与收尾

两轮driver因固件异常返回2，QEMU本身均quit/rc0，runner已关闭、租约保留到退出、无信号。异常后的串口边界未知，额外异常命令按原守卫拒绝，没有为了读取更多数据绕过边界。owner/残留资源读回及精确空间统计见本任务final-audit.json；原始逐项storage.json、finalize.json不回填。

封存核心输入与两轮现场时，本任务新增/保留实占约3,032,367,104B（约2.82GiB，含恢复前像、当前derive、原运行与证据归档；USB收据及尾部小收据另计）；实际回收0B，项目盘可用1,948,080,529,408B。文件系统净变化不记作回收。当前derive供下一轮消费者，前像供本次产品回退，原失败与host fixture供父会话核收；替代恢复点验证和证据接管后，按逐项引用核查决定回收。未执行文件回收，未访问真实设备。
