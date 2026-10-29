# 原固件像素输入合同：几何/属性字段已定位，完整帧仍未闭合

> **后续主会话分支归属复核**：下文 A `0x34f6fd0` 是通用 JPEG 服务入口，
> 不是已经证实的“快门 still 编码入口”。本次新增原指令核查确认 wrapper
> `0x34c8018` 在 `0x34c8040` 调它；裁剪序列 `0x30a9858` 在 `0x30a99f0/9ac4/9b9c`
> 调 wrapper，视频提帧序列 `0x3411324` 在 `0x34120b8/216c/2214` 调 wrapper。
> 原 ELF VA `0x4c1f1c8` 字符串是 `sequence_edit_trimming_trim::mpr_record_trimming_still()`，
> `0x4c47338` 为 `sequence_record_still_from_movie_content::run()`。
> 裁剪分配函数 `0x30a83b0`：`0x30a83c0` 查对象+`0x11c` 句柄，
> `0x30a83d4/e0` 写 type=`0x62f`/option=1，`0x30a83ec` 调 `0x34d35e8`，
> `0x30a83f0..8400` 将24B结果存对象+`0x118`。
> **只闭合裁剪工作缓冲的描述符来源；像素写入者及快门实际输入仍未闭合**，
> 不可把该分配类型或当前 UVC/VDT type=`0x643` 当作 CMOS still 合同。
> 下一步仅在自然全按时观察 `appFw+0x34f6fd0` 的调用者/输入，未命中要保留阴性结果；
> 不强行发送 `2000:0004` 使它冒充正常快门路径。

原请求的有界观察现可显式启用 `A7C2_JPEG_REQUEST_TRACE=1`（自然启动窗口），
或在 `run-menu-probe.sh` profile 中启用 `MENU_JPEG_REQUEST_TRACE=1`。
该探针只记录前8次入口的调用者、上一帧LR、输入/输出指针及输入0x90B原字节，
复现原件前16B指令后继续，不写输入对象、输出对象或业务门禁。
`JPEG_REQUEST`/`JPEG_INPUT` 不表示编码成功；没有命中也不能单凭日志判定编码器故障。
已完成宿主 ASan/UBSan 的输入不变/errno/次数上限/坏指针检查，以及原件prologue匹配
和AArch64编译；自然全按下的实际命中尚待验证。

### 后续：真实 MPR 写盘入口与空兼容接口必须分开

新核原件 `libmpr.so` SHA-256 为
`4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9`。
下列地址均为 **libmpr.so 自身 ELF VA**，不是 appFw VA 或 K raw。

- `MprIf::EncodeStill/WriteStill/FlushWriteStill` 在 `0x2c8cd8..2c8d0c` 的相应导出实现
  只有 `mov w0,0; ret`。符号名存在和返回0不能作为编码或写盘证据，不调用它们拼出假链。
- 真正 `mpr::RecordStill(recordStillInParam const&, recordStillOutParam*)` 在 `0xeb260`，
  长`0x3f4`。`0xeb2e0` 调 `_check_error`；`0xeb308..310` 按内部对象+`0xc` 选分支；
  普通分支 `0xeb618..620` 将原输入与内部记录对象传给 `_record_still`（导出`0xe85a0`）。
  另一分支属于 trimming，不能合并当普通拍照。
- 下游异步 writer 的确切 sink 已核：
  `_write_async_and_sidb_update`（`0xf183c`，长`0xa64`）在 `0xf20e8` 置 x0=x20，
  `0xf20ec` 调 `Fsys_WriteDirectFileAsyncV2@plt`（`0x82010`）。
- 原 `libInfraFsys.so` 的 `Fsys_WriteDirectFileAsyncV2` 在`0x32eac`，使用 x0 的请求对象；
  `0x32f9c..32fb8` 向 `fsysDepAsync_DriveQueueRequest` 传递 executor=`0x2f7e4`、
  请求尺寸`0x508`。这不是普通 `Fsys_Write(handle, data, count)` ABI。

以上只闭合静态 API/分支/下游异步请求位置；普通分支到 sink 的完整运行链、
真实编码载荷、请求内部 buffer/lease、回调及写完/封口状态仍须核查。
已有文件后端能写数据库/XML不等于照片已编码，也不以直接调用这些API替代正常快门。
下一项定点分析只读这两个 writer/executor，不重扫全库；反编译中条件表达式仍以原指令为准。

`verify-mpr-writer.py` 重新读取并校验 `libmpr.so`/`libInfraFsys.so` 原字节：
MPR 端的`0x508`请求、callback/cookie位点、`Fsys_WriteDirectFileAsyncV2`调用及
`fsys_callbackfunc`→`write_finished`队列通过；Fsys executor 端的请求长度、callback
字段和 DriveQueueRequest 入口也通过。它同时确认 MprIf 的兼容接口是 no-op。
这是静态调用合同，不是运行写卡证据，脚本末尾明确输出 `CAPTURE_VERIFIED false`。

为下一次正常快门场景增加了默认关闭的 `A7C2_FSYS_ASYNC_OBSERVE=1` 旁路观察：
它要求 `MENU_RM_FILE=1`，在原 `Fsys_WriteDirectFileAsyncV2` 入口透传后，
只记录请求路径、area数量、callback/cookie、请求整体 FNV-1a64 和返回码；
不改 `0x508` 请求、不重新提交、不替代原写入。`test_fsys_async_observer.py`
验证 profile 门禁；后续修复关闭时仍复制请求的副作用，改为显式开启后最多32次
`/proc/self/mem`精确读取（短读/不可读不记录），调用前恢复原errno，返回后只分析副本。
新增编译执行的ASan/UBSan测试验证原指针/返回码/errno透传、关闭时零读、
原函数使请求失效后的副本生命周期、坏指针/跨页短读及次数上限。
更新代码按原AArch64 libc ABI独立链接通过；相关RC/debug/JPEG/async回归共44项通过。
尚未把 GTK 首设失败场景计为运行命中，故尚无 `FSYS_ASYNC_WRITE` 运行记录。

