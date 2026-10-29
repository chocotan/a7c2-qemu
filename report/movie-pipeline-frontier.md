# 原Movie控制、编码与写入链：静态部分研究

范围：旧只读代理在turn limit完成部分调查，主会话抽查了sequence名称/vtable/run、
`RecStart` enqueue和Movie Fsys sink。原件身份保持：appFw SHA256
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`；libmpr SHA256
`4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9`；
libInfraAvbbc SHA256 `676197567dbbefa54e08f528968efc6ca2aaffe8bee3ee3eae8164382ed5a7e5`。
没有由该调查生成媒体、启动VM或宣称运行时编码成功。

## 1. 正常输入到Movie sequence的已识别部分

- 模式拨盘raw `0x71c9` 产生 `0x2240002`，选择Movie不等于REC。
- REC输入路径为raw `0x1f0` → UIBIZ `0x1c` → 原事件 `0x02150012`。
- 从原事件到当前活动控制器/policy再到sequence `0x40` 的完整选择规则**尚未闭合**；
  因此下列链条从原factory开始，不声称当前REC一定会到达。

原名表与vtable（主会话复核）：

```text
sequence ID 0x40 = sequence_start_movie_recording
name table 0x57f7658 + 0x40*8
sequence table 0x5578920 + 0x40*8 -> 0x248fc58
factory -> 0x322aa28 -> constructor 0x31a7c4c
vtable start 0x5b47078
  +0x00 offset-to-top 0
  +0x08 RTTI 0x5b47048
  address point 0x5b47088
  +0x20 from start -> sequence run 0x3487d7c
```

`0x3487d7c` 在 `0x3487e1c` 调用 `0x3486928`
（`sequence_start_movie_recording::start_recording_movie()`）。后续已识别调用为：

```text
0x3486928
  -> 0x34d4288 -> 0x356000c -> mpr::PrepareRecStart
  -> 0x34d4308 -> 0x357d10c -> mpr::RecStart@libmpr+0xddda0
```

AP `0x357d274` 调 `mpr::RecStart@plt`，`0x357d27c` 经 `0x3531300` 等待注册完成上下文。
在准备/开始前还有四个异步audio/control job及join，以及原文称为 `mss_stop` 的操作；
这些都是实际执行后可能出现的等待，不能由模式页或REC输入提前跳过。

## 2. MPR RecStart与encoder控制顺序

`mpr::RecStart@0xddda0` 建立录制信息、媒体/路径/UMID和必要的DMM资源。主会话核到原enqueue点：

| 地址 | 操作 |
|---|---|
| `0xde094` | `EnqueueExecEncOpen@0xd7e90`（encoder未保留时） |
| `0xde0b4` | `EnqueueExecReady@0xd8f74` |
| `0xde0c8` | `EnqueueExecEncStart@0xd8008` |
| `0xde0d4` | `EnqueueExecSetLensProfile@0xd92bc` |
| `0xde0dc` | `EnqueueExecEventMovieRecStarted@0xd9ad0` |

这些是队列操作，不是样本完成。原执行器包括：

```text
ExecEncOpen   0xd30d4 -> Codec::EncOpen  0x280bc8 / EncOpen2  0x280fcc
ExecEncStart  0xcbc20 -> Codec::EncStart 0x27df88 / EncStart2 0x27e10c
ExecEncStop   0xca42c -> Codec::EncStop  0x27e37c / EncStop2  0x27e50c
ExecEncClose  0xd07fc -> Codec::EncClose 0x27c1d0 / EncClose2 0x27c304
```

`ExecEncStart` 设置 `s_isEncoding` 只是控制状态，不证明一帧已提交或压缩。

## 3. Codec/Avbbc服务边界

- `Codec::Init@0x27bd54` 创建接收线程并注册callback SID `0x80c70047`。
- `Codec::SendMsgToAvbbc@0x27c058` 发送48B envelope到 `0x8055001f`，再等待condition variable。
- `Codec::CallbackFromAvbbc@0x283e74` 将事件转换为匹配控制完成或继续分发。
- 单流MID `0x210` 的open/start/stop命令号为0/1/3；参数长度分别为0x98/0x80/0x10。
- `CreateMessage@0x27be38` 记录参数长度、codec/file-format、MID及staging指针。

`libInfraAvbbc.so` 的 `CreateCommandSequence@0xb010c` 还区分单/双encoder变体。
`ExecCmd_MC_EncOpen::ExecCmd@0x12bd1c` 可见38B MC请求到 `0x805700f9`，而
`MovieEncoderUtil::GetMcOsalId@0xb1d9c` 依据输入选择 `0x8057071f` 或 `0x805720f9`。
这些目的SID不能合并猜测；当前自然session实际选择哪个变体仍未测量。

## 4. Scenario不是完整录像链

`CAMERA_SCN_MOVIE_REC_START.so` SHA256
`5a6324ac2177e44fb4a742d6edf19207620233605c3674a6dcc15cb8f12bfd5a`。
其 `scenario_run@0x1280` 是控制scenario：先发送20B消息，消息头 `05 00 00 40`
（`+0=5`、`u16+2=0x4000`），再发32B查询（`u16+2=0x3001`，timeout5000）。
不能将头两个字节和命令字段合并命名为 `0x4005`。该函数不调用MPR或样本writer，
也没有证明与上述正常AP sequence相连。

## 5. 编码样本、mux与独立Movie Fsys sink

已识别的数据消费路径为：

```text
Codec::GetVideoInfoReadList@0x2820fc
  -> 60h stride VideoInfo records
  -> XavcsMovieWriter::MakeVideoEsList@0x11b958
  -> ES buffer areas / DMA transfer / mux work
  -> Movie file writer
