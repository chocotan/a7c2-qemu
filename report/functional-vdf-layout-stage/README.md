# 启动期 canonical 014c 的虚拟 layout 寄存器 stage

本模块实现显式功能 profile 的启动期本地 bank32 预置：保存原请求、写入独立 bank、复制读回并逐字节/FNV 比对，原请求真实 free 成功后才向原动态 D 发布独立 114c。它还提供供后期真实 op7 使用的 bank 读取及 model192 绑定接口。早期完成只表示软件寄存器预置和 AP ACK 生命周期完成；`stage_only=1`、`semantic_applied=0`、`frame_consumed=0`、`hardware_ready=0` 和 `capture_verified=0` 始终保留。后期 apply receipt 单独存放，不能改写早期 ACK 的含义。

范围为用户授权的 `virtual-functional-camera-v1` 本机软件模型。原严格 profile 的拒绝策略保持不变。此次仅新增模块、模块测试和本目录报告，没有修改 main、既存 VDF/core/ABI、broker、checkers 或旧 run；没有 VM、fullreg、整批构建、私有 dump、真实设备或真实 SD。本文为 `flavor=null` 的实现报告。

## 主会话接入

源码/API 位于 [functional-vdf-layout-stage.h](../../runtime/analysis/device-models/functional-vdf-layout-stage.h) 和 [functional-vdf-layout-stage.c](../../runtime/analysis/device-models/functional-vdf-layout-stage.c)。main 负责构建与 hook、路由、profile、prefix history 及整体验证。

host policy 字段采用：

```python
startup_layout_policy = 'guest-local-canonical-initial-register-stage-before-active-route'
startup_layout_stage_only = True
startup_layout_frame_completion = False
```

1. 在 owner 原进程、处理输入之前调用一次 `functional_vdf_layout_stage_owner_init()`。重复调用返回 `-EALREADY`，没有 reset/import；fork 子进程在接触继承 mutex 前返回 `-EXDEV`。
2. main 先让既有 `full_bb_set_mode_observe_prefix` 看到这个原 014c 一次，保持原 prefix history。该兼容 hook 由 main 负责，此模块不会代调。
3. 只有精确 header40、显式 functional profile，且 all13/active route 已明确未就绪时，才调用 `functional_vdf_layout_stage_dispatch(dst, request, io, 1, 0, result)`。这里 `route_ready=0` 只表示调用方已确定的未就绪；未知值与 ready1 都返回 0，不接管。late all13/active 路径继续进入既有真正 op7。
4. 在真实原 `u_rcv` 成功之后调用 `functional_vdf_layout_stage_observe_receive_cycle(D, pointer, actual_source, actual_size, &ticket)`。接受时返回 1，ticket 必须保存到该 receiver 的 TLS。free 时只传这张 immutable ticket，不能从 snapshot 重新取当前 cycle。
5. 原 free hook 调用 `functional_vdf_layout_stage_release_cycle(D, pointer, ticket, real_free, record, result)`。receive 和 free 都要求原 sender TID；返回 0 表示该事件不属于本 owner，返回 1 表示该 hook 已处理，不能再执行一次真实 free。

`dispatch` 的返回规则与现 owner 风格一致：

| 返回 | 所有权与调用方行为 |
| --- | --- |
| `handled=0` | 其它命令、目的、profile 或 route_ready；继续原路由，不改 result |
| `handled=1, result<0` | 未接管的精确请求拒绝；请求仍归调用方 |
| `handled=1, result=0` | 已接管；检查 snapshot 的 faults、leases 和计数，不得把它直接报告为 model/frame 完成 |

已接管后出现错误仍保持 `result=0`，避免上层双重释放；故障 sticky，真实 retained pointer 和 rc 保留。不存在成功清零、隐式 retry、fake reset 或转入 legacy 空 ACK 的路径。

## 精确软件合同与实际读回

仅接受原请求：

```text
0d204c012800018007010100000000008002e0010000000000000000000000000300000000000000
```

body32 为：

```text
07010100000000008002e0010000000000000000000000000300000000000000
```