状态：**请求、YC元数据与JPEG输入的主要几何/属性字段已定位，并闭合一条真实容量检查；仍不足以构造能被正确解释的真实像素帧。**
缺的主要是分量字节/位顺序、plane 组织、DataPlacement 的具名枚举与转换输出布局，以及源帧 generation/lease。**禁止**据此实现“固定 ready + 任意像素”。

本文由独立只读调查交付，主会话已复核其关键原字节（见 `verify.py`，实际运行通过）：`av-cam.bin` 的容量公式取 `YcCompress`（`ldrb w9,[x19,#0x2f]`）、`DataSite` 转换表 `0x30b400={0,0,1,2,2,3}`、具名 codec 枚举表 `0x32f8c0/0x32f8e0` 及 `CHROMA_420/422/444`、`BIT_DEPTH_8/10` 字符串。主会话未运行固件、未产生任何像素帧。


**结论：已经定位请求、YC 元数据和 JPEG 输入的主要几何/属性字段，并闭合一条实际长度检查；仍不足以构造能被正确解释的真实像素帧。** 缺的主要是分量的字节/位顺序、plane 组织、DataPlacement 的具名枚举与转换输出布局，以及源帧 generation/lease。不得据此实现“固定 ready + 任意像素”。

本轮新增最重要的辨别是：JPEG 直通判据 `G+c4==2` 指由 **DataContent** 转来的值；JPEG `Q+20` 指由 **DataSite** 转来的属性。它们都不能凭数值当作 YC422/RGB/NV12。找到了具名 8/10 位、420/422/444 表，但属于另一 codec 参数域，尚未与本 YC 字段绑定。

## 1. 范围、身份和地址纪律

范围授权见 [scope.md](scope.md)。只做离线静态读取与本目录证据写出，没有运行 QEMU/VM、GDB、编译、测试或设备/网络访问。没有读 full/private 或真实 setting；没有读其他新代理的报告。文档结构使用 docs-generator 的普通逆向模板，flavor=null。

以下 SHA 均由本轮直接计算，随后每次提取窗口再核完整文件 SHA：

| 代号 | menu-root 下原路径 | 字节数 | SHA-256 |
|---|---|---:|---|
| A/AP | usr/lib/appFw.so | 99960744 | 2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b |
| C/CP | cp/cpapp-b.bin | 18090880 | f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428 |
| K | system/av-cam.bin | 13797088 | 90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096 |
| D | usr/lib/dataflowInfraFramework.so | 306496 | 620e04a9cd51e65bd190ed1d5459b7235ff5a4109bc6498df342972621991d47 |

根路径为 `final/a7c2-re/report/2026-10-17-qemu-native-camera/runtime/analysis/menu-root/`。CP 实际在 `cp/`，不是 usr/lib；首先在指定 usr/lib 下 find 未命中，再限于同一 menu-root 定位，未扩大到私有资产。

- A 地址为 ELF VA。第二 PT_LOAD 为 VA `51b7718` / fileoff `51a7718`，不能统一 VA=fileoff；本轮 A 代码窗口均处第一段。probe 用 ELF 段换算。
- K 地址全部为 **raw 文件偏移**；真实 KVA=`ffffffc001000000+raw`。
- C 地址若使用须为 CPVA=raw+108000；本轮 C 仅摘要、字符串和 SID 字面量查询，没有借 ARM 解码冒充 Thumb。
- D 同样用 ELF 段换算。对象偏移、序列化 payload 偏移和消息偏移是三个坐标系。
- corpus 只用于找函数：`FUN_035f6fd0` 对应 A VA `34f6fd0`，不能照抄 FUN 数字。本报告关键结论均对应本轮原字节窗口。

E-imports：A/D 均 EM_AARCH64；A 有 947 个 undefined dynsym、3 个 defined dynsym，D 为 28/1824。A 的字段 setter 是 PLT 导入，原 `.rela.plt` 给出具名符号；D 导出这些具名实现。DT_NEEDED、PT_LOAD 与完整数量保存在 [assets-and-imports.json](assets-and-imports.json)，字段 PLT 对应关系在 [AP-plt-field-symbols.json](AP-plt-field-symbols.json)，D 符号在 [D-field-symbols.json](D-field-symbols.json)。K/C 为 flat image，无 ELF 导入表，未假定没有外部接口。

## 2. 继承的结论与本轮调查边界

已读用户指定的 IMAGING-CHAIN-CONTRACT（含第8节及其后像素相关补充）、IMAGING-SUBSET、MEDIA-PIPELINE、control-lens-exposure-frontiers，以及两个指定 scratch REPORT。既有结论沿用：DMM 分配请求/响应；ValidState 不是 ready；752/753 属于 K 的 Sdt 链；现模型只证控制/所有权，不证像素；当前 CMOS source 是测试图。

不重做 EE、快门或存储链。本轮新增核实请求赋值、具名 setter 的原布局、K 的描述符解析/长度检查、JPEG 的属性搬运、以及几个确切的枚举域。没有闭合完整 DMA 消费/正常归还；既有报告里的 JPEG DMA 对齐仅按原报告注明，未把它当本轮新的完整验证。

## 3. 68B resize 请求 R：没有独立的 stride/plane 表

发送者 A `34f6324`，R 基址是 FP+1c8；原赋值窗口 A `34f6954/1c`、`34f6970/230`。所有偏移为十六进制。

