# 启动流程 07 · 存储：虚拟 SD、热插拔与关机保存

本篇讲存储在启动链路里的三段：第 6 步把虚拟卡接进原文件系统（启动时）、
运行中的安全拔出/重插、以及第 9 步的关机保存导出。
对象只是实验目录里的普通虚拟文件，不接物理 SD。

变量见[索引](README.md)。历史运行结果来自文末报告，本次只回读源码，没有重跑。

## 1. 卡镜像：先证明来源合法

宿主侧 `sd_transport.py::card_source()` 逐级 `O_NOFOLLOW` 打开路径，
要求镜像是当前用户所有的普通文件，**4 MiB–2 GiB**、按 4096 对齐，
读取前后核文件指纹。

guest 侧种子由 `prepare-menu-initramfs.sh` 装配：复制前查空间、
对固定 fd 跑只读 `fsck.fat -n`，然后作为 `/simulation/sd-card.fat`
追加进 cpio，输出其 SHA-256。`qemu-menu-probe.py` 再把种子的摘要写进
运行清单，并核对实际 cpio 里的成员字节——只验来源路径不证明 guest 装了它。

默认相机 profile 用 128 MiB 的 `media-camera.fat`（FAT16，卷 ID `7C220201`）；
独立 Fsys 单测用 4 MiB 的 `media-template.fat`。4 MiB 只够单测——
相机应用的数据库分配是 `0x939000` 字节，不能拿单测卡当正常应用卡。

## 2. `/image_mmca` 文件后端：原 Fsys 通路

启动时卡镜像**复制**为 guest 内的 `/image_mmca`（原固件写的是副本，
宿主来源文件不直通），`file-media-config.so` 加入预加载链，
把 `EXISTMEDIADRIVER` 改为 0，让原 MediaCommon 选自带的普通文件后端。
原 `/dev/mmca` 通路因此读写这个文件，原 Fsys 的 Mount/目录/文件操作不变。

注意：包装器只**设置** `EXISTMEDIADRIVER=0`；`OMIT_WRITE=0` 是
`fsys-file-test` **检查**的前提，不是包装器设置的——旧文曾把两者混写。

独立验收（`fsys-file-test.c`）用两个进程：
第一个 Mount flags=0，走 Mount→Mkdir→Open→Write(4096)→Flush→Close→
Read 回读逐字节比对→Unmount；第二个以 flags=`0x100` 重挂再读。
然后整卡导出到预留区 `0x41e600000`，宿主侧核 FNV、独立 fsck、
解析 FAT 逐文件比对内容。完成标志全在原返回值和读回内容上，
不是"命令返回 0"。

这是**文件后端**验收：不表示 MMC/ADMA 控制器已模拟，
也不表示真实相机断电持久化。

## 3. RM 通知：卡能写 ≠ 媒体管理器知道

正常应用里卡的插拔要走原媒体管理器（RM）。`rm-file-device.c`
在 RM2 上注册唯一虚拟卡，处理设备配置（opcode9）、媒体查询（opcode2）、
订阅（opcode3）；插拔变化发 7 字节通知：

```text
02 00 00 02 00 XX 00        XX = (RemoveCnt << 4) | (在卡 ? 2 : 0)
```

通知交给原消费者，由原 Callback→Parse→Update→Notify 驱动真正的
Mount/Unmount；适配层不主动调 Unmount、不写 AP 状态、不补完成事件。

踩过的坑：拔卡通知原 free=0、Flush=0，但 45 秒没有 Unmount，UI 卡在
ejecting。根因是 opcode9 首 record `+4` 的掩码错位：旧值 1 只选 R0，
而 RM2 通知更新的是 R1。改为 `1 << slot`（默认 slot=1，即值 2）后
原链路自然卸载。这个对应关系成立于当前虚拟拓扑，不是 Sony 硬件通则。

## 4. 一个物理槽，一串逻辑盘符

A7C II 只有一个物理槽；RM1/RM2 是逻辑记录/通知通道。
同一张卡重插，原库给新盘符——报告里的实际序列：

| 代 / 操作 | payload | 原卷操作 |
| --- | --- | --- |
| 2 / REMOVE | `02000002001000` | Unmount A，mask 1→0 |
| 3 / INSERT | `02000002001200` | Mount B，mask 0→2 |
| 4 / REMOVE | `02000002002000` | Unmount B，mask 2→0 |
| … | … | C、D 同理 |

A→B→C→D 是**同一镜像**的盘符序列，不是四张卡；重挂后原应用打开的是
`B:/PRIVATE/...`，不沿用 A。完成判断要把镜像身份、generation、
通知计数、原操作和卷 mask 一起关联。

## 5. 消息的 owner 和 destination 是两回事

