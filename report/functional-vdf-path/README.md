# 功能 VDF path / Zebra / Layout / display / refresh / initial BB 的原 transport owner

当前另支持原015e的[显示位宽事务](../disp-bit-width/README.md)：OP12/input8/result168/class7，软件selector0表示RGB888八位分量，物理含义未知；完整RGB消费/读回/retire后原request free，再独立发送成功状态`00590000`的115e。原sender本轮receive/ticket/free完成后才记消费。本次公开host结果不构成新原AP/VM或capture验收，以下前轮记录保留当时范围。

本成果在 `virtual-functional-camera-v1` 的同一 VDF owner 中处理原 AP `200d/0138`、enable0 `0153`、精确 initial case0 `014c`、disabled `0152`、off `0162`、exact-bound `0141`，以及 initial/neutral `0111/0166/0167/015f/0128`。每条命令保留实际 OSAL source、完整原 wire/header/FNV、独立 ACK 和同 sender TID 的 receive/free ticket。新 C 组通过稳定 bridge API 取得并严格验证 class5/result192，再按原 owner 释放 request、分配各自零状态12B回复。**本轮新增验证仅为 HOST_TEST owner/OSAL fixture；真实 core、native AP/VM 和拍摄链由主会话另接。本轮不把构造的模型回执当作实际 CMOS/RGB 执行证据。** `capture_verified=false`、`physical_asic_verified=false`；原 C 工作、0111 deferred 路径和 CP RTOS 独立未验证。后文真实 core/guest 组合结果保留为前轮历史证据。

前轮五命令实现仅修改 `runtime/analysis/device-models/{functional-vdf-path.c,functional-vdf-path.h,test-functional-vdf-path.c}`、`runtime/analysis/test_functional_vdf_path.py`、本文和 `source-pins.json`，共6个 owned 文件。未修改组合测试、menu-observe、bridge/broker、profile、共享 ABI、core 或构建脚本；未启动 VM、调试器、mainso/fullreg/fullbuild，未接触保留的 old VM、真实设备或原件。继承原 C 合同的项目根路径为 `analysis/scratch/functional-cp-vdf-startup-inventory/AFTER-BB-RESULT.md` §1/3，范围见同目录 `scope.md`；已有源窗只复用元数据，没有重新提取或反编译。本文按 docs-generator 的普通技术报告结构维护，`flavor=null`。

## BB0166 observed initial：本次精确策略修正

`run-pgf891an` 的原saved console stack在`0x7f34e6df78`保存header
`800100240166200d`；其后body28为
`00010000000000000000000008000000070000000100000001000000`。
完整36B为`0d2066012400018000010000000000000000000008000000070000000100000001000000`。
`df98`低u32结束原包；高4B `df9c..df9f=7f000000`属于包外栈内容。
原builder216B `034ebb84..034ebc5c`的原字节SHA256为
`8ff3613629f6eed955e79ef7c4af567a8d9fb8385931c6874f9d22cfcade9116`，本次只重读
该public窗口并复用完整已保存assembly/decompile：u8 body0/1、零u16 body2..3、六个
LEu32 body4/8/12/16/20/24原样存P1..P6，观察为`0,0,8,7,1,1`。
原send宽36、header起点与调用034e552c均相合。父独立原register-FP/ELF BL证明的
appFw base=`0x7f46b2b000`；来源见 [source-pins.json](source-pins.json) 的
`bb_0166_observed_initial`。request pointer `0x7f9b139840`只在另一saved栈槽出现，
未live读包，不称其为原packet-memory核验。

初期把0166猜成仅neutral输入，使这轮原builder无法通过；保留原批次FAILED和
shared-send assert结果（非已证allocation失败）。本次用户批准仅给旧explicit neutral和
这一完整初始tuple选择软件RGB identity；core、guest共用header中的
`fcam_bb_0166_body_valid`，实际sink校验完整u32 token。完整canonical32保存/读回、
input/result FNV、192B class5/kind5、真实RGB copy/retire、独立status0 1166与原free
合同保持。8/7/1/1无Sony参数名称或单位/系数推断，其它四命令范围保持。

本次owner增加205个`bb0166-initial-*`场景，与旧neutral场景并存；strict及ASan/UBSan
各2147个，共4294个独立进程，通过`4 passed, 1 deselected in 10.04s`。
覆盖default-off/handle/type/destination/header/长度、source81cf域、每个body字节、全部
192B关键字段/tail32、独立ACK/fresh lease/ticket/free/inline与故障保留。fixture的
完整日志FNV与snapshot逐条比较；这是owner fixture事实。真实core的RGB与完整192B
逐字节oracle由 [core报告](../functional-camera-core/README.md)独立记录，
本次未改父拥有的integration C/Python，也未执行新literal的core→guest组合。

**E-166-stack**=上述saved stack和原builder pin；**E-166-owner**=当前定向pytest、
C/Python fixture；**F-166-owner**（n/a_re，owner_tested，high，
evidence_ids=[E-166-stack,E-166-owner]）只确认两个精确identity token及生命周期。
**P-166-owner**：原metadata/header/body→shared校验→原op9完整192B验证→原request
free→独立1166→同D/TID receive/free。原AP/VM、物理work/units和capture未验。
时间线：先读saved stack/完整原builder→核字段span和36B边界→shared root修正→
strict/SAN与broker/profile/evidence定向验证；旧失败原件保持。

## C 组：同一 owner 的五项 initial/neutral 软件配置

