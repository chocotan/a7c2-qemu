# P1 第四十七跑：半按锁与 release-key 接收前沿

本轮接通 capture SID 的 `0x4036 set_still_lock` 请求接收与释放，原 AP 实跑 4 次消费后推进至 `0x40de`。第一轮 `5781` 的 `0x40de` 返回 `-1020`，随后进入原固件异常监视器；任务 owner 使用独立且经过身份校验的 QMP 客户端执行 `quit`，独立 RAM 消费者收据确认 rc0。原驱动的失败和缺失的生命周期标志保留，没有回填。第二轮已补 `0x40de` 接收并启动验证，结果待本页后续核收。`capture_verified=false`。

范围是已授权的本机隔离 QEMU、独立 RAM 卡和原 App32 操作。不接真实相机或物理磁盘，不改 AP 状态、EE、exclusion 或镜头状态。入口继承 candidate45/runtime-3 的 direct-bootin 诊断路径，不能代替原 Sony loader、WBI、真实 CP 或硬件看门狗。

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| candidate46 `recover-4266-evidence.json` | 原 capture 发送 `4036/16B` 返回 -1020 | 缺失接收端 → Imaging:3109 → 异常监视器 |
| 本轮 `source-audit.json`、`still-lock-helper-audit.json` | AP `0x353a280` 构造 16B；CP `0xae18f2` 读取 token/kind，设置 kind 活跃和 token，再经 RelMgr/`0x3031` 驱动异步路径 | 接收、状态意图、内部对焦控制、AP 异步通知是分别需要验证的环节 |
| `5781` 的 `NATIVE_CP_BACKGROUND_SLOT_RETIRE opcode=0x4036` | 4 代请求，free rc0、retired=1..4；无分配或合成回复 | 只闭合原请求所有权，不声称执行原 CP handler 或半按锁完成 |
| 第一轮 `P18_OSAL_RESULT opcode=0x40de` | capture SID、12B、wire `0500de406c00008002000000`、rc=-1020 | 原 AP 已越过 4036，新的 release-key 接收缺口 |
| `40de-audit.json` | CP `0xae17d8`，6 槽类型表 `0xce7550={0,1,0,0,0,1}`；状态变化可在内部生成 4036 或 4038 | 只接收该请求不能冒充内部拍摄或 AF/AE 完成 |
| `runtime-1/owner-recovery.json`、原 run RAM 消费者收据 | executable SHA、socket peer uid、`/proc/<pid>/root/out` 的设备/inode均核对；query-status 后唯一 ID quit；进程退出；独立消费者 rc0；零信号 | 原失败不改写，恢复事实另立 |
| `final-verification-1.json` | 2 线程/2 检查组，97 份归档完整 SHA 读回，guest observer 摘要、broker attach、UPM 收据及恢复核对通过 | 接收与恢复验收通过；business_passed=false |

实际 wire `050036404200008004000000ffffffff` 的 token 是 **`0x80000042`**，kind 是 `4`，参数是 `0xffffffff`。不能把 token 的低字节 `0x42` 和第 8 字节的 kind 混成 32 位参数。

CP SHA256 为 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。AP SHA256 见 `still-lock-helper-audit.json`。原输入保持只读；报告不复制固件或批量原始日志。

## 实现与限制

产品修改仅在现有 `runtime/analysis/device-models/cp-background-device.c/.h`、`device-models/test_cp_slot_retire.c`、`test_cp_slot_retire.py`。增加 `4036/16B`、`40de/12B` 两个 capture SID 接收槽，复用既有来源、长度、owner、重入、free 失败、跨 fork 和请求别名保护；40de 的 key>=6 拒绝。每代请求保留首份和最近 wire，回收原消息，不分配 ACK。

日志持续写明 `handler_executed=0 completion=0 original_CP=0 capture_verified=0`。`4036` 另记 token/kind/argument、`kind_state_updated=0 lock_start_notified=0 lock_complete_notified=0`；`40de` 另记 key/value、`key_state_updated=0 internal4036_delivered=0 internal4038_delivered=0`。这些是**接收与请求退休**，不是完整的 CP 语义实现。第一轮专用 pending tag 未在 observer allowlist 中，所以第二轮将其命名置于已有 `NATIVE_CP_BACKGROUND_` 前缀下；通用 SLOT_RETIRE 行在两轮均可见。

测试用实际 4036、40de wire 验证保留、重复调用与零回复，覆盖 free 失败、来源/尺寸拒绝、重入、同地址复用、fork、并发、generation 溢出、全部 65536 capture opcode 路由，以及 40de 全部越界 key。两次重建各用 2 线程/2 组宿主检查：6 个测试和 22 个子测试通过。先前各 opcode、参数 owner 与 face 接线保留。

任务级 `capture_exports.py` 复用生产 `sd_transport` 与 `sd_export_lifecycle`，只在 console 已出现自然 `4038` 作业时，通过原 Fsys flush、两次完整 RAM 卡导出和 proof 链，在 QMP quit 前提供 READBACK/COVERAGE 闭合机会。其 synthetic 自检通过；它本身不是完整 P4 证据入口。运行级 manifest、冻结 batch 和 `JPEG_ONLY_PASS` 仍须按原 checker 验收，不能由这个适配器推断通过。

## 复现、恢复与资源

任务材料在 `scratch/a7c2-capture-p1-runtime-20261115-candidate47/`。`prepare.py` 保存四份源码前像并完整读回；`run.py` 复用既有 candidate34 构建/CPIO/derive 主管线，以当前 observer 与派生镜像 SHA 绑定第一轮。`next.py 2` 仅在上一 owner 已安全关闭或独立恢复证据完整后续跑；显式 rebuild 收据对应新的原始前沿。构建和当前实例保持串行。

`recover.py 1` 仅在原 `retain_running_owner` 已打印本轮 PID、停止串口操作而等待 owner 退出后允许执行。它核 socket peer、UID、run 目录设备/inode和 QEMU 完整摘要，拒绝关闭尚未退休的自然拍摄作业；发送 query-status 再发一笔唯一 ID quit，不发送进程信号。独立消费者的 rc0 和 detach/runner cleanup 由 `finalize.py 1` 再读回，不改原失败收据。

生成前预算为实际可用空间至少 64GiB 余量加 12GiB 峰值；每轮 integration/budget.json 记录实际字节。新增、保留、实际回收与可用字节由 `storage.json` 记录；原日志、源前像、失败现场与必要 derive 身份绑定保留供父会话核收，未执行回收。
