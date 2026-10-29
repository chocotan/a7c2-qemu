# 观测探针与 MENU 输入实验校正

目标仍是固件自然启动到拍摄主界面，并能通过 MENU 键进入菜单。以下检查仅限本机 QEMU；主界面尚未恢复。

> 最新纠正：启动scr0099的group311/31e、IDs b1c..b3d是语言可用性列表，并非媒体错误predicate。
> 历史“读取b1d即可找SD原因”的关联已撤回。真实存储提示位于后续dlg_dbl021，producer仍在调查。

> 当前源码策略（用户更新要求）：需要使用full-system源码时，先复制到native的
> `runtime/analysis/device-models/`，然后只读取、修改、测试和编译本地副本。
> 已复制公开源文件/必要工具并记录`UPSTREAM-COPY.json`，不含固件、setting、镜像或运行资产。
> 下面旧章节中的“直接复用同仓库源码”描述的是早期阶段；当前已移除跨full目录的include、构建和运行时摘要读取。
> 每次构建再从native本地源码生成固定快照，保存源码归档和实际observer摘要，避免编译中头文件版本混用。

## 已复核的实现问题

- `MENU_INJECT_KEY` 原来只在 `observe_factory_entry()` 调用注入函数；未启用 `MENU_FACTORY_HOOK` 的实验不会到达此调用点。`run-y8m4spah` 中 guest 已 export `MENU_INJECT_KEY=press`，第一帧返回，但没有 `KEY_INJECT`。因此该运行不能用来判断固件是否拒收 MENU。
- 注入调用移到 `observe_draw_framebuffer()` 的原函数返回之后，仍检查 `create_screen` 已返回、当前线程为 UI 线程。补上 App 队列接收日志，分别报告“提交回调”“App 队列收到”“界面响应”；前两者不等于最后一项。
- 输入开关只接受 `press` / `pressrelease`。主机启动 guest 前校验，C 端用完整字符串比较，避免原先读取短字符串 `mode[5]` 的越界风险。
- `run_i_gate_probe_trampoline` 原样复制了 PC 相对 `CBNZ` 编码。搬到观察器 so 后，远分支不再指向 appFw 的 `0x305e8b4`。现改为局部条件分支加显式继续地址，并保存额外的易变寄存器；必须显式启用 `MENU_RUN_I_GATE`（依赖 `MENU_ENTRY_PROBES`）。
- `test_observer_gate.py` 检查**编译产物**中门探针的分支与最终槽位，覆盖两个字节的所有零/非零组合；不只检查 C 文本。

## 收回过度推断

以下旧报告与对话中的断言不可作为验收依据：

1. `SEQ_FINISH` 只记录前 40 次，且旧实现以 64 位读取 `node+0x10`；不能据此证明“所有节点完成”“0x4bd 从未注销”或“0x4bd 从未创建”。
2. `model::create_sequence` 是通用创建入口。未记录请求 ID 的 `stage=2` 命中，不能证明执行了 `0x4bd` 工厂。`stage=1` 前后都有命中也不能建立同一请求的关联。
3. `deps=0` / `waiters_now=0` 不是整个 boot 已完成的证明；仍需对应线程栈、调用返回点和具体队列状态。
4. 加锁包装后还有实际函数调用。看到包装本身没有循环不能排除被调用函数阻塞。
5. `{byte500=0, byte501=0}` 只说明两条原始 CBNZ 都不跳，目标为 `0x305bcbc`；没有证据将字段命名为“就绪”。远路径条件是 `byte500==0 && byte501!=0`。
6. 单色 PNG 必须读取 RGB 值；黑、白、透明不能靠文件大小判断。OSD 发送次数或颜色数也不能独立证明拍摄界面已出现。
7. `0x3369850(manager,0x4bd,NULL,0)` 已崩溃，参数 ABI 未闭合；本轮不会启用 `MENU_SEQ4BD_CREATE` 或以其结果推断正常构造链。
8. 旧分支扫描脚本写了 `imm-(1<<26)` 而没有赋回，漏掉向后 BL。原指令 `0x209f320: 97fffa92 bl 0x209dd68` 即为 `process_power_on` 的直接调用点；“没有静态引用、只能间接调用”的结论作废。

## 验证状态

- `bash build-observers.sh` 成功；保留辅助工具中已有的 libc 手工声明警告，未出现编译错误。
- `python3 test_observer_gate.py`：2 项测试通过，包括编译产物的分支条件组合检查、非法注入模式在启动 VM 前被拒绝。
- `python3 -m py_compile qemu-menu-probe.py` 通过。
- `analysis/sync_repo_scripts.sh --check` 通过；项目约定的 pytest 回归为 **244 passed, 1 skipped, 58 subtests passed**（排除缺 Cryptodome 的 `remove_dat` / `jiritsu_crypto` 两组）。
- QEMU `run-rc1m3yhb` 使用 `MENU_INJECT_KEY=pressrelease`；关闭入口探针、强制切屏、手工造序列和管线虚拟应答。
  - `console.log:1464–1466` 记录提交 MENU ON，以及 ON/OFF 回调返回；没有 `App queue received MENU` 记录。
  - 唯一 `CREATE_SCREEN_ARGS` 为 `id=0x308 count=28`，没有观察到后续切屏或异常监视器。
  - 导出像素 RGBA 为 `(0,0,0,0)` 单色，RGB 视图全黑。AP 快照 seq=1，SHA-256 `f8b97f66a6873f620006b37b01e69b4922b8d0866559ee5afa762cba39b3d8e3`。
  - 因回调的返回值没有单独校验，`MENU ON sent` 日志只能证明回调完成，不能证明入队成功、消费成功或 MENU 门控拒收。
- 后续实验保持同一输入，仅增加已有 `MENU_UI_STACK=1` / `MENU_QUEUE_STACKS=1` 只读栈采集，判断 UI 是否仍在 boot 等待链。结果待回填。

旧证据保留，不将错误探针结果改写为固件行为。

## `0x4bd` 独立核查

三个运行不能合并推断：

| 运行 | 内容证据 | 能得出的结论 |
|---|---|---|
| `run-kb8j6kxt` | appFw B=`0x7f4994d000`；SeqQueueStillCa 帧 `0x7f4cdfb0cc ← 0x7f4cb56e48` | 对应 `0x34ae0cc ← 0x3209e48`，当时 4bd 已创建并进入运行，等待媒体初状态 |
| `run-huafzp1s` | lookup 空分支、请求入口和通用创建入口均命中 | 没有 4bd 专属工厂/构造/登记证据，无法确认该对象生命周期 |
| `run-x91gd7_y` | PC=`B+0x3368cf0`，原指令 `ldr w0,[x20]`，x20=0 | 强制构造在读取 NULL 参数时崩溃，未完成该次构造 |

正常请求 `0x24a5c18` 构造 `R`：`+0=u32(0x4bd)`、`+4=flag`、`+8=predicate`、`+0x10=u32 payload`。请求入口参数可空时，构建器把 payload 设为零；工厂传给构造器的是**有效地址 `R+0x10`**，不是 NULL。

`0x25018d4` 入口还有 `u8[B+0x7e4e608]` 许可门；通用创建器还有按请求组求值的 predicate 门。入口命中并不能证明请求被接收，更不能证明指定工厂执行。

登记 `0x3222ad0(M,O,id,flag,lock)` 不保证返回对象指针；旧实验把残留 x0 当 `created -> pointer` 不成立。4bd 的 group 为 2；current 位于 `B+0x910a5c0`，pending 链头为 `B+0x910a548`。后续应以同一轮的线程栈、对象 vptr/描述符和查找结果来判断，禁止用不同 run 拼接“单一根因”。

## 同一轮动态栈：`run-cvugzblg`

本轮未启用入口探针、强制切屏或强制造对象，MENU ON/OFF 回调完成，屏仍为 308、像素透明黑。appFw 加载基址为 `0x7f27730000`；以下帧已逐个减去该基址：

| 线程 | appFw ELF VA 帧链（从内向外） | 解释 |
|---|---|---|
| UI tid286 | `2e071c0 ← 272ffb4 ← 27316a8 ← 209e39c ← 209f324` | 等 boot_start_seq 的 future，尚未回到正常输入循环 |
| SeqQueueCommon tid324 | `3510ff0 ← 34e9b24 ← 34c6904 ← 305dd70 ← 305e9e8 ← 3209e48` | boot 仍在执行，当前卡在 Dataflow ReceiveASync |
| SeqQueueStillCa tid326 | `34ae0cc ← 3209e48` | 本轮 4bd 已开始运行，处于媒体初状态等待 |

**当前等待的是 VDF `0x9059000e` 的时码配置回复。** 原指令 `34e9b08` 构造 `w3=0x9059000e`，`34e9b10` 发送；`34e9b20` 随后调用收取包装，`3510fec` 调 `ReceiveASync`，超时为 `-1`。本轮日志有 `SND_MSG_OTHER tid=324 dest=0x9059000e bytes=52 source=0x81cf61c7`，另有内核 `Skip snd to 0xe`。接口名表 `58c8550` 的 id48 指向 `vdf_srvc_set_timecode`。

旧 §4.30 从相邻 `34e9d30` 取出的 `0x92840747` 不属于这条调用链，不能将该端点的错误回显实验用于否定当前 VDF 阻塞。

