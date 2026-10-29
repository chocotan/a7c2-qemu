# YC IN1 注入实验（任务 #8）：合成帧 → 原 av-cam VDT 服务

**这是 AP YC 输入诊断与可选灰度镜像，不是 CMOS/Bayer 模拟完成，也不是 CP VDF/VPH 已恢复。**
原 av-cam 已在隔离 QEMU 中读取元数据并完成 RDIMG 搬运；RSIZE_YUV 可提交缩放，
但没有转换完成、`200b:2300`、照片或录像证据。下面“运行记录”保留了各失败版本，
其中旧消息解释以 [协议更正](../PROTOCOL-CORRECTIONS.md) 为准。

## PNG 输入与 3:2 画幅

本实验工作画布为 1920×1080（UVC 支路要求），**不是传感器的 3:2 原始画幅**。
PNG 等比缩放并居中留边：3:2 图在该画布内为 1620×1080，两侧各留 150 像素。
当前PNG路径只把8-bit灰度字节交给 `YcCompress=2` 实验缓冲。
**已核原指令：此设置会选择RC format1并启用DCD解压；这些灰度字节不是合法压缩YC。**
因此现有PNG路径仅供原AP字节搬运/提交与宿主诊断镜像，不能用于转换正确性验收。

默认关闭的 `MENU_YC_UNCOMPRESSED=1` 是另一实验源，不能与PNG/raw输入同时启用。
它使用原DMM unit type431（extent561，可缓存根池424000000）尝试分配5MiB单元，
检查真实容量足够容纳5184000B后填所有byte lane=128，
metadata Compress=0。中性常量不预设Y/Cb/Cr顺序，也不冒充彩色CMOS。
此前type644候选只有2MiB，已被写前检查拒绝；unit与extent编号不同，不再混用。
`run-7lwl11ti`已证unit626和原RC format0，但RDIMG需要5184000B而4MiB不足，故不验收。
16-bit RC有效矩形为4147200B；原RDIMG的M[0]=10存储公式另需5184000B，两者不能混为一谈。
unit431在`run-ks9_80je`已通过完整存储范围与原RDIMG/OUT1/format0 FHD请求验收；
不代表压缩算法、component order或后续真实输出已恢复。
mode marker只在本轮guest创建，选定镜像含残留marker时拒绝启动；原注入模块摘要另行校验。
此实验要求 `A7C2_RESIZE_WATCH=1`，验收必须有完整5184000B QMP读回、guest FNV、
原RDIMG消费、OUT1及已核原指令的format0选择；输出与完成仍单独标记未验证。
所有事件必须绑定实际DMM分配、帧发送handle/地址及QMP读回地址，RC setup必须成功。
资源取得后初始化失败会记录`YCIN_INIT_FAILED`和`YCIN_RETAINED`，保留模块所有权状态至VM退出；
内核模块加载返回成功不是输入成功，不能重试或将`MOD_OK`单独当作验收。

RC中断还有独立的CPU前提：原LIRO记录要求CPU1，离线回退路由CPU0不会修改该谓词。
`QEMU_CPU_COUNT=2`默认关闭；启用时同时设置QEMU双核、固定地址DTB的PSCI CPU节点及双核PPI mask，
不改原固件，原单核输入DTB保持不变。该配置需另验两核online和原注册/handler执行；
它不发中断、不设置完成。`QEMU_SONY_RC=1`另将GPEX搬至外部SPI244..247（旧12..15与SA冲突已撤回），
要求应用`runtime/analysis/device-models/rc-board.patch`并重新构建QEMU；只改DTB会被拒绝。
实验RC参考后端已接入并由原B/C请求产生完整输出及成功回调；它不代表硅片颜色算法。
新版板级候选另加f2800000配置页的普通存储/读回，并搬移GPEX，仍须运行验收；
它没有SA完成中断或像素转换。

从本成果根目录运行有界输入验证：

```bash
cd runtime/analysis
QEMU_SYSTEM_DIR="$PWD/../../source/build/qemu-pcidma-work/build" \
QEMU_SYSTEM_BINARY=qemu-system-aarch64 QEMU_SONY_PCIDMA=1 \
MENU_DTB="$PWD/qemu-virt-board/virt-pcidma.dtb" MENU_EXTRA_MODULES=safe \
MENU_LOAD_PCIEATU=1 MENU_VPANEL=1 MENU_YC_INJECT=1 \
MENU_YC_INPUT_PNG="$PWD/input.png" MENU_YC_INJECT_DELAY=45 \
MENU_SETTLE_SECONDS=130 MENU_DIAG_TIMEOUT=90 bash run-menu-probe.sh
```