```

VideoInfo中 `+8` 为ES offset、`+0x10` 为ES字节数，`+0x18..0x24` 进入sample-info；
`SetVideoSampleInfo@0x1184d0` 经内部mux helper `0x222dc0` 使用90000时基转换。
具体时间戳字段命名仍未完全恢复。

大writer worker `0x11df70` 等待命令 `0x10000000`，复制0x550B配置，派生 `.RSV/.BIN`
名称，建立ES/DMA/mux/file工作。`CreateXferLinkedList@0x11805c` 调用原DMA虚拟成员，
不能用控制ACK替代这些字节传输。

主会话核实独立Movie写入helper **`libmpr+0x118e48`**：

- `request+0x20` → `RingBuffer::GetReadPointer`；
- `request+0x10` → file object，句柄在object `+0x10`；
- `request+0x18` → 请求字节数；
- `request+0x30` → 选择 `Fsys_WriteAndFlush@0x118eec` 或 `Fsys_Write@0x118fe0`；
- `0x118f04..0x118f0c` 将sign-extended实际返回值与请求字节数比较；
- 之后才释放ring空间。ring退休本身也不是写盘证据。

停止/收尾的已识别点：`mpr::RecStop@0xd9d00` 排入EncStop/EncCut；内部finalizer
`0x118fe8` 做mux finalization、两次 `Fsys_Combine` 并销毁对象；
`CallbackPointForMovieWriter@0xdbff8` 处理writer停止事件。完整queue到write/finalizer的绑定、
`0x226f20/0x226ed4` 的Close/Flush语义以及host持久化顺序仍未闭合。

## 6. 下一步与最终验收分离

可独立于Still门禁调查的最早边界是codec服务初始化：在自然启动中只读观察
`InfraAvbbc_Init@0xa3308`、`InfraAvbbcIf::Initialize@0xa301c`、`Codec::Init@0x27bd54`
的真实返回和SID注册者；只有自然EncOpen后再记录变体和ring/status地址。静态调查没有证明
当前runtime缺少这些服务。

若之后做正常REC press/release，应按 `0x248fc58`、`0x3487d7c`、`0x34871c8`、
MPR `0xddda0` 分层记录，不能强发sequence或伪造完成。最终必须分别取得：

1. open/start请求及匹配原完成；
2. 真实帧buffer、几何、lease与实际提交；
3. 新编码ES字节及匹配信息/时间戳；
4. 原mux样本与对应字节；
5. Fsys实际写入数等于请求数，final close成功；
6. host目录提交后的MP4及独立ffprobe/decode/duration。

当前主阻塞是 `sequence_clock case1`，本文不改变该优先级。没有原MP4、录像完成或时长验收。
