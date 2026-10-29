# Movie 同步 Fsys 写入追踪：API 与原字节证据

**当前交付状态：真实 runtime wrapper 接线已实现并由主机组合测试执行；初始 extent/source lease、最终 MP4 和 checker 接口仍未闭合。**
本轮只修改 `file-media-config.c`、必要的共享同步 API、专属 C/Python 测试与本目录 README/source-pins 增补。使用 public ALLLANG ELF 和本机测试临时文件；没有 VM、DSO build、完整回归、真机、真实 SD 或私有 dump。`capture_verified`、`media_origin_verified` 保持 false。独立的 host fixture 不能证明原 AP 已自然执行 movie worker。

## Runtime 接线增补（2026-10-28）

授权范围为本轮用户指定 owner 文件和两层 `AGENTS.md`；`network_profile=offline`，`flavor=null`。a441 的原始 API/source 记录保留在后半部分；其中“尚未接线”是前轮状态，本节为当前状态。原 `source-pins.json`、校验器、旧收据与其它 owner 文件均未修改。

### 实际调用闭包

[`file-media-config.c`](../../runtime/analysis/file-media-config.c) 直接复用 `fsys_sync_trace_*`，没有新增一套 ledger 或构造函数：

| 原路径 | 已接线行为 | 原调用约束 |
|---|---|---|
| `Fsys_Open` | 原调用前逐字节安全冻结 NUL path、generation/context；成功后安全复制 u64 输出 handle，建立 lifetime | 原 Open 一次，原 path/output/flags 不变；失败不读 handle |
| `Fsys_Write` / `WriteAndFlush` | before 解析 token，`write_begin` 冻结 virtual x1；after 第一时间保存 rc/errno，再 `write_end` | 原源指针/count 不变，各一次；返回后不再读原源 |
| `Fsys_Seek` | before token/context，after 仅安全复制原成功输出的 u64 position | 不插入 Seek；原失败或输出不可读拒绝 known position |
| `Fsys_Read` | before 显式 invalidate 对应 writer，避免继续使用旧 cursor | 不添加 Seek，不推算位置 |
| `Fsys_Close` | before token，after 原 rc/errno/实际 generation，观察关闭 | 不强制或添加 Close |
| `FTruncate` / `WriteFile` | 未建模 mutation before/after invalidate；记录实际 mutation rc/errno | 保留参数/次数和原 hotplug_io 包围 |
| `Combine` / `Rename` / `Remove` | 正向确认 ABI 后透传并 invalidate；不重建 finalizer 文件映射 | 各一次原调用，原参数，保存原 errno |
| Mount / Unmount | invalidation 与下述真实挂载事件代次；Unmount 不由观察器发起 | 保留已有热插拔 mask 查询和 owner/drive 状态 |
| `WriteDirectFileAsyncV2` | 旧 async 流程保留；同步 ledger 在前后 invalidate，避免异步 alias 冒充同步全覆盖 | 原 submit/callback/worker 仍是原接口 |
| 原 flush 后 | 同一进程/代次且无原 I/O inflight 才进入 `readback_all`，复用单文件原 Open/Read/Close 检查 | 原 pending 路径仍是原先的一次 flush + opt-in 读回后的第二次 flush；hotplug 路径仍一次 |

所有原操作前恢复 incoming errno，after 先保存原 rc/errno，观察结果不替换原返回。`FSYS_SYNC_MUTATION` 记录失败也可能修改文件的未建模操作，reason 为负数：2001 Mount、2002 Unmount、2003 Open 跨代、2004 普通 Read、2005 FTruncate、2006 WriteFile、2007 Combine、2008 Rename、2009 Remove、2010 async alias、2011 flush 代次/I/O 不稳定。具体 reason 由 `FSYS_SYNC_INCOMPLETE observation_rc` 输出。

### generation 与 unknown 的含义

`rm-file-device.c::native_rm_file_media_generation()` 直接转发 `native_sd_hotplug_generation()`；后者只有 hotplug enabled 且当前 pid 是 owner 才返回 epoch，否则为 0。因此 functional 未开启 `A7C2_SD_HOTPLUG` 时不能使用该值作为已知代次。

