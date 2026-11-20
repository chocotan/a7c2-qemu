# 第二十六跑：两笔4023退休通过，下一重复4028仍触发Imaging3109

4023候选独立审查通过，八文件已精确集成，完整preload→CPIO→生产derive和宿主回归通过。实际原AP发出的两笔同值4023均写入参数、释放请求并复用入口槽，generation/retired分别1/1与2/2，free_rc=0；没有覆盖首笔中央8306义务，也没有伪造中央事件或APPLY完成。

**本轮整体运行仍失败。** 原AP越过旧4023触发点后，第三笔4037和4084/40fb参数处理可达，随后第二笔4028命中其既有单笔保留限制，以模型分支支持的-1021拒绝，仍在Imaging3109断言。没有到达首设/HUD、Imaging三连接或mailbox，没有发快门，没有JPEG或写卡验收。下一工作是4028实际语义与请求退休，不是扩大保留槽或吞掉重复请求。

## 范围和独立审查

[本轮scope](../../../../scratch/a7c2-cp-4023-integration-20261115/scope.md)限定为审查→八文件集成→第二十六跑，不再委派。保留现有产品变化、历史失败与原固件；只使用独立RAM卡和虚拟设备，没有真实相机、物理USB/存储写入或发布。运行是direct-bootin原AP诊断，未执行原Sony loader/WBI、原CP RTOS或完整冷启动，不能用于确认实机刷入问题已修复。报告flavor=null；技能邻接tool-index缺失，文档无外部工具依赖，沿用已存在脚本与实际路径；证据契约采用router现有副本。

[独立审查](../../../../scratch/a7c2-cp-4023-20261115-candidate1/main-independent-review-v1.md)确认4023是SET_AF_MODE，原355edc写P688/P720、按条件清P2ba/增P7a6，公共dispatcher置dirty，接收循环解锁后释放每笔请求。404e才是FC CancelTracking。未发现本批集成前必须修复的P1/P2；中央8306、config+2db及公共APPLY仍是明确的P2完备性限制，不记为已实现。

[独立host复验](../../../../scratch/a7c2-cp-4023-20261115-candidate1/checks-main-review.json)：2工作线程、3组、210逻辑场景，4608条件组合、10000同值复用、5实际布局pytest、严格/ASan/UBSan与AArch64交叉构建全部通过，93项产品输入和候选输入前后摘要未变。两笔原wire重放、拒绝不覆盖、free失败保全、重入、fork、别名、溢出和并发均覆盖。方法、场景和重复pytest不简单相加，不替代guest消费。

## 集成和恢复点

[集成目录](../../../../scratch/a7c2-cp-4023-integration-20261115/)保存before前像、manifest、git apply --check、应用和逐文件after SHA读回。仅应用candidate清单中的八文件，六个既有文件修改、两个测试新增；没有覆盖整份候选目录或其它已集成变更。调用既有build-observers.sh、prepare-menu-initramfs.sh及生产derive，真实只读fsck沿恢复owner执行。CPIO只有simulation/menu-observe.so内容变化，成员集和权限保持，KO不变。

| 产物 | SHA-256 / 身份 |
| --- | --- |
| preload | `e68dc245fb931fef6252b6b29c53a673e62da75df261981ad36a32226d84d5dd` |
| base CPIO | `9f13f584a3fd79aa85c9cc0fe8d92bf60b7651315d159f1025b83cfeb14e8dae` |
| binding | `derive-prod-690b919ec3d32a2c` |
| derivation.json | `a5b17c51a2449f1f84c025b8a1f0288386d165ec05431d7b87d46c807ed815ec` |
| RAM CPIO | `c9d046abe9e3e95b50f4f52d1e86b27a28169577ad4d27ed59bc315d9126f55b` |
| KO | `b60437dbac70e287fc2a75d2e162578e71b011476f325dd3e89f7d7195d1ebc5` |

集成后两线程、两回归组：imaging 408 passed；CP 8方法与100 subtests；UDATE/Backup/BB 6方法与69 subtests；另CP40b8六场景、BB0159五场景均过。未变化的USB重型回归未重跑。

恢复资料位于集成目录restore/，目录0700、文件0600，逐文件完整SHA读回；manifest保留原路径、mode与前像身份。回退须先核当前消费者和目标SHA，恢复六个修改文件并移除本批两个新测试，再沿同构建链重建；也可恢复已验证旧产物及其绑定收据。未执行回退，未覆盖旧binding或失败收据。

## 实际guest结果和下一前沿

[运行目录](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate26/)的原run为runtime/analysis/menu-runs/72d1，归档与原run逐文件SHA一致。guest实读preload/KO摘要匹配部署。1GiB seed与/image_mmca两次全卡SHA均为`71362dfd3446d9de01fc59f1614d1dd7944a88cae19f2d70261f16e41e7e7888`；这不替代本轮原Fsys同卡挂载验收。

下表使用原console的LF物理行，CR去除不增加行；[前沿核验](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate26/frontier-readback.json)以assert验证顺序、wire和部署分支。

