# Native liveview 交接复核：撤回错误协议，改走原序列请求

当前没有原固件消费模拟 liveview 像素、拍照或录像的证据。
旧交接中“CP 核心机制全部通过、唯一阻塞是 display_setup”的结论撤回。
`MENU_CP_EMULATION` 原型已被运行入口明确拒绝；源码保留作失败证据，不能用于成像验收。

## 范围与方法

授权范围沿用本成果根目录 `AGENTS.md` 以及
[成像合同范围](../imaging-pixel-contract/scope.md)：仅本机隔离 QEMU 和离线原件。
不连接相机、不直通物理磁盘/SD，不读取私有 setting 或 `full/private`。
主会话为唯一集成 writer，两个独立只读调查负责合同复核，主会话用原始指令和本机 `kuna` 复核。
文档为普通固件逆向报告（flavor=null）。

原件为 `runtime/analysis/menu-root/usr/lib/appFw.so`，SHA-256：
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。
下列 appFw 地址均为 ELF VA；运行期必须加实际 load bias，数据段按 PT_LOAD 换算文件偏移。

## 证据与更正

| Evidence | 原件位置与内容 | Finding（n/a_re，置信度高） |
|---|---|---|
| E-log | `0x36830a8` 将旧/新值指针重排，按类型表选日志函数；`0x2b10000` 调它后更新模型值 | F-log：两者分别是值变更日志与模型 setter，不是 SeqQueue post/poster；不能捕获任意 a0 改造成请求 |
| E-request | `0x24820f0` 分配 `0x778`；`0x2482108` 装入 `0x4dc`；`0x2482110` 写入 id/flag；`0x2502e7c` 调原构造器，随后加入原列表 | F-request：真正原入队 API 为 `void(0x2502e24)(NULL, 1, NULL)`；原框架负责请求生命周期 |
| E-enabled | `0x2502e5c` 的 `ldrb w23,[x0,#1544]` 读取 `0x7e4e608`；零则原函数返回 | F-enabled：这是字节门槛。实验只读并使用原 API 二次检查，不写使能位 |
| E-source | `0x34e5390` 读取 `0x910fa20` 并 set_src；`0x34f3524` 从同地址读接收队列，`0x34f353c` 为 `b.ne 0x34f36bc` | F-source：async 也使用动态 AP source；不能以 `src!=0x92840747` 判为 sync。source 不等于接收队列进入正常解析，等于则为线程退出握手 |
| E-result | `0x34f3a90` 生成事件 `0xd1`；`0x34f3a98` 读取消息 `+8`，调用 `0x34e4500` | F-result：`0x1118` 是面板配置完成；`+8` 是 VDF 结果码。`0x8001` 会转换成错误 2，不是图像 handle |
| E-histogram | `0x34f54cc` 构造 `vdf_set_histogram` 的 `0x148` 请求；完成端按命令查 promise 表 | F-histogram：`0x1148` 移除等待记录，不是已证的图像缓冲释放 |
| E-face | `0x341a044` 所属原字符串 `sequence/sequence_save_individual_face.cpp`；该业务拉取 `0x64000/0xd100` 并保存人脸登记资料 | F-face：不能据这两段传输推 liveview 帧大小或“CP 永不推” |
| E-remote | `osal_uipc.ko:.text+0x3d78` 检查远端位后调用 sender；旧 run 中 `VIRTCP_RECV sub=1118 src=0x90030001` 紧跟发送 | F-remote：完成消息重入 sender 后被丢弃；`osal_snd_msg=0` 不是 AP 收到通知 |

DMM op2a 单段 40B 回复的 status/段数/地址/长度偏移有原消费者依据，
但旧原型没有检查请求 handle、generation 和分配身份；任意 handle 都映射同一物理块不能作为有效 DMM 模型。
ICDT endpoint 第二个 u32 是 byte offset，旧文档的 phys_hi 解释作废。

可在本成果根目录复核关键伪代码；`kuna` 对 stripped 大型 ELF 的函数发现可能把目标称为
`Application_System_Init` 内部地址，因此这里显式从已核入口反编译，并以原指令校验：

```bash
kuna decompile runtime/analysis/menu-root/usr/lib/appFw.so 0x2502e24 --addr --mode fast
kuna decompile runtime/analysis/menu-root/usr/lib/appFw.so 0x34e4500 --addr --mode fast
aarch64-linux-gnu-objdump -d --start-address=0x34f3a58 --stop-address=0x34f3ab0 runtime/analysis/menu-root/usr/lib/appFw.so
```

## 实验与判据

第一轮对照 `run-wwi5p0nh` 在修改旧协议前保留：
`MENU_LIVEVIEW_TRACE=1` 当时观测的是错误的日志地址 `0x36830a8`。
原调用依次打印模型编号，a0 为 NULL，`pread` 返回 -1；没有事件对象可复用。
同一轮 console 第 2096 行已有 `LIVEVIEW_RUN n=0 tid=387`，随后原固件发出 22B `0x118`。
**这直接否定“display_setup 尚未启动”**，不需要为该轮额外注入请求。
旧 CP 原型把此 async 错当 sync，发送全零 ACK，另向远端发 `0x1118` 后自行丢弃。
该轮 probe 正常结束，但十张候选 RGB565 图均为全黑；不算菜单、liveview 或像素消费通过。
该错误地址探针已经移除。

当前默认关闭的 `MENU_LIVEVIEW_TRACE=1` 改为观察三个真实入口：

1. `0x2502e24`：原请求 API 被调用。
2. `0x2483188`：原框架消费请求并进入专用 thunk。
3. `0x309b82c`：原 `sequence_display_setup::run` 开始执行。

三处原 prologue 先统一比对再安装；只读诊断保留参数、LR、SIMD 参数及 NZCV，
不保存调用期以外的请求指针。每类日志最多八条。
曾实现的一次性请求实验已删除，因为自然请求与执行已经有完整证据。
入口明确拒绝 `MENU_DISPLAY_SETUP_REQUEST`，避免旧环境误用；当前交付只有只读观察。
原 API 返回不代表请求被消费，消费和 run 均需各自日志。

Path P-request（callflow）：原 UI 安全点 → 原 API `2502e24` → 原构造器 `24820e0`
→ 原待建列表 → 原框架消费 → `2483188` → 原序列对象 → `309b82c`。
该调用链的静态闭合不意味着下游面板配置、liveview、拍照或录像完成。

第二轮 `run-ncqd8ka8` 关闭 CP 原型及注入，正确探针实际记录：

| 阶段 | 实际内容 |
|---|---|
| 原请求 API | caller=`appFw+0x25fbea0`，data 非空，flag=1，callback=NULL，TID=332 |
| 原请求消费 | 读取8B请求头，id=`0x4dc`，flag=1，TID=332 |
| 原序列执行 | `0x309b82c` 入口，TID=386 |

`verify-liveview-sequence.py` 已验证三者先后顺序、原入口探针身份、run身份、无注入及无异常。
控制台 SHA-256 为 `39e6885349720d8809daedfd4981db413d9ecb8a835392f4864ada72e920643d`。
证明文件为该 run 内 `display-setup-sequence-proof.json`；
`original_display_setup_sequence_observed=true`，完成/像素/照片/录像标记仍为 false。
**因此无需为本场景注入 display_setup。**

最终删除注入代码后又以 `run-yssumm1f` 重建/实跑，通过相同自然链验收。
最终观察库 SHA-256 为 `3463237115caa192cc6d32cb73f29fd12b13afd2338b60c1c82a1604a3b7a77e`，
与 run 的 frozen build 和当前源码匹配；控制台 SHA-256 为
`d7e99f86633a832e0803fce3f80a0eb7d04cdedf7d9161f86cf14a758f514ae6`。
最终相关回归为 **29 passed / 34 subtests passed**；脚本同步和改动文件空白检查通过。
验收摘要见 [display-setup-native-proof.json](display-setup-native-proof.json)。
这组测试不覆盖全部 native 功能，构建仍存在原有格式/声明警告，没有以本轮顺便修改它们。

复现同一观察场景（从成果根目录开始，QEMU 需先按 BUILD 文档构建）：

```bash
cd runtime/analysis
unset MENU_CP_EMULATION MENU_DISPLAY_SETUP_REQUEST
QEMU_SYSTEM_DIR="$PWD/../../source/build/qemu-pcidma-work/build" \
QEMU_SYSTEM_BINARY=qemu-system-aarch64 QEMU_SONY_PCIDMA=1 \
MENU_DTB="$PWD/qemu-virt-board/virt-pcidma.dtb" MENU_EXTRA_MODULES=safe \
MENU_LIVEVIEW_TRACE=1 MENU_SETTLE_SECONDS=150 bash run-menu-probe.sh
# 使用上一步打印的 run 目录：
python3 verify-liveview-sequence.py menu-runs/run-yssumm1f
```

历史 run 名仅供已有证据核对；新的运行应把最后一行参数替换为其实际输出目录。

## 面板配置的真实剩余条件

CP Thumb handler `0x1c1128` 由表 `0xd16b88` 的
`18 01 00 00 29 11 1c 00` 关联到 `0x118`（CP VA=raw+`0x108000`，原件 SHA 为
`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`）。
主会话已核对表原字节、selector读取和 LCD/VF 分支指令。
14B payload 从消息+8开始：

| payload偏移（十进制） | 已证消费 |
|---|---|
| 0 | LCD/VF选择掩码，bit0/bit1分别决定更新哪组字段 |
| 1、5、10 | LCD panel、色彩模式、省电配置 |
| 2、7、9、11、12、13 | VF选择、色彩模式、帧率、强制normal、优先级、放大 |
| 3 | projector，无条件保存 |
| 4、6、8 | 当前接收函数不读；不推广为整个协议的保留字段 |

保存字段之后仍有真实应用阶段：CP `0x1f57ec` 状态机、`0x6c84d6` 子系统setter、
`0x6c8da6` 的内部 `0x2001:F00A/F00C` 配置请求和待完成掩码3。
状态 `0x12` 收回执并清掩码，归零才经 `0x6c7f3e` 完成；外发12B为
`0d 20 18 11 0c 00 01 80 <result:u32LE>`，source为`0x92840747`，目的地取原请求。
**不能仅存14B配置后就发成功完成。**

### 面板完成汇合（已闭合，main 核字节）

- `0x6c866c`：`movs r0,#3 / movs r1,#0x12 / str r0,[sb,#4]` 置 pending=3、error=0、state=0x12，等待事件 0x2d。
- `0x6c86a2`：`bic.w r0,r6,r0` 即 pending &= ~ack.mask；仅 ack.result!=0 覆盖 error；归零才清 busy、更新缓存、调完成 helper `0x6c7f3e`。
- `0x6c8da6` 构造 12B `2001:F00A/F00C`，mask 1/2 经路由表 `0xd275a4` 到 `0x90590819/1a`（panel/EVF 两支）。
- 内部错误：全关+要求省电→1、未覆盖状态段→2、不支持模式→1、子设备失败→5；完成 helper 正常发内部 `2001:1100`，外层 `0x1c7520` 构造 `0d20 1811 0c00 0180 <result:u32>`、source=`0x92840747`、result 成功为 0。
- **实现边界**：有限虚拟面板 = 单笔在途、requested/applied 分离、两支（或确认无需变更）实际应用后才发完成；
  缺回执无已证超时/看门狗，不能自动完成。硬件回调时序留作动态观察点（`0xbc1b54` 返回、`0x6e1f84` 请求、
  `0x201628` 回调、AP `0x34f3a98` 消费 + 虚拟后端读回）。


## 真正像素消费者的候选

较具体的静态候选是 USB 预览，不能直接代替 LCD：

- `libInfraStreamingUsb.so+0x10df4` 注册 `0x82d908f2`；`+0x113e4` 对通知子命令`0x2300`
  把`msg+8`交`rcvVdtEvtNotify+0x10610`。主会话已核对分派及通知字段的原指令。
- 通知payload有handle、64位地址、字节数及格式；`+0x107b4/+0x107b8/+0x107c0`分别读取
  handle/长度/地址。经`/dev/stream2`映射后，`wriUvcVideoEsData+0x104d8`把USERPTR交UVC。
- 后续DQBUF、munmap与DMM op23归还构成一条真实字节消费者候选，未见此处ICDT整帧拉取。
  DQBUF错误前归还队首的异常路径与设备持有关系仍需动态确认。
- 格式表含JPEG与NV12、FHD/720/4K；容量上限不能证明stride或plane布局。
  `sndVdtEvtSetFormat+0x11104` 发40B `200b:0304`到`0x827e073f`，下一站应追该服务的通知生产者。
- LCD的`vdf_update_yuv@0x34f58cc`发送160B `200d:014f`及ImageSize/YcState/OutTiming；
  已核调用者为人脸列表/播放，不能把它改称实时取景入口。

这些都是静态候选，当前没有把宿主图像送进它们，也没有UVC或LCD实际输出验收。

## VDT 像素生产者（2026-10-23 补，部分经 main 核字节）

`0x2300` 通知的直接生产者是 **AP/Linux 侧 av-cam VDT 服务**（K=`menu-root/system/av-cam.bin`，
raw 地址，KVA=`0xffffffc001000000+raw`，SHA `90343f5f…55096`）。两条生产链：

1. **NV12**：YC pin/SDS → YUV_CONV → SA → `200b:2300`（K `1d42d4` 打开 pin 解析元数据，
   `1d52e4` 提交 SA 程序 `1564e`，`1d4cec` 收 AA 回执后缓存 `{handle,PA,3·W·H/2}`）。
2. **JPEG**：YC pin/SDS → 编码器 → 回调 → `200b:2300`（`1c1708` 分配输出，`1c211c→2a58f0` 提交，
   回调 `1c2bec` 发 `200b:1389`，`1c26f8` 补 `FF D8`，长度为编码回调字节数+2）。

main 已核原字节：尺寸表 `1bff78`（0x438×0x780 / 0x2d0×0x500 / 0x870×0xf00 = 1920×1080 /
1280×720 / 3840×2160）、格式分派 `1dc130`（0/1/2=JPEG、0x10/0x11/0x12=NV12）、
发送函数 `1e4d90`（source/reply=`0x827e073f`，目的地取配置 SID）。
`0x2300` 的具体构造指令尚未在声明窗口直接命中，作为遗留证据点。

关键边界：
- 通知均为 48B、version=1，payload：`+0 handle:u32、+8 PA:u64、+10 bytes:u32、+14 format:u8`。
- 标准 NV12 通知长度 3110400 / 1382400 / 12441600 B；输出 Y/UV stride 与 UV 偏移未钉，
  `stride=W、UV=W×H` 仅是候选。JPEG 为码流。
- 通知 PA 来自输出 DMM 分配；不能拿元数据 SDS offset 代替。
- 完成端先 op25 close、通知前 op21 share、换缓存 op23 释放旧引用；**无新输出可重发末帧缓存，
  通知次数不证明新鲜度**。
- **输入 YC pin source 已闭合（main 核字节）**：静态拓扑 = CP InfraBB `9284074a` → CP VEF `905a0048` OUT1
  → 跨芯片输入 → av-cam VDT `827e073f` YC IN1。CP 表项 `d49250={1,0,2,0x905a0048}`、
  appFw init `17158a0` 含 `movk w3,#0x905a,lsl#16`（端点记录在 bss 运行时建）均核过。
- **YC 级注入合同（YC/ISP 输出替身，非原始 Bayer）**：向 `827e073f` 投递 56B 内层 `1000:0102`——
  `+8` source=`{0,2,1,0x905a0048}`、`+18` destination=`{0,1,1,0x827e073f}`、
  `+28/+2c/+30` 元数据 SDS type/handle/offset、`+34=0`。K 入口 `1dc570/1dcec8` 投入 flow，
  `1c5e2c` 解元数据取图像 handle/地址/长度，`1c7808` 提交 `{op200,len,srcPA,dstPA,callback}`
  经 API 表 +688（provider 未闭合，不称 ICDT），回调自发 `200b:1381`。
- `0x2300` 构造已补证：`1d4b24`/`1c1f48` 原字节 `2900e0d2…e90700f9` = MOV/MOVK 造
  `x9=000100302300200b` 后 STR，内存头 `0b20 0023 3000 0100`（main 核 MATCH）。
- 活跃模式选边、`0301` 配置、DMM backing/generation、UV stride/偏移仍需实现期动态验证。

## 拍照链现状（#6 第一轮，基于现存材料核读，未逐条新核字节）

三条链均未闭合，作为已知边界登记，不作实现依据：

- **EE 启动**：虚表槽 `0x5b46790→0x347618c`；run 先同步操作，再按 object+18 选择
  2→`0x34cb808`（still，发 CP `3003`、查回复 +8==`f000`）、3→`0x34cb948`。
  对象构造者/模式填写者/真实调度调用者未找到。enter-rec-still 另一路 `339fa58→338e924`
  （409d等待→4072→3003等待→token汇合→3012→`339fc70→338d998` 提交 EE=1）。
  **含 CP 同步依赖，不是纯 AP 条件；display_setup 自然执行与该 EE 对象之间无已证连接。**
