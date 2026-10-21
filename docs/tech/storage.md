# 大步骤 5：用原文件系统恢复虚拟卡和安全热插拔

这篇解决原 Fsys 文件通路、RM 通知、所有权和导出，不把数据库写入或存储诊断当成拍照录像。

变量见[索引](README.md)。所有镜像仅指实验目录里的普通虚拟文件。

## 小步骤 1：先证明原文件系统确实读写

**问题 →** 未建模真实 MMC，也要验证原固件保存链。
**现象 →** 初期 Fsys 测试缺 `_ZTIN3MWF12EventHandlerE`，还没走到磁盘。
**误判 →** 在 Linux 任意目录写文件，就等于原相机存储已通。
**定位 →** 补原 libMWF 依赖；找到原 MediaCommon 自带普通文件 dummy 后端。
**解决 →** 原参数初始化后显式选 `EXISTMEDIADRIVER=0`、`OMIT_WRITE=0`。
原 `/dev/mmca` 路径进入 guest 普通文件 `/image_mmca`，保留原 Fsys。
独立两进程做 Mount/Write/Flush/Close/Read/Unmount，再重挂读回 4096B。
全镜像 guest/host 摘要、FAT 文件内容与 fsck 分别核对。
**剩余 →** 这是文件测试后端，不能声称 MMC ADMA 控制器或成像已恢复。

## 小步骤 2：卡能写，不等于原媒体管理器知道卡变化

**问题 →** 发送拔卡通知后，UI 一直 ejecting。
**现象 →** 通知原 free=0、Flush=0，却 45 秒没有原 Unmount。
**误判 →** free 成功就是拔出成功；或者只是首设没完成。
**定位 →** 首设后对照仍失败，随后追同一消息的原 Callback→Parse→Update。
记录原 7B payload、R 状态、M 状态和上层 Notify，不直接调用 Unmount。
**解决 →** 找到设备配置 opcode9 首 record `+4` 的掩码与实际通知通道不一致。
旧值 1 只选择 R0，实际 RM2 通知改变 R1；默认模型改为对应 bit2 后自然卸载。
**剩余 →** `rec+4 = 1<<record_index` 是本模型成立的配置，不能推广为所有硬件通则。

## 小步骤 3：区分物理槽、逻辑记录和盘符

**问题 →** A7C II 单物理槽，却有 RM1/RM2 和多个逻辑盘符。
**现象 →** 同一张卡重插后盘符 A→B→C→D。
**误判 →** 把 RM2 直接叫第二物理槽；每个新盘符都算新卡。
**定位 →** 逐代关联原 Mount/Unmount、卷 mask、通知 count 和同一镜像身份。

| 历史原通知 payload | 该次行为 | 原库结果 |
| --- | --- | --- |
| `02000002001000` | generation2 REMOVE | Unmount A，mask1→0 |
| `02000002001200` | generation3 INSERT | Mount B，mask0→2 |
| `02000002002000` | generation4 REMOVE | Unmount B，mask2→0 |

**解决 →** M0 可选择 R1，M 与 R 不必同号；插入后使用原新盘符。
同卡多周期通过后才做本包移交，本包又独立验真实 GTK 两轮及默认旧卡回载。
**剩余 →** 当前不提供运行中选另一镜像的 UI，RM1 诊断也不承诺完整热插拔。

## 小步骤 4：把消息 destination 与 allocation owner 分开

**问题 →** 通知发到订阅队列，不代表内存就归该队列释放。
**现象 →** 变化消息 destination 为订阅 N，原释放按 Front owner `0x8028017c`。
**误判 →** initial 与变化消息都用同一个 dst 分配/发送/free；send0 就销毁 lease。
**定位 →** 核原分配/source/free 合同，并把 generation、owner、destination 一起记账。
**解决 →** lease 分开记录 owner/dst；发送失败也按 owner 处理。
迟到 free、错 owner、排队期间代变化都不能被误当当前代完成。
**剩余 →** 分配/原 free 成功只证明消息生命周期，不单独证明 Parse 或业务动作。