同步观察复用 `A7C2_FSYS_ASYNC_OBSERVE=1`，默认不启用，不增加 `/proc/self/mem` 探测。首次真正 opted-in Fsys 调用才绑定 observer pid。没有 hotplug 时，只有原 `Fsys_Mount` 返回成功、before 冻结的路径确认为 `/nondev/rm2` 或 `/dev/mmca`、安全读取输出 drive 后，才推进本进程的 `observed_mount_generation`；成功的 owned Unmount 使旧代次失效。每次事件发 `FSYS_SYNC_MEDIA domain=observed_mount`。它是**观察到的挂载事件域**，不宣称 native hotplug 或物理卡身份。已启用 hotplug 时仍使用 actual native epoch，0 保持 unknown，不回退编造值。没有观察到 Mount（包括后来才启用 observer）、继承 owner、失去 drive、Open 路径不属于 before 挂载 drive、跨代都拒绝完整性。

已有 mounted owner/drive 原子状态继续负责 flush admission。fork 子进程不复用父 observer；共享 API 也在触碰状态锁前拒绝继承 pid，包含父进程冻结时持锁 fork 的情形。

### 共享 API 的最小增量

[`fsys-write-trace.h`](../../runtime/analysis/fsys-write-trace.h) 原签名保留，新增 `fsys_sync_trace_readback_all(generation, flush_rc, flush_errno, ops)`。它只在锁内 snapshot 已关闭 lifetime IDs/handles/epochs，然后逐个调用原单文件实现；未知/跨代、仍打开、无候选均不能返回完整成功，锁不跨原 callbacks。wrapper 不重复维护文件列表。

未知 source allocation/lease 时，`write_begin` 仍在 128 MiB/1024 tickets/32 lifetimes 预算内通过 `/proc/self/mem` 冻结实际 requested span；`extent_known=0` 保持原样，不把 count 当 allocation extent。若原 result 是合法非负实际长度，`write_end` 可发冻结源的真实 actual-prefix 摘要和 `source_complete=1`，同时 `observation_rc=-ENODATA`、`full_write=0`、文件永久 incomplete。这里 `source_complete` 仅表示 requested span 已安全冻结；不证明 lease 或文件全覆盖。预算用尽照常拒绝，不复位、不掩盖、不取样伪通过。

原 `FSYS_CONTENT` 格式与 gate（hotplug generation>=3、最多 256 次）保留。Write 的 legacy 内容也只读 before snapshot，Read 对原输出走安全自内存复制；不再 return 后裸读原 Write source。两个开关同时启用时 legacy snapshot 单独有界，可能额外占用一个请求大小的内存；它不产生同步完整性结论。

### Source proof 与未完边界

增补 [`wiring-source-pins.json`](wiring-source-pins.json) 在相同 SHA-256 public `libInfraFsys.so` 中 pin 4 个窗口：

- `Fsys_Combine 0x35954..0x35a48` 保存原 x0/x1，自己设置 w2=0 后调用 `0x2e5e8`；下游 `0x2e694..0x2e6dc` 将两个原参数分别传给 `fsys_CreatePathInfo`。闭合 ABI 为两个 path 指针与 int 返回。
- `Fsys_Rename 0x33e7c..0x34114` 保存原 source path/new name，后面经 PrFILE/TNtfs rename；`Fsys_Remove 0x33978..0x33b44` 只保存原 x0，原 x1 在使用前覆盖。

初始文件 extent/position **未被证明**。原 Open 的写 flags 到 backend fopen mode 仍有条件改写/分支，未完成完整正向证明，故所有 runtime Open 都传 `size_known=0, position_known=0`。原实际 Seek 可以证明后续 cursor，但不会证明初始大小。不得从 `.BIN/.RSV/.MP4` 文件名、flags 常识或成功 count 推断空文件；因此本轮正常 wrapper 收据仍是 partial，readback checker 会在 unknown extent/lease 处拒绝，不额外调用原 Open/Read/Close 来绕过证据缺口。

`Combine` 当前只可靠 invalidate。原 finalizer 的最终路径/extent、`CombineV2`/`RemoveAll` 等尚未 source-closed 的 aliases 不猜 ABI；未覆盖 mutation 和命名别名仍是功能/完整性边界。后续若要允许 runtime 完整结论，必须先补真实初始 extent/source lease 证据并闭合这些 mutation。现有 host/media checker 对 `FSYS_SYNC_*`/`domain=observed_mount` 的 ingestion 尚未接线；不能把同步 receipt 当成已通过旧 async checker，不能称最终 MP4、host commit 或独立解码通过。