既有 `after-buspower/AP-WIRE.md` / `VDF-TIMECODE.md` 已解出：52B 请求包含24B封套与 `2001/0205/001c/0001`；回复为36B（24B封套+`2001/1205/000c/0001`+u32结果），源 `9059000e`、目的为动态 replySID。已重新逐字节核对 `vdf-reply-evidence.txt` 的169条记录及CP SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。

下一步复用已有有状态 VDF/HDMI 时码配置实现与测试。成功回复必须对应实际配置消费；不得将回复成功描述为 HDMI 输出、取景或拍摄已完成。

## VDF 接入实验

native 通过 `MENU_VDF_CONFIG=1`（默认关闭）链接并复用相邻 full-system 成果的公开 `vdf-device.c`、`vdf-device.h`、`imaging-device.h`。未复制其 root、setting、镜像或运行资产。当前源码构建依赖该同仓库目录；尚未制作可独立分发的 native 包。

native 的接入点为原 OSAL 发送 wrapper，仅拦截 `9059000e`；未启用 `92840747` 的旧回显实验。回复释放沿原 free wrapper 交还原 OSAL。共享模块保存20B配置，模型内部消费f033并更新hdmi_cache，使用独立36B回复与lease跟踪；失败保留/回滚及拒绝行为沿用原模块测试。

这里的内部消费是 C 配置模型执行，不是原CP线程运行；`internal_destination=9059081b` 是对应原协议的日志字段，不表示向该队列发出了另一条真实内部消息。模型没有 cable 状态，因此 **hdmi_cache=0 不等于 NoCable=0**。本实验不会主动制造连接、ready或像素输出；不宣称已动态验证 cable 状态。

已启动“既有 `test-vdf.c` → native 构建 → 探针/模式测试 → QEMU”的失败即停止链。后续只用原waiter释放、配置读回及线程栈/帧缓冲判断结果。已有full-system验证器的 `verify(console)` 可复用，CLI需要的元数据文件名与native不同，不能直接套CLI。

首次接入验证的 `VDF_EVF_SUBSCRIPTION_NO_EVENTS_PASS`、`VDF_PROTOCOL_STATE_OWNERSHIP_ABA_PASS` 和3项观察器测试均通过；QEMU **尚未启动**即被资产检查拒绝，原因是临时 `simulation/vdf-device.o` 被误放入 guest 根目录。已移除该临时文件，改为主机构建临时路径并在退出时删除，资产白名单不变。修正后的运行清单记录 VDF 开关、输入模式及复用源码摘要；重试结果待回填。

### `run-fnp8hx_d`：时码消费闭合，boot 前进到 0165

复用原 `verify-vdf-timecode.py::verify(console)` 返回 `vdf_timecode_config_verified=true`：

- tid324 发52B原0205请求，动态source/replySID=`81cf61c7`。
- `FULL_VDF_COMMIT` 显示 `cache_before=1 cache_after=0 hdmi_consumed=1 request_free_rc=0`。
- 对应36B回复由同一原waiter释放：`lease=1 waiter=1 cmd=0x205 rc=0`。
- 同一线程随后发020b订阅，配置被保存，`valid=0/events=0/ap_reply=none`，没有生成伪状态事件。

UI依然在boot future中等待；当前Common栈已前进到 `34e5788 ← 34e9960 ← 34c6844 ← 305dec0 ← 305e9e8`。原`34e9900`构造的是raw `200d/0165/000a/8001`，selector=2，size=0，发送至`92840747`并期待12B回复。

已接通共享模型中现有的0165处理分支，其原协议与状态消费见 `after-buspower/RAW-0165.md`：先保存控制影子，再按结果返回带域编码的`00590000 | status`，维护尺寸有效缓存与调用者所有权。仅处理已知0165；其余raw命令继续走既有路径。后续QEMU结果待回填。

`run-fnp8hx_d` 的 `camera_startup_verified=false`、`hdmi_output_verified=false`，画面仍为透明黑，不能称为拍摄界面已恢复。

### `run-bmlcpz8i`：0165 状态消费与原线程释放通过

既有 `test-panel-resolution.c` 的主机状态/所有权测试通过后进行了本轮 QEMU。逐条关联同一 reply 指针、lease=2、tid324，原始请求 `0d2065010a0001800200` 得到原协议回复 `0d2065110c00018000005900`。记录的顺序为 request → reply queued → commit → native waiter free；对应动态目的地 `81cf61c7`，原请求和回复释放均返回0，无 `FULL_VDF_FAULT`。

状态结果：`shadow_flags=0x40 shadow_selector=2 shadow_size=0 cached_valid=1 cached_size=0`，明确 `pixels_switched=0`。已把逐字段校验与摘要存入 `vdf-panel-native-proof.json`。

Common 已越过原0165等待，下一帧链为 `34e5788 ← 34f4dd4 ← 34c7984 ← 305e064 ← 305e9e8`。UI仍等boot future，StillCa仍处于媒体首状态等待，截图透明黑。此项验收仅为配置模型，尚未通过拍摄主界面验收。

### 独立接线审查

只读 reviewer 在新增接线范围未发现可证问题。复核了默认关闭、冲突GOT开关拒绝、回调ABI、单次消费与释放、lease不随环境开关消失、共享源码路径和资产隔离。现有观察器版本依赖仅为 `GLIBC_2.17`，未引入高于固件glibc2.25的要求；4项观察器测试通过。审查独立复核了 `run-fnp8hx_d` 的原时码验证器结果；面板 `run-bmlcpz8i` 的动态验收由主会话完成，不混写为reviewer实测。

时码/面板两项接线后的 `sync_repo_scripts.sh --check` 与项目回归再次通过：244 passed、1 skipped、58 subtests passed。此处不包含已按项目约定排除的两个Cryptodome缺依赖测试组。

## HDMI 开机配置接线（动态结果待验）

`run-bmlcpz8i` 下一等待已由原代码与请求记录确认：`305e060→34c7958→34f4d54→34e552c` 发 `2500/010a` 到 `909a015a`。复用同仓库公开 `hdmi-device.c/h`，以默认关闭的 `MENU_HDMI_BOOT_CONFIG=1` 接入其既有 `FULL_HDMI_BOOT` 子集：010a定义、0101六字段初始化尺寸、0117五项速率枚举，以及已有定义/尺寸getter。其它命令仍走原路径。

010a的原共享状态回复为**裸status1**，由AP既有mapper接受；不能套用panel0165的域编码。0101/0117为status0，但必须保存对应字段后才生成回复。字段枚举不推断为物理像素尺寸或Hz，DP字段按原共享consumer保持不应用。

发送/释放回调、日志镜像、环境转发和源码摘要均接入；与发送GOT实验钩子的组合在启动前拒绝。主机完整HDMI测试→构建→观察器测试→QEMU已启动，尚未把既有full-system动态证据计为本轮native通过。

### `run-tudovicj`：HDMI 三段配置通过

主机HDMI定义、六字段尺寸、五项rate和50轮受控地址复用测试均通过；5项观察器测试与ALLLANG资产检查通过。本轮原Common tid324依次完成010a、0101、0117×5，按每条原请求的动态source、reply指针、lease和tid关联后，均为 request → queued → commit → 原waiter free，原请求/回复free返回0。

定义保存0/known1，native status1；尺寸按原请求保存`000000000605`；rate枚举为`[0,0,17,17,0]`，valid mask逐项`1/3/7/f/1f`，DP未应用。同一reply地址在真实free后用于下一lease，共lease1..7。下一栈出现`305e410`且不再停留在`34f4dd4`，证明已越过该配置段。逐项校验与摘要见`hdmi-boot-native-proof.json`。

UI仍等boot future，画面透明黑。下一实际帧链为`3510ff0 ← 3511158 ← 3511604 ← 35a9ad0 ← 35a9eb4 ← 34dc514 ← 305e410`（源pin查询路径）。

## pin Get-only 接入（动态结果待验）

默认关闭的`MENU_PIN_REGISTRY=1`复用公开`vef-device.c`、`pinmem-device.c`及`pin-registry-core.c`。源端和peer端分别持有16/13个metadata对象，按原三键查询并回显完整查询键、当前state与ownSID；不创建图像buffer，不把cold state1强改0，不启用Connect。发送、lease释放、日志镜像、开关校验及源码摘要均接入。

Connect与其后的404控制buffer/格式消费需要真实保留虚拟RAM、映射与内容读写验证，尚未在本轮native启用；不能用Get成功冒充连接或图像消费成功。

首次Get-only验证在主机测试编译阶段停止：共享`test-vef.c`的一行while循环/解锁语句触发`-Werror=misleading-indentation`，尚未启动QEMU。仅为while添加花括号并把解锁移到独立行，测试语义与严格编译选项不变；已启动同条件重试。

### `run-dayp_jhq`：实际目的地不同，Get-only尚未命中

测试与QEMU观察完成；manifest记录`pin_registry_service=true`。但没有`FULL_VEF_`或`FULL_PINMEM_`消费记录，Common仍停在同一源pin查询栈。检查原发送日志 `console.log:2976`：tid324实际发送**48B到`9284074a`**，source为`81cf61c8`。这不同于旧full-system的`905a0048`查询，不能直接套用其对象表或把两个SID互换。

已加入默认仅随`MENU_PIN_REGISTRY`启用的被动`PIN_QUERY`记录：在服务分派之前记录实际目的地/source及48B原包，保持原始投递行为。原CP接收者及分支选择另行只读调查。本轮没有证明源/peer Get成功，不能将host registry测试当作该次guest通过。

