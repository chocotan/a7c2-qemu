# JPEG Without_Pin：元数据入口闭合，像素布局与原生压缩仍未闭合

结论：`libInfraAvbbc.so` 的 `ExecCmd_SDF_EncodeJpeg_Without_Pin` 是向原 SDF JPEG 服务提供显式输入 SDS 的包装器。其特殊分支生成 SSYC 元数据，引用已有像素 buffer；没有软件 JPEG 压缩或像素写入实现。它仍提交到原 `0x82830752` 服务，接收端最终进入 JPEG 设备寄存器编程和完成等待。不能据此实现一个已证明正确的已知像素编码 helper。`CAPTURE_VERIFIED=false`。

本轮继承已完成的通用 JPEG/receiver 结论，不重做 9624、快门、Fsys 或其他代理成果。仅离线读取三个公开固件文件，新增本目录三个文件；未运行固件、VM、设备或网络，未改运行时代码/构建输入。所有 I/D 地址分别为各自 ELF VA；K 为 `av-cam.bin` **raw 文件偏移**，运行 KVA 为 `0xffffffc001000000 + raw`。

## 复核

在本成果目录执行（需要现有 `pyelftools`、`capstone`）：

```sh
python3 report/jpeg-without-pin/verify.py --self-test
```

异地资产可加 `--root /path/to/public/menu-root`。脚本只读资产，核完整 SHA、ELF 符号/尺寸、12 个小窗口、47 个原指令/PLT 调用和具名 getter vtable ABI；额外自测 ELF 段偏移及四种非法/跨界范围拒绝。它不会执行原指令，也不会生成 JPEG。精确原字节摘要、完整 mangled symbol 和依赖摘要见 [source-pins.json](source-pins.json)。

| 原件 | 长度 | SHA-256 |
|---|---:|---|
| `usr/lib/libInfraAvbbc.so` (I) | 1738760 | `676197567dbbefa54e08f528968efc6ca2aaffe8bee3ee3eae8164382ed5a7e5` |
| `usr/lib/dataflowInfraFramework.so` (D) | 306496 | `620e04a9cd51e65bd190ed1d5459b7235ff5a4109bc6498df342972621991d47` |
| `system/av-cam.bin` (K) | 13797088 | `90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096` |

## 构造器与两个实际方法

| I ELF VA / 字节数 | 原方法 |
|---|---|
| `0x11ac38` / 108 | `ExecCmd_SDF_EncodeJpeg_Without_Pin` C1/C2 |
| `0x11b388` / 716 | `MakeInputYcStdData()` |
| `0x11b18c` / 508 | `makeParamEncodeJpeg(SDF::ENCODE_JPEG_COMMAND_PARAM&)` |
| `0x11b654` / 756 | `ExecCmd(unsigned char const*)` |

构造器 AArch64 ABI：`x0=this, x1=InfraAvbbcMsgManager*, x2=AvbbcParamCtrl::ParameterControl*, w3=unsigned int, w4=unsigned int, w5=unsigned char, w6=unsigned short, w7=unsigned short`。`w3` 透传给 `ExecCmd_Base(manager,w3)`；`x2` 保存到对象 `+0x18`，`w4` 保存 `+0x20`（后续读取配置的参数 key），`w5` 保存 `+0x24`（输出分支选择），`w6/w7` 保存 `+0x26/+0x28`（请求 JPEG 宽高）。不把 `w3` 猜为帧 generation。

getter 不是按 vtable 偏移猜的：原 `ParameterControl` vtable relocation 将 `+0x80` 绑定到 `GetValue(unsigned int,unsigned char&)`，`+0xb0` 绑定到 `GetValue(unsigned int,void*&)`；校验脚本重查两项。

### MakeInputYcStdData 只建立元数据

I `0x11b3b4..3c4` 读 byte 参数 `0x1049`；**只有值 `0x40` 执行下述构建**，其他值直接离开，不生成输入像素。它读取 pointer 参数 `0x1054`；把该描述符的 `+0/+4/+0xc` 写入 ImageSizeInfo 的 `UnitType/UnitHandle/UnitDataOffset`。像素 PA/UnitSize 字段保持零；这不是清空对应像素 buffer。