稳定生产依赖为 `fcam_bridge_bb_startup_config(const struct fcam_native_origin *, const unsigned char[32], unsigned char[192], struct fcam_bridge_result *)`，由主会话的 bridge 提供。本 owner 的非 HOST_TEST 对象保留该未定义外部符号及 `fcam_bridge_call`，没有生产替身或第二 owner。共享定义来自 [functional-bb-startup-abi.h](../../runtime/analysis/functional-bb-startup-abi.h)：op9、input32、result192、class5/proof kind5。当前 owner 同时声明该稳定外部依赖，允许 parent 的 bridge header/实现独立落地。

canonical32 采用 `LEu16 command + LEu16 原body长度 + 全部原body + virtual zeros补足32`。snapshot 新增 `canonical_bb32[32]`，每条日志增加同名64hex；原 wire 与完整 wire FNV 不变。CONFIG16 始终表示当前 VDF route；INPUT_FNV 只覆盖 canonical32，不能使用原 body、完整 wire 或 route16。新36B命令按 opcode 归入 BB 类，不能按同样的 result192 或大包长度误认为 Layout；014c 仍是唯一 layout/stage-bind 命令。MAX_REQUEST40 与 MAX_VDF_RESULT192 保持不变。

| 原命令 / 请求字节 | 允许的原 body | 软件应用范围 | 独立12B成功回复 |
|---|---|---|---|
| 0111 /36，body28 | exact `00 00 0f 02` +24零 | SQ idle/off；sqMode、frameRate、aux 均0，无软件 deferred work | `0d2011110c00018000000000` |
| 0166 /36，body28 | `00 01` +26零，或上述精确observed initial body28 | 两个软件RGB identity token；六个opaque word完整保留，不赋物理地址、Sony枚举或单位 | `0d2066110c00018000000000` |
| 0167 /10，body2 | LEu16 0 或1 | 两个 opaque RGB identity 域，不命名 Sony gamut/matrix | `0d2067110c00018000000000` |
| 015f /12，body4 | LEu32 0 | software gain-tag 初始0；0保持旧值，不清零、不写 Configure48/ISO | `0d205f110c00018000000000` |
| 0128 /20，body12 | `00 01 00 00`，LEu32 period∈{60,50,40,30,20,10,9,8,7,6,5,4,3,2,1}，末4零 | scheduler disabled；period opaque，无计时事件或拍照 | `0d2028110c00018000000000` |

五个 status 全为0，**不 OR `00590000`**；015f 使用原专用 AP parser `034e4500`。原 CP live config→snapshot→work 的存储偏移/读取宽度见继承 §3，精确源字段摘要与原 producer、work、独立回复窗口均追加在 `source-pins.json` 的 `bb_startup_*`；源中未消费的 padding 只保留原字节，不据此命名物理语义。

所有五条命令继续要求实际 metadata source 高16位 `81cf`。绑定到 `80946189` 的0141例外只授权0141，不能供旧五命令或新五命令借用。新命令在桥调用前要求本 owner 已完成且消费完的 active route，并复用 all13/resource guard；**不要求 CP3003/mode1 已完成，C/D 可并行**。core 另须拒绝 active clip、pending job/result、非640×480 route 或非 idle frame owner。

core 的生产完成合同是：当前 active RGB render → 独立 sink copy/readback → retire → 在五个独立 canonical32 feature bank中保存并读回本命令配置 → 提交 config/frame generation 各+1。该顺序及真实数据由 core 负责执行；owner 接收并检查完整192B回执，包括严格 used/required、ABI/bytes/instance、class5、route CONFIG16、当前 typed tail32、canonical32 FNV、真实 RGB source/sink 非零相等、640×480×3=921600B、stride1920、lease 单调且已退休、before generation 不回退、frame/config=before+1，以及 status/reserved0。仅复制 body 的回执缺这些字段会拒绝。

原 request 的 size/source/完整字节与 guard 在模型返回后再次读回，全部通过后才设置 `request_owned`。随后固定执行 real request free→独立 ACK allocate/write/source/readback→原 D send→原 sender receive/ticket/free。allocate 返回0且实际新12B对象复用已退休 request 的同址合法；015f 的 request 本身也是12B，仍按两段不同生存期验证。live request/state/所有 ACK 常量别名、错误 shape、非空失败分配、inline AP free、sticky send/free错误、退休地址不永久认领、PID fork-before-lock 与 onepending 规则保留。模型/配置/依赖/guard 拒绝不接管、不 free 原 request、不分配或发送 ACK。

### 前轮五命令验证与主会话接续（历史）

在成果目录执行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider \
  runtime/analysis/test_functional_vdf_path.py -k 'not pinned_public' -q