下游404 RAM调查已完成：native的现有5GiB高DDR bank覆盖`0x500000000`，但目前没有该8192B区域的专属reservation/identity，不可直接写入。Connect/cold格式模块只支持明确的`905a0048→90590818`源/peer组合；在`9284074a`归属闭合之前不启用或移植该连接流程。

### `run-q9w2fg7h`：实际48B请求已捕获

原Common tid324发送：destination=`9284074a`，source/replySID=`81cf61c8`。

```text
c861cf81a0a0a0a00100300018000000300000007f000000
001000001800020000000000020000000100000000000000
```

外层是1条消息/总长48/读游标24/写游标48；opaque字段本轮为127，不强制零。内层为`1000/0000/0018/0002`，四个u32为`0,2,1,0`，即查询三键 **`{type0,dir2,index1}`**。48B长度、头部与各u32已按小端独立解析；不是旧full-system的`905a0048:{0,2,3}`。捕获未改变目的地或原包内容；owner归属调查继续。

## 旧生命周期探针收敛

已移除`MENU_SEQ4BD_CREATE`触发的NULL-payload手工构造调用。主机若收到旧开关，会在启动VM前明确拒绝；保留`SEQ4BD_CREATE`的只读入口观测，不再从探针修改对象生命周期。

`SEQ_FINISH`改记`action=metadata_erase_enter`：读取`node+0x10`的u32 ID和`node+0x18`的cookie，原LR由trampoline显式传入，避免把观察器自身返回地址误标为appFw调用者。一般记录仍限40条并明确输出上限标记，0x2a/0x4bd记录不受该上限截断。它仍不能单独证明对象析构已完成。

新增测试以真实C recorder源码编译主机小程序，覆盖非零填充污染、cookie读取、原调用地址和第40条之后的关键ID观测；另测试旧强制构造开关在VM启动前被拒绝。构建/测试结果待回填。

上述生命周期修正构建成功，7项观察器测试通过。

## InfraBB YC OUT1 Get-only（动态结果待验）

路由调查闭合：`9284074a`是原InfraBB `PinMgrTask`的完整SID。CP raw `fe7808`起有21项属性，每项四u32；raw `fe7858`为slot5 `{0,2,1,9284074a}`，对象CPVA `01789434`（YC OUT1）。主会话已重新校验CP摘要及全部21项原始数据，未把它改投为VEF。

原构造raw `59b918→583582`设置state1、peer `{ff,ff,0,0}`；原Get raw `cdba0`用完整三u32查找，返回实际metadata state及ownSID。回复外层自身replySID为`9284074a`，与VEF的零值不同；OSAL目的地仍取本次原请求的动态replySID。

新增`infrabb-registry.c/h`只构造虚拟cold metadata、实现Get并拒绝Connect；不运行原CP任务，不分配图像buffer、不设置ready。共享core显式增加full-key与replySID策略，默认值保持原VEF/PinMem/Scalar语义；快照容量扩到21而各owner live count不变。

自动验证链包含：InfraBB原48B/56B向量、21项边界、拒绝高位不同的查询键、拒绝Connect；原VEF/PinMem/Scalar回归与跨owner内存地址复用测试；native构建及7项观察器检查。全部通过后才运行本轮QEMU。

### `run-typ0vn1q`：三个owner的11次Get消费通过

主机测试、构建和QEMU观察完成。已逐条核对21/16/13项构造记录、48B请求与56B回复、查询三键完整回显、state1/ownSID/status0、动态目的地、同一owner的reply指针/lease、同原tid324的实际free0，无owner fault。InfraBB回复自身replySID为`9284074a`，VEF/PinMem为0。

通过数量：InfraBB 2次，VEF 5次，PinMem 4次。YC OUT1查询唯一命中InfraBB slot5；随后原线程实际查询VEF IN1。Get-only拒绝未支持的控制请求后，原固件继续检查其它拓扑边；**继续发请求不代表被拒绝的连接成功**。完整验收范围与摘要见`pin-get-native-proof.json`。

下一实际请求为`91670464:{0,1,4}`，与已有Scalar独立10对象registry契约一致。已接通该Get-only owner（无图像缩放或buffer），并增加64B控制请求的被动全包记录以核对后续原命令。Scalar/跨owner测试→QEMU正在执行，动态结果待验。

InfraBB→VEF的后续静态调查已交付：该边使用真实四包`0001→0100→8100→8001` metadata握手，Get的非零replySID规则不能沿用到这些控制包；后者外层replySID为0。VEF IN1在8100之后还会分配unit404并生成80B冷格式数据，通过0104通知InfraBB OUT1实际打开/读取/比较/关闭/归还引用。该路径不同于旧VEF→PinMem连接：producer为VEF、InfraBB helper为216B wire/token55/动态临时SID，不能直接套152B PinMem路径。尚未在native实施或验收该连接；没有把四包成功视为buffer-ready。

### `run-adysi__6`：Scalar Get消费通过

Scalar10对象构造、实际查询`91670464:{0,1,4}`、slot4/state1/ownSID/status0读回、独立56B回复及同原tid324的request/free与reply/free0已逐字段校验，摘要见`scalar-get-native-proof.json`。

新增的64B被动捕获确认了多条原RequestConnect（`1000/0001/40B/flags2`），包括InfraBB OUT1→VEF IN1、type8链、VEF OUT2/OUT3→PinMem IN0/IN1、PinMem OUT1→Scalar IN4。Get-only仍拒绝连接，不能把固件错误后继续遍历的行为当成连接完成。

当前最后一条48B查询为`9058003f:{0,1,0}`，原owner及已有ADF实现另行核查。UI仍等boot future，截图透明黑。

## 专用控制RAM验证（结果待验）

新增默认关闭的`MENU_PIN_CONTROL_MEMORY=1`：仅支持高DDR cpio实验，最终bootargs加入唯一profile及`memrsv=0x00002000@0x500000000:uc`；同时用既有严格helper校验最终所有reservation、RAM范围、DTB reservation map及16B owner identity。没有原区域空闲证明时不写入。

`MENU_PIN_BUFFER_SELFTEST=1`只在上述声明启用时运行独立guest探针；在独立本轮VM中获取独占owner，实际分配、写读32B SSYN基础头、第二次映射检查整8192B、归还lease。QMP再独立导出整区，与预期字节及guest FNV比对后才生成`pin-control-backing-proof.json`。它不是80B格式链验收，也不运行原CP任务或消费像素。当前未把buffer owner接入AP Connect，所以独立探针不会抢占正在运行的连接owner；后续接入时须保持两者互斥。

资产白名单仅新增明确的`simulation/pin-control-probe`可执行工具，目标文件仍只在主机构建临时目录。DTB/冲突测试、构建、guest/QMP验证链及独立审查已启动。

## ADF Get 契约核查

新的`9058003f:{0,1,0}`静态链已补齐：CP raw `572068→572be6→572bf0`加载raw `c0b234`的10项属性，通过`583582`构造独立对象；`572624/57264e→57275a→5727ee`处理Get并比较完整三u32。命中010为slot0，读取当前state和selfSID，回复56B/外层replySID0、source9058003f，六u32为`{0,1,0,state,9058003f,0}`。

现有`adf-device.c/h`已设置full-u32策略，10键表与原件一致，可在共享core上复用。缺键原status为e002，但当前模块只声明found-key子集，缺项明确拒绝，不补零成功。尚未取得ADF原waiter消费证据；已独立启动其现有主机测试，未将静态核查记作动态通过。

### `run-d294kdld`：控制RAM guest/QMP跨通道验证通过

native DTB测试3项、共享保留区测试10项、观察器测试7项通过，ALLLANG资产检查通过。内核日志实际出现`memrsv: 0x2000@0x500000000`；最终DTB identity读回为`(0x500000000,8192)`。guest独立probe取得unit404/handle8000/512B，写读32B基础SSYN头、二次映射核查整8192B，归还后live0/releases1。

QMP独立导出整8192B，逐字节为基础头加零区；与guest FNV一致为`779675b750ddac53`，SHA256=`23edb99892f3ada277c0f4c3672106cd1080769e1120a5ceed1fc6c9cc83bacb`。主会话另外复查最终console、DTB、raw dump与自动proof的三项摘要一致，公开证据为`pin-control-ram-native-proof.json`。

该项仅通过RAM绑定/写读/释放基础。没有AP Connect，没有80B格式消费者，没有像素或拍摄成功。ADF Get-only接线已进入单独测试→QEMU链；Connect准备工作将复用已证VEF OUT3→PinMem IN1边，不套用到不同的InfraBB边。

### `run-iy_cqmmi`：ADF Get消费通过

ADF10对象及原查询`9058003f:{0,1,0}`命中slot0。56B回复六u32为`{0,1,0,1,9058003f,0}`，外层replySID0；同原tid324、同pointer/lease的request/free0及reply/free0已核对，证据见`adf-get-native-proof.json`。下一实际48B查询为`928d0783:{6,1,0}`，另行只读调查原owner。此项仍是metadata消费，未运行原CP任务、未连接或消费像素。

## 有真实backing的冷态连接实验（待验）

新增默认关闭的`MENU_PIN_CONNECTION=cold`，只复用已有明确的VEF OUT3 `{0,2,3,905a0048}`→PinMem IN1 `{0,1,1,90590818}`实现。它要求同时开启专用RAM与registry，且与独立RAM selftest互斥。AP进程首次相关请求绑定保留区，随后复用四包metadata握手、404实际buffer分配、80B冷格式写读、consumer打开/解析/保存、最后引用归还；释放原AP回复后额外记录持久CPU格式状态。

