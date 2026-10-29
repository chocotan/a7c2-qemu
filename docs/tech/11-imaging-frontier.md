# 启动流程 11 · 成像与录像：功能模型及原固件成片前沿

**2026-10-29：尚无原固件生成的有效 JPG/MP4，`capture_verified=false`。** 已有实际软件像素、光学/对比度AF、JPEG/H.264核心、原SDK适配及多轮原生VDF消费；它们尚未与原AP→源帧→encoder→原MPR/Fsys→虚拟SD连成成片闭环。最新功能profile还需完整首启复验，不能由旧默认HUD/MENU短时通过推断当前稳定主界面。

完整功能矩阵与分阶段时间线见[当前进度](2026-10-29-current-progress.md)。变量见[索引](README.md)；本页只整理已有源码/报告，没有新实验。native与完整dump路线分别记账，不互借动态结论。

坐标约定：AppFw 用 ELF VA（按 PT_LOAD 换算）；`av-cam.bin` 记为 K，
地址是 raw 文件偏移，运行 VA = `0xffffffc001000000 + raw`；
CP 用 `CPVA = raw + 0x108000`。三套坐标不能混用。

## 0. 当前实现与验收分层

用户批准的 `virtual-functional-camera-v1` 明确采用软件 RGB888 总线，严格profile保留拒绝策略。实际Core经 acquire→render→consumer_read→retire，使用真实JPEG/H.264编码器；INIT只探测/渲染并退休一帧，不能当编码消费。**物理ASIC兼容、原CP模块/RAM/RTOS仍false**，不以host另造媒体冒充原拍摄。

| 环节 | 当前证据 | 未完成 |
| --- | --- | --- |
| 原图连接/控制 | 13边曾在同轮由原AP消费；mode1 ACK与1748B通知已有原free证据 | 传输完成不是AP业务应用或像素就绪 |
| VDF | run52的0141 exact global `80946189`绑定及独立1141 receive/free；六个真实RGB周期，每帧921600B源/sink读回一致 | 原取景UI消费未通过；该global是本run值，不是固定Sony队列 |
| 时钟与BB初值 | 实际State128 FPS→20a6 `(fps,1)`，默认30/1；pgf已越过旧零pair fatal并完成六VDF+0111 | pgf停0166初值`0,0,8,7,1,1`误拒；精确identity已修，旧失败保留 |
| 直方图 | core→guest组合268项；同sink RGB计算软件Y/R/G/B四段256个u8柱高，独立逐字节一致/peak255，三lease退休 | 仅首个enabled/mode1；原AP/UI、连续更新和物理bin语义未验 |
| 原JPEG适配 | 独立Main/MainComp、原reply-free/长度读回、同文件EXIF Main/Thumb及普通可读VMA guard已组件验证 | 原MainP、key104a/P128 writer、ResizeEnc1500 cmd2、retained RGB及1006/event9自然producer未闭合 |
| 原媒体保存 | MPR/Fsys源范围/回调/原读回/导出/解码checker已实现 | 没有本轮原媒体作业或最终JPG/MP4 |

最近完整基线为`unified-camera-4b3kb4kd`：5568 tests /7057 subtests、host/guest构建和双原glibc2.25 ABI通过。后台3006、队列绑定/记录/checker及完整首启修复已纳新整批；原AP新运行与成片验收仍未完成。旧694个owner组件和其它定向结果保持各自范围，不相加作完整新总数。

## 1. HUD 和控制回复 ≠ 成像启动

HUD 上的 `AF-S` 是 `model+0` 的显示翻译，不是合焦反馈。
拍照模式的 EE 控制链（`sequence_start_ee`）会向 `0x90030001` 发
24B、cmd `0x3003` 的请求，调用方读 16B 回复的 `+8` 并与 `0xf000` 比较——
但这份回复没有像素地址、帧序号或帧消费证明。

边界：不预填 f000、不写EE=1、不以OSD截图代替原像素。严格物理profile的合法启动前置仍需源证据；功能profile仅在真实Core probe/数据读回及原消息生命周期后给出明示软件回复，不能提高物理ready。原代码里mode2且EE=0时会直接离开拍摄入口（`0x2688ef8`），但最新qqu还在更早的后台等待，本轮尚未到3003。

## 2. 镜头与曝光：从 4073 等待追到 2040 生产者

