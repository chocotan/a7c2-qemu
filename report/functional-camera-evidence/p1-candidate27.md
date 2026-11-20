# 七槽请求退休集成：重复4028已跨过，下一前沿为BB0145

第二十七跑实际跨过第二笔4028：两笔请求均由真实释放回调返回0，generation/retired=1/1、2/2。第三笔4037及后续4084/40fb也已实际消费，本轮未复现Imaging3109。新首个负发送是原AP发往`0x92840747`的type13/`0x0145`/24B，虚拟BB接收器明确返回−1020，随后触发原BB949。未进入拍摄HUD，Imaging三连接、mailbox、自然快门、JPEG和写卡均未通过。

## 范围与审查

本轮按[候选范围](../../../../scratch/a7c2-cp-slot-retire-20261115-candidate1/scope.md)执行独立审查→精确集成→第二十七跑；没有再委派。使用ponytail和docs-generator，flavor=null。仍是direct-bootin原AP诊断：未执行Sony loader/WBI恢复或原CP，不是完整整机启动验收，也不能据此认定故障相机已修复。

[独立审查](../../../../scratch/a7c2-cp-slot-retire-20261115-candidate1/main-independent-review-v1.md)无必修项，candidate1原样集成。七个通用槽4028/4022/4077/4039/40a5/404e/4070允许逐笔释放并复用；未实现业务保留deferred_count和首末wire，404e/4070的内部事件、worker和completion仍为0。4028只解码请求的有符号增量、mode、两个LE16，不猜gate或修改未知CP参数；4023的中央8306独立义务检查未放宽。

free失败保留原指针和sticky fault，恢复核BG/CAP目的SID，锁外释放并以sending防重入；只有真实free0才退休。快照ABI扩展后执行完整build-observers，全部device-model object、preload、声音/helper和UDATE模块重建，再重建CPIO及生产derive。未混用旧布局消费者。

## 集成与验证

[集成目录](../../../../scratch/a7c2-cp-slot-retire-integration-20261115/)保存七个既有源码前像、构建恢复点、精确九文件清单和git apply --check/apply收据。新增C/Python fixture一并集成；全部前后SHA读回，候选其余冻结源码未覆盖产品。CPIO只改变`simulation/menu-observe.so`，成员集合和全部文件模式保持。

| 资产 | SHA-256 / 结果 |
| --- | --- |
| preload | `754cbdd3513244affe3e72a989ad0a42390caa400a80853e0586c5819a25afae` |
| UDATE KO | `b60437dbac70e287fc2a75d2e162578e71b011476f325dd3e89f7d7195d1ebc5` |
| 基础CPIO | `4414b08e0c30e4c9c9cb3eb9c3ea871ba8565333ae1413cd46faf42f8f512c51` |
| 实际运行的派生CPIO | `1473b9cb8f978c90891705c84b3a3ca452ed2f9e69ebbafdb162c8da964d23e5` |
| binding | `derive-prod-153f477ac3f1bc45`；derivation SHA `b580178350e4796608bcce1b27f3a500f150abb3ed5d5d0d4f982ec3729a755f` |
| QEMU | 已验证既有b369构建；run=`2f5f` |

[独立宿主收据](../../../../scratch/a7c2-cp-slot-retire-20261115-candidate1/checks-main-independent-v1.json)：3检查组、2工作线程，270直接case调用和6个pytest入口通过；包括ASan/UBSan、DNDEBUG、AArch64编译、七槽复用、free失败/恢复重入、4028全部signed byte、4023条件枚举及既有命令族。历史fixture别名和重复入口不算额外独立业务覆盖。

[集成回归](../../../../scratch/a7c2-cp-slot-retire-integration-20261115/product-regression.json)：2组、2工作线程；still/dispatcher 408项，CP 9方法/100 subtest，UDATE/BB 6方法/69 subtest，以及40b8六场景、0159五场景均通过。guest实际读回新preload与KO摘要，全卡1GiB SHA消费验证通过。未重复运行无源码变化的重型USB回归，前轮证据仍保留。

## 原AP运行结果

[运行汇总](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate27/runtime-summary.json)、[退休核验](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate27/frontier-readback.json)与[新前沿因果核验](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate27/next-frontier-readback.json)保留原始行号。OBS实时输出与后续plain日志的相同body去重计数，原console保持不变。