该路径明确使用virtual-cold constructor参数，非原运行协商；不设置frame-ready、不消费图像planes。其它连接边不扩大支持。QMP保存整个保留区以便独立核对；发现连接/格式ownership fault时整轮失败并保留RAM与console证据。

为保持两个交付路线的构建兼容，full-system派生构建的baseline源集合补入native新增的`infrabb-registry.c`；验证只在临时root链接，未覆写full-system运行镜像。

首次隔离兼容检查中，既有Connect/80B格式模型主机测试六项PASS；派生构建在文本转换阶段失败，未进入链接，原因是旧模板要求无条件`REG_ASYNC`日志，而当前基线带`MENU_REG_SILENT`条件。匹配范围已收窄到唯一的`record("REG_ASYNC ", text);`调用，保留其外部条件及严格单匹配检查。九处转换锚点已全部核实唯一；正在分别对当前条件形式和旧无条件fixture做临时root完整链接重验。

该次隔离重验已完成：当次current基线和旧无条件registration fixture均完整链接成功，产物SHA256分别为`e793dcbe9e530c79e2b09481f456003552d8a854daedb6e90a3cdeaf44285af2`、`290a79db8429093a39bd426d83c2e56d09a850bc77401852c9667a5bfe81715f`。所有产物均位于临时root，未覆写运行镜像；此证据限定于当次源快照，不自动覆盖后续并行更新。

## DrawInfo Get命中子集（主机测试待验，未接入运行器）

`928d0783`的原接收者是DrawInfoPinCtrl/DrawInfoPinMgr：静态任务raw`5d8b8`构造sender及registry后接收完整SID；原表raw`c0053c`仅两项`{0,1,0}`、`{6,1,0}`。完整构造`5327d8→583582`建立独立state1/peer `{ff,ff,0,0}`对象，Get `531fc0`按完整三u32查找，读取当前state。默认池的薄构造不能单独作为state1依据。

命中回复56B，外层replySID0，OSAL source为`928d0783`、目的地取请求外层动态replySID。本次静态cold body为`{6,1,0,1,928d0783,0}`。原缺项有e002及特定残留metadata语义，当前仅复用found-key子集，缺项明确拒绝；不称完整Get等价。

已新增`drawinfo-registry.h`及独立owner实现/主机测试，覆盖两对象、完整u32拒绝、独立source/replySID、零回复SID及Connect拒绝。为保留共享构建脚本期间已有的并行更新，native的两个独立owner同处已有`infrabb-registry.c`编译单元，未覆盖另一条路线的可选依赖逻辑。DrawInfo现已接入native并启动动态验证；未运行原CP绘图任务，不代表drawing/ready/像素消费。

### `run-_1cx34uw`：一条真实backing冷态路径的观测

实际Common为tid325，UI为tid287（线程号必须从本轮日志读取，不能沿用此前324/286）。VEF OUT3→PinMem IN1已出现四包消费、双方state0/peer一致/pending0读回，随后unit404分配512B并写读80B格式。

引用读回依次为shared `(owners2,opens1)`、creator-released `(1,0)`、consumer-open `(1,1)`，最终commit为`live0/owners0/opens0/buffer_released1/format_cpu_consumed1`。原tid325释放8001后，持久CPU getter仍读到pin2/ordinal1/code1/component0/flags0/1920×1080。参数来源明确为virtual-cold constructor，非原运行协商。

主会话独立比较整8192B QMP导出：前80B精确为声明的SSYN/ETRY冷格式，其余全零；80B FNV=`e90fff64626243a2`，整区SHA256=`76841724cf9a57743c84a0fb01f6ef25015865ee189635eb2c5107a59e9b200b`；CPU currentinfo_raw与RAM内容一致。完整共享内容验证器已增加native元数据入口（不伪造full-system inputs/result），并开始正例、篡改RAM/状态/缺free/profile负例及原full-system回归。

本轮仍停在DrawInfo Get，截图透明黑；其它连接边仍unsupported，`frame_ready=0/pixels_consumed=0/camera_startup_verified=0`。

后续`run-oow6rsz4`中，DrawInfo两对象构造及`{6,1,0}`命中slot1已实际通过：56B/零replySID/owner928d0783/state1/status0，原tid325同pointer/lease的request及reply释放均返回0。逐字段证据见`drawinfo-get-native-proof.json`。下一查询为HDMI pin `909a015a:{4,1,0}`，并非已有2500配置命令；目前正在使用native本地复制的HDMI pin模型验证，不直接读取full源码。

本地副本首轮验证在启动QEMU之前失败：构建快照2测试、HDMI/InfraBB/DrawInfo C测试、observer 8测试、保留区10测试（缺历史DTB跳过1）和native格式2测试已通过；随后格式回归缺少本地`test-pin-control-verifier.py`，报`FileNotFoundError`。这是测试依赖迁移遗漏，不是本轮guest拒绝Get。现已先复制该helper再修改本地libfdt路径，原始副本摘要追加到`UPSTREAM-COPY.json`；失败链与HDMI动态实验已重启。

本地`verify-vef-pin.py::verify_registry(..., native=True)`复用原逐字段Get检查，直接读取native的manifest/summary，不伪造full元数据。`test-native-registry-verifier.py`以`run-oow6rsz4`为正例，并分别破坏回复owner、lease、free、profile和run identity，2测试/5负例通过。验收范围是`registry-query`，始终保留`whole_run_success_verified=false`。

该阶段项目约定回归再次通过：`analysis/sync_repo_scripts.sh --check`确认旧system-dump交付脚本一致；`cd analysis && python3 -m pytest $(ls test_*.py | grep -v remove_dat | grep -v jiritsu_crypto) -q`得到244 passed、1 skipped、58 subtests passed。两组Cryptodome环境缺口按项目约定排除。这是工具回归，不替代HDMI Get或自然主界面的动态验收。

本地副本重验已完成并实际运行`run-aehffq8v`：control验证器4测试通过，format验证器4测试通过，connection验证器4测试中私有历史地址复用run缺失跳过1项，其余通过。native保留区测试该命令未设置libfdt环境，因此3项中2项跳过；另行补跑带工具和旧DTB的完整版本，不把跳过报为通过。

补跑已完成：设置native的`A7C2_LIBFDT`和`run-iy_cqmmi/virt.dtb`后，保留区3测试全通过、无跳过；本地格式验证器在`run-aehffq8v`的真实内容及RAM/状态/free/profile负例2测试通过。80B格式、最后引用释放和持久CPU缓存再次通过，整8192B SHA256仍为`76841724cf9a57743c84a0fb01f6ef25015865ee189635eb2c5107a59e9b200b`。该批任务在下面独立审查修复之前启动，不用它替代修复后的回归。

HDMI pin两个对象实际构造为410/510、cold state1/peerff；tid325查询410，56B回复outerSID0/ownSID909a015a/status0，同`reply=0x7f88fe5e40,lease=1`原request/free均0。`verify_registry(...,native=True)`逐字段验证通过，见`hdmi-pin-get-native-proof.json`。现有2500配置服务保留，Get后固件还发出PinMem type4→HDMI Connect，但本模型不支持该边，不能因后续继续遍历而宣称连接完成。

本轮113个C/头文件编译输入全部位于native，运行保存的源码tar归档逐项摘要与`observer-build-inputs.json`相同，无full跨目录源输入。之后Common325仍在`3510ff0←3511158←3511710←35a9ad0←35a9eb4←34dc514←305e410`，最后实际Get为`9080003b:{1,3,0}`；UI287仍等待boot future，StillCa327仍在`34ae0cc`。13张RGBA4444截图均为640×480、每像素RGBA=(0,0,0,0)，未恢复拍摄主界面或MENU消费。已并行派只读调查核对新owner契约与StillCa媒体前提，主会话继续负责实现和动态验收。

独立RAM审查返回两项P2证据关联问题，未发现分配/引用/fork/high-DDR路径额外可证缺陷：

- E-image：原启动校验检查主机observer/原库，未比对`--initramfs-file`所选cpio内部内容。F-image：有效旧cpio配合新主机observer可能生成不相符的构建归属记录；这不是已证明历史run发生错配。P-image：新增`initramfs_identity.py`只读解析raw newc，检查实际选定镜像中observer、pin-control-probe、appFw/Obj及已记录GPE/MPR/CP配置字节，拒绝缺失、重复、非普通文件、截断和多重归档；构建记录补充probe摘要。修复后的测试/实际镜像核验正在执行。
- E-reservation：原offline verifier仅核正profile及DTB owner，缺最终cmdline冲突校验。F-reservation：可接受启动端会拒绝的重叠保留、冲突profile及超16条配置；不表示当前启动端允许这些配置。P-reservation：本地`pin-buffer-region.py::validate_final_command`集中原启动规则，native启动和offline verifier共同调用；真实libfdt修改bootargs的5种负例及现有组件回归正在执行。

修复首轮验证中，真实newc正/负例2测试和源码快照2测试通过；原control fixture因只有控制池reservation、没有原workspace reservation，被统一规则拒绝。保留严格规则，给host fixture补入非重叠workspace `memrsv=0x1000@0x410000000:uc`，并让5种冲突变体从这个合法基线生成。此项属于测试fixture适配，非放宽启动/offline规则；后续完整链重新运行。

