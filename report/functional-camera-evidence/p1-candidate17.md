# 第十七跑：BB candidate2 已集成，实际启动仍在发送边界失败

BB receiver candidate2 已接入产品，交叉构建的 KO 与审查候选逐字节一致；CPIO 只改变该 KO，并生成新生产 RAM derive。产品模块测试与两组/两线程 USB 回归通过。实际 QEMU 首跑和唯一重试都先出现 Imaging3109，随后 BB949；两者都是发送返回非零的断言，未进入拍摄 HUD。本轮没有观察到 BB 接收日志或0118 pending，不能判定第十六跑978缺陷已修复，也不能判定0118后端等待是当前阻塞。两轮均 QMP quit、rc0、无信号，租约保留到退出。

## 范围与产品改动

范围来自本轮委托：集成 `scratch/a7c2-bb-receiver-20261115-candidate2/`，执行第十七跑及一次允许重试；不继续委派、不接真实设备。沿用既有 direct-bootin、原 AP、虚拟 RAM 卡和 CP 功能模型；没有执行真实 CP 固件、原 Sony loader/WBI 恢复或完整 SD 更新。

产品目录 `report/virtual-cp/udate-distribution/`：

- `client.c` 接 BB 目的 `0x92840747` 及 worker 生命周期，原 UDATE/Backup 与非支持目的的显式失败保持。
- 新增 `bb-receiver.c`、宿主 `test_bb_receiver.c`、宿主锁适配 `test_kernel_lock.c`。guest 构建不链接宿主适配文件。
- `check_client.py` 增加7个原 kernel API 导入和锁/保留记录 ABI 校验，保留产品相对 ABI helper 路径。
- 更新 `test_udate_kernel.py` 的导入预期与既有三种宿主 fixture 编译参数，接入12个 BB 场景，确保原测试入口继续可用。

候选只接受五类配置 `0142/015a/0160/0500/033b`，由 worker 记录并释放；不能把配置入队当作成像副作用已完成。0118 为严格22B请求，仅保留一笔并记录 `pending_mask=3, applied=0, completion=0, backend_missing=1`，没有伪造1118。锁竞争使用原内核 IRQ-safe ticket lock；先脱队再free，free失败保留并关停，不重试或双free。

## 集成身份与验证

所有脚本均先写文件、读回审查，再执行。补丁先 `--dry-run --fuzz=0`，再应用；复制、构建、安装和归档均摘要读回。

| 项 | 结果与证据 |
| --- | --- |
| KO | SHA256 `c9023130497b6354ed08eb2773fcc939d8f5e4f7c74463e421a2207b21ff489e`；产品、候选、menu-root副本一致 |
| CPIO | 成员集合和全部mode不变；唯一内容变化为 `simulation/sony_udate_distribution.ko` |
| derive | `functional-camera-profiles/derive-prod-c1b5bb1918bb1eed` |
| derive CPIO SHA256 | `7d644f626f02dcde9fce048f0da5f8383e874f847b4196f6b382cb22f73b0b9a` |
| derivation.json SHA256 | `fa16b96de4af79f4cbaf4aea26981075972e77ca11d48c81fac1626d0b2b2322` |
| 产品模块测试 | 5个unittest方法；57个既有协议场景与12个BB场景全部通过，ASan/UBSan |
| USB宿主回归 | 两组/两线程，22+78项、39 subtest，0跳过；原码和收据稳定 |
| 实际 guest KO 身份 | 重试setup中原openssl读出完整 `c9023130…`，加载前后使用同一initramfs |
| RAM卡 | 两轮guest完整seed SHA均匹配原生产seed；没有提升为Fsys同卡或capture通过 |

集成入口与收据位于 [integration](../../../../scratch/a7c2-bb-receiver-integration-20261115/)：`integrate.py`、`cpio-delta.json`、`derive/derive-result.json`、`module-tests.json`、`host-regression.json`、`final-sha256.json`。宿主回归原批次为 `analysis/scratch/cp-wait-20261111/usb-msc-host-batch-v4/run-w3oxnmqd/`，result SHA256 为 `7301f3fd9b94547f636cb53bb2577550fe90c233921098e7b392a1febc0830fd`。

## 实际运行与新前沿

原首设37个App32动作已按第十六跑预置，快门只有在 `ENTER_REC_STILL`、三条Imaging commit及无先前断言都满足后才提交。两轮均在首个UI观察附近异常，尚未执行首设动作和快门。首帧导出无法形成可解码LCD帧；该失败保留，没有用替代图像计通过。

| 场景 | 首跑 | 唯一重试 |
| --- | --- | --- |
| 原4字符run名 | `2e73` | `bdd2` |
| 首个原断言 | Imaging `execute_infra_cmd_i:3109` | 同左 |
| 随后原断言 | BB `send_no_wait_i:949` | 同左 |
| 原978断言 | 未观察到；前序失败阻断，不能视作修复 | 同左 |
| BB_K_REJECT / PANEL_PENDING | 均未观察到 | 均未观察到，已提前开启内核console日志 |
| 0118 | 原 AP 22B输入可见，未证明到达kernel receiver | 同左 |
| HUD / mailbox / broker / 快门 / JPEG | 均未通过或未提交 | 同左 |
| 退出 | quit + rc0 + 租约到退出 + runner_closed | 同左 |