- **JPEG 数据面**：局部链 `34f6fd0(sdf_encode_jpeg)→80B 2000:0004(752)→K 41910/41934/41b2c→55d34→56d98` 已证；
  但源是输入对象 `+0/+4` 的像素 type/handle，**其填写者未找到**——不能判 liveview 环还是独立 still 缓冲。
- **媒体可录字段**：旧字段命名有反证——键 1052 受 −15…15 校验、日志为
  `set_picture_profile_black_level`，不能当 remaining_capacity。名字目录序号≠dispatch key。
  Fsys 空间结构有约124MiB空闲证据，可排除"Fsys 回零"，但 Fsys 数值→状态机→源996/规则5269 未闭合。

## 剩余工程

- 原请求消费与run已确认；继续定位序列的实际等待及完成点。
- 闭合真实 liveview producer/consumer、通知及图像描述符，区分显示配置与像素传输。
- 为每个已证命令实现有限状态与一请求一完成；不再使用 generic ACK。
- DMM 分配/generation/租期、像素布局和正常归还均需独立验证。
- 之后才接宿主 PNG/MP4/摄像头输入、拍照/录像和磁盘产物验收。

时间线：先读取旧交接；只读对照暴露 NULL 日志对象，并捕获自然 display_setup run；两路原件复核撤回日志/帧合同；
主会话用 kuna/反汇编重核后改为原序列 API 实验，并禁用错误 CP 原型。

## 2026-10-23 追加：元数据读取的缓存属性门禁（实证）

- av-cam 读元数据单元前会调 liro 绑定的内核函数 `arch_phys_to_cache`（API 表 +0x628；原内核
  raw 0x31b3d8）。语义：PA∈[0x400000000,0x600000000) → VA=PA+0xffffffbc00000000，再
  `AT S1E1R` 校验：翻译须存在、PAR 回译 PA 须等于输入、**cache 属性高半字节 ≠0 且 ≠4**
  （即必须可缓存），否则返回 NULL 并打印 `ERROR:arch_phys_to_cache:pa=...`（run-09i5nf3n 实捕）。
  无 CP/AP 地址域分支；`0x1e000000` 这类值不会被自动加 0x400000000。
- 后果：SSYC/ETRY 内容全部正确（主机 pmemsave 核过）仍报
  `Not find image_size_info_entry`——因为 0x639 单元落在 kemco 的 `:uc` 池
  `0xCFC00000@0x430400000`，转换返回 NULL。
- SsycReader 校验清单（子代理逐指令核）：总长≥20；前缀 memcmp 仅 "SS"；主标记 memcmp "SSYC"；
  count/first 均须非 0；entry 须 "ETRY" 且 cate==0 即命中；链按 count 迭代，**不要求末项 next=0**；
  payload 固定拷 48B；blob+4..b、entry+8、容量+0x10、总长内界**均不校验**。返回码：
  −10=VA 空，−11=SSYC 不符，−e=无 cate-0 entry；上层统一打印 "Not find image_size_info_entry"
  （不区分），只能靠 arch_phys_to_cache 的 ERROR 行区分 −10。
- **否定结论入档**：把 kemco 的 `0xCFC00000@0x430400000:uc` 去 `:uc`（全局可缓存）→
  codec 驱动在 av-cam 初始化期 Oops 96000046（copy_to_iter 目的地址 NULL，EXTERNAL_CODEC_，
  run-8_1a7gq5）。已回退。改为枚举单元类型找默认即可缓存的池（yc_survey.ko）。

## 2026-10-23 追加2：可缓存单元类型 = 0x643（勘测实证）+ 元数据已被消费

- yc_survey.ko（yc-inject/yc_survey.c，run-mn0dqmb0）逐类型 alloc→op2a→free 实测：
  0x639→0x4f8500000（:uc ✗）；**0x643→0x4287aa000 len=0x200000，落在 0x424000000+0xC400000
  （kemco 无 :uc，可缓存 ✓）**；0x404→0x425ed8000 len=0x200（可缓存但 512B 太小）；
  0x405/0x4ce→:uc 池；0x63a 超时、0x63d/0x63e/0x4e0/0x4e1 status=-3。单元尺寸由 DmmCfg 按类型固定，
  请求尺寸不影响。
- yc_inject DMM_UNIT_TYPE 改 0x643 后（run-86w_573v）：`ERROR:arch_phys_to_cache` 与
  `Not find image_size_info_entry` 均消失；av-cam 真实消费元数据：
  `Change pin_param(-1x-1,undefined? -> 320x240,60P)`（分辨率/帧率取自我们的 ImageSizeInfo），
  SET_OUTPUT_FORMAT_PARAM 被接受并回 COMP（回包发送 err=0xFFFFFFE0 为已知非阻塞项）。
- camera_info_entry 缺失走 "maybe thumbnail?" INFO 旁路（非阻塞）。
- **当前卡点**：flow 重建含 FLOW_FREE_PIN（每帧消费后释放输入单元属正常），
  free_unit(h) err=0x2 → LOG_STOP。疑似所有权/引用计数：单元由注入队列分配且持有 op21+op24 引用，
  av-cam 侧 free 被拒。op21 Share 语义与 err=2 的确切分支在查。

## 2026-10-23 追加3：回调嵌套发送的深度上限 + err=2 真相 + cate2 门禁

- **err=2 真相**（子代理逐指令核 dmm.ko/av-cam.bin）：free_unit 的 err=2 是 av-cam 客户端封装
  （任意正状态→2）；底层 DMM 返回 3 = "最后一个 Share 引用释放时旧 state 仍为 Open(2/3)"，
  **释放实际执行了**，不是权限/类型拒绝。根因是我们的 op24 自开引用让 state 停在 2。
  真机 CP 流程：alloc(state 1) → op21 share(+1) → av-cam 自开自放自 free。**注入方不要 op24 自开**。
- op21(option=0) 仅增全局 Share 引用，**无目标客户端字段、无 owner 转移**；owner 队列不同
  不会导致 free 被拒（op23 free 只收 handle，无 owner 参数）。
- **cate=2 ImageOutTimInfo（payload 0x40）是 YUV_CONV 的强制门槛**（K 0x1d44e8→942ec，
  缺失 → error GetEntry_ImageOutTimInfo + LOG_STOP）；camera_info(cate=5, payload 0x3a8) 可缺省
  （走 thumbnail 旁路，无替代算法分支）。cate2 当前为零值首探，字段合同待补。
- **否定结论**：回调里继续发 DMM 请求超过 2 层嵌套会丢 inline 回复（run-er9vb95m：
  unit0 的 op20→op21→op2a 链成功，stage5 回调内再发 op20 分配 unit1 → 回复永远不到达）。
  改为 yc_survey 实证的 init 内顺序发送+msleep 轮询（10 次迭代全成功）。VDT 迟到回复
  （1304/2300）仍走回调，仅记录。
- 多帧流：flow 消费后会 free 单元（FLOW_FREE_PIN 是正常每帧清理），**每帧必须独立单元**；
  像素/元数据同单元时 flow 会 free 同一 handle 两次（像素句柄=pin 句柄），第二次的
  状态 3 已被 no-op24 修复。

## 2026-10-23 追加4：第二个并发 0x643 alloc 无回复（在查）

- run-bwik4oez/run-8bnjik8k：unit0 的 op20/op21/op2a 回复全部 inline 到达；unit1 的 op20
  **永远无回复**（非错误码——根本不回）。已排除：回复消息池耗尽（回调内即时 osal_free_msg
  后同样复现）；DmmCfg 0x643 记录 count=0x13=19 槽（非槽位不足）。
- 与勘测轮的差异：勘测每个单元 alloc→…→**op23 free**→下一个成功；v2/v3 持有 unit0 不放
  再 alloc → 无回复。隔离实验（yc_survey 改双并发 alloc）运行中。
- **谜底（run-30c158o_ 隔离实验）**：第二个并发 alloc 的回复**不是不来，是延迟 ~19s guest**
  （dmm.ko 走延迟路径；回复在 FREE 等待期间以 op=8020 status=0 迟到到达）。icount 下
  msleep 过冲 ~90x，200ms 预算 ≈18.6s guest，刚好不够。修复：op20 等待预算 1000ms（≈93s guest）。
  v2/v3 里回复到达时模块已超时卸载，无处可投。

## 2026-10-23 追加5：同类型并发 alloc 被 dmm.ko 串行化（踢泵证伪）

- run-o3twx9dn：op20#2 发出后踢泵 8+ 次（每次 op2a 都即时回复），8020#2 **始终不到**。
  对照 run-30c158o_：8020#2 在 op23 free unit0 后才到。结论：**持有未释放单元时，下一个
  alloc 阻塞至该单元被 free**（不是回复延迟、不是队列饥饿——是 dmm.ko 的串行语义）。
- 因此注入改为**单单元串行流**：alloc → 写元数据/像素 → 发 0102 → op2a 轮询等 flow
  free（free 后 op2a 返回 -0x105/-0x205）→ 下一帧。PIN_CONNECT/0304 在所有帧之前一次。

## 2026-10-23 追加6：三帧流全通（消费+释放正常），flow 缺转换器是下一缺口

- run-j1evbl7u：单单元串行流完整走通——3 帧各自 alloc→SSYC+像素→0102→**flow 即时消费并
  free 单元**（op2a status=-1，槽位 0x4287aa000 被下一帧复用），无 free err、无 ImageOutTimInfo
  错误、无 LOG_STOP。camera_info 缺失仍走 thumbnail 旁路（每帧 2 次读取，符合两阶段处理）。
- **当前唯一缺口**：create_flow 产出 [FLOW_NOP5, FLOW_FREE_PIN0, FLOW_NOP3]——无 YUV_CONV/
  JPEG_CONV 步骤，帧只被消费+释放，不产 200b:2300。疑似输出侧未真正连接：
  0304 只设了 notify 队列，未接输出 pin/缓冲；且 ulog 有 INFRA_WRAPPER register_callback
  失败（qid 0x184e0d91, err 0xFFFFFC04），疑似真正的输出消费服务在本 guest 注册失败。
  flow 拓扑决策与输出侧合同在查（子代理 flow-topology-contract）。

## 2026-10-23 追加7：flow 转换器分支合同（子代理 K 指令级证据）

- create_flow 三条打印 = **三个 flow 对象**（IN0→OUT0 / IN1→OUT1 / IN2→...），不是串行步骤；
  NOP/FREE_PIN 尾随数字无语义（K 格式串不输出）。flow[1]（IN1）选 FREE_PIN 的根因：
  **主输出 pin（YC OUT1）未连接**（K 0x1b9c04：输入未连→NOP；主输出未连→FREE_PIN）。
- 转换器分支 **FLOW_READ_STP_READ_IMAGE_RC_UVC**（K 0x1be0c4；内部构造 YUV_CONV@+0x3288
  与 JPEG_CONV）要求：OUT1 已连接；OUT1 pin 格式==输入（否则走普通 resize 优先分支
  K 0x1e4f24）；UVC 标志==1（总 flow +0x471cc，由 200b:0305 u8@+8=1 设置，需先 0304 成功，
  K 0x1dc424）；IN2/OUT5 未连接；宽高帧率非 -1、32px 对齐、fps≤60。
- 输出侧最小序列（静态推导，本轮实跑验证）：200b:0301（u32@+8=0x101=REC_MAIN/OUT1，
  u8@+0xc=0=60P，u16@+0x10/0x12=宽/高；K 最多读 +0x13，原厂完整消息长度未闭合，发 0x28 零填充）
  → 1000:0001 REQUEST_CONNECT（源 {0,2,1,0x827e073f}=VDT OUT1，目的 {0,1,0,我方队列}）→
  VDT 回 1000:0100 → 我方答 1000:8100（0x30，复制 src/dst，+0x28/+0x2c=0；K 0x958d4 置 pin
  state=0=已连接）→ 200b:0305 len 0x10 u8@+8=1 → 帧流。
- **2300 一帧延迟**：完成回调只入队（K 0x1d42f8 在下次输入处理开头调 0x1d4964 出队发送）——
  N 帧转换成功最多产 N-1 条 2300，需持续供帧。
- K 自己分配输出 DMM 单元（0x639），客户端无需提供输出缓冲。
- **红鲱鱼排除**：INFRA_WRAPPER register_callback 失败属 NFC wrapper（appFw 0x358d090）
  与 bus-power wrapper（0x350c404），与 VDT 输出侧无关；0xFFFFFC04=-1020=同步目的端不存在。

## 2026-10-23 追加8：REQUEST_CONNECT 目的端被 ERR_PARAM 拒绝（实跑）

- run-hmqdlytb：0301/0305 发送无错、帧照常消费释放；但 OUT1 握手被拒：
  `[RequestConnect] exec error(err=ERR_PARAM,src.YC_OUT(1), dst.YC_IN(0))(vdt_pin.cpp,405)`——
  目的 {type=0,dir=1,index=0,SID=我方队列} 被 VDT 解析为它自己的 YC_IN(0)。OUT1 未连接，
  flow 仍是 NOP/FREE_PIN/NOP。握手 0100 未到达（connected=0，2s 预算超时后继续——0305 照发）。
- 待子代理修正：真实 UVC 消费者对端三元组（服务 SID + type/dir/index）与 ERR_PARAM 的
  确切校验条件。

## 2026-10-23 追加9：ERR_PARAM 根因 = 缺 Dataflow 信封（reply_id=0），非目的三元组

- 子代理复核纠正自己上一轮结论：K 0x1d7e98 的 RequestConnect **不把 destination 交给本地
  pin 查表**；vdt_pin.cpp:405 只是打印点。最先失败的是 `cbz w19(reply_id),953b4` → ERR_PARAM——
  **外层 reply_id==0**。dst {type=0,dir=1,index=0,SID=我方队列} 合法（type 须与 source 相同=YC、
  dir 互补=IN、index/SID 不校验）。
- **Dataflow 信封**（K 0x947e8 构造/0x96984 识别 +4==0xa0a0a0a0）：24B 外层
  {+0 u32 replyQ, +4 0xa0a0a0a0, +8 u16 type=1, +0xa u16 total, +0xc u32 inner_off=0x18,
  +0x10 u32 total, +0x14 u32 0} + inner。GetReplyId 对裸消息返回 -0x1e——这解释了长期存在的
  `cannot send response(err=0xFFFFFFE0)`：裸消息无 reply_id，COMP 发不出。0301/0304/0305/0001
  已全部改带信封（0001 的 inner header +6=2，原厂如此；其余 +6=1）。
- 原厂 YC_OUT1 对端拓扑（A=appFw.so 指令证据）：**MCODEC_0 / YC_IN0 / SID 0x805700f9**
  （A 0x1715e78/0x1716008 端点描述符；A 0x35a8cd8 名字交叉）。USB 服务收 2300 的 SID 是
  0x82d908f2（U 0x10e54）——pin 对端与通知接收端是两个东西，上轮曾混淆。
- 0305 接受条件不含 OUT1 连接状态（K 0x1dc430）：标志可先存；建流重评估在 pin 消息处理后
  （K 0x1dcec8→0x1b9814 比较快照），非每帧。

## 2026-10-23 追加10：信封全通 + UVC 转换 flow 建成 + share 类型合同

- run-klidlryw/run-q7glqi7d：Dataflow 信封让 0304/0301/0305 的 COMP 全部正常回复
  （200b:1304/1301/1305），`cannot send response` 消失；RequestConnect 不再 ERR_PARAM，
  VDT 发 1000:0100（带信封！回调须先探 +4==0xa0a0a0a0 取内层 +0x18）→ 我方 8100 →
  1000:8001 完成 → OUT1 连接。
- 建流重建为 **`FLOW_READ_STP_READ_IMAGE_RC_UVC,in:320x240,Prog=60/12`**（首次重建因 pin
  参数未就绪报 "Cannot UVC Create Flow!![in pin invalid](width:-1...)"；帧元数据更新
  pin_param 后重建成功——时序正常）。
- **share 类型合同**（主会话直核）：flow 的 alloc_unit_share 调 op21 Share，
  **type 是常量 0xe0b00**（K 0x1d3c9c movz/movk），dmm.ko Share 全等比较（D 0x8e50-58），
  不符 → -3 → av-cam err=1 → LOG_STOP。0xe0b00 在 DmmCfg @0xde8c 有记录。
  DMM_UNIT_TYPE 已改 0xe0b00，运行验证其池位置（可缓存性）与 share 通过与否。

## 2026-10-23 追加11：双单元架构 + 消费者释放语义（实跑证据）