正常拍摄初始化的通知链：

1. AP 的 `CamUserIf` 向 `0x90030001` 发 12B 的 4073 请求并等回复；
2. 再等 `0x80020002` 上的 2040 快照——AP 侧 `memcpy` 0x6d4B 进本地快照
   后兑现 promise。**AP 登记 2040 本地指针 ≠ 向 CP 发 2040 请求**。
3. CP 侧由 generation 比较驱动：published 与 shadow 不同才遍历
   76 条 getter 拼出 2040。generation 不在线上包头，`+4` 那个 word 是 0；
   AP 固定拷贝不校验长度/generation——"收到"不自动等于"新鲜"。

已核的编码（只证明编码，不证明设备已给值）：

| 量 | 编码 |
| --- | --- |
| F4 | u16 400（F 数 ×100） |
| 快门 1/125 | u16 分子 1 / u32 分母 125 |
| ISO100 | CP 字节 `0x0b` → AP 枚举 5 → 数值 100 |

`LensCommunicator` 的 op0/op1 是外部维护查询，不能代替正常初始化链。
严格源合同不允许全零快照、强兑promise或以d018控制动作代替2040消费。独立功能profile已定义76块软件快照：2012固定、201b/2044/20a6三块投影、72块明示零策略，完整1748B；20a6必须来自实际State128 FPS及原AP可接受的canonical pair。run52的零pair fatal与pgf的30/1实际推进分别保留，不能因模型政策而声称原CP writer/物理参数已恢复。

## 3. 像素：从编码消费者反推 YC 描述符

`sdf_encode_jpeg@0x34f6fd0` 读输入描述符：`+0x20` 描述 PA、`+0x28` 长度、
`+0x30/+0x32` u16 宽高。描述符的分配走 DMM（SID `0x0061003c`），
回复给 handle/PA/长度——但**分配和填写完成不等于帧生产完成**。

resize 请求发往 `0x82830752`（68B，`2000:0003`）；接收端定位在 AP 侧
`av-cam.bin` 的 `tsk_sdt`，内部改投 `0x82830753`。有一条真实的分段
容量检查：按 CanvasX×CanvasY 和 YcCompress 算 required，再核段容量减
offset——它不是位深公式，也推不出单 plane 或连续内存。

严格物理路径仍缺YC字节/位顺序、planes/stride、DMA完成及generation/lease。功能profile不再等待未知硅片packing，而是明确软件RGB888；真实VDF已消费921600B源/sink。下一缺口是原AP选择的retained RGB、SDK frame MainP、key104a的128B writer、真正ResizeEnc1500 cmd2与自然1006/event9 producer，不能由独立测试图样或metadata SDS替代这些绑定。接收端在AP也不证明原传感器生产者必在AP。

原JPEG的Main `1226c4` 与Without_Pin `11b654` 是不同入口；Main ACK原Res `120e64` 返回0但不退租，独立MainComp `122dfc/122b44`完成DONE并由原代码写回长度后才退租。实际receive→真实free0→原Res的顺序、普通可读VMA、输出lease与完整内容均须验证。Main/Thumb目前各自render，跨selector同一sensor frame未证；Screen的原MPF/layout也未闭合。

## 4. "成功"路径要核原检查

踩过的坑（已撤回）：把 `ValidState` 当 ready 门——五个直接调用点全传 0，
JPEG 函数的 434 条指令没有读回它再分支。另外 JPEG 路径两次调用接收
wrapper 都不检查返回值：要分清"队列有效但无消息"（无限阻塞）和
"API 报错返回后继续"（可能留下 status0/length0）两种失败。
"上层没检查"不是模型可以空 ACK 的理由。

## 5. Still 编码队列

`mc_still_enc_encode_frame` 向 qid `0x8057060a` 发 `2003:010e`，
请求头长 `0x60`（96B——早期"60B"是十六进制/十进制歧义）。
回复 `+0x10` 是 status，`+0x18` 是唯一读取的 8B 值——
旧说它是"JPEG 字节长度"已撤回，语义未闭合。
诊断字符串里出现的是 `encode_heif`，不能把这队列直接叫 JPEG 执行器。
该队列的实际 receiver、输出写入和格式绑定仍未闭合；
AppFw 里搜不到不等于所有镜像都没有消费者。

