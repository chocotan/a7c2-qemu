# P1 第四十八跑：JPEG 空闲观察器拖慢原 UI 输入

本轮先复用 candidate47 的第三轮诊断入口，确认 `INPUT_EVENT32 n=78` 是有限观察窗口内的停点，不是已证实的永久卡死。延长等待后原 AP 消费推进到 n=84；四条快门仍在后面排队。只读线程栈直接落在本项目的 JPEG 接收观察器：普通按键每次接收都扫描 `/proc/self/maps`。已为 JPEG 空闲或目的队列无关的接收增加提前返回，实际 JPEG 作业继续走原有源、大小、信封、地址、生命周期校验。新镜像的运行消费验证进行中；`capture_verified=false`。

范围与授权见 [scope.md](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate48/scope.md)。仅本机隔离 RAM 卡和 direct-bootin AP 诊断，不改固件、EE、拍摄禁止或镜头状态，不操作真实设备，不再委派。文档按 docs-generator 的普通逆向结构（flavor=null）记录。技能引用的同级 tool-index/field-journal 文件缺失，分析使用已存在的源码、运行器和离线符号工具。

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| `baseline-input.json`；candidate47/runtime-2 run69d6 console | 原窗口只看到 n78；86 次提交不能当作86次原 AP 消费 | 原 App32 发送 → 队列 → 原接收 → dispatch 分别验收 |
| `diagnostic-final-input.json`；run6c90 原 console | 延长观察到 n84，仍未见半按/全按消费；没有证明原输入线程永久停止 | 推翻“n78一定卡死”，保留积压与慢处理证据 |
| `runtime-3/ui-sequence-post-shutter.raw`、`post-shutter-stacks-va.json` | AppFw tid334 栈为 libc read/fgets → JPEG `memory_access` → `read_object` → `functional_jpeg_codec_observe_received` → `native_cp_state_received` → `osal_rcv_msg_tmo` → 原 AP `0x1799a48` | 本项目的空闲 JPEG 观察器挡在普通输入接收返回前，拖慢输入消费 |
| 原源码 `functional-jpeg-codec.c` 的 receive 路径 | enabled 后先校验 transport 与 reply，扫描 maps 后才看 pending；此前没有空闲/目的队列前置过滤 | 最小修复：持锁检查 pending/qid，无关时返回；实际事务校验保留 |
| StillCa tid379 栈 `appFw+0x34ae1a8 → 0x3209e48`；Common tid377 `0x3209dc8` | StillCa 已越过初始媒体等待返回点 `0x34ae0cc`；采集器的 UNAVAILABLE 与栈不匹配相符 | 不能把 unavailable 当成媒体失败或改写初始化位 |
| `candidate47/exit-review-3.json` | 诊断 QEMU 经 quit 后 rc0退出，runner/worker/detach/mailbox关闭；原 QMP EOF 失败保留 | 可进入下一独立运行；原 driver 状态不回填为成功 |

栈解析初稿错误地把 RX 映射的文件 offset 当作 ELF VA，在 load gap 存在时地址差 `0x10000`。已修正为零 offset 映射的 load bias，加入对应自检；采用 `*-stacks-va.json`，保留初稿以说明否定结论。observer PT_LOAD RX 的 offset/vaddr 确为不同值。AppFw 原基址与 JPEG helper 运行地址由实际 `/proc/<pid>/maps` 决定，不用历史基址猜测。

## 实现与验证

产品改动位于 `runtime/analysis/functional-jpeg-codec.c`。新增的 pending/qid 快速过滤在 process guard 之后、所有用户指针读取之前；实际消费时仍在现有锁内重新核对 pending 状态。无需新增依赖或绕过边界校验。测试以不可读地址验证空闲和其他目的队列均不检查无关消息，同时现有正常、拒绝、过期、跨进程、回复 free、原 Main/THM done 生命周期保持覆盖。

首轮宿主检查由2个线程执行2组：JPEG 229项通过；接线/槽位2963项通过，但44项参数路由测试因旧夹具漏 `stdlib.h` 和新增 background dispatch 声明而编译失败。保存原始失败及输出，修复测试夹具后只重跑这44项，全部通过；未重复未变已过的 JPEG 重型回归。重建与原 CPIO 成员集合、权限检查通过，CPIO 仅 observer 内容改变。

新 binding：`derive-prod-bdc968b1d0a9aa5c`；observer SHA256 `7ad24be31590ca97b56793e0077c90dbc9821f96dc978cfd49acdb73d83df3cb`；派生CPIO SHA256 `3b7875a6a72ba819792e9981384235d4de04751b84fde8d6652bd1a9070e027c`。运行目录为 `menu-runs/bac2`，驱动材料在 `candidate48/runtime-1`。

私有驱动新增 `shutter_receipts.py`，只承认原 `INPUT_EVENT32` 的半按1、全按1、全按0、半按0完整顺序，投递成功或脚本回显均不能满足。等待上限120秒；完整消费后仍需独立验证自然4038、capture、JPEG与两次导出。初始诊断和修复运行均保留1秒按键保持、快门前后只读线程采集；ptrace会短暂停guest线程，调度影响不能排除。

## 运行验收与剩余边界

修复镜像运行尚在核收。自然4038、JPEG、Fsys写卡和 P4 `JPEG_ONLY_PASS` 均未取得通过证据。原 CP handler执行、物理ASIC、Sony loader/WBI和真实看门狗不在本轮覆盖内。不存在“接收退休即完整 CP 语义完成”的提升。

本任务入口 `candidate48/run.py` 首轮保留验证失败，`--resume` 只在该owner退出、原诊断独立关闭已证明后继续；没有复写首轮结果。最终两线程/两组核收入口是 `candidate48/finalize.py`；最终存储与资源账本另见本任务 `storage.json`。原日志、前像、失败输出、当前derive和复现脚本为父会话核收与下一前沿的必要材料；未执行回收，实际回收0B。