- **双单元分离**：元数据单元 type=0xe0b00（0xf80 B，可缓存池 0x424000000+）装 SSYC blob，
  0102 SDS 指它；像素单元 type=0x643（2 MiB，同池）装像素，由 ImageSizeInfo 的
  UnitType/UnitHandle/UnitAddressPhy64/UnitSize/UnitDataOffset 指向。flow 的
  alloc_unit_share 用常量 0xe0b00 share 元数据单元；像素单元由 flow 从 ImageSizeInfo 取得。
  跨类型并发持有不触发 dmm 串行阻塞（run-o692uetk）。
- **flow 全链执行实证**（run-1ppfg0pj）：`flow[1]RUN ... in_pin(h:0x415) image(h:0x416
  a:0x4287AA000)->out(type:0x0487)` → `flow[1]CMP ... size=192000 diff=0`——像素被真实
  转换消费（320×240×2）。转换输出经 OUT1 以**带信封的 1000:0102** 推给消费者（SDS=
  元数据单元 {0xe0b00, meta handle, 0}）。
- **消费者释放语义**：flow 消费后元数据单元即时 free；**像素单元由消费者（OUT1 对端）
  负责释放**——不释放则下一帧的 pixel alloc 被 dmm 串行化永久阻塞。注入模块作为消费者
  在收到输出 0102 后 op23 free 对应像素单元。
- 2300 的一帧延迟：K 0x1d42f8 在下次输入处理开头才出队发送——需持续供帧才能见到 2300。

## 2026-10-23 追加12：3 帧端到端转换完成（run-icq94ctv）

- 设计定型：**持久像素单元**（0x643，分配一次，帧间重写——flow 转换在 0102 send 调用内
  同步完成，无竞态）+ **每帧新元数据单元**（0xe0b00；flow 消费后即时 free，dmm 串行化
  形成天然背压/帧同步）。不再按帧 alloc 像素单元（flow 持有的 share 要等下一帧输入才放，
  逐帧 alloc 会死锁——run-vqiu06ih）。
- 实证：3 帧全部 `RDIMG RUN→CMP ... image(h:0x415 a:0x4287AA000) type:0x0487 size=192000
  diff=0`（帧计数 [1:0:0]→[2:1:0]→[3:2:0]），3 次 OUT1 投递（带信封 0102 到消费者队列），
  全程零错误零 LOG_STOP。
- **剩余缺口：200b:2300 未产生**。K 0x1d42f8（下次输入开头）→0x1d4964 要求 streaming≠0
  ✓、**时间信息队列非空**（cate2 ImageOutTimInfo 相关，当前全零可能不入队）、有已转换
  handle。cate2 字段合同在查。

## 2026-10-23 追加13：2300 条件链 + RDIMG CMP 是拷贝不是转换（重要更正）

- **更正**：RDIMG CMP `size=192000 diff=0` 是 **PCIe DMA 拷贝**（输入单元→flow 分配的
  输出单元，type=0x0487 按面积分桶：A≤0x21c000→0487），不是 NV12 转换。真正的转换是
  YUV_CONV→SA（make_mmu_param/calc_start 到 0x00930101，完成回 byte[1]==0xaa）；
  SA 完成才入队 converted 通知（要求 streaming≠0 且 (fmt&0xf0)==0x10），2300 在下次输入
  处理开头出队发送。
- **cate2 ImageOutTimInfo 字段合同**（P=payload 起点）：+00 ycCreateStartTime（入时间队列，
  可为 0）；+08 → 2300 的 +28（可为 0）；+18 ycTransStartTime（=0xffffffff 表示"未指定"，
  固件约定，RDIMG 会写回当前 VFC）；+1c ycTransTime；+2c u8 进位；+38 id。时间队列
  唯一容量门槛 count<5；**无字段非零校验，全零可入队**。但注意 1d1dc8 缩略图旁路检查
  （缺 camera_info 时）：fmt 10/11 要求 (P[00]+exposureTime+PicDelay) bit1==0（全零恰好过）。
- **2300 格式**（内层 0x30 B）：{200b,2300,0030,0001, handle@+8, 0@+0c, phys:u64@+10,
  size@+18, fmt@+1c, P+00@+20, exposureTime@+24, exposePicDelay@+25, 0@+26, P+08@+28, 0@+2c}。
- **疑似真转换门槛**：缺 camera_info(cate5) → 帧走缩略图旁路，RC/UVC 转换步不跑
  （run-icq94ctv 只有 RDSTP+RDIMG）。已补 cate5（0x3a8，+0x17c=60/+0x180=1 取缺省分支
  默认值），验证轮运行中。

## 2026-10-23 追加14：cate5 补上后缩略图旁路退出，但 RC 步仍不跑（在查）

- run-w8216694：cate5 CameraInfo（0x3a8，+0x17c=60/+0x180=1）使 "maybe thumbnail?" 消失、
  RSIZE 建流时 acquire SRC0/1/2 成功；但每帧仍只有 RDSTP+RDIMG（拷贝），**RC 步无每帧
  RUN 日志、无 SA 提交（menu-observe 的 0x00930101 钩子零记录）、无 2300**；OUT1 投递的
  SDS 引用我方元数据单元 = 输入引用透传，非转换输出。
- 待查：RC 步的每帧触发条件 / RC 是否有自己的 RUN 日志标签 / YUV_CONV 转换提交的上游 /
  消费者是否需回确认解除背压（子代理 rc-step-trigger）。

## 2026-10-23 追加15：RC 步门控机制（子代理 K 证据）

- **直通根因（与现象相容）**：RSIZE 输入处理（0x1cce64）在 `0x1cd2a4-2bc` 比较目标/输入尺寸，
  **目标宽≥输入宽 或 目标高≥输入高 → 0x1cd304 直通**（增引用、直交后继、不打 RUN、不分配
  转换图像）。我们 OUT1=输入=320×240 → 直通。OUT1 投递即此直通产物（非转换输出）。
- **RSIZE_YUV 执行门**：数据先入 R+0x1440 队列（0x1d13f4），执行入口 0x1d298c 要求
  **24 位 clock 差 ∈[1,0x7ffffe]**（零差直接返回）——cate2 时钟字段需有效值。
- **0x1d1dc8 检查**：输出尺寸/enable/模式奇偶 + ImageSizeInfo 两字段须被 1920/1080 整除；
  失败释放输入回收 callback（无 RUN）。
- **RC 在途计数 >1 才等待**（0x1d2ba0）——不等消费者 ACK；OUT1 无逐帧 8102（8102 进
  unexpected 路径；PSEND 发送后直返，0x96150→0x97114）。
- 各步独立日志标签：RSIZE `flow[%d:%s]RUN`（无序号）、RSIZE_YUV 同、YUV_CONV
  `flow[%d]RUN in_pin…->out_image…canvas_width=…`；ulog 类别 RSIZE=2、RSIZE_YUV/YUV_CONV=3，
  RDIMG CMP=1——**注意日志类别过滤可能藏行**。
- 转换链：RSIZE_YUV 输出（fmt 高半字节==0x10）→ YUV_CONV（0x1d42d4）→ 分配 0x639 输出
  （0x1d4628）→ make_mmu_param（0x1d4864→…→0x00930101）→ calc_start → 完成 → 2300。
- 待续：1920/1080 整除检查的确切字段、RSIZE_YUV 尺寸门、clock 差字段来源、真机几何
  （子代理续查中）。

## 2026-10-23 追加16：RC 接受门的完整几何/时钟合同（子代理闭合）

- **RSIZE_YUV 帧接受门**（0x1d1dc8，在入队前）：读 cate0 **TargetSize**（I+0x3e/+0x40）；
  拒绝条件 `Ow>Tw && Oh>Th`（Ow/Oh=0304 fmt 推导的输出尺寸，0x11→1280×720，K 0x1bffc4），
  且要求 **Tw%1920==0 && Th%1080==0** + enable/模式奇偶等。最小合法 TargetSize=1920×1080。
  RSIZE_YUV 无"目标≥输入直通"逻辑（那是普通 RSIZE 的 0x1cd2a4）。
- **RC 输入矩形**：Canvas/Valid/Target 三组（0x1d3218-0x1d3264 搬入 RC 参数），嵌套检查
  ValidOffset+ValidSize≤Canvas、TargetOffset+TargetSize≤Valid（0x2d6860-0x2d68c8）。
  RecordSize 不参与 RC。
- **RDIMG 拷贝长度**：N=((CanvasX*CanvasY*b)>>2 * M[YcCompress])/b，b=BitDepth==1?10:8，
  M={10,5,4,5,4,5,6,8}（K 0x3242f0）；字段：YcCompress=I+0x20、YcBitDepth=I+0x21、
  Canvas=I+0x2e/0x30（对象基 +0x228）。1920×1080 未压缩=5,184,000B（超 2MiB 单元）；
  **YcCompress=2 → 2,073,600B ≤ 2MiB** ✓（压缩布局语义未映射，先求管线执行）。
- **VFC 门**：24 位差 = diff24(当前 VFC, R.prevVFC 对象缓存)，不读 cate2；VFC 槽=
  av-cam BSS 0xba1cd4（读 0x1b7868/写 0x1b7690，经 hw 寄存器 0x2108 由 0x2a094c 更新——
  QEMU 里无 vsync 源故冻结）。P+18=0xffffffff/P+1c=0 是"未指定传输起点"的官方填法。
- 对策（本轮实跑）：输入几何 1920×1080 + YcCompress=2 + OUT1=1920×1080/60P +
  注入模块每帧写 VFC 槽推进（替代传感器帧同步信号，不伪造转换结果）。

## 2026-10-23 追加17：VFC 推进生效 + 接受门全指令解码（run-9qxsvzcd）

- 注入模块写 av-cam BSS 的 VFC 槽（KVA 0xffffffc001ba1cd4）生效：RDIMG RUN 行
  `now:1/2/3` 逐帧推进（此前 now:0 冻结）。这是传感器帧同步信号的替代源，不伪造结果。
- 几何改为 1920×1080 + YcCompress=2（1B/px，N=2073600 ≤ 2MiB 单元）后 RDIMG CMP
  size=2073600 ✓；但 RSIZE_YUV 接受门仍静默拒帧。
- **接受门 0x1d1dc8 全指令解码**（x0=R+0xd8）：① R+0x168c（配置目标宽）≠0
  ② R+0x168e（目标高）≠0 ③ **R+0x1692 enable 字节 ≠0** ④ R+0x1691 mode：
  mode&0xfe==0x10 → (P00+expTime+PicDelay) bit1==0；mode∈{4,6} → 该和 bit0==0
  ⑤ Ow≤Tw 或 Oh≤Th（已过）⑥ Tw%1920==0（过）Th%1080==0（过）。
  **当前嫌疑集中在 ①-④**：R+0x168c/168e/1691/1692 的写入者在查（子代理 rsize-config-trace）。
- 030x 分派表 @0x374718：0300→0x1e2f30，0301→0x1e317c（OUT1 pin 格式），0302→0x1e33d0，
  0303→内联 enable 风格（payload +8 u32/+0xc u8 0/1 分支），0304→输出格式，0305→streaming。

## 2026-10-23 追加18：接受门四字段来源闭合（全来自已发的 0304/0305）

- R+0x168c/168e（目标宽高）← 0304 的 format 字段（**P+5**，派生表：0/0x10→1920×1080，
  1/0x11→1280×720，2/0x12→3840×2160；K 0x1bff80/0x1bffc4-0x1bffdc）。
- R+0x1691（mode）← 0304 的 **frame_rate（P+4）**：0=60P、2=50P、4=30P、6=25P、0x10=15P、
  0x11=12.5P（分派表 0x3747c8）。我们 P+4=0=60P ✓。
- R+0x1692（enable）← 0305 的 streaming 布尔（P+0）✓=1。
- 传播机制：0304/0305 缓存到 G，建流（0x1be574-0x1be5e8）或更新时经成员回调
  （0x1d30f8，虚表槽 0x375818→0x1e1b70 thunk）写入 R。
- **注意偏移陷阱**：0304 参数区 P+0=dst_osal_id、P+4=frame_rate、P+5=format、P+8=yRange、
  P+9=colorSpace、P+0xa=quality、P+0xc=maxBitPerFrame；0304 无显式宽高。
- 运行时确认法（在跑）：dump 0x639 输出池（0x4f8500000+，slot 0x1518000）——转换真跑则
  有 NV12 内容（1280×720×1.5），日志类别过滤无法遮蔽内存证据。

## 2026-10-23 追加18b：0x639 池全零——YUV_CONV 确实未跑（非日志过滤）

- run-38zkvrj3：pmemsave 0x639 输出池（0x4f8500000，4 slots × 0x1518000）**全零**——
  转换未发生是真实的，不是 ulog 类别过滤。YUV_CONV 若跑会自分配 0x639 单元并写
  1280×720×1.5=1,382,400B NV12。
- RSIZE_YUV 入口 0x1d13f4/执行入口 0x1d298c 均无直接 BL 调用者（delegate 间接调用）。
  执行入口的调度源在查（疑似 vsync/定时器/消费者拉取驱动——QEMU 无 vsync 是关键嫌疑）。

## 2026-10-23 追加19：RSIZE_YUV 执行调度源闭合（帧同步通知驱动）

- 链：VDT 收 **source==0x80c2019f**（或 0x00c20219）消息 → 0x1dc6e0 → 0x1ba1d0（对三个 G
  逐个）→ 0x1bfe28（遍历 G+0x1d8 连接表 fire delegate）→ RSIZE_YUV 执行 0x1d298c。
  **VDT 分派 0x1b9660 纯按 OSAL source 路由**（0x61003b/0x61003c/0x930101(SA)/0xc20219/
  0x80c2019f/0x9061003c(CP DMM) 各有分支；其余才看消息 cate）。通知正文不被消费。
- 0x1d13f4 入队后纯排队（无自激/唤醒）；原生产者=帧同步扇出（VDT 初始化时订阅
  0x80c2019f，K 0x27b850 注册；扇出点 0x1b75bc-0x1b7608）。
- **QEMU 最小补全**：每帧入队后向 0x827e073f 发 src=0x80c2019f 的通知（yc_send_frame_sync）。
  与 VFC 推进是两个独立必要条件（调度 + 门控）。对象布局备忘：Gᵢ=T+0x22c0+i*0x17a90，
  Rᵢ=Gᵢ+0x6090；*(G+0x1d8)=R+0x58；R+0x16f8=&0x1d298c。

## 2026-10-23 追加20：RSIZE_YUV 已执行（帧同步通知驱动生效）

- run-_uymn0s5：每帧后补发 src=0x80c2019f 的帧同步通知 → **RSIZE_YUV RUN 出现**：
  `flow[1:SRC1]RUN in_pin(h:0x416) in_image(a:0x4287AA000)(1920 x 1080) -> out_image(...)(1280 x 720)`
  （SRC1/SRC2 两条；一帧滞后模式，帧 2 的执行需第 4 条通知）。RUN 日志本就会显示
  （此前不出现是真没跑，不是类别过滤）。
- RUN 后流程：RSIZE_YUV 自分配 0x639 输出单元（0x1d2f34→0x27817c(0x639)），成功则
  0x1d317c 构建 resize 作业描述符 → 0x2daf2c 提交引擎（底层 0x2d5524/0x2d54b0/0x2cf244）。
  完成是异步的（引擎完成回调）——**0x639 池仍全零、无 CMP、无 2300**。
- 在查：引擎提交是否真的发出（menu-observe 的 SA 钩子日志在非镜像记录，已加
  0x4102d0000 memory_log dump），以及引擎完成是否依赖未建模硬件。

## 拍摄页显示路径的独立边界（2026-10-23 只读调查）

- appFw 候选连接表：CP VEF YC_OUT2/OUT3 → CP VDF YC_IN0/IN1；VDT YC_OUT1 →
  MCODEC_0 YC_IN0 属另一分支。前者尚未以实际逐帧交付证据确认启用，不能由 UVC
  路径已消费三帧推断拍摄页已显示预览。
- 当前 `device-models/vdf-device.c` 仅处理配置/完成消息，无像素 DMA 或预览平面；
  `headless-osd.c` 从 AP bitmap 实际读 640×480 RGBA4444 OSD，`ramfb-viewer.c`
  仅在新的 OSD 像素来源序号到达时转换并提交 640×480 XRGB8888。ramfb 双槽
  0x41e100000/0x41e300000 是模拟器 viewer 的地址，不是原厂面板帧缓冲。
- CP 原件通用 ImageSizeInfo writer raw 0x9e492e 证明 type/handle、记录/画布/
  有效/目标矩形及 YcCompress/BitDepth 的序列化偏移；尚未将其绑定到活跃的
  VEF OUT2/OUT3 producer，也未恢复该帧的 stride、色度顺序、plane 偏移或压缩布局。
  1920×1080 冷态 SSYN 参数不能证明活跃 SSYC 帧尺寸。当前 2 MiB 0x643 输入
  加 `YcCompress=2` 只是 AP UVC 实验，不能作为 PNG→CP 显示格式依据。