| 行 | 原事件 | 已证明行为 |
| --- | --- | --- |
| 5724–5726 | tid378、sequence9，首笔4028，token80000007 | wire=`05002840070000800000000000000000`；单笔请求保留，live-gate/prior-parameters后端未执行 |
| 5757 | 首笔4023，token8000000d、body2 | generation1、retired1、P688=2、P720=0、free0、retained0 |
| 5784 | 第二笔4023，token80000011、body2 | generation2、retired2、free0、retained0，入口槽实际复用 |
| 5889 | 第三笔4037，selector0xd、token80000013 | controls=3、still token更新、free0；没有物理AF/capture完成 |
| 6004–6075 | 后续多笔4084/40fb | 参数接收与请求free0，原AP继续推进 |
| 6077–6079 | 同tid378、sequence29，第二笔4028，token8000001b | wire=`050028401b0000800000000000000000`；body与首笔相同，remainder-pending-or-owner-fault拒绝 |
| 6144–6146 | ASSERT_CALLER、lib_assert.cpp46、Imaging3109 | 旧4023触发点已越过，新的4028保留限制触发同一上层断言 |

两笔4023都明确记录central_pending=1、central_generation=1、central_delivered=0、apply_pending=1、apply_completed=0、handler_complete=0。第二笔没有覆盖中央义务；仅请求生命周期闭合，不等于完整SET_AF_MODE业务闭合。P688初始未知、config gate未绑定仍保留unknown语义。

4028返回值-1021来自精确部署源码的pending守卫与unsupported分支，**没有独立底层P18_OSAL_RESULT/4028负返回行**：被模型截获的发送不经过该底层trace。因此runtime-summary的first_negative_send=null不表示全部发送成功。本轮没有4023-central-backend-busy或4023 owner错误。

0118仍有panel pending（applied/completion0）；0159记录lower_pending1、lower_sent0；404e与4070各保留一笔、内部0901/1010仍未投递。3006/3007背景启动未获得本轮完成证据。Imaging三commit、ENTER_REC_STILL均0，mailbox/broker均false。初始/proc/osal/uipc采样没有有效池统计，不能声称池/三个outstanding健康；本轮未做新的池容量验收。UI初始导出没有形成可验收LCD帧，异常后原App32输入停止；37动作虽预置，没有据此宣称首设走完。快门/HUD守卫未满足，未发P3快门。

## Evidence → Finding → Path

| Evidence（本轮2026-11-15观察，supersedes=none） | Hash / 重现入口 | Finding / Path |
| --- | --- | --- |
| E1：独立host检查checks-main-review.json | `f810b89ac9c7ea72803199536a09766710b679df310256c0814a91cf086c3c6b`；candidate/run_checks.py使用新的--output可独立重跑，须恢复其baseline产品布局 | F1：候选请求生命周期和既有回归host通过，n/a_re/high；P1：审查→备份→精确集成→完整重建→新binding |
| E2：原console.log | `bfc4f4312addf44e2db4a07645322ca155a4ab08f3314298fecf8f308b2e2f3f`；运行目录start.py为原命令，复跑须新建独立目录与新收据 | F2：两笔4023实际退休且中央义务未被覆盖，validated/high；P2：原AP wire→accept_4023→参数写入/独立义务复制→free0→retired1/2 |
| E3：frontier-readback.json | `3abbf6a526f38370996e8f40d1de00860b3b5c87b0ef8096801e7aa07550d528`；verify-frontier.py为可审查判据，原输出用独占创建保护 | F3：第二笔4028命中未退休槽并触发Imaging3109，validated/high；P3：首笔pending→两笔4023越过→第三笔4037/参数→第二笔4028拒绝→上层断言 |
| E4：final-audit.json与QMP原wire | 每文件SHA在storage.json；collector读回原run/归档、owner身份和QMP退出响应 | F4：QEMU正常退出、租约与socket收尾通过；不改变F3业务失败 |

时间线：冻结输入与原CP/AP证据审查→两线程独立复验→六文件前像及其余构建产物备份→八文件应用→完整重建/derive→两组宿主回归→72d1运行与guest摘要核对→两笔4023退休→第二笔4028拒绝→保留异常→QMP quit/rc0→归档、前沿和空间核收。未重试：部署、原请求释放和确定的新前沿均已取得，无必要重复相同运行。

下一消费者应调查原4028 handler、live gate/prior parameters和公共接收释放合同，制作有真实语义的逐笔退休候选；不能直接套用4023业务、清pending、增加永久槽或制造完成。4023中央8306/APPLY义务仍需独立后端，不因本次free0而取消。

## 生命周期和空间

QEMU pid2400125/starttime126996459退出，launcher不存在，runner closed，租约保持至退出，无遗留本任务socket/FIFO。QMP唯一quit ID为`ded4598a9c7bd0c138777d5fc845f81d`，原响应同ID且return为空对象，原wire SHA匹配。QEMU rc0；driver rc2保留业务失败，未发任何信号。

[收尾审计](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate26/final-audit.json)记录四个主要目录新增/保留实占3,019,165,696 B，实际回收0 B，采样文件系统可用1,928,591,519,744 B（集成前1,931,641,262,080 B）。st_blocks包含恢复前像、当前binding、原失败和原日志归档，reflink共享块可能重复计数，不等于底层独占新增。文件系统净变化与回收分开记账。后续小型脚本、独立复验、报告和新增测试的补记见运行目录final-supplement.json，账本本身不递归计数。

**未执行回收。** 当前binding供下一运行使用；恢复前像供回退；原异常与host原输出供父会话核收、4028语义和中央后端调查，均有下一消费者。可重建host重复布局和构建品本轮仍待父会话接管，标为保留；接管后须精确身份/活引用审计再回收，不清唯一失败、恢复依赖或当前binding。本任务无遗留运行VM、租约或socket。
