# BB042b 集成与第二十一跑

本轮独立审查 BB 命令族候选并精确集成三文件，完整重建 KO/preload、CPIO 和生产 RAM 卡 binding。原 CP 对042b只取request+8低byte写u32参数并走公共释放；候选保持该合同，无必修P1/P2。两轮实际guest中042b与随后0500发送均返回0；唯一日志增强重试确认042b参数提交和真实free，旧BB949未复现。两轮首个新拒绝均为CP404e（−1020），随后原Imaging3109断言；0118/0159/0500下层完成仍不成立。未进入HUD、未发快门，mailbox/broker及拍摄写卡未通过。两轮均quit/rc0、无信号、租约到退出；本轮无活VM/socket/FIFO遗留。

## 范围、输入与恢复

授权范围为父会话委托的审查→集成→第二十一跑，不再委派。仅操作本机虚拟卡及本任务状态，不访问真实相机或物理存储。flavor=null；无适用IOC/ATT&CK。无独立case scope文件，本节、父会话任务和运行plan构成范围合同。

候选位于项目根 `scratch/a7c2-bb-opcode-batch-20261115-candidate1/`。独立审查见其 `main-independent-review-v1.md`；原CP完整SHA及全部cp-pins/probe窗口经过独立读回，结果见 `scratch/a7c2-bb-opcode-batch-integration-20261115/independent-source-review.json`。报告技能引用的tool-index和ops/evidence-finding-path文件缺失，本轮仅用已声明文件/命令工具，未声称使用不存在工具。

产品只应用 `bb-receiver.c`、`test_bb_opcode_batch.c`、`test_bb_opcode_batch.py`，其余候选冻结依赖未覆盖产品。保存前像、完整摘要和原模式后执行git apply --check，再应用并逐文件读回。恢复清单位于集成目录 `restore-manifest.json`：按映射恢复前像及原mode，移除本轮两个新增测试文件，沿原build-observers→prepare-menu-initramfs→derive链重建旧版；不可只换旧KO。

## 构建与宿主验收

| 层 | 结果 |
| --- | --- |
| 独立静态审查 | 无必修；042b class6、69ac86低byte/u32写入、公共free匹配；未知命令拒绝及IRQ锁/地址复用/失败保全保持 |
| 完整guest构建 | 原resident ABI通过；KO `b60437dbac70e287fc2a75d2e162578e71b011476f325dd3e89f7d7195d1ebc5` |
| CPIO差异 | 成员集合与mode完全保持，只改simulation/sony_udate_distribution.ko；preload `294d6fd43a749f742963635bffdcef2ce60ec8ca8afcb35d7927291bdd777f75` 未变 |
| base CPIO | `5c13b957f4795d7881f162c0b2a14259b86c28be5fc74d0363639fb22c236a51` |
| derive | `derive-prod-71bcac1dec3cf32c`；derivation SHA `029241a457eac538df683c7f2b62a2a7cc45df3521db9614e05050478a45c45a`；输出CPIO `7c554c3816b6a1474f7bcfcca00322196ba597cff5aad66ecf0aae3d09228be7` |
| 回归组1 | CP/history：pytest4项+100 subtests；独立CP40b8六场景均rc0 |
| 回归组2 | UDATE/Backup/BB：pytest6项+69 subtests（包含新042b七场景）；独立0159五场景均rc0 |
| 宿主USB | 既有run-usb-msc-batch-v4入口通过，输出run-r86cqrld |

回归两组使用两个宿主工作线程，没有另开子代理。产品回归JSON继承旧脚本的new_scenarios计数字段，本轮实际计数以原pytest stdout和各独立场景rc为准，未把候选194场景重复算作新增场景。各argv/rc/stdout/stderr独立留存于集成目录，complete.json只在构建、derive和全部回归均通过后生成。

## 第一次实际运行

任务目录 `scratch/a7c2-capture-p1-runtime-20261115-candidate21/`，原run `runtime/analysis/menu-runs/9e90`，原console SHA `355d8c1395eab5d8b023ec46e57a542d6e3ad529c1dcd99954fe6705aa2c80a3`。

- console5518：0118/22B原发送rc0。
- console5609：0159/10B原发送rc0。
- console5641：042b/10B，raw `0d202b040a0001800000`，原发送rc0。
- console5644：0500/10B，raw `0d2000050a0001800100`，原发送rc0。
- console6018：401c参数接收且request_free_rc=0；此前40b8/402a/40af参数族继续通过。
- console6022–6023：404e/8B，raw `05004e4004000080`，原CP模型UNHANDLED且原send返回−1020。
- console6288–6291：notify_model_system_error，原Imaging execute_infra_cmd_i行3109；BB949未出现。

第一次运行已核对guest整卡1GiB SHA，owner收据为quit确认、QEMU rc0、无信号、runner关闭、worker停止、磁盘租约保留到退出。未进入HUD、没有提交快门，mailbox/broker未连接。首轮在stage0采样之后才出现042b；内核日志级别1导致其free/pending日志未进console。因此仅凭首轮发送rc0尚不能记042b实际free通过。