```

实际结果：`4 passed, 1 deselected in 9.23s`。strict C11 `-Wall -Wextra -Werror -pedantic` 与 ASAN/UBSAN（含泄漏检查）分别运行1942个场景，合计3884个独立进程；保留原900，新增1041个 BB 场景和1个 legacy0141重复周期。fixture沿用既有模型回执构造、真实独立宿主 OSAL allocation 和 controlled fresh-lease arena；**五银行保存是 fixture 的输入/尾部隔离检查，不能证明真实 core 已执行相同工作**。生产符号检查确认两个 bridge 依赖为外部符号，没有 bridge init 或 HOST_TEST 导出。另有文档包字节/共享合同自检，不重读原件源窗。

覆盖五种 neutral 成功、gamut0/1、15个 period、每个原 body 字节非法、短/长包/header/source域/无active/缺依赖/guard错误，192B逐字段及全部尾32篡改、所有未用canonical尾字节、20个跨银行借用组合、错误 class/FNV/sink hash/generation/retire。共享生命周期覆盖同址新lease、inline free/send失败、旧/空ticket、foreign TID、free失败保留和跨opcode pending拒绝；两个 exact-bound0141来源 `81cf0012`、`80946189` 均执行两次原格式1141 receive/free。首次 strict 尝试暴露 fixture 原篡改偏移13不适用于新12B请求；已改成依据实际长度取末字节，随后 strict/SAN 全部通过。此为测试构造修正，不是新增运行时完成证据。

主会话负责将新五 opcode 纳入生产 lazybridge/all13入口，并在 `functional-camera-bridge.h/.c` 提供稳定 API 的声明/实现。已有 `test-functional-vdf-integration.c` 只定义旧 `fcam_bridge_call`，需主会话接续真实 core 对 op9 的转接后再执行组合测试；本轮没有给该测试添加假成功 stub，也没有执行该组合。原 `source-pins.json` 681/900场景与 core99场景等历史记录保持不变，新验证单独记在 `bb_startup_owner_validation`。

E-C10（file，继承源证据）：`AFTER-BB-RESULT.md` §1/3、`after-bb-source-pins.json` 与 verification；内容 SHA-256 和19个原AP producer/parser、CP config/work/reply窗口元数据（5596B含重叠）已入新 ledger。F-C10（category=`reverse_algo`、severity=`n/a_re`、status=`source_confirmed`、confidence=`high`，evidence_ids=[E-C10]）：五命令是独立 local kind1 结果及零状态回复；原0111延期和物理下游仍未知。E-C11（command/file）：上面的专属 pytest、C/Python fixture及生产对象符号。F-C11（status=`owner_tested`、confidence=`high`，evidence_ids=[E-C10,E-C11]）：有限 canonical32 与完整回执拒绝、原 D 生命周期和五类隔离通过，验证范围限 owner。P-C11（path_type=`callflow`）：实际原 metadata/wire（E-C10/F-C10）→neutral/all13/active gate→稳定 op9 与完整192B检查（E-C11/F-C11）→原request退休→对应零状态 ACK→同D/TID真实 receive/free（E-C11/F-C11）。原物理 work/deferred/CP RTOS/capture 是该路径的独立未验边。

时间线：读取项目约定和既有 §1/3 → 在同一 owner 有限扩展五命令 → 复用 fixture 批量覆盖 → 修正12B测试偏移 → strict/SAN与符号验证 → 追加继承 pins 和本报告。完整新 core/native 组合结果由主会话另留证据。

## 0141 的 exact global queue 绑定增量（前轮历史）

主会话已交付的根因：0141使用原AP全局队列，原set/get source仅复制4B，动态owner来自运行表；它不保证与五个per-call命令同属`81cf`。本轮原global实际值为`0x80946189`，**不是固件固定队列ID**。本owner不重做源调查、不读取native现场；主接线负责在已验证原appFw调用点`0x034e4f3c`下，对原global`0x0910fa30`做两次独立4B只读读取，要求二者相等、非0且等于真实`get_source(request)`，之后才调用新增API。API参数本身不构成native来源证据，禁止从wire body挑选ID或任意放宽caller白名单。

`functional_vdf_path_bind_refresh_queue(unsigned int source)` 必须在`owner_init`之后调用，仅写snapshot的`refresh_queue_bound`和`refresh_queue_source`，不调用bridge、不建立lease、不修改模型、AP消费、frame或generation。PID检查在mutex之前；`0`、`UINT_MAX`、本SID返回`-EINVAL`，未初始化`-ENODEV`，fault `-EPROTO`，busy或已有未消费周期`-EBUSY`，继承PID `-EXDEV`。空闲same ID重复返回0，different ID返回`-ESTALE`且不覆写；无reset/rebind API。

只有0141允许`bound && actual io.source(request)==exact bound source`；caller0、未绑定（包括旧fixture的`81cf0012`）、同域或异域但不相等均拒绝，原wire/metadata/指针保持caller所有权。0138/0153/014c/0152/0162继续要求高16位`81cf`，即使它们的source等于绑定的`80946189`也拒绝。queue身份只证明native transport身份，不是硬件ready；原all13/resource guard、active route和完整176B回执条件不变。

0141仍使用原8B `0d20410108000180`，typed envelope16为`41010000000000000000000000000000`，op8/result176不改；独立12B `1141`为`0d2041110c00018000005900`。实际request free→新ACK lease→原source/D send→原sender TID receive/ticket/free的顺序不变。origin.source不归一化，不重写原请求metadata/D；绑定不认领退休地址。每条cycle record新增同名`refresh_queue_bound`、`refresh_queue_source`内容字段，fixture逐条解码并与snapshot核对。

复现命令沿用下节的两个专属pytest文件及`-k 'not pinned_public'`。本增量实际结果：`201 passed, 1 deselected in 29.27s`。

| 当前验证 | 每构建场景 | strict + ASAN/UBSAN |
|---|---:|---:|
| owner/OSAL | 900（原735保留，新增18个bind边界及147个refresh） | 1800 |
| 真实core + guest owner组件 | 99（含原early-stage/layout/display及cross-domain/legacy refresh） | 198 |
| 非HOST_TEST生产对象编译/符号 | 1 | 1 |

共1998次独立场景进程，201是pytest测试项数，不能混计。strict使用C11/`-Wall -Wextra -Werror -pedantic`，SAN启用ASAN/UBSAN及泄漏检查。两个refresh组合分别显式trusted bind `80946189`和`81cf0012`；各自先拒绝2个未绑定请求、再拒绝caller0及2个错误source，之后0138→两次0141均向同一global D返回独立1141并真实receive/free，得到`config=4 frame=4 rendered=4 consumed=3`、3次request/ACK实际free。绑定前后完整core State128/proof及owner除queue字段外逐字节相等，两个真实RGB回执source/sink FNV相等且非0、每帧921600B，反复INIT未提前消费ACK。18个bind边界另覆盖0/max/SID、初始化前、持锁fork、busy/已绑定busy、pending/fault、不可改绑、退休地址无ticket不认领及其余五命令跨域拒绝。147个refresh复用现有生命周期、完整176B逐字段/尾部、inline、错误free及controlled fresh-lease测试。

本增量未运行原件70窗pins测试，保留旧ledger及其681场景历史计数；没有将宿主组件结果升级为原AP/VM成功或完整拍摄。完整组之后只复用已生成的normal/SAN二进制各复核cross-domain与legacy refresh，共4次（不重构建），均RC=0；每次两帧各921600B，source/sink FNV同为`3019813b04b8d825`，typed input FNV为`1a8cb62342e6d89f`，3次request free和3次ACK free，原D/source未改变。E9为本增量C/Python fixture及上述实际命令；F9（`owner_tested/high`）为0141 exact绑定、五命令域隔离、完整模型回执与lease不变；P9（`callflow`）为trusted主接线来源校验→immutable queue bind→0141 exact source→op8完整回执→原D独立1141→实际receive/free。主接线的native读取及保留old VM的后续验证由main完成。

## 前轮生命周期修复验证（保留历史）

从本成果所属的 `2026-10-17-qemu-native-camera/` 目录执行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider \
  runtime/analysis/test_functional_vdf_path.py \
  runtime/analysis/test_functional_vdf_integration.py -k 'not pinned_public' -q
```

