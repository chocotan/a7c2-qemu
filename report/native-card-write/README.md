# 原MPR/Fsys异步写卡与读回验收

`check_writeback.py` 只读取已完成运行的原始 MPR/Fsys 观察日志、两次 SD 导出清单和宿主目录卡文件，核对源缓冲区、原始 Fsys 回读、宿主读回及独立解码之间的一致性。它始终输出 `capture_verified: false`：真实 CMOS 被原固件消费，以及 JPEG/视频确实出自原始编码链路，必须由其他证据连接，不能由宿主媒体、成功回调或来源布尔值代替。

它不启动 VM、不接网络、不访问真机/物理 SD、不写目录卡，也不生成媒体。临时文件都是检查器私有的匿名字节快照或解码诊断输出，退出时关闭删除。Python 3、Pillow、`ffprobe` 和 `ffmpeg` 必须已安装；缺少依赖会留下未解码结果，不会自动安装或降低判据。

运行时代码在 [fsys-write-trace.c](../../runtime/analysis/fsys-write-trace.c)、[头文件](../../runtime/analysis/fsys-write-trace.h) 和现有 [file-media-config.c](../../runtime/analysis/file-media-config.c)。沿用严格开关 `A7C2_FSYS_ASYNC_OBSERVE=1`，缺省关闭；原请求、callback、cookie、返回值及 errno 均透传。原始 `Fsys_WriteDirectFileAsyncV2` 继续负责排队和实际写入，本组件只读取真实缓冲、旁观原 MPR callback/worker，并在既有导出流程调用原始 `Fsys_Open(...,1)`、分块 `Read`、EOF 探测、`Close`。只在同一 mounted owner、真实 `FlushVolume=0` 后读回，随后再次执行真实 volume flush，再进入既有 STOP/块同步/宿主导出/CONT 流程。读回失败只产生失败证据，不篡改原 volume flush 返回值。

[原ELF证据](source-pins.json) 固定公开 `libmpr.so` 和 `libInfraFsys.so` 的完整 SHA-256、19 个文件映射窗口（34,700字节）及两个 `R_AARCH64_GLOB_DAT` 回调绑定。MPR从GOT取原callback和`_write_finished`，因此可用导出符号透传观测，无需修改请求里的函数指针。验证器拒绝重复JSON键，防止源合同被静默覆盖。复核命令如下；不执行目标代码：

```bash
python3 -B report/native-card-write/verify_source.py
```

原 `Fsys_FlushVolume@0x38c28` 经 `0x2e15c` 排空两个 async 层及 I/O 队列，I/O节点在真实callback返回后才退休。但它不会 join MPR另一个32字节工作队列，也不关闭新写入准入。故还要求原 `_write_finished` 返回，以及停止后的完整日志中每个请求都有匹配的native readback和最终coverage。新请求、未返回的回调/worker、坏快照、重复/歧义或超过32条观察上限均拒绝写卡证明；不会把“观察满了”解释为pending为零。这是事后证据检查，不是阻止并发写入的准入锁。物理地址模式没有进程内存等价读取，明确不支持内容证明。

从本成果根目录运行，`RUN` 事先设为已完成运行的绝对目录：

```bash
: "${RUN:?Set RUN to the absolute completed evidence-run directory}"
python3 -B report/native-card-write/check_writeback.py "$RUN"
python3 -B report/native-card-write/check_writeback.py "$RUN" --mediafile DCIM/100MSDCF/DSC00001.JPG
python3 -m pytest report/native-card-write/test_writeback.py -q
```

`--mediafile` 是宿主 SD 根下的精确相对路径；省略时检查日志实际声明的所有 `.jpg`、`.jpeg`、`.mp4` 请求，不扫描整张 256 GB 卡。JSON 只写 stdout。退出码 0 表示所选文件写回和独立解码均通过；退出码 1 表示证据缺失、失败或未解码；参数格式错误由 argparse 返回 2。退出码 0 也不代表拍摄完成。

输入文件是 `console.log`、`SD/export.json`、`gtk-input-proof.json` 的 `sd_export`，以及两份导出中同一 `host_directory` 下所选文件。目录卡只能位于运行目录内部、运行目录同级 `directory-sd-tests/` 内，或本成果公共 `runtime/analysis/directory-sd-tests/` 内；不接受其他导出根目录。两次导出的序列必须递增，文件路径、长度、SHA-256、owner PID、drive 和 host 根目录必须一致。