## 唯一日志增强重试与实际消费

重试只改观察日志级别（dmesg -n1→-n7）和trace grep前缀，沿用同一产品、binding、37个原App32动作与快门前置条件。任务 `candidate21/retry-1`，run `e6b0`，console SHA `a15bbe18b29048736fc455e0e755a8eaf8e724a6027223c0634944751eb8c895`。未进行第二次重试。

| 原console物理LF行 | 实际结果 |
| --- | --- |
| 7221 | 0118 generation1，selector3，pending_mask=3，request_retained=1，applied=0，completion=0 |
| 7251–7252 | 0159 raw7→lower_value7，lower_pending=1，lower_sent=0，backend_missing=1；原请求free，非下层完成 |
| 7275、7277–7278 | 042b原send rc0；parameter_value=0，generation1，request_freed=1，reply_required=0，applied/completion=0；worker总freed2 |
| 7282、7284 | 0500原send rc0，参数1，generation1，原请求free；未生成1500或完成模式业务 |
| 7650、7653 | CP404e UNHANDLED，8B原send rc−1020，raw05004e4004000080 |
| 7666–7668 | 原notify_model_system_error与Imaging3109；未观察到BB949 |

两轮均读到指定preload/KO完整SHA，guest整卡SHA通过；运行source前后身份一致。实际3条Imaging连接commit、ENTER_REC_STILL和拍摄均0，shutter_attempted=false，mailbox/broker=false。rc2是诊断driver对固件业务失败的返回；QEMU进程本身quit/rc0，不能把两者混作业务通过。

汇总 `runtime-summary.json` 的line字段使用Python universal-newline行号，原收据保留不改；新增 `physical-line-citations.json` 用原bytes按LF计数并核全文SHA，报告上述行号以该补充清单为准。原stdout/stderr、各返回码、唯一失败和恢复映射均保留。

## 保留的业务边界与下一前沿

0500原handler不仅记录参数，还构造1500回复并调用6a1ca2/6a1dae；0142/015a/0160亦有异步下层工作，旧模型均为partial。0118保留请求/pending_mask=3，没有分支applied或1118完成；0159只记录VDF0302，lower_sent=0。0161/0429含异步event与下层closure，本批仍拒绝。未知命令不通用ACK、不清pending、不伪造原CP执行。

CP404e原静态合同已在[参数批量候选](../../../../scratch/a7c2-cp-opcode-batch-20261115-candidate1/README.md)中明确：8B请求，配置gate真时对P+7a7递增，否则构造内部0901并投递90060197；消费/回调/完成链见[404e专题](../cp302c-prefix-404e-0901-preservation.md)。新拒绝符合已知缺口，下一批需闭合gate、分配/投递/消费所有权及下层回调，不能把它改成空AP回复。

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| 独立读回CP原SHA/窗口、042b完整handler、三文件摘要 | 042b无独立ACK，低byte/u32参数合同成立 | 精确槽6+完整wire保留→guest send/free验收 |
| git apply前像/恢复摘要、CPIO delta、derive收据、两组host原输出 | 当前增量保持其余产品及guest成员/权限 | 新binding→FD/租约→实际guest装载核验 |
| run9e90原042b/0500 send rc0及404e -1020、Imaging3109 | 旧042b发送边界通过，404e为首个新拒绝 | 单次日志增强复跑→确认kernel free与pending→独立404e后端 |
| 0118/0159/0500原合同与partial记录、重试kernel原输出 | 0118保持pending，0159未发下层，0500仅参数/free | 保留pending与未完成边界，不报告完整拍摄通过 |
| 两轮QMP quit、QEMU rc0、owner身份与lease退出收据 | 业务失败仍完成自有VM资源生命周期 | 保留原失败，交由CP404e后端实现继续 |

## 空间与收尾

生成前分别预算12GiB集成峰值和4GiB单轮运行峰值，保留64GiB余量；均满足。初步逐文件账本：集成目录1,500,811,264B、运行任务20,406,272B、新derive1,492,905,984B、两个原run19,275,776B，另有小型报告、最终审计与USB既有回归输出；最终按 `candidate21/final-audit.json` 和两目录 `storage.json` 计实际分配块。此口径包括恢复前像的文件分配块，reflink可能共享物理extents，不把其相加当作文件系统净新增。

核收时文件系统可用1,944,784,162,816B（精确最终值见final-audit）。实际回收0B，未执行回收。当前derive留给下一次生产运行，前像留给恢复当前产品，原run/摘要/原输出留给父会话复核和404e下一前沿；编译品与任务临时材料留给检查重放。接管后须先完成消费者、活引用及身份核查，再回收可重建项。本任务没有通过信号终止VM，不访问真实设备，不删除他人资源。