`actual io.source(request)` 必须属于 `0x81cf0000/0xffff0000`，不是 body 的 src byte。snapshot 保留 owner PID、原 sender TID、actual D、目标 `92840747`、command、40B 原 wire 和完整 wire FNV。每次 stage 推进独立 `cycle` 与 `stage_generation`，保存 `bank32`、`copied_readback32`、两个 FNV、`bank_written`、`readback_verified`。两个 32B 区域分别占据自己的存储位置；成功判断使用完整 `memcmp` 与两次实际 FNV，不只信任 rc0。故障 generation 也保留，不能据 generation 非零推断读回成功。

ACK 固定为独立 12B：

```text
0d204c110c00018000005900
```

它的 metadata source 为 `92840747`，目的为本次捕获的实际 D。顺序为：

```text
原 014c/actual D → 独立 bank32 写入 → 独立复制读回及比对
 → 分配独立 ACK 并校验（原 request 此时仍 live，拒绝 alias）
 → 原 request 按 owner 92840747 真实 free，必须 rc0
 → ACK 按原 D send → 原 D receive/ticket → 同 sender TID 真实 free rc0
```

原 request free 失败时不得 send，原 request/ACK 两 lease 均保留。ACK free 失败保留其 pointer/ticket；随后真实 free 成功可以退休 pointer，但 sticky fault 不会变成 AP consumed，也不会允许新 cycle。一次只允许一个 pending ACK，新 cycle 必须等前一次原 AP free0、send0、所有读回检查和健康状态全部满足。允许 send 内 inline receive/free；send 返回后不再解引用可能已经释放的 envelope。

allocator 返回的 live request 重叠区、owner state/transport/mutex/常量及其边界重叠区、溢出 span 均被拒绝，不写入也不假释放。所有 IO/record callback 在私有 mutex 外执行；callback 重入不能夺走 pending lease。退休地址不单独代表新消息归属；same D/same address 在不同 cycle 依靠 ticket 区分。

所有日志统一以 `FUNCTIONAL_LAYOUT_STAGE_` 开头，包含原 wire、bank/readback、FNV、generation、lease pointer/rc/TID 和各安全声明；不产生 `FUNCTIONAL_VDF_PATH_` 记录，不参与 op7 cycle/modeldone 计数。`AP_consumed` 在此仅指 **stage ACK** 的真实 receive/free 完成。

## 后期真实 model192 的读取与绑定

`functional_vdf_layout_stage_read_bank(stage_generation, out, 32, &digest)` 只在同 PID、健康、已完成的当前 stage generation 下复制实际 bank32；返回真实输出 FNV。错误不改输出，长度必须恰好 32，拒绝输出与私有状态或 digest 的别名。

main 应将该输出用于既有真实 op7。只有该 op7 已完成原有严格 result192 校验、完整 RGB sink 消费和 lease 退休后，才能调用：

```c
/* Context: main holds the actual validated native op7 result and metadata. */
int rc = functional_vdf_layout_stage_bind_applied(
    staged_generation, actual_model_owner_pid, actual_model_instance,
    actual_result192, FCAM_LAYOUT_RESULT_BYTES, &actual_bridge_metadata);
```

此函数不发起 RPC，也不自造 frame。它重新要求：

- 同 PID、非零 actual instance、metadata instance 一致，`used=required=192`、token0、ABI/length 正确。
- result 尾部全部 32B 与当前实际 bank/readback 精确相等，输入 FNV 等于这份 bank FNV；header 里的 route config 为 active 的 pins5/5 受限子集，含 canonical tail 校验。
- endpoint、selected/completed mask、enabled/class、config readback、commit、frame consumed、retired 均为既定成功值；status/reserved0。
- `640×480`、RGB stride1920、完整 `921600` 字节、非零相等 source/sink FNV、非零 lease generation。
- config/frame 各自等于其 before generation+1 且不溢出；重复或倒退 receipt 拒绝。后续 receipt 保持同 model instance 并严格推进 config/frame/lease。

通过后只更新独立 `snapshot.applied`：owner PID、stage generation、model instance、config/frame/lease generations、192B result FNV，以及该 receipt 的 `verified/semantic_applied/frame_consumed`。原 stage 的三个语义字段与计数保持原义，后续新 stage 也保留上一次 receipt 的 generation 供追溯。它无法鉴别同进程调用者伪造的 result bytes，因此 main 必须从真实 op7 验证点调用，不能从 host fixture、stage ACK 或任意 rc0 调用。

此次已实现并验证 **接口与校验**；尚未在 main 接线点验证真实 op7 → bind 的执行。host 测试中的 model192 是明确的 fixture，`capture_verified=false`，不形成真实图像消费证据。

