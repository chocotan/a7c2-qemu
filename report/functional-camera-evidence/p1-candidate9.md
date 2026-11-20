# P1 第九跑：修正 RAM 卡逻辑位置后原 Fsys 挂载成功，前沿转为 EE 入口未完成

本轮只在独立虚拟状态上运行一次 QEMU（`runtime/analysis/menu-runs/7161`），把运行器强制的 `MENU_RM_FILE_SLOT=0` 改为已有模型支持的 `1`，使单张虚拟卡与原媒体配置的 `/nondev/rm2` 对齐。**原 `mcmn_drv_open` 和原 `Fsys_Mount` 均成功，BB:906 与 Imaging:3109 两个断言本轮没有复现。** 但功能 broker 在预算内未建立，mailbox/debugger handoff/拍摄写卡均未通过，不能把挂载成功记为 P1 全部完成。

调查也纠正了一项历史日志误读：callback 的实际队列号是 **`0x0184e0d9`**，属于 NFC 动态回调；朴素 printable-string 提取出的末尾 `1` 是下一条记录长度 `0x31` 的首字节。`FFFFFC04` 是错误码 `-1020`，不是函数或缓冲区地址。

## 范围和输入

委托范围为第八跑的 Imaging 请求路由、callback 注册失败和 DMM/媒体挂载线索调查，随后一次最小环境/配置对照。没有进一步委派，没有修改产品运行源码、原固件、QEMU 二进制、共享 CPIO、历史失败结论或旧收据，也没有连接真实设备。使用 docs-generator 普通技术报告结构，`flavor=null`。

复用只读 QEMU `b36998138a65b1bd2645ca24bf0dde0c0801d868d1291ec6f9e83ff707d64bad`、RAM CPIO `74c708dca7098651cc01bf7ddbcd34e76d7f1e105f52e9b7ddbc58ece758c5ca`（1,492,625,848 字节）和生产 seed `71362dfd3446d9de01fc59f1614d1dd7944a88cae19f2d70261f16e41e7e7888`（1 GiB）。独立 profile 的精确映射见任务 `profiles.json`；DTB 实际 DDR 为 8 GiB。

任务脚本、原输出、归档和账本位于项目根 `scratch/a7c2-capture-p1-runtime-20261115-candidate9/`。

## 静态调查

### 三条 Imaging 连接由原 AP 消息触发

ABI 与软件成像核心本身不生成这些连接。`runtime/analysis/menu-observe.c:11132` 起的发送截获调用三个模型；目标必须是 `NATIVE_INFRAIMAGING_CP=0x90050004`，由原 AP 发出 64 字节 Dataflow 信封（魔数 `0xa0a0a0a0`、inner `1000:0001`、flags=2）。三个模型只消费约定的 pin 对：

| 连接 | 原消息源 pin → 对端 pin | 必需前置状态 |
| --- | --- | --- |
| Imaging image | `{0,2,1,0x90050004}` → InfraBB `{0,1,1,0x9284074a}` | 原 AP 消费 BB set-mode 完成、两侧 registry 初始化且查询完成、pin 为冷态、池无活缓冲 |
| Imaging control | Imaging type8 control0 → InfraBB type8 control0 | 第一条连接 clean completion/AP consumed、格式已消费、缓冲已释放、marker 已确认 |
| Imaging audio | Imaging type3 audio0 → ADF type3 audio0 | 前两条连接及相应 ADF/registry/资源完成状态 |

dispatch 顺序为 audio → control → image。后两模型明确识别并跳过前面的合法 pin 对，再交给下游处理；没有因顺序发现必然吞掉 image 请求的证据。`infrabb-vef-connection.c:112` 的 `dependencies()` 继续要求三个 Imaging 连接完成以及 VEF/ADF/registry/资源退休状态，`enabled=1` 不能满足这些条件。

第八轮共提取 25 条 `OBS PIN_QUERY/PIN_CONTROL_REQUEST`，目标 `0x90050004` 的条数为 0。前三条模型日志也只有 constructor profile，业务事件为 0。这个证据支持“本观察范围没有进入三条接收路由”，不能直接证明某个 CP 硬件坏了，也不能排除原流程尚未请求这些连接。

### callback 的队列属于 NFC

