# Windows / macOS 移植评估（2026-10-21 调研）

本文汇总对本包做一次跨平台静态调研的结论。**未改动任何代码，未在 macOS/Windows 实机验证**；
所有"可行"均为源码层面的推断。调研基于四个并行审计：显示与输入路径、外部命令盘点、
POSIX 专有 API 审计、guest 交叉编译与 QEMU 构建。前提：操作系统没有的能力允许跳过或降级
（如 bubblewrap 隔离、seccomp、linux-user、X11 自动化验收）。

## 总体结论

| 平台 | 判断 | 主要原因 |
| --- | --- | --- |
| macOS | **可行，中等工作量** | 所有 Linux 专有点均有替代；无死结 |
| Windows 原生（MSYS2） | **能做但性价比低，建议 WSL2** | 默认启动链本身依赖 POSIX IPC，需重做 |

机身窗口不是 X11 嵌入：Python GTK3 经 QMP screendump → PPM→PNG → Cairo 绘制
（`camera_ui.py:678,832`、`qemu-menu-probe.py:935`、`menu_live.py:280`），
默认 `native_display='none'` 即 `-display none`，QEMU 不依赖宿主显示后端即可运行。
这是跨平台最有利的一点。

## macOS 移植清单（均有替代，按改动量排序）

| 问题（证据） | 替代方案 | 性质 |
| --- | --- | --- |
| bwrap 包裹构建与启动（`build-qemu.sh:88`、`qemu-kernel-probe.sh:339`、`start-menu.py:107`、`menu-native.py:26`） | 加平台分支直接跳过，失去隔离 | 降级（已批准） |
| `/proc/self/fd` 连接/定位 fd（`menu_live.py:123`、`firmware_overlay.py:154,251`、`sd_transport.py`、`sd-image.py:142`、`request_queue_watch.py:50,169`，另有 dir_fd 定位 `request_queue_watch.py:45,164`） | macOS `/dev/fd`；注意只适合单文件 fd，不能替代目录后缀/跨 PID 路径 | 小改 |
| 强制 X11（`qemu-kernel-probe.sh:29,36` 查 DISPLAY/Xauthority、强设 `GDK_BACKEND=x11`、`SDL_VIDEODRIVER=x11`） | 平台分支；mac 用 GTK Quartz（QEMU 官方支持，可保留 GTK 侧栏） | 小改 |
| mkfs.fat `-F16 -s4 -S512 -i7C220201`、fsck.fat（`make-media-fixture.py:38,45`、`sd-image.py:142`） | brew dosfstools 参数一致；或自带 newfs_msdos/fsck_msdos 需改参数 | 换依赖 |
| cpio 打包/追加未压缩 newc（`prepare-menu-initramfs.sh:54,81`） | brew cpio 参数一致；bsdtar 需改参数 | 换依赖 |
| debugfs `rdump /` 提取 initrd/nflasha15（`prepare-assets.py:413`） | brew e2fsprogs，参数一致 | 换依赖 |
| clang/ld.lld 交叉编译 guest 程序（`build-observers.sh:9,20`：`-nostdlib -O2 -mno-outline-atomics`，链接固件 libc/dl/pthread/ld-2.25，产物为动态 ELF/.so） | **推荐 LLVM+LLD+GNU 目标头**（需用户提供 aarch64 glibc sysroot）；`zig cc` 可适配但不能逐字替换（禁 libc 链接时不自动加 bundled 头，建议锁 `gnu.2.25`；源码用到 `__fxstat/__lxstat/__register_atfork` 旧 ABI，见 `sd-window-export.c:93`） | 中改，最麻烦的一步 |
| QEMU 11.1.2 构建（`build-qemu.sh:95`：system+linux-user、TCG/GTK/SDL/pixman/seccomp/internal-FDT） | 官方支持 macOS；去掉 linux-user（仅 Linux 宿主）与 seccomp；glib2 必需、pixman 显示必需、GTK3 侧栏需要、SDL 可关 | 改 configure 参数 |
| Xvfb/xdotool 自动化验收（`check-natural-gtk-input.py:125,190`、`check-gtk-controls.py:35` 等） | 跳过或另写；不阻塞手动运行 | 降级（已批准） |
| flock、chmod、tzset、geteuid（`instance_lifecycle.py:70,73`、`prepare-assets.py:465,496,510`、`bodydata-launch.py:209`） | macOS 均原生支持 | 原样可用 |
| 配置存储 dir_fd 系列（`setting_store.py:48,94,112` 等，共 7 处） | macOS Python 支持 dir_fd | 原样可用 |
| 虚拟网（`ethernet_peer.py:59` 仅 AF_UNIX 流 + 自行组 ICMP，无特权 raw socket） | AF_UNIX 原生支持；`usb_network.py:76` 固定 `.so` 需换本机库 | 小改 |

两阶段 QEMU 补丁只碰 `hw/、include/、ui/`（`source/qemu-sony-native.patch:74`、
`source/qemu-sony-usb.patch:51`），不触及宿主编译系统，macOS 构建不受补丁阻碍。

## Windows 原生的硬障碍（macOS 均不存在）

1. **控制通道 IPC**：`menu_control.py:49,280,315` 用 `socketpair + fcntl + pass_fds`
   把 FD 继承给 QEMU 作 `-serial stdio`（输入链：队列→JSON→stdin→guest inject-key，
   `menu_live.py:128,240,380`）。Windows Python 无 `pass_fds`，需改 TCP/命名管道并重做进程回收（killpg）。
2. **配置租约锁**：`instance_lifecycle.py:70,73` 用 O_CREAT+flock（不是 O_EXCL），Windows 需换锁实现。
3. **debugfs 无 MSYS2 包**：ext2 提取需 Python 重写或禁用相关导入。
4. **其余连锁**：即使禁用 overwrite（`firmware_overlay.py` 明确 Requires Linux），
   默认启动链仍卡在上面 1–2；GTK3 on Windows 部署脆弱；X11 验收测试整体不可用。
5. QEMU 本身 MSYS2 可构建（官方支持），但需统一 MinGW 环境、处理路径转换与 DLL。

结论：Windows 原生 ≈ macOS 全部工作 + IPC/锁/ext2 三处重做，且完全无法在本机验证。
WSL2 + WSLg 理论上可直接按 Linux 流程运行（较新 WSL2 内核支持 bwrap 命名空间），未实测。

## 允许跳过/降级清单（已与需求方确认）

- bubblewrap 无网络构建沙箱与 QEMU 运行隔离
- libseccomp、qemu-aarch64（linux-user）及对应测试
- Xvfb/xdotool/xprop/xwininfo 图形自动化验收
- （Windows）overwrite 覆盖功能、SD 导入导出

## 未验证与风险

- 本文一切 macOS/Windows 结论未经实机构建或运行；macOS 实机首跑大概率还有此处未列出的零散问题。
- MSYS2 与原生 Windows Python 混用的行为（socket、路径、FD）未验证。
- `zig cc` 替代交叉编译链为建议方案，未实际编译过 guest 程序。
- WSL2 路线未实测，仅依据其命名空间/WSLg 能力推断。