- **画幅比例更正**：A7C II CMOS/静态照片是 3:2；实验中的 1920×1080
  仅是 VDT/UVC 支路接受门（TargetSize 被要求为 1920/1080 整倍数）所用的
  **16:9 工作画布**，不能称为传感器原始尺寸或照片纵横比。PNG 输入应保留
  原宽高比，在此画布内居中留边，不能强行拉伸 3:2 图像。
- 下一判据：先取 CP VDF 实际接收的帧描述符与输出提交地址，再让虚拟 VDF 消费
  同一帧并发布带来源摘要/序号的预览平面；由 viewer 在预览或 OSD 更新时按原
  OSD alpha 合成，最后读回活动槽或 QMP 截图比对像素。未经固件消费而直接写
  ramfb 的宿主 RGB 不算固件 liveview 验收。
- 控制面已有一次实跑握手的**精确边**：`menu-runs/run-0x450xlj/console.log`
  `FULL_PIN_CONNECT_STATE_READBACK` 显示 VEF `YC_OUT3` (`0x905a0048`, `{0,2,3}`)
  → VDF `YC_IN1` (`0x90590818`, `{0,1,1}`) 双侧 state=0；随后的 `0x404`
  单元在 `0x500000000` 传的是冷态 SSYN 格式，`pixels_consumed=0`。
  **这只证连接与格式通知，未证哪路在拍摄页有实际帧、是否经 VPH 显示。**
- CP 原件在 `cpapp-b.bin` raw `0x0f7670` 有 VDF `1000:0102` 消费者：
  元数据 SDS 的 type `0xe0b00` 指向独立图像 unit；`0x6df354` 生成
  `2001:f01a` 并管理本地引用；后续有 `2001:0500` 及向 VPH SID
  `0x906605a9` 发送 op `0x22`、长 `0x98` 的提交路径，`0x6cff58`
  把图像 PA64 写到参数首字段。**尚无活跃帧走完整链的运行证据，亦无
  VPH 真正扫描该 PA 的地址/格式合同。**
- 原件 `2001:f016` 路由配置为 36B，payload `+8 pin_slot`、`+c table_index`、
  `+10 outmask` 不可互换。CP raw `0x5bd648` 构造、`0x5d743a` 按 table_index
  存 28B；镜像默认 `VdfCategoryInfo+0x5c=0`、`+0x3c=7`。常规分支构造
  `{slot=1,index=1,mask=A}`，若路径对象 `+0xc∈{8,10}` 则 `A` 有面板位 `4`。
  这支持 IN1 为面板候选，但**拍摄页路径对象值和 f016 实际投递尚未取证**。
- VPH op `0x22` 的封装是 `M+0=u32 op, M+4=P(0x98B)`；接收器 raw
  `0x447118` 按 `P+0x68` 选槽，将 P 复制到待处理状态。调度器 raw
  `0xabae9c→0xabac8a` 读取 pending，再入七项参数队列；raw `0xad3b32`
  读取 **P+0 地址值**做非零检查，尚未解引用取像素。几何 helper raw
  `0x5daf8e/0x5daf94` 将 ImageSizeInfo CanvasX/Y 写到 `P+8/+a`，
  此处宽度**不是已证 byte pitch**；像素读取、硬件提交与完成时机仍未知。
- 联合诊断 `menu-runs/run-jx4h1c6c`：OSD `HOSDAP02` seq=1 被持久化、AP
  `YCIN_SEND` 发出三帧且模块返回完成，但原始 OSD 640×480 只有黑色，
  `summary.json` 的 `gui_library_loaded=false`、`visible_menu_verified=false`，
  也无 VEF OUT3→VDF IN1 握手。因此这是**未进入可见拍摄页**的否定对照，
  不能当作画面上屏验证。长 settle 的 `run-0bvf5wst` 在 guest 结束后
  向 stdin 追加诊断触发 BrokenPipe；缩短 settle 的上述运行已正常完成。
  下一轮采用仓库自然启动 profile 同时打开 YC 注入，各项仍独立验收。

## 追加21：RSIZE 的直接完成是 RC 回调/1383，不是后续 YUV 的 AA

以下为新增只读调查与主会话原字节复核；尚无该链运行命中证据。
K raw 加 `0xffffffc001000000` 才是本实验内核地址，不混用 AP ELF VA。

- K `0x1d3318` 从对象+`0xa4` 取引擎标识；`0x1d331c/3320` 取 callback=`KVA+0x1d3138`；
  `0x1d3324` 令 x1=`sp+0x70`，`0x1d332c bl 0x2daf2c` 提交 J。
  J 的输入地址/长在+`0x10/+0x18`，输出在+`0x98/+0xa0`；
  输入 Canvas/Valid/Target 从+`0x50` 开始，输出从+`0xd8` 开始。
  这些不是已证 stride/plane 格式合同。
- K `0x2d3b00` 为实际 MMIO 启动 helper：`0x2d3b04` 取 `C+0x10` 的低32位基址，
  `0x2d3b08` 与 `0xffffffff00000000` OR；`0x2d3b0c` 读 bank1+8，
  `0x2d3b10/14` 置 bit24 并写回，`0x2d3b20` 读回，`0x2d3b28 dsb sy`。
  真实 bank 地址/IRQ/像素布局未闭合，不能猜窗口后自动清忙位。
- K callback `0x1d3138` 构造16B `200b:1383`，+8=w0、+c=w1，
  `0x1d3168` 调 `0x1e4e70` 投给 `0x827e073f`。**这是 RSIZE 的直接完成边**；
  后续 YUV_CONV/SA 的 byte[1]==`0xaa` 是另一阶段，不能合并，更不能伪写 AA 冒充处理。
- 用户态 SA 发送 hook 没日志，不否定这条 av-cam 内核直接 MMIO 提交路径。
  当前 `sony-regfile` 只回读寄存器值，没有已证的 RC 像素运算或完成 IRQ。
- 下一可执行观察为 `A7C2_RESIZE_WATCH=1` 的隔离原 YC 输入/原 native live 运行：
  使用既有 owner/run/原镜像校验、Unix GDB硬件断点、QMP恢复保护，
  只读提交 J、实际 context banks、启动前寄存器与 callback 参数；
  前16个事件有界，64B像素样本明确不作为全缓冲验证。没有 MMIO/像素/完成写入。
  宿主 parser/隔离 profile 和原有 debug 安全回归已通过，实际断点命中尚待运行。

### 追加21b：六组 RC bank 的静态来源已闭合

原件表 `0x3ef308+i*0x1c` 的+4依次为
`f30a0000/f30b0000/f30c0000/f31a0000/f31b0000/f31c0000`。
主会话重新核对原字节：`0x2d35cc`=`0x2901a808`（`stp w8,w10,[x0,#0xc]`），
构造器把表基址 B0 与 B0+`0x2000` 的 B1 写入 context；
context 候选为 `KVA+0xb1ff50+i*0x60`。运行 engine 配置表+`0x58` 引用它，
初始化函数 `0x2d1a48/54` 将其存入运行 engine+`0xe0`。

主会话亦通过已安装 `libfdt` 读取当前 `virt-pcidma.dtb` 的 `/sony-test-iomap-5`：
phys=`0xf3000000`、virt=`0xfffffffff3000000`、size=`0x410000`、memtype=1。
与 QEMU `hw/arm/virt.c` 的普通 regfile 窗口一致。因此 B1+8 的启动寄存器候选为
`f30a2008/f30b2008/f30c2008/f31a2008/f31b2008/f31c2008`。

这闭合的是地址映射，**未证明哪个 engine 是本轮活跃请求，未闭合 IRQ号/像素布局**。
旧 `run-xa7qfksg` 中可见 B0初始化和 B1其它参数写入，但对上述六个启动寄存器
未检出 REGFILE 日志命中；这只是具体日志的阴性结果，不能当“转换已启动/完成”证据。
下一轮 kernel 硬件断点将直接核验原 context、bank pair 及原函数入口，
不允许将配置表的 `(0,1)..(10,11)` selector 直接当作 Linux IRQ。

### 追加21e：RC vtable 实际目标已定位为 `2d86fc`

`run-7d7k_rpr` 在原 `2d6324` 执行入口读回：

```text
descriptor_executor = 0xffffffc001bfbcc8
descriptor_executor[0] (vtable) = 0xffffffc0013883c8
vtable + 0x20 = 0xffffffc0012d86fc
```

当前 RC engine 的参数构造经 vtable 进入 `K+0x2d86fc`；这不排除后续启动进入 `2d3b00`。
同轮仍有两次提交、两次 dispatch、两次 engine exec，`0x2db008` 返回 `x0=0`，
但 `2d3b00` 和 `1d3138/1383` 均为零命中，输出像素仍未证明。
`2d86fc` 原指令窗口显示它继续构造多个参数块并调用 `2c8eb8/2c8ef8/2c9154/2c91f0`
等 helper；这些 helper 的实际硬件提交/完成路径仍待有界追踪，不能把 vtable 进入当作 RC完成。

后续 `run-0dv9_nq9` 又在原 `2d86fc` 入口命中2次；提交、dispatch、engine、vtable
事件各2次，`2d3b00` 和 `1383`仍0次。先前由线性 Capstone 扫描推导“全体指令没有
直接BL、因此启动helper是备用实现”的结论撤回：扫描可能在数据处中止，且不能排除
后续间接调用。只保留上述运行阴性计数，不据此排除实际启动链。

### 追加21f：size helper 表地址纠错及参数构造边界

`run-yr89in5t` 在第一个 submit 因 Python 局部变量 `descriptor` 遮蔽解码函数失败，
decoded hits=0，已detach。改名 `descriptor_ptr` 后 `run-3xnqypdy` 取得14条事件，
含两次 `2c8ef8`，其 descriptor+`0x16c` 均为0。但所记录 helper target=0 **无效**：
观察器误用 raw `0x3870ac8`。原 `2c8f18 adrp #0x387000`、`2c8f1c add #0xac8`
给出正确表 raw `0x387ac8`，index0 对应 `K+0x2c8f2c`。现已修正，索引限0..10，
运行表项必须与已校验原镜像一致；不读任意索引，不把可读零值当有效目标。

原 `2d8764` 调该函数后，`2d8770` 把返回宽度写回 descriptor+`0x16c`；
`2c9144` 实现 `(width + chunk_width - 1) / chunk_width`，
`2d87c0` 存本轮chunk数到+`0x174`，`2d8990` 决定是否生成各chunk参数。
`2d8c24..38` 把chunk数累加+`0x178`，清+`0x174/+0x17c`；
`2d8c3c` 将w22作为构造结果返回。此函数是参数构造，不是已证像素处理。
后续观察改为读取构造结果、chunk字段和 `2d1ff0` 的下一槽状态条件，
不再仅增加已证入口后重复运行。相关原表偏移/指令断言与debug回归34项通过。

### 追加21g：启动与清理地址重新归属（静态核原件）

独立调查返回后，主会话核对原 `0x3883c8` 的五个表项：
`2d8c60 / 2d8fdc / 2d9038 / 2d835c / 2d86fc`，依次为执行、清理、
完成处理、请求构造、参数构造。先前称 `2d3b00` 为“启动 helper”的命名撤回。

- 执行 `2d63e4` 从 record+`0x208` 生成 P+`0x1b0`，经 vtable+0 进入 `2d8c60`。
- `2d8f0c` 只在 P+`0x1b0` 为1或2时向下执行 DMA start：
  `2d498c`、`2d4a00`，再于 `2d8f2c bl 2d3a90`。
- `2d3a90` 原指令 `2d3a98 ldr w9,[x0,#0x10]`、`2d3aa0 str w8,[x9]`
  （w8=1），写 bank1+0=1 后读回、`dsb sy`。这是明确的使能操作。
- `2d8fec` 原字节 `c5 ea ff 97` 确实是 `bl 2d3b00`；它属于 vtable+8 的
  `2d8fdc` 清理路径。因此旧线性扫描阴性已有正向原字节反证。
  `2d3b00` 写 bank1+8 bit24 的正式硬件位名仍未知，不能再将其无命中当无启动。

上述是静态路径，不是新增运行使能证据。下一观察应核实际使能条件及 `2d3a90`，
之后必须通过实际DMA数据与真实完成通道验收，不允许只补IRQ或修改record状态。
新增实际执行GDB循环的host harness覆盖submit解码（防变量遮蔽）、正确表项、
越界索引、错误表项、坏原指令及读失败后的detach；与debug安全回归共39项通过。

### 追加21h：构造成功及下一槽就绪已运行观察

`run-sqhs6vp3` 的两次size helper表项均通过原镜像比对，index0目标确为
`K+0x2c8f2c`。两次 `2d8c3c` 的w22=0；P+`0x16c`=2368、
P+`0x174`=0、P+`0x178`=1，表示一块参数已构造、待处理索引清零。
`2d1ff0` 两次w0=1，manager分别为 `K+b20288` / `K+b20380`，当前slot均为1。
manager0的两record为 `K+b20b80` / `K+b20d90`；
manager1为 `K+b20fa0` / `K+b211b0`。这些是不同manager的提交，不是同一manager连续完成。
本轮尚未读取前一record状态，不能凭w0=1推断启动分支；也未设置真实使能断点。
旧 `resize_mmio_start=0` 在该轮仍指 `2d3b00` 清理点，不得解读为使能阴性。
观察器无错误且detach，PNG全量读回与3次RDIMG/OUT1另行通过；像素处理仍未验证。

### 追加21i：实际 RC 使能及 DMA 通道启动已运行闭合

`run-8qms16sb` 两次 `2d8f0c`：enable_mode=1、setup_status=0、branch_value=0。
两次 `2d3a90` 入口原指令通过，context分别为 `K+b1ffb0` / `K+b20010`，
对应 bank1=`f30b2000` / `f30c2000`；启动前寄存器均0。
同轮 **console.log**（不是boot-trace.log）有明确写入：

```text
REGFILE_WR 0xf30b1280 = 0x3
REGFILE_WR 0xf30b1200 = 0x3
REGFILE_WR 0xf30b2000 = 0x1
REGFILE_WR 0xf30c1280 = 0x3
REGFILE_WR 0xf30c1200 = 0x3
REGFILE_WR 0xf30c2000 = 0x1
```

两个manager的下一record状态1、前一record状态0，所以本轮未卡在复用等待。
两组共享DMA mask `f30b1008/f30c1008` 由f0更新至ff。
运行输入channel+20低地址=`287aa000`、pitch候选+24=`780`、行数候选+2c=`437`；
输出低地址=`f8500000`（另一engine不同）、pitch候选=`a00`、行数候选=`2cf`。
这些数值与提交几何相关，但地址高位重建、字节/分量格式和行宽语义必须进一步核查。

本轮14条事件未达16上限，观察无错误且detach；清理入口、1383回调仍零命中。
因此**启动已证、像素处理/完成未证**。当前QEMU的相应窗口仍为普通regfile，
并无执行实际RC运算/W1C/IRQ的模型，不能通过注入完成通知越过该缺口。

### 追加21j：当前luma不是合法压缩YC；未压缩源另行验证

独立调查经主会话核原指令：`63128` 的 SetYcCompress 把零压缩/第二选择0映射为
RC format0，非零压缩/第二选择0映射为format1；`2ce244` 对format1启用DCD分支，
`2d4dcc` 配置解压寄存器。本轮console亦有 `f30bd0xx/f30cd0xx` DCD配置。
因此现有PNG的8-bit L缓冲虽被原AP搬运，**并不是合法format1压缩YC帧**。
禁止将灰度扩展为16-bit后冒充真实DCD处理完成。format0输出的分量顺序仍未知。

`rc_dma_evidence.py` 将submit、enable gate及console配置写入逐项关联，
`run-8qms16sb/rc-dma-configuration-proof.json` 读回通过：两组输入row_bytes1920、
rows1080、2073600B；输出row_bytes2560、rows720、1843200B，均在原提交容量内。
原表 `3320d8` 将PA4GiB起映射为总线0，PA5GiB起映射为总线1GiB，
所以低地址287aa000对应PA4287aa000，不是高位丢失。原表/位宽/失败对照与相关回归54项通过。
该proof明确 `pixel_processing_verified=false, completion_verified=false`。

新增默认关闭 `MENU_YC_UNCOMPRESSED=1`，仅与YC注入且无PNG/raw输入共用。
虚拟源用原DMM type644候选大单元，先查真实长度，满足4147200B后才填所有byte lane=128，
metadata Compress=0；不假定Y/Cb/Cr顺序，不改原固件或完成状态。模块身份纳入选定initramfs校验，
mode marker仅在本轮guest创建，旧镜像残留marker直接拒绝。
实际元数据填充ASan/UBSan验证默认PNG不覆写、mode容量/常量及缓冲边界；
原ABI校验模块SHA `600cfec9aa04b1215b112a5e8fc465e7e2ce220cf0f4560eb3bfaad01bbd97af`。
最初一次编译得到空对象，被未定义init_module的ABI检查拒绝，未安装；重编译后通过。
未压缩模式的实际DMM可用性、RC格式0选择和像素消费仍待运行，不据host测试宣称可拍摄。