输出 `yc-input-proof.json` 核对 initramfs 身份、guest DMM FNV、QMP 像素单元 SHA-256、
RDIMG 完成及 OUT1 投递；有任一项未通过即退出失败。`probe_collected=true` 本身不算上屏。
模块需在改动后执行本目录 `build.sh` 构建安装，再启动；运行脚本会重建 initramfs。

### 已实跑的输入证据

| Evidence | Finding | Path / 边界 |
|---|---|---|
| `run-iu87ljhx`：initramfs SHA-256 与输入一致，DMM FNV64=`d25017aa3a4b6a30`，三帧 RDIMG CMP | 16:9 测试 PNG 的真实字节进入原 AP | 无 QMP 全量读回；不证明显示 |
| `run-ju47ps0l/yc-input-proof.json`：输入、选定 initramfs、QMP DMM 全量读回 SHA-256=`e237d48fb66d6f9b66ec7f86490f8080d04b8149d53d613f55d44ed397f93d77`；guest FNV64=`a2acb608306e41c5`；3 CMP、3 OUT1 | 3:2 源正确留边后的同一字节缓冲被原 RDIMG 引用处理 | `runtime/analysis/menu-runs/run-ju47ps0l/yc-pixel-readback.bin`，2,073,600B；1080行逐行确认两侧150px零、中间1620px非零，红区76、蓝区29 |

这些是输入/搬运证据，不是 YUV 转换完成、原 CP 面板、拍摄页业务状态或照片证据。

`run-xa7qfksg` 的自然 profile 同样通过三帧搬运与完整 QMP 读回，输入 SHA-256 为
`7e8eba41de18eb3eb529df066f4e53de30cc62caca17eca95cfdac2a8b4d00c0`。
`yc-preview.png` 为灰度输入镜像，`yc-preview.json` 保留原 OSD 容器与输入证据；
该轮 OSD 捕获全透明，**没有拍摄页 HUD，不能当作拍摄主界面已恢复**。

GTK `run-vy9cu13z` 使用较早载入的快照代码，在第一帧摘要比较处失败，未完成首设或快门操作。
卡尚未挂载，关闭路径的 flush/STOP 超时而保留该 VM，导致后一个 GTK 观察任务等待运行锁超时。
主会话经原串口只读核验文件后端 globals：owner、drive、retired、在途I/O、busy、
previous/cancel 均为0，配置已调用1次；核验前后状态相同，guest `/image_mmca` 全量摘要
`61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727` 等于初始128MiB卡夹具。
仅在此“未挂载、无写入、卡未变”证据齐全后关闭该拥有的测试 VM，并确认退出与锁释放。
`recovery-pristine-card-proof.json` 保留原始读回出处；没有把失败的 flush 或未导出的卡标成成功。
原有已挂载卡的 flush/冻结/导出保护没有放松，其他会话未被关闭。

### 失败与复用保护

- 未明确请求 PNG 时，选定 initramfs 中只要还含 `simulation/yc-input.gray` 就拒绝启动，
  包括 `SKIP_REBUILD=1`，防止把上一轮 PNG 冒充默认合成源。
- 预览 admission 以当前 run、manifest 摘要及源摘要绑定。guest DMM FNV 先通过时，
  即保留 `yc-preview-admission.json` 的 pending 记录，但**不显示像素**；真实 OUT1 到达后才放行。
  即使摘要和 OUT1 分别位于串口日志轮换前后，也不会丢失准入证据。
- 模块初始化失败会按原 `osal_uipc.ko` ABI 调用 `osal_unreg_msg_queue_cb(qid, slot)`，
  等待活动回调退出；若注销失败则保留模块代码并报告 `YCIN_INIT_FAILED/YCIN_RETAINED`，
  **不报告 `YCIN_INIT_DONE`**。本诊断不提供卸载入口，共享单元及映射仅随隔离 VM 关闭回收，
  不使用强制 `rmmod`。该措施防止错误 PNG 导致回调落入已卸载模块代码。
- 宿主回归：34 passed、13 subtests；含真实 C init 包装器的错误分支 mock 检查、
  stale newc 文件拒绝及跨日志轮换 receipt 回归。没有实际注入内核注销故障；
  原 GTK 全量回归的 OFF 按钮断言失败另行保留，不声称全套通过。
  后续补充 split-evidence（日记轮换前只有摘要、轮换后才有OUT1）回归；
  输入、探针和调试器安全的联合回归为87 passed、13 subtests。

本地 GTK 窗口的可选灰度镜像入口（与 USB 网络 profile 暂不兼容）：

```bash
A7C2_PREVIEW_PNG=/absolute/path/input.png python3 runtime/analysis/camera_ui.py
```

