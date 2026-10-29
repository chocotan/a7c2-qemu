# 宿主目录直通 SD（固定 256 GB）

## 目标与边界

用户已取消原机内格式化验收。本路线将**宿主目录中的实际文件/子目录**映射成原相机 USB/SCSI 驱动看到的 FAT32 虚拟卡，而不是把 `card.img` 放进目录、把目录当普通 guest 文件系统，或由宿主生成照片/录像。

- 逻辑块容量固定为 **500,000,000 × 512 = 256,000,000,000 字节**（十进制 256 GB）；实际可用空间还受 FAT、目录和簇占用影响。
- 不再把整张卡复制到 guest RAM。QEMU 使用有界的 FAT/目录元数据和临时写回层；实际文件写入必须经过原 Fsys/设备 flush 才返回宿主目录。
- 原机内格式化不执行，也不以宿主格式化冒充原格式化。`firmware_format_verified=false`。
- 不接物理磁盘/真实 SD，不向 guest 暴露宿主根目录。控制器通过固定目录 FD、独占租约和 sandbox bind 只暴露选中的目录。
- 租约期间禁止宿主外部并发修改；锁是协作式所有权，不是对恶意宿主进程的安全隔离。启动时拒绝符号链接、非 UTF-8 名称和非普通文件/目录。
- 采用 FAT32，不声称 exFAT。单个文件的实现上限是 FAT32 的 `0xffffffff` 字节；大于此值拒绝，尚未证明任意长录像。

## 实现

`source/qemu-directory-sd.patch` 固定于原始 QEMU 11.1.2 `block/vvfat.c`，由 `build-qemu.sh` 在独占构建锁内应用，并以 `source/qemu-directory-sd.json` 校验输入/输出摘要。项目内 `source/directory-sd/vvfat.c` 是唯一工作副本；构建额外检查补丁结果与该文件一致，不依赖 `/tmp`。构建显式启用 `--enable-vvfat --enable-qcow1`；后者是原生 `vvfat` 可写写回层所查找的 `qcow` 驱动，不能用 `qcow2` 名称替代。

补丁包括：

1. 显式 `total-sectors=500000000` 的 FAT32 容量选项；大容量目录盘使用 32 KiB 簇，避免把整个卡复制到内存。
2. FAT32 的 32 个保留扇区、主/备份启动扇区、FSInfo、FAT32 分区类型和真实根簇 2。内部映射与外部簇号统一，数据地址计算扣除 FAT32 保留的两个簇。
3. 拒绝符号链接和不支持的文件类型；允许合法空文件，检查短写、提交错误和关闭错误。
4. 注册真实 `bdrv_co_flush_to_disk`：先同步虚拟写回层；原 Fsys 在 FAT 前的中间/重复 flush 可幂等成功，但只代表 qcow 已同步。FAT/目录一致后才提交目录/文件改动并对映射的宿主文件和目录执行 `fsync`。backend 的实际待提交/已提交事件会被宿主快照检查，未决导出拒绝。FSInfo 仅允许修改空闲簇/下一簇字段，其他元数据仍受保护。

`runtime/analysis/directory_sd.py` 持有目录租约；`directory_sd_profile.py` 从已验证的虚拟 xHCI 启动器派生：

```text
-blockdev driver=vvfat,node-name=sony_directory_sd,dir=/sd,rw=on,fat-type=32,total-sectors=500000000
-device usb-storage,id=sony-directory-sd,drive=sony_directory_sd,removable=on,serial=PI_DIRECTORY_SD256
```

`/sd` 只绑定固定目录 FD。原 SCSI/USB、`/dev/sda`、原 RM dummy 后端和受限容量/真实 fsync 适配器继续复用；不修改通用 `stat`、媒体状态或 ready 位。

## 验证与尚未完成项