| R 偏移 | 类型 | 原赋值/用途 |
|---|---|---|
| 00/02/04 | u16×3 | 2000 / 0003 / 0044 |
| 06 | u16 | 0 |
| 08 | u16 | 7，类型域的具名语义未验证 |
| 0a/0c/0e/10/12 | u16×5 | 本地回复 handle 的低16位重复填入；不命名为帧序号 |
| 14 | u8 | `in+bc==6` 的布尔值 |
| 15..17 | bytes | 0 |
| 18/1c/20 | u32×3 | 源描述符 SDS：`in+18/+1c/+2c`，type/handle/offset |
| 24/25 | u8×2 | `(u64[in+b0]!=0)` 及其逻辑反值；裁剪参数存在性控制 |
| 26/27 | u8×2 | 0 |
| 28/2a/2c/2e | u16×4 | `in+b0/b2/b4/b6` 的矩形四值；本轮未凭位置指定全部坐标名称 |
| 30 | u8 | 旋转转换：0→0，+90/−270→1，±180→2，−90/+270→3；其它→0 |
| 31 | u8 | `in+c0!=0` 的布尔值，具体翻转轴未验证 |
| 32 | u8 | 0 |
| 33/34 | u8×2 | 80/80，数值语义未验证 |
| 35..37 | bytes | 0 |
| 38/3c/40 | u32×3 | 目标描述符 SDS：`in+70/+74/+84` |

K 处理的内部消息比 R 多20h头：源为内部+38/+3c/+40，目标为+58/+5c/+60。K `47db0` 从+38/+3c/+40抽取源，K `48048..60` 建目标 SDS；K `48224..78` 读源属性、解析**像素** SDS 后存 API+1a8；K `48048..a8` 对目标存 API+1b0。

因此不能把 `R+20` 或 `R+40` 直接当像素 PA/总长度。它们先定位元数据；元数据里的 UnitType/Handle/DataOffset 再定位图像存储。宽、高、位深不直接作为 R 的独立字段发送，来自下节 YC entry。

## 4. YC 序列化结构：真正的宽高、属性和状态偏移

### 4.1 三种结构必须区分

记 `I` 为 ImageSizeInfo 的**序列化 payload 起点**；`Y` 为 YcStateInfo payload；`B` 为 K 解码后的 ImageSizeInfo 临时结构。

D `363b8` 构造 ImageSize 对象，其 payload 位于对象+20、长48h。D `36410` 的 SetData_All 复制48h；D `34b64..74` 根据 entry data offset 把对象指针/长度复制到序列化 blob。D `37bbc..bec` 则将 Y payload 置于对象+1c、长8。不能把“对象+4e”写成“payload+4e”。

K `31d8c` 按 marker `SSYC` 查结构、按 cate 0 查 entry；K `31eb8..31f98` 将 I 字段解码到 B。K `31f9c` 按 cate 1 读取 Y，`320c8`复制前7字节。本轮未证 K 在此读取 Y+7。

entry header marker 为 `ETRY`（D `3ae90` 与 K `3f1bbf`）；K `3171c` 从主头+c取 entry 数，从主头+10取首 entry offset，再比较 E+4 cate、用 E+14 链到下一项。K `3183c` 用 `blob+u32[E+c]` 算 payload。E+10是 payload 容量；D `34a48` 把该容量向上取32B整。**这只是元数据 entry 容量对齐，不是图像行 stride。**

### 4.2 ImageSizeInfo 字段

类型名称来自原 D dynsym、setter 原 store 和 A PLT relocation；B 对应来自 K `31eb8`。`—`表示所核 B decoder 未复制，不表示全固件不读取。

| I 偏移 | 类型/名称 | D setter VA → 对象偏移 | K B 偏移 |
|---|---|---|---|
| 00 | u32 UnitType | 36444 → +20 | 04 |
| 04 | u32 UnitHandle | 36458 → +24 | 08 |
| 08 | u64 UnitAddressPhy64 | 3646c → +28 | — |
| 10 | u64 UnitSize | 36480 → +30 | — |
| 18 | u32 UnitDataOffset | 36494 → +38 | 0c |
| 1c | u8 ImageAttach | 36430 → +3c | 00 |
| 1d | u8 DataSite | 365e8 → +3d | 2c |
| 1e | u8 Aspect | 36610 → +3e | 2e |
| 1f | u8 IibNumber | 365fc → +3f | 2d |
| 20 | u8 YcCompress | 36624 → +40 | 2f |
| 21 | u8 YcBitDepth | 3669c → +41 | 30 |
| 22 | u8 DataTransfer | 36638 → +42 | 31 |
| 23 | u8 DataPlacement | 3664c → +43 | 32 |
| 24 | u8 DataContent | 36660 → +44 | 33 |
| 25 | u8 DataScan | 36674 → +45 | 34 |
| 2a/2c | u16 RecordSize X/Y | 364f8/3650c → +4a/+4c | 14/16 |
| 2e/30 | u16 CanvasSize X/Y | 36520/36534 → +4e/+50 | 18/1a |
| 32/34 | u16 ValidOffset X/Y | 36548/3655c → +52/+54 | 1c/1e |
| 36/38 | u16 ValidSize X/Y | 36570/36584 → +56/+58 | 20/22 |
| 3a/3c | u16 TargetOffset X/Y | 36598/365ac → +5a/+5c | 24/26 |
| 3e/40 | u16 TargetSize X/Y | 365c0/365d4 → +5e/+60 | 28/2a |
| 42 | u16 StripWidth | 36688 → +62 | 36 |

I+26..29及44..47未作为本轮像素解释依据；不能借空隙安插 plane count 或序号。

A JPEG writer 的输入 `in+30/32` 填 Canvas X/Y，`+34/36` 填 ValidOffset，`+38/3a` 填 ValidSize，`+3c/3e` 填 TargetOffset，`+40/42` 填 TargetSize；`in+44` 分别经过 `34e38a0` 与 `34e3c58` 写位深和有效位宽，`+48/+4c/+50` 写色度相位/色度学/Y范围。A `34f7038..64` 用 in+0/+4 写像素 type/handle，PA和data offset置0；UnitSize由构造清0，未在此填实际分配长度。

### 4.3 YcStateInfo：8B，而非 ready 结构

| Y 偏移 | 原名称 | D setter VA | A JPEG writer |
|---|---|---|---|
| 0 | YRange | 37c14 | convert(in+50) |
| 1 | Colorimetry | 37c28 | convert(in+4c) |
| 2 | ChromaPhase | 37c3c | convert(in+48) |
| 3 | Scanline | 37c50 | 1 |
| 4 | CopyProtection | 37c64 | 0 |
| 5 | Author | 37c78 | 4 |
| 6 | ContentsBitWidth | 37c8c | convert(in+44) |
| 7 | ValidState | 37ca0 | 0 |