### 追加21k：首次未压缩源因真实容量不足被拒绝

`run-kmg4__hn` 的type644 op20/21返回地址/长度仍不可用于映射：它们报告
`4fea00000/400000`，而op2a首段为 `4289aa000/200000`。现有版本只读取首段，
不足4147200B，故在写像素前报告 `YCIN_MAP: REFUSED`，init失败时注销成功。
随后guest insmod又出现一次初始化，第二次分配未得到回复；本轮无RC断点命中。
不能把该结果解释为原RC拒绝未压缩格式，因为尚未发送有效帧。

主会话核原dmm.ko `.text+5200..5240`：op2a调用Open的option1001，
`.text+9298..92e0` 返回count并以16B步长输出地址/长度。
注入器现检查全部段：count限1..12、每段非空/地址有效、连续、总长不溢出；
只在总容量满足时映射，不猜相邻内存。实际C分段解析ASan/UBSan覆盖连续双段、
不连续、零长、越界count；模块ABI校验SHA
`82602ee13ca91cd85877bd0a482aaf3cfcc41a8621b3ba789d128a9bd9728d59`。
段表完整重试及全量源字节准入仍待运行结果。

### 追加21l：DMA完成状态及IRQ静态合同（非运行完成）

独立调查随后返回完整注册链，主会话已核原表 `bd7298+i*20`：
六项INTID34..39分别绑定 `2c89f0/2c8a90/2c8b38/2c8be0/2c8c88/2c8d30`，
attributes=0、CPU字段=1。活跃B/C分别INTID35/36（QEMU外部SPI输入3/4），
不能用PCIe的SPI166替代。原LIRO `.text+1980` 直接按ID/32向GICD_ISENABLER写位，
表明此接口不再额外加32。

正常DMA完成为每通道nibble bit0：原测试 `20ef78/20eff4` 专门检查bit0；
`2d910c/2d919c` 检查另外三位 `&0xe` 并返回硬件错误8。
共享状态 `G+0` 按nibble读取，`20d958`写清掩码；成功双通道状态候选为11h，
原清除0fh/f0h。只有实际数据运算成功后才能置相应完成位并送IRQ。

**CPU限制不能略过**：LIRO `.text+16f0` trampoline 读取已注册CPU字节，
`.text+1718..1720` 调os_this_cpu并比较。主会话核 `.text+13e0`：
TPIDR_EL1作per-CPU偏移，`.rela.text+13f0`符号为Linux `cpu_number`。
因此不可把CPU1自动解释成一基编号，也不能直接保证当前 `-smp 1` 可接收此回调。
真实CPU亲和/IRQ交付仍待运行核验，额外bank级门禁亦未闭合；本轮未生成任何完成IRQ。

### 追加21m：unit/extent编号域纠错，选定4MiB可缓存源

原DmmCfg的extent分配记录与unit映射表编号域不同，不能用同名编号推容量。
主会话依原dmm.ko的顺序读取函数解析配置，核以下原件字节：

| unit记录 | 目标extent | extent记录/容量 | 根池 |
|---|---|---|---|
| fd90: unit643 | 70c | 708: 200000 | 424000000可缓存 |
| fda0: unit644 | 70d | 71c: 200000 | 424000000可缓存 |
| f760: unit4c0 | 644 | 2558: 4fb000 | fb100000 uncached池 |
| **fc60: unit626** | **6d7** | **488: 400000** | **424000000可缓存** |

因此type644只有2MiB，不是4MiB。默认关闭未压缩源改用unit626，仍必须以运行op2a
段表及容量确认；不修改DmmCfg，不靠op20回复地址或请求size来假设实际容量。
配置SHA/映射、元数据/缓冲边界、完整段表、输入准入、RC/debug/异步写盘相关64项回归通过。
模块ABI另要求init_module为已定义非空.init.text代码，避免空对象产物进入运行。

### 追加21n：受限恒等数据核心（host-only，未接入QEMU）

`runtime/analysis/device-models/rc-identity.c/.h` 新增format0的16-bit行字节恒等搬运：
仅输入/输出尺寸、phase、type均相等时工作，保留行间距且不改padding；
压缩、缩放、布局选择不同、容量不足、地址溢出和部分重叠均写前拒绝。
它不知道分量名称、不解压、不重采样，也不置完成位或触发IRQ。
ASan/UBSan检查非对称字节内容逐行相等、padding不变、失败不写入。
**该核心尚未接入QEMU；宿主测试不代表原固件已产生输出。**

未压缩实验的下一版本正常0304请求将选NV12 FHD(10h)，原PNG诊断仍选HD720(11h)，
以使原RC能够请求同几何处理；由实际C信封测试验证，而非修改原固件尺寸。
原使能入口观察另补RC/DMA/input-pack/output-pack寄存器快照，供设备合同匹配；
输入proof分别记录RC输入/输出format/canvas及same_format_and_canvas_observed，
不把有效未压缩输入误报为恒等请求。相关回归66项通过；原固件恒等处理、
完成中断、输出buffer全量比对仍未验收。

配置验收器另支持format0输入的16-bit行字节合同，并与format1压缩输入分开报告；
仅标记same_format_and_canvas_observed，不将尺寸一致自动升级为恒等运算已验证。
新增测试首次因夹具全局字符串替换误改几何值而失败；改为按寄存器地址定点赋值后，
相关33项回归通过，生产几何校验未放松。
延迟到达的 `bbb8af1a3` 终态仍对应上文 `run-kmg4__hn` 的type644容量拒绝，
不是后续unit626实验结果；该旧实验没有有效RC请求，也没有输出像素证据。

### 追加21o：unit626仍不足原RDIMG存储合同；审查修复与CPU路由前提

`b253c2832 → run-7lwl11ti`已结束且安全关闭：3次OUT1、2次原RC format0使能，
4147200B全量SHA=`acbbceef81ae2ab47d2a69bb1ea004e12ab48fe419933cb569c10c54dae412ab`。
但原RDIMG三条CMP都要求5184000B，超过unit626的400000h容量，因此验收失败，不解释成格式拒绝。
原`1c63f0..1c646c`和表`3242f0={10,5,4,5,4,5,6,8}`说明Compress0的存储需求为2.5*area；
后续RC16-bit矩形2*area不是上游存储合同。新版采用unit431（unitrec f2d0→extent561，
extentrec4b0长度500000h、root1d cached424000000），先查真实段、检查5184000B后全量初始化/读回。
该实验模块SHA=`3fb0b351df2d8f8c3dfe33d0b9d083ed6e77e3c07952de81861b1167226e6b68`，
输出仍720p，不能拿它验收后续FHD同尺寸改动。旧proof的init=false还受shell回显
`echo YC_INJECT_MOD_FAIL`误匹配影响；新版仅识别独立失败标志行，未将该旧run改判通过。

只读审查6323b677确认两项P2，主会话复现并修复：
- 失败初始化可能在op20/Share/memremap后丢失所有权记录；取得任何DMM资源后失败，
  保留失败模块和所有权状态至VM退出，不擅自free已共享/在途单元。实际完整C测试覆盖截断输入和Share后段拒绝。
- 未压缩proof原先只查独立日志存在，可能将无关CMP/RC当作输入消费；新版要求DMM→发送三帧→
  RDIMG输入/输出地址→OUT1 metadata→RC输入PA及成功setup绑定，并绑定QMP地址收据。
  无关地址、错误handle、非零setup、缺分配、短读/坏摘要均不验收；像素/完成标志仍false。

CPU调查41b936a4已完成（不是仍在运行）：原liro `.text+1818`保存definition CPUbyte，
`13a8`离线回退只改路由参数，`1714..1720`仍比保存CPU1与cpu_number；当前单核无法通过。
原内核已支持SMP/PSCI，但双核启动尚未实测。新增DTB helper仅声明合法CPU1与PSCI、
双核PPI mask并移除可选旧拓扑，不改固件CPU谓词。原GPEX占外部SPI3..6，与RC35/36
对应的SPI3/4冲突，尚须一致搬移PCI中断映射，不能接两个producer伪装完成。

### 追加21p：完整存储范围与原FHD配置通过；SMP/RC数据处理仍独立验收

`ba50370b4 → run-ks9_80je`的unit431实际PA=`425558000`、容量`500000h`，
5184000B全量QMP SHA=`3ed9b790b7c98f0d857dd2dbee2c297f4be0136fa2996d1ff20c93188ff159dd`，
guest FNV=`37acb63d66972b25`，三次RDIMG CMP/OUT1及DMM/发送/QMP/RC地址身份绑定全部通过。
两次原RC输入/输出format0、几何均1920×1080；原DMA row3840×1080，
RC矩形4147200B落在5MiB单元内。`rc-dma-configuration-proof.json`已独立生成并读回，
`identity_operation_verified=false`、像素和完成均false。原输出pack+108=1而输入pack全0，
尚不能仅凭相同canvas宣称字节恒等；常量128也会掩盖重排/转换。

独立调查965d543e核实GPEX可搬到空闲外部SPI12..15（GIC INTID44..47），
原RC INTID35/36对应外部SPI3/4。新增`native_rc_board.py`只在显式RC profile下校验并修改
固定DTB的16条slot/pin映射，`device-models/rc-board.patch`同步QEMU板级分配，默认仍3..6。
门禁要求匹配SMP2和PCI DMA profile，旧QEMU缺`SONY_RC_BOARD_V1`构建标记则拒绝执行，
不允许只改DTB留下板级分配不一致。现有eDMA外部166保持不动，其IRQ编号语义另行核对。

首次SMP候选`b24985e94`在资产校验阶段因自有diag overlay摘要未同步而退出，VM未启动；
同步的仅是project_overlay记录（7565B，SHA=`b1e7ff365b13e961dda30a2b0456fd64f509db2606021a834355deb436008a2a`），
原始固件资产身份未改，CHECK_RUNTIME已通过。后续SMP运行另记，不把该预启动失败当作双核失败。
只读观察现额外记录GIC enable/pending/IRQ32..39 CPU targets，diag采集真实CPU online和/proc/interrupts；
这些采集不产生IRQ，也不改变原affinity。RC板级候选构建和双核运行仍须各自验收。

### 追加21q：双核已带起；实验性RC数据后端与真实硅片合同分开

`b17ac760f → run-jekozups`原内核记录CPU1 secondary boot、`Brought up 2 CPUs`，
但host后续diag超时，未生成summary，也未加载到YC/RC请求阶段。日志末尾为正常BusyBox shell，
不能把它称为双核不支持，亦不能称整次启动通过。其关闭guard记录QMP连接已拒绝、safe_to_close=false；
未取得原Fsys挂载/媒体写入证据。新版先验证一个短串口往返，再启动GDB观察，并正确设置
cpu1 cgroup=1、双核组=0-1；另以无GDB/无YC实验隔离启动输入问题，结果仍须实际采集。

`b3f93e29b`仅板级构建通过，SHA=`7dd8f6ac28ae0d863abd7236eeedcf2cc004cac08aaeac9cf5208e00835db3c0`，
不含RC数据后端。后续构建能力检查拒绝了仍缺后端的旧二进制：GNU patch的自动反向判断使
dry-run反向检查误判已应用。新版使用`--force --reverse`，复现测试覆盖未应用、应用、再次检查，
没有移除能力/源文件摘要门禁。

独立调查64511aae已完成：unity Q12=1000、phase0、两轴coeff=01000100已核，
但输出pack+108=1是原代码刻意设置，硅片lane/filter语义仍未知。主会话新增显式实验性
lane-preserving-unity-v1后端，**不把该假设升级为Sony恒等运算已证**。它仅匹配已观察的
FHD寄存器子集并实际搬运完整RAM矩形，然后发布正常DMA状态/W1C/IRQ；其余配置拒绝。
只有B/C有模型，A与虚拟RTC的IRQ冲突未绕过。详见
[`RC-REFERENCE.md`](../../runtime/analysis/device-models/RC-REFERENCE.md)。

只读审查9f4ebf82发现reset未清旧状态的P2，已补legacy reset清寄存器并拉低IRQ；
QTest覆盖真实搬运后pending状态的重置，不把源码修复当作动态通过。宿主实际C测试使用不等lane、
逐行/邻接不同字节及边界哨兵；QTest将进一步验证真实QEMU RAM、IRQ边沿、W1C、拒绝和reset。
这些检查即使通过，也只验证声明的后端，不提供独立硅片像素参照。原1383、JPEG/MP4仍未验收。

### 追加21r：参考后端实QEMU验证通过，SMP串口问题不依赖GDB

`ba008d630`完成真实QEMU QTest：完整4147200B非对称RAM结果、尾部哨兵、
设备IRQ上升/下降、W1C11→10→0、非零phase拒绝不写不发正常IRQ，以及pending完成后的reset清理均通过。
结果SHA=`b873296f134275db356f8116fefe81dc1e511a9800054201c66042b0745fcb1a`；
二进制SHA=`0aa4da94b4510d7cc9e81ab2c87994bd9abf9db76fd2a755c178d9843e86f591`。
主会话又核全部7项canonical source/patch与build receipt摘要及实际binary摘要一致，
未用仅含板级标记的旧构建冒充数据后端。这是实验模型的实际字节操作/W1C/IRQ证据，
不是原LIRO CPU1回调、硅片packing、彩色CMOS或媒体文件证据。

`b9bb437e5`在无GDB、无YC条件下，GDB之前的最短串口往返仍超时；
故前次shell输入失联不能归因于观察器抢停CPU。新增有界失败现场采集：
QMP CPU registers/status，GIC enable/pending/active/targets和UART flags/interrupt masks。
明确避开UART DR、GIC IAR/EOIR等有消费或确认副作用的寄存器；两个实际helper测试覆盖读范围及失败留证。
后续必须以这些现场定位板级/IRQ问题，不延长等待或修改原CPU谓词来冒充通过。

### 追加21s：UART接收IRQ无目标；补显式loader交接而非改固件

`b9d7255e5 → run-5i1no3y4`取得双CPU PC=`ffffff8008097988`，原kernel
offset17980/17984/17988为DSB/WFI/RET。后续monitor物理GIC读取失败，
原QEMU `gic_get_current_cpu()` 在SMP/non-qtest下依赖current_cpu，不能由该失败反推guest GIC死锁。
已移除monitor和GDB中的GIC MMIO读取，避免观察工具缺少vCPU上下文破坏现场。

`bc95d9c09 → run-7cxqmt7j`安全UART读回FR=c0、IFLS12、IMSC50、RIS30、MIS10：
宿主输入确已到FIFO且RX未mask。新增无MMIO副作用的QOM `sony-debug-state`读模型现有状态，
`bd2978124 → run-p_kxc9ja`实测IRQ33 target=0/enabled=255/level=255/active=0；
两个GICC control1、PMR240、running_priority256、current_pending1023，故SPI无目标可直接解释未唤醒。
IRQ198同为target0；Sony timer232/233已分别为1/2。原eDMA输入166对应INTID198，不改动该正确映射。

已有源码调查`analysis/qemu-boot-research/smp-uart/REPORT.md`说明Sony takeover配置跳过
SPI默认target初始化并在request_irq时只继承既有target；原2.01binary对应分支仍由独立调查核对，
不把公开配置当作逐字binary证明。新增默认关闭GIC handoff属性：只在reset为实现的SPI初始化CPU0目标，
不设置pending/active/enabled、不中途强改affinity；原驱动后续可正常重设RC CPU1。
该策略是显式模拟loader交接，不声称恢复了真实loader完整IRQ表；单/双核及flagoff/on QTest和
原kernel串口/RC回调分别验收。候选运行未回收前，不报告原1383、像素算法或拍照录像成功。

### 追加21t：原RC回调实际进入，GICC EOI缺页修复后到达下游新阻塞

`b5693d760 → run-5p9z3vmj`先通过GIC handoff flagoff/on两个QTest，再由原双核内核
完成boot串口往返。UART33 target1，原RC B真实搬运4147200B并清W1C0f/f0，
GDB原字节校验后命中`K+1d3138`回调，result0=0/cookie10002。
随后CPU1在原LIRO `.text+1754` EOI store到`fffffffff13a2010`缺页，
原固定DTB仅映射GICD VA页而没有GICC页；该轮不能当作正常完成验收。
已补固定DTB `sony-gicc-alias`: PA08010000→VAfffffffff13a2000，size1000，
不改EOI指令或IRQ条件，实际prepared DTB测试校验该映射。