## Evidence → Finding → Path

公开源身份、PT_LOAD 与窄窗原字节/SHA 全部在 [source-pins.json](source-pins.json)。复用研究 `analysis/scratch/functional-bb014c-source/RESULT.md`，仅挑选所需的 9 个窗口、414B，没有重做全局 survey。

| Evidence | Finding / 置信度 | Path |
| --- | --- | --- |
| E1：AP `34f135c` 初始化、`34f1b84` case0、`4c66db4` 表、`34f16e8` send | F1 / source-confirmed / high：原 case0 是精确 40B 014c + body32 | P1：精确原输入 → 独立 bank32 软件 stage |
| E2：AP `34e56c8` actual source/send、`34e35b8` status parser；CP `69c946` 114c、`1c6688` status、`1c791e` reply source/D | F2 / source-confirmed / high：独立 12B 114c，成功字 `00590000`，原动态 D 与 source92840747 合同 | P1：bank 完整读回 + 原 free0 → 独立 ACK → 原 receive/free ticket |
| E3：新 C owner + strict/SAN 生命周期测试 | F3 / implementation-verified / high：单 pending、sticky retention、same TID、cycle 和 alias 防护 | P1 各所有权边在 host IO fixture 下通过；原 guest 边由 main 另验 |
| E4：新 read/bind API + model192 fixture 的全32B与消费/退休/byte count/generation 变异拒绝测试 | F4 / interface-verified / high：独立 late receipt 需要相符的完整 model192，不改写 stage ACK 含义 | P2：当前 bank 读取 → **main 真实 op7（此次未验）** → 独立绑定 |
| E5：main 提供的 `runtime/analysis/scratch/functional-early-layout-crash-frame-records.json` | F5 / inherited-main-evidence：保存 FP 链中的原 LR `34e5778/34f170c/34c5f44/30ea500` 及前 BL `50130394/89cfff97/fbac0094/876e0f94` 定位早期 setter 拒绝后 abort | 仅解释接入 stage 的触发点；不重做 opcode 调查，不将任意栈词或旧 raw 栈负证当作消费证据 |

物理 ASIC 格式、原 CP RTOS/FIFO 历史、原 selector，以及完整 CMOS→编码→MPR/Fsys→虚拟 SD 拍摄链仍未验证。启动期本地寄存器预置成功属于用户明确采用的软件 policy，不能提升为原 0305/1305 硬件工作完成。

## 复现与当前验收

在项目根执行，要求公开 ALLLANG 资产已经位于原 `runtime/analysis/menu-root`；测试只读该公开资产：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/runtime/analysis/test_functional_vdf_layout_stage.py -q
```

本次结果：**4 passed**。strict C11 `-Wall -Wextra -Werror -pedantic` 与 ASan/UBSan 各跑 30 个场景；另验 production 对象无 HOST_TEST 符号、无 bridge/既有 VDF/RPC/mailbox/malloc 依赖，以及两份公开原件 SHA/PT_LOAD 和 9 个窄窗原字节。没有运行完整回归或整批构建。

场景包含三次早期 canonical 重复、same D/same ACK 地址跨 cycle、完整 readback 和尾字节故障、source callback 改写输入后的重新校验拒绝、shape/profile/late-ready 拒绝、live/private alias 和 span 溢出、原 free 失败不发 ACK、ACK free 失败保留与重试后 sticky、inline receive/free、stale ticket、同线程要求、callback 重入和持锁 fork。late bind 逐字节变异全部32B，另验完整 RGB 字节数、摘要、commit/retire、generation、instance/PID 及 duplicate receipt。

开发时两个失败均来自测试断言：inline-send-fail 最初被误归入 send 前失败，request-mutation 的拒绝最初被过度限定为 `ENODATA`。已修正对应夹具后，完整上述验收通过。测试不以这些失败冒充模块或原固件的负证。

| 项目 | 状态 |
| --- | --- |
| 独立 stage/copy-readback、真实 IO lease/ticket 生命周期 | 模块级通过 |
| 后期 model192 精确 bank 读取与单独绑定接口 | 模块级通过，真实 main 调用待验 |
| main hook、prefix、build、policy 联接 | 主会话负责，本子任务未改 |
| VM、整批构建/fullreg、真实 op7/帧完成、捕获链 | 未运行/未声明完成 |