K `320c8..3210c`复制Y0..6；范围内没有读Y7参与 freshness/ready。不能从 Scanline 名称直接推 top-down 排布，也不能从 ChromaPhase 名称推 YUYV/UYVY。

## 5. 接收端实际检查什么长度、怎样找像素

E-length：K `3dd64` 先用 `31d8c` 得 B。若 B+2c（DataSite）==3，跳过此处图像范围检查；其它情况：

```text
pixelSDS = {u32[B+4], u32[B+8], u32[B+c]}
required = u32(CanvasX * CanvasY) << (YcCompress == 0 ? 1 : 0)
K3dc3c(pixelSDS, required)
```

**该公式取的是 YcCompress，不是位深。** 原指令为 K `3dda8:69be4039 ldrb w9,[x19,#2f]`，`3ddc4:e8179f1a cset w8,eq`，`3ddcc:6a7d0a1b mul w10,w11,w10`，`3ddd0:4221c81a lsl w2,w10,w8`。不能据这个下限公式确定全部格式的有效像素字节数。

K `3dc64` 调 `33c84` 得 `L`；后者通过 `33bfc`取8个分段，累加每个长度。检查为无符号：

```text
L >= pixelSDS.offset
(L - pixelSDS.offset) >= required
否则返回0x10；满足则返回0。
```

原字节：`3dc70:0901046b subs w9,w8,w4`、`3dc74:62020054 b.hs`；`3dcc0:3f01146b cmp w9,w20`、`3dcc4:62030054 b.hs`。这是 allocator/segment list 返回的存储容量检查，**不是 I+10 UnitSize 的检查**。

K `33af0` 从 pixelSDS+8取offset，在8段长度中逐段扣减，命中后返回该段地址+剩余offset。K `41934..50` 从 B 中取像素SDS、解析到 JPEG API+e8；resize 对应 API+1a8/+1b0。只解析首地址不自动证明整个 requested 区间跨段连续，也没有证明 plane 数为1。

freshness：上述 parser 检查 marker、entry存在、分配范围；本轮所核函数中没有“上一帧序号不同/时间戳递增”检查。分配 handle 可解析、尺寸合法和状态返回0均不能证明该缓冲被传感器新写过。是否由队列/lease在上游隐式保证新鲜，**未验证**。

## 6. JPEG：80B请求 J、解码结构 G 与驱动参数 Q/P

### 6.1 J 不是68B resize请求，也不是HEIF消息

A `34f7310..34f73e4`、`34f75dc..34f767c`核定 J=2000:0004、长50h，发752；先收16B再收16B。J 中相关字段：

| J 偏移 | 原来源/含义 |
|---|---|
| 18/1c/20 | 源YC描述符SDS，来自 in+18/+1c/+2c |
| 24/28/2c | 输出SDS，来自 in+58/+5c/+6c |
| 30 | u32 0 |
| 34 | u32 in+68 |
| 38 | u32 in+84 |
| 3c | u32 `in68-in6c-in84`，按原u32语义 |
| 40/42 | u16 in+70/+72 |
| 44/46 | u16 in+40/+42，目标尺寸 |

J+34/+38/+3c不是由此即可命名的pixel stride/plane offset；其输出范围语义须连到编码器继续互证。

### 6.2 K API → G 的属性来源：精确区分 placement、bitdepth 和 bitwidth

JPEG API在 `41910` 把 ImageSize 解码到 API+a8，`41928` 把Y解码到 API+e0。`41b2c` 分配编码输入 G，关键搬运如下：

| G 偏移 | 来源与原调用 | 已证语义 |
|---|---|---|
| 88 | API+e8 (`41c80..84`) | 解析出的源像素首地址 |
| 90/92 | API+c0/c2 | Canvas X/Y |
| 94/96 | API+c4/c6 | ValidOffset X/Y |
| 98/9a | API+c8/ca | ValidSize X/Y |
| 9c/9e | API+cc/ce | TargetOffset X/Y |
| a0/a2 | API+d0/d2 | TargetSize X/Y |
| a8 | API+d4 →31c40 (`41cd8..e4`) | DataSite转换 |
| ac | API+d5 →31c60 | IibNumber转换 |
| b0 | API+d7 →31cac | **YcCompress转换** |
| b4 | API+d8 →31ccc | **YcBitDepth转换** |
| b8 | API+e0 →31c80 | YRange转换 |
| bc | API+e1 →31c8c | Colorimetry转换 |
| c0 | API+e2 →31d18 | ChromaPhase转换 |
| c4 | API+db →31d24 (`41d48..54`) | **DataContent转换** |
| c8 | API+da →31d40 | **DataPlacement非零测试** |
| cc | API+e6 →31ce8 | ContentsBitWidth转换 |

其中31d24：原u8为0→0、1→1、其它→2；31ce8：0/1/2保留，其它→3。两个不是同一枚举。

K `55d34..7c` 的直通条件为 G188≠1、Gb0=0、Ga0/a2=G16c/16e、Gc4=2、Gb4=0。Gb0是压缩标志转换，Gb4是位深转换，**Gc4来自DataContent；值2的像素语义尚未验证**。AP wrapper只构造并清0元数据、未设DataContent，因此不能据此宣布 AP自产的描述符会走直通。其它路径进入55fb4及后续转换；转换输出的像素组织仍未闭合。

核对修正：中间进度曾把Gc4称为DataPlacement，并把Gb0/b4错标为位深/transfer，现全部撤回。原三段读取机械提取结果见 [field-provenance.json](field-provenance.json)：D具名setter→I偏移→K31eb8的B偏移→K41cd8..74的G使用点。以该原字节链及本表为准。

### 6.3 Q+20的身份已进一步闭合

记编码工作对象为 Dwork，避免与库D混淆。直通 `56308` 与转换 `55fb4` 都保存源属性；`56434`搬到提交区，`56d98`构造传给 `628f8/62954` 的Q：