重试只增加启动前 KO SHA、原 UIPC 池dump和早期printk可见性；源码、CPIO、derive和业务环境均不变。没有第三轮运行。

**对早期解释的更正：BB949是发送失败，不是分配失败。** 原反编译记录 `0x0034e0000.c` 的 ELF VA `0x34e62bc` 中，分配非零为行943、空指针为945、`osal_snd_msg` 非零为949。`0x003530000.c` 的 Imaging3109也对应 `osal_snd_msg` 非零。早期重试计划的旧reason保留，另立 [更正说明](../../../../scratch/a7c2-bb-receiver-integration-20261115/interpretation-correction.md)。本轮未取得首个失败包的完整“目的→发送层→返回码”绑定，不能将最近的0118、016a、0159输入或全局ioctl警告单独认定为根因。

## 池证据与泄漏范围

池数据使用原 `/proc/osal/uipc` 的两次32KiB read，gzip/base64运输后解压核验，按原字段读回。普通 `head` 读该proc得到空输出，不作为池证据。三份完整normal vpool快照如下；队列表可能未完整输出，缺失队列不按0计算。

| 样本 | normal空闲字节 | 最大连续字节 | normal历史高水位 | 可见三队列outstanding |
| --- | ---: | ---: | ---: | --- |
| 首跑初始 | 524032 | 523712 | 2880 | 0x83f/0x86f/0x8fc均0 |
| 重试AP前 | 524288 | 524288 | 2880 | 0x83f/0x8fc均0；0x86f未列出 |
| 重试初始 | 524160 | 524032 | 2880 | 0x83f/0x86f/0x8fc均0 |

这些结果没有复现第十五跑的normal池耗尽或大规模碎片化。由于启动被发送失败提前阻断，不能据此认定长期泄漏验收已通过，也不能推广到所有池或首个失败瞬间。

两轮完整摘要、原断言、KO身份与解码池记录分别在 [首跑证据](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate17/assessment.json)、[重试证据](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate17/retry-1/assessment.json) 及各自 `pool-analysis.json`。`runtime-frontier-excerpts.txt`只收实际日志行，排除shell中grep表达式；重复诊断输出不累加为业务事件计数。

## Evidence → Finding → Path

| Evidence | Finding / 置信度 | Path |
| --- | --- | --- |
| 前像manifest、零fuzz补丁收据、KO三处SHA及CPIO delta | F1：candidate2准确集成，既有CPIO其他内容保留；高 | 备份→dry-run→应用→构建→安装→CPIO→生产derive |
| 产品5方法/69场景、两组两线程USB结果 | F2：已覆盖宿主协议与并发合同无回归；高，限host | 原入口→新锁适配→并发/复用/0118保留→ABI与USB回归 |
| 两轮原console及原断言调用点 | F3：现前沿是发送失败；具体失败层和返回值仍缺；高/未定 | AP原输入→发送返回非零→Imaging3109→BB949→异常 |
| BB接收日志缺失、0118原输入可见 | F4：未验收0118接收和完成等待，不以“没有日志”断言路径不存在 | 原0118输入→中间分发待核→kernel接收未证→完成后端未实现 |
| 三份原normal池快照、队列A-F | F5：短时样本近全空闲，未见原碎片化；高，限采样 | 原proc→有界运输→解压/完整性→空闲/连续块/队列计数 |
| attempt收据、原owner PID身份与consumer租约记录 | F6：两轮自然退出、无信号，资源已关闭；高 | 唯一QMP ID→quit→Popen wait rc0→context退租→runner close |

下一步应先绑定原 `osal_snd_msg` 的确切返回及用户态模型/真实OSAL/kernel public sender之间的路径；在978和0118接收实际可达前，不应直接伪造0118完成或放宽所有未知命令。0118后端仍须按candidate2 `0118-contract.md`完成LCD/EVF应用、读回、1118原队列投递及AP d1消费。

## 恢复、资源与空间

修改前源码、模块、CPIO及prepare入口可能触及的既有文件均保存于 integration 的 `restore/`，完整映射在 `restore-manifest.json`。回退前先确认无本任务运行owner，然后逐项将manifest前像恢复至产品相对路径并核SHA；恢复原KO/menu-root KO/CPIO，重新产生与原基线绑定的derive。新增三个BB源码/测试文件不被旧build引用，可留作诊断材料；不需要无范围删除。当前生产derivation和两轮原目录受不可变收据引用，不能只因同内容已归档就删除。

本轮任务目录、derive、两轮原目录及宿主回归的累计 `st_blocks*512` 为 **3,056,017,408 字节**（写storage账本前），全部保留，实际回收 **0字节**。当时项目文件系统可用 **1,954,871,087,104 字节**，开始可用 **1,957,991,510,016 字节**；净可用变化不是任务回收量，reflink共享也不按文件逻辑长度推断。后续收尾精确读回见 integration `finalize.json`，其收据保留最终目录与报告新增量。

保留原因：前像用于回退；当前derive供下一运行消费者；两个原失败和解码证据供发送路径调查；宿主批次供主会话复核。回收条件为新消费者接管、证据核收及精确身份/活引用审计。两个QEMU及其driver/supervisor均已退出，两个原run目录无socket节点，租约按收据关闭。没有真实设备、没有QEMU信号；未执行文件回收。报告使用docs-generator的Evidence→Finding→Path结构，flavor=null；相邻tool-index缺失，全部实际工具按已有入口核对。