以下 I 偏移相对 **72 字节的 ImageSizeInfo payload**，不是 C++ 对象偏移。具名语义沿用 [已有原字段链](../imaging-pixel-contract/README.md#4-yc-序列化结构真正的宽高属性和状态偏移)，D `0x36410` 再核实际复制 `0x48` 字节：

| Payload 偏移 | 原赋值 |
|---|---|
| `+0/+4/+0x18` | `u32[parameter1054+0/+4/+0xc]`，像素 SDS type/handle/data offset |
| `+8/+0x10` | PA64/UnitSize64 均为 0 |
| `+0x1c..+0x25` | `01 00 02 00 00 00 01 01 02 00`：ImageAttach=1、DataSite=0、Aspect=2、IibNumber=0、YcCompress=0、YcBitDepth=0、DataTransfer=1、DataPlacement=1、DataContent=2、DataScan=0 |
| `+0x2e/+0x30` | Canvas `1920 × 1088` |
| `+0x32/+0x34` | ValidOffset `0,0` |
| `+0x36/+0x38` | ValidSize `1280 × 720` |
| `+0x3a/+0x3c` | TargetOffset `0,0` |
| `+0x3e/+0x40` | TargetSize `1280 × 720` |
| `+0x42` | StripWidth=0；未由此推断图像行 stride |

YcStateInfo 的 8 字节为 `01 00 00 01 00 04 00 00`；D `0x37bfc` 原实现整块复制 8 字节。这里也没有“像素已新写入”证据。

接着 I `0x11b518..554` 读 pointer 参数 `0x1053`，把 `u64[desc+0x10] + u32[desc+0xc]` 作为 **元数据区域地址**，通过 `AvbbcPhycMem(...,0x400,CACHE_MODE(0),0x29)` 映射 1024 字节。仅先清该区域的前 32 字节，然后调用 `C_DataflowInfra_StdData_YC`、三个 `SetEntry_*` 写 ImageSizeInfo、YcStateInfo、ImageOutTimInfo。**没有映射并填入 `0x1054` 所指像素的数据循环**。结束的 `SetAddrInfo(0,0,0)` 调用将当前包装对象脱离 buffer（D `0x35048` 存对象地址/容量并调用 CreateHeader）；没有观察到它释放像素 lease。

`DataContent=2` 是本特殊生产者确实可达的值；不能把它跨域命名成 YUYV、UYVY、NV12 或另一 codec 的 MPEG 枚举。Canvas/ValidSize 固定也意味着此方法本身不是任意 1×1 像素输入器。

### makeParamEncodeJpeg / ExecCmd 仍提交原编码服务

I `0x11b18c` 读取构造器 `w4` 指定的配置 pointer，同时读 `0x1049` 和描述符 `0x1053`。前置 `ClearCommonMemFmtData(ctrl,0x1054)` 在**此公开库**中为 I `0x127390` 的单条 `ret`，不是像素清理/生成函数。

| 80B 请求偏移 | 已证明来源 |
|---|---|
| `+0x18/+0x1c/+0x20` | `0x1053` 描述符 `+0/+4/+0xc`：**元数据** SDS |
| `+0x24/+0x28/+0x2c` | stream SDS：type=0、handle 来自配置、offset=0 |
| `+0x34/+0x38/+0x3c` | mode=0：配置 `+0x58 + +0x5c`、`+0x58`、`+0x5c`；mode≠0：相应为 `+0x64 + +0x68`、`+0x64`、`+0x68` |
| `+0x40/+0x42` | 构造器 JPEG 宽高 |
| `+0x44/+0x46` | `0x1049==5` 为 `1360×720`，否则 `1280×720` |
| `+0x49/+0x4b` | mode=0：quality=3/addSoi=0；mode≠0：quality=4/addSoi=1 |
| `+0x4a` | `0x1049==0x40` 转成 2，否则保留原 byte |

I `0x11b7fc` 先调用元数据构建，`0x11b838` 调参数构建；`0x11b924..928` 复制 payload `0x48` 字节，`0x11b938..940` 以 `OsalSndMsg(0x82830752,request,0x50)` 提交。消息类别/命令通过 `ConvertCid(3)`/`ConvertCmdMid(3,0x304)` 转换，不能未经转换直接写成另一包装器的头值。此方法没有消费源像素或产生压缩流。

## 接收端仍是硬件，第一处缺口

沿用 [已闭合 receiver](../imaging-pixel-contract/README.md#6-jpeg80b请求-j解码结构-g-与驱动参数-qp)：K `0x41910/0x41934/0x41b2c` 解出元数据里的像素 SDS；K `0x55d34` 决定直通或转换；`0x56d98` 构建 JPEG 驱动输入。**本轮新增核对的连续末段**为：

```text
K 0x628f8 -> 0x62954 (参数转换) -> 0x62a7c
  0x62acc -> 0x2a58f0
  0x2a5980 -> 0x2acb14 (设备配置)
  0x2accb8 -> 0x2af65c -> 0x2af698
  0x2af734 -> 0x2a476c (写设备基址 +0x12a0/+0x12a4/+0x12a8...)
  返回配置后由 0x2accc0 -> 0x2ac140 申请/安排硬件任务
  K 0x62b18 等待原完成事件，之后才读取原状态/长度
```

设备基址来自 K `0x2a3e34` 的设备号索引表，经 `0x2a3e24` 扩展到 `0xffffffff00000000 | base32`；`0x2af6d0 -> 0x2a43a4` 设置源参数，`0x2af734` 写流参数。这里只证明设备寄存器编程/任务边界，没有把寄存器写入或完成事件当作 JPEG 数据验证。

**第一个未闭合的输入事实**：`0x1054` 解析出的真实像素内容，其分量字节/plane/行组织仍未知；该方法的常量只闭合元数据，不能证明其引用 buffer 包含这些像素，更不能证明它的 generation/lease。没有独立的原生软件编码器可在这条调用链替代硬件。因而本轮不增加 `jpeg-input-without-pin*.c/h`，也不把宿主 JPEG 当原件输出。

下一次最小只读切口：K **`0x2aa3e8`**，由 `0x2acc18` 传入 `P`、`P+0x28` 及设备 source block `+0x90`；只追本次可达 `DataSite=0/DataContent=2/YcCompress=0/YcBitDepth=0` 路径如何布置 source 地址/步进，再与 `0x2a43a4` 的 source 寄存器消费对上。若先追库内元数据来源，则对应 `ExecCmd_SDF_Resize_Rotate_useInPin::MakeOutputYcStdData()` I **`0x11ccbc`**；它不是已经证明的像素写入者。无需扩大到整台相机架构。

验收状态：静态元数据/请求/硬件边界通过；像素布局、实际 buffer 消费、原固件生成且可解码的 JPEG、Fsys 保存均未验证。捕获状态继续为 false。
