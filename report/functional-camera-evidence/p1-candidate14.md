# P1 第十四跑：日期确认后的 Backup 回复分配阻塞

本轮仅在隔离本机 QEMU 复用第十三跑的环境和原 App32 输入，未修改产品源码或固件，未访问真实设备，未委派。原首设的日期确认后，`AppBackupDaemon` 在虚拟 Backup 公共发送回调内申请 4096 字节回复时，持续等待原 UIPC 内存池。这是当前同步未完成的直接阻塞位置；**尚未证明消息泄漏、具体池耗尽原因或唯一的显示故障原因**。拍摄写卡仍未完成。

证据根：`scratch/a7c2-capture-p1-runtime-20261115-candidate14/`。第一轮 `786e` 保留诊断失败；唯一重试 `8e9b` 在 `retry-1/`。正式核收入口为该根的 `assessment.json`、`storage.json`，线程与地址解析为 `retry-1/passive-analysis.json`。本文不把受控 AP 软件显示当成真实 CP、完整启动或物理相机通过。

## 原始同步语义

`MENU_BACKUP_SYNC=virtual-primary-v1` 不直接写 AP pending 位。原 AP `0x2f3ac5c`（另有 `0x2f3a99c`）设置字节 `0x8838af8=1`，排入带同步标记的 `0x12` 事件，随后等待条件变量 `0x8854a10`。`AppBackupDaemon@0x2ff07ac` 消费该事件，经 `0x35aa8dc` 调原 `Backup_sync_all`；只有该调用及包装返回后，才清 pending 并 `notify_one`。事件 `0x11` 的 subsystem 同步也使用相同完成出口。因此单独 pending=1 既不能证明是哪一种事件，也不能证明原调用已发送 CP 请求。

生产的 sole public sender 位于 `report/virtual-cp/udate-distribution/client.c`，将目标 `0x903e0811` 转交 `backup-endpoint.c`。后者严格校验原 40 字节、opcode `0x30` 请求，申请独立 **4096 字节回复**，stage3 冻结并完整读回虚拟 PCI primary，stage0 在 DMA 完成标志满足后解锁，按原动态 source queue 发回复。它不会替原 AP 清 pending。`menu-observe.c` 中直接对 `0x003e014d` 回成功的旧分支仍为 `if (0)`，本轮没有启用。

## 运行证据与先后

复用 QEMU b369 和 `derive-prod-10f203e5529612d0`，RAM CPIO SHA256 `75ba3158e3d4312b025bd10e029359a2ae8bfcd4dc4acb4a7e05fe67bbfb09c8`。guest 整卡 SHA、环境准入和正常退出分别以最终收据核对。输入仅重放第十三跑动作1至37，在动作32、36、37及延长窗口做被动采样；不 ptrace、不 SIGSTOP、不写 pending/EE/模式字段。

- 日期确认前的 `after-32`、`after-36`：pending=0，EE_START_ENABLE=1，EE_STATUS=0。AppBackupDaemon 的原栈候选包含 `0x2ff0874`，与 daemon 的空队列条件等待一致。
- 日期确认后：第二次 UDATE 完成；温度提示 screen `0x1db` 已创建，但原 LCD 保持日期编辑。AppBackupDaemon 转到原 `Backup_sync_all` 的内核路径，并在虚拟 public callback 的回复分配等待。随后延长观察检验是否持续，最终帧/时长/计数见核收收据。
- 启动早期 generation1 的 stage3/0 两条 `BACKUP_K_REPLY` 都存在、faults=0。日期后的阻塞发生在下一次分配回复之前，不能把早期回复复用为这次的完成证据。

阻塞内核栈的关键连续部分为：

```text
vpool_alloc+0x110/0x220 [osal_uipc]
osal_valloc_msg_wait+0x134/0x190 [osal_uipc]
udate_sender+0x408/0x1830 [sony_udate_distribution]
osal_snd_msg+0x1a0/0x238 [osal_uipc]
backup_get_cp_data+0x3c/0xf8 [backup]
Backup_sync_all+0x64/0x128 [backup]
backup_osal_call_func+0x3cc/0x548 [backup]
backup_put_cp_wt_data+0x23c/0x248 [backup]
uipc_oom+0x88/0xce0 [osal_uipc]
__osal_snd_sync_msg+0x17c/0x260 [osal_uipc]
```

完整原栈保留 `uipc_oom+0xa84` 和未命名的原 backup helper 帧，没有把其省略当成完整 unwind。被动用户栈只列原始代码字候选，不是经寄存器认证的调用链。所有线程保留 syscall 前后是否一致和未采到稳定 syscall 的错误，不把运行中的线程误报为采样成功。