本轮受影响组件组仅完整执行一次，结果：`195 passed, 1 deselected in 26.98s`。

| 验证 | 每套构建实际场景数 | strict + ASAN/UBSAN合计 |
|---|---:|---:|
| owner/OSAL | 735（原681全部保留，新增54） | 1470 |
| 真实 core + guest owner | 96（原94全部保留，新增2个controlled arena组合） | 192 |
| 生产对象编译/符号 | 1，非HOST_TEST | 1 |

两个组件共1662次独立进程场景执行，195为pytest测试项数，不能混计。新增owner54场景为Layout/peaking/flag各13个fresh-request-lease成功/失败/混合/旧ticket分支，加五opcode各3个真实生产常量别名；strict C11使用`-Wall -Wextra -Werror -pedantic`，SAN为ASAN/UBSAN，均启用失败立即退出及泄漏检查。生产owner仍保留`fcam_bridge_call`外部依赖，没有`fcam_bridge_init`或HOST_TEST导出。完整组后只复跑已有normal/SAN二进制各3个场景读回计数，共6次，未再构建或重跑整个组。

本轮主动排除`test_pinned_public_vdf_source_ranges`；下述70窗与[source-pins.json](source-pins.json)的681场景数为原轮次继承记录，未将历史ledger改写成本轮证据。历史pins记录两个完整公开原件的大小与SHA-256、AP两个原ELF PT_LOAD与每个窗口VA→raw映射、20个继承区间、42个Layout窗口及8个display窗口，共70窗。8窗3028B、Layout42窗9934B均为已交付调查；本轮没有读取/复制原件、重survey、提取或反汇编。

测试覆盖：

- 旧 path 的 active/disable/repeat、24B opaque 原 wire、canonical16、逐字段160B拒绝、INIT身份、代际、transport错误、同址复用、foreign对象复用、持锁 fork、callback重入与 inline receive/free。
- 旧 Zebra 的14B、前5B opaque/尾padding、canonical8、active/inactive/cold-inactive、独立1153、全部尾8逐字节篡改、错误160B/FNV/route/代际/lease、0138/0153混合和相同生命周期错误。
- Layout 的40B exact case0与动态 D、active/无active拒绝、opaque当前route不变、全部32个body字节变更拒绝（含padding）、运行中padding篡改拒绝、全部尾32逐字节篡改、192B逐字段/身份/counters/FNV/readback/retire检查、错误160/168B尺寸拒绝、自洽但错误的宽/高/stride/activebytes拒绝。
- Layout 的 `0138 → 014c → 0138 disable → 0153 → 0138 active → 014c` 合法混合路径、同一个ACK地址跨opcode cycle复用、旧ticket与空ticket、独立114c拒收1138/1153、全部transport错误及free失败sticky状态、snapshot中新增192B结果尾部的allocator别名拒绝、完整日志内容与实际结果长度。

- 新增0152/0162的原16/10B、typed envelope16、完整176B逐字段/尾16逐字节拒绝、错误160/168/192B长度、原body/route错误FNV、其它display命令尾部、伪inactive回执、route opaque不变、四palette/三个level/三个magnification边界、enable1/未知字段/非零padding拒绝。
- 新增五opcode混合cycle和同ACK地址跨opcode复用；request real free失败时不分配/不发送ACK，实际ACK free失败后sticky；foreign TID、重入、inline free、snapshot display/result尾部别名、UINTPTR_MAX跨界分配均保留拒绝。

## 已退休 request 同址复用的根因与复核

原`allocate_ack(io,request)`无条件用`request/origin.bytes`做overlap，即使`release_owned`已真实free成功并清空`leases[0].pointer`。普通小块allocator可合法把刚退休的10/16B request槽返回为新的12B ACK；原逻辑将新lease判为alias并sticky，原wire保存与ACK尺寸均无助于跨过该错误判断。组合fixture曾二次`message()`避让该地址；owner fixture曾多分配64B改变size class，这两处遮蔽已移除。

先移除组合避让、将正常消息改为准确尺寸的`malloc + memset`，保持生产修复前代码构建。strict构建`RC=0`，`display-mixed`退出`RC=-6`。以下为首次失败的相关原始输出（仅相机项目工作目录前缀改为相对路径，省略libx264初始化banner）：