```text
I.DataSite → API+d4 → 31c40 → G+a8
→ Dwork+180 → Dwork+278 → Q+20
I.IibNumber → API+d5 → 31c60 → G+ac
→ Dwork+184 → Dwork+27c → Q+24
```

原store例：`563bc:758201b9`保存源a8到work180；`56478:687a02b9`保存work278；`56dd8:a87a42b9 / 56ddc:882200b9`读work278、写Q20。

`62984`读Q20/Q24，`61ee8`以**Q20**索引表K30b400，得到P50。原表24B为：

```text
00000000 00000000 01000000 02000000 02000000 03000000
u32值：0, 0, 1, 2, 2, 3
```

**这是DataSite域到驱动参数的转换表，不能命名为像素格式表。** Q20=0/1→P50=0仅说明这条驱动选择；不能推出8bit/YC422/RGB565。

Q几何来自 `work258`及其后的半字块，`56db8..dd4`整体搬到Q0..1f；`61b98..bec`把它解开成P：

| Q偏移 | 类型/语义 | P偏移 |
|---|---|---|
| 00 | u64源首地址 | 00 |
| 08/0a | u16 Canvas X/Y | 08/0c u32 |
| 0c/0e | u16 ValidOffset X/Y | 10/14 u32 |
| 10/12 | u16 ValidSize X/Y | 18/1c u32 |
| 14/16 | u16 TargetOffset X/Y | 20/24 u32 |
| 18/1a | u16 TargetSize X/Y | 28/2c u32 |
| 20/24 | DataSite/IibNumber 转换结果 | 50/54，经61ee8 |
| 28/2c | YRange/Colorimetry 转换结果 | 78/7c所用成对属性的一部分，不能当分量顺序 |

几何是**最终提交图像**的几何；转换分支可以重建画布和矩形，不能总按原G的值填Q。既有报告给P50=0内存路径的2S字节步进、128像素画布对齐、16B源地址及W16/H8要求；本轮核到2acb14确实取P50/P28等参数并下传原驱动，但没有重验全部寄存器步进，故这些行对齐细节仍引用既有专项报告，而非声称本轮重新完整证明。

## 7. 找到的枚举：值和域必须一起保留

### 7.1 本输入链能证明的数值映射

- A `34e38a0`：model bit_depth 0→I.YcBitDepth0、1→1，其它进入原错误/断言路径。**0/1对应8/10位在这个域的具名绑定未验证。**
- A `34e3c58`：model 0/1/2→Y.ContentsBitWidth0/1/2，其它错误路径后3。不能认为2就是12bit。
- K `31d24`：I.DataContent 0/1/其它→G.c4 0/1/2；0/1/2对应的像素格式名称**值未证**。K31d40对I.DataPlacement作非零测试，写G.c8；linear/tiled/packed的具名语义未验证。
- K `30b400`：DataSite转换结果0..5→P50 {0,0,1,2,2,3}；不是RGBA/Bayer/YC采样枚举。

### 7.2 有原名称的codec枚举，但尚不能代入YC描述符

K `27a284`按u32索引K32f8c0；K `27a2a8`索引K32f8e0。表是原八字节KVA指针：

| 表raw/值 | 原条目小端字节 | 指向raw/名称 |
|---|---|---|
| 32f8c0 / 0 | 78704401c0ffffff | 447078 / CHROMA_420 |
| 32f8c8 / 1 | 83704401c0ffffff | 447083 / CHROMA_422 |
| 32f8d0 / 2 | 8e704401c0ffffff | 44708e / CHROMA_444 |
| 32f8d8 / 3 | 99704401c0ffffff | 447099 / CHROMA_UNKNOWN |
| 32f8e0 / 0 | a8704401c0ffffff | 4470a8 / BIT_DEPTH_8 |
| 32f8e8 / 1 | b4704401c0ffffff | 4470b4 / BIT_DEPTH_10 |
| 32f8f0 / 2 | c1704401c0ffffff | 4470c1 / BIT_DEPTH_UNKNOWN |

调用方 K `135940..a8`实际把某codec参数对象+78交给chroma打印器、+7c交给bitdepth打印器；对应原格式字符串K413dc9/413e02为 `chroma_format` / `video_bit_len`。这是具名数值互证，**没有找到该对象与I+21/Y+6的别名或转换链**。因此不能跨域把I+21的0、1直接标为8、10。

另一表K317f40按索引0/1/2/3/4指向YC420/YC422/RGB444/YC411/MPEG；调用方1179d0读其自身参数对象+c。也没有与I.DataContent的绑定，不把它当YC字段编码表。

## 8. SID、完成与CP：实际能交付的范围

752的已知原receiver在K，753是K内部执行投递；本轮抽查 K `3a2c4/3a2c8`用两条指令构造753、调用97058。它不是“CP收到一帧”的证据。

C全文件752/753小端u32字面量均0命中，结果在CP-sid-literal-search.json。由于K自己也是指令构造SID，**该阴性不能证明CP没有相同SID的receiver**；本轮没有追出另一个CP receiver，也不猜其像素地址/完成消息。

resize原24B第二回复在K48d50构造：+8为原状态转换，+c/+10/+14带API+d0/d4/d8（目标SDS）。JPEG原16B第二回复在42058构造：+8为状态，+c读API+148。A34f7644把第二回复+c写out+4，+8转out+0。它们是操作结果/引用回传，**没有已证的输入帧generation字段**。

下列不能混淆：

- K42bcc是实例Acquire helper，不能当真正resize像素handler。
- K3d480所构造的命令/97058调用，不能当已经闭合的pixel copy。
- API state+20的0→1/2不等于完整像素lease；本轮未闭合正常reset/free。
- 已有JPEG IRQ→寄存器计数→callback链仍需实际像素消费验证；本轮不重新推导、不构造完成通知。

## 9. 给虚拟设备的最小可行帧合同（草案）

这是一份**禁止把缺证项填成常量的接口草案**，不是可投产的帧生成配方。