修复后的完整回归已通过：control 5测试（含5种冲突bootargs）、format 4、connection 4中缺私有run跳过1、native保留区3无跳过、native真实格式/负例2、observer 8；Python解析及observer/initramfs构建通过。实际395MiB raw cpio内observer SHA256=`977b9f921850b4961b67c9542bb19318cf74dda4f7559f28aee7f93d47e27d95`、probe=`41361c208646d3332d4e744dbb75fa63dd6df8719941cc90c90734edc5de8214`，逐项匹配构建记录；appFw/Obj同时匹配原身份。该摘要仅描述这次生成物，后续重建应读取对应run记录，不写成永久常量。修复后的实际QEMU启动检查与独立复核已启动，动态结果待返回。

9080003b只读调查已完成并收回：这是OsdPinIF，一个130 pin，原Get忽略键且回复外层SID为自己，同时尝试200B内部图形事件。详见`osdpin-get-contract.md`的原始地址与实现边界。主会话已独立复核关键Thumb常量；新增本地独立owner仅支持实际130 Get，明确不支持原图形事件/资源初始化/其它键，不把Get回复算成OSD完成。测试和锁内动态实验已启动，结果未预判。

StillCa调查亦已交付，当前两个只读调查均已完成：初始snapshot的原生产者是rep_boot退出回调，故`34ae0cc`本身不证明缺虚拟存储。`stillca-initial-wait.md`记录完整谓词、producer和条件mount链；主会话新增`menu-regs --stillca`只读对象/字段采集，要求原wait/run栈、vtable和mutex相符，两次pread一致，明确非原子快照。host字段读回与坏对象/截断负例通过，动态字段待采集。

RAM修复独立复核：统一cmdline验证已确认修复。cpio stale-image检查亦已生效，但复核发现未知路径可经符号链接祖先覆盖已校验文件。现对所有archive条目跟踪祖先类型及重复路径，拒绝符号链接/普通文件祖先和后续祖先替换；新增alias/appFw覆盖负例。真实cpio 2测试含该负例通过，当前实际cpio重新跑祖先检查通过。运行结果仍须关联各自归档版本，不能把修复后的校验能力追溯套在旧run上。

镜像身份动态路径`run-0kwavcos`已完成：运行清单实际记录8个选定cpio文件摘要，observer/probe与构建输出一致，appFw/Obj与原库身份一致，CP/配置/GPE/MPR亦匹配所记录输入；源码归档逐项摘要通过，清单SHA256=`7015f8f9ac4b28f3f0613e55b5da037793d86442bfcb051dec42aa6964724ca9`。见`runtime-image-identity-proof.json`。本轮启动早于OSDPIN和StillCa新代码接线，仍等9080003b130，没有`FULL_OSDPIN`或`STILLCA_STATE`，不能把后续代码功能算在本轮；后续实验按同一probe锁排队。画面仍透明黑，主界面未恢复。

`run-mfj5hx4k`完成OSDPIN130 Get动态验收：cold对象1，56B自SID封套，原tid325对同`0x7fa54a8d40/lease1`回复实际消费/free0，scope日志明确200B内部图形事件未发送、OSD资源未初始化。证据见`osdpin-get-native-proof.json`。此后ADF520/HDMI510 Get也已出现，Common325栈改为`303d49c←305e434←305e9e8←3209e48`，不再停在pin Get receive；其它Connect依然拒绝，不能把遍历结束视为连接成功。UI287仍等待boot future，13张截图仍透明黑。该轮helper早于StillCa字段采集，故无字段记录；最新只读helper实验已启动。

新原生registry正/负例3测试通过，包含OSD自replySID被改成零时必须拒绝。`run-mfj5hx4k`的冷格式正/负例2测试亦通过：80B格式、最后引用归还、持久缓存和8192B全区摘要仍匹配，未回归，但仍无像素消费。新Common等待已派独立只读调查，主会话未按未知谓词强置任何状态。

对同一run的原始64B控制包完整清点为11条RequestConnect，均tid325、目的等于S.SID，封套内`1000/0001/40/2`。仅VEF023→PinMem011有既有80B格式内容验证；其余10条各有明确`UNSUPPORTED`记录，未把请求发送或遍历继续当成功。逐包source/peer/raw和console行号保存在run内`topology-observed-proof.json`。

| Source | Peer | 本轮验收 |
|---|---|---|
| InfraBB `{0,2,1}` | VEF `{0,1,1}` | 明确拒绝 |
| InfraBB `{8,2,0}` | VEF `{8,1,0}` | 明确拒绝 |
| VEF `{0,2,2}` | PinMem `{0,1,0}` | 明确拒绝 |
| VEF `{0,2,3}` | PinMem `{0,1,1}` | 有限control/80B冷格式通过，无像素 |
| VEF `{8,2,0}` | PinMem `{8,1,0}` | 明确拒绝 |
| PinMem `{0,2,1}` | Scalar `{0,1,4}` | 明确拒绝 |
| PinMem `{0,2,2}` | ADF `{0,1,0}` | 明确拒绝 |
| PinMem `{6,2,0}` | DrawInfo `{6,1,0}` | 明确拒绝 |
| PinMem `{4,2,0}` | HDMI `{4,1,0}` | 明确拒绝 |
| PinMem `{1,3,0}` | OSDPIN `{1,3,0}` | 明确拒绝 |
| ADF `{5,2,0}` | HDMI `{5,1,0}` | 明确拒绝 |

这份清点只说明已知拓扑缺口，不足以直接判定`303d49c`谓词或唯一根因；必须继续核原等待和真实producer。

StillCa新字段采集首轮`run-wokbrxbh`失败：host测试/构建/选定cpio身份检查通过，清单含新menu-regs摘要`8aad45156c8557c37e74b8a0a35655a13842b5c83882e0d23aef9494cf8cc227`；在settle期完成4次screen dump后，下一QMP pmemsave发送报BrokenPipe，清理关闭VM。没有summary或StillCa字段，不作为完整动态验收。console SHA256=`91e94e39c3ce88f667d785d31e156c24338e6c7e97cfc554b8803f12a716d7e3`，未见Exception monitor；该观察不足以确定控制通道断开原因，亦未证是180秒限时或内存不足。失败见`stillca-capture-failure.json`，保留原数据，下一轮只将settle90改为30秒，更早获取诊断；不改固件逻辑或判据。

settle30重跑`run-v5hf37qm`完成并取得StillCa327字段：O=`7f64171a80`，匹配原run栈/vptr/mutex，initialized/initial_arrived/slot0/slot1/completion0/completion1全0，predicate0、atomic_snapshot0。这次采样缺初始通知，两slot状态均不要求mount completion；见`stillca-initial-native-proof.json`。Common325仍`303d49c←305e434`，没有借此次诊断改变任何固件字段。

新Common只读调查已完成：这是`303d400 await_i`的4任务完成token join，当前等待完成deque非空；合法producer是原pool成员返回后触发completion closure。四成员为音量3058eb0、音频功能305ac4c、提示音3060464、许可3062e3c，尚未动态匹配哪一项未返回。主会话独立核原指令并将既有queue stack采集扩到`SeqThreadPool*`，新实验已启动；不手造完成token、不凭Connect拒绝数断言根因。详见`common-boot-join.md`。

pool采集`run-gjwv9_0o`已完成：Pool0/321当前空闲；Pool1/322在volume0330 wrapper、Pool2/323在sound address033f、Pool3/324在capabilities0327。三条原等待栈及静态协议映射见`boot-worker-waits-native-proof.json`，不把Pool0空闲单独解释为许可成功。StillCa初始字段仍全0。主会话新增默认关闭`MENU_AUDIO_BOOT_CONFIG=1`接本地有状态audio/inputless能力缓存，完整host校验、guest export、free/lease、日志、构建和manifest已接线，动态实验已启动。sound owner未初始化时033f/0329明确拒绝，不回占位地址；真实sound backing已派独立只读调查，未与主会话重复实现。

首轮audio `run-vz1l2isu`整体失败并保留异常：host音频全部状态/能力/25表项/ABA测试及observer8测试通过；原tid322实际消费0330 wire8→level7/op4并读回，12B回复及原free0；原tid324实际消费0327/28B inputless能力缓存，原free0。复用本地协议`received`逐字段验过，组件证据见`audio-partial-failure-native-proof.json`，不是完整运行通过。tid323发033f时因sound owner未ready返回-1021，原Pool2随后assert/abort。由console原stack words独立还原`35aa4dc←34e5778←34ec204←34c73c4←3060a1c←34b9568`，不能将此调用当作可错误降级。

sound backing调查已完成：原SysSound为66368B、SHA256=`5d94c660c48afde364fbb936105abdaf5c35f8bf8fc0bfd6945cd12146f6824a`，可用独立物理区`41d000000/20000`（128KiB），phys64返回`81d000000`、CPU/bus offset`1d000000`。当前native已有14条reservation，加sound为15，ramfb可到16，超过16必须拒绝。已接native专用最终cmdline/DTB校验、frozen-source helper、生成资产白名单、选定cpio音源/helper身份、启动前真实加载/读回/元数据门控和终态QMP全区逐字节比对。`test_native_sound_region.py`5测试通过，含最终bootargs篡改的offline拒绝；下一轮真实声音backing动态实验已启动，结果未预判。