- `test_directory_sd.py`、`test_directory_snapshot.py` 检查租约、sandbox 目录绑定、容量补丁身份、原 flush/STOP 前置条件、宿主文件散列和符号链接拒绝。测试通过不等于 QEMU/原 Fsys 已通过。
- `check-host-sd-guest.py --original-fsys --seed-backup --directory-fsys` 在独立测试目录运行原 ALLLANG Backup + 原 Fsys 诊断，要求原挂载、QTEST 4096 字节写入/读回、FlushVolume/Unmount 和宿主文件逐字节一致。该测试目录与旧 `host-sd/card.img`、正式目录隔离。
- 中文自然启动由 `A7C2_DIRECTORY_SD=/absolute/owned/directory` 显式启用；与其他卡、成像、热插拔 profile 互斥。保存使用原 flush/STOP/CONT 生命周期、真实块同步和宿主目录清单/散列，不导出整卡镜像。
- 首轮 `b3b967762` 在临时源码目录错误寻找补丁，未编译/运行 QEMU；修正为从交付 `source/` 读取补丁后重试 `bfa3a3d09`，同时纳入 FAT32 union 清零、备份签名和 FSInfo 规则修正。`bfa3a3d09` 在编译期发现 `read_directory` 误用不存在的 `errp`，已改为沿原返回值上报并由 `b63e3f5b4` 重试。失败均保留，不将重试称为首次成功。
- 目录/启动配置组 `b90babf51` 为 **3 passed**，集成组 `bbfa0b907` 为 **36 passed + 2 subtests**，几何/快照组 `ba63cc8b2` 为 **9 passed**；这些不是设备或原 Fsys 验收。
- `b63e3f5b4` 曾完成 C 驱动构建，但随后 `b9ed2d6f6`/`b3734f715` 均在启动参数阶段发现 `-blockdev` QAPI 拒绝 `total-sectors`，没有设备 I/O。已将同一字段加入 `BlockdevOptionsVVFAT`，并加入项目内 `regenerate-patch.py` 统一生成 C/QAPI 补丁和摘要；`b1d51fc86` 正在重建。早期失败均保留，不能当作运行时成功。
- `b1d51fc86` 已重新构建并安装 QAPI 修正版，原生输入测试通过。`be21749dc` 先暴露测试脚本 AF_UNIX 长路径，`bae98e56d` 进一步暴露可写 vvfat 需要 `/var/tmp` 临时文件而 sandbox 未提供；均尚未完成 I/O。已复用短 socket 路径，并为每次运行绑定独立宿主磁盘 `vvfat-writeback` 目录，当前以 `b652fd8d2`/`bccbfc60f` 重试。构建记录更新于 `source/directory-sd/build-receipt.json`，但两项 I/O 标记仍待真实结果。
- `b652fd8d2`/`bccbfc60f` 进一步在打开写回层时发现精简构建未编入 `qcow`（`Failed to locate qcow driver`），仍未执行 I/O；已明确补 `qcow1` 并以 `b3da5f0a8` 重建。所有失败保留，不把重试称为成功。
- `b3da5f0a8` 已构建并安装 `vvfat+qcow1` 完整依赖组；`b18cb51e6` 首次取得原 Fsys `Mount=0`、`GetFreeSpace=0`、空闲 `255937380352B`，但创建 `QTEST` 时 SCSI 在 LBA122272 写40扇区失败，随后 `Mkdir=0x80010003`，不能称为可写卡。原始失败已保留。
- 设备测试又先后暴露测试预期/实现差异：BPB总量应与分区长度一致而非簇对齐末尾；FSInfo TrailSig实测曾错误写成16位55aa，已修为32位AA550000并由 `bebf13a7e` 重建。不得通过放宽检查掩盖这些问题。
- `b407f8a09` / `directory-device-magyhig3` 已完整通过独立设备验收：`geometry_verified=true`、宿主已有文件读取、虚拟写入、flush、正常退出及退出后宿主读回均为真。替换内容 SHA-256 为 `a863e21577e54cd763729803a621804da4b5030afa35bcf879ea3b3413488a66`。这证明目录 FAT 设备，不是原 Fsys 或拍照。
- `b841fa62f` 的原始 pwrite 证明：Fsys 目标偏移为 `62606848`（LBA122279），Linux 对齐写回从 LBA122272 开始。`try_commit` 在 FAT 更新前先看到新簇，过早返回错误。已改为数据保留在真实 qcow，FAT 一致后提交；中间 flush 只代表 qcow 已同步，未决状态不能被当作宿主保存。
- `b4b8a7e76` 进一步证明：Fsys 的 FAT 单扇区写被 Linux 页写回合并为 LBA88–95，而 FAT 从 LBA95 开始。边界拆分只接受保留区逐字节不变的请求，并将 FAT 部分照常提交；不跳过一致性检查，也不丢弃保护区变化。`b298757d0` 的独立设备测试已通过原样跨界写回及保护区篡改拒绝。
- `b298757d0` 的原 Fsys 诊断调用全部返回成功，且宿主实际生成 `qtest/probe.bin`，内容 SHA-256 为 `c5d2097fa1cd94e31b5aeb3e30ddad3b49194826436c11fdf91f27090e8f9e9a`；但测试当时只查大写 `QTEST/PROBE.BIN`，因此整体仍保留为失败，没有倒填通过。现改用 FAT 唯一、不区分大小写路径解析，并加入重复 flush 幂等和提交状态检查。
- `bd84b63e0` 构建的修正版由 `b925924f6` 完整验证：独立设备 `directory-device-qc3_aowt` 通过几何、FAT 边界原样写回、保护区篡改拒绝、已有文件读取、写回、flush、提交状态和正常退出；原 Fsys `directory-sd-helper-qpiazxgl` 通过 Mount/Mkdir/OpenWrite/4096B Write/OpenRead/Flush/Close/FlushVolume/Unmount，最终 `pending=false`、`closed_pending=false`，宿主 `qtest/probe.bin` 精确读回，SHA-256 同上，原 `INPUT.BIN` 保持不变。该通过仅是原 Fsys 目录存储验收，不是格式化、中文拍摄页或媒体文件验收。
- `b365423ad` 的自然简体中文首设在第12页附近失败，未取得 HUD/保存通过。原日志证明 `A:/PRIVATE` 与 `A:/PRIVATE/DATABASE` 创建成功后，写入 `DATABASE.BIN` 触发 `handle_renames_and_mkdirs` 的 `j < s->mapping.next` 断言；这不是拍照失败，也不是格式化。VM 返回1，导出未完成；显示资源已确认无 QEMU/媒体 FD 后用 SIGTERM 清理，未强杀。
- `b74cf262d` 的原 Fsys 嵌套诊断（`QTEST/NESTED/DEEP`、1MiB）所有原调用返回成功，但宿主只有单级 `qtest/probe.bin`，关闭时 `pending=true/closed_pending=true`，故整体失败；它证明“原返回成功”仍不足以证明宿主提交。源码和独立调查定位到 `array_insert` 未初始化新 mapping 的 `first_mapping_index`，父目录过滤可能排除真实父项；另发现新增 direntry 区间也未清零。两处初始化已修补，仍保留断言。
- `bdb0a88d1` 的逐簇证据进一步定位最终阻塞：BIG.BIN 的32个数据簇已计数（`directory_used=38/fat_used=38`），但 Linux 页写回额外把末尾一个扇区写入空闲 cluster40；该簇 FAT=0、未被目录引用，原一致性检查正确拒绝提交。已加入严格的“完整前驱链 + FAT空闲 + qcow连续前缀部分簇”页填充识别，任意完整/稀疏未归属写入仍拒绝。
- `bfd58544f` 构建后，`bc7cd6a2e` / `directory-sd-helper-yhrpisvn` 通过嵌套原 Fsys 验收：`QTEST/NESTED/DEEP`、1MiB 写读、FlushVolume/Unmount、正常退出和最终 `pending=false/closed_pending=false` 均为真；宿主 `qtest/nested/deep/big.bin` 为 1,048,576B，SHA-256=`721b8aaa6dd213a5d358b36b8063922091ae50f104c418042dd48d0909db141b`，单级 `qtest/probe.bin` 与原 INPUT 也保持不变。该通过仍不是自然 UI 或媒体捕获。
- `b1328174d` 已在修复后重新到达原拍摄 HUD/菜单（`run-cvzd157y`），HUD 剩余张数显示9999、中央取景仍黑；首次导出因目录后端未创建运行输出 `SD/` 而失败，原 flush/STOP/CONT 已完成。该任务最终仍按超时失败保留。后续 `bb510a6a9` 在本运行创建私有报告目录并重试原导出成功：宿主由原固件生成 `private/database/database.bin`（9,670,656B，SHA=`cb9eeb1d156189541de53a619c46a56868c8d0360df506fd0048df1ea9436391`）及 `private/m4root/mediapro.xml`，提交清洁、owner恢复；随后正常 GTK 关闭和 Xvfb 清理完成，无强杀。独立恢复证据为 `directory-natural-acceptance.json`，不改写原失败任务。
- `publish_final` 已修正为目录后端自动创建私有 `SD/` 报告目录；`b8299111c` / `run-dk4f19u6` 已在全新目录完成中文首设、HUD、自然四记录快门、首次导出和正常清理。原 `INPUT_EVENT32 n77..80` 与四个 `SHUTTER_ROUTE stage=0..3` 均各命中4次，业务分发 `0x1e79d64` 已证实；宿主只有原数据库/XML/INPUT，提交清洁、无JPEG/MP4。此次 `natural_start_trace=false`、`jpeg_request_trace=false`，所以 Still/JPEG 零命中**不是完整否定证明**；证据见 `baseline-shutter-evidence.json`，不把其称为拍照成功。此结果不等于 JPEG/MP4 或 CP liveview 验收。
- `bcf075eef` / `run-e_a1oc3f` 未执行到快门：中间 vvfat 诊断警告与原串口完成标记交错，主机误判事务边界并保留 VM。交错后的原始 `gui-model-export` 标记实际为 `rc=0`；宿主数据库/XML已提交、真实设备 fsync 返回0、后端 `pending=false`，随后仅对身份匹配的 QEMU 发送普通 SIGINT 并正常关闭，未强杀。该次没有完整 owner STOP/CONT 导出，也没有 Still/JPEG 结论；恢复证据为 `directory-recovery-shutdown-assessment.json`。
- `b924a5ff0` 已将中间一致性诊断降为 DEBUG-only，保留提交生命周期事件；原生输入回归通过并安装新二进制。旧二进制的设备/Fsys/自然通过记录保留在 `build-receipt.json` 历史项，新二进制的这些验收仍需重新取得。`menu-observe.c` 新增默认关闭于未启用路由追踪时的 `SHUTTER_DISPATCH`、`SHUTTER_TARGET`、`SHUTTER_RECEIVER` 只读观察点，原始重放及 ASan/UBSan 测试4项通过；尚待新自然运行验证。
- `b98212edf` / `run-leujd_cy` 在三点全部启用时于首设早期发生 AppFw 取指异常（PC=`appFw+0x5bc27a8`，调用者返址 `appFw+0x1e79f04`），没有快门或媒体写入；该失败保留，尚未把原因归咎于某一个探针。
- `b1c490fc9` / `run-46a4ot3_` 关闭三点后完成中文首设、四段快门、原 flush/STOP/CONT、清洁提交和正常导出，证明降噪基线有效。此次 Still/JPEG/Fsys 观察均已武装，但命中均为0；没有照片或视频。证据为 `baseline-shutter-evidence.json`。新观察点改为独立 `A7C2_INPUT_ROUTE_DETAIL` 选择，不再默认补丁。
- `bb490f19c` / `run-x5gyvckx` 的 canonical 单点和 `bb5969243` / `run-31z8u_t0` 的 target 单点均完成四段快门及清洁导出；RTTI 确认全按进入原 `cap_screen` 控制器，半按进入 `lock_screen`。`bce25472c` / `run-zm1ykl1p` 的 receiver 单点独立复现同一早期取指异常，故 receiver 已撤回并禁止配置，证据为 `receiver-isolation-evidence.json`。
- 后续改用四个最终处理器函数入口（`handlers`），`b67c97298` / `run-9b2yl8n9` 已安全到达半按、全按、额外事件和半放并完成导出，Still/JPEG/Fsys仍无命中。该次三个状态读取均为 `-1`，不是状态0；已修正为 `appfw_base+offset`，由 `baf6dc1fb` 重新验证，不能沿用旧零值作业务判断。
- 地址复核进一步纠正：`0x285f0b8` 的真实字段是 `0x7e5d498`，不是 `0x7e5d430`；先前把邻接字段早退归因已撤回。`b24618329` / `run-m73s6yon` 只读证明全按进入 `0x1b54444` 和 `0x1af16dc`，但未取得候选发送 ID；真实 option/EE/API门禁需以新运行为准。
- `b566d65b8` / `run-545vcvpn` 将半按/全按各保持1000ms，事件顺序不变但仍无 Still/JPEG/Fsys 产物，排除单纯50ms保持不足。`bd92203f2` 使用修正后的 d498、EE、transition 和 `0x2688f44→0x2688eac→0x2688a08` 入口观察继续定位，尚未宣称拍照成功。
- 当前静默日志 QEMU `e23589c44386c19417551c982e394b7a4e779f8e68a72f2964b705aca1e96c0d` 已重新取得独立存储验收，未沿用旧二进制结论：`b33bc7763` / `directory-device-aqv8o0si` 通过几何、FAT 边界保护、已有文件读取、写回和正常退出；`b38770bf9` / `directory-sd-helper-vpd1fcmm` 通过原 ALLLANG/Fsys 单级 4096B 与嵌套 1MiB 写读、FlushVolume/Unmount、清洁提交和宿主精确读回。对应摘要仍为 `c5d2097f…9e9a` 与 `721b8aaa…141b`，`build-receipt.json` 已按新证据更新。
- `run-3w1lebcs` 通过原 Fn 页面开启静音模式并在同一拍摄页执行自然半按/全按/释放，原 capture API wrapper 到达，但 EE=0、execute/Still/JPEG/Fsys 照片写均为0；宿主仍只有数据库/XML/INPUT。此前多发送一次 MENU 的 `run-j296zvvl` 不是干净同页对照，保留但不据此判定快门类型。静音页面仍显示 `MECH` 只是待解释 UI 证据，不单独否定用户实机所述静音→电子快门联动。
- 中文拍摄页和原 JPEG/MP4 产出均**尚未验收**。任何构建或运行失败必须保留，不得把目录里已有的测试文件称为原固件拍摄结果。

## 与旧路线的区别

旧 `host-sd/card.img` 是真实的宿主文件支撑块镜像；旧 FAT 诊断的 FSInfo 陈旧失败仍保留，不在本目录路线中修复或重写。本目录路线的 FAT 元数据由 QEMU 按目录内容生成，不能把宿主目录直接交给 `fsck.fat`；应以原 Fsys 行为、原设备同步和宿主文件内容分别验收。两条路线不混用，也不启动第二个 VM 争用同一目录。