`module-provenance.json` 对已准入 CPIO 逐成员哈希确认，实际装载的 `sony_udate_distribution.ko` 与所反汇编模块相同，SHA256 `1300b44c53834e1cbb9492e53641a894b42002a909231662792faa99b637b9b5`。符号 `.text+0x7d0` 为 udate_sender，`+0x408` 返回点即 `.text+0xbd8`；前一条 `.text+0xbd4` 调 `osal_valloc_msg_wait`，参数 `w2=0x1000`、`w3=1`。对应源为 `backup-endpoint.c` 的回复分配行。原 `vpool_alloc+0x110` 对应 `schedule` 返回点；其前序查找未得到可用块才入等待队列。**尚未读取具体 pool 指针、总量、可用块或持有者，不能判定是泄漏、碎片化、资源配置不足还是未消费消息累积。**

## LCD 与模型修复输入

原 screen 创建不等于显示。现有 manager slot3 只排队；`libObj.so@0x17da9c WidgetSystem::notifyDraw` 检查 `this+0xa3c`，再访问活动 widget。`drawFramebuffer@0x174dbc` 还要完成 graphics engine 更新、dirty-content 判断、GRM 输出/交换。现有 headless 模型必须接收 `1002` fix 和 `1003` 像素或 `1005` metadata，将完整容器持久化并读回后才发送 `6003/6005` ACK；失败会报 `OSD_HEADLESS_FAILED`，本轮没有用渲染强制调用绕过它。

AppFw、ExternalOSDIF、grm_result、grm_gpe 与 AppBackupDaemon 都已纳入日期前后采样。精确稳定等待与原帧摘要见最终核收。当前证据支持先修 Backup 消息资源生命周期，再验证原 UI 是否自然恢复；不能仅凭同时发生就把 GRM 独立问题排除。

下一修复应从当前回调的 **4096B 回复分配与原 UIPC OOM/Backup 同步重入** 开始：核 pool 身份与空闲块、请求/回复 ownership、未消费队列及释放路径。若要预留回复或改异步处理，必须保留原 4096B reply/source/type、冻结→DMA→解锁顺序、原消息所有权和失败保全，不能缩成40B、直接置成功或清 pending。若要改变分配模式，需先核原 API 对非等待/独立内存与 `osal_snd_msg/free` 的合同，不能把普通 kmalloc 冒充 OSAL message。

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| 两份日期前 passive、原线程栈与 pending=0 | 同步完成位起初清，daemon 可空闲 | 首设页面→原事件队列→daemon |
| 日期后及延长 passive 内核栈、pending/帧读回 | 当前调用停在虚拟回复的池分配，未到本次回复/clear | 原保存→Backup_sync_all→public sender→4096B allocation wait |
| 准入 CPIO 成员SHA、模块 relocation disassembly | 精确调用与源码吻合 | 实际 guest 模块→udate_sender+0x408→backup-endpoint.c |
| 原 libObj corpus 与 headless-osd.c | 创建 screen 与实际显示/ACK 是不同阶段 | 原 UI→notifyDraw→drawFramebuffer→GRM/OSD→持久化ACK |

## 核收与材料

两组、两个工作线程核收通过：两轮均 QMP quit 确认、QEMU rc0、租约保持到退出、runner closed、无信号、产品源码稳定；原日志与复制件逐文件 SHA 相同，QEMU owner 均已消失。两轮 guest 全卡 SHA 验证通过。首轮保留 `/proc/maps` 被内核警告拼行导致的诊断失败；唯一重试仅抑制诊断控制台内核输出并收窄目标线程，功能环境只变 TMPDIR。重试 driver rc2 保留 `Functional broker never attached`，未改写成功。

七组被动采样完成：日期前两组 pending=0；日期后及四组延长窗口均 pending=1，AppBackupDaemon 每次都停在 `vpool_alloc+0x110 → udate_sender+0x408`。AppFw 主线程的原栈候选为 `0x2f3aa30 → 0x24cce7c → 0x1e78eb8`，与原 presenter `process_event` 中同步提交屏障一致。动作37及51–54全部 sequence=271、完整帧 SHA256 `b2eb1340e593c8a85fb088feae9e93c7edacefd470290e250595d45ea8907219`，OCR 为 Date/Time；温度页已创建但没有显示证据。两次 UDATE 完成；仅早期两条 Backup 回复，日期后无新增回复。MODE_TRANSITION、ENTER_REC_STILL、0x90050004 请求、Imaging三业务均为0；mailbox/debugger/broker仍为false，未观察到原 AP ASSERT_CALLER。

`storage.json` 核收时新增保留实占 **185,163,776 B**（写账本和本次报告补文前统计），实际回收 **0 B，未执行回收**，项目文件系统可用 **1,961,930,641,408 B**。两个可写私有 profile 为恢复身份依赖保留；原 run 的失活 socket 路径待父会话核收，未声称这些依赖已完成回收。原始失败、stdout/stderr、被动读回、像素和脚本归父会话模型修复及恢复审查消费；st_blocks 合计不声称 reflink 独占。真实 CP、完整冷/热/WBI 启动、拍摄及写卡均未验收。
