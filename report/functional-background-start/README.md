# 功能 3006 后台初始化 owner：延迟 Core 初始化与原消息生命周期

状态：**HOST_COMPONENT_VALIDATED / NATIVE_INTEGRATION_PENDING**。本组件在显式 `virtual-functional-camera-v1` 下，把原 type0/3006/24B 请求映射为真实 functional Core 的 INIT128 → 同实例 STATE128 → 独立缓存读回，然后走独立 12B 正常回复与真实 receive/free 生命周期。目标测试 **694 passed**，同时运行严格 C11 和 ASan/UBSan；本轮没有启动 VM，也没有验证原 AP、本机 mailbox/RSP 或 native last13/debugger 交接。

原 CP 非零 module masks、RAM/RTOS、资源业务与当前功能模型是独立结论。这里证明的是软件 Core 的实际初始化和读回，没有复制原 CP 模块完成标志，没有改写原本地 0x21 future、AP/CP gate、current 或 UI。`business_published`、`hardware_ready`、`image_ready`、全部物理标志和 `capture_verified` 永远为 false。原 3007 owner 与严格 profile 的代码均未改动。

## 范围与授权

本节为自包含 scope：`auth=设备所有者已授权的本机功能模拟实现`；`network_profile=offline`。新增文件只在以下位置，父会话负责 main/policy/checker/build/index 接线：

- [functional-background-start.h](../../runtime/analysis/device-models/functional-background-start.h)：稳定公共 API、snapshot、显式 trusted source 合同。
- [functional-background-start.c](../../runtime/analysis/device-models/functional-background-start.c)：单进程、一个 pending 请求、两份 lease；无线程、timer 或新 RPC。
- [test-functional-background-start.c](../../runtime/analysis/device-models/test-functional-background-start.c)、[test_functional_background_start.py](../../runtime/analysis/test_functional_background_start.py)：HOST_TEST 实际 Core 与 malloc/OSAL fixture。
- 本目录的 README、[source-pins.json](source-pins.json)、[validation.py](validation.py) 和 [validation.json](validation.json)。

未启动 VM/GDB/QMP/GUI；未发送 signals、访问网络、读写真机或 SD；未构建 production `.so` 或运行 fullreg。原固件、完整 dump、旧 run、原有 main/core/bridge/broker/profiles/runner/evidence 均不在本组件修改范围。测试的 guard 是明确标注的 HOST_TEST fixture，不能拿它证明 native all13。

## 复现

在项目根目录执行；编译输出由 pytest 写入独立临时目录，不生成媒体文件：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/runtime/analysis/test_functional_background_start.py \
  -q -x --color=no