`bb7aa22c2 → run-rloczxt2`随后取得B/C两次实际DMA，原`1d3138`成功回调各一次，
cookie10002/20003，原dispatch两次返回0；EOI缺页不再出现。之后下游写f3170110/114/30/08等，
在`K+20df90`访问VAfffffffff28004a0缺页（caller2110d0、参数2f），
这是真实下一阻塞，不能将新异常忽略或把空regfile当成下游像素运算。
独立只读调查核这段控制合同。当前原回调**入口**已证，1383后续消费/整个成像成功仍未证。

源码现在额外将RC参考构建receipt绑定本轮binary和全部canonical source/patch摘要，
支持全输出QMP读回及源PA/大小/FNV关联。即使下游异常也先保留完整源/输出并将
`run_without_observed_exception=false`单独报告，避免丢掉正/负内容证据。
SMP串口偶尔交错`YCIN_INIT_DONE`与shell MOD_OK；源码允许原kernel的
`initcall init_module... [yc_inject] returned 0 after ...`作为init结果的独立证据，
但仍必须通过失败标志排除、三帧handle/地址、原RDIMG/OUT1和全量摘要等全部输入判据。

原kernel takeover二进制调查c9b57924预算内只核了镜像身份，未恢复两目标函数；
该项保留为未验证，不以源码配置替代原指令证据，也不继续描述为运行中。

### 追加21u：异常现场的两路RC输出已全量读回，仍不升级失败运行

`b8ee82fcb → run-_69oxqrc`专门保存已知下游异常前的内容证据，未修改设备行为。
源存储5184000B完整读取；B目标`4f8500000`、C目标`453cae000`各4147200B完整QMP读取，
两者SHA均=`acbbceef81ae2ab47d2a69bb1ea004e12ab48fe419933cb569c10c54dae412ab`，
逐字节与本轮源矩形一致，FNV=`c093758771ffc325`。地址绑定本轮原DMM单元、
原RC提交及设备数据receipt；原回调result0/cookie10002和20003均由校验原入口的GDB观察取得。
`rc-reference-output-proof.json`中：
- `declared_reference_output_readback_verified=true`；
- `original_submission_identity_verified=true`；
- `original_success_callback_observed=true`；
- `run_without_observed_exception=false`；
- `silicon_packing_verified=false`、`color_pixels_verified=false`、`capture_verified=false`。

这闭合的是原请求驱动**声明的实验参考运算**并实际消费/产出字节，不是Sony颜色算法或拍摄成片。
该轮仍在`fffffffff28004a0`缺页，不能把成功的局部证据抹成整条链成功。
观察16次停止后正常detach，未触64上限；关闭guard记录safe_to_close=true、
CPU running已核、forced_termination=false。下一步等待该控制页原合同后修复，不重复入口探针。

### 追加21v：配置页合同已核；GPEX避开原SA中断注册

独立调查0c6edb32已结束配置页调查，并由main核原字节：`2110cc→20df7c`，
`20df90 ldr w9,[x8]`经`bd9f38+8*channel`取地址；`20e024 str w9,[x8]`、
`20e028 ldr w8,[x8]`是普通配置RMW/回读。channel2f指向f28004a0，
companion表bda1e8指向f2800520；当前相邻channel30为f28004e0/f2800560。
两张各86项表的所有地址均落在VAfffffffff2800000..0fff，所以候选只背这一页。
该词不是IRQ状态、W1C或完成触发。软件默认177/100不当作硅片reset值；
PAf2800000为显式模拟器映射选择，不由VA指针冒充原物理翻译已证。

调查同时核出原SA注册44..53：旧GPEX外部12..15对应INTID44..47，会与SA0/SA1重叠，
因此撤回旧分配。新`rc-board.patch`/固定DTB同步选外部244..247（INTID276..279），
launcher要求`SONY_RC_BOARD_V2 gpex_spi_base=244`，旧binary拒绝。main对
bd6d38..bd8d38有界登记窗取得58个结构匹配项，最大ID265且不含276..279；
此前标准板级分配调查也未占外部244..247。这是有界覆盖，不声称所有动态IRQ均已排除。
原eDMA外部166→INTID198仍保持不变。

`cp-config-page.patch`仅在显式RC profile创建一页普通寄存器存储，不发IRQ、不模拟SA像素。
固定DTB在全局重叠检查之前添加该VA映射。实际prepared-DTB、原表/指令、patch复现及16条swizzle测试通过；
新QTest还检查四配置词独立写后读回、写这些词不会使RC IRQ变化。
本轮候选`bbbef3eb5`先构建并运行QTest，再推进原固件；尚待结果，不能把配置映射当作SA完成。

### 追加21w：配置页实跑通过，原RSIZE CMP与SA启动门已到达

`bbbef3eb5 → run-w9e264g1`已结束：f28004a0/0520/04e0/0560按原调用分别写177/100/177/100，
原缺页没有复现。SA2 f3170104/108写ff，f3170000/0004各写1，随后轮询本体状态；
仍没有SA执行/中断/完成模型，不将轮询背板读零报告为计算结束。
host最后因console中原始非UTF8字节92严格decode失败，因此没有summary；
只修post-run文本读取为errors=replace，原console字节和摘要保留，直接离线重验既有产物，不为此重开VM。
`recovered-component-proofs.json`明确记录host_finalization_failed=true：
源输入、双核DTB/online/串口往返、RC CPU1目标、原成功回调及全量参考输出均通过；
guard safe_to_close=true、forced_termination=false，未见Oops/Exception。
原ulog两次`RSIZE_YUV CMP`已出现，输出分别4f8500000和453cae000；SA/2300仍未完成。

该轮有序MMIO console校验因串口交错未通过，错误`Original enable entry has no matching MMIO enable write`
原样保留，未放宽正则或删除该失败。模型现在把RC寄存器写和DATA receipt同时记入独立boot-trace，
DATA另保留console人读行；新证据读取优先用独立trace，避免guest printk混行。
`b38f27005`已完成该构建与两个真实QTest，包含trace中仅有效搬运有receipt的检查，2 passed。
binary SHA=`42f0296452ba96eacf6a05cffaef1a5f3f6927b6780e15cccae1b903c4be5026`。

独立SA合同调查已完成静态部分：f317110/114是word-addressed MMU表槽，需左移2，
原转换窗332558支持PA47e5bd200/47e5bd400；030/060是程序入口低/高字，
原3325d8窗支持候选PA47d0e0900。0008=80000000不是足以断言的启动位，
真正原launch在3052fc/305308对0000/0004置bit0并dsb。普通完成预期SA2 group0/rawINTID48，
group1/2为49/50；各组raw/pending/enable为100/104/108、140/144/148、200/204/208。
精确完成位和程序语义未知，不写pending/IRQ冒充成功。
新增`sa_job_evidence.py`只在原双启动门已观察后读取程序所在两页及两个512B表前缀，
范围/原地址表/短读拒绝有实际测试；输出明确partial、记录数/一致性/载荷解码/执行/完成均false。
新运行负责取得实际字节，独立MMU记录解码调查不复做已交付的配置页合同。

### 追加21x：SA实际程序、参数与MMU已按原入口绑定

`b5371a1d1 → run-zfh7n5ca`虽然真实SA launch发生，但读回仍错误地依赖YCSTAT(+60s)；
90s settle窗口内较晚出现该事件，最终缺source读回，host证据生成失败。已把RC数据和SA启动采集
独立放在settle循环首部，并用实际AST执行测试验证无YCSTAT也能读SA；不靠延长等待冒充修复。
SA寄存器写另记独立trace以免serial交错。后续`b2d513bb0 → run-oblfv6k8`完成结果文件，
input/reference_output/原回调均通过、未观察内核异常；程序及两个slot前缀已真实QMP读回。

**槽角色纠正**：110/114并非已证的“两张MMU表”。该轮slot0(PA47e5bd200)是参数块：
`{1564e,780,438,f00,1,0,0,0,3e140000,2bd95000,0,0}`；slot1(PA47e5bd400)才符合16B映射格式。
早期文件名mmu0/mmu1保留原样作证据，新采集器中性命名slot0/slot1，不给未知槽预设角色。

独立MMU代理ca6d449d预算内未取得目标反汇编，main直接核原`2ff5f4..2ff95c`：
输出22槽，每槽16B，+0=enable1，+4=logicalstart&1fffff80，+8=(start+size-1)&1fffff80，
+c=转换backing地址；w3低字节0选word(addr>>2)，非零选byte。未用槽四字清零。
`b2d44d5ed → run-fe83l2l0`原字节校验后记录builder入口count3/windowmode1/wordmode0，
commit读到3条/VAffffffc07e5bd400，全部352B与独立QMP的slot1前352B完全一致。
这使word单位从“地址吻合的条件假设”升级为本次真实调用已证，而非通用模式推断。
三条logical映射为：0..1ff→PA47e5bd200，200..15181ff→PA4f8500000，
1518200..2a301ff→PA4af654000；后两者覆盖容量均1518000h，不把容量当实际图像字节数。

程序身份由693d1fde调查、main独立全量比对：8KiB读回SHA36e6317a..028d逐字节等于
官方`usr/sabin/sa_sabin_mp_cam_post.bin[8000:a000]`，package SHA38a99704..9a12；
bundle8800、payload8900、入口在读回+900，bundle名SA_NV12_0x02、entry名NV12CONV0x02。
payload1400B，SHA75c481ee..8822。原validator计数是+e处**ldrb**，撤回早期u16表述。
loaded_nv12_program_identity=true，ISA/执行/精确像素变换/SA完成仍false。
独立正常完成位调查与参考转换边界评审继续；不因识别程序名字就置完成位或假造NV12文件。

### 追加21y：受限参考转换核已测，SA状态位未知仍不发布完成

只读评审2ab59a13确认：默认关且明确声明的参考转换可以用于追踪固件数据流，但不能替代
Sony SA指令、颜色/CMOS保真或最终成片验收。main新增host-only `nv12-reference.c/.h`，
显式定义Y0-Cb-Y1-Cr输入、偶byte为Y、相邻行Cb/Cr以(a+b+1)/2平均、Y后接interleavedUV。
该选择是参考算法假设，不由NV12CONV0x02名字推成原packing已证。
独立Python期望值测试覆盖非对称Y/Cb/Cr、相邻行、舍入、stride、两端哨兵、
容量不足/重叠拒绝不写；实际C另过ASan/UBSan。尚未接入SA QEMU或发SA IRQ。

38fbe4b5已结束正常完成调查，只核到group0软件状态3的结果路径；
精确正常/错误raw/pending位及程序输出寄存器含义仍未知，不能报告已恢复。
main进一步窄反汇编300ec4确认它读120..12c、160..16c和220结果寄存器并构建响应，
这些真实结果字段不能由“一次group0 IRQ”代替。当前没有写SA pending/强制ready。
参考核、程序身份、MMU真实单位三者分别记证，仍缺真实SA执行与后续2300/成片。

`run-fe83l2l0`虽然取得上述精确MMU证据，但该轮输入总体仍false：第三方regfile日志插入
一条DMM metadata len中间，严格身份匹配只承认2次RDIMG/OUT1。保留该失败，不放宽regex。
新增显式RC profile下的`regfile-trace-only.patch`：普通regfile读日志不再污染串口，
写日志移入独立trace，非RC profile保持旧输出；寄存器行为不改。
patch复现测试增加所有补丁应用后的再次反向dryrun，防止互相修改context破坏重入。
新候选负责真实QTest和原运行复核。126项相关host tests通过，不与QTest计数混合。

### 追加21z：默认关SA数据参考运算实跑通过，仍无SA完成事件

新增`QEMU_SONY_SA_DATA_ONLY=1`要求显式RC profile，模型只覆盖SA2控制页，
没有任何IRQ输出。仅匹配固定program payload SHA、全512B参数、22槽3项映射及原双启动门，
要求所有范围真实RAM且不重叠。读取输入快照、计算显式YUYV-vmean-half-up参考结果，
重查program/参数/表不变，写目标并读回核验；不设置ready/result/pending/完成IRQ。
pending ff写仅按已知W1C清零，固件仍等待未模拟的SA正常完成。

`b4c2b8d8e → run-vuh2ib5k`先通过默认关/开、GIC handoff关/开四个真实QTest，
包含非对称完整输出、尾部哨兵、program单byte变异拒绝且不写、pending/IRQ不发布。
随后原固件实际发起作业：输入4147200B SHAacbbceef..12ab；
输出3110400B，SHA=`00d2ed0a6c04c0d97f3a8085194d956a6892c87f1657ae422307dbd924f68040`，
两者独立QMP全量读回并关联本轮官方程序identity和原MMU commit。
中性源的Y2073600B、UV1036800B均128，main再次逐字节确认。IRQs48/49/50虽由原驱动enable且target2，
但pending/active/level均0。summary中data_only_readback=true、completion_published=false、
nativeISA/silicon/downstream/capture均false；关闭guard安全、无强制结束。原窗口仍黑、没有成片。

只读审查974e1432发现P2：memcpy后校验不一致会走“未写输出”的拒绝日志。
已拆分为precommit reject output_written=0与postcommit OUTPUT_MISMATCH output_written=1，
均completion_published=0；没有声称并发vCPU写入下能回滚。实际C错误路径注入+ASan/UBSan通过。
`b08c82493`修复后重新构建并过四QTest，binary SHA=
`7417adda195d4a97708abae4a3f0012d175242019554c02843b068b539136ae1`。
该修复只修错误报告，不给原运行追加不存在的执行/完成证据。

### 追加22：原AA消费者已核；独立虚拟完成协议推进至原NV12通知环

eecc62b1已交付并由main窄反汇编复核：300ec4为NV12请求类型1生成34h字节0aa响应，
通过原2fd100 callback/queue送达；1d4cec按opcode aa走1d4e28分支，
1d50b4将error bytes6/7保留到job，随后1d565c按job metadata给出handle/PA/3wh/2，
这条分支不读取响应+c..30十个result words作输出选择。源码寄存器位调查bb277fa6在限定本地源码范围
未找到SA完成因子，不能把ffmask解释成真实bit0正常完成定义。

新增独立默认关`QEMU_SONY_SA_REFERENCE_COMPLETE=1`，与DATA_ONLY互斥：
实际参考转换及目标读回成功之后，使用明确声明的**虚拟group0 bit0**协议置raw/pending并发IRQ48。
真实硬件因子/ISA仍false；不修改原固件predicate、不填伪结果词、不注入AA消息。
原ISR和结果响应仍由原代码生成。原data-only模式继续不发IRQ。
SA2 external16/INTID48与默认virtio0transport冲突，因此此模式单独把该空transport断线并在
generated/fixed DTB标disabled，其他模式保留。实际QTest检查全输出先产生、pending与line、
mask0降线/重开升线、W1C清线、program错误不写不发、reset及模式互斥。

`b30504166 → run-_lzmvbit`六种实际QTest通过，原运行1次DATA publication→原IRQ48入口→
原calc_start_done日志→原1d565c消费者入口；消费者全3110400B快照SHA00d2ed0a..8040，
与原RC输入及参考算法逐byte一致，handle41c/PA4af654000。summary显式注明
reference_completion=true、hardwarefactor/nativeISA/silicon/downstreampixels/capture=false。
安全guard正常，未见异常。只读审查905812fd发现证据匹配未校顺序/覆盖率P2，
已增加原IRQ先于consumer的pair、全部publication计数相等及反向/部分消费否定测试，
此一作业原记录独立重验仍通过。

`b7131af22 → run-xhmmanb7`再核原consumer streaming=1/format10h，
原1d571c通知环确实入队handle41c/PA4af654000/3110400B，深度0→1。
原notify drain入口是1d4964（1d495c为前函数尾），它还要求context+1458的UVC request队列非空。
当前无2300像素消费者证据，正核正常请求生产者/调度，不强填队列或假造notify。

### 追加22a：撤回“UVC fetch请求队列”假设，保留正常输入时序

f8c61bb6已交付并main对关键store核对：consumer+1458是**输入帧时间信息队列**，
不是额外UVC fetch请求。1d42d4→GetEntry cate2，将payload+0/+8和尺寸信息写consumer+1464
五槽，每槽c字节，递增+1458；不存在所查路径对时间值非零的要求。
有界对齐分支扫描定位1d42f8→1d4964，发生在下一次YUV输入开头、先于该帧时间字段入队。
正常frame-sync经1dc6e0/1ba1d0/1bfe28/1d298c，要求VFC前进且R+15b0有完成RC输出，
再由1d2a58 delegate进YUV输入，自然调用drain。没有证据要伪造新的fetch消息。

当前三帧快速提交的frame-sync可能早于参考SA完成，所以未压缩源在三帧之后另发送有界8次
40ms间隔sensor timing通知，仍由原调度决定是否处理已有完成队列。实际C摘取块测试覆盖8次上限、
默认PNG模式不追加、发送失败传播；不写原队列、不直接调drain或发送2300。
候选`bb0d70fdf`已运行待回收，未预测其通知结果。

### 追加22b：原2300整块接收已验收，转向自然EE现场