真实sound backing实验`run-ypsslyoq`完成：SYSTEM_SOUND_INIT_OK，原tid326消费033f地址、后续25x0329和25x032c均实际发出，四pool324..327均回到空闲栈。独立QMP131072B完整等于66368B原源+64704B零尾，全区SHA256=`d4d940aa686f53103b1baef800f60fc9cffd2d27cab36530bfbddca1afa2c918`，音源/helper选定镜像身份一致。完整slice/lease负例验收正在执行，不提前把请求数量当成功证明。详见`system-sound-native.md`。

本轮Common328已越过原token join，改停`34e5788←34ebddc←34c7404←305e47c`，最后原10B请求032a=`0d202a030a0001800700`，source81cf61c5。已派独立只读调查032a原consumer、状态及回复，主会话负责声音组件证据验收。StillCa330 initial_arrived0/slot states0，UI290仍等boot future，5张RGBA图仍透明黑。

声音完整验收已通过：native sound 2测试含源区/零尾/profile/helper/free/bootargs六种破坏均被拒绝；033f、25个kind、25次volume读回与原waiter释放都核对通过，正式`system-sound-native-proof.json`已归档。5个原描述size0按原请求保留，不冒充5份声音数据。保存DTB离线再次验证为15个reservation、sound profile仅1个；既有VEF-PinMem控制格式验证在同run也通过（Common现tid328）。scope仍为声音配置与内存，不是音频播放或相机启动。

用户补充允许Kuna加速反编译；已确认本机`/usr/bin/kuna`可用并将优先使用Kuna的偏好同步给正在调查032a的代理，关键分支仍以原始指令/字节复核。不重复已交付的逆向调查。

032a调查已收回（代理到turn limit交付，关键契约有明确原始地址）：这是AdfSystemSoundPath的全局route，relay取wire u8&7，原cache初始0，0→非零消费control127/argument0并改变音频寄存器bit0，非零→零idle反向控制，active则有额外deferred callback。主会话独立复核CPVA1ca6b2/67dd78/b6c1dc原Thumb指令；新增本地缓存及虚拟bit RMW/读回，明确不执行硬件MMIO、不实现活跃播放callback。原音量/per-kind表语义不变。ASan/UBSan下掩码、idle双向转换、重复nonzero、发送失败回滚、坏封套及完整原音频host回归均通过。详见`audio-path-032a.md`。

032a实际固件验收及当前项目回归已启动，`verify-native-audio-path.py`/`test_native_audio_path.py`准备逐字段/负例核原cold7控制与原waiter释放；尚未收到动态结果，不标为解除。后续0347/0330仅来自原条件分支的静态候选，必须看本轮实际请求，不预设下一等待。

`run-7t6lu6an`已取得032a状态消费证据：原328同pointer7fb1454a80/lease54请求及reply释放均0；cold mask7缓存读回7，control127/argument0消费1次，virtual bit从0写1并读回。完整sound背景+path逐字段/破坏cache/control/free回归正在跑。当前采样并未等待静态候选0347/0330，而进入`34e5788←34efa0c←34c8b84←305e554`；主会话核ELF34ef9b0构造SID912f0335/24B、selector3/4，已加有限被动记录并另派Kuna调查原owner与consumer。没有构造该端点回复。UI/StillCa仍等待，未验收主界面。

032a接线后项目约定回归再次完成：同步检查通过；pytest 244 passed、1 skipped、58 subtests passed（照约定排除缺Cryptodome两组）；observer8、实际cpio正/负例2、本地源码快照2均通过，语法和diff空白检查通过。此批回归不替代后续实际端点验证，未声称所有子系统均已测试。

032a完整内容验收/负例结果已领取：2测试通过，路由缓存、control127计数或原waiter释放任一被破坏均拒绝。正式`audio-path-native-proof.json`确认同run真实声音backing前提及cold7 virtual bit控制，明确hardware_mmio_executed=false、active_request_deferred_callback_verified=false、audio_output_verified=false、camera_startup_verified=false。该组件完成，不等于自然boot完成；当前仍在912f0335。

912f0335被动采集`run-uyajukb_`完成：实际Common328、source81cf61c5、24B原请求`030000000000000000000000000000000000000000000000`，即u32 selector3、其余20B全零。console SHA256=`c26204fa1cc194b14a39f5ade529a1d8edba909b75749bd4c2f67e589de30078`，见`service912f0335-request-native-proof.json`。已将真实bytes通知原契约调查代理，目前只观察未加回复，consumer语义仍未验证。

等待912f0335调查时，主会话独立推进InfraBB OUT1→VEF IN1尚未支持的连接：取回旧代理已交付契约，不重做整个未知项；定点核原216B/token55/dynamic CP SID helper和VEF producer、cold表，保存`infrabb-vef-static/CONTRACT.md`与可复现`extract-evidence.py`。原CP摘要、wrapper整section逐字节相等、10个有界证据窗口及错误身份拒绝测试通过。已明确SSYN版本02000000、producer close25后owner移交无额外share、InfraBB close25后release23/opt0，现有152B/双share引用模型不可直接套用。Kuna定点复核仍在执行，尚未将该边接进runtime或声称动态通过；音频review范围未被修改。

912f0335 Kuna调查已完成：DIG_LEVEL_INFRA selector3启用角度通知，下游20B selector3到90a3035b，原main保存enabled1/count30，24B回复result在+10；AP wrapper实际读request+10的旧零，故不能用AP返回0证明成功。主会话核关键原Thumb分支后新增默认关闭`MENU_DIG_LEVEL=virtual`，显式virtual mode2/inline控制consumer，实际保存订阅及30计数，没有样本就不发角度/错误事件；不假称原backup模式或CP线程已启动。完整边界见`digital-level-selector3.md`，host/动态验证已启动。

音频独立审查已领取：在所查接线/所有权/RAM边界内未发现其它可证问题；指出path verifier失败时可能保留旧成功JSON。现CLI捕获预期验证错误写false并非零退出，新增“先成功→破坏cache/control/free→CLI重跑→必须覆盖旧成功”回归；结果随DigitalLevel验证链领取。不能将此前原CLI的这一缺口隐藏。

主会话InfraBB静态补查完成：Kuna5个指定函数均无独立error，原bytes核实216B/token55/动态SID、VEF ordinal0/SSYN02000000和owner关闭移交。Kuna把0061003c误渲染为字符串`tingData`的类型恢复错误已记录，协议仍以原指令为准；10个原窗口与身份断言可复现。Task对应的是实现前契约闭合，连接runtime仍未接入，不能标该边完成。

DigitalLevel实验`run-dvpe50ts`完成：Common328的selector3被virtual owner消费，通知开关1/countdown30持久保存；样本valid0、原CP任务0、事件0。原独立回复7fb0514ec0/lease1正常入队、同sender328 waiter free0。ASan/UBSan host通过，observer9测试通过；音频stale proof CLI覆盖回归2测试通过。订阅5破坏负例及原sound/route/format同run回归另行运行。

本轮Common328继续到`3552ea4←34d3794←305e780`，新的只读调查负责该等待；主会话同时直接推进Pool0/324的新BB 0119（28B实际raw已捕获）。经原classifier→内部25→rawc4d2c可确认它是SendVDF_SetPanelReverse，发2001/0101到9059000e，与音频无关，不能把日志标签当owner语义。VDF display/device consumer已定位并在Kuna定点恢复。StillCa330 initial_arrived仍0，5张RGBA图仍透明黑；没有预造新回复。

DigitalLevel完整验收已完成：2测试含5种状态/scope/free/profile破坏及旧success覆盖回归通过；正式`digital-level-native-proof.json`已归档，明确virtual模式来源、无原CP/原backup模式证明/无sensor ready/无事件。相同run的sound/route及80B控制格式复核亦通过。

0119主会话继续核到原VDF RTTI与consumer：CPVA6c90ba识别2001/0101，6c90e8包装内部f02e；DevPanelCmdSetPanelReverse原RTTI/vtable指向CPVA1fb630、6db63a、6db824。CPVA6db93a经Accessor+444实际保存反转属性（getter/setter对应CP raw5dbfc4附近），原PanelEvfInfraRvsCall还会走外部控制27d0728；这些副作用不能只写成功status代替。原rawbf664对0119专门将00590000成功去域成0，再构造1119/12/8001，不能套0165的590000回复。consumer条件和错误仍在Kuna恢复，尚未接入runtime。

0119 relay Kuna结果已领取、无function error，结合原RTTI/Thumb核对确认当前即时h1/v1/osd0/timing0。主会话实现默认关闭`MENU_PANEL_REVERSE=virtual`严格观察子集，将20B internal输入消费为独立reverse属性与control=2*h+v字节读回，回复裸0；原设备时序/队列/027d0728物理驱动和像素翻转均不在此模型范围，日志显式hardware_driver_executed0/pixels_flipped0。完整边界见`panel-reverse-0119.md`。Sanitizer及虚拟配置动态验收已启动，不提前写完成；Common另一处等待仍由独立代理只读调查。

0119 device Kuna4函数现已完成且无function error，确认原路径有VFC计数/device phase/buffer条件，当前模型不声称覆盖其时序。进一步原字节核查更正：Accessor+444复制16B，但只证前三u32明确赋为{0,h,v}，第四word不能断言原始为0；模型尾word0属于显式virtual初始化。已同步报告及注释，不改既定虚拟控制语义。