### 定点验证

从本成果根目录执行：

```bash
python3 -B report/native-movie-write-trace/verify_source.py
python3 -m pytest runtime/analysis/test_fsys_sync_wiring.py runtime/analysis/test_fsys_write_trace.py runtime/analysis/test_fsys_async_observer.py runtime/analysis/test_fsys_hotplug_generation.py runtime/analysis/test_fsys_flush_barrier.py runtime/analysis/test_fsys_unmount_trace.py -q
```

`test_fsys_sync_wiring.py` **包含并编译实际 file-media-config.c translation unit**，链接真实 trace；用 fake original dispatcher 和重定向临时文件执行原 wrapper。24 个 mode 分别在 `-std=c11 -O1 -Wall -Wextra -Werror` 与 ASAN/UBSAN 下运行：逐个验证原参数/调用数/errno、before path/source 在原调用内 munmap、短写、原错误、不可读 path/source/Seek 输出、budget、跨 native epoch、无 hotplug 的实际 Mount/Unmount、晚启用时 unknown epoch、错误 volume、fork、每类 mutation、STOP/cancel/原 flush 次数、pending 与 hotplug flush 后原回读。仅独立注入已知 extent/lease 的 host fixture 会产生 `content_verified=1`，测试没有把 runtime Open 的 unknown 改成 known。

共享 C fixture 从前轮 57 扩到 62 mode：增补 `readback_all` 正常/旧代次/flush 错误/unknown generation，以及**冻结持锁期间 fork** 的拒绝；原 57 场景保留，unknown-extent 场景新增真实前缀摘要检查。共享 fixture 使用 strict C11 `-pedantic -Werror`，两种构建均运行。原 verifier 仍是 8 ELF windows/5 PLT，增补 4 个 mutation windows 由新 pytest 独立校验。

本轮初始检查的失败是 fixture 预期未适配 unknown-extent 冻结和跨代拒绝，以及一处测试摘要常量错误；均在定点测试中修正并重跑，不修改原返回/证据来通过测试。最终结果：**16 pytest passed、52 subtests passed**；实际 wrapper **24×normal/SAN**，共享 API **62×normal/SAN**。同节命令可以复现；没有提交、全量回归、DSO/dual ABI build 或 VM 实验，集成构建与真实 AP 同轮运行交由主会话后续统一验收。

| Evidence | Finding / confidence | Path / 状态 |
|---|---|---|
| E-runtime-wiring：实际 file-media-config.c + 24×2 mode 组合测试 | F-wiring / high：真实 wrapper 调用了共享同步 API；原调用参数/次数/errno 保留 | 原调用前冻结 → 原实际 rc → 同 lifetime Close → 原成功 flush → 原读回 checker；host 已执行 |
| E-mutation-abi：wiring-source-pins.json 的 4 窗口与同 ELF identity | F-mutation / high：Combine/Rename/Remove ABI 可以透传；内容变更尚未建模 | mutation 触发 invalidation，最终 MP4 未验证 |
| E-generation：rm-file-device/sd-hotplug-runtime 正向源码 + 组合测试 | F-epoch / high：无 hotplug 时 native epoch 不可用，observed_mount 需要实际成功事件 | 未见 Mount、跨代、fork 拒绝完整结论 |
| E-extent：真实 Open wrapper 传 unknown，读回拒绝测试 | F-remaining / high：extent/lease/aliases/checker ingestion 仍有缺口 | `capture_verified=false`、`media_origin_verified=false` |

Timeline：读 a441 API/双层约定 → 核对 epoch 和 mutation public ABI → 原 wrapper 接线 → 主机实际源码组合执行 → 定点失败修正与证据补充。无新增设备或 VM 记录。

## a441 原始交付记录（历史保留）

以下保留前轮 API/source 调查与 7 pytest、57 场景的记录；其中未接线、未修改 FSYS_CONTENT 及行号属于当时 baseline。**当前实现差异和未完项以上述 runtime 增补为准。**

## 范围与结论

Scope：用户授权的独立同步写入追踪。仅修改：