| 结果字段 | 成立条件与范围 |
| --- | --- |
| `exports.ok` | 两次 256,000,000,000 字节目录卡导出均成功，原始 FlushVolume 返回 0、owner STOP、匹配 PID/序列的 resume、guest block sync、无 pending/closed-pending commit |
| `readback_verified` | 所选宿主文件实际长度和流式 SHA-256 与两份导出一致；摘要与后续检查共用同一匿名快照 |
| `range_matches` | 每个声明的源贡献范围 FNV-1a64 与快照相同；本字段不单独代表整文件或拍摄 |
| `native_readback_verified` | 每批原始 Fsys Open/Read/EOF/Close 全部成功，整文件长度与 FNV 均匹配宿主快照 |
| `whole_file_verified` | 源贡献范围从 0 连续、无重叠地覆盖 fileSize，且宿主文件长度精确等于 fileSize |
| `writeback_verified` | 上述整文件、原生/宿主读回、完整原始 submit/callback/finished/return 和全 token coverage 均通过；不依赖解码成功 |
| `independent_decoded` | JPEG 实际加载并计算解码 RGB SHA-256；或 MP4 实际计帧及完整 null 解码通过 |
| `capture_verified` | 永远为 `false`，此组件没有 CMOS/编码来源证明 |

结果中的 `items` 保留范围、原始回读、摘要和解码信息。错误保留类型与原因；可解析但不合格的生命周期会进入 `trace_issues`，包含原始字段和行号。`exports.ok` 与写回判定独立：存储导出成功而原生读回失败时，不能把导出成功改写成拍摄或写回成功。

本检查器比较两份完整清单，但只重新读取所选文件；未选文件的实际 SHA-256、虚拟 FAT 格式与磁盘镜像结构不在本次验证范围。256 GB 是导出声明的虚拟容量，不会分配或读入 256 GB 镜像。

## 最终观察日志契约

每行以以下标签开头，允许一个可选的 `OBS ` 前缀。字段是 ASCII 空格分隔的 `key=value`，数字为无前导零的十进制，cookie 为 `0x` 十六进制，FNV 为 16 位十六进制。拒绝重复字段、重复事件、截断行、零/未匹配 token、缺项和超范围整数。额外诊断字段可存在，但不作为来源证明。旧 `FSYS_ASYNC_WRITE` 不是写回证据。

| 标签 | 必需字段 |
| --- | --- |
| `FSYS_WRITE_REQUEST` | `pid token cookie bytes request_fnv1a64 areas observation_rc path_hex payload_complete expected_bytes address_mode media_origin_verified` |
| `FSYS_WRITE_AREA` | `pid token index offset bytes data_fnv1a64 readable submitted_bytes` |
| `FSYS_WRITE_SUBMIT` | `pid token rc callback_seen` |
| `MPR_WRITE_CALLBACK` | `pid token cookie rc result_copied result_fnv1a64` |
| `MPR_WRITE_FINISHED` | `pid token cookie rc input_copied returned` |
| `MPR_WRITE_CALLBACK_RETURN` | `pid token returned` |
| `FSYS_WRITE_NATIVE_READBACK` | `pid token cookie rc bytes fnv1a64 eof close_rc` |
| `FSYS_WRITE_READBACK_COVERAGE` | `pid records rc` |

任何 `FSYS_WRITE_COVERAGE_INCOMPLETE` 都拒绝本次认证。Coverage 必须 `rc=0`，其 `records` 必须等于当时已观察的 token 数；本批 native readback 必须对这些 token 各出现一次，且最后一批覆盖全部请求。每次 flush 可以再次回读全部 token，必须以独立的 coverage 行关闭该完整批次，批内重复仍拒绝。最多接受 64 个完整回读批次。

请求、area、submit、callback entry、finished 和 callback return 按 `(pid, token)` 连接，cookie 必须在请求、callback、finished、native readback 间一致。同一路径的多请求或复用 cookie 一律视为歧义，不推测最后一次写入，也不合并多次写入。未选择文件若仍有 pending/失败 token，同样拒绝整个认证。全部 `rc`、`close_rc` 必须为 0，`result_copied/input_copied/returned/eof` 必须为 1；`duplicate` 若存在必须为 0。