`b138e74fd → run-9qby4xza`完成三次有序参考发布→原IRQ→原消费者；每条消费者快照3110400B
均与对应源及参考算法一致。两条原2300通知由诊断receiver实际读取全部字节并FNV，
结果与原消费者入口一致；第三个输出仍留在通知环，不计为已消费。读取在callback内完成并memunmap，
保留handle/PA/size/format及callback-only lifetime证据，不把receiver ACK当CP显示或照片。

`b9b0a5d50`在不ptrace/SIGSTOP的条件下采样9个原AP线程：EE_START_ENABLE=1、
EE_ENTRY_SOURCE=0、EE_STATUS=0；线程syscall/stack边界一致，码字只标candidate，未断言卡点。
新增独立`MENU_NATURAL_START_TRACE=1`，在`33aa0d0`模式切换、`339d44c` enter-rec-still及
`305b9b0` run_i返回处按原16字节重放，保存NZCV/errno，未启用旧MENU_ENTRY_PROBES中
已知+8 continuation危险路径。`bc259912e`正用该观察与自然JPEGtrace采集现场，
不把未命中或EE字段值直接解释为成功；自然still/JPEG/MP4和CP显示仍未验收。

### 追加21c：第一次有界 RC 观察停在原提交入口，但观察器读地址失败

`run-rc7ma9z8` 的 PNG 输入全量 QMP SHA、guest FNV、三次 RDIMG/OUT1及模块完成均通过；
GDB 日志实际停在 `0xffffffc0012daf2c`。然而 `resize-watch-result.json` 为
`hits=0, error="OverflowError: can't convert negative int to unsigned"`，
所以**并未取得 J 描述符、bank 或 RC 完成证据**，不能把该轮外层退出0当作观察通过。
GDB 的 AArch64高位寄存器可能以负整数暴露，读内存前必须归一化为无符号64位。

主会话已修正归一化，并保留每次停止的原寄存器及事件计数；新增独立观察验收，
requested RC probe 若没有解码命中、退出有错误或未detach，运行入口以失败退出。
这项验收与 PNG 字节输入验收分别报告，不把缺少转换完成伪装为输入失败或成功转换。
该轮清理证据显示 debugger正常退出、QMP将pausedCPU恢复running、`safe_to_close=true`。
相关39项回归与语法检查通过；修正后的运行仍待实际参数读回。

### 追加21d：RSIZE 提交描述符已取得，RC 启动/完成仍未命中

修正后的无GUI run `run-3yr8x8z3` 取得两次原入口 `KVA+0x2daf2c` 停止，
每次原16B入口字节校验通过。PNG输入身份仍独立通过：guest FNV=`f72083ecb6f5abd9`，
QMP SHA=`a772e9113835434f2039ba1626bc8cc9040f96154a6d7cdf9b04c676544e7432`，
3次RDIMG CMP/3次OUT1。

两次 J 描述符字段均为：

| 字段 | 第一次 | 第二次 |
|---|---:|---:|
| input PA | `0x4287aa000` | `0x4287aa000` |
| input length | `0x200000` | `0x200000` |
| input Canvas/Valid/Target | `1920×1080` 嵌套 | `1920×1080` 嵌套 |
| output PA | `0x4f8500000` | `0x453cae000` |
| output length | `0x1518000` | `0x1518000` |
| output Canvas/Valid/Target | `1280×720` 嵌套 | `1280×720` 嵌套 |

输出地址两次不同，证明提交对象确实引用独立输出缓冲；输入/输出前64B样本均为零，
不能用样本推断转换内容。该 run 的 `resize-watch-result.json` 为 `hits=2`，
`events_per_kind.resize_submit=2`，但 `resize_mmio_start=0`、
`resize_complete_callback=0`；因此这是**原 RC 请求提交证据**，不是硬件启动、像素处理
或 `200b:1383` 完成证据。QEMU regfile 仍只是回读占位，不能据此宣称输出有效。

### 追加22：Application_System_Init 返回值与自然启动的 403d 等待

旧观察器把 `Application_System_Init` 的非零 `x0` 打成 `RETURN_NONZERO`，一度被误读为
初始化错误。原指令 `0x36ec318` 调用 OSAL 创建线程，`0x36ec340` 从 `[x29,#0x60]`
取出输出句柄，并经 `0x1796a00..0x1796a10` 返回；该值是**不透明线程句柄**，不是 errno。
观察器现保留并返回原句柄，只记 `RETURN_HANDLE`。曾临时改为返回 NULL 的 `run-2hkxvsd4`
不能作为正常启动验收；后续实验恢复原 ABI。

`run-s7s9lcww` 的被动线程/栈快照定位到原 `sequence_set_release_lock::run`：
AP 向 SID `0x90040193` 发送 16B、类型5、命令 `0x403d` 请求，随后在
`0x3535b00` 的 `future.get` 和 `0x3101948` 的 futex 等待。实际请求为：

```text
05 00 3d 40 02 00 00 80 00 80 00 00 01 00 00 00
```

即 token `0x80000002`、mask `0x8000`、lock=1。现有
`MENU_CP_RELEASE_SERVICE=1` 只实现原 CP 已分析的“无活动 release，立即回复”分支，
用原消息分配/发送 API 返回 12B、类型1、同命令/同 token、状态 `0xf000` 的回复；
不写 EE/ready、不生成像素、不释放调用方请求。可执行测试验证请求/回复布局、
source/destination 和失败传播。`run-2hkxvsd4` 观察到 token 02/09/0b/0e/10/12/14
均被原发送器接收，但该轮含上述临时 NULL 返回值且因可选 AP 快照缺失提前收尾，
所以只保留为协议服务证据，不宣称菜单、拍摄或文件输出已经恢复。

恢复原返回句柄的 `run-g9imyc_6` 正常完成实验收尾，403d 请求仍全部收到回复，
但收尾时已无 AP maps。控制台保留了直接退出原因：

```text
/usr/bin/im.elf: symbol lookup error: /usr/lib/appFw.so: undefined symbol: iCrypt_HasPublicKey
```

因此“AP 仍在某个 EE 条件等待”的假设不成立；该轮 appFw 因动态符号环境不完整退出。
固件自带 `libInfraCrypt.so`（22,768B，SHA-256
`18992ab1c7495a4acc746097e7a13a0cc62ddd01161dda4d14cefb1171f6c8fd`）
在 `0x1e58` 导出该符号，并跳转到原 `iCryptManager_hasPublicKey@plt`，不是固定真值 stub。
现有默认关闭的 `MENU_CRYPT_LIB=1` 通过 `dlopen(..., RTLD_LAZY|RTLD_GLOBAL)`
恢复这个原库及其 `libInfraCryptCore.so` 依赖；不伪造公钥、认证结果或拍照状态。
后续自然启动必须显式保留此开关，并以新运行判断下一个真实边界。

### 追加23：sequence_boot 1436 是 BusPower 0x2f6 缺接收端，不是 UPM/EE

`run-zg27xysi` 在原加密库恢复后进入 `sequence_boot::run`，随后 SeqQueueCommon
进入异常监视器。保存栈只证明通用 `notify_model_system_error()` 被调用，不能把相邻的
日期、UPM 或409分支直接定为根因。`run-3f8axpzr` 的新只读探针进一步记录全部
UPM model error=0，且409探针0命中，因此早先409候选被实际证据否定。

原 `menu-ulogio.bin` 给出了直接日志：

```text
[SEQ]void model::sequence_boot::run_i()(1436) assert at sequence/sequence_boot.cpp:1436(error:00000011)
```

原指令/函数链逐段闭合：

1. `0x305db94` 调 `0x34caa48`，随后 `0x305db98` 读取结果，非零进入1436 fatal；
2. `0x34caa48 → 0x350c6fc` 是 `infra_wrapper_bus_power::detail::set_buspower_setting`；
3. 它经 `0x3599c6c` 以 raw destination `0x12282f6` 发同步请求，路由低15位为 `0x2f6`；
4. 无接收端时底层返回 `-1020 = 0xfffffc04`，`0x359a274` 将 `-0x3fc` 映射为模型错误 `0x11`；
5. 因而1436/error0x11与缺失 BusPower 接收端完全对应，不是 CMOS/EE 像素条件失败。

`MENU_BUSPOWER=1` 调用固件原 `libBusPower.so` 的 `BusPower_Init`，其 DT_NEEDED 包含
原 `libUsbControl.so`。库身份分别为43,968B/SHA-256
`4c39d2789745a4638490da1aa41b39c90980c7dd30837a693e87085689bbcc0e` 与
135,424B/SHA-256 `2baa5ad90a468751e5a7c8e7db3221ac39b53427ed4360c35dce80ec3520c39c`。
这是恢复固件自己的接收模块，不是宿主伪造0x2f6成功回复。此前完整基线
`run-xa7qfksg` 中该模块初始化返回且有 `0x12282f6` 接收线程/同步流量。
当前只增加此原模块的运行用于验证能否越过1436；在看到新终态前不宣称启动、拍摄或录像成功。

### 追加24：原 BusPower 已越过1436，下一等待是 VDF timecode

`run-qfwvpgi1` 正常收尾且未进入异常监视器：原 `BusPower_Init` 返回，
`libUsbControl.so` 的 `0x12282f6` 接收线程存在，同步目的地计数为4。
这证明恢复固件原模块可消除1436崩溃，但 `run_i` 返回、模式切换、Still入口和JPEG请求
仍全部0命中，不能称启动或拍摄完成。

该轮被动 AP/线程快照仍可读，`EE_START_ENABLE=1`、`EE_ENTRY_SOURCE=0`、
`EE_STATUS=0`。`SeqQueueCommon` 保留 `run_i→0x305dd70` 调用链，
停在原 reply queue 的接收 ioctl。原指令 `0x305dd6c` 调 `0x34c68d8`，
再到 `0x34e9a64`：`infra_wrapper_bb::detail::vdf_srvc_set_timecode` 经
`0x3510d78` 向 `0x9059000e` 发异步请求，并由 `0x3510fa4` 以 timeout=-1
等待原回复。因此新的阻塞是 VDF timecode 配置交换，不是 EE 像素门禁。

现有 `MENU_VDF_CONFIG=1` 与该52B请求布局匹配：它校验 envelope和受限数据，
更新声明式配置cache，使用原分配/发送/释放接口排队36B回复并跟踪lease；
它是 `virtual_config_only=1`，不证明CP像素、VDF硬件或拍摄页。正在以该既有服务
验证 `run_i` 能否继续；不把配置ACK当显示或CMOS验收。

### 追加25：VDF 配置交换通过，下一等待是 HDMI definition

`run-g9kqrei0` 的 `vdf-timecode-proof.json` 由仓库验证器直接复核console：
52B请求、36B/status0回复、commit/cache1→0、原等待线程free以及后续原VDF请求
全部满足，`vdf_timecode_config_verified=true`；`camera_startup_verified=false`。
独立 ASan/UBSan 模型测试也通过 `VDF_EVF_SUBSCRIPTION_NO_EVENTS_PASS` 与
`VDF_PROTOCOL_STATE_OWNERSHIP_ABA_PASS`。这仍只证明配置协议和所有权。

推进后的 `SeqQueueCommon` 栈变为 `run_i→0x305e060`：
`0x34c7958 → 0x34f4d54` 构造 `2500:010a` 并向 `0x909a015a` 调用
`hdmi_set_definition_hd`，随后等待原回复。下一项使用已有
`MENU_HDMI_BOOT_CONFIG=1` 的共享definition配置服务，不用泛ACK。
独立 HDMI ASan/UBSan 测试覆盖六字段、五selector、50次地址复用和definition ABA，
均通过；物理 HDMI 输出仍未验证。

### 追加26：HDMI 配置系列完成，下一阻塞是 pin topology

`run-6k86frq8` 中原 `hdmi_set_definition_hd[0] definition[0]` 成功返回；
`010a`、后续 `0101` resolution 和五个 `0117` rate selector均完成真实回复、
状态readback及原等待线程free。此结果只证明共享配置，不证明物理输出。

`run_i` 随后推进到 `0x305e40c → 0x34dc4e8 → 0x35a9e40` 的
`change_infra_pin_topology` 路径，仍在原数据流/pin流程中等待。
因此下一项不是再补一个泛成功码，而是恢复既有完整拓扑依赖：
`MENU_PIN_REGISTRY=1`、`MENU_PIN_CONNECTION=cold`、
`MENU_PIN_CONTROL_MEMORY=1` 和 `MENU_DMM_UNIT_CONFIG=1`。
独立 `test-pin-connection-verifier.py` 与 `test-pin-format-verifier.py`
共8项（1项按环境跳过）通过。当前用该组既有模型继续自然启动，
连接、格式backing和像素消费仍分别验收。

### 追加27：cold pin 仅闭合一条边；三个实际等待属于 BB audio/config

`run-w5ev4cqv` 实际完成 `0x905a0048` 一条 cold 连接的peer交换、DMM backing、
80B格式记录、引用释放和原reply free；但日志同时保留多条
`FULL_PIN_CONNECT_UNSUPPORTED` 与 `change_infra_pin_topology error connect`，
所以**不能宣称完整topology已恢复**。`SeqQueueCommon` 进入 `i_sequence::await_i`
汇合等待，另外三个SeqThreadPool仍各有未完成请求。

被动栈将三者分别定位到 `0x92840747` 的原 `send_and_wait_cmp_i`：

| 调用 | 命令 | 既有模型 |
|---|---|---|
| `adf_set_volume` (`0x3058ed0→34c7298→34eabc8`) | `200d:0330` | `MENU_AUDIO_BOOT_CONFIG` 音量状态/readback |
| `0x3060a18→34c7398→34ec1ac` | `200d:033f` | 原音频映射/只读生命周期回复 |
| `0x305ac84→34c6f58→34ea484` | `200d:0327` | 明确inputless能力/错误回复 |

这些不是猜测的通用面板ACK。独立 ASan/UBSan 测试通过
`AUDIO_SYSTEM_PATH_MASK_IDLE_CONTROL127_STATE_AND_ROLLBACK_PASS`、
`SYSTEM_SOUND_PER_KIND_VOLUME_STATE_PASS`、
`AUDIO_INPUTLESS_CAPABILITY_OWNER_STATUS_ERROR_28B_ABA_PASS` 和
`AUDIO_VOLUME_CONFIG_OWNERSHIP_ABA_PASS`。当前以该既有audio boot服务验证
三个请求及汇合能否完成；音频输入/输出硬件仍未验证。

### 追加28：audio/config完成后出现屏幕对象；当前等待是digital level

`run-8suocb4y` 中三个目标请求均完成真实reply、原waiter free；后续又完成
53组音频表注册、切片readback、音量/path配置与释放。随后出现
`CREATE_SCREEN id=0x308 count=28` 和 `CREATE_SCREEN_RETURN=0x1c`，
但这只证明原屏幕对象/arena创建，不是CP拍摄页或像素输出。

新的SeqQueueCommon栈为 `0x305e554→34c8b84→34ef9b0→34e552c`。
原反编译确认 `0x34ef9b0` 是digital-level查询：`*a0!=0` 时发送24B、首字节3，
等待24B回复并用 `0x4c670e8` 原错误表转换；它不是audio命令。
此前观察标签 `FULL_AUDIO_BOOT_NEXT_REQUEST` 已更正为 `DIG_LEVEL_BOOT_REQUEST`。

既有 `MENU_DIG_LEVEL=virtual` 是明确的mode2订阅模型，不提供加速度计或角度事件。
其独立测试通过 `DIG_LEVEL_SELECTOR3_VIRTUAL_SUBSCRIPTION_NO_SAMPLES_OWNERSHIP_FAILURE_PASS`
（Python证据组2项因缺目标run而跳过，未伪称执行）。当前只加入该模型验证请求/订阅；
屏幕创建不等于拍摄页，角度样本、显示与Still仍分别验收。

### 追加29：digital-level完成；下一实际请求为panel reverse

`run-opzdm6vn` 完成digital-level selector3的控制消费、24B reply、commit和原waiter free；
仍明确 `sample_valid=0 angle_events=0`。SeqQueueCommon再次进入汇合，剩余Pool1等待
`0x3058ea8→34c6a84→34e9f48→34ea008`。

原函数 `0x34e9f48` 的名字和断言均指向
`infra_wrapper_bb::detail::vdf_set_panel_reverse`：发送28B到 `0x92840747`，wire命令
`200d:0119`，等待12B并经 `0x34e349c` 转换状态。当前实测输入为
`0101000000000000000000000000000000000000` 的后续载荷。

既有 `MENU_PANEL_REVERSE=virtual` 仅提供方向配置、shadow/readback和错误回滚，
独立测试通过 `VDF_PANEL_REVERSE_VIRTUAL_CONFIG_ZERO_STATUS_CONTROL_READBACK_ROLLBACK_PASS`。
当前以其回复该实际请求；不宣称物理方向、像素翻转或拍摄页已经恢复。