- [`fsys-write-trace.c`](../../runtime/analysis/fsys-write-trace.c)、[`.h`](../../runtime/analysis/fsys-write-trace.h)；
- 专属 [`test-fsys-write-trace.c`](../../runtime/analysis/test-fsys-write-trace.c)、[`test_fsys_write_trace.py`](../../runtime/analysis/test_fsys_write_trace.py)；
- 本目录的说明、[source pins](source-pins.json)、[只读校验器](verify_source.py)。

授权依据为本轮用户指令和两层 `AGENTS.md`；`network_profile=offline`，禁止启动 VM、全量构建或触碰设备。报告采用普通逆向格式，`flavor=null`。

差异真实存在，而且实际 wrapper owner 是 **`runtime/analysis/file-media-config.c`**，不是 `menu-observe.c`：

| 原路径 / 当前日志 | 已有能力 | 本轮结论 |
|---|---|---|
| MPR still → `Fsys_WriteDirectFileAsyncV2` | `FSYS_WRITE_*`、callback、worker 和原 API 读回 | 保留符号、实现与日志格式；未复制或改写旧收据 |
| Movie helper → `Fsys_Write` | 成功 Write 只有 `FSYS_CONTENT`，受 `A7C2_FSYS_CONTENT_OBSERVE`、generation≥3、256 次限制 | 缺少冻结源、文件身份/offset/Close 的等价证据 |
| Movie helper → `Fsys_WriteAndFlush` | `FSYS_FILE_TRACE` 的返回值 | 缺源内容收据 |
| `Fsys_Close` | 透传，没有成功 Close 内容链日志 | 缺明确关闭完成收据 |

当前 `FSYS_CONTENT` 在原调用返回后直接遍历源指针；本交付没有修改它。新 API 用独立的 `FSYS_SYNC_*` 命名，避免将同步事件伪装成 async 请求/完成。

## 原 public ELF 的正向证据

完整身份与 8 个代码窗口、5 个 MPR PLT relocation 保存在 `source-pins.json`。校验器只读文件，不执行固件；依赖项目已使用的 `pyelftools`。

| 原件 | SHA-256 |
|---|---|
| `libmpr.so`，3,528,576 B | `4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9` |
| `libInfraFsys.so`，687,960 B | `33451a884b65f946ac8aca44b620cd3cec677d05752c52f2ff0e212a01824bfa` |

`libmpr+0x118e48` 的数据/调用方向：

1. `request+0x20` → `RingBuffer::GetReadPointer`，返回保存在 `x22`；
2. `request+0x10` → file object；object `+0x10` 的 u64 为 Fsys handle；
3. `request+0x18` 的 u32 → `w2`；源指针 → `x1`，handle → `x0`；
4. `request+0x30` 选择 `0x118eec → Fsys_WriteAndFlush@plt(0x7bc50)` 或 `0x118fe0 → Fsys_Write@plt(0x7bee0)`；
5. `0x118ef4` 的 `sxtw x20,w0`，随后 `0x118f04..0x118f0c` 将原实际返回与请求字节数比较；
6. 到 `0x118fc0` 才调用 `RingBuffer::FreeMemory`。因此源要在原调用之前冻结，不应在返回后重新读取原 ring。

`libInfraFsys` 正向保存/传递 `x0=handle`、`x1=virtual buffer`、`w2=int count`；下游 `0x2eaf4` 调 `PrFILE_fwrite` 或 `fsysDepTNtfs_fwrite`。原 Write 的非负结果是实际字节数，负值是状态错误。WriteAndFlush 还可能在数据已发生写入后用 flush 错误覆盖非负返回，所以负返回不能推断“文件改了 0 字节”。本 API 遇到这种情况污染完整性，保留原 result/errno。

闭合的 ABI：

```c
int Fsys_Open(const char *path, uint64_t *handle, unsigned flags);
int Fsys_Write(uint64_t handle, const void *virtual_source, int count);
int Fsys_WriteAndFlush(uint64_t handle, const void *virtual_source, int count);
int Fsys_Read(uint64_t handle, void *virtual_destination, int count);
int Fsys_Close(uint64_t handle);
int Fsys_Seek(uint64_t handle, int64_t offset, unsigned origin, uint64_t *position);
```

Open/Close/Seek 是零成功状态。Write/WriteAndFlush/Read 返回非负实际字节数。Seek 的 u64 输出只在原成功后、且完整安全复制时使用。