`REQUEST → AREA` 在 submit 与 callback 之前。原始调用可能内联 callback、finished 和 callback return，因此这些事件允许早于 `SUBMIT`；异步 worker 的 finished 与 callback return 之间不强加先后次序。原生读回必须晚于 submit、finished 和 callback return。`callback_seen` 只是 submit 返回时的观察，不代替回调返回证据。

源请求固定 1288 字节。`path_hex` 严格解码 UTF-8，接受原始 `A:/` 到 `Z:/` 驱动器前缀，但必须与两次原始 flush 的 drive 一致；只把驱动器后路径精确映射到宿主清单。请求路径最多 1038 个 UTF-8 字节（原始 0x40f 字节 NUL 终止字段）；拒绝绝对路径、空组件、`.`、`..`、反斜杠、额外冒号和控制/格式字符。Unicode 文件名可以使用，JSON 输出转义非 ASCII。

源描述符在请求 `+0x430`，步长 `0x18`，含 `{u64 physical_address, u64 virtual_address, u64 submitted_length}`；第一个字段不是文件偏移。原始 worker 会按第一项的 virtual address 选择全表地址域，并转换成内部 `+0x450` 的 `{selected_address,length}` iovec；`+0x440` 是地址域、`+0x444` 是数量、`+0x448` 是提交长度总和。virtual 模式要求所选地址非零且4096字节对齐、所有提交长度4096字节对齐；physical 模式需要底层驱动能力，观察器不把物理地址当进程指针读取。`expected_bytes` 是请求 `+0x42c` 的 u32 fileSize。原始执行器依次拼接所有 submitted span，然后截断到 fileSize，因此检查器要求：

```text
area[i].offset = sum(area[j].submitted_bytes for j < i)
area[i].bytes = max(0, min(area[i].submitted_bytes, fileSize - area[i].offset))
```

只接受 `address_mode=1` 的已观察虚拟地址源，submitted 长度必须为 4096 对齐且累计不溢出；原始地址本身的对齐与可读性由 C 观察器检查，Python 不从日志外推地址。物理模式 2 不受支持。完整 source hash 必须来自可读的实际贡献前缀，`payload_complete=1`、`observation_rc=0`，索引恰为 `0..areas-1`，最多 8 段。原 MPR 构造循环自身没有对应的八段容量保护；出现超过八段时观察器只留下 unsupported/coverage failure，不能让后续 Fsys检查替原固件补救这个越界风险。MPR提交长度是每段原始长度向上取整后的值，fileSize仍是原始长度之和，不能把两者混为一谈。零贡献尾段仍保留索引和累计 offset，可超过 fileSize，必须 `bytes=0 readable=1` 且 FNV 为 `cbf29ce484222325`；不把它补成文件数据。中间 submitted 对齐填充若落在 fileSize 内，本来就是文件字节，不能删除。洞、重叠、重复或错误截断语义均不得成为整文件证据。

所有 source/host/native FNV 使用初值 `14695981039346656037`、乘数 `1099511628211`，每字节异或后乘法，按 u64 回绕。`MPR_WRITE_CALLBACK` 的 result digest 对应 0x4d8（1240）字节原始结果快照；`result_bytes` 若提供必须等于 1240。它不是文件字节数或 CMOS 摘要。原结果中的 `+0x42c` 是 freeCluster，不是 request 的 fileSize；MPR用 `bytePerSector * sectorPerCluster * freeCluster` 计算容量统计。`_write_finished` 接收的是32字节工作项指针，其中 cookie 在 `+0x00`、状态在 `+0x08`，不是原始 cookie 直接作为工作项地址。回调结果中的容量 metric 也不是文件长度；finished 的 24 字节输入在原始函数释放上下文前观察，`FINISHED returned=1` 只说明原始函数实际返回。

## 读取、解码和证据限制

路径读取复用 [capture-evidence 检查器](../capture-evidence/check_evidence.py) 的固定位置代码，只加载该文件，不搜索插件。每一层目录和叶子都通过 dirfd 与 `O_NOFOLLOW` 打开；叶子必须为有界普通文件。根目录和文件必须属于当前用户、不能 group/world writable，文件必须只有一个硬链接。检查前后验证 fd 的 inode、大小、mtime、ctime。拒绝符号链接、设备、FIFO、路径逃逸和读取过程中变化的文件。

