# BB0145 接收已验证，第二十八跑的新前沿为 BB011b

第二十八跑实际跨过了上轮的0145入口：原AP发送24B请求返回0，guest中新BB worker完成一次真实free并提交generation1。随后同一AP线程发送BB011b/10B，被当前接收合同拒绝−1020，再触发原BB949。因此0145旧拒绝已消除，BB949整体尚未消除。未到首设按键阶段或拍摄HUD，Imaging三连接、mailbox、P3快门、JPEG与写卡均未通过。

0145仍是**接收、释放与VDF0312最新意图记录**，没有下层发送、显示应用、通知或完成。现有0118/0159/0500及CP副作用缺口没有因本次接收成功而闭合。下一消费者应调查原011b合同并精确实现，不能统一放行任意10B命令。

## 范围与独立审查

按[委托范围](../../../../scratch/a7c2-bb-0145-integration-20261115/scope.md)完成审查→三文件集成→第二十八跑，没有再委派。使用ponytail及docs-generator，flavor=null，沿用本项目报告位置。skill直接引用的tool-index.md和ops/evidence-finding-path.md缺失；纯文本报告不需要bootstrap，按可读模板的E/F/P字段组织。二进制原字节身份由候选已有验证器独立重核，没有声称本轮使用IDA或执行原CP。

[独立审查](../../../../scratch/a7c2-bb-0145-20261115-candidate1/main-independent-review-v1.md)无P1必修项，candidate1原样集成。审查确认：8个布尔、opaque通知QID和notify_type0/2对应原event95→CP1cd530→VDF0312；原AP34e62bc的send_no_wait_i没有回复接收等待。单worker沿用detach-before-free、失败保全及锁存fault，free成功后才提交记录；失败不重试、不生成伪ACK。原24B padding保持，下层0312 padding置零。未知枚举及未知opcode仍拒绝。

P2边界保留：VDF0312业务后端缺失，latest-intent覆盖只表示最新配置，不能代替逐笔应用与通知。没有立即AP等待也不保证后续显示业务永无依赖。

## 集成及宿主验证

[集成目录](../../../../scratch/a7c2-bb-0145-integration-20261115/)保存完整前像、摘要、git apply --check/apply及重建原输出。补丁相对final/a7c2-qemu，仅修改bb-receiver.c并新增test_bb_0145.c与runtime/analysis/test_bb_0145.py；没有用冻结候选目录覆盖产品。全部三文件摘要与候选一致。

完整build-observers链重新生成KO、preload与相关消费者，随后CPIO和生产derive。preload内容保持原摘要，CPIO只有simulation/sony_udate_distribution.ko改变，成员集合与文件模式均保持。不是直接拿候选ABI检查KO部署。

| 资产 | SHA-256 / 结果 |
| --- | --- |
| bb-receiver.c | `9f4650801353e6588dc34e28f277fdb57bcb11964db61ce713431c6efb763515` |
| preload | `754cbdd3513244affe3e72a989ad0a42390caa400a80853e0586c5819a25afae` |
| UDATE KO | `0cf14c57a440b035e107bd0b3eee4671ac5bb927ae264b790d9120690652620d` |
| 基础CPIO | `ae1f9ab91c788b0a20d1a23493a8bfab3d7530d619167f7778dd56d2e91419dc` |
| 实际运行派生CPIO | `e84eb5b7236e8e5fd136b8d1722165f2743e9699266f6e8cc8facdaf9cefec17` |
| binding | `derive-prod-22c26ebf71167871`；derivation SHA `4aaa61dc624ff46f515ae757304f68bb35d11cacc2cad929f029236d9bbca424` |
| QEMU | 已有b369构建，run `9b05` |

[独立宿主收据](../../../../scratch/a7c2-bb-0145-20261115-candidate1/checks-main-independent-v1.json)：2线程、2组、32场景全部通过，其中0145八场景、旧BB/0159/042b24场景。使用NDEBUG、严格警告、ASan/UBSan；包括512合法组合、65535个24B未知opcode、非法字段、并发、free失败、地址复用及旧命令回归。候选原33场景含额外旧前像反证，独立32场景与原33不累加为新的独立业务覆盖。

[集成回归](../../../../scratch/a7c2-bb-0145-integration-20261115/product-regression.json)：2线程、2组；0145 pytest1方法（内部八场景），UDATE/BB6方法及69subtest，以及0159五个直接场景全部通过。完整生产KO的ABI检查通过。CP/USB源码本轮未改，没有重复运行其重型回归，原收据保留。guest实际读回KO/preload SHA与plan一致，1GiB原RAM卡消费SHA通过；该条不等于本轮Fsys挂载或写卡通过。

## 真实运行与第一处失败

[原始运行汇总](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate28/runtime-summary.json)与[精确因果读回](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate28/frontier-readback.json)基于原console物理LF行号，仅去行尾CR。console SHA256为`82cdc1c038b15a868fd7d2204b08ca682b4a56fc8b4bb67d14634773c5617068`。

| 原console行 | 实际证据 | 判定 |
| --- | --- | --- |
| 7187 | tid379、dest92840747、source81cf61c6、type13、0145、24B，原send rc0 | 上轮0145入口拒绝跨过 |
| 7197 | BB_K_0145_CONFIG generation1、notify_destination81cf618b、notify_type0、request_freed1 | 新guest模块实际执行接收/释放与意图提交 |
| 7192 / 7194 | 011b/10B，BB_K_REJECT及原send均−1020，caller_owns1 | 新首个拒绝合同 |
| 7219 / 7221 | 首个ASSERT_CALLER后，infra_wrapper_bb_ipsx_sp_pp_branch.cpp:949 | BB949仍存在，已由011b触发 |