E-imports/E-exports：MPR 的相关导入有上述同步 API 和独立的 `Fsys_WriteDirectFileAsyncV2`；原 Fsys 导出分别在 Open `0x322c0`、Close `0x3246c`、Read `0x325bc`、Write `0x327d8`、WriteAndFlush `0x32a0c`、Seek `0x3307c`。Fsys 的底层 I/O 导入包含 PrFILE/TNtfs read/write/fsync。MPR 依赖包括 pthread、C++ runtime、dl 等；这些导入不能证明当前 runtime 已进入 movie worker。

## 稳定 API 与接线位置

权威声明在 `fsys-write-trace.h`。函数保持调用时的 `errno`；返回的是**观察状态**，不得用它覆盖原 Fsys 的 result/errno，也不得因为它失败而跳过原调用。

| API | 精确接线位置和时序 |
|---|---|
| `fsys_sync_trace_open` | `file-media-config.c::Fsys_Open`（当前约 184 行）。原调用前，用完整、安全的 `/proc/self/mem` 复制冻结 NUL 终止 path；原调用后保存原 rc/errno、安全复制 u64 handle，再传 path snapshot、flags、实际 generation 与已独立确认的初始 extent/position。传入 path 长度不含 NUL。失败时不解引用原 handle 输出。 |
| `fsys_sync_trace_file` | 在每个原 handle 操作之前，用 `(handle,generation)` 取得唯一仍打开的 lifetime token；返回 0 表示缺失/歧义。必须把这个 token 保留到原调用之后。 |
| `fsys_sync_trace_write_begin` / `_end` | `Fsys_Write`（约 192 行）、`Fsys_WriteAndFlush`（约 225 行）。begin 在原调用前，end 在原返回后立即保存 result/errno 后；`and_flush` 分别为 0/1。end 的 generation 使用调用后重新观察的实际值，以发现跨代调用。保持原 `hotplug_io` 加减与原函数参数。 |
| `fsys_sync_trace_position` | `Fsys_Seek`（约 239 行），只传原结果和安全读取的输出 position；未知输出置 `position_known=0`。它不会额外调用 Seek。 |
| `fsys_sync_trace_close` | `Fsys_Close`（约 210 行），原调用前捕获 token/generation；原调用后保留实际 rc/errno 并观察。不会发起 Close。 |
| `fsys_sync_trace_invalidate` | 未闭合的 truncate/combine/rename/unmount/遗漏操作、其它别名写入。`file=0` 污染全部 lifetime；有确切身份时传具体 token。普通 Read 也移动文件位置；若不跟踪其对 writer handle 的实际 cursor 影响，必须失效该 writer，不能静默忽略。 |
| `fsys_sync_trace_readback` | 显式 post-close、**原 FlushVolume 成功之后**。传原 flush rc/errno、原 handle/generation 和原始 Open/Read/Close 函数指针。当前 `fsys_native_write_readback` 约 298 行只处理 async；适合由 owner 添加同步调用。`file_media_flush_pending` 首次 `rc=flush(...)` 后约 376 行、或既有 hotplug flush 的成功分支是检查位置，不能改变原 flush 次数、原返回、STOP/cancel 逻辑。 |

`build-observers.sh` 当前约 66 行已经把 `file-media-config.c` 与 `fsys-write-trace.c` 链进同一个 DSO；本轮未改构建脚本、未构建 DSO。`menu-observe.c` 不需要猜测新 Fsys ABI。

原 API 的 `uint64_t` 在 AArch64 typedef 不一定与 wrapper 的 `unsigned long long` 是同一 C 类型。**不可将这两种函数指针强制转换。** 原读回 ops 沿用现有 `struct fsys_native_read_ops` 的 `unsigned long long` 声明，直接复用 owner 现有 original lookup 方式。

新 API 不读取环境开关；调用方应复用自己的显式观察/profile gate。generation 必须由实际挂载/媒体生命周期提供；未知或 0 不要编造为 1。初始文件大小、初始位置、源 allocation/lease extent 也不能仅由文件名、函数名或请求 count 推断；未知标志为 0，此时仍可留下准确的局部失败/源内容收据，但不能生成完整内容结论。`FSYS_SYNC_VIRTUAL` 只用于已证明为虚拟指针的原 x1；logical/physical 不能换一个枚举值冒充 virtual。