### 追加30：`run_i`首次返回；后续原LDEC固定映射缺页

`run-7gobimqr` 完成两次panel-reverse请求、readback和原reply free，随后首次记录
`RUN_I_RET n=1`，并创建第二个原屏幕对象 `id=0x12d count=6`。但这不是拍摄成功：
`uxengine_res1` 随后在原 `ldec.ko` 崩溃。

内核完整寄存器/调用链（不是根据栈邻接猜测）为：
`ioctl→ldec callback_func+0x3d8→hw_ldec_set+0x2c`，在
`0xfffffffff1055004` 写入时DABT。原平台头文件明确
`IO_ADDRESS(x)=0xfffffffff0000000|x`、`LDEC_IO_BASE=0xf1055000`，
所以这是**应有的固定MMIO VA但页表缺映射**，不是用户空函数指针。
现有DTB窄窗口从 `0xf1056000` 开始，未覆盖LDEC；仅增加映射而不实现数据/完成
仍不足以宣称LDEC恢复。

仓库已有默认关闭的 `MENU_SOFTWARE_LZ77`：保留原资源/stream/bitmap，先验证完整
压缩输入，再执行真实CPU解码并写入原bitmap，不是成功ACK或主机生成图片。
最终源通过sanitizer的边界、重叠、块重置、精确长度、失败不部分写入测试，
且全部九份固定压缩/解码样本逐字节一致。下一次仅新增此明确软件服务；
原LDEC固定映射、IRQ与硬件解码仍单列为未完成。

### 追加31：真实CPU资源解码通过；UX活跃但显示和Still仍未验收

`run-466rkgmn` 正常结束，无LDEC异常；`RUN_I_RET=1` 保持。七次原UXC资源
均经 `RESOURCE_LZ_CPU_OK` 实际解码并写入匹配stride的原bitmap，七次返回1，
无 `RESOURCE_LZ_CPU_FAIL`。第二屏幕对象与持续GPE请求证明UX继续执行。

但结果仍不是拍摄页：census有147个GPE请求、68个软件不支持项；八个
`0x43a7b4100` 候选扫描缓冲全部614400B全零；`MODE_TRANSITION`、
`ENTER_REC_STILL`、JPEG命中均0。正常的后台 `future.get` 不再单独当作根因。

下一步启用已有 `MENU_GPE_RGBA4444` 的有界sprite/copy/fill模型，并以
`MENU_FRAME_OBSERVE` 只读捕获原GRM framebuffer描述符及字节。相关raster源码与
历史sanitizer/生命周期验证版本SHA一致，当前 `GPE_RASTER_SELFTEST_PASS` 亦通过。
该模型仍明确不是硬件逐位等价；只有实际位图/描述符能支持HUD证据，黑ramfb不能。

### 追加32：RGBA位图证明当前是语言页；本run的YC总体验证失败

`run-jzffksml` 中 `GPE_SOFTWARE_UNSUPPORTED` 从68降为0，
`GPE_SOFTWARE_SPRITE_APPROX=68`，并捕获原GRM on/off描述符。
`framebuffer-on-01..07` 均为614400B、非零字节355155、SHA-256
`b127de144dbac6d6b031fa020639331efe78992e649098908a218b685a40cbcf`；
off-buffer仍全零。软件RGBA4444解释图明确显示**语言选择页**，不是拍摄HUD，
且描述符/候选PNG仍不证明CP scanout。

同一run的RC观察为零命中、原始submission/callback身份缺失，最终严格校验抛出
`Uncompressed YC source did not pass byte readback, original RDIMG and RC format checks`。
因此该run只接受RGBA/页面证据，**不接受整体YC/启动完成**。没有放宽验证器；
后续关闭该frame-hook组合，是否与其存在因果关系仍未证明。

从同固件历史首次设置序列恢复到原输入路径：语言页及后续共11次
`CONFIRM(0x1ac)`，在 `0x431` 页面前加一次 `DOWN(0x30)`，之后经过
`0x1f4/0x347` 到拍摄控制页。当前用app32队列 `0x5503e0` 重放该序列，
使用headless OSD/既有GUI模型/原日期服务，不直接写EE或模式状态。
`HEADLESS_OSD_HOST_CAPTURE_PASS` 与GUI/control测试25项+26子项通过。

### 追加33：按用户要求改为简体中文逐页导航

追加32的默认语言静态序列尚未形成结果；对应后台任务已按用户新要求停止，
不计为成功或失败样本。当前改用既有 `--new-ui --firstboot --simplified-chinese`
自动化：从语言页向下定位并选择**简体中文**，随后逐页确认初始设置、保存并核对
每页真实固件画面，直到拍摄控制页。它不使用固定次数盲按替代页面判断，
也不把语言/设置页或候选scanout图当成Still/CP liveview完成。

### 追加34：简体中文拍摄HUD已验收；liveview与自然拍照仍分开

`b26ff71f9` / `run-qzcokwhi` 完成语言页向下选择**简体中文**，随后逐页
初始设置并进入原拍摄控制页。`gtk-input-proof.json` 记录
`automation_completed=true`、`shooting_screen_created=true`；其 `ok=false` 仅因明确
`full_camera_capture_implemented=false`，不是把该导航改写成全相机通过。

主会话已实际查看：
- `gtk-simplified-chinese-selected.png`：高亮“简体中文”，SHA
  `b51c4da5c04e7e1fb7f7ea1026cb18a52d126147aca2f9a1aa7201360d803fb7`；
- `gtk-shooting-after-setup.png`：`J-FINE`、`14M`、`AF-S` 和拍摄控制图标，SHA
  `8718e2251bd284e3c75c91bde990f55cbb417b881b7b254c14f7ae3095944242`。
原screen序列包含 `0x347→0x343`；证据来源是原QMP ramfb LCD+实际GTK窗口，
不是AP灰度镜像或主机生成图片。**中央取景仍黑，故CP liveview未验收。**
该run未按快门，mode/Still/JPEG零命中不解释为失败或硬件缺失。

中文虚拟配置已保存：`language=25`、2390264B、SHA
`c457ea35c1762c2458597b1056ea0bafc4cca62dca03771a53dd241878927f6d`，
`language_date_consistency_verified=true`；仅恢复此虚拟run的派生副本，未读真实setting。
虚拟SD导出 `fsck_rc=0`，但尚无JPEG/MP4内容验收。

当前 `bb40a1a5a` 从该中文拍摄配置恢复，使用app32的
半按保持→全按→释放半按，观察自然Still/JPEG/MPR/Fsys；不直接写EE/ready，
不把generic JPEG、配置ACK或已有SD fsck当作照片通过。

### 追加35：自然快门的页面判据与正确四记录输入

`bb40a1a5a` 在QEMU启动前因restore要求显式 `A7C2_SETTINGS_PERSIST=1`
被拒绝，未执行固件或快门；已补齐为 `b5549e65f`，不改写为拍照失败。

只读调查核对全部502份当时权威console后确认：历史没有任何一组run同时覆盖
当前自然入口/JPEG探针与实际快门；所以历史零命中不能解释为Still被拒绝。
`0x343` 单独不是拍摄页判据：完整序列为
`0x347→0x343→0x1e6教程→0x343→id=0/count=565`，并需实际HUD内容。
当前 `run-qzcokwhi` 同时满足控制序列、教程关闭和LCD，故页面结论不变。

默认HUD已是Still switch0，不要求重复MODE_STILL。正确app32输入是四记录：
`0x1f1/status1` 半按保持→`0xa7/status1,0` 全按→`0x1f1/status0` 半按释放。
旧body probe的半按点按后再全按点按没有测试“半按保持到全按”，不能替代当前实验。
`b5549e65f` 同run启用natural-start、JPEG、MPR/Fsys与严格YC观察，正是补足该覆盖缺口。
后续仍须普通MPR Still分支、async writer、Fsys completion和独立JPEG decode；
generic JPEG命中或API提交0不够。

### 追加36：两次静态快门未形成消费证据；app32键码与提交语义纠错

`b5549e65f` / `run-tkfcihnl` 的严格YC校验通过，但四条静态命令全部为
`INJECT_KEY_BAD_ARGS`：app32必须带 `--app`，不能只把队列地址换成 `0x5503e0`。
所以该run实际发送为0，不是Still/JPEG拒绝；headless OSD导出也为1。恢复配置的
`FIRSTBOOT_DATE_STATUS=0`，故这份派生备份不能声称完整恢复“已完成首设”状态。

随后 `bcf272bee` / `run-777jwuoo` 修复 `--app` 后取得22条
`INJECT_KEY_SEND result=0 bytes=32`，但静态序列错误使用了legacy导航码
`0x43d/0x431`；已成功的 `run-qzcokwhi` 明确使用app32 `ENTER=0x1ac`、`DOWN=0x30`。
本run没有对应的新 `INPUT_EVENT32`，第23条（DOWN press）在injector内阻塞，未产生
send记录，后续快门从未执行，最终诊断等待超时。启动前还出现89个重复 `0x66`
输入事件，与成功GTK路径不同；当前仅记录该差异，不未经对照就归因于YC/SMP2。
`INJECT_KEY_SEND result=0` 今后只称**injector提交成功**，不等于原消费者接收。
该run没有summary或自然拍照通过结论；Still/JPEG/MPR均未得到本次有效测试。

输入实现已增加失败证据文件和严格发送计数，并新增固定四记录 `shutter_cycle`
控制动作：`0x1f1/1→0xa7/1→0xa7/0→0x1f1/0`，所有释放均尝试，返回仍只表示
提交结果。下一实验复用真实GTK逐页验证，要求 `id=0/count=565` 后才允许动作，
不把控制回复当作照片完成。

### 追加37：独立CMOS源的代际、租约和字节预言机（尚未接入YC）

`cmos-source.c/.h` 已先独立于运行中的YC链修复：默认stride和总尺寸用宽算术验证，
拒绝不能容纳16B身份头或不能用正 `int` 返回长度的几何；行填充实际写零。
帧checksum覆盖帧号、像素和padding，仅将checksum自身8B清零，因此篡改帧号也会
被拒绝。`cmos_frame_probe` 要求完整的 `stride*height` 容量并比对存储checksum，
失败时不输出一个看似有效的身份。

生产者使用严格递增帧号和**单租约**：`fill`生成并发布一帧；未以相同指针和帧号
`retire`前，覆盖（包括另一目的地）及重新配置均拒绝。退休不重置代际单调性。
测试图使用非对称x/y系数及逐lane偏移，9×6、2Bpp、stride24的3:2用例与独立
Python逐字节预言机完全相同；generation/checksum/payload/padding四类损坏均拒绝。
ASan/UBSan与断言覆盖错误指针/帧号退休、活跃租约重配、重复/倒退代际、短容量
不改写及极值几何。该组结果为 **3 passed + 4 subtests**；只证明独立源合约，
尚未接入unit431/RC/SA，不是自主CMOS时序、动态liveview或原固件拍摄完成。

### 追加38：natural GTK的安全清洗需要显式成像profile

`b54bb22f5` 在创建新run之前以 `VM 控制通道已关闭` 结束，因此没有页面、快门或
固件阴性结果。核对 `start-menu.py` 后发现 natural boot 会刻意清除调用方的
`MENU_* / QEMU_* / SONY_*`；此前命令行看似设置了YC/RC/SMP2，实际并未传入，
而保留下来的 `A7C2_RESIZE_WATCH=1` 缺少其必需的YC依赖，启动预检不能成立。
这不是一次自然拍照失败，也不能复用前一个run作为它的证据。

现新增显式 `A7C2_NATURAL_IMAGING_PROFILE=1`：只在natural profile中展开固定的
本机QEMU/DTB、SMP2、未压缩YC、RC/SA参考完成、120秒settle和自然/JPEG/Fsys观察，
不接受调用方替换QEMU路径，且与PNG preview、USB network和data-only SA互斥。
`test-start-menu.py` 已覆盖展开值、覆盖外部研究开关及非法组合；qemu manifest和
summary记录 `natural_imaging_profile`，防止再次把“环境变量写在命令里”误当成
实际运行配置。后续 `b96f4f75e` 仅通过该显式开关启动GTK中文逐页与快门实验。

`b96f4f75e` 创建 `run-g268vr4y` 后仍在QEMU启动前停止：实际receipt路径落在默认
`runtime/sources/qemu-11.1.2`。第二处覆盖来自 `camera_ui` 默认启用独立USB网络，
`prepare_profile()` 因而替换了候选QEMU；这不是固件或RC构建证据缺失。现自然成像
与PNG preview一样明确关闭USB网络，VM层还在启动任何进程前拒绝该冲突并保留
回归测试。重试为 `b9c3640d2`，未把前两次宿主预检失败写入固件失败统计。

### 追加39：重复0x66可以合法；保存栈把输入停滞定位到GRM绘制等待

只读调查 `a994ae6b` 已交付（达到轮次上限，未宣称穷尽）。原 `libObj`
`InfraInput::SendAttachEvent@0xcd9b4` 的诊断及访问确认32B事件word3是
`prev_status`、word5是`repeat`、word6是`from_type`，不是ready字段。
原repeat线程/计数器可以产生 `0x66/status1/prev1/repeat递增/from1`；计数器在
`0x7fffffff`饱和，当前没有已证的`0x58`退出条件。appFw还会在缺少initial-press
状态时把repeat转换为 `0x20000001` 无事件，因此原始repeat记录不证明custom回调执行。

主会话继续复核 `run-777jwuoo` 已保存的非停止式样本：TID441睡眠于
`osal_wai_sem_tmo`，前后syscall边界一致。结合原 `u_osal_wai_sem_tmo` 栈布局、
16B对齐且递增的帧记录、同run可执行maps和窄窗口原反汇编，得到：
`App main→0x1798f24→libObj drawFramebuffer→0x1636f8→0xf8df0→0xf843c→0xf7724→0x102798`。
实际等待sem为 `0x02886043`，不是已证的App输入接收循环退出。
原 `ExternalOSDIF` 的 `0x6003/0x6005` 处理分支有对应unlock/callback路径，
但本run谁持锁、哪条回复未完成仍未知。详见 [GRM等待证据](GRM-WAIT.md)。

仅扩充被动采样至 `ExternalOSDIF/grm_result/grm_gpe`，上限16且列出跳过项；
13项主机回归通过。没有signal解锁、空ACK或guest状态修改；当前运行不因此改写为通过。

### 追加40：unit431退休注释撤回，原op28提供引用/open而非完成通知

只读调查 `4ccb4770` 已交付（轮次上限，非穷尽），主会话核原字节确认
`0x1d42f8→0x1d4964` 是unit639输出drain；`0x1d4a4c` 显式加载类型0x639。
旧“下一IN1/2300 dequeue即可退休输入”的注释撤回。
last-pin keeper的image Free `0x1c300c`/Share `0x1c3184`，与RC作业
`job+0x6c` input Free `0x1d2744` 分离；二者都不单独证明所有fan-out读者退出。

原 `dmm.ko` `.text+0x5408` 的op28 handler及 `GetUnitInfo@0x97d8` 已静态核：
reply+0x0a是reference、+0x0c是open，handle generation先验证；Free reference>1时
只减一但仍返回0。现有op2a分段映射和三次RC callback没有补齐这组所有权证据。
本轮仅改正注释，不向guest新增op28，也不覆盖动态帧。详见
[像素退休合同](yc-inject/PIXEL-RETIREMENT.md)。下一代写入需同allocation/generation身份、
生产者独占refs1/open0以及无可再取得旧引用的已发布作业；计数快照本身也不够。

后续中性源安全修复仅把重复填充改成首次发布前填充一次，后续完整摘要日志和三次
提交保持；不新增动态内容、格式或完成。实际builder的只读像素页测试及失败资源
测试共4项通过，AArch64编译/链接通过；临时构建未安装，当前运行仍绑定原receipt。

### 追加41：默认关op28观察及真实短回复边界

新增显式 `A7C2_YC_OWNERSHIP_OBSERVE=1`，只在未压缩YC诊断源启用，两个有界查询
以不同tag绑定原unit431 allocation，不做Share/Open/Free或完成注入。原
`dmm.ko .text+0x5e90` 的长度表与 `0x8550–0x8558` 已补核：op28回复40B、source
`0x0061003c`。因此新解码器严格验40B和来源/当前tag/type/capacity；不能照旧注释
把0xd8请求尺寸当回复尺寸。通用回调也已改为真实长度有界复制，避免旧216B盲读。

host校验保存原hex并拒绝重复、乱序、缺失、错误来源/尺寸或打印字段与原字节不符；
即使refs1/open0也明确不授权覆盖。新模块/源码receipt检查阻止旧二进制静默忽略开关。
15项host测试、AArch64临时编译/链接及ABI检查通过；未安装进运行中guest，
未把模型/夹具的计数当作原固件计数。用法与边界见像素退休合同。