原函数 ELF VA `0x358cf70` 在 `infra_wrapper_nfc.cpp:336` 打出同样的 `ERROR Regist qid fails` 文本。其 callback QID 存在 BSS `0x91193b8`，由 `0x358d410` 调用 `FUN_0369a1c0(1,0x184,&DAT_092193b8)` 动态创建；注册请求的服务目标为 `0x818104bb`，打印的 QID 是待注册回调队列，不应混作缺失的服务目标。

本轮按 16 字节 ulog 记录头的显式 payload 长度读回，原记录 offset=614857、length=89，文本结束于 `qid:0184E0D9`。下一记录长度 49（`0x31`）紧随其后，没有 NUL 隔开。历史报告里的 `0x184e0d91` 应作为旧误读保留，不能继续用作 Imaging 队列归属依据。`static-details.json` 含原记录、ticks、边界与 ELF/BSS/动态分配验证。

首次 ELF 检查误把 BSS 当作文件初始化值，返回 rc1；已保留 `static-details-first-failure.txt`，修正为零填充与原动态分配调用核验后通过。没有因此重启 VM。技能引用的 `field-journal/precedent-reverse.md` 和 `tool-index.md` 在当前包缺失；本轮复用已有本地语料与工具，没有自举服务或重开 IDA 数据库。

### BB/Imaging 断言是发送失败，且 Imaging 位于关机路径

原 BB 函数 `0x34e552c` 的 906 行检查 `osal_snd_msg` 返回非零，尚未进入 `osal_rcv_msg_tmo`；原 Imaging `0x35358b8` 的 3109 行同样在发送失败后断言，尚未等待 future。不能把函数名中的 `wait` 当成超时证据。

第八轮异常调用栈归一化后包含 `0x3545230`，落在 `0x3545064 set_zoom_drive`，其发送目标为 `0x90030001`、消息头 `0x40010005`；上层包含原关机相关调用，console 也先出现媒体错误和 `scr0039_shutdown`。这条断言并非三条 pin connect 的直接调用栈。BB 的该轮完整独立调用栈没有采集，不能替它推定确切命令。

### 媒体映射与 DMM

原媒体查询 transport/business 都成功且 valid=1，`mediaID=0x1000` 映射 `/nondev/rm2`。旧驱动的 launch 却强制 `MENU_RM_FILE_SLOT=0`；`rm-file-device.c:161` 说明 0=RM1、1=RM2，cmd9 仅在选定记录上报告卡字段，而既有 cmd2 接受 target `0x102`。本轮只改逻辑位置为 1，没有修改 mediaID、FAT、容量、RM 消息、原返回值或 callback。

DMM `alloc_core=-3` 可关联原 `0x62a` 分配，模型原日志显示两槽均持有、`handle=0xffffffff`、地址/size=0，分配者 appFw+`0x35522a4`。该失败本轮仍存在，同时媒体挂载已成功且原断言消失，因此不能单凭它解释前两轮 BB/Imaging 断言；其对后续流程的影响仍未闭合。

## 一次实际对照的结果

保留第八轮全部 MENU/guarded profile，仅 host TMPDIR 和 `MENU_RM_FILE_SLOT=1` 有差异。原驱动硬编码的 guest `0` 在任务包装器内替换为 `1`，原始完整发出命令保存在 `launch-config.json`，guest `launch.raw` 逐项读回。另在 guest 中启动只读 `tail -f /tmp/im.log`，使此前未保留的启动标准输出进入 console；不启用与 guarded profile 冲突的 GOT/同步/异步探针。

| 判据 | 第八轮 | 第九轮 |
| --- | --- | --- |
| `mcmn_drv_open(/nondev/rm2)` | `0x80000004`、空 handle | 两次返回 0、非空 handle |
| 原 MediaMount completion | `service_error=0x7fffffff` | `service_error=0`，原 waiter 消费与 free 返回 0 |
| 原 `Fsys_Mount` | 未成功 | `/nondev/rm2`、flags=`0x300`、rc0、A: |
| 原 `Fsys_GetFreeSpace` | 未成功 | rc0、drive=`0x41` |
| Imaging image/control/audio 实际业务事件 | 0 / 0 / 0 | 0 / 0 / 0 |
| InfraBB→VEF | predecessors_not_ready | 仍 predecessors_not_ready，requests=0 |
| InfraBB control→VEF | four_predecessors_not_ready | 仍四前置未满足 |
| BB:906 / Imaging:3109 | 复现 | 均未复现，ASSERT_CALLER=0 |
| broker / mailbox / debugger handoff | 未完成 | 100s host 预算超时，未完成 |
| 拍摄→JPEG→原写卡导出 | 未完成 | 未执行 |