写调用的最小顺序如下；其中 source/context/实际 generation 由 wrapper 的已知来源填入，不能替换原 data 或增加原 Fsys 调用：

```text
save incoming errno
resolve original function and actual generation
lookup file token; freeze bounded source with write_begin
restore incoming errno
call original(handle, original_data, original_count) exactly once
save original result and errno immediately
write_end(ticket, original_handle, actual_post_generation, original_result, original_errno)
restore original errno; return original result
```

caller 为原调用返回地址；context、producer 仅保存 owner 已实际观察到的原始标识，未知填 0。API 记录真实 pid/tid，不将这些标识自动解释为 CMOS、codec 或 mux 来源。原读取回调绕过 interposition；因此读回不会误生成新 Open lifetime 或改变 writer cursor。

## 收据与 fail-closed 判据

- `FSYS_SYNC_OPEN`：唯一、不回收的 `file` token，handle/generation、flags、冻结路径 hex、已知 extent/position、原 rc/errno、raw caller/context/producer。
- `FSYS_SYNC_BEGIN`：ticket、原请求数、地址域、声明 extent、实际源冻结是否完整。通过 `/proc/self/mem` 精确读取整个允许范围；不能读取则没有源摘要。没有对 logical/physical 地址直接 host 解引用。
- `FSYS_SYNC_WRITE`：原返回 `result`/errno，非负合法的 `actual`，只对冻结源中原实际返回的前缀计算 FNV；短写也保留真实前缀摘要，`full_write=0` 并永久禁止该 lifetime 的完整结论。原返回失败或超出请求范围不能 claim 数据写入。原数据在返回前被释放/改写也不会触发再次读取。
- `FSYS_SYNC_POSITION/CLOSE`：真实操作结果，始终使用同一 file/handle/generation；Close 失败、重复 Close、未结束的写 ticket 都不能通过。
- `FSYS_SYNC_CONTRIBUTION`：原读回过程中最终可见的字节段，连接 write ticket、file offset、source offset，以及冻结源/读回实际字节的两个 FNV 和逐字节比较结果。Seek 覆盖旧数据按 ticket 顺序合成，完全被覆盖的旧字节不冒充最终贡献。
- `FSYS_SYNC_NATIVE_CHUNK/READBACK`：原 Open/Read/Close；支持反复正的短 Read，检查每个返回范围、实际逐字节内容、精确 EOF 和原读回 Close 结果。只有全文件实际读到、所有 byte 都有已冻结写贡献、原 write/Close/flush 均成功，才允许 `content_verified=1`。

同句柄同时写、已打开身份的别名 Open、旧 generation/handle/ticket、缺失 token、未知初始 extent/position、写入中关闭、未知 mutation、超限、未覆盖洞、任何失败/短写都会拒绝完整结论。成功的空写/空文件不证明媒体。跨 generation 的重新 Open 得到新 token，旧身份失效。原 readback 期间的观察状态变化也会使最终结果失败。

**边界：**最多 32 个 lifetime、1024 个 write ticket、总共保留 128 MiB 冻结源，单个可验证文件也限 128 MiB。冻结数据保留到进程退出，任何超限会发 incomplete 并拒绝完整性，不静默截取。观察状态锁不跨原 Fsys 调用或读回 callbacks，但冻结/日志在观察锁内，会增加延迟；它不是原写入的 admission lock。接线 owner 必须覆盖所有可能影响该文件的操作，并用既有原流程确定读回时序。此 API 不承诺抵抗绕过全部观察器的并发原写入。路径别名检测限于完全相同的冻结路径；FAT 大小写/其它命名别名没有擅自推断，由掌握原文件身份的 owner 失效相关 lifetime。

首个尚未闭合的下游边界：movie finalizer `libmpr+0x118fe8` 的两次 `Fsys_Combine`、`0x226f20/0x226ed4` 的最终 Close/Flush/path/extent 对应关系。**不能把 `.RSV/.BIN` 的局部同步收据直接认作最终 MP4。**本轮没有猜这些 wrapper 或更改 finalizer；发生这类未建模 mutation 必须 invalidate。原 movie worker 是否自然执行、源字节是否来自编码器、最终 MP4/host commit/独立解码，都仍需主会话的新同轮实证。

## 验证和复现

从本成果根目录执行（public library 默认在既有 runtime menu-root，只读使用）：