日志最多 64 MiB、单行最多 8192 字节；每份 JSON 最多 4 MiB；最多 32 个 token 和每份导出 4096 个文件。单请求实际贡献和可解码匿名快照上限均为 128 MiB，这是本组件与 C 观察器的检查预算，不是原始 API 文件大小上限。所选文件哈希及范围读取共享 512 MiB 总预算。大文件最多报告有界范围匹配，缺少完整 SHA/native/解码链时不认证整文件；不会把洞自动填零。修改这些预算需要显式扩展实现与验证，不能依靠卡的虚拟容量推导通过。

JPEG 在独立 Python 子进程通过 Pillow `Image.load()` 加载，拒绝截断图和非 JPEG，最多 100,000,000 像素；输出尺寸及解码 RGB 字节的 SHA-256。MP4 必须有实际 `ftyp` 签名，`ffprobe -count_frames` 至少读到 2 帧、尺寸受限、duration 有限且大于 0，再用 `ffmpeg -xerror -err_detect explode` 完整解码视频到 null，确认最终帧数一致。元数据和容器标记本身不算解码。

所有解码只使用已验证快照的继承 fd，参数数组调用、无 shell，MP4 固定 mov demuxer，禁用外部 data reference，协议只允许 `file,pipe`。每项解码合计最多 30 秒，子进程有 CPU/内存/输出限制，不保留原始视频帧或重编码媒体。缺依赖、超时、解码错误或只有元数据时 `independent_decoded=false`；已有写回一致性结果可以单独保留。

日志和导出 JSON 是明文研究证据，FNV 不抗碰撞。SHA-256 把实际宿主快照绑定到导出记录，但不认证日志、原始二进制、观察器或拍摄来源。`media_origin_verified`、`original_capture_verified` 等布尔值一律不作为拍摄证明。需要父任务另行固定源码/二进制来源，并连接真实 CMOS 消费与原始编码链路；原生异步 still write 路线也不能自行推广为已恢复视频生产链。

## 组件验证记录

`test_writeback.py` 使用 pytest 临时目录，Pillow 在内存生成微型 JPEG，已安装的 ffmpeg 在内存生成 MP4。这些明确是 **host-test** 夹具，只验证检查器，绝不作为固件拍摄证据。覆盖正常 Unicode 路径、内联回调、异步 finished、真实 JPEG 像素摘要、实际视频计帧/null 解码、source corruption、截断/尾随字节、flush/commit/两次导出不一致、路径逃逸、软/硬链接、错误 source span/零贡献尾段、中间对齐填充、多 token 歧义、回调未返回、原生回读缺失/错误/hash 不符、coverage 缺项/失败/重复和元数据无视频帧。

证据到结论的对应关系：

| Evidence | Finding | Path |
| --- | --- | --- |
| 原始请求贡献范围、MPR callback/finished/return、完整 native readback coverage | 源范围、业务执行与原始回读的可连接一致性；明文不提供来源认证 | [检查器](check_writeback.py) 的 `parse_trace`、`lifecycle` |
| 两次原始 flush/resume 导出、宿主私有快照 SHA/FNV、原始 Fsys Read FNV | fileSize 全覆盖且跨通道相同才可标记 `writeback_verified` | `exports`、`check_item` |
| JPEG 实际像素加载或 MP4 两次实际解码 | 可独立解码，依然缺 CMOS/原始编码来源 | `decode`、[组件测试](test_writeback.py) |

检查器独立自测为82项；C布局、溢出、页对齐、真实原回调透传、errno、原函数释放输入后的生命周期、内联完成、并发token、原Read短读/EOF/错误/Close失败和漏记保护均由SAN fixture验证。整批冻结、回归、构建和原libc2.25 ABI结果统一保存在[本批验证收据](../2026-10-27-unified-camera/verification-with-card-write.json)。新media preload同时参与实际原ABI装载，单独记录产物摘要。

当前仍无本批原固件拍摄运行或JPEG/MP4产物。最后原运行仍停在`3003`，EE=0；真实LIF/CP provider、native YC解释及原视频生产链尚有缺口。导出契约基于 [directory_snapshot.py](../../runtime/analysis/directory_snapshot.py)、[directory_sd.py](../../runtime/analysis/directory_sd.py) 和已有公开目录SD运行格式；未读取私有完整系统资料。这一批不启动逐模块VM，也不提升任何capture标志。