Fsys 后续尝试打开 `A:/PRIVATE/DATABASE/DATABASE.BIN` 返回 `0x80000051`，目前不能认定为致命错误。成功挂载不等于已经生成照片，也不等于 runner 的“原 Fsys 同卡”内容/生命周期合同通过；旧布尔 `fsys_same_card_verified=false` 保留。

无异常时采集被动快照，不暂停线程、不写寄存器或内存。原 AP PID222，`SeqQueueCommon` tid348 处于 futex（syscall98），前后边界一致；4096 字节栈中的 AP 代码候选包含 `0x3209dc8/0x3209f10/0x36ec1b0`，**未做栈展开，不能据此宣称阻塞原因已证明**。EE_START_ENABLE=1、EE_ENTRY_SOURCE=0、EE_STATUS=0、BOOT_SHUTDOWN=0，Backup pending=0；记录状态 pending/current=22196/22195。新前沿是 EE/拍摄入口尚未进入，而非已复现崩溃。

## 验收、退出和下一消费者

`verification.json`：**2 个检查组 / 2 个工作线程通过**。分别核对源码前后及当前 SHA、精确环境差集、guest 实际导出，与原始/归档所有普通文件 SHA、guest 1 GiB 整卡 SHA、DTB 8 GiB、QEMU owner 身份、QMP quit、Popen rc0、租约到退出和 runner safe-to-close。QMP 使用现有事务唯一 ID；四字符 run 名，Unix endpoint 小于108字节。

驱动实际 rc2，原因 `Functional broker never attached`；QEMU rc0 仅表示受控退出。QEMU/launcher owner 已消失，无信号，runner 已关闭，consumer lease 保留到退出。没有第二次 VM 尝试，没有物理设备访问。保留原 Sony loader、WBI 恢复、原 CP RTOS、物理 ASIC/SD 的未覆盖状态。

下一消费者是主会话：将本轮 RM2 配置作为下一次运行基线；从原 EE 入口与未完成初始化/界面路径追查为什么没有原 `0x90050004` 连接请求；单独检查 database open 错误、DMM `0x62a` 所有权和真实 shooting-ready 前置。不要清掉这些依赖守卫，不要把 NFC 注册问题作为 Imaging 根因，也不要继续把后置关机发送断言当作首个异常。

| Evidence | Finding | Path |
| --- | --- | --- |
| `static-analysis.json`、`original-functions.txt`、第八轮异常栈 | 两处断言检查发送返回；Imaging 来自 set_zoom_drive | 媒体挂载失败 → 原 UI/shutdown → 后置发送失败 |
| `static-details.json`、原 NFC 动态创建/注册源码、ulog 89B payload | QID=0x0184e0d9，NFC callback；末尾1为下一条长度 | ulog header → 精确文本 → 源码行336 → NFC queue owner |
| `preflight.json`、`launch-config.json`、`launch.raw`、原 RM/Fsys 日志 | RM2 对齐后原挂载与 completion 成功 | 单卡配置 → cmd9 RM2记录 → cmd2/原open → 原Fsys/原waiter |
| `wait-analysis.json`、`ee-passive-6k9ohrxv/result.json` | 断言消失，Imaging业务仍0，EE入口未完成 | 原AP继续 → Common被动采样 → mailbox/broker未建立 |
| `verification.json`、`driver-exit.json`、consumer receipt | 业务未完成，owner正常退出 | QMP quit → rc0/wait → lease结束 → runner关闭 |

复现入口为任务 `verify_runtime.py`（复用第七轮的只读运行器）；运行会创建新 VM 和独立 profile。封口收据使用排他创建，复现必须复制任务脚本至新的专属任务目录并同步 TMPDIR/前一轮映射，不应覆盖本轮文件。

**未执行回收，实际回收0字节。** 本轮独立 profile、唯一失败/等待现场、全部原日志和必要归档保留供主会话核收；非活 socket 随原 run 路径保留。逐项长度、完整 SHA、device/inode、实际分配、owner、下一消费者及回收条件见 `storage-final.json`，其中共享只读 QEMU/derive/CPIO 不计新增。账本和报告本身保留，不把可删候选量算作已回收。