```bash
python3 -B report/native-movie-write-trace/verify_source.py
python3 -m pytest runtime/analysis/test_fsys_write_trace.py -q
```

没有默认 public 原件的读者可将同 SHA-256 的官方 ALLLANG 提取物目录显式传给 verifier；本目录不分发 Sony 原件。

本轮结果：`source_verified=true`，8 个代码窗口，5 个 sync PLT bindings；pytest **7 passed**，其中原 async 测试保留，新 C fixture 在两种构建下各运行 **57 个 mode**。普通构建使用 `-std=c11 -O1 -g -Wall -Wextra -Werror -pedantic -pthread`；另一构建加 `-fsanitize=address,undefined -fno-omit-frame-pointer -no-pie`。

专属 fixture 覆盖：正常 Write/WriteAndFlush、原数据改变/munmap、7 字节覆盖写和贡献分段、短写/失败/非法返回、Close/flush/读回 Close 失败、旧 handle/generation/replay、未知 extent/position、logical/physical、NULL/无效地址、实际跨 unmapped 边界/部分 pread、地址/extent/大小溢出、并发 inflight、真实多线程独立文件及同句柄重叠、hole、别名与重用、file/ticket/总冻结字节上限、读回 open/read 错误、过早 EOF/额外字节/内容不符、读回期间 invalidation、gettid 被拒绝时原读回 callbacks 仍看到正确 errno。总冻结字节上限场景会在 host 测试进程中临时使用约 128 MiB 匿名源和 128 MiB 冻结副本，不涉及磁盘镜像或设备。

## Evidence → Finding → Path

| Evidence | source_ref / content_hash | 复现 |
|---|---|---|
| E-sync-elf | `source-pins.json` 中两个 public ELF 的完整 SHA-256、8 个窗口 digest、5 个 PLT GOT binding | `verify_source.py`；`aarch64-linux-gnu-objdump -d --start-address=0x118e48 --stop-address=0x118fe8 runtime/analysis/menu-root/usr/lib/libmpr.so` |
| E-wrapper-baseline | 原观察差异在 `file-media-config.c` 的 Open/Write/Close/WriteAndFlush；本轮只读 baseline SHA-256 `9a0d3f9d618a3dca91531bede019ef4912b272ca8a99579dd11fbb19521bf242` | `rg -n 'FSYS_CONTENT|Fsys_Write|Fsys_Close|fsys_write_trace_begin' runtime/analysis/file-media-config.c`；owner 接线后此 baseline hash 预计变化 |
| E-sync-host | 专属 C fixture + pytest，内容 hash 由交付文件计算；合成输入只证明 API 行为 | 上述专属 pytest，strict C11 和 ASAN/UBSAN |

| Finding | severity / evidence_ids / confidence / location / status |
|---|---|
| F-sync-gap：独立 Movie sink 走同步写，现有 async 收据不覆盖该路径 | n/a_re / E-sync-elf,E-wrapper-baseline / high / MPR `0x118e48`、file-media-config wrappers / 静态已确认，未证明本轮运行到达 |
| F-sync-api：有界冻结、真实 actual-prefix、身份/关闭/原读回和覆盖贡献可用 | n/a_re / E-sync-elf,E-sync-host / high / fsys-write-trace.c/.h / host 实现已验证，runtime 尚未接线 |
| F-final-movie：当前不能声明原 MP4 产物链闭合 | n/a_re / E-sync-elf,E-wrapper-baseline / high / finalizer `0x118fe8`、未接线 owner / 未完成 |

P-sync-write，`path_type=callflow`：原 movie ring pointer → 同步 Fsys 原 Write/WriteAndFlush（E-sync-elf/F-sync-gap）→ begin 冻结/原 result/Close（E-sync-host/F-sync-api）→ 原成功 flush 后，原 Open/Read/Close 和 ticket 分段比对（E-sync-host/F-sync-api）。最后一步是 host 接口验收；实际固件同轮 path 不在本轮证据中。

Timeline（本轮 2026-10-28）：先读根及 final 规则 → 只读确认真实 wrapper/两个 public ELF 的 ABI 与调用方向 → 限定文件实现同步观察 API → 专属 strict/sanitized 测试及 source verifier 通过。没有运行新 VM、媒体生成、旧 batch 收据改写或提交。