| 实际命令 | 观察 |
| --- | --- |
| 404e / 4070 / 4022 | 各1笔free0/retired1，semantic_pending1；业务副作用未执行 |
| 4028 | 两笔wire分别`05002840070000800000000000000000`、`050028401b0000800000000000000000`；free0，retired1/2，semantic_pending1/2，gate_known0、parameter_updated0 |
| 4023 | 两笔free0/retired1/2；central_pending1、central_generation1、central_delivered0、APPLY未完成 |
| 4037 | 共3笔still-unlock实际释放；第三笔之后4084/40fb参数请求free0，再到第二笔4028 |
| 4077 / 4039 / 40a5 | 本轮未发送；仅宿主覆盖 |
| 0118 / 0159 / 0500 | 0118仍retained/backend_missing；0159 lower_sent0；0500完成仍未验证 |

首个负发送的完整wire为`0d2045011800018000000001010000008b61cf8100000000`，目的`0x92840747`、源`0x81cf61c6`、24B、原线程tid486。console第7746行BB_K_REJECT记录caller_owns1；第7748行原P18_OSAL_RESULT返回−1020；第7784行原`infra_wrapper_bb_ipsx_sp_pp_branch.cpp:949`，函数`send_no_wait_i`。部署的[bb-receiver.c](../../report/virtual-cp/udate-distribution/bb-receiver.c)入口只允许10B/22B，bb_index没有0145；本轮未猜测它的业务语义或扩大白名单。

初始被动采样EE_START_ENABLE=1、EE_ENTRY_SOURCE=0、EE_STATUS=0、BACKUP_SYNC_PENDING=0。这不是断言时最终状态。故障发生在首张LCD采样/初始被动观察阶段，尚未成功注入首设按键；没有走图或P3快门条件。Imaging三commit=0，mailbox/broker=false。UIPC初始proc采样没有取得分配器/queue统计，因此不宣称池健康或泄漏已消除。没有观察到带回复3006/3007/403d成为本轮首个阻塞。

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| 独立审查、270 case/6入口、精确清单/原值SHA | 七槽生命周期修正可集成，CP业务未实现边界保留 | exact apply→全消费者重建→CPIO→生产derive |
| guest摘要、原AP input audit、两笔4028退休、3笔4037 | 上轮重复4028模型入口限制已解除；Imaging3109本轮未复现 | 原AP→新owner→真实free0→后续原命令 |
| 原wire、BB_K_REJECT→原send−1020→BB949 | 新缺口为虚拟BB0145/24B接收合同，不能归因于CP退休槽 | 调查原0145消费者/回复/副作用→精确实现→下一轮重建运行 |
| QMP原帧/ID、consumer/owner收据、final-audit | 失败现场完整，QEMU干净退出，未伪造业务通过 | quit→wait rc0→租约释放→证据保留 |

收尾检查首轮把基础CPIO误与派生CPIO摘要比较而失败，已分别按集成收据和运行plan修正核验；原失败保留在集成目录final-check-v1-failure.json，不涉及产品内容修改或VM重试。

本轮无需运行重试：新部署身份、输入wire、模型拒绝和原断言链均明确。下一轮应先恢复0145真实接收、所有权和回复/副作用合同，再推进HUD；不能为24B统一返回成功。七槽未实现业务、4023中央义务和0118/0159/0500后端继续单独记账。

## 恢复与资源

恢复清单在集成目录`restore-manifest.json`，保留原路径、模式和完整SHA；归档文件均0600、目录0700。需回退时按source-manifest恢复七个旧源码、移除两个本轮新增fixture，再沿同一完整重建/CPIO/derive链恢复原产物，禁止只换旧.so。当前实例没有被回退。

QEMU使用唯一ID `e296d4deed38622acebf1a9457ae25dd` 的quit返回帧，进程rc0；driver返回2如实记录业务异常。无信号，租约持续到进程退出，QEMU/launcher已不活跃，任务socket/FIFO均不存在。未连接或写入真实设备。

初次核收新增保留实占按st_blocks为3,020,836,864B；最终补充数字见本轮`final-supplement.json`和`storage-final.json`（包含后续报告、复核与独立宿主输出）。reflink共享extent可能重复计入逐文件块数，文件系统净变化单列，不当成回收量。实际回收0B，未执行回收。恢复前像、新binding、原失败现场及宿主重放材料保留给父会话核收和0145实现；核收与替代恢复确认后，才按精确身份/活引用审计清理可重建项。空间预算12GiB峰值+64GiB余量已在生成前通过；初次结束可用1,925,340,233,728B，最终值见补充账本。