变化通知由 Front `0x8028017c` 作为分配/source owner，
destination 是订阅队列。lease 分开记 owner/dst/generation；
发送失败不马上销毁 lease（对方可能已消费，之后还会迟到 free），
错 owner 的释放返回失败并记故障。分配/free 成功只证明消息生命周期，
不证明 Parse 或业务动作。

## 6. 安全拔出：守住边界

请求入队即阻断新机身输入；REMOVE 前先在同一原卷 owner 进程做真实
`Fsys_FlushVolume`（要求无在途 I/O；**不暂停原进程**——它还要处理 REMOVE）。
拔出完成的全套条件：原 Unmount 返回 0、旧卷 mask 清位、当前代通知
正确释放、无在途 I/O、worker 确认 retired。事件队列（64 项）溢出会
sticky lost，禁止退休导出。

注意：host 的 45 秒是观察截止，guest pending 期限是 300 秒，两回事。
超时返回 uncertain 并保留现场——墙钟超时不是"已拔出"，
不自动回滚成"已插入"，也不强断镜像。

## 7. 保存导出：在卡和已拔出用不同证据

- **在卡**：原 `Fsys_FlushVolume` 成功，回复 `SD_FSYS_FLUSH`，
  证据 `original_Fsys_FlushVolume_rc=0`；
- **已拔出**：按退休证据回复 `SD_FSYS_RETIRED ... unmount_rc=0`，
  `original_Fsys_FlushVolume_rc=null` 是**有意区分**，不能改成 0 凑验收。

随后 owner 进程自发 SIGSTOP，host 核过进程状态和 maps 才复制。
数据经 `sd-window-export.c` 以 4 MiB 窗口（基址 `0x41e600000`）逐块导出：
guest 算 FNV → QMP `pmemsave` → host 核长度和 FNV → guest 重读确认没变。
128 MiB 卡分 32 块，拼好后整卡 SHA-256、独立 fsck、原子发布 `SD/card.img`。

原程序有没有真读文件内容另验：重插后原 AP 读回 `DATABASE.BIN`
9670656B、`MEDIAPRO.XML` 406B，与独立 FAT 解析的完整文件摘要匹配。
Open 成功不算内容消费；内容匹配也不证明数据库解析语义完成。

踩过的坑：一度完全没有内容 trace，原因是重建时没重设 `MENU_RM_FILE=1`、
库没重编——guest 有 flag、源码有 trace 都不证明选用库里有这段代码。
先核实际 cpio 里的库字节，再谈观测结果。

## 8. 关机：保存顺序不能乱

`VM.stop()` 不直接杀 QEMU，而是排入带 `_shutdown` 的 `export_sd`：
**先取配置 checkpoint，再导出 SD**；SD 屏障完成、owner 恢复确认后，
才发布配置新代数、更新下次回载的 `card_seed`；全部成功才退出 QEMU
并释放实例租约。任何一步失败：VM 保留运行，不显示"已关闭"。
`close()` 等保存最多 180 秒。

注意：SD owner 恢复和调试 CPU 恢复是两套独立检查，都不能省；
这是正常保存协议，不承诺崩溃/掉串口时也能保存。

```bash
# 执行目录：$PKG；核自己的已关闭运行，RUN 指向一个已存在的 run 目录
cd "$PKG"
: "${RUN:?请先指定一个已关闭运行的目录}"
sha256sum "$RUN/SD/card.img"   # 与该 run 的 export.json 摘要对比
fsck.fat -n "$RUN/SD/card.img"
```

## 9. 当前边界

已验：同一虚拟卡的安全拔出/重插多轮、原完整内容读回、在卡/退休导出、
默认回载（本包独立两轮 GTK + 后续默认 profile 运行，整卡 SHA 一致、
fsck 0、owner 恢复通过）。

未通过：REC 可记录状态、重插后的新拍摄写、照片、视频。
数据库/XML 文件不是拍摄产物；文件后端不是 MMC 控制器。

## 证据入口

- [原 Fsys 独立通路](../../../a7c2-re/report/2026-10-17-qemu-native-camera/STORAGE-PROOF.md)
- [掩码、owner、generation 与实际周期](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/sd-hotplug-progress.md)
- [原 API 诊断范围](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/sd-reinsert-api/README.md)
- [本包两轮及默认回载](../../validation/README.md)

## 如果你在做别的机型

Fsys 文件后端、RM opcode/mask、消息池 owner 都是 Sony 具体合同，
不能盲搬 payload，也不能把 `1 << record_index` 当硬件通则。
可复用的是：单 worker 串行、入口捕获代号、在途隔离、退休条件、
恢复后才发布成功、跨通道内容比对。先闭合普通文件存储，
再做通知和热插拔，最后接拍摄保存。