只有原 AP OUT1 已交付输入帧，且 manifest 与 DMM 读回摘要吻合时，才把该输入灰度
镜像合成到原 AP OSD 下方；界面标记“模拟灰度预览 / AP已消费 / 非CP面板”。
这条宿主镜像通道**不宣称**原 VDF 面板转换、CP liveview 或拍照成功；MP4 尚未接入。

## 依据（全部经 main 核字节）

- 注入合同：`1000:0102` 56B 到 av-cam VDT 本地队列 `0x827e073f`：
  `+8` source `{0,2,1,0x905a0048}`（替身 CP VEF OUT1）、`+0x18` destination `{0,1,1,0x827e073f}`、
  `+0x28/+0x2c/+0x30` 元数据 SDS `{type,handle,offset}`、`+0x34=0`。
- K `1dc570` 校验 sub-op、dest type==0、dest index≤2，并把消息字段与 context 内 pin 连接记录逐项比对；
  未匹配/未建连时走 `1dc69c` 回复路径。注入被接受 ≠ 被消费。
- 元数据 = SSYC blob（主头 +0xc entry 数、+0x10 首 entry；ETRY +0 marker/+4 cate/+0xc payload偏移/+0x10 容量/+0x14 链），
  cate0=ImageSizeInfo(0x48)、cate1=YcState(8)、cate2=ImageOutTimInfo(0x40)、cate5=CameraInfo(0x3a8)。
- **双单元**：原 dmm.ko 分配元数据 type `0xe0b00` 与像素 type `0x643`；
  op20 分配、op21 增 Share、op2a 查真实地址。帧重复引用一个持久像素单元，
  每帧单独分配元数据；不可把 op20 回复的首地址字段直接当单元地址。

## 运行

```bash
cd report/virtual-cp/yc-inject && bash build.sh   # 构建+ABI校验+安装到 runtime
cd ../../../runtime/analysis
QEMU_SYSTEM_DIR="$PWD/../../source/build/qemu-pcidma-work/build" \
QEMU_SYSTEM_BINARY=qemu-system-aarch64 QEMU_SONY_PCIDMA=1 \
MENU_DTB="$PWD/qemu-virt-board/virt-pcidma.dtb" MENU_EXTRA_MODULES=safe \
MENU_LOAD_PCIEATU=1 MENU_VPANEL=1 \
MENU_YC_INJECT=1 MENU_YC_INJECT_DELAY=45 MENU_SETTLE_SECONDS=130 bash run-menu-probe.sh
```

## 运行记录

- `run-2mlb8e_4`（v1）：cb ABI 误判（实为 `cb(msg,cookie)`，osal_uipc.ko+0x28e4
  `ldp x2,x1,[rec,#32]; add x0,node,#0x18; blr x2`）。v2 改为正确 ABI、事件驱动。
- `run-mvu9m48m`（v2）：40B op20/type 0x63a 被 dmm.ko 拒（status=-1）。
  av-cam 真实分配是 K `0x1d4a4c→0x278eec`：**0xd8B op21，type 0x639，size@+8，
  magic 0x1111@+0x14，option@+0x16**，队列 `0x8061003c`（w21 bit15 经 bfi 选 0x9/0x8 前缀）。
- `run-x2g90937`（v3）：`0x827e0751`/`0x827e0811` 均被其他客户端占用（double-register/stale
  8020），改为 4 候选自注册（0x8aa5-8aa8 0751）。
- `run-deeais2q`（v4）：证明**本地队列回包在 `osal_snd_msg` 内同步 inline 投递**——
  时间戳先于 send 后 printk，且 op 码跟随请求。op21 type 0x639/size 0x80000 被 **status=-5** 拒。
  v5 改为发送前置标志 + 同轮三变体（0x639/512K、0x639/720p、0x63a/512K）+ 8021 全量转储。
- `run-mmar9l9h`（v5）：直发 op21 把 size 当 handle，Share 代次校验报 -0x205（dmm.ko `0x4dc8`
  转 -5）。核出 0xd8/0x1111 协议两段式：**op20 Alloc（+4 type/+0xc size；回 +0xc handle、+8 段数、
  +0x18 段记录）→ op21 Open/Share（+4 type/+8 handle）**。
- `run-csn9nk4k`（v6）：op20/op21 **均成功**（handle=0x408、段地址 0x4fea00000）。
  但错误地把段地址再加 0x400000000 后 memremap（0x8fea00000 不存在），写元数据时
  synchronous external abort（memmgr 线程，已留 crash 证据）。**回复段记录就是 AP 物理地址
  （0x4fea00000=DRAM 顶部保留池），不需要任何换算**；v7 加 0x400000000..0x500000000 边界防护。