| 合同项 | 已证部分 | 假设/尚缺 |
|---|---|---|
| 元数据定位 | R源/目标SDS；SSYC头、ETRY链、cate0/1 payload | 合法分配/entry版本与全部错误处理需沿原allocator实施 |
| 图像存储 | I.UnitType/Handle/DataOffset被K解析成首地址；分段总长作容量检查 | 物理连续范围、跨段DMA、plane布局/plane数未验证 |
| 几何 | I2e/30画布，I32..40有效/目标矩形；JPEG Q/P对应表 | 实际CMOS尺寸模式绑定未验证；不能拿裁剪回放分支当sensor producer |
| 长度 | 非DataSite3下，L−offset≥CW×CH×(Compress0?2:1) | 这是下限检查，不足以确定stride×height或全部plane总长 |
| 格式属性 | I20/21/23/24/25与Y0/1/2/6分别存压缩、位深、placement/content/scan等 | 每个枚举的真实像素字节顺序、YC采样、打包/平面方式仍未验证 |
| JPEG直通 | 检查G.b0(压缩)、G.b4(位深)、G.c4(DataContent)、尺寸等 | content转换值2的具名含义及转换后布局未验证；不准称8bitYC422 |
| 行对齐 | 既有P50=0专项报告给128像素画布/16B源地址/16×8尺寸要求 | 不能推广到其它P50或CMOS原始Bayer；metadata32B对齐不替代pixel行对齐 |
| 新鲜/完成 | 真实请求/解析范围/操作完成回复各有独立字段 | 输入generation/写完后的发布屏障、消费者完成后归还、复用条件未验证 |

可写成不含像素假设的设备接口约束：持有原分配的lease→按上述真实字段解析元数据→验证所有地址/长度→只有在已识别的像素布局下实际消费→按原通知协议完成→按原生命周期归还。**当前在“已识别像素布局”和“输入发布/回收”处必须停下并报未支持。**

下一个有界调查点不再是752端点，而是：沿G.c4(DataContent)、G.c8(DataPlacement)、G.b4(YcBitDepth)及G.cc(ContentsBitWidth)到实际转换执行器，给出一个原始枚举组合对应的逐字节布局；随后再追输入buffer的producer与generation/lease。Q20的DataSite映射、marker合法和范围足够都不能替代这两项。

## 10. Evidence → Finding → Path 与复现

| Evidence | source_ref / 原字节窗口 | 支持的结论 | content_hash |
|---|---|---|---|
| E-wire | AP-34f6970-230-arm | R布局 | d966e7c42f0fe7a0b186083d5ab2ffd410911cea0ac7c857cd89668acb8dd3b8 |
| E-setter | D-363a0-320-arm | ImageSize payload布局 | e25397567e548c4defde64abd082eed609073ca80cede527dfc9efd4a5938ded |
| E-state | D-37bbc-100-arm | Y布局 | de7dcc8deb53e278c7fe94ded05e97d7a388aa2f2054ed82be20e5f0dd570816 |
| E-decode | K-31d8c-210-arm | I→B | 708ee482fb8c02db04cc64154192d060c6e4cbbbff6706fadb5671f19b4ff365 |
| E-length | K-3dc3c-128-arm | 容量减offset比较 | f24c47e56436b796b2d4b364decaba064842e48d7e85011ad1574e25ce017250 |
| E-formula | K-3dd64-2d0-arm | 压缩标志控制面积倍数 | 3ba32e212d42d41fb4b7789e10784103015b905ae123029b413526c84469bf15 |
| E-G | K-41b2c-4b0-arm | G字段身份 | f6164035152f453482e62232b9e759ec0861d88eb9dd6129be68b79769bdfc76 |
| E-Q | K-56d98-128-arm | DataSite→Q20 | 489f62f218cde1801ae71e986472cd44b89fd8a76df599a294a94cd13468f5e8 |
| E-enum | K-32f8c0-50-data | 具名codec枚举表 | 88f0a3e6e30ad2e49369a7c89e8a837be55c97a42d0b332d68640579cbe00e0d |

每个窗口均有同名`.json`（完整原bytes、artifact SHA、window SHA、VA/fileoff、长度、模式）和`.txt`（逐指令/十六进制）。E-Q还依赖同目录56308/56434窗口，E-state读取端在31f9c窗口；不能省略中间搬运后跨域命名。证据索引在 [evidence-manifest.json](evidence-manifest.json)。

| Finding | severity | evidence_ids | confidence/location/status |
|---|---|---|---|
| F-geometry | n/a_re | E-setter/E-decode/E-G | 高；I/B/G/Q/P静态布局已证 |
| F-capacity | n/a_re | E-length/E-formula | 高；K3dc3c/3dd64检查已证；不代表完整像素大小 |
| F-domain | n/a_re | E-G/E-Q/E-enum | 高；placement与DataSite身份已证；跨域格式名称未验证 |
| F-frame | n/a_re | 上述证据及范围内缺口 | 完整可执行帧合同blocked：分量组织、freshness与lease未闭合 |

P-1，path_type=callflow：A构YC entries(E-setter/state)→R/J引用SDS(E-wire)→K解析SSYC/ETRY(E-decode)→解析像素SDS及检查容量(E-length)→G属性转换(E-G)→Q/P几何和DataSite转换(E-Q)→实际像素组织/发布与回收未验证(F-frame)。

复现（仅静态取证脚本，不运行目标指令，不是固件测试）：

```bash
cd final/a7c2-re/report/2026-10-17-qemu-native-camera
python3 -B report/imaging-pixel-contract/probe.py pins
python3 -B report/imaging-pixel-contract/probe.py asm AP 0x34f6970 0x230
python3 -B report/imaging-pixel-contract/probe.py asm D 0x363a0 0x320
python3 -B report/imaging-pixel-contract/probe.py asm K 0x31d8c 0x210
python3 -B report/imaging-pixel-contract/probe.py asm K 0x3dc3c 0x128
python3 -B report/imaging-pixel-contract/probe.py asm K 0x41b2c 0x4b0
python3 -B report/imaging-pixel-contract/probe.py asm K 0x56d98 0x128
python3 -B report/imaging-pixel-contract/probe.py data K 0x32f8c0 0x50
```