0145原wire为`0d2045011800018000000001010000008b61cf8100000000`，与候选重放的原wire一致；新011b原wire为`0d201b010a0001800308`。日志中的errno=2来自成功send后的旧errno，不将它当作0145失败码；diagnostic=1/ownership_changed=0表示trace不改变所有权，不推导为接收器未取得所有权。真实释放进度由worker的request_freed1及已验证源码支持。

worker是异步的，所以0145释放日志晚于011b拒绝日志；这不是0145返回−1020。未做live bb_0145_wire或bb_0145_vdf_request内存转储，不能把宿主规范化记录说成guest内存读回。真实guest日志明确lower_sent0、applied0、notifications0、completion0。

本轮4037有3笔still-unlock、4023两笔退休、4028等槽退休持续可见，没有新CP unsupported/unhandled或Imaging3109。但没有ENTER_REC_STILL，三条Imaging commit=0/0/0，mailbox/broker=false，快门未提交，Fsys同卡消费也未在本轮单独验收。首张LCD导出解码的ValueError及后续FirmwareFault原输出保留，不算UI走图通过。

失败发生在初始观察阶段，driver停止接收按键，尚未进入HUD或P3准入条件。新部署身份、精确wire、拒绝及断言链已明确，因此不作重复VM运行；允许的一次重试未使用。

## Evidence → Finding → Path

| Evidence / source_ref / content_hash | Finding / severity / confidence / location / status | Path |
| --- | --- | --- |
| E1：独立source-verification与32场景；receiver SHA见资产表；复核入口见checks-main-independent-v1/原argv | F1：n/a_re，high，BB0145 sender/worker；接收与生命周期检查通过，VDF后端partial | P1 callflow：原AP发送→严格字段校验→单worker快照→真实free0→提交意图 |
| E2：console7187/7197及frontier-readback；console SHA见正文；可用下述rg复核 | F2：n/a_re，high，guest BB0145；实际rc0/free1，原0145拒绝已解除 | P2 callflow：新KO→0145 send0→AP继续011b；不提升lower completion |
| E3：console7192/7194/7221，同一console SHA | F3：n/a_re，high，BB011b/949；真实新前沿，待实现 | P3 callflow：011b未知合同→−1020→原BB949→保留失败→下轮调查原011b |
| E4：consumer、final-audit、原QMP帧及请求ID | F4：n/a_re，high，owner lifecycle；退出/退租通过，业务失败保持 | P4 callflow：唯一ID quit→相同ID response→rc0→租约关闭→证据保留 |

时间线：先独立核对原合同及两组宿主检查；再备份、三文件apply、完整重建、CPIO/derive与两组集成回归；然后运行9b05并核guest摘要；随后取得0145成功与011b拒绝链；最后核QMP响应/rc0、关闭租约并保存空间与恢复账本。详细时刻保留在supervisor/driver/result收据，未修改历史收据。

从工作区根可只读复核关键原行：

```sh
rg -n 'opcode=0x145|BB_K_0145_CONFIG|command=0x11b|opcode=0x11b|assert at infra_wrapper_bb_ipsx_sp_pp_branch.cpp:949' scratch/a7c2-capture-p1-runtime-20261115-candidate28/run-1-evidence/console.log
sha256sum final/a7c2-qemu/report/virtual-cp/udate-distribution/bb-receiver.c final/a7c2-qemu/report/virtual-cp/udate-distribution/sony_udate_distribution.ko
```

构建/运行脚本采用独占新收据，禁止在已保存目录重复运行覆盖。重现实验须新建任务目录并更新binding，在run28与候选checks中的原argv基础上复用相同生产入口；每次仍需核身份、空间、FD及退出。原记录不能回填为重跑通过。

## 恢复及资源

[恢复清单](../../../../scratch/a7c2-bb-0145-integration-20261115/restore-manifest.json)保留本次修改前的源码、构建产物与原模式、SHA；归档目录0700、文件0600并逐个完整读回。回退时按source-manifest恢复旧bb-receiver.c，移除本轮新增两个fixture，再执行相同完整重建/CPIO/derive链；不要单独换一个旧KO冒充完整恢复。现有集成未回退，旧产品修改没有整目录覆盖。

QMP最后原帧`return {}`的ID为`8807ba6d8898c53fb2427edef79f603f`，与请求ID相同。QEMU rc0，driver rc2如实表示FirmwareFault；租约保留至退出，QEMU和launcher已不存在，任务socket/FIFO已清除。qmp-exit-unknown.json中serial_boundary_known=false是故障后串口边界未知的记录；它不等于quit失败，原响应和进程退出分别核验。故障后没有继续发诊断串口字节、写寄存器或恢复原程序，没有发送信号或接触真实设备。

生成前完成12GiB峰值+64GiB余量预算。本轮首轮核收列项保留实占为3,014,086,656B，最终新增文档、独立审查输出和恢复索引补充计入集成目录storage-final-v2.json及运行目录final-supplement.json。st_blocks逐文件总和可能重复计入reflink共享extent，不宣称是独占物理增量；文件系统净变化与实际回收分列。实际回收0B，未执行回收。恢复前像、当前binding、原始唯一失败与重放材料保留给父会话核收及下一轮011b实现，替代恢复和证据消费者确认后才按精确引用审计处理。最终可用空间及全部保留项的下一消费者见本轮最终账本。