- `run-07tx5dqb`（v8/v9 合并判读）：注入及 200b:0304 均入队成功，但 YCSTAT 在 ~1875 guest 秒后
  深度仍为 1/2——**av-cam VDT 服务线程在本 guest 不消费 827e073f**：队列已建，服务未激活；
  正常启动中 appFw 从未向该队列发 pin 连接/配置。
- `run-e5zrce2t`（vpanel 联试）：vpanel.ko 按 #4 合同应答 `VPANEL_118 sel=3 result=0 dst=0x81cf618f`——
  虚拟面板完成格式/路由全对，但**下游零变化**（YCSTAT 仍 2）——证明 VDT 激活不在面板完成这一环。
- `run-_jq0dkz9`（pcieatu 修复）：**根因修正**——此前 `MENU_EXTRA_MODULES=safe` 跳过 pcieatu 导致
  liro 缺 `pciatu_map/unmap` 失败、av-cam 从未装载（osal 对无接收者本地队列按需建对象、rc=0 不代表有服务）。
  加载 pcieatu 后：av-cam 完整 init（liro returned 0）、**60+ `liro-kliro_N` 服务线程**、
  注入的 0304/1000:0102 **被实际消费**（YCSTAT 深度 0）。
- `run-y10zgz_i`（ulog 实证）：0304 被接受（NV12(HD720)、dst=我们队列），但 1304 回包发送失败
  （err=0xFFFFFFE0, vdt_util.cpp:20）；1000:0102 到达 PIN 层（`PARAM_PIN_SEND: [905a0048]YC_OUT(1)->[827e073F]YC_IN(1)
  unitType=0x639 unitHandle=0x415`——我们的 DMM handle 被正确解析）但报
  **`Received PIN without PIN_CONNECT!`**（vdt_pin.cpp:597/264），SELF_CREATE_FLOW 后 free_unit err + LOG_STOP。
  **缺 PIN_CONNECT（拓扑连接）**：消息合同调查中。
- `run-1acy435w`（PIN_CONNECT 联试）：PIN_CONNECT 合同（子代理+main 核 K `953f8/95680/9581c/95810`）
  实跑被接受：`[Rcv]PIN_CONNECT`、`PARAM_PIN_CONNECT:s[905a0048]YC_OUT(1)->d[827e073F]YC_IN(1)`，
  拓扑边建立，"without PIN_CONNECT" 错误消失。新阻塞：`Not find image_size_info_entry
  in_pin_handle=0x000415`（vdt_pin.cpp:615/289）——**image_size_info 是独立消息，须在 0102 前注册**
  （字符串 0x425c29 "received image_size_info, but waiting YCPin" 为证）；合同由子代理续查中。
  另：1304 回包发送仍失败 err=0xFFFFFFE0（vdt_util.cpp:20），性质待查，暂不阻塞数据面。
- `run-53_61mzf`/`run-yfurzlm2`（地址域修正）：**op20 回复 +0x18 的 0x4fea00000 是恒定字段、
  不是单元地址**（被拒回复也有它）。用 op2a/op24 复刻查得真实单元地址 0x4f8500000、
  长 0x1518000；主机侧 pmemsave 证实 SSYC/ETRY/ImageSizeInfo 全部正确写入。但 av-cam 仍报
  `Not find image_size_info_entry`——内容正确说明**它没在读这个单元**：元数据路径经
  `0x2f514` thunk（API 表 +0x628，ldec 运行时注册）做地址转换，随后 SsycReader(0x94258)→9338c→933c8→93e70。
  转换语义与逐项校验清单由子代理调查中。另已修双重注入（sentinel 文件）。
- 通项：guest 电源序列约 guest 4680s（wall 比率 15-24x 不定），ulog/单元 dump 用 YCSTAT 事件触发。
  （icount 约 15-16 倍墙钟）使 QEMU 退出，host 诊断写入 BrokenPipe——注入证据在此之前已入 console。

## 判据（逐级，不得跳级）

1. `YCIN_REGISTER rc=0`（回复队列注册）→ `YCIN_DMM rc=0 handle=...`（原 DMM 分配成功）。
2. `YCIN_SEND rc=0` 只证明入队；`YCIN_REPLY op=8102`（或 av-cam 错误日志）才有协议层信息。
3. 消费证据 = av-cam flow 活动：`200b:1381` 回调 / SA 提交 / `200b:2300` 通知（userspace observer 在 `0x82d908f2` 可见）。
4. 上述任一缺失即如实记录为未完成，不得以 `YC_INJECT_MOD_OK` 冒充成功。

已知未闭合：pin 连接记录是否在本启动场景建立、0301/0304 配置前提、+688 传输 provider、
输出 stride/UV 偏移、JPEG 直通判据（G+c4==2 的 DataContent 来源）。