`verify.py`（主会话复核用，已实际通过）只锁定上表关键原字节/表，不替代本文的完整证据窗口。

其余窗口按manifest的kind/address/length/mode同样调用。probe为本轮已实际使用的脚本；只写自己目录，SHA不符立即拒绝，不安装依赖。工具：Python3.14.7、Capstone5.0.7、pyelftools。未运行测试或动态验收。

Timeline（顺序记录，不杜撰墙钟时间）：核三个主原件摘要→读六份指定报告/corpus→以D导入/导出互证字段→追K容量检查与G/Q/P搬运→记录具名枚举的域隔离→交付草案及缺口。未产生像素帧、原固件JPG或伪ready组件。

## 12. 转换执行器追到驱动提交边界（main已核代理取证，本轮新增）

代理（deepseek）取证`scratch/cmos-pixel-layout-deepseek/`（REPORT.md），main独立复核K原字节（raw偏移）确认属实。结论：**逐字节布局对任何枚举组合仍未钉**——但钉清了为什么这条链不决定布局：

- **G是双描述符**：#1源在G+0x00、#2目的地在G+0xd0（K 41c80-41d74/41d94-41e44）。目的地DataSite/IibNumber/YcCompress是conv(0)/conv(1)/conv(0)常量（K 41dac-41dd8），非源拷贝。
- **执行器选择器K 55d10**（main已核55d34起）：`G+0x188==1 || G+0xb0!=0 || 几何不等 || G+0xc4!=2 || G+0xb4!=0`→convert(55fb4)，否则direct(56308)。即README的`G+0xc4==2`是**门槛**非布局选择器。
- **格式字段被丢弃**（main已核）：55fb4把G+0xc4(DataContent)/0xc8(DataPlacement)/0xcc(ContentsBitWidth)存到E+0xcc/0xd4/0xc8，但只转发E+0x180…0x1a4与目的地块到Q/P；**E+0xc8…0xd4在链中无读者**（未穷尽反证）。故格式字段不到达提交结构P。
- **Canvas X向上对齐到128px**（main已核K 560d4：`add w8,w8,#0x7f; and w8,w8,#0xff80`），是画布范围对齐非字节stride。
- **驱动提交K 2acb14**只消费P+0x50/0x58（=DataSite经30b400）与P+0x54/0x5c（=IibNumber经跳转表336260），并两次调2aa284((P50,0,3),(P58,1,3))+2a96c8(…,3,0,P50∈{2,3})——**疑似逐面参数提交但plane数未验证**。

**新线索（未绑定，勿用于命名G+0xc4）**：K 0x433483 `[CAM_MP]…LLC Encode Param:ImageFormat(%d)(0=Bayer,1=YC422,2=YC420)`（main已核字符串前缀）；`NV12(FHD/HD720/4K)`@0x42c45a；`[ENCHANDLER]ChromaFormat:%d BitDepth:%d`@0x21c9a8；`[ENCHANDLER]illegal format YcCompress:%d Chroma:%d Depth:%d`@0x21e854；`[VDT][RSIZE_YUV] unknown compress/depth`@0x42a09c/0x42a0d2（code refs 1d3670/1d36ac/1d3790）。

**布局闭合的真正缺口**：①converter K 53848/53864/57c4c内部；②2aa284/2a96c8/2a9dd4语义（plane/index/count）；③YC字段到具名格式的别名链。这些在**CAM_MP/ENCHANDLER域**，不在本encode转发链——格式枚举的真实绑定需转到那些域继续追。诚实声明：不得据本链宣布任何8bit/YC422/RGB565/NV12为CMOS消费格式。

## 13. YC字段→InputFormat码/字节每像素/对齐 已绑定（main已核代理取证，本轮新增，实质突破）

代理（kimi，`scratch/cmos-enchandler-format-kimi/`）在ENCHANDLER域找到真正的格式校验器，main独立复核K原字节（raw偏移）确认全部属实。**这是YC字段首次绑定到具体像素格式参数。**