## 6. Movie：先配置往返，再追 ES/info

`Codec::EncOpen` 用调用方**预先提供**的 ES/info/status 缓冲，
发往 `0x8055001f`——那是 `InfraAvbbcIf` 的控制接收/转发端，
**不是 H.264 执行器**。EncOpen 返回成功 ≠ 编码了一帧。

真正写出要 writer 取得可消费条目：`WaitForVideoInfoAccumulation`
在空列表也能返回 0，条目存在、ES 有效、payload 非零、搬运完成都要另证。
共享读索引受最慢消费者约束，不能简化成"消费一帧就 free"。
原软件MP4封装已定位，不等于得到有效MP4。功能Core已能实际消费RGB并产出逐帧H.264与真实packet/PTS；组件成功不证明原writer消费。原Movie初始extent/source lease、ring、自然Stop→Close、Combine最终MP4贡献及FSYS_SYNC内容仍缺同轮证据。

## 7. 保存链终点

Still：`libmpr` 构造 `0x508`（1288B）参数，在 `libmpr+0xf20ec` 调
`Fsys_WriteDirectFileAsyncV2`，
路径形如 `_:/DCIM/100MSDCF/DSC0<编号>.JPG`。Fsys 侧在打开前就拒
总长度 0（`0x80000030`）；异步入队成功不算保存成功，完成状态经
callback 回到 `libmpr+0xe81ac`。
Movie 走另一条 API（`Fsys_Write`/`Fsys_WriteAndFlush`），
不能套 Still 的链。

前提是真有挂载卷。有卡 payload 经原 MediaDetect 引出
`Fsys_Mount("/nondev/rm2")` 返回 0 已实证；但 `DATABASE.BIN`/`MEDIAPRO.XML`
只证明部分卡通路——没有 `DCIM/`、没有原 JPG/MP4。
注意：full 早期"通知未到达"的说法已被后续挂载实证推翻，引用旧报告
要保留时间和范围。

## 8. 最新原生等待：后台3006先于local21

`run-qqu0q5oe` 的语言24步实际LCD消费通过，但温度确认模态误被标作shooting；原system error30c早于S2。两条完整保存FP链与原BL字节确认：原CameraBackground339等待更早24B `3006` / 动态source `810261c4` 的回复，串行本地21被挡，Common382在future等待。本轮未到3003、VDF或codec，不以更早run的成功为本轮补证。

新功能owner实现原请求pending→同轮13边原free及debugger交接→实际Core INIT/STATE128→同实例缓存读回→原request free→独立12B回复→原sender receive/free。BEGIN/snapshot/ticket/cache与退休后新source绑定已通过完整5568/7057及构建/双ABI，尚无新原生证据证明该链已完成。裸send ENOTSUP会遗失原request/queue，不能作为修复或业务失败的合法回复。

完整dump路线曾定位的pcie-if/远端回调缺失是另一条历史传输边界，不用于解释本轮native等待，也不由功能owner抵扣。

## 9. 成片验收终点

拍摄需要逐边关联原AP的实际源帧与lease→原SDK/encoder真实消费→当前输出内存→原MPR封装与Fsys请求/callback/worker→原文件读回→两次SD导出与宿主SHA/独立解码。JPEG适配不是单独保存API，也不直接写媒体文件。

当前卡只有数据库/XML；Flush0不等于媒体写入，host成功编码/解码不等于原固件拍摄。新整批完成后用新空卡/intent做一次完整运行，旧失败不回填；没有确定完成时间。`capture_verified=false`。

## 证据入口

- [当前矩阵、阶段时间线与JPG下一缺口](2026-10-29-current-progress.md)。
- [完整基线SHA与最新原生负例摘要](../../validation/2026-10-29-progress.json)。
- [媒体前沿](10-media-frontier.md)、[存储分层](07-storage.md)与[调试/退出证据](12-debugging.md)。
- [本包验证记录](../../validation/README.md)：历史实验与当前组件批次分别计数。

## 如果你在做别的机型

Sony 消息、DMM/SDS、MPR、CP 模块都要按原件重核，别把本页消息当成功回复。
可复用的是方法：从消费者反追生产者；控制、像素、编码、封装、存储分开记账。
证据不足就写缺哪条边——比把帧和 ready 补成常量有用得多。