新DigitalLevel模型的OSAL allocation已移到lease mutex之外，沿用已有音频/VDF“分配可等旧free”的锁策略，避免内存池等待时阻断原receiver释放。原Sanitizer/所有权host测试重新通过；该小改动晚于run-dvpe50ts，其动态证据仍按当轮源码归档解释，不把新版代码追溯算入旧run。

Common3552ea4调查已交付：原CP DMM get_unit_size(unit50b58,chip1)，远端9061003c/40B/op18，结果用于main_image_unit_size(17cd)。原DmmCfg96a0 unit→firstextentf0，576c extent size09600000。主会话实算原源SHA/FNV及原记录，并独立核appFw305e7a0..7ec和getter2883750，确认B+7ecfbf0由原代码写size，不是指针字段。

已新增默认关闭`MENU_DMM_UNIT_CONFIG=1`，从原配置初始化独立单unit只读lookup，原40B回复/lease/free及字段日志完整接线；不分配150MiB、不修改AP模型属性、不混入63a或404服务。选定cpio/readmem/config身份关联，诊断只读main_image_unit_size。host Sanitizer及含panelReverse的新组合QEMU已启动；原请求raw、原free、属性值和下一个等待需本轮逐项验收。详见`dmm-unit-size-50b58.md`，未提前标为通过。

0119配置动态`run-f6pnqj0o`完成：原worker324消费h1/v1/osd0，virtual properties与control3读回，独立裸0回复7f8297ec00/lease3及原waiter free0；该worker已回空闲，四pool当前均空闲。Common328仍等DMM unit size。0119五种破坏负例和完整字段验收另行启动，日志/报告保持hardware_driver_executed0、pixels_flipped0，没有原VFC/driver翻转成功证明。

DMM实验`run-hobha2ig`完成：实际40B原op18/unit50b58、配置firstextentf0/size09600000、独立reply7fb67cac40/lease1、同原Common328 waiter free0。readmem只读原AP property B+7ecfbf0得到00 00 60 09，证明原代码写150MiB配置值；完整破坏负例已另启动。没有分配图像内存。

本轮首次取得自然路径可见错误UI：308(scr0039_boot)→12d(scr0099_0001)→322(dlg_dbl021_base)，实际截图是日文“存储卡无法正确读取，请重新插卡”。UI290回到1795708消息循环，原MENU ON/OFF已消费，但没有menu/shooting转屏。图像原样保存为`boot-card-error-visible.png`，内容/摘要/限制见`visible-card-error-native.md/.json`。截图非透明黑这一变化已基于实际文字与原screen链确认，不靠14色计数。

Common328新栈310194c←34f4f74←3535b04←3548cbc←34d1774←305eb88，处在原sequence_boot::run的305e9ec future-completion调用之后；不再等旧bootfuture，run_i亦已返回。StillCa330 initial_arrived0/slot states0但completion0=1，不能外推挂载成功。独立代理调查实际存储错误来源，主会话核原收尾future/CameraBackground依赖，已补该原线程栈和8102021f请求被动捕获；没有直接写promise或跳过错误页。

0119面板虚拟配置完整验收结果已领取：2测试含5种属性/control/scope/status/free破坏全部通过，正式`panel-reverse-native-proof.json`归档。它只证明virtual panel config消费；hardware_driver_executed、original_device_phase_verified、original_vfc_scheduling_verified、pixels_flipped均false，不会据此升级为真实像素翻转。

DMM unit50b58完整验收已领取：2测试含原property、reply bytes、config identity、原free四种破坏通过；实际40B查询/回包、unit→extent查表、原Common328释放及原AP main_image_unit_size157286400读回均已核实，正式`dmm-unit-size-native-proof.json`归档。allocated_bytes0；未单独探针原model publication回调，相关verified字段明确false。相同run的panel与订阅证明也通过，未将这项配置成功等同成像内存或拍摄完成。

post-boot被动采集`run-coojlkn6`完成：原Common328发8102021f/source80020002/20B `1000000020000000000000000000000000000000`；原CameraBackground本轮tid287，接收该请求后当前等动态queue810261c7，libObj原栈eda8c←ee460←ee82c。主会话核libObj ed9c4/ee434原字节：下一层向90030001发type0/cmd3007/24B，而非20B未送达。已加更窄原CP请求捕获并单独调查3007consumer，绝不按AP可接受F001/F002就假造该结果。细节见`post-boot-common-static/DEPENDENCY.md`，与媒体错误调查分开推进。

用户质疑是否启动触发/参数本身导致SD错误，该假设未排除。主会话核原bootin帮助确认dmode3=APP/default、normal app默认；但当前派生IMDB的10项SKIP确实包含libInfraMediaPwrMgr，先前“只略过USB”的描述过窄，已纠正CLI help。媒体调查已恢复为初始化/实际caution链核查，不能从截图直接假设Fsys mount失败。

已独立核39e/group/selector等getter数据地址并加只读诊断；启动相同已构建镜像取消MENU的单变量对照，不盲扫boot type。原UPM boot-factor consumer由主会话Kuna定点核查；媒体电源initializer ABI与原caution依赖由原只读代理继续，不未证就启用模块。详见`startup-caution-controls.md`，结果均待返回。

原CP请求采集`run-cxj7qh2s`已完成：本轮CameraBackground286发90030001/source810261c7/24B raw000007300000000000000000000000000000000000000000。consumer调查已交付：3007是原CameraBackGround状态转换，只有原current6/7走捷径，其余依赖实际module转换；成功f000，不存在已证3007的f001/f002 producer。主会话不加空替代reply，保留post-boot收尾阻塞，详见`post-boot-common-static/CP-3007.md`。本轮镜像/observer摘要已记录为无MENU实验基线，等待对照返回。

无MENU对照`run-sjspmvwk`已完成：compare脚本核原cpio/observer/启动选项和power record相同，仅autoMENU取消，截图RGBA逐字节一致。实际group311/selectedb1d/selector1，b1c/b1d输入1；追加调查证实这些是语言DST可用性，不能作为SD错误producer。原writer2d8fecc经35abb64/35abb70读取Backup010d008f/0090，35aa6bc原断言名为backup_get_language_dst，byte1→model1、byte2→model0。先前关联已明确撤回，当前追踪真正dialog ID与创建调用链；主会话新增/proc/self/mem只读有界stack采集，坏frame/不写/errno恢复host测试随新run验证。

媒体电源追加调查已完成：native资产/inventory和导出中无libInfraMediaPwrMgr及其provider，原IMDB仅记录期望名字；原im.elf caller证明void(void)初始化ABI，但无实际实现可安全恢复。没有直接解mask、编占位库或设media ready。原UPM boot记录仍独立核查，不能预先判定其正确或判定SD故障。

原UPM Kuna3符号已完成、无function error；主会话objdump核原.text偏移3cd8/4188：setup确实读0051004a/128B，复制record+4后的字段；default将相同mode字段设2。mode2有原默认依据，未找到该函数直接SD/Fsys错误分支；额外0051000f可能覆盖复制值，type/eecap/bis仍未证明与真机cold boot一致。详见`startup-caution-controls/UPM-RECORD.md`，不盲改boot type，也不因这项静态一致性把启动环境全部标正确。

无MENU控制完整验证已通过：2测试/4种混入变量负例均通过，镜像/observer/boot type/实际key记录任一不同必须拒绝。正式`startup-menu-comparison-proof.json`已归档；相同RGBA错误图像在无MENU时重现，只排除自动MENU必要触发，不证明SD/mount错误或boot record全部正确。

真实dialog创建栈`run-yquhg8jh`已采到1d56688←1d5677c←1e4bb44←1e773f8←1e78c70←1e795ec←179a314：是UI异步构造而非producer直接调用。追加只读调查定位P=dlt01_presenter、vptr59590b8，P+2ac8为真实资源getter，最终selector由原1ab9068写进view-string.param+30。主会话核原ABI及父构造保存x19=P，新增纯/proc读P/getter/最终text参数；没有改getter vtable、没有调用资源getter或写UI。host fixture不写/坏帧/errno及资源字段验证随新run执行，动态selector待返回。详见`dialog-resource-trace.md`。

同run group0 current O=7f84170760、vptr5b30e10；主会话独立64位RTTI解析为sequence_boot，O+68=0/+74=0/+80=1b，与原postboot分支相符，但没有从这几个裸值推断错误启动或SD原因。UPM mode2来源与其它实验loader字段仍按前述有限结论保留。

原dialog真实资源捕获`run-1_77s6pg`完成：P7f55c80190，构造时getter7f4e10ced0/vptr59128c0/method1882dc8，RTTI原链解析为caution::caution_module；实际view-string.param+30=0200a73b。当前RGBA与原错误截图逐字节相同，且没有getter hook/状态写入。正式`dialog-text-resource-native-proof.json`保存scope及未证因果。

主会话核原getter代码：u16 active module index位于getter接口+10，记录表58f03a8/stridea0按predicate选资源；静态仅匹配候选233(screen321/pred187f89c)和262(screen322/pred187f8dc)。不能只按文字或screen推断active index。新的构造时只读index采集与7e80dd0/7e80f50实际model输入采集已启动；独立代理追候选262原predicate/property自然writer，主会话不重复其未知项、不清错误或伪ready。

活动模块动态`run-0xqk0apm`已消歧：index_known1/module_index262，selector0200a73b；原getter28787f0数据B+7e80dd0=u32 2。正式原资源链验证/坏index/model/resource/method负例及项目回归已启动。该index是原caution模块内部索引，不等于外部错误码或mount errno；独立调查已收到actual262/值2，只追其自然writer，不再扩扫语言或233候选。没有直接清值2来遮住提示。

