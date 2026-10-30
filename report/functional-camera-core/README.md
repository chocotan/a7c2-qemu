# Functional camera core

A synchronous C backend for the host broker, using the explicit
`virtual-functional-camera-v1` software RGB888 image bus. Sony physical ASIC
packing/compatibility remains unverified. The original AP → MPR/Fsys → virtual SD
integration and `capture_verified` are owned by the parent integration; this
component alone does not establish that capture chain. 本次 OP12 的实际 RGB 消费、完整回执与原115e生命周期见[位宽合同](../disp-bit-width/README.md)；OP11源读取由[独立 AP source provider](../functional-face-source-snapshot/README.md)负责，不调用 Core 生成替代图像。

The implementation produces actual frame-content and raw transfer receipts.
The OP9/OP10 contracts and limited software policies are documented below under
[BB startup and first histogram](#bb-startup-and-first-histogram-op9op10).
The prior core-only host matrix passed 31 tests; the earlier OP7 subset passed
15 tests. The earlier OP8 subset passed **21 tests, 24 deselected** (13.14s),
covering VDF/Zebra/layout/display and actual JPEG/H.264 cases in ordinary and
ASan/UBSan scenarios. Broker/guest integration and parent evidence joins remain
outside this component validation; these receipts do not clear original
JPEG/MPR/Fsys acceptance gaps. Scope is the authorized local functional profile
in the [public package scope](../../README.md).

## Build and integrate

Requires the already installed C11 compiler, pkg-config, libjpeg, libavcodec,
libavformat, libavutil, libswscale and the libx264 encoder. From this directory:

```bash
cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 -fPIC -shared -Wl,-z,defs \
  functional-camera-core.c \
  ../virtual-optics/optics.c \
  ../virtual-optical-frame-owner/optical-frame-owner.c \
  ../virtual-jpeg-hardware/jpeg-hardware.c \
  ../virtual-jpeg-hardware/jpeg-hardware-codec.c \
  ../virtual-jpeg-sos/jpeg-sos.c \
  ../virtual-video-engine/video-engine.c \
  ../virtual-camera-pipeline/camera-pipeline.c \
  $(pkg-config --cflags --libs libjpeg libavcodec libavformat libavutil libswscale) \
  -lm -o libfunctional-camera-core.so
```

The [public interface](functional-camera-core.h) exports:

```c
struct fcam_model *fcam_model_create(uint64_t instance);
void fcam_model_destroy(struct fcam_model *model);
int fcam_model_request(struct fcam_model *model, uint32_t opcode,
                       const uint8_t *input, size_t in_size,
                       uint8_t *output, size_t out_capacity,
                       struct fcam_exec_result *result);
int fcam_model_proof_snapshot(const struct fcam_model *model,
                              struct fcam_frame_proof *proof, size_t proof_size);
```

Load the library through ctypes with pointer/size_t/u32 arguments, a void-pointer
create result and an int request result. `test_functional_core.py::Model` contains
an executable ctypes binding and sequential read/release client. All calls need
external serialization; no threads or generic RPC framework are introduced.

Creation requires a nonzero instance, initializes real optics/JPEG contexts and
opens the installed H.264 encoder to determine its capability bit before
cancelling the probe. A missing H.264 encoder leaves still/AF available with the
H.264 bit clear. NULL means initialization failed, with errno. The first actual
INIT then acquires, renders and retires one default 640×480 sensor lease without
calling any encoder consumer. Its State128 has rendered1/frame_generation1 and
consumed0/jpeg_encoded0/video_encoded0 when no real job preceded INIT. Later INIT
calls do not repeat that probe; CANCEL does not erase its evidence. This lets CP
gate availability on real configured-sensor state rather than a readiness flag.
The probe temporarily uses default optics/geometry and restores an optional
INIT configuration. Default config is 640×480, 30 fps, quality90, f/4, ISO100,
shutter16667us, focus3000000um. A single
192 MiB private frame pool covers the 8192×8192 still ceiling; one frame is reused
for AF, still and video, with no collection of raw frames or clip packets. VDF
adds one independent packed RGB sink, allocated on demand and reused, bounded
by the same 192 MiB frame ceiling; the 640×480 route needs 921,600 bytes. Sink
storage participates in the request/proof alias guards and is freed at destroy.
The constructor explicitly stores this software endpoint's initial disabled
route0/pins1,1 canonical body. It creates no frame or completion transaction for
that declaration, and does not infer original CP BSS or live state.

## Wire operations

The immutable contract is
[functional-camera-abi.h](../../runtime/analysis/functional-camera-abi.h).
All wire integers are explicitly read/written little-endian; wire storage is
never cast to a C struct. State128/config48/AF32/still16/Packet96 use its exact
offsets and reserved zeros.

| Operation | Input | Successful output |
| --- | --- | --- |
| INIT | empty or Config48 | State128 after the once-only actual sensor probe; empty INIT preserves config |
| STATE | empty | State128 from actual model events |
| CONFIGURE | Config48 | State128 after actual optical configuration |
| AUTOFOCUS | AF32 | u64 focus_um, u64 score_Q16, u32 coarse/refine counts, 8 zero bytes |
| VDF_PATH (5) | Canonical16 | Fixed Vdf160 config/actual-sink receipt; no result token |
| VDF_ZEBRA (6) | Zebra8: five source bytes + reserved zero3 | Fixed Zebra168 saved config/current-route/actual-sink receipt; no result token |
| VDF_LAYOUT (7) | Exact original014c case0 body32 | Fixed Layout192 saved layout/current-route/actual-sink receipt; requires active 640×480 route; no result token |
| VDF_DISPLAY_CONFIG (8) | Typed16: LEu32 original command, LEu32 original body size, body8 | Fixed Display176 independent saved feature/current-route/actual-sink receipt; only disabled0152 and off0162; requires active route at current RGB geometry; no result token |
| BB_STARTUP_CONFIG (9) | Canonical32: LEu16 original command, LEu16 body bytes, body28 | Fixed BB192/class5, five independent initial/neutral software banks; active 640×480; no result token |
| HISTOGRAM (10) | Canonical8: LEu16 0148, LEu16 4, original body01010000 | Fixed Hist1192/class6: base160 + saved input8 + actual sink-derived software Y/R/G/B heights1024; active 640×480; no result token |
| VDF_BIT_WIDTH (12) | BitWidth8：selector0及七个保留零 | 固定168B/class7；真实active640×480 RGB sink/读回/retire及独立Config8读回；原物理位深未知，见[位宽合同](../disp-bit-width/README.md) |
| STILL | Still16, optional 128-byte DQT | Actual full JPEG or SOS/entropy/EOI suffix |
| VIDEO_BEGIN | Config48 | State128 after opening the real stream |
| VIDEO_FRAME | empty | Packet96 + Annex-B config + real packet; empty only if actually buffered |
| VIDEO_END | empty | Actual tail packet records, or a header-only drained EOS record |
| READ_RESULT | token, current offset, capacity, reserved0 | Next actual encoded-result chunk |
| RELEASE_RESULT | token, whole-result FNV1a64 | Zero bytes after complete read/hash verification |
| CANCEL | empty | State128 after cancelling real codec work and discarding a live result |

Apertures are exactly f/4, f/8 and f/16, matching the installed renderer. Config
flags/reserved fields must be zero. Dimensions are 1..8192 for still config;
video is independently 2..1920 × 2..1080, both even, fps1..120. Quality1..100 uses
libjpeg's actual `jpeg_set_quality` tables, reordered from natural to zigzag;
this is an explicit functional policy, not a claimed Sony default. Optional
source DQT arrays are used exactly and must contain no zero element. A still
request uses its own validated dimensions/quality, then restores the configured
preview/record geometry without resetting counters or incrementing config
generation for that temporary geometry.

The still path reuses `vcam_capture_still`, its source-derived prefix, actual
hardware-model SOS/entropy encoding and exact destination readback. Video
acquires/renders/consumer-reads/retires one real optical lease per accepted frame
and feeds `video_engine_stream_feed_rgb888`. The sink copies borrowed packet
bytes and extracts the first packet's actual SPS/PPS before feed returns. Every
Packet96 carries real encoder pts/dts/duration with time base1/fps. Records are
delimited by `96 + config_bytes + packet_bytes`; END sets EOS on the final record
only after real finish/drain. The installed zero-latency engine permits one
pending frame; an unexpected buffered frame prevents another feed and may be
resolved by END. No compressed packet is fabricated, and no 600-frame aggregate
limit is applied to streaming. Native AVCC conversion and native PTS conversion
belong to the original-MPR adapter.

## VDF path transaction

[VDF wire offsets](../../runtime/analysis/functional-vdf-path-abi.h) define the
16-byte request and 160-byte reply. This profile defines one RGB endpoint
`0x90590819`, selected/completed mask1. Route1/pins5,5/class1 enables its software
RGB source/destination; route0/pins1,1/class0 disables it. This mapping does not
establish Sony physical pin/selector/clock semantics. Both routes accept byte4
only in 0..2, require canonical tail13..15=0 and preserve bytes3/5..12 opaquely.
The common bodies are `01050500` + 12 zero bytes and `00010100` + 12 zero bytes.
Other routes are EINVAL; no additional device gets an invented completion bit.

The model copies the canonical configuration into staged device storage, reads
it back and verifies all 16 bytes. Enable configures/readbacks the existing
optical owner with the current geometry/optics, then uses its actual
acquire → render → consumer_read → retire sequence. The consumer callback copies
every active RGB row into independent sink storage. It hashes that sink's real
bytes; after the callback the core hashes it again and compares the whole sink
to every active source row before counting consumption. All stages and retirement
must succeed before parent configuration/class commit and completed-mask1.
There is no JPEG, H.264, host media export or second CMOS owner in this route.
Disable saves/readbacks/commits its configuration without acquiring a lease or
changing rendered/consumed/retired/frame counters. Every successful request,
including an exact repeat, commits one new configuration generation. Every
enable also renders, consumes and retires exactly one new frame.

Vdf160 contains ABI1/size160, model instance, committed config generation, current
global frame generation and current optical-owner lease epoch, original input
FNV, actual source/sink FNV, active byte count, current width/height/stride,
endpoint, selected/completed masks, class/enabled, config-readback/committed,
actual frame-consumed/retired, status0/reserved0, exact 16-byte canonical readback,
and the before-frame/config generations. Disable's lease generation,
source/sink FNV, active byte count and consumed/retired flags are zero; geometry
and unchanged global frame generation remain visible. Fixed replies require
capacity>=160, return used160 and
zero token/total/offset, and do not increment encoded-result read counters.

Pending encoded results, active recording, busy owner/model, invalid bodies,
insufficient output capacity and exhausted counters reject before a job or
allocation. Runtime config/copy/source-mutation/sink-mutation/retire failures
leave the old committed config/generation intact, preserve actual partial
observations, return EIO and leave stream_state3/device busy. No success receipt
is copied on failure. CANCEL clears device busy only after the existing owner
is genuinely idle; it cannot silently retire an invalid live lease.

## Zebra 显示配置事务（OP6）

原 AP0153 请求 `0d2053010e0001800300204b4100` 对应 Zebra 显示配置；
CP `69abae..69abf2` 保存请求 `+8..+c` 五字节。这里将它们作为独立显示配置保存，
不映射到曝光、ISO、fps、尺寸、光圈或焦距。`Zebra8` 输入为
`03 00 20 4b 41 00 00 00`：前五字节为源配置，后三字节为虚拟保留零。
原阈值单位、enabled 算法和 CP 条件 gate 均未证明；本轮仅实现 byte1 enable=0，
其他 enable 返回 `-ENOTSUP`，保留非零或长度错误返回 `-EINVAL`。
byte0/2/3/4 原样保存，不推测标志、selector 或阈值单位。

OP5 和 OP6 复用 `vdf_transaction`、原有 optical owner 与 `vdf_frame`，
Zebra 使用独立的 staged5/committed5 保存区。事务先保存并读回五字节，
当前 route active 时实际 acquire → render → consumer_read，全行复制到独立 RGB sink，
逐字节及 FNV 读回一致并成功 retire 后，才提交 Zebra 和软件 config generation+1。
此 generation 是新的软件显示配置事务序号，不代表原 CP RAM generation。
JPEG/H.264/encoder 计数、全部 Config48 内容和已提交 route16 保持不变。
当前 route inactive 时只保存/读回配置，不分配 sink、不获取 lease，
rendered/consumed/retired/frame generation 均不变；selected/completed mask1
表示实际完成了配置事务。enable=0 不关闭已经 active 的 VDF route。

168B 回执前160B 使用既有 VDF schema：`INPUT_FNV` 覆盖实际 Zebra8，
`CONFIG16` 为当前已提交 route，尾 `160..167` 为保存区读回五字节加三个零。
class/enabled/frame-consumed/retired 跟当前 route；inactive 的 lease、source/sink FNV、
active bytes 为零。两种情况都输出实际软件 endpoint `0x90590819`、mask1，
不声称原 Zebra gate 已运行或物理 ASIC 兼容。新 proof 保持原376B ABI，opcode6/kind4；
inactive proof 没有帧或消费计数差值。

重复成功 Zebra 事务也推进一次 config generation；重复空 INIT 保留现有配置和回执，
不增加 probe/frame。pending JPEG、active video、owner/model busy、错误输入、
输出容量不足168（包括167）和计数溢出在动作前拒绝。实际配置、部分复制、source/sink
篡改、staged 配置变化或 retire 失败保留旧 Zebra/route/config generation，
返回错误、记录实际失败阶段，并且不写成功回执。原有 CANCEL/owner-idle 恢复规则不变。

## Layout 显示配置事务（OP7）

本轮仅支持原 AP `vdf_set_yuv_layout` case0 的精确32B body：

```text
07010100000000008002e0010000000000000000000000000300000000000000
```

这是授权的 `virtual-functional-camera-v1` 软件 policy：将四个 LE u16 输入分量
显式定义为 `x,y,w,h = 0,0,640,480`，全零 output-area 定义为整帧透传。
sel7/layout1/src1、aspect/type0、u8 timing3、u32 id0 和全部 opaque/padding 字节
均严格原样匹配。它们不代表已证明的 Sony 物理枚举、YUV 分量顺序、CMOS 配置或
编码尺寸。错误长度返回 `-EINVAL`；其他 body（包括任一 opaque 非零）或当前配置
非640×480返回 `-ENOTSUP`。当前软件 route 必须已由成功 OP5 提交为 active1/pins5,5；
从未提交 active route 或已禁用均返回 `-ENODATA`，没有默认 route/尺寸回退。

OP7 扩展既有 `vdf_transaction`，使用独立 staged32/committed32 和 `layout_valid`；
初始 valid=false。保存并读回完整 layout 后，消费回调从 staged layout 读取宽高，
要求与实际 RGB view 一致，再复用同一个 optical owner 执行 acquire → render →
consumer_read，逐行复制到独立 sink，核对全部921,600B和 source/sink FNV，并成功
retire。再次核对 staged32、从 committed32 独立读回全部32B后，才设置 valid、提交
config generation+1 和 frame generation+1。Config48 的全部配置、当前 route16、
Zebra5、video packet generation/PTS 和 JPEG/H.264/编码结果读取计数不因 OP7 增长。
重复成功 OP7 同样实际消费一帧；重复空 INIT 返回当前 State128，不重复 probe，
不重置现有 layout、配置、frame/rendered/consumed 或上一个 proof。

Layout192 的前160B沿用 VDF schema：`INPUT_FNV` 覆盖 layout32，`CONFIG16` 为
实际当前 route；尾 `160..191` 为独立保存区读回的原 layout32。响应大小192、
endpoint `0x90590819`、mask1、config-readback/committed/frame-consumed/retired1
均只在整个事务成功后输出。仍无 result token、主机媒体文件或编码器调用。
376B proof ABI 保持不变，opcode7/kind4 记录实际 source/sink、阶段、owner lease epoch
和提交后的 generation；成功时 source 与 sink 全字节相同。容量必须至少192，
容量/shape/route/geometry/busy/pending/overflow 拒绝均在分配或实际动作前完成，
保留全部 model、旧 proof、输出和 exec-result。

实际配置/源变化/部分拷贝/sink或staged变化/lease/retire 失败返回 `-EIO`，不写成功
响应，保留旧 committed32/valid、Config48、route/Zebra 和 config/frame generation。
真实已完成的 rendered、完整 sink consumed、retired 及 underlying owner lease epoch
仍如实记录；它们不能回滚成“未发生”。例如 retire 失败可保留一次真实完整拷贝，
但不能发布新的 layout frame generation。没有 consumer callback 或零/错误 lease
无法获得成功完成。故障后沿用原 CANCEL/owner-idle 规则；活跃未退休 lease 不会被
CANCEL 静默清除。

源合同来自研究目录 `analysis/scratch/functional-bb014c-source/RESULT.md`：
AP `34f132c..34f1e10` case0；CP external014c→event9e→`1cd908`→0305，
1305→event298→独立114c，成功 wire 为 `0d204c110c00018000005900`，metadata source
`92840747`。该12B native回复及实际 AP receive/free 由集成层负责；此 core 只返回
Layout192。真实物理0305工作/1305生成和实际 metadata source→原FIFO 的入口未证明，
`physical_asic_verified`、`physical_cp_rtos_verified`、`original_selector_verified`、
`original_cp_fifo_verified` 与 `capture_verified` 均不能因本组件通过而变成 true。
本轮没有验证原 AP014c 消费，也没有原 JPEG/MP4 产出。

## Peaking / 匿名 flag 显示事务（OP8）

OP8 的 typed envelope 为固定16B：`LEu32 original_command`、
`LEu32 original_body_bytes`、`body8`。只允许以下两个独立功能：

| 原命令 | 原 body | 此功能模型允许的值 |
| --- | --- | --- |
| 0152 peaking | 8B | body0 selector3、body1 enable0、body2 level0..2、body3 magnification0/10/40、body4 color_type0；body5..7 仅 `(81,90,240)`、`(210,16,146)`、`(29,255,83)`、`(235,128,128)` 四种原 palette |
| 0162 匿名 flag | 2B | 原 body 两字节均为0；后六字节为虚拟保留零 |

本次真实0152 body 为 `0300010000eb8080`。对应的完整功能 envelope：

```text
0152: 52010000080000000300010000eb8080
0162: 62010000020000000000000000000000
```

selector、level、magnification、color_type、y/cb/cr 的字段名继承原源码；
不推导物理单位、色度范围、ASIC packing 或空间算子。peaking enable1 及任何
其它未支持值返回 `-ENOTSUP`；0162 的功能名/on 行为仍未知，任一原 body 字节非零
也返回 `-ENOTSUP`。未知 command 返回 `-ENOTSUP`；envelope 长度、原 body size
或0162虚拟 padding 不合法返回 `-EINVAL`，不能退化成任意命令保存或通用 ACK。

两个功能均必须已有成功 OP5 提交的 active route1/pins5,5/class1；尚无 active route
或 route 已 disabled 返回 `-ENODATA`。它们使用当前合法 Config48 的全部 RGB 几何，
包括1×1和奇数尺寸，无 crop，不要求640×480，也不要求已有 layout。disabled/off
只定义显示效果透传，不禁用正在工作的 RGB route，不更改光学或 Config48。

OP8 直接扩展原 `vdf_transaction`，为0152和0162分别保留独立 staged16/committed16。
每次先保存并读回完整 envelope，随后复用同一个 optical owner 的真实
acquire → render → consumer_read → 独立 sink 全行复制 → 全字节/FNV读回 → retire。
再次核对 staged16、从对应 committed16 独立读回后才提交 config generation+1 和
frame generation+1。另一功能的保存区、Config48、route16、Zebra5、layout32/valid、
JPEG/H.264、packet generation、编码结果读取计数均保持；重复相同请求仍消费一帧。

Display176 前160B沿用既有 VDF schema，`INPUT_FNV` 覆盖完整 typed envelope16，
`CONFIG16` 始终为当前 route；尾 `160..175` 来自当前功能自身保存区的16B读回。
class/enabled/frame-consumed/retired1 表示 active RGB route 和本次真实消费，
不表示 peaking/匿名 flag 被开启。容量至少176，`used=176`、token/total/offset=0；
`FCAM_VDF_RESULT_MAX_BYTES` 仍为192。376B proof ABI 保持不变，opcode8/kind4，
记录真实 source/sink、消费阶段、owner lease epoch 和提交后的代次。

长度/值/route/capacity/busy/pending/overflow 错误在动作前拒绝，旧 proof、模型和输出
不变。实际 config/consumer/完整拷贝/staged/retire 失败返回 `-EIO`，不提交任何功能
配置或 config/frame generation，不写成功回执；真实 rendered/完整 sink consumed/
retired 和底层 lease epoch 的阶段计数仍保留。恢复沿用 owner-idle/CANCEL 规则，
未退休的真实 lease 不能被 CANCEL 静默清除。

源合同为项目研究目录 `analysis/scratch/functional-cp-vdf-startup-inventory/RESULT.md`
和 `analysis/scratch/functional-ap-startup-frontier/RESULT.md`。原 AP0152 producer
`034e7e9c`、CP `001ce138` 转0202，1202→29c→独立1152；原 AP0162 producer
`034e9068`、CP `0069f078` 转0325，1325→29f→独立1162。两者成功 status 均为
`00590000`。原12B1152/1162 的独立发送、AP receive/free 和原消息身份由 guestmain
集成层负责；core 只返回本次 Display176。原下游物理工作/完成生成仍未证明，
`capture_verified` 和各 physical/original FIFO 验证标记保持 false。

## BB startup and first histogram (OP9/OP10)

范围为本机独立 `virtual-functional-camera-v1`，授权见根约定 §8；报告 flavor=null。
本节只验收 core 的有限 initial/neutral 配置和一次真实 sink histogram。原 AP 触发、原回复/
notification 的 receive/free、持续数据及 UI 消费、编码→原 MPR/Fsys→虚拟 SD 成片均由
parent 独立集成，`capture_verified=false`。旧 strict profile、16页邮箱、State128、
Config48、旧 op 行为及旧 `FCAM_VDF_RESULT_MAX_BYTES=192` 保持；新 histogram 调用方
单独提供1192B，不能使用旧192B owner 的数组。

共享合同为 [functional-bb-startup-abi.h](../../runtime/analysis/functional-bb-startup-abi.h)。
OP9 的32B是 `{LEu16 native_cmd, LEu16 body_bytes, body28}`，未用尾部必须全零；
各命令有独立 staged32/committed32/valid，不借用 route/layout/display/Zebra 字段。
每个 bank 的完整32B均保存并读回，另有实际软件应用状态；下表是软件政策，
不声明 Sony 物理单位、默认 CP RAM 或延后 RTOS 工作已验证。

| 原命令/body长度 | 仅支持输入（body相对偏移） | 实际软件功能 | 继续拒绝/未完成 |
| --- | --- | --- | --- |
| 0111/28 | 首4B `00000f02`，body4..27全零；sqMode:u8@4/rate:u32@8均0 | 独立 SQ idle/off 状态；本代真实 RGB passthrough。VIDEO_BEGIN 检查该软件 off 状态，原缺省视频准入保持 | 非零 SQ/rate/aux、原重新配置/延期工作、回调及 RTOS |
| 0166/28 | `0001`+26零字节，或精确 observed initial body（见下文） | 两个明示软件 RGB identity look token；独立保存/readback 原 cfg624/628 对应两字节及六个opaque u32，不把 word 当地址/单位 | 其它 look/resource/display-gain 行为、Sony CreativeLook 算法 |
| 0167/2 | LEu16 0或1，body1和unused tail为0 | 两个 opaque RGB identity 输入域，均实际消费同一帧 RGB | Sony gamut 名称、矩阵、其它tag；AP→wire反转仍由原 producer/guest 保留 |
| 015f/4 | LEu32 0 | 软件 gain tag 初始0；输入0 **保持旧tag**，不是clear。Config48 ISO（默认100或原当前ISO）不变 | 非零标签、EiGain物理单位、ISO数值映射 |
| 0128/12 | `00010000`，word4∈{60,50,40,30,20,10,9,8,7,6,5,4,3,2,1}，body8..11全零 | interval scheduler disabled，无事件产生；独立保存/readback opaque pending-enable ticks | enabled/delay/真实timer动作；不能把period称Sony秒/帧 |

OP9/OP10 必须已有 OP5 提交的 active1/pins5,5/class1、640×480 RGB；core无active
clip、pending encoded result、busy/fault或未退租owner。长度、cmd/bodylen、virtual
padding、非neutral/enable、几何、全部输出容量和计数预算都在动作前拒绝，保留旧
配置/帧代际、旧输出和既有工作。不会为了 neutral0111 强行 CANCEL clip。
成功依次完成 staged保存/readback → 实际 CMOS render → 原 `vdf_copy` 独立 sink
逐字节copy/readback → 真实retire/idle → 独立bank及完整reply cache保存/readback →
config/frame generation各+1。原Config48的fps/ISO/曝光/光圈/焦点不借作新字段。

BB192 的前160B沿用 VDF schema：INPUT_FNV覆盖完整32B，CONFIG16仍为当前route，
class5；tail160..191为本feature的独立canonical32读回。instance、before/current
config/frame/lease generation、921600 active bytes、source/sink hash、copy/retire
标志均来自本次真实事务。host proof的376B布局不变，新kind5；encoded消费/字节和
result token均0，`result_bytes=192/result_fnv`覆盖完整固定缓存。

OP10 input8 精确为 `4801040001010000`，只支持 enable1/mode1/flag0/reserved0。
Hist1192 前160B同schema但class6，tail160..167独立读回原canonical8，168..1191是
四段各256B。**这里显式定义软件256bins、u8柱高、Y/R/G/B顺序**：

```text
Y = (77*R + 150*G + 29*B + 128) >> 8
height[channel][bin] = (count[channel][bin]*255 + peak[channel]/2) / peak[channel]
```

全部是整数除法，每段独立peak归一化；空RGB输入拒绝。每个count真正遍历同一份
已copy/readback且retire后的**model-owned sink像素**，不从统计摘要或FNV制造数组。
没有保留 borrowed view/lease 指针；sink仍归model所有。计算前后核对sink FNV与原
source，并将完整1192B保存到独立cache再全字节读回；失败不提交config/frame代际，
已有valid/cache保留，真实render/copy/retire事件仍如实计数。kind6 proof的
`result_bytes=1192/result_fnv`覆盖这个完整固定缓存。该cache不占encoded-result
cursor，后续真实JPEG仍按旧read/release协议消费。

原210c逻辑1034B header `0d200c210a040180`、选择字段及四段的分配/发送/free属于guest；
core不构造OSAL包。此处是单次 first-frame sample，重复OP10会另取一帧，未承诺持续
histogram、原future/notification送达、0xd5事件到UI解释或C的全部功能完成。邮箱nonce/
sequence/native-origin认证属于parent transport；core保持不透明instance身份，不新增
或声称完成transport认证。parent约定的 bridge 名为
`fcam_bridge_bb_startup_config(origin,input32,out192,meta)` 与
`fcam_bridge_histogram(origin,input8,out1192,meta)`；本组件只提供model op。

| 验收层 | 本组件结论 | 仍需独立证明 |
| --- | --- | --- |
| staged/copied/readback/semantic model | 声明的有限软件idle/identity/first-hist功能；实际帧事务为验收前提 | 非neutral功能、连续调度/通知 |
| 原CP/ASIC/RTOS/FIFO | `original_cp_verified=false`, `physical_asic_verified=false`, `original_cp_fifo_verified=false` | 原CP完整工作/延期/物理入口，不由软件model成功提升 |
| AP业务与媒体成片 | `capture_verified=false` | 原AP触发与消费、原MPR/Fsys写虚拟SD、独立解码整链 |

来源直接复用研究成果，未重做survey/提取：
`analysis/scratch/functional-cp-vdf-startup-inventory/AFTER-BB-RESULT.md` §1/§3与
`after-bb-source-pins.json`，及
`analysis/scratch/functional-histogram-0148-source/RESULT.md`、`source-pins.json`。
研究目录是私有工作树来源，不作为公开runtime依赖；原AP SHA256
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`，原CP SHA256
`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，本轮只继承源
身份/字段宽度/四段结构，不声称重新验证这些原件或闭合未知CP工作。

- **E-BB1**（file/source表）：上述§1/§3确证五命令的原body宽度、source字段及015f零保持；未知0111延期/下游工作继续保留。
- **E-HIST1**（file/source表）：上述0148报告确证210c逻辑1034B、四段256B、future与通知分离；256bins/u8/YRGB为本次软件政策。
- **E-MODEL1**（command）：本节下方定向pytest复现实际CMOS→sink逐字节消费、全部192/1192B独立Python golden与normal/ASan/UBSan故障矩阵。
- **F-BB1**（n/a_re，evidence_ids=E-BB1/E-MODEL1）：五bank的有限软件语义和真实RGB帧事务可验收；不能升级为Sony全功能C完成。
- **F-HIST1**（n/a_re，evidence_ids=E-HIST1/E-MODEL1）：四段内容来自同一真实sink，软件公式可独立复算；原物理bin及UI仍unknown。
- **P-BB1**（callflow）：canonical输入校验→独立staged/policy→实际lease render/copy/readback/retire→软件hist（仅OP10）→独立bank/cache完整读回→代际提交→固定reply；每步关联E-MODEL1，输入/物理边界分别关联E-BB1/E-HIST1。

### BB0166：精确 observed initial identity 增量

`run-pgf891an` 的 saved console stack 在 `0x7f34e6df78` 保存原 builder 的36B：

```text
wire36 = 0d2066012400018000010000000000000000000008000000070000000100000001000000
body28 = 00010000000000000000000008000000070000000100000001000000
input32 = 66011c0000010000000000000000000008000000070000000100000001000000
```

复用完整原 `034ebb84..034ebc5c` 的216B builder，SHA256
`8ff3613629f6eed955e79ef7c4af567a8d9fb8385931c6874f9d22cfcade9116`：body0/1为u8，
body2..3留零，body4/8/12/16/20/24为六个LEu32，观察值为`0,0,8,7,1,1`。
原 `034ebc1c` 设置36B、`034ebc24` 指向header、`034ebc38` 调共享send；
`df98`只取低u32，`df9c..df9f=7f000000`不在包内。父核原FP/ELF链的base为
`0x7f46b2b000`，证据与字段span见
[原source及观察pin](../functional-vdf-path/source-pins.json)的`bb_0166_observed_initial`。
这些是 **stack-held 原builder** 内容；另一个栈槽中的request pointer `0x7f9b139840`
没有live读回。保留原批次的 shared-send assert 失败，不归因为allocation失败，
不把此修正或unit pass改判为原AP消费、主界面恢复或拍摄成功。

用户批准的功能策略只给旧explicit neutral和这个完整literal选择软件RGB identity。
共享header的`fcam_bb_0166_body_valid`与`fcam_bb_0166_identity`分别校验原body和
完整u32软件状态，由core与guest复用；core仍实际保存原六个word，sink只在完整token
匹配后消费真实RGB，再按原bank/cache/readback/retire提交。其它四命令范围不扩大。
不把8/7/1/1命名为Sony对比度/gamma或换算成系数；原physical/work/units均false。

定向复现（项目ROOT，仅本机临时测试构建，不替换运行模型）：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider \
  report/functional-camera-core/test_functional_startup.py -q
```

实际normal与ASan/UBSan共8项通过。独立Python逐字节oracle核对新literal的完整192B、
class5、完整input32/result192 FNV、921600B source=sink、render/copy/retire与代际；
追加的同一状态histogram也消费真实sink。新literal具有完整原失败注入矩阵；两种token
的每个body字节全部255个替换值均拒绝，完整u32状态高位也拒绝。
**E-166-stack**=上述不可变saved观察与原builder pin；**E-166-model**=本节定向命令、
C/Python oracle；**F-166**（n/a_re，source shape/host software validated，high，
evidence_ids=[E-166-stack,E-166-model]）仅确认这两个软件identity token。
**P-166**：精确body→shared校验→独立canonical32 bank→真实RGB sink/retire→完整192B；
原AP/VM及成片链保持独立未验。时间线：读原stack与完整builder→共享策略修正→真实
core与owner分别严格/消毒测试→profile/evidence精确声明；不修改failed run。

## Result ownership and errors

The model returns 0 or negative errno. Input/output declared spans are bounded
by FCAM_DATA_BYTES, must be live accessible objects of the stated sizes through
return, must not wrap, and must be disjoint from each other, the exec-result
object and model storage. Alternate virtual mappings of the same allocation
are forbidden by the accessibility contract. The model retains no caller
pointer. Validation errors preserve caller output, exec-result and public model
configuration/counters. A real codec/consumer failure can consume/render input;
it reports a negative error plus explicit stream_state3, with truthful stage
counters, and requires CANCEL before new work.

One encoded result is held at a time, bounded by FCAM_MAX_RESULT_BYTES (64 MiB).
The producing request requires output capacity >=1 and copies its first chunk.
Its exec-result has `{token,total,offset=0,used}`. READ_RESULT requires a matching
token/current cursor, nonzero capacity <= output capacity, and copies up to the
remaining bytes. The returned offset names the first byte of that chunk.
RELEASE_RESULT requires every byte read and the full-result FNV1a64, which is
also recomputed over the model's actual buffer before retirement. The token is
monotonic/nonzero for a model lifetime; CANCEL invalidates it without reuse.
While pending, only STATE/READ/RELEASE/CANCEL are allowed.

| Error | Meaning |
| --- | --- |
| EINVAL / ERANGE / E2BIG | Invalid spans, shape, flags, values or declared limits |
| ENOSPC | Fixed reply too small or READ capacity exceeds supplied output |
| EBUSY | Pending result or active recording forbids the operation; incomplete RELEASE |
| ESTALE / ESPIPE / EBADMSG | Wrong token / nonsequential cursor / wrong whole-result hash |
| ENODATA | Fully read result, actual AF search with no contrast, or layout/display/BB/histogram without a committed active route |
| EPIPE / EAGAIN | No active video stream / actual encoder still has a buffered frame |
| ENOTSUP | Unknown opcode/typed display command, unavailable probed codec, unsupported Zebra/peaking enable, flag value or layout/body/geometry |
| ENOMEM / EOVERFLOW / EIO | Allocation / counter exhaustion / explicit hardware-model fault |

State counters are lifetime stage events. `rendered` counts completed leased
source frames, including the once-only sensor probe; `consumed` counts the JPEG
hardware model's real input attempts, accepted H.264 frames and complete
verified VDF sink copies, and encoded counters count successful JPEG readback
and actual received compressed video packets, including packets rejected by a
failing sink. `result_bytes_read` advances only after copying actual encoded
result bytes into the caller's span, including the first chunk. AF scratch
renders are represented by actual coarse/refinement counts in AF32 rather than
leased-frame counters. Global frame generation counts leased rendered frames
across both owners, except OP7/OP8/OP9/OP10 publish their new frame generation only after
the whole display/software transaction commits; failed renders for these ops remain visible in
`rendered` and the optical lease epoch. Each underlying owner additionally
retains its own checked lease epoch and active-pixel hash. Successful explicit config/AF increments
config generation; no configuration, INIT or CANCEL resets counters. None of
these events claims AP, native MPR, Fsys or capture acceptance.

## Read actual frame content after the original job

`fcam_model_proof_snapshot(model, &proof, sizeof(proof))` is a **host-only**
read-only API. The existing create/destroy/request signatures and shared FCM1
transport ABI are unchanged. Its fixed v1 POD is 376 bytes: all scalars are
`uint64_t`, except the four signed `int64_t` statuses, and `before`/`after` each
contain five `uint64_t` counters. There are no pointers, `size_t` fields, borrowed
objects, new capture operations, rendering calls or encoder calls in the
snapshot. Use it only after the original synchronous request returns and under
the same external serialization lock. It returns 0 or negative errno; wrong
size/alias is EINVAL, active execution is EBUSY, a model inherited across fork
is ECHILD. The output stays unchanged on error. The caller must provide a real,
live, disjoint object; checking arithmetic cannot prove an arbitrary mapping.

The complete member order is in [functional-camera-core.h](functional-camera-core.h).
`FrameProof`/`ProofCounts` in the broker bind that exact layout through ctypes.

| POD members | Actual observation and interpretation |
| --- | --- |
| `version`, `struct_bytes`, `serial` | v1/layout and monotonic job receipt serial; serial0 means no probe/frame/drain/VDF transaction yet. |
| `model_instance`, `model_lifetime`, `owner_pid` | Mailbox nonce, process-local nonreused model creation ordinal, actual host process PID. A new model has a new lifetime even with the same nonce. |
| `opcode`, `consumer_kind` | Actual originating core operation; kind0=INIT probe, 1=JPEG source consumer, 2=H.264 source consumer, 3=drain/finish, 4=VDF RGB sink, 5=BB neutral software transaction, 6=first software histogram. |
| `config_generation`, `frame_generation`, `lease_generation`, `packet_generation` | Config at the actual job; global frame ordinal (OP7/OP8/OP9/OP10 advance only on complete commit); checked underlying optical-owner epoch; actual H.264 Packet96 generation. Failed renders for these ops can advance render/lease observations without a new committed frame ordinal. The still and video owners have separate lease epochs; never join on lease generation alone. |
| `width`, `height`, `stride`, `active_bytes` | Actual rendered view geometry, byte stride, exactly `width*height*3` active bytes. All zero for a drain without a new source frame. |
| `source_fnv1a64`, `consumer_before_fnv1a64`, `consumer_after_fnv1a64` | Hashes read from the real model-owned buffer after render, at the actual JPEG acquire/H.264 feed boundary, and after the actual hardware-model call returns, while the same optical lease remains held. |
| `render_observed`, `consumer_entered`, `consumer_returned`, `encoder_consumed`, `retired` | Actual stage observations. JPEG consumed means its encoder input attempt, H.264 consumed is the actual feed counter delta. An entered/returned drain does not mean an RGB frame was consumed. |
| `source_state`, `consumer_before_state`, `consumer_after_state`, `final_state` | Actual optical owner states: successful source observation is RENDERED3, source consumer is READING4 before/after its call, successful retirement leaves IDLE1. Zero means no corresponding observation. |
| `render_status`, `consumer_status`, `retire_status`, `operation_status` | Raw optical statuses, actual VJPEG/video-engine consumer enum, raw optical retirement status, actual outer request errno. `-ENODATA` marks a stage never called. Consumer return alone never establishes success; outer error/retirement/byte extent remain relevant. |
| `before`, `after` | Lifetime `rendered`, `consumed`, `jpeg_encoded`, `video_encoded`, `retired`, captured before/after the actual job. Failed consumers retain real counter advances. |
| `encoded_bytes`, `encoded_fnv1a64` | Actual JPEG SOS/entropy/EOI bytes handed to the destination writer, or ordered actual Annex-B packet payloads delivered to the H.264 sink. Excludes the functional JPEG prefix, Packet96, and duplicated Annex-B config. Sink-rejected encoded packets can be observed with an outer error. |
| `result_bytes`, `result_fnv1a64`, `result_token` | Exact staged representation offered through the original retained-result protocol: full JPEG or suffix, or Packet96/config/AU records including actual final EOS flags. For OP9/OP10, bytes/FNV instead cover the complete fixed192/1192B cache, with token0. On failure, partial staged bytes remain observations rather than a published result. |

VDF appends consumer kind4 without changing any earlier value or the 376-byte
POD layout. For that kind, consumer-before FNV reads the source and
consumer-after FNV independently reads the packed sink (including a partial or
changed sink on failure). Consumer status is the actual optical-owner status.
Its `encoder_consumed`, encoded byte count and encoded-result fields stay zero;
the lifetime consumed delta describes the verified sink copy. Route disable or
inactive Zebra emits a new kind4 transaction receipt with no rendered/consumed
frame or retired lease; Zebra on an active route consumes a pass-through RGB
frame even with Zebra enable0. Supported layout always requires an active route
and consumes one real full-frame RGB copy before committing its layout.
Supported OP8 features also require an active route and each consumes one real
full-frame copy at the current geometry before committing its independent envelope.
STATE/READ/RELEASE/CANCEL preserve that receipt just as they preserve old jobs.

All pixel hashes are FNV-1a64, offset basis `14695981039346656037`, prime
`1099511628211`, modulo 2^64. Feed active R,G,B bytes in top-to-bottom row order,
left-to-right byte order. Each row contributes exactly `width*3` bytes beginning
at `pixels + row*stride`; all inter-row and final-row padding is excluded. This
matches the renderer/owner's active-pixel ordering, but receipts recompute bytes
at the real boundaries rather than copying the metadata hash. `active_bytes`
and stride must both be checked. Zero byte counts use the FNV offset basis for
encoded/result empty digests; unobserved source/consumer hashes are zero.
FNV is a consistency check, not a collision-resistant authentication mechanism.

JPEG instrumentation lives in `camera-pipeline.c`: source after the actual
`optical_frame_render`, consumer before in the exact `jpeg_acquire` callback
that supplies `vjpeg_frame.rgb`, encoded suffix in `jpeg_write`, consumer after
`vjpeg_hw_execute` returns, and retirement only after borrowed consumer return.
`vcam_frame_proof_snapshot` copies those scalar observations to the core. H.264
instrumentation reads the actual `video_engine_rgb.data` immediately before and
after `video_engine_stream_feed_rgb888`; its sink hashes the actual received
packet payload even if a later bound/copy fails. No independent test image or
alternate encoder supplies these receipts. Raw RGB is never dumped by the broker.

The first INIT receipt describes the real 640x480 default probe and its actual
retirement, including when INIT supplies a different Config48. Config is
restored as before. Its encoder counters/encoded bytes stay zero and it has no
consumer. Repeated INIT, STATE, CONFIGURE, AF, READ_RESULT, RELEASE_RESULT and
CANCEL leave the preceding receipt unchanged; a previous capture is never
relabeled as their work. VIDEO_END emits a distinct drain receipt with no new
RGB extent. A failed/partial job retains its actual error and stage observations.
Validation rejected before a job starts leaves the previous receipt unchanged.

## Join broker binary chunks to the frame receipt

The broker's original single C request call remains in place. It calls the
read-only snapshot after that job, under its existing serialized worker. Each
new receipt serial emits one additive `model_frame` event. That event contains
`sequence`, `opcode`, actual header `origin`, `actual_c_result`,
`actual_core_sha256`, `request_payload`, `output_payload`, full scalar `proof`
and `native_acceptance:false`. The core library SHA must still be bound to the
parent-frozen model/helper source archive and tested build. The broker checks
that unchanged snapshot serials preserve the entire prior POD; reads of old
proof do not emit new frame events.

Each actual accepted request retains exactly two **binary chunks**, including
empty input/output, in the exclusive owned run subdirectory
`functional-camera-data/`: `{sequence:020d}-in.bin` and
`{sequence:020d}-out.bin`. They contain exactly the input passed to ctypes and
the bytes returned from that C call. State128 is therefore retained as real
bytes too. These are transport evidence files, not JPEG/MP4 exports or standalone
media generation. No full RGB buffer is saved. The subdirectory is mode0700;
files are exclusive `O_EXCL|O_NOFOLLOW` creations, mode0600, regular, single-link,
never overwritten by this producer. File/directory identity is pinned and
checked. Writes are fsynced, read back and compared exactly with the immutable
in-memory bytes plus SHA/FNV before a record is returned, then checked again
before mailbox commit. The producer retains a failed partial file as failure
evidence, poisons the store and stops; it never truncates or invents a record.

The binding event exposes `payload_policy`: per-file ceiling 64 MiB, aggregate
raw-byte budget 512 MiB, maximum 65,536 files, exact directory and source kind.
Actual FCM1 payload chunks remain at most 65,024 bytes. A full budget, unknown
short read, corrupt writeback, existing path/link, replaced directory, wrong
mode/owner, write/flush error or changed C-result metadata prevents a successful
response and is reported through the existing failure/cleanup path. SDSTOP,
physical-mode restore, owner/socket validation and DETACHED ordering remain as
before, including the parent's dirfd Unix long-path connection fix.

`request.request_payload`, both refs in `core_result`, both refs in committed
`response`, and both refs in `model_frame` refer to the same immutable chunk
records, never newly generated representations. All original event fields are
preserved. The refs contain:

| Reference keys | Exact source |
| --- | --- |
| `path`, `source_kind`, `direction` | Direct relative `functional-camera-data/<sequence>-in/out.bin`, `actual_hardware_transfer`, `in` or `out`. |
| `producer_event`, `sequence`, `opcode`, `model_instance`, `origin` | Exact request/core-result JSONL event number, native request sequence/opcode, mailbox nonce, and unchanged native header producer TID/source SID/destination SID/command/bytes/FNV. No invented AP SID. |
| `token`, `total`, `offset` | Output: actual `fcam_exec_result` scalars. Input READ/RELEASE: actual argument token; known current lease total only for a matching tracked token; READ offset from actual argument, RELEASE extent from the current actual cursor. Other inputs use zero. Invalid tokens/cursors may still be retained for a real negative C result. |
| `bytes`, `sha256`, `fnv1a64` | Exact chunk extent and hashes of the actual in-memory bytes. |
| `writeback_sha256`, `writeback_verified` | SHA from actual disk readback and true only after exact full readback comparison succeeds. This is a storage-stage observation, not capture acceptance. |
| `device`, `inode`, `mtime_ns`, `ctime_ns` | Actual stable file identity at verified writeback, to reject changed evidence. |

For every retained result, concatenate the creating output chunk and subsequent
READ_RESULT output chunks in actual sequence/cursor order, with the same
nonce/token/total. Parse READ arguments as little-endian `<QQII>`: token,
current offset, capacity, reserved0 (24 bytes). Check capacity against the actual
mailbox capacity and output length. Parse RELEASE arguments as `<QQ>`: token,
whole-result FNV (16 bytes), with every byte already transferred. Recompute the
whole FNV and SHA from actual concatenated bytes, rather than composing opaque
chunk digests, then compare the FNV/extent with the matching `model_frame.proof`
result and the guest destination readback. `result_token` and `model_instance`
bind that receipt to the real job; `config_generation`/`frame_generation` bind
its rendered and consumed RGB content. JPEG full/scan-only and Packet96/config/AU
representations must be parsed as defined above before comparing encoded hashes.
Do not compare a wrapped packet hash directly to AVCC or MP4 bytes.

The additive `result_transfer` object in `core_result` and `response` records
`status` (`opened`, `chunk`, `released`, or `cancelled`), actual `token`/`total`,
`reconstructed_bytes`, `fnv1a64`, `sha256`, `chunk_count`, `first_sequence`, current
`sequence`, and boolean `complete`. It hashes the actual returned chunks in
memory. RELEASE succeeds only with the exact actual Release16 token/whole-FNV
and complete extent after a successful C release. CANCEL records the actual
transferred extent (possibly incomplete) and invalidates the token; cancelled
status never means release. `complete` describes byte coverage only. Fixed
state/AF replies and failed calls have no transfer object. Parent cleanup CANCEL
has no invented guest sequence or native origin and remains a cleanup event.

These producer records cover the first two rows of the
[exact missing-producer table](../functional-camera-evidence/README.md#exact-current-missing-producer-contract).
The parent-owned checker must implement and test its positive joins against the
frozen current run. Original JPEG SDK/lease transformations, Annex-B→AVCC/native
PI consumption and original event ownership/MPR/Fsys joins remain separate
requirements; these records do not clear their gaps or enable a capture flag.

## Component verification

OP9/OP10 当前定向结果为 **29 passed, 24 deselected (44.42s)**：新增8项和旧21项
一起运行，严格C11 `-Wall -Wextra -Werror -pedantic`、normal及ASan/UBSan，临时构建
目录仅在host `/tmp`。从本目录复现：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest \
  test_functional_core.py test_functional_startup.py -q -p no:cacheprovider \
  -k 'startup or vdf or zebra or layout or display or real_af_jpeg_scans_and_native_packet_metadata'
```

`test-functional-camera-startup.c` 在真实 owner 边界验证5→8→五种9→10及重复操作，
五bank/valid及旧功能bank互不污染；Config48保持，固定cache不占encoded-result。
独立Python从真实sink全部RGB重新计数，逐字节比较四段与全部192/1192B回执，再验证
small/gradient/flat已知像素和整数舍入。静态assert固定邮箱16页、State128、旧VDF
max192、新reply大小和proof kind值。production ctypes以两组Config48独立执行，
并在histogram后实际编码/读回/独立Pillow解码一张JPEG（仍非原AP成片证据）。

normal/sanitized分别覆盖五feature和hist的18种故障（各108个事务）：allocation、
configure/render、source前后改变、partial copy、sink、零/错lease、空consumer、
stale retire、staged前后改变、policy、committed readback、完整cache及其readback、
retire后sink改变。拒绝全部不足容量、短/长输入、cmd/bodylen/padding、非neutral、
无active/几何、alias/wrap、11项计数溢出、busy/live lease/fault、pending JPEG/video；
旧result/clip保留且不强cancel，失败不提交config/frame代际或bank/cache，实际阶段
计数保留。015f额外检查非零旧软件tag遇输入0仍保持，未赋予任何ISO单位。

失败过程同样保留：首轮8项setup error源于新测试未用的 `path_off` 被 `-Werror` 拒绝，
移除后为2 failed/6 passed (27.87s)，仅手写绿色Y bin把149误写为150；该轮独立算法、
完整golden与全部故障/ctypes均已通过。修正这个标量后合并定向运行得上述29项全通过。
未触碰VM/调试器/信号、main.so、原run/冻结批；transport nonce/origin、原AP业务、
notification/UI与最终成片验收属于parent，本轮未执行或提升其结论。

Run the older component matrix from this directory:

```bash
python3 -B -m pytest test_functional_core.py -q
```

The prior full component result was **31 passed**; the earlier OP7 subset was
**15 passed, 24 deselected** (11.00s). This OP8 implementation ran only the
scoped subset below: **21 passed, 24 deselected** (13.14s). It does not rerun
any parent batch or VM evidence.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest test_functional_core.py -q \
  -p no:cacheprovider \
  -k 'vdf or zebra or layout or display or real_af_jpeg_scans_and_native_packet_metadata'
```

Across both Python files the component now collects 53 tests; this OP9/OP10
run selected29 and left24 unexecuted. The earlier OP8 file alone collected45.
The scoped subset builds ordinary and
ASan/UBSan C scenarios plus the real production ctypes shared library under strict C11
`-Wall -Wextra -Werror -pedantic`; the shared library links with `-z defs`.
`test-functional-camera-vdf.c` uses test-only wrappers around real optical-owner
functions for invalid config, source changes before/during the consumer, partial
sink capacity, changed sink/config readback and an actual stale-token retirement
failure. The production translation unit has no fault-injection hooks. Python
independently compares source and sink byte-for-byte, checks non-flat RGB, FNV
and every byte of the 160-byte enabled/repeated/disabled responses. Both builds
exercise all capacities0..159, missing/invalid inputs, aliases/wrapped spans,
counter exhaustion, busy/pending JPEG/video ownership and unchanged error output.
A separate ctypes case exercises the unwrapped production VDF request path.

Zebra 的 normal/sanitized 专属场景为 `test-functional-camera-vdf.c` 的 `zebra`
参数，由 `test_zebra_real_rgb_sink_and_saved_config_readback` 执行。它验证实际 RGB
source/sink、完整168B回执、先于 INIT 的 canonical disabled route、重复 INIT、
path0/1 与 Zebra 混合、opaque 五字节逐值保存、尾读回、所有容量0..167、
enable1..255/reserved/short/alias 拒绝、inactive 不需要新帧 epoch、active 计数溢出、
pending JPEG/video 内容保留，以及真实 source/copy/sink/config/retire 失败后的不提交。
production ctypes 场景还使用两组完整 Config48（含不同尺寸/fps/质量/ISO/曝光/光圈/
无限远对焦），逐字节验证全部配置不变。OP7 专属 `layout` C 场景在 normal/sanitized
下验证精确32B保存、独立 RGB source/sink、完整192B golden 和128B State128、
0138→0153→014c→重复空 INIT、无 active route/disabled/错误 geometry、容量0/128/191、
错误长度及32个逐字节非canonical变体、alias/overflow/busy/pending 内容保留。
真实 optical primitive 拒绝零 generation 和错误 buffer 的 lease；另外验证不调用
consumer 的空返回不能提交，源前后变化、部分复制、sink/staged变化、真实 stale retire
均保留旧 layout/valid/config/frame generation 和原输出。失败时记录真实阶段计数，
并检查 CANCEL 必须等真实 owner idle。新增 production ctypes 场景用两组640×480
Config48，检查不同光学/fps参数保持、route改变后读回当前 route、重复 INIT 与错误
几何拒绝。所选旧媒体场景独立 Pillow/ffmpeg 解码2/4帧 H.264、JPEG/DQT/scan 和 AF；
未执行其余24项或任何 VM/整仓回归。

OP8 的 `display` C 场景在 normal/sanitized 下复用同一组真实 owner/fault wrappers，
验证两个独立 staged/committed16、全部176B golden、921,600B source/sink逐字节和独立
FNV、376B proof，以及默认配置从初始 cfg1 经 INIT→path5→Zebra6→layout7→8(peaking)
→8(flag) 后的 State128：同 instance、cfg6/frame6/rendered6/consumed5/retired6。
重复空 INIT 完全保留模型、状态和 proof。所有四个 palette、全部合法 level 和
magnification 值在128×64真实帧上消费；未知command/body size/padding/enable/on/
selector/color/level/magnification/palette、无active/disabled、短容量、alias、overflow、
busy/pending JPEG/video 均拒绝并保留旧内容。两项功能分别注入 config/source-before/
source-after/partial-copy/sink/staged/zero-or-wrong-lease/no-consumer/stale-retire 故障，
验证不提交配置/代次，阶段计数如实，并且真实 retire 完成前 CANCEL 不能成功。

新增 production ctypes 两组640×480配置运行相同混合链，并在其它功能之后重复读回
各自 tail16；Config48 和编码计数均保持。默认基线 cfg1 最后 cfg6；另一组显式
CONFIGURE 自身推进为 cfg2，所以最后是 cfg7，二者显示事务增量都为5，frame6/
rendered6/consumed5。另用1×1和127×63验证当前合法几何透传且不依赖 layout。
首轮仅 `-k display` 为 **2 failed, 4 passed, 39 deselected** (8.51s)：两个 Python
非平坦检查误设 `len(set(source))>10`，而默认曝光的真实 RGB 只有10种字节值；C所有
正常/故障场景及4项production ctypes已通过。随后仅修正测试为多种RGB像素且存在
彩色分量，source/sink全字节、FNV和回执标准保持，以上21项范围全部通过。

The existing matrix exercises the real INIT sensor probe without encoder consumption,
real AF; two JPEG table variants and scan reassembly;
quality1/50/100; an actual still beyond the video ceiling; 2/4-frame real H.264
streams and Packet96 metadata; independent Pillow/ffmpeg pipe decoding;
configuration/exposure/ISO/focus/aperture effects; chunks1/63/65024; preserved
error output; wrong/stale/cancelled tokens; partial/wrong-FNV release; empty EOS;
601 streaming frames; source lease/hash guards; and actual encoded consumption
followed by a forced sink bound fault. Media stays in memory/pipes.

The new `proof` C scenario runs in both ordinary/sanitized builds and checks the
read-only POD boundary, same real render/consumer active RGB, INIT no encoding,
frame/config/packet epochs, actual output hashes, unchanged old proof on
read/release/cancel, padded stride and a real failed tiny-destination JPEG.
The sink-bound fault scenario retains its actual failed H.264 consumer receipt.
Broker cases queue exact multi-chunk raw reconstruction and Release16 joins,
actual ctypes JPEG/H.264 proof, no false probe/EOS consumption, exclusive/link
refusals, corrupt/short readback, byte/file/count budgets and write failures.
All transport-only fixtures are HOST_TEST; actual-codec tests use the real model
and its real buffers. The parent's queued long-path and FD cleanup tests remain.

The core proof, lifecycle and media cases above have now executed successfully.
Broker cases and the original AP → CMOS → encoder → MPR/Fsys → virtual SD →
independent readback chain were not executed in this scoped change. No VM,
physical camera, private dump, full build or repository-wide regression was
used; `capture_verified` remains false.

## Evidence → implementation → remaining validation

| Evidence/source | Finding or producer change | Path and verification limit |
| --- | --- | --- |
| Exact first two missing-producer rows in the linked evidence README | Raw transfer bytes and actual same-frame consumer receipts were absent. | New `PayloadRecords`/`model_frame` and `fcam_model_proof_snapshot`; parent checker joins still required. |
| Actual pipeline `jpeg_acquire`, `jpeg_write`, `borrowed_consume`, `run_frame` | Instrument the exact source pointer and consumer return while the real lease is held. | Existing `camera-pipeline.c` receipt exercised by the core-only normal/sanitized JPEG cases. |
| Actual core `sensor_probe`, `consume_frame`, `packet_sink`, `still_frame` and original request dispatch | Separate probe/frame/drain content and output receipts; retain errors and real counters. | Core-only normal/sanitized and real ctypes scenarios passed; original AP/MPR/Fsys acceptance unverified. |
| Functional-profile single-endpoint VDF transaction | Actual independent RGB copy/readback/retire gates config commit and completion; disable has no frame. | `vdf_copy`/`vdf_frame`/`vdf_transaction`; source/sink/160B/reject/fault cases passed, guest/broker integration remains separate. |
| 原AP0153 `0d2053010e0001800300204b4100` 与CP五字节保存语义 | 独立 Zebra 配置，enable0 明确透传；保持全部 Config48 和 route16。 | `vdf_transaction` OP6 → 实际 active RGB sink/readback/retire → commit；静态来源只支持 Zebra 身份/保存，不证明原 gate 或阈值单位。 |
| 实际 normal/sanitized source/sink、168B逐字节比较及 production ctypes 配置读回 | active 必须消费，inactive 仅配置完成；错误/partial/retire失败不提交。 | 专属11项通过；原AP1153/guest/broker/VM集成由主会话继续验证。 |
| 原AP014c case0 body32、CP `1cd908` 的0305转发和1305→114c `00590000` 完成合同 | 独立 staged32/committed32/valid；明确 x/y/w/h 和零out软件 policy；只接受已提交active640×480 route。 | OP7 → 实际 RGB copy/full-byte+FNV readback/retire → layout32独立读回 → config/frame generation提交；原物理0305/1305及 metadata→FIFO 入口仍未验证。 |
| normal/sanitized 完整192B golden、实际921,600B RGB、State128与production ctypes两组配置 | 失败不提交 layout/config/frame generation；实际render/copy/retire观察保留；duplicateINIT不重置。 | 本批15项通过，24项未运行；原AP014c receive/free、broker/guest/VM与成片链由主会话继续验证。 |
| 两项原0152/0162独立AP producer、CP0202/0325与1152/1162合同（上述研究RESULT） | 仅disabled peaking和匿名flag off；各自完整typed16保存，不推测物理单位或空间算子。 | OP8 `display_validate` → 原VDF真实RGB事务 → 各自committed16读回 → config/frame提交；原独立1152/1162与AP身份由guestmain集成。 |
| normal/sanitized Display176全字节golden、实际RGB/State128、production ctypes两组Config48和非640几何 | 功能保存区互不污染，失败保留配置/代次、实际阶段计数；默认混合链cfg6/frame6/rendered6/consumed5。 | 本批21项通过、24项未运行；AP消费、broker/guest/VM和最终拍摄链未在本组件验收。 |
| Actual broker bytes already returned by ctypes and verified mailbox copy/commit | Save exclusive binary chunks, disk-read them back and track exact token byte extent/FNV/SHA. | `functional_camera_broker.py`; AST passed, real-model/negative storage tests queued. |

## Changed files

This OP9/OP10 change touches `functional-camera-core.c/.h`,
`test-functional-camera-startup.c`, `test_functional_startup.py`, the existing
`test_functional_core.py` build fixture and this README. Shared
`functional-camera-abi.h` only gains op identifiers9/10;
`functional-bb-startup-abi.h` is new. Earlier changes and all other owners'
work are preserved. Broker, bridge, guest VDF/histogram, menu/observer,
profile/runner, JPEG/MPR actors, existing runs/batches and firmware are not edited
by this component change; no VM, debugger, signals or main.so build were used.
