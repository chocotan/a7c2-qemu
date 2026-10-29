# Imola MBP：有界双向邮箱传输核心

已实现公开 Imola2 固件指令所示的两字邮箱接口，供后续前端复用。组件标识为 `diagnostic_only=1`、`owned_data_transport=1`、`original_mcu_executed=0`。它实际保存、复制和读回调用者写入的两个完整 `u32`；本次验证范围是主机 C 测试、原始 AArch64 libc 用户态测试及只读源字节核对。物理地址别名、IRQ、完整 MCU 执行和编码生产者仍未闭合。

范围仅限本目录六个源文件，原件取自公开 ALLLANG。没有修改 QEMU、其他模型或原始固件，没有启动系统 VM、访问网络、物理 SD 或 private/full 数据。正式接入前需解决下述硬件边界。

## 复现

在 `2026-10-17-qemu-native-camera/` 中执行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -q \
  report/imola-mbp-mailbox/test_mailbox.py
```

本次结果为 **53 passed**：

- 20 个实际 C 场景各运行于严格 C11 与 ASan/UBSan 二进制，共 40 项。
- 1 项 AArch64 测试使用同一个 `test-mbp-mailbox.c` 的真实 `main(argc, argv)`，逐一执行全部 20 个场景。入口复用 [original-abi-entry.c](../lif-capability-owner/original-abi-entry.c)，编译/链接方式沿用 [test_fill.py](../native-video-record-fill/test_fill.py) 的 `test_all_modes_with_original_aarch64_libc`：Clang `--target=aarch64-linux-gnu -nostdlib -fuse-ld=lld -mno-outline-atomics`，直接链接公开根目录中的 libc/libdl/libpthread/ld 2.25，并使用现有 `build-user/qemu-aarch64 -L menu-root`。这是用户态自测，未执行原始 MCU。
- 12 项公开原件、六个窗口、实际指令顺序/分支延迟槽及显式 bank 边界检查。源窗口合计 880 B（含重叠的完整提交函数），无新增反汇编依赖。

编译器或原始 libc 执行失败会导致测试失败；缺少已准备的 qemu-user/Clang 时仅 AArch64 项显式 skip，缺少公开原件时源检查显式 skip，不能把 skip 记为已验证。公开固件不随本目录分发；位置及完整摘要见 [source-pins.json](source-pins.json)。

## 已核对的实际源接口

完整原件长 `10934476` B，SHA-256：`15e75a9732e2f9904ada1c919c631dac0da57e605ce3daa4c6fb2ebe98982b5b`。所有窗口先经 [image.py](../imola-mcu-firmware-contract/image.py) 的 `load_image` 验证完整原件，再用不可变 `bytes` 和显式 bank 读取；不把 raw 偏移当运行内存快照。原件是 raw MCU 镜像，没有 ELF/PE 导入表；本次只验证已定位的普通 MIPS LW/SW、算术、分支和延迟槽，没有宣称 IPSX/完整 CPU target 已闭合。

| 证据 ID / bank | 实际地址 / raw | 已核对内容 |
|---|---|---|
| E1 / ram0 | VA `802485c8` / raw `2485c8`, 8 B | 两个小端 u32：`bf062000`、`bf072000` |
| E2 / ram0 | VA `80175c2c` / raw `175c2c`, `9c` B；同起点完整函数 `e0` B | 输入先截断 u8 再 `<2`；读 `+10`、`AND 2`、`BNEZ` 到提交；先写 command `+0`、argument `+4`，最终写 `1` 到 `+10` |
| E3 / ram0 | VA `8000b26c` / raw `b26c`, `e8` B | 读 `bf062010 & 8`，无结果则分支；实际读 `+8/+c`；处理路径后写 `4` 到 `+10`，并非读即 ACK |
| E4 / ram1 | VA `80746fbc` / raw `746fbc`, `68` B | 轮询 `be000010 & 8`，将 `+8/+c` 两字写到调用者输出；返回 `JR` 的延迟槽写 `4` 到 `+10` |
| E5 / ram1 | VA `807470f4` / raw `7470f4`, `9c` B | 反向发送读 `be000010 & 2`、`BNEZ`；先写 `+0/+4`，`JAL` 延迟槽最终写 `1` 到 `+10` |

E2 的轮询计数上限是 `0x100`。超限走断言调用，**断言若返回，实际代码继续写消息**：`80175ce0` 跳到 `80175ca4`，延迟槽装入 `1`。本核心的 `-EBUSY` 是明确的虚拟有界队列策略，不能据此推断原函数超时会返回错误。完整 `e0` B 函数 SHA 为 `48f76b31c53873b96a3fedcb6b4538975cc445ba4556dc3be8040147e96a8c36`；各短窗口与反向发送摘要亦已独立从原件读回。

## 稳定 API 与寄存器视图

接口见 [mbp-mailbox.h](mbp-mailbox.h)，实现见 [mbp-mailbox.c](mbp-mailbox.c)。调用者拥有固定尺寸 `imola_mbp`，从 `imola_mbp owner = {0};` 开始，仅调用一次 `imola_mbp_init(&owner)`；后续所有调用由调用者外部串行化，不得拷贝或修改内部状态。无分配、线程、互斥锁、PID/lease、回调或 I/O。

| API | 功能 |
|---|---|
| `imola_mbp_init(owner)` | 以显式构造策略清空全部槽；重复初始化拒绝 |
| `imola_mbp_write(owner, channel, role, offset, value)` | 暂存两字，或执行提交/受限 ACK |
| `imola_mbp_read(owner, channel, role, offset, out)` | 返回 `{value, known_bits}`；数据读记录相应读位，但不出队 |
| `imola_mbp_snapshot(owner, out)` | 只返回组件标识、容量、状态和位掩码；不暴露 payload、不产生读或消费 |

`channel` 只接受 `0/1`，`role` 为 `IMOLA_MBP_SPU=0` 或 `IMOLA_MBP_MBP=1`。这两个参数按完整 `unsigned` 范围验证，不复现原函数的 u8 截断。偏移和数据使用 `uint32_t`。

| 字节偏移 | 支持访问 | 行为 |
|---|---|---|
| `0x00` | 写 u32 | 暂存 command，置 fresh mask bit 0 |
| `0x04` | 写 u32 | 暂存 argument，置 fresh mask bit 1 |
| `0x08` | 读 u32 | 读当前 RX command，置 read mask bit 0 |
| `0x0c` | 读 u32 | 读当前 RX argument，置 read mask bit 1 |
| `0x10` | 读状态 / 写门铃 | 写 `1` 提交，写 `4` ACK；其他值拒绝 |

所有操作返回 `0` 或负 errno，**错误保持 owner 与输出不变**。错误包括 `-EINVAL`（空指针、未初始化、越界通道/角色、未对齐、owner/output 重叠）、`-EOVERFLOW`（声明对象地址跨度回绕）、`-EALREADY`（重复构造）、`-ENOTSUP`（未知寄存器、方向或门铃值）、`-ENODATA`（空数据读、暂存不完整、ACK 前两字未读全）、`-EBUSY`（完整暂存提交到满槽）、`-ENOENT`（ACK 空槽）。提交先检查两字 fresh，再检查容量。

每个指针必须指向符合声明尺寸、对齐且存活的真实对象。检查在解引用之前拒绝空值、地址算术回绕和错误对齐，输出还须与整个 owner 不相交；C 无法证明任意非空、不回绕指针实际映射到合法对象。所有容量由固定类型限定，没有调用者声明的可变缓冲区。

## 明示虚拟硬件策略

以下是可审查的适配策略，不能作为原硅片事实：

1. 固定两条独立逻辑通道，每条有 SPU/MBP 两个角色；每方向单槽，两方向可同时占满。构造为空是模型策略，原硬件 POR 和 FIFO 深度未知。
2. 同通道的相反角色被选为逻辑 peer。头文件中的 `bf062000`、`bf072000`、`be000000` 仅是源链接地址常量，API 不按物理地址绑定它们，也没有证明两个 RAM 核的实际交叉别名。
3. 两字允许任意暂存顺序，并允许在上条消息 pending 时暂存下一条。写 `1` 只有在**自上次成功提交以来两字段均已写过**且 peer RX 为空时，才精确复制两个 u32 到 peer RX；成功后只清 sender fresh mask。RX 在 ACK 前不受下一次暂存影响。缺字段或满槽不会改动任何状态。
4. 数据必须先存在才可读。成功数据读的 `known_bits=UINT32_MAX`，包括实际写入的 `0` 和 `ffffffff`；初始 C 存储即使为零，空槽也不会暴露为已知零数据。重复读只 peek，不出队。
5. ACK `4` 要求自身 pending 且两字均被成功读取，才清 pending/read mask；这是保守消费护栏，未证明原硬件会强制执行。ACK 不解释 command，也不宣称像素或 ES 已消费。
6. 状态只知道 `0xA`：bit 1 当且仅当 peer RX 未占用，bit 3 当且仅当 own RX pending。其他位值为 `a5a5a5a5 & ~0xA`，其 known mask 始终为零。bit 1 表示邮箱容量，不表示编码器 ready；不会无数据强制置位来跳过工作。

snapshot 的 `staged_words`/`read_words` 为两位 bitmask，不是计数。全部测试比较实际消息内容和失败前后状态；消息往返或 ACK 数量不作为 ES/CMOS 消费证据。

## 接入边界与证据链

| Finding | evidence_ids | 状态及后续路径 |
|---|---|---|
| F1：存在可核对的两字 MMIO 发送/接收接口 | E1–E5 | 原字节已验证；可将寄存器动作提交给本核心，物理映射待证 |
| F2：核心确实保留并传递调用者数据，拒绝无数据提交/消费 | E6：`test-mbp-mailbox.c` 的 20 场景及 `test_mailbox.py` 严格/消毒器/原始 libc 执行 | 53 pytest 项通过，执行范围为 HOST_TEST；不是 MCU 运行结果 |
| F3：scalar CPU MMIO、IRQ、编码执行仍缺证据 | E1–E5 的静态边界及 `source-pins.json` 的 `unclosed` | 保持关闭；后续需证明 unknown 位的实际指令消费、物理别名与 IRQ |

P1（callflow）：E2/E5 中调用者写两个 u32 → F1 对应的 `0/4/1@10` 提交 → E6/F2 的单槽实际复制 → E3/E4 对应的 `8/c` 读 → 显式 `4@10` 受限退休。前半是源指令事实，逻辑 peer、单槽与 ACK 护栏是上述虚拟策略，不能将两者合并宣称硬件已启动。观察时间为 2026-10-27，重现命令见上；各源证据的 artifact、bank、长度和 SHA 保存在本目录 JSON。

**尚未启用 scalar CPU-MMIO wrapper 或 IRQ API。** 原始 `LW` 会先取得整字，再由指令掩码筛选；本 API 返回 value/mask 只能供未来调用者限定消费已知位，并不能证明 guest 全部指令不会观察未知位。IRQ 线和投递语义未证，不生成虚拟中断。

command/argument 为不透明 u32。上游已定位的 `0x20` 参数是共享 command block 指针（请求 `+0x18`，块大小 `0x2c00`），不是已证明的 pixel DMA 或 ES 地址；本组件不解引用或执行它。PCPU 结果上下文是 `0x40a`；`0x40c` 是原请求的另一条完成通知，其出现本身不证明编码字节已产生，本组件不合成任何响应。尚无 codec body、实际 ES writer 或新 CMOS 的原生消费证据，本交付没有创建原始录制记录，也不改变工程既有 `native_gaps=63`、`capture_verified=false` 边界。

剩余工作是物理别名/IRQ、未知位消费与 MCU ISA 执行，再接实际共享块生产者及像素/编码数据链。本目录没有 QEMU frontend、host socket、文件生成器、虚假 ACK 或完成包。