实际dialog链验证已通过：2测试/4种破坏负例，正式`dialog-resource-chain-proof.json`归档，保持natural writer/FS错误因果未证字段false。项目同步检查、pytest244 passed/1 skipped/58 subtests passed通过，约定排除缺Cryptodome两组。另补原appFw选定镜像身份强校验及第五负例，正在执行；不是改变观测到的模块/资源/值，也不直接清除错误模型。

dialog来源身份补验2测试/第五负例已通过：要求选定cpio原appFw SHA及unchanged=true，坏身份不能保留旧success。主会话并行补独立原Fsys文件后端的应用mount flags测试：保持首进程flags0实际写入，第二进程以相机参数100h重挂原文件并读回，增加marker和选定helper/template镜像身份；此独占测试不启动camera app，不将其成功等同当前dialog治愈。动态及fsck/完整镜像验证正在执行。

模型writer调查已完成：当前262自身必要条件是media_mount_state_slot1(ed1)=2且media_error_slot1(edd)=1。主会话独立读原metadata及完整predicate确认；次getter28789d0虽也用于233，仍是262第二必要输入。原exec_mount337ac38尾段写阶段2（非成功判据），依据FP+94写error1；原完成事件01000146同样不表示成功。

主会话闭合持久错误保存：337af78取Mount模型错误，25a9844→25a96f8写media_mount_error_slot1/slot2(1cf3/1cf4)，原数据7ee5fa0/7ee5fb8。新增纯观察原00b08170 sync RPC入口/返回及这两个值的只读采集，原服务不替换；用于区分本地缺注册1d与真实service buffer+c失败。原MediaMount provider/MCmn错误转换亦在Kuna定点恢复。详见`media-mount-source-static/MODELS-AND-WRITER.md`，实际失败值仍待返回，不直接判定Fsys或启动模式原因。

独立Fsys相机参数基础测试`run-z51ilinf`通过：原首进程flags0写4096B，原第二进程flags100h重挂读回/卸载全0，QMP4MiB FNV41613544a04795ca与guest相同，fsck.fat -n RC0、主机FAT解析及原文件逐字节通过。镜像SHA仍d2490baa…、文件SHA c5d2097f…，不改写旧输出。正式`fsys-camera-flags-proof.json`归档；这是direct /dev/mmca文件后端，未接通APP RM/nondev/rm2、未消当前dialog。生成helper/template选定身份已校验；六个原provider库单独selected-byte检查是此后新增，不追溯算进本轮。

首轮自然Mount错误采集`run-vzk9iksr`：持久media_mount_error_slot1=2a、slot2=0，state/error=2/1。原tid332的00b08170 GetInfo/Mount初始同步都返回0且buffer+c=0；主会话核35505e0/3599f3c/355014c确认这只是接受阶段，之后还会等异步完成消息。故不作“Mount成功但模型异常”判断，也不宣称已采最终service_error。原676B provider函数在mcmn_drv_open前会向80cf016d发228B RM查询，可能先失败。现补异步send/free及原MWF SendAndRecv透明观察，ASan/UBSan参数/数据/返回/errno/短帧/默认关闭fixture1测试通过；新run同时补原provider二库选定镜像摘要比对，未替换服务。

后续静态结果已交付并由主会话核原指令：80cf016d provider是libInfraMediaConfig，非读取卡状态的RM；原16×110h配置表及Backup建表提供设备名/类型/valid，valid不是插卡或上电。原IMDB启用、run-vzk9iksr有该module B/E Ii日志，仍未等于实际callback注册成功。MWF transport与业务结果+14分开，原provider错误表33/15项多种原因都归ER_OTHER7fffffff→模型2a。原MediaMount ParseMessage的最终Header类型4已核，旧筛选1/2不足、已补4并重过ASan/UBSan；旧“command”实为消息类型，后续日志改api/type。此前RM_QUERY/present_byte标签按配置查询/配置valid解释，新源已改名并补原Config/MWF选定cpio库身份，不追溯算进旧run。详见`media-mount-source-static/CONFIG-QUERY.md`，未据此发card-ready或启用全局dummy进APP。

验证补验已收齐：Fsys相机参数2测试（缺flag/镜像末字节损坏及旧success覆盖）通过；dialog2必要输入2/1及原身份六项破坏、失败覆盖2测试通过，正式proof更新归档。观察源码11测试、选定cpio身份2、源码冻结2、同步检查、pytest244/1skip/58subtests及diff-check通过。它们不替代native全量构建：新增MWF观察wrapper曾用精简C环境未定义的RTLD_NEXT，native编译在guest启动前失败（bc8af3c3e原日志保留），已改既有(void*)-1写法，bd76ccb44重新真实构建/采集；未把失败轮说成VM结果。MediaCommon的/nondev/rm*实际driver分派作为下一独立未知项交代理只读调查，主会话继续实际返回核查。

修复后的`run-k3d13p5x`已完成：原Config查询transport/business0、valid1、df10、/nondev/rm2、type0/连接2；原provider276最终api1000/type4 status7fffffff，callback端点1cfe114、动态wait queue1cfe115、同指针/40B内容被原waiter332消费并进free，随后原model1cf3=2a。free返回当轮未记录，不报free成功；clone source=a5a5a5a5未当身份。原Config/MWF/Mount/Common四库选定cpio摘要及实际dialog图完整RGBA由复用验证器核通过。`media-mount-final-capture.json`归档，配置查询缺失已排除，更下层实际错误仍待抓，不证明Fsys失败或全部启动参数正确。

RM driver分派调查已交付：/nondev/rm*两种全局表都进rm_open/rm_mount，dummy仍依赖cmd9/2及80d9016e内核服务，且全局dummy影响内部nflash；不是设置69=0就能接通。已加mcmn_drv_open透明原调用及RM原同步字节捕获（不加服务、不改返回），Open函数在加载线程缓存避免IPC线程dlsym。相关原源片段ASan/UBSan1测试通过，b07937126真实构建/新采集中；独立代理继续补两条协议精确规范。详见`media-mount-source-static/RM-OPEN.md`。

`run-wuyujort`取得更下层原值：mcmn_drv_open('/nondev/rm2',0)80000004/errno0。原type4完成及waiter free返回0，原caller3599fd8，模型仍2a。后续`run-hqxkxsfb`抓stat80d9016e原rc0和word0/1全0；主会话核原sender394d0，39500因word1=0直接跳39618返回80000004，发生在valloc/snd之前。原Root队列判断未伪造、未加载带GPIO的mcmn KO。原sender实际用异步snd+私有replyQ阻塞等待，cmd9为136B配置、cmd2为32B类型查询，不能称为同步SND接口。

用户新增快门自检/首次语言假设已拆两项只读调查，主会话做同cpio/observer无输入对照与正常ENTER1ac按下/释放。当前确实走过语言页，但未证明已确认首次设置；卡错误有独立预检查链也不能排除后继自检。既有InfraInput注入现记录manifest并观察App队列消费，无输入/单变量MENU验证器拒绝混入CSV确认。新配对实验、七项输入/身份负例及旧MENU真实配对回归待返回，详见`firstboot-checks-in-progress.md`。队列传输自检源已补入独占helper但尚未运行，不作服务已建立证明。

用户首设假设有实际条件支持：`run-k3xyvyuz` date_time_set_status0/clock_force_settled1，原强制首设分支成立；原32B callback在实际卡错误绘制后送Confirm1ac，原App队列ON/OFF均消费，但最终RGBA仍同卡错误。未取得UIBIZ/handler接受证据，未称Confirm无效。诊断576B/48项status0且全部字节与原初始化模板48b28f8一致，严格不当快门通过；`firstboot-confirm-consumed-proof.json`归档。机械CP初始化/等待虽有静态入口，尚未闭合到AP主界面硬门槛；0返回含超时/fatal分支，不能误判。

真实RM用户consumer注册契约已静态核：原reg_msg_queue_cb可注册80d9，stat+4是有效异步callback数；需要16B stat，非广播请求由consumer free。独占helper按原reg/valloc/snd/callback/free/unreg及跨进程idle做32B内部传输自检，未运行相机、不生成卡ready。已原ABI临时交叉编译通过，b8eadb06d实际验证结果待取；该临时编译先因readelf中文输出筛选返回1，改LC_ALL=C后完整命令通过，不隐藏失败。原UI确认保护ASan/UBSan及fixture11测试通过（先因新增状态/错误文本未同步失败，已适配再通过）。

完整验证链首轮中，native真实内容检查及四种负例（篡改RAM、状态、移除free、移除profile）通过，原full-system回归随后失败。原因是适配参数`native`被原函数中同名的“原waiter free记录”局部变量覆盖，导致旧格式误读native文件名。当前共享源码已将局部变量改名`native_free`；保留这项现有修正并重新运行两种元数据入口的完整回归，不将首轮聚合失败隐藏。

该次重验现已通过：native正/负例2项、原格式验证器4项、原连接验证器4项均成功。完整组件结果保存为`pin-format-native-proof.json`，明确`verification_scope=native-component`、`whole_run_success_verified=false`、`camera_startup_verified=false`。这一条冷态控制/格式路径完成，不外推其它连接边或图像链。此任务在用户要求本地复制之前启动；之后的源码读取和验证均改用native本地副本。