**校验器`create_imola_enc_start_param` @ K 0x21e6a4**（名来自ScanMode-err字符串0x43a77e，唯一调用方0x21c3d0）。它读输入结构三个u32字段——**Depth=+0xf4、YcCompress=+0xf8、Chroma=+0xfc**（main已核：错误打印参数存储0x21e824 `ldp w8,w9,[x20,#0xf4]`+`str w9,[sp,#8]`/`str w10,[sp,#0x10]`/`str w8,[sp,#0x18]` 配字符串"YcCompress:%d Chroma:%d Depth:%d"证实字段顺序；宽度=ldrh[x20,#0xe0]）。

**只有4个合法三元组**（main已核0x21e768-0x21e8a0逐指令）：

| YcCompress | Chroma | Depth | InputFormat→out+0x28 | 行字节w10→out+0x24 | 推断格式 |
|---|---|---|---|---|---|
| 0 | 1 | 0 | **4** | w<<1 = 2·w | 8-bit 4:2:2 packed |
| 0 | 1 | 1 | **5** | (5w)>>1 = 2.5·w | 10-bit 4:2:2 packed |
| 5 | 1 | 1 | **0xd** | (5w)>>2 = 1.25·w | 10-bit 4:2:0-class |
| 6 | 1 | 1 | **0xe** | (3w)>>1 ≈ 1.5·w | 12bpp (4:2:0变体) |

其它三元组→illegal format打印+返回0。**仅Chroma==1被接受**；Depth 0↔8-bit、1↔10-bit（由B/px强推断）。**YcCompress 5/6区分4:2:0变体，非"压缩开关"**——这纠正了此前把YcCompress当布尔压缩标志的读取（§5容量公式的`YcCompress==0?2:1`与此处语义分属不同域，不能混用）。

**`INPUT_BUFFER_WIDTH_RESTRICTION`表 @ 0x3ec1d0**（main已核：16项×16B={id,mul,div,align}；id4={2,1,0x8}、id5={5,2,0x20}），按InputFormat索引，强制画布宽对齐（0x21e8b0-0x21e944 udiv/msub，不符→"input width Aligh Error"）。其它消费者0x23a2ec/0x23c4e4/0x255c5c。

**仍未闭合（诚实）**：①CAM_MP ImageFormat(0=Bayer,1=YC422,2=YC420)到YC字段的**别名链未找到**（写输入结构+0xf4/+0xf8/+0xfc的producer未追到，fn 0x21c348的arg1来源未知）；②**逐字节布局未钉**（分量顺序/plane数/plane偏移/色度放置）；③fmt 0xd/0xe的w10是仅亮度pitch还是总stride未决；④fmt码4/5/0xd/0xe与CAM_MP 0/1/2枚举数值是否一致未知（域未连通）。

**对CMOS消费的意义**：虚拟传感器/CP成像模型若要产出被ENCODER接受的帧，输入结构的YcCompress/Chroma/Depth必须是上表4个合法三元组之一（Chroma=1），且画布宽满足对齐表。这给出了**第一个具体的格式合法域**；但"被接受"≠"被正确解释"——分量顺序与plane组织仍需闭合才能生成语义正确的像素。

## 14. 输入结构producer已追到+钳制证伪一个三元组（main已核代理取证，本轮新增）

代理（deepseek，`scratch/cmos-producer-alias-deepseek/`，turn上限中止但报告完整），main独立复核K原字节确认关键声明属实。

**调用链（每hop唯一调用点）**：`0x21c348`（校验器所在fn）无BL xref，由尾分支trampoline `0x2254ac`（`b`）→vtable thunk `0x22ce50`（add x0,x0,#0x390;b）→wrapper `0x227d38`（两个caller：`0x2495e4`与`0x25e274`）。参数映射：校验器读的arg1=trampoline的x2=`0x227d38`的x2。**caller A `0x2495e4`：x2=sp+0x98 ⇒ 输入结构=fn `0x2491bc`的栈局部sp+0x98**，该函数即producer。

**producer从相机设置结构x26写YC三元组**（main已核字段存储）：
- Depth(+0xf4=sp+0x18c)：`249400 ldurb w0,[x26,#-0x1f]`→`0x277d84`（main已核`cmp w0,#0;cset w0,ne`）⇒ **Depth=(settings[-0x1f]≠0)∈{0,1}**。
- YcCompress(+0xf8=sp+0x190)：`24940c ldurb w0,[x26,#-0x20]`→`0x277d70`钳制。
- Chroma(+0xfc=sp+0x194)：**在0x2491bc-0x2495e4未找到**（OPEN）。

**钳制证伪一个三元组（main已核）**：`0x277d70 sub w8,w0,#1;cmp w8,#7;mov w8,#8;csel w0,w0,w8,lo`——src∈1..8保留、否则→8（含src==0→8）。结合§13合法集{0,5,6}：**YcCompress 0（fmt 4，8-bit 4:2:2）从此producer不可达**；只有fmt `0xd`（10bit 420）与`0xe`（12bpp 420）可产出，且都需Depth==1（settings[-0x1f]非零）。**故此producer实际只产出0xd/0e两个420-class格式**。

**CAM_MP别名链：未找到（bounded否定）**：0x21c348/0x224260/0x2254ac/0x22ce50全无64位指针表/ADRP引用（纯代码图），CAM_MP ImageFormat枚举不跨此调用链；数值巧合他处未证（open）。

**第二caller `0x25e274`** 是结构相同producer（x2=sp+0x3a0），未细查（turn上限）。

**对CMOS消费的意义（修正§13）**：经此producer路径，虚拟传感器/CP成像模型**只能用fmt 0xd（10bit 4:2:0）或0xe（12bpp 4:2:0）**，且Depth=1；fmt 4/5（4:2:2）不可达。Chroma来源未钉是下一缺口；逐字节布局仍开。

## 15. fmt 0xd/0e布局追踪：撞上动态blob句柄障碍（main记录代理取证，本轮，诚实否定）

代理（kimi，`scratch/cmos-byte-layout-kimi/`）沿out-struct消费链前进两跳，**布局未钉**但钉清障碍：

- **C1**：out=obj+0xe198、out2=obj+0xe1d8（caller fn 0x21c348，args 0x21c3b8-0x21c3d0）。故每行字节=obj+0xe1bc、InputFormat=obj+0xe1c0。
- **C2**：校验后fn 0x21c348调`0x216f1c`四次（0x21c404/0x21c450/0x21c49c/0x21c4e8），经`0x2291b4`把各结构**memcpy进动态分配的blob缓冲**（表[obj+0x1038]，entry+0x10=base、+0x18=capacity），只在obj+0x1160(out,0x40B)/+0x11e8(out2,0x1c0B)/+0x1270(arg3,0x300B)/+0x12f8(arg2,0x80B)存**句柄描述符**。**静态字段xref因此不可能——读者全走句柄**。
- **C3（后续已纠正方向）**：`0x2223dc` 在0x222474-0x222574调用 `0x218c68` 按tag找四个blob节点，随后把对应buffer归还free pool。此前“消费者读取四句柄”的描述撤回；另一簇0xe9ea4-0xf0ca4与真实像素读取的关联仍未证明。

**后续原字节复核修正**：`0x218c68 → 0x2290d8` 把找到节点的 `{base, capacity}` 归还free pool并移除tagged node；它是lease归还，不是读取或消费像素。不能再沿本条归还路径宣称编码器读到了blob。详见 [原录像绑定的22窗口证据](../native-video-binding/README.md#blob-ownership-correction)。真正的blob数据读取、原生frame/SDS及DMA/plane地址编程仍未闭合；没有plane数或NV12/I420字节组织证据。

**方法论含义**：fmt 0xd/0e的逐字节布局尚未从已证动态blob复制与归还链恢复。应另找真实数据读取和DMA编程入口；句柄释放本身不证明像素消费。静态缺证不等于不存在实现，也不能仅因句柄层间接性断言静态方法已无能为力。