PYTHONDONTWRITEBYTECODE=1 python3 -B \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/report/functional-background-start/validation.py
```

需要现有 `cc`、pytest、pthread，以及项目既有 libjpeg/libavcodec/libavformat/libavutil/libswscale 开发依赖。第二条命令需要通过项目现有资产准备流程获得的两份公开 ALLLANG 原件；未打包固件。验证器先核完整文件大小/SHA256，再核恰好三个小窗、原坐标和 `eda4c=39b3fd97`，共 **284B**。只有静态身份/窗口验证，不执行 CP 或重新调查其模块业务。

## 父会话接线合同

| 入口 | 行为及父会话前提 |
|---|---|
| `functional_background_start_owner_init()` | 仅本进程结构初始化；不调用 `fcam_bridge_init`，无 MAILBOX、RPC 或设备初始化。重复调用 `-EALREADY`，fork 后 `-EXDEV` 且不碰继承锁。 |
| `functional_background_start_bind_source_once(q)` | parent 已核原 libObj `eda50`、`dladdr` 同基址、`eda4c` 的两次原 4B 指纹读、实际 `osal_dynamic_id(2a,102)` 与 getSource 一致后才调用。当前 parent 只放行其已证明的 `0x8102....` dynamic-102 来源；组件不自行制造 caller 证据。相同 q 幂等，不同 q 为 `-ESTALE`。 |
| `functional_background_start_dispatch(dest,p,io,guard,enabled,&rc)` | 仅 enabled==1、dest90030001、命令3006；精确 type0/24B/已绑定 metadata source。byte1、word+4、尾部均复制/哈希但不解释。接受时返回 handled1/rc0，表示保留原请求的 pending 所有权；不表示完成。 |
| `functional_background_start_progress()` | 先锁外只读 ready；0 或 `-ENODATA` 时不 reserve，因此不触发 parent 桥初始化或 MAILBOX deadline。ready1 后才调用 reserve；parent wrapper 先 `tracked_native_reserve_resources(29)`、核同 run 实际 last13 与 global resource 锁，随后才准备桥。reservation 内再读 ready；回退时 sticky `-ESTALE`，无 Core 调用。 |
| `observe_receive_cycle(...)` | parent 仅在实际原 `osal_rcv` 成功后调用，核完整 source/size/body 和原请求 sender TID，捕获不可变 cycle ticket 到 receiver TLS。 |
| `release_cycle(...,ticket,real_free,record,&rc)` | 使用 receive 时保存的 ticket；不在 free 端查最新 snapshot 替换 ticket。必须原 sender/receiver TID 的真实 free0，加 send0，才 AP-consumed/transport-complete。 |
| `snapshot(...)` | 可在全部 IO/bridge/guard/logger callback 中重入读取；包含 pending、fault、真实保留指针、完整两次 State128、缓存/读回、hash、实际 counts 与各 TID/rc。 |

parent 在原同 run 最后第 13 个 audio predecessor 的 **原 free0 之后**调用 progress；dispatch 末也调用一次，以覆盖前置快照已完整 ready 的情况。parent 的 HDMI observer/runner 必须完成其实际 debugger handoff 后才服务 Core INIT。组件不制造 debugger-done、不写 guest bool；没有成功 bridge 往返就不能完成。

## 实际工作与传输顺序

1. 接受时仅保存不可变原24B、实际 source、原 sender TID、wire FNV 与回调；同一时刻只允许一份 pending。
2. ready 预检后，先确认原 request 的完整字节/source/length 未变；篡改在 reserve/MAILBOX 前拒绝。全局 reservation 成功且 ready 复核一致后，当前 progress 线程成为独立记录的 producer TID。
3. 实际 `fcam_bridge_call(origin, INIT, empty, 128)`，随后实际 `STATE`。origin 是原 source、dest90030001、cmd3006、bytes24 和原 wire FNV。两个返回都核 used/required128、token0、实例/nonce、ABI/caps、完整 geometry/config、counts、idle/pending、保留8B零及缓冲区 canary；两份128B必须逐字节一致。
4. 成功 STATE 独立复制到 owner 缓存，再复制读回并逐字节/FNV 比对。仅此时 `functional_core_initialized`、`state_copied/readback_verified` 和 `model_complete` 才成立。已有 Core 的重复 INIT 不强求默认 generation1、rendered1，也不重置其真实配置和帧数。
5. 真实 `io.release(90030001, original)` 返回0后，才分配独立 reply lease。原 free 失败不分配、不 ACK、不重试，保留实际指针/rc/TID。
6. reply 为 `01 00 06 30 | 原word+4 | 00 f0 00 00`；byte1=0 是明确软件策略。实际 source90030001，destination=已绑定原 source；写入后用实际 metadata 与全部12B读回验证，send 仅一次。已退休原地址可以作为新分配复用；任何仍 live 的原请求/私有状态别名拒绝。
7. send0 仅表示 queued。原 sender 实际 receive 整个 reply，并在该 TID 真实 free0 后，才记录 `AP_consumed=transport_complete=1`。允许 send 内 inline receive/free，但必须等 send 返回0与 guard 释放才能完成。旧 ticket 不会破坏同址的新 pending 请求；退休地址不会永久认领后来无关消息。

所有 IO、bridge、guard 和 logger 都在私有 mutex 外调用。`working`/lease `releasing` 保护重入与并发；无忙循环或生产 worker。错误为 sticky，实际 owned lease 留在 snapshot；即便 live=0 但已有故障，pending 仍不被写成干净完成。不存在以 F001/F002 或未知状态伪装成功/取消的分支。

## 验证结果与边界

**最终 694 passed（35.20s）**：每种构建 347 个实际子进程场景，包含 67 个行为/失败场景、24 个 pending 原字节篡改，以及 INIT/STATE 各128个响应字节篡改。编译参数含 `-std=c11 -Wall -Wextra -Werror -pedantic`；第二种构建附 ASan/UBSan，开启 leak 检查与首错停止。

| 实际验证 | 内容 |
|---|---|
| Deferred 工作 | ready0 与 `-ENODATA` 接受 pending、reserve/bridge/ACK均0；随后真实 ready 才在另一 pthread producer 中执行 Core，原 sender 仍负责 receive/free。pthread 仅属于 host fixture，生产 owner 不创建线程。 |
| Core 初始化 | 直接链接真实 `fcam_model_request` 及 optics/frame owner/pipeline；默认 INIT 的真实 proof 有 render/retire，rendered1/consumed0/retired1，无编码或成片。 |
| 重复 INIT | 先实际 INIT、configure96×64、VDF消费，使 config3/rendered2/consumed1/frame2；两轮3006各自INIT/STATE完整读回，原状态和 proof 不变。 |
| 完整性 | 两个不同真实 dynamic 值在各自进程可绑定，同 owner 不能 rebind；任意 word+4（包含0/ffffffff）原样回显；全部原24B和两份State128每字节篡改、metadata nonce/token/尺寸、canary均拒绝 ACK。 |
| 所有权 | 真实 malloc envelope、原 free0 后才 ACK allocate；独立两 lease、inline free、send失败、alloc带指针失败、错误长度/source/readback、私有别名、request/reply free失败均保留真实状态且不重试。 |
| 接收/释放 | send0未 receive 保持 pending；wrong TID、source、length、完整body、提前/重复receive、无callback、无/旧ticket均拒绝；同址复用为无关新消息/新 pending request/新 ACK 的旧事件不被重新授权。 |
| 并发/重入 | 全部 callback 可 snapshot，bridge期间并发 progress 不重复 Core，busy dispatch 保留 caller 所有权，guard/probe callback故障停止后续Core，fork-before-held-mutex立即拒绝。 |
| 证据输出 | `FUNCTIONAL_BACKGROUND_START_` typed 行，payload缓冲1024；测试核每行合计<1200，低于console4096限制。含 raw24、完整实际State128/FNV、probe/readback阶段、实际lease metadata和rc/TID。 |

此测试直接替换的是 bridge transport 与 OSAL allocator/queue，并使用 host fixture ready。它没有验证 parent exact caller hook、真实 all13 两份 UPM/24B HDMI 消费、MAILBOX/RSP、debugger handoff、原 AP 释放、原 local21 自然推进、SystemError 消除、拍摄UI或成片。故主会话仍需完成同 run 原消息接线与后续验收；不能据本组件测试把 AP、物理 CP 模块启动或 capture 标记通过。

## Evidence → Finding → Path

证据的具体摘要、编译输入与最终返回码见 [validation.json](validation.json)，公开原字节与完整原件SHA见 [source-pins.json](source-pins.json)。普通工程/固件实现报告，`flavor=null`；不涉及漏洞、IOC 或 ATT&CK。

| Evidence | source_ref / repro_command | content_hash |
|---|---|---|
| E1：继承原 sender 与 producer | `source-pins.json`；上述 `validation.py` 命令核三窗与原件身份。原 dynamic caller/3006→local21 阻塞、send非零会遗失request/queue 的否定结论保留。 | 每窗及原件完整 SHA256 在 pins；没有重新扩大 CP 反编译。 |
| E2：owner 实际实现 | `functional-background-start.c/.h`；上述目标 pytest 命令编译真实 C。 | `validation.json` 的 implementation_inputs。 |
| E3：实际 Core/lease 行为 | `test-functional-background-start.c`；上述目标 pytest 同时运行普通及 SAN。完整输出有 actual State128、FNV、真实 free counts。 | `validation.json` 的 test_inputs 与 final_tests。 |
| E4：否定/错误验证 | 同一矩阵的 ready0、错误注入、128+128+24字节篡改、错误TID/lease/ticket、fork。 | 与 E3 同一固定测试输入；保留的是失败后 pending/lease，不提升为native成功。 |

| Finding | severity / confidence / status | evidence_ids / location | 影响与残余风险 |
|---|---|---|---|
| F1：deferred 功能初始化及完整128B读回在host组件层通过 | n/a_re / high / validated-host-component | E2,E3；owner `progress/probe/cache_state` | 原CP物理模块与native执行没有因此闭合。 |
| F2：两 lease 及原 sender 消费门槛在host组件层通过 | n/a_re / high / validated-host-component | E2,E3,E4；`observe_receive_cycle/release_cycle` | parent仍须传入真实receive时的不可变ticket与真实free函数。 |
| F3：原3006正常传输形状只作继承合同 | n/a_re / high / inherited-static | E1；libObj ed9e0、CP b2298c/4b6b2c | 三窗不是全CP业务证明；virtual功能不能冒充CP modules/current/masks。 |
| F4：本轮未验证native/AP/UI/capture | n/a_re / high / bounded | E2,E3,E4；所有snapshot物理/capture常false | 后续阻塞、系统错误和拍摄链可能仍存在。 |

P1（`path_type=callflow`）：parent trusted caller/source（E1/F3）→ 单 pending 原请求（E2/F1）→ 实际 predecessor 预检及 reservation（E2/E4/F1）→ bridge INIT/STATE 和 cache读回（E2/E3/F1）→ 原request真实free、独立reply写回/send（E2/E3/F2）→ 原sender真实receive/ticket/free0（E2/E3/E4/F2）。终点限定 host transport 完成；native/UI/拍摄是未验证残余风险（F4）。

时间线：读项目约定及两份既有研究 → 提前交稳定header → 完成deferred owner及真实Core fixture → 首次fixture编译因误用 `fcam_model_create` 签名失败并纠正 → 普通/SAN矩阵通过 → 补原请求预检、ready回退与同址旧ticket保护 → 最终694项通过、三窗284B验证通过。本轮没有运行固件时间线或旧run改写。