## 小步骤 5：安全拔出时，先守住 inflight 和 retirement 边界

**问题 →** 新输入、旧 I/O 和迟到回复可能跨越拔出边界。
**现象 →** 单纯关镜像会丢写入，超时后反向 insert 会制造未知状态。
**误判 →** 墙钟超时就自动回滚成“已插入”；收到旧成功回复就解除新请求。
**定位 →** 单 RM worker 串行请求，原 Mount/Unmount 入口捕获 generation，完成时原样携带。
**解决 →** 请求入队即阻新输入，执行时再检查；未决/溢出/失步继续隔离。
只有原 Unmount 成功、旧卷 mask 清位、无 inflight、worker 确认退休才允许 absent 导出。
**剩余 →** uncertain 就停，保留恢复路径，不能补“卸载完成”或直接强断镜像。

## 小步骤 6：在卡与已拔出使用不同保存证明

**问题 →** 已退休卷不能再假装取得一次新 Flush。
**现象 →** absent 导出中的 `original_Fsys_FlushVolume_rc=null` 是有意区分。
**误判 →** 所有导出都必须填 rc0，否则改表凑成功。
**定位 →** present 核原 Flush；absent 核原 retirement 证据，两者均核 owner 和数据。
**解决 →** 128MiB 卡按 32×4MiB 窗口导出，guest/QMP块摘要再对整卡 SHA。
host 独立重读文件、fsck；恢复 owner 后才继续生命周期。
**剩余 →** SD owner 恢复与调试 CPU 恢复是两套检查，都不能省。

```bash
# 执行目录：$PKG；以后核自己的已关闭运行，RUN指向一个已存在的run目录
cd "$PKG"
# 先设置 RUN；例如从保存结果中选取，不要操作活跃镜像
sha256sum "$RUN/SD/card.img"
fsck.fat -n "$RUN/SD/card.img"
```

## 小步骤 7：从 Open 成功推进到完整内容读回

**问题 →** 重插后打开 DB 成功，尚未证明读到原卡字节。
**现象 →** 内容 trace 一度缺失，实际原因是选用库没重建，而非原程序没读。
**误判 →** 源里加了 trace 就认为 guest 已装；Open0 就算内容消费。
**定位 →** 核实际 cpio 唯一库字节，再记录原 Read 的真实返回长度和 buffer 摘要。
**解决 →** 原 DB 返回 9670656B、XML 返回406B，与导出 FAT 中完整文件重新计算匹配。
native 另有原 API 写4096B诊断，完整 Read/导出逐字节一致，明确标为诊断文件。
**剩余 →** 原 DB 内容 Read 不证明全部解析语义；诊断 BIN 不是自然拍摄产物。

## 解决了什么，仍未解决什么

本包已验同一虚拟卡的真实安全拔出/重插、原完整内容 Read、退休/在卡导出和默认回载。
原第一次 GTK 重插未确认与 marker 污染失败保留；未给首次按钮超时编造唯一根因。
REC 可记录状态、自然重插后新拍摄 Write、照片/视频仍各自未通过。

## 证据入口

- [原 Fsys 独立通路](../../../a7c2-re/report/2026-10-17-qemu-native-camera/STORAGE-PROOF.md)。
- [掩码、owner、generation 与实际周期](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/sd-hotplug-progress.md)。
- [原 API 诊断范围](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/sd-reinsert-api/README.md)。
- [本包两轮及默认回载](../../validation/README.md)。

## 如果你在做别的机型

Fsys 文件后端、RM opcode/mask 和消息池 owner 是 Sony 具体合同，不能盲搬 payload。
可复用的是单 worker、入口代号、在途隔离、退休条件和跨通道内容比对。
先闭合普通文件存储，再做通知和热插拔，最后接拍摄保存。
