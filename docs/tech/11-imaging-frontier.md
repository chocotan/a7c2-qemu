# 启动流程 11 · 成像与录像：拍摄页面之后未闭合的链路

拍摄页面能画出来，但取景区域仍黑。本篇沿原消费者反追整条成像链：
取景像素、镜头/AF/AE、编码、保存——**到目前没有原固件生成的有效
JPG/MP4，成片闭环未形成**。

变量见[索引](README.md)。地址只用于阅读既有证据，不授权调用内部函数、
写模型或注入完成包。native 与 full 是两条独立路线，动态通过不能互借。

坐标约定：AppFw 用 ELF VA（按 PT_LOAD 换算）；`av-cam.bin` 记为 K，
地址是 raw 文件偏移，运行 VA = `0xffffffc001000000 + raw`；
CP 用 `CPVA = raw + 0x108000`。三套坐标不能混用。

## 1. HUD 和控制回复 ≠ 成像启动

HUD 上的 `AF-S` 是 `model+0` 的显示翻译，不是合焦反馈。
拍照模式的 EE 控制链（`sequence_start_ee`）会向 `0x90030001` 发
24B、cmd `0x3003` 的请求，调用方读 16B 回复的 `+8` 并与 `0xf000` 比较——
但这份回复没有像素地址、帧序号或帧消费证明。

边界：**不预填 f000，不写 EE=1，不用 OSD 截图代替原像素。**
原代码里 mode 2 且 EE=0 时会直接离开拍摄入口（`0x2688ef8`），
所以 EE 状态是真实卡点之一，但它的合法前置和完成事件仍未闭合。

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
禁止发全零快照、强兑 promise、把 d018 控制动作当成 2040 已到达。

## 3. 像素：从编码消费者反推 YC 描述符

`sdf_encode_jpeg@0x34f6fd0` 读输入描述符：`+0x20` 描述 PA、`+0x28` 长度、
`+0x30/+0x32` u16 宽高。描述符的分配走 DMM（SID `0x0061003c`），
回复给 handle/PA/长度——但**分配和填写完成不等于帧生产完成**。

resize 请求发往 `0x82830752`（68B，`2000:0003`）；接收端定位在 AP 侧
`av-cam.bin` 的 `tsk_sdt`，内部改投 `0x82830753`。有一条真实的分段
容量检查：按 CanvasX×CanvasY 和 YcCompress 算 required，再核段容量减
offset——它不是位深公式，也推不出单 plane 或连续内存。

仍缺：CMOS 原始源、字节/位顺序、planes/stride、最终 DMA 完成、
帧 generation/lease 和新鲜度。接收端在 AP 不证明传感器生产者必在 AP。
本包的 `cmos-source.c` 只生成确定性测试图样，**没有**接到原 YC 链。

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
原软件 MP4 封装已定位，不等于得到有效 MP4。

## 7. 保存链终点

Still：`libmpr` 构造 508B 参数，在 `libmpr+0xf20ec` 调
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

## 8. 当前卡住的边：AP↔CP 传输

full 的最新动态定位：本地查询进入 CameraBackground，状态 1 时向
`0x90030001` 发 24B cmd3007，`send` 返回 0 后以 `ffffffff` 无限等回邮——
但 **`pcie-if.ko` 没加载、`osal_reg_public` 没调用**，内核
`osal_snd_msg` 对 CP 目的走"缺远端回调、打印 Skipto1 后仍返回 0"的分支：
**消息没离开 AP**。`liro.ko` 也因缺符号无法加载。

所以当前要补的是 AP↔CP 的真实传输与资源合同：send 返回 0 不能称送达，
更不能用空 ACK、固定 30 或 f000 代替原消费。native 的有限 3007 控制模型
（`cp-background-device.c`，默认关闭、日志保留 `hardware_ready=0`）
是它自己的显式模型，不抵扣 full 的缺口。

## 9. 总结边界

已有可追溯合同：输入、OSD、卡存储、部分快照/描述符、控制请求、
编码/保存消费者。**没有成片闭环。** "MF + 手动曝光 + 单张 JPEG"只是
缩小排查范围的假设，未证明足以拍照。
最终验收必须逐边关联：原帧与 lease → 原编码实际消费 → 有效输出 →
原封装/写入 → 完成回调 → 独立读回。任何一条边都不能用常量或宿主
生成文件顶替。

```bash
# 执行目录：$FULL；只读跳到合同中的纠正和保存边界
cd "$FULL"
rg -n '^## |重要更正|总长度 0|Fsys_Write|ValidState|MCODEC_2' IMAGING-CHAIN-CONTRACT.md
```

## 证据入口

- [成像链合同（重点 §8、§10–13 的纠正）](../../../a7c2-re/report/2026-10-17-qemu-full-system/IMAGING-CHAIN-CONTRACT.md)
- [full 最新状态与传输边界](../../../a7c2-re/report/2026-10-17-qemu-full-system/STATUS.md)
- [native 镜头/曝光生产合同](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/control-lens-exposure-frontiers.md)
- [镜头初始化静态合同](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/lens-init-contract/README.md)与[像素几何/容量边界](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/imaging-pixel-contract/README.md)
- [native 有限控制传输的独立验收范围](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/cp-background-contract/TRANSPORT.md)

## 如果你在做别的机型

Sony 消息、DMM/SDS、MPR、CP 模块都要按原件重核，别把本页消息当成功回复。
可复用的是方法：从消费者反追生产者；控制、像素、编码、封装、存储分开记账。
证据不足就写缺哪条边——比把帧和 ready 补成常量有用得多。