```text
PRE_FIX_BUILD_RC=0
PRE_FIX_CASE=display-mixed RC=-6
retired-request alias: command=0152 allocate_rc=0 request_freed=1 request_null=1 same_address=1 ack_size=12 request_frees=4 allocations=4 sends=3
vdf-integration: runtime/analysis/device-models/test-functional-vdf-integration.c:346: cycle: Assertion `!rc && !s.faults && s.model_complete && s.request_owned' failed.
```

修复只将request重叠范围取自当前`state.leases[0].pointer/bytes`；该pointer非NULL才有live/retained lease。保留Layout/display实际原request free成功→pointerNULL→新ACK allocation的顺序，保留path/Zebra allocate-before-free时的live alias拒绝。state（含route/config、original wire与result）、各opcode ACK常量、layout常量、palette常量和span溢出保护不变。新ACK仍须真实allocate成功、actual size严格12、写入独立ACK/source后再次用真实size/source/wire读取验证；任何失败保留新lease并sticky，不能因旧地址再free原request或误丢新ACK。

测试中的retired `alloc-alias`/`alloc-alias-interior`不再声称旧地址仍live：controlled arena保存未新分配的旧descriptor，size accessor对interior显式返回旧尺寸，避免伪造未对齐OSAL header。原40/16/10B尺寸均非12，必须shape拒绝，`allocation_alias=0`，不send、不再free旧request；live path/Zebra同两例仍`allocation_alias=1`，不写/不free活对象。正常fresh arena会先退休原lease，再创建有真实12B size/source的新descriptor；arena的live标记及allocate/free计数检查两生存期不重叠。

复核使用完整组已生成二进制，无重建，每行`RC=0`：

| 构建/场景 | ACK allocate / 原request实际free / ACK实际free | request→新ACK同址次数 | arena allocate/free |
|---|---|---:|---|
| normal `display-mixed` | 5 / 5 / 5 | 2（普通malloc自然复用） | 0 / 0 |
| SAN `display-mixed` | 5 / 5 / 5 | 0（SAN未自然复用） | 0 / 0 |
| normal及SAN各自`display-fresh-request-lease` | 5 / 5 / 5 | 3（Layout、peaking、flag） | 6 / 6 |
| normal及SAN各自`layout-fresh-request-lease` | 3 / 3 / 3 | 1 | 2 / 2 |

两套display组合均得到`config=6 frame=6 rendered=6 consumed=5 retired=6 proof_serial=6 requests=5 completed_cycles=5`；Layout组合得到`config=4 frame=4 rendered=4 consumed=3 retired=4 requests=3 completed_cycles=3`。真实core提供结果160/168/192/176、RGB copy/FNV/readback/retire及proof；HOST_TEST只替代bridge transport和OSAL。原D、sender/receiver/free同TID、独立receive ticket、跨opcode旧ticket拒绝、inline receive/free、free失败保留、private guard、原wire/FNV及source getter均保留，未产生host媒体文件。

## Parent 集成合同（原六命令，C组增量见开头）

实现文件：

- [functional-vdf-path.h](../../runtime/analysis/device-models/functional-vdf-path.h)：稳定 API、旧请求尺寸常量、新40B上限与 snapshot。
- [functional-vdf-path.c](../../runtime/analysis/device-models/functional-vdf-path.c)：生产 owner。
- [test-functional-vdf-path.c](../../runtime/analysis/device-models/test-functional-vdf-path.c)：HOST_TEST bridge 与真实独立宿主 OSAL header/分配。
- [test_functional_vdf_path.py](../../runtime/analysis/test_functional_vdf_path.py)：专属构建、场景执行、source pins及生产符号检查入口。

Parent 显式调用 `functional_vdf_path_owner_init()` 一次；重复调用返回 `-EALREADY`，没有reset/import API。Parent统一lazy初始化 bridge，本 owner 不调用 bridge init，没有新增模型RPC初始化路径：保留首次真实请求的一次 INIT/State128/model instance验证，后续五个opcode共用同一实例。识别实际0138/0153/014c/0152/0162并通过 all13 consumer/resource guard 后方可 dispatch；不要求 CP3003 start 或 mode1。`guard.reserve/release/predecessor_ready` 与所有 io、bridge、record callback 均在 private mutex 外执行。

`enabled==1`、destination `92840747`才进入该profile。0138/0153/014c/0152/0162的actual `io.source(request)`仍须高16位`81cf`；0141必须已绑定且等于exact global queue source，见上节trusted caller合同。D取自OSAL metadata accessor，不能把014c body.src或header内字节当作caller。其它opcode/type/destination/profile关闭返回handled0；匹配opcode但长度/header/source/配置/依赖非法返回handled1/result<0，不分配ACK。

| 操作 | 原请求 | 模型输入/结果 | 独立成功回复 |
|---|---|---|---|
| 0138 path | 24B，header `0d20380118000180` | op5，canonical route16 /160B | `0d2038110c00018000005900` |
| 0153 Zebra | 14B，header `0d2053010e000180` | op6，canonical Zebra8 /168B | `0d2053110c00018000000000` |
| 014c Layout | 40B，header `0d204c0128000180` | op7，exact layout32 /192B | `0d204c110c00018000005900` |
| 0152 peaking | 16B，header `0d20520110000180` | op8，typed display16 /176B，disabled only | `0d2052110c00018000005900` |
| 0162 unnamed flag | 10B，header `0d2062010a000180` | op8，typed display16 /176B，off only | `0d2062110c00018000005900` |
| 0141 refresh | 8B，header `0d20410108000180`，exact-bound source | op8，typed display16 /176B，active route | `0d2041110c00018000005900` |

旧 `FUNCTIONAL_VDF_PATH_REQUEST_BYTES=24` 与 `FUNCTIONAL_VDF_ZEBRA_REQUEST_BYTES=14` 保留。新 `FUNCTIONAL_VDF_LAYOUT_REQUEST_BYTES=40`、`FUNCTIONAL_VDF_MAX_REQUEST_BYTES=40` 仅扩展保存/检查容量；旧fixture仍分配24B，不会因上限增长而误跑Layout。snapshot.original_wire、内部saved/release缓冲与raw日志支持40B；model_result使用共享 `FCAM_VDF_RESULT_MAX_BYTES=192`，state整体别名检查随snapshot尺寸扩展。

`FUNCTIONAL_VDF_PEAKING_REQUEST_BYTES=16` 和 `FUNCTIONAL_VDF_FLAG_REQUEST_BYTES=10` 为独立常量，旧24/14/40及MAX40不变。snapshot增加 `canonical_display16[16]`，model_result仍为MAX192，没有缩小Layout容量。

0138仍只支持path1/pins5,5或path0/pins1,1、body[4]<=2。body[3]、[5..12]保持opaque，canonical16仅将末13..15置0。0153只实现enable body[1]==0，前五字节保存并补三零；原body[5]任意值只保留在完整wire/FNV。初始canonical route为软件core明确规定的path0/pins1,1，其余零；Zebra和Layout都保持当前route16。Config48曝光、fps、编码参数不由本接口改变。

### 014c 软件policy与精确边界

原40B wire：

```text
0d204c012800018007010100000000008002e0010000000000000000000000000300000000000000
```

独立canonical_layout32：

```text
07010100000000008002e0010000000000000000000000000300000000000000
```

只接受此initial case0：sel7/layout1/src1、in四个LE u16为0,0,640,480、out全零、aspect/type/padding0、timing3/id0。全部32字节逐字节固定，不把源consumer忽略的padding当可随意变化的输入。`in=(x,y,width,height)` 与 zero-out=full-frame passthrough 是用户授权的软件policy；原Sony area分量顺序和src/type/timing枚举物理意义仍未知。

Layout必须已有active当前route；没有active route在模型RPC前返回拒绝，原请求仍由caller持有。模型还必须对自己的实际当前route、640×480 geometry和layout32保存/独立readback/实际RGB消费/retire执行验证；本 owner检查全部192B回执，并再次检查原请求实际40B、metadata source、长度和guard未变。任何模型错误、短160/168B回执、错误geometry、篡改padding或尾32都会拒绝，不free原请求、不分配或发送成功ACK。HOST_TEST只构造回执，不证明真实RGB执行。

### 0152 / 0162 的 typed display 合同

两者分别保存原wire和原source。共享op8的input16为 `LEu32 native_command + LEu32 original_body_bytes + body8`；0152为`52010000 08000000`加全部body8，0162为`62010000 02000000`加原body2及六个virtual zeros。不能只发body8、把原flags或动态D塞入envelope，也不能将两个命令混为一个配置。

| 0152 body offset | 字段 | 支持值 |
|---|---|---|
| 0 | selector | 3；只继承原constant3→3转换，不推任意selector |
| 1 | enable | 0；enable1的实际算子未知，拒绝 |
| 2 | level | 0、1、2 |
| 3 | magnification | 0、10、40；物理单位未知 |
| 4 | color_type | 0 |
| 5..7 | y/cb/cr | (81,90,240)、(210,16,146)、(29,255,83)、(235,128,128) |

0162只接受原body `00 00`；body1非零也拒绝，匿名feature不命名。六个canonical尾零为软件envelope填充，不是原10B上隐含的额外字段。二者都必须已有本owner成功提交且消费完成的active VDF route；cold/inactive在桥调用前拒绝。core须分别保存/readback两个命令的配置，并实际consume→RGB copy/FNV→readback→retire；本owner的mock验证不替代该组合工作。

176B的base160沿用当前route CONFIG16，INPUT_FNV严格覆盖typed envelope16，offset160的tail16必须等于从当前原16/10B重新导出的canonical_display16。实例、used/required、token、status/reserved、全部base字段、source==sink非零、activebytes/stride、config/frame/lease代际、readback/commit/consume/retire和原请求逐字节/metadata/guard检查全部通过后才接管。route保持不变；不写Configure48，不从本地保存或空ACK产生完成。

原source合同复用已交付的整段研究：0152为eventa3→0202→1202/kind1 event29c→1c5026→独立69c9ea/1152；0162为eventab→0325→1325/kind1 event29f→1c504c→独立69cb32/1162。两者成功status均00590000，独立12B回复source92840747→actual D。原source FIFO的实际ingress与物理工作/completion生成仍未证明。

同run jfz 的 `pid258/tid381/src81cf61c5` 已实际发出 `0d205201100001800300010000eb8080` 是parent提供的继承观察，本成果没有重跑。AP63-call清单及CP八命令批量合同已在项目根 `analysis/scratch/functional-{ap-startup-frontier,cp-vdf-startup-inventory}/RESULT.md`；第一组A在014c后有0153、0152、三个ret stub、0162及条件014e，不能再把014c称为唯一阻塞。本次仅实现0152+0162，不扩展其它候选或发送oneway014e的回复。

### 所有权、顺序与消费

模型验证前的负结果保留caller对原请求的所有权。模型结果和原请求/guard全部验证通过后设置 `request_owned=1`；此后handled1/result0表示接管，不能据此推断AP消费。sticky faults与实际retained leases记录后续错误，不回滚成冷态。

014c、0152、0162顺序固定为：

1. 验证完整192B（Layout）或176B（display）内容、实例、代际、route/config、exact canonical、FNV和实际消费/退休判据。
2. 原destination `92840747` 下调用原request的real free；失败保留request并停止，不分配任何成功回复。
3. 独立分配该opcode的12B回复（114c/1152/1162），写入表中原字节，设source `92840747`，逐字节及metadata读回。失败不send；若allocator异常返回非空独立对象，保留真实lease。
4. 只向不可变origin中保存的实际D发送。send返回后仅访问lease元数据，允许callback已inline receive/free实际释放回复。
5. 原D实际receive成功后调用 `functional_vdf_path_observe_receive_cycle(dest,p,src,size,&ticket)`，只接受原sender TID的当前ACK，写入不可变cycle到receiver TLS。
6. 同TID实际free调用 `functional_vdf_path_release_cycle(dest,p,ticket,real_free,record,result)`。成功后parent退休TLS ticket；禁止free时从snapshot重新取得新cycle。

旧0138/0153保留原先“独立分配/读回ACK → 原request free → send”的顺序及失败保留合同。两种顺序都只在完整模型结果校验后开始；没有generic ACK、假两阶段成功或其它opcode扩展。

allocator只把**仍live/retained的request lease**与ACK的重叠判为alias：`leases[0].pointer!=NULL`时使用该lease的范围；原request实际free成功并置NULL后，其历史地址不再代表活区。该地址被真实allocate成功返回为新12B ACK时按新lease完整验证/保留/消费。immutable origin/cycle和原wire保持不变，`release_owned`不会再匹配到已清空的原request。普通malloc无需额外容量或二次分配避让；controlled arena另对SAN强制复用。

只有send成功、原receive、同sender TID的real free成功、原request已free、guard释放且dispatch退出后，才有 `ap_consumed=1`、completed_cycles递增并允许下一操作。inline receive/free期间仍有send_inflight和busy，不提前完成。busy与未消费ACK阻止另一个opcode抢入同一通道。

`allocation_returned`记录allocator原始返回值；`allocation_alias=1`时它不是可独立free的对象，真实保留所有权见leases。allocator返回仍live request/state（包括192B结果末字节）/各ACK常量/layout常量/palette常量的重叠范围被拒绝。已退休地址上的旧尺寸伪分配按shape拒绝，非空返回保留于ACK诊断lease；它不会触发第二次原request free。异常非空分配失败保留，不擅自释放。original-free失败、ACK-free失败与send失败都是sticky，清理重试成功不抹除失败历史。

对owned ACK，空/旧ticket返回 `-ESTALE`且不real free，不污染当前合法cycle。receive/free的目的、线程、metadata、字节等协议错误为sticky fault。retired ACK地址随后可被无关OSAL对象复用：unmatched receive和无ticket的unmatched free返回0，显式非零旧ticket命中最近退休地址仍返回 `-ESTALE`。同址跨opcode的新ACK也必须使用该cycle实际receive取得的ticket。PID在任何继承mutex之前检查，fork child返回 `-EXDEV`；旧持锁fork测试保留。

## 完整160/168/176/192B回执的内容判据

复用 [functional-vdf-path-abi.h](../../runtime/analysis/functional-vdf-path-abi.h)，本成果没有另定义wire struct或修改共享ABI。

| 条件 | 校验 |
|---|---|
| 所有结果 | used/required严格等于本opcode的160/168/176/192，token0；ABI/bytes；payload与bridge metadata实例均等于INIT实例；status/reserved0；缓冲canary完整 |
| 当前配置 | CONFIG为current canonical route16，readback=commit=1；config generation=before+1且before不回退；endpoint90590819，selected/completed mask均1，class/enabled等于route active |
| op5输入 | INPUT_FNV(route16)，从原24B重新导出canonical并比对，末3B置零 |
| op6输入 | INPUT_FNV(Zebra8)，尾8逐字节等于单独保存/读回配置，route16不变 |
| op7输入 | INPUT_FNV(layout32)，从原40B重新比对exact case0；尾32从offset160逐字节等于canonical_layout32，route16不变 |
| op8输入 | INPUT_FNV(typed display16)，tail16从offset160逐字节比对原请求重新导出的命令/bodybytes/body；active当前route16不变，canonical额外6零只用于0162 |
| active | RGB stride=width×3，activebytes=width×height×3；source/sink FNV非零且相等；consumed=retired=1；frame=before+1；lease generation非0且不能重用最近active lease |
| op7 geometry | 必须active、width640、height480、stride1920、activebytes921600；不能用其它自洽尺寸代替 |
| inactive仅op5/op6 | source/sink FNV、activebytes、lease、consumed/retired均0，frame不增长；仅配置元数据，不虚构帧 |
| 共享代际 | before config/frame不得低于本owner最近回执；允许其它共享model操作推进generation，不假定独占model生命周期 |

输入另与保存的原wire比较，bridge非法改写输入会被拒绝。每cycle清空结果，model_result_bytes取本次实际used并裁至capacity，超长声明仍验证失败；旧160B结果不会补零冒充176/192B。nonce和跨进程transport属于生产bridge，本owner继续限定INIT与每次回执实例。

## 日志与因果join

所有日志使用 `FUNCTIONAL_VDF_PATH_*`。单条text缓冲3000B，继续适配parent的4096B记录器。每条保留cycle、actual source/D、origin FNV、model instance、config/frame/lease代际、完成阶段、TID、retained pointers及分配/send/free错误。

| 字段 | 内容 |
|---|---|
| raw | 按origin.bytes输出完整10/14/16/24/40B，含原padding |
| ack_wire | 该cycle独立1138/1153/114c/1152/1162完整12B；1153零status不归一化，其余四者成功00590000 |
| canonical_config | current route16B；0153/014c/0152/0162保持原route |
| canonical_zebra8 | 独立Zebra8 |
| canonical_layout32 | 独立Layout32完整64hex |
| canonical_display16 | 当前display cycle的命令/bodybytes/body，合计16B/32hex；其它opcode保留最近display配置 |
| model_result_bytes / realresultbytes | 本cycle实际可用回执字节数；合法Layout明确为192 |
| model_result_hex | 实际160/168/176/192B对应320/336/352/384hex；短回执按真实长度输出 |
| model_result_fnv1a64 | 独立对上述实际字节数计算FNV1a64 |

fixture逐条解码日志并与snapshot数组/实际长度/独立FNV比较，确认未截断。checker应连接同cycle的raw→对应canonical→完整回执→独立ACK→实际receive/ticket/free，不能把model_complete、queued、received、ap_consumed合并为一个事实。

## Evidence → Finding → Path

证据摘要及原文件哈希见 [source-pins.json](source-pins.json)。E1–E5为既有公开source ledger，E7为最终014c源调查；本次没有重新反编译。

| Evidence / source_ref | Finding（category=reverse_algo，severity=n/a_re） | 实现路径 |
|---|---|---|
| E1 原AP set_path/scoped D/send/wait/free、CP event8f/1138；既有completion ledger | F1/source_confirmed/high：保存actual D并按原格式独立1138返回；原ingress r6身份仍有gap | origin/cycle、source92840747、原sender receive/free |
| E2 原0138转换、cache及GetPath；既有event8f/device-cache ledgers | F2/source_confirmed/high：canonical尾3置0与保存/readback可分开检验 | 原wire不动，canonical16与完整result160 |
| E3 原1138 constructor及AP parser | F3/source_confirmed/high：00590000表示该路径成功，不能抹成0 | 固定1138原字节、真实consume证据 |
| E4 原f021端点表，selector来源仍未知 | F4/profile_policy/high：90590819/mask1是显式软件端点合同，未提升为物理历史 | snapshot/log物理标志false |
| E5 原AP34e7de8/CP69abae/69ca3c；0153 source ledger | F5/source_confirmed/high：14B前5B保存、独立1153零status，同步AP生命周期；外部分派/原gate时序未闭 | op6、Zebra8、尾8、enable0 |
| E6 本轮专属命令、C fixture、Python driver及生产目标符号 | F6/owner_tested/high：owner735×2和真实core组合96×2通过；自然/强制同址新lease可消费，live/state/常量alias仍拒绝，旧ticket和失败保留不变 | 五opcode共享同一guard/cycle/channel，Layout/display先free后alloc；仅活lease进入request overlap |
| E7 项目根analysis/scratch/functional-bb014c-source/RESULT.md、content-verification.json、pins42窗9934B；哈希入source-pins | F7/source_confirmed/high：AP40B case0、actualconsumer1cd908→0305、1305→event298→独立69c946/114c，success00590000与原send/wait/free静态合同 | op7保存全32B并严格192B读回，向actual D独立114c；不声称执行原0305/1305 |
| E8 项目根analysis/scratch/functional-cp-vdf-startup-inventory/RESULT.md/source-pins.json、AP63call清单；仅选8窗3028B读回验证 | F8/source_confirmed/high：0152八字段、selector3转换、0202/1202/event29c/1152与0162匿名off/0325/1325/event29f/1162均有独立源合同，status00590000 | op8按nativecmd构造不同envelope16，严格176B→原request free→独立ACK12；原FIFO入口/物理工作仍false |

E6复现命令见开头；原source原件由专属pins测试读回验证。E7源调查自带 `python3 -B analysis/scratch/functional-bb014c-source/extract.py` 复现命令，本次没有运行该写证据的提取器。source ledger中的candidate窗口仅固定内容，不把候选表名提升为已证opcode绑定。

P1（path_type=callflow）：actual request/sourceD（E1/E5/E7/E8，F1/F5/F7/F8）→all13 guard与既有一次INIT→对应op5/op6/op7/op8完整校验（E2/E6，F2/F6）→该opcode的独立回复及真实request free（E3/E5/E7，F3/F5/F7）→原D send→原sender实际receive/ticket/free（E1/E6，F1/F6）。布局policy和真实消费的宿主实现属于parent core；本owner的mock通过仅证明回执约束和生命周期。

时间线：继承0138/0153/014c/0152/0162及原681场景与全部源调查；原轮次曾因malloc短request复用而用fixture容量/二次分配避让。此次先移除避让，以真实core组合得到上述0152失败；随后修复活lease overlap，加54个owner及2个真实core组合场景，strict/SAN组件组一次通过，并用已有二进制读回6次计数。未重新反编译或扩展0141 actor。

## 未验与集成边界

原CP metadata source→decoder `1c5300`第二参数的caller身份仍未闭合。原event9e FIFO、物理0305工作与1305生成、src1/type0/timing3枚举名、四u16物理分量次序、selector singleton、event35聚合/第三word、设备延后完成producer、物理总线/plane均未验证。原0153 external dispatcher、saved config→work调度、gate实值与699556发布仍未闭合，阈值单位与enable1渲染未实现。

0152启用时的peaking算子、物理level/scale/colorimetry与0202实际完成生成未知；0162的feature语义和on分支未知，均严格拒绝。新增a3/ab source FIFO静态映射不提升为原OSAL metadata→decoder参数的运行时证明。

`original_cp_fifo_verified`、`physical_cp_rtos_verified`、`original_selector_verified`、`physical_asic_verified`、`capture_verified`在snapshot和日志中独立保持false；源档另保持 `original_ap014c_consumed=false`。单元测试的AP消费表示HOST_TEST OSAL生命周期，不能当成固件原AP运行证据。

Parent负责main lazybridge识别与hook、生产bridge/broker/events/build集成及0141接续。真实core对layout、独立peaking/flag配置保存/读回/实际RGB消费/retire已在本轮HOST_TEST组件组合通过；原AP/VM/mailbox/RSP仍未验证。完整“原AP触发 → 实际虚拟CMOS → 编码模型消费 → 原MPR/Fsys写虚拟SD → 独立解码”仍需整链验收。本成果没有运行VM、fullreg/fullbuild或真实设备，也没有修改EOS关闭。
