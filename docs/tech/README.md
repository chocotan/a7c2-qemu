# 相机系统如何 QEMU 启动到拍摄页面：启动流程全记录

本文按**实际执行顺序**记录 Sony ILCE-7CM2（A7C II）2.01 ALLLANG 固件
从本机 `./start.sh` 到进入拍摄主界面的完整启动链路：每一步由哪个文件做、
做什么、以什么为完成标志、当前走到哪里。

## 阅读前先定范围

对象是本机隔离 QEMU 项目；不接真机、不写真实 SD、不刷机。
方法来自仓库已有报告与源码；文档编写代理没有启动 QEMU、连接 GDB、编译或执行测试。
主会话另核了原件/源码事实、文档链接及代码块语法；集成回归与独立运行的范围见本包 validation，不将这些测试冒作本文示例已逐条执行。
文档仅记录路径、结构、地址、摘要和结论，不附 Sony 固件、字体、镜像或 dump。

本包目前实际到达：原厂首设（语言/日期）、640×480 HUD/MENU 画面、
部分原按键输入、虚拟 SD 和有限配置恢复。**取景区域仍黑；CMOS、完整镜头/AF、
照片和录像没有通过。**“拍摄页面出现”与“相机能够拍摄”是两个不同阶段，
本文只承诺前者范围内的流程。

## 目录约定

在工作区根目录设置以下变量；`$W` 随你自己的 checkout 位置变化：

```bash
# 执行目录：含 final/ 的工作区根目录
W="$PWD"
PKG="$W/final/a7c2-qemu"
NATIVE="$W/final/a7c2-re/report/2026-10-17-qemu-native-camera"
FULL="$W/final/a7c2-re/report/2026-10-17-qemu-full-system"
```

`$PKG` 是独立包，`$NATIVE` 是研究报告与后续调查，`$FULL` 是另一条系统路线。
只有本包 checkout 时，用 `PKG="$PWD"`，先读本包 README 与 validation。
本组指向研究报告的相对链接需要完整工作区；独立分发本包时可能不可达。
不要把路径变量换成 `/dev/...`，不要把这些仿真步骤搬到真实相机执行。

## 启动流程：从 start.sh 到拍摄页面

### 第 0 步：入口 `./start.sh`

文件：`$PKG/start.sh`。
只做一件事：转到 `runtime/analysis/bodydata-launch.py`，
并把临时目录指到包内 `runtime/tmp`（避免宿主 `/tmp` 配额）。
完成标志：进入 bodydata-launch；若运行程序未装配则报错退出。

### 第 1 步：导入并固定固件资产

文件：`runtime/analysis/bodydata-launch.py`。

1. 在 `incoming/bodydata/`（或 `--bodydata` 指定处）找到**唯一**一份
   `BODYDATA.DAT`，禁止符号链接，读取前后比对文件指纹。
2. 用 vendored fwtool SDK 解 DAT 容器、解密 FDAT，核身份必须是
   `model=0x20030014 version=2.01 region=0 (ALLLANG)`，其他固件直接拒绝。
3. 解包出的固件树按包 SHA256 缓存进 `runtime/bodydata-cache/<sha>/`，
   写 `success.json` 清单；下次启动逐文件复核缓存，变了就拒绝使用。
4. 调用 `prepare-assets.py`：把内核（`vmlinux.bin`）、DTB、模块、库、
   语言字体等从解包树安装/校验到运行目录，并以 `native-assets.json` 锁定身份。

完成标志：输出 `BODYDATA_PREPARED ILCE-7CM2 2.01 ALLLANG`。
细节见 [启动资产](boot-assets.md)。

### 第 2 步：打开相机控制台窗口

文件：`runtime/analysis/camera_ui.py` → `menu_control.py`。

1. 创建 GTK 单窗口（LCD 画布 + 按键/拨盘 + ON/OFF + SD/Wi-Fi 控件）。
2. 构造一个由本窗口**独占**的 `VM` 对象（`menu_control.VM`），
   绑定持久实例目录（配置代数、历史运行资料）。
3. 若有已保存配置代数，经 `settings_instance.load_for_boot` 取出 Backup
   并设置 `A7C2_SETTINGS_RESTORE*` 环境变量；没有则从首设开始。
4. 点 ON（或自动启动）后，`VM.start()` 在线程里跑 `_run()`：
   建 socketpair 作为控制通道（guest 侧 fd 约定 20），
   通过 `start-menu.py::profile_environment` 生成**自然启动 profile**
   （`natural_boot=True`：headless OSD、软件 LZ77、GPE RGBA4444、
   原语言字体、GUI 模型、RM 文件媒体、日期/音频/HDMI 等服务开关），
   然后启动 `run-menu-probe.sh`。

完成标志：控制通道收到 `ready` 消息，UI 状态进入 `running`。

### 第 3 步：运行器自检与重建

文件：`runtime/analysis/run-menu-probe.sh`。

1. `flock` 抢占探针锁（fd 9），防止两个 VM 并发踩同一运行目录。
2. 若传入了虚拟 SD 镜像，先做宿主侧来源校验（`sd_transport.card_source`）。
3. 有 `native-assets.json` 时先 `--check-runtime` 复核已安装资产。
4. 默认重建观测器 `menu-observe.so` 和实验 initramfs
   （`prepare-menu-initramfs.sh`：从固件树组 cpio，生成 guest `/init`、
   注入观测器、seed setting/Backup、语言字体；可选追加 SD FAT 种子）。
   忘记重建会让旧观测器假装是干净实验，所以默认不跳过。

完成标志：打印 `rebuilt observer + initramfs`，进入 qemu-menu-probe。

### 第 4 步：装配并启动 QEMU

文件：`runtime/analysis/qemu-menu-probe.py` → `qemu-kernel-probe.sh`。

qemu-menu-probe.py 先做**启动前身份核算**：

1. 逐个比对将要进 guest 的关键文件的 SHA256
   （`appFw.so`、`libObj.so`、`libgpe.so`、观测器、语言字体、
   媒体/音频/配置相关库和 seed 文件），对不上就拒绝启动。
2. 写本次运行的 `runtime-manifest.json`，准备 `menu-runs/<run-id>/` 目录。

然后 `qemu-kernel-probe.sh` 真正拼 QEMU 命令行：

1. **DTB 修补**：用 libfdt 在固定地址 DTB 上更新 `chosen` 的 bootargs 和
   initrd 起止地址；自然启动走高 DDR 布局（24 GiB 内存配置，
   DTB 装载 `0x400002000`、内核 `0x400080000`、initrd `0x440000000`），
   并拒绝重叠的静态虚拟映射。
2. **隔离**：`bwrap --unshare-all` 沙箱，只读挂载工具链和内核/initrd，
   `-nic none` 默认无网络（隔离 USB 以太网是显式 opt-in profile）。
3. **机器**：`-machine virt,secure=off -cpu cortex-a35 -smp 1`，
   `-serial stdio` 作为唯一控制台，`-qmp unix:/out/qmp.sock` 供宿主控制，
   `-no-reboot -sandbox on`，trace 写 `/out/boot-trace.log`。

完成标志：QMP 握手成功，控制台出现 guest shell。

### 第 5 步：内核启动到 guest shell

initramfs 的 `/init` 只挂 devtmpfs，然后把 shell 接到 `ttyAMA0`。
宿主等待 console.log 出现 `/ #`，25 秒内不到就判失败
（`Merged filesystem did not reach shell`）。
完成标志：`/ #` 提示符出现。**注意：到 shell 只证明内核活了，
不证明任何相机程序启动。**

### 第 6 步：按依赖顺序搭建 guest 运行环境

宿主通过串口逐条下发 `setup` 命令（qemu-menu-probe.py 中构造），顺序即依赖：

1. **基础挂载**：proc、sysfs、`/tmp`、`/setting`、`/tmp_wbshd` 用 tmpfs；
   设置 PATH / LD_LIBRARY_PATH；建 cpuset cgroup 分组。回显 `MENU_ROOT_READY`。
2. **语言字体**：复制已校验字体到 `/tmp/images/` 并逐个 SHA256 复核。
3. **IPC 与内核模块**：`devno.ko` → `osal_utm.ko` → `osal_uipc.ko`；
   随后 `utimer.ko`；seed Backup（`Backup_load=1`，保存写回是显式 opt-in）；
   `stream.ko`/`stream2.ko`；seed setting → `ulogio` → `dmm.ko`（带
   DmmCfg.bin）→ `grm_ma.ko`；`upm.ko`（电源）；`udate.ko` + 原日期时钟种子
   （失败则直接中止，不启动应用）；音频 backing、kikilog 等按 profile。
4. **固件身份**：造一个虚拟 `nflasha1`（ramdisk + FAT），
   让原固件能读到自己的版本身份，回显 `VIRTUAL_FIRMWARE_IDENTITY_FILES_READY`。
5. **上电种子与服务开关**：`seed-power-on` 写入启动类型；
   各原服务（CapID、SA 地址、HDMI 格式/照片、DMM、显示信息、软件 GPE、
   headless OSD 等）以环境变量声明给观测器/服务层。
6. **媒体**：RM 文件媒体 profile 把虚拟卡（FAT 镜像）放到 `/image_mmca`，
   经 `file-media-config.so` 预加载接入原 Fsys/RM 路径；SD 热插拔默认开启。
7. **观测器自检**：`menu-observe.so` 自测、寄存器/读内存工具自测，
   通过后才允许带 `LD_PRELOAD` 启动应用。

完成标志：各 init 标记（如 `DATE_CLOCK_INIT_OK`、字体摘要、模块 MOD_OK）
全部按预期出现；任一硬失败则中止启动。

### 第 7 步：启动原相机应用

自然启动 profile 使用原启动管理器：

```
LD_PRELOAD=<观测器与媒体配置> /usr/bin/bootin.elf 'target=qemu ' dmode=3 &
```

（研究探针 profile 则直接跑 `im.elf target=qemu`。）
bootin.elf 按原启动链拉起各服务进程和 IM 主程序；观测器在旁只读记录
CreateScreen、OSD 提交、输入队列等。

完成标志：首设或主界面屏幕被创建，headless OSD 开始产出帧。

### 第 8 步：首设 → 拍摄主界面

无已保存配置（或用户点了"销毁并重新初始化"）时，固件进入原厂首设：

1. **语言选择**（已验证简中等原语言列表，字体为原固件解码显示）。
2. **日期/时间设置**（原日期服务；日期确定键等输入已逐项校准）。
3. 完成后进入**拍摄主界面**：HUD 与 MENU 可由原按键调出，
   已验证 C1/半按/全按/REC 等八个原输入的限定回归。

画面路径：guest 内 headless OSD 导出 → 宿主解码为 640×480 PNG
（RGBA4444 软件转换）→ GTK LCD 画布。UI 只显示**本次 VM、经校验**的帧，
旧帧明确标注"旧画面"。

完成标志：拍摄页面 HUD 出现在 LCD 画布，且按键输入产生原固件画面变化。
**当前边界**：取景（CMOS 实时图像）区域仍黑；REC 走向媒体选择/容量链路，
"插槽2无卡/无空间"等提示的真实业务状态仍在调查中，照片与录像未通过。

### 第 9 步：运行中操作与关机保存

- **输入**：UI 按键 → 有界队列 → 控制通道 → guest 注入 → 以固件新画面为响应
  （队列满/VM 未运行/SD 介质变化未收敛时拒绝，不静默丢弃）。
- **SD 热插拔**：安全拔出/插入走原 RM 通知链路，状态未收敛时暂停机身输入。
- **关机**：OFF 先把虚拟 SD 刷新并导出（Flush 原返回 0、整卡 SHA、独立 fsck=0
  为验收），成功后才退出 QEMU；保存失败则 VM 保留运行，不假装已关闭。
- **配置**：退出时把 Backup/设置快照发布为新代数；下次 ON 从该配置恢复，
  跳过首设直接进入拍摄主界面（恢复链路的完整验收仍在进行）。

## 每一步对应的深入文档

| 启动步骤 | 深入文档 |
| --- | --- |
| 第 1 步 资产 | [boot-assets.md](boot-assets.md) |
| 第 2/4 步 地址与观测 | [debugging-playbook.md](debugging-playbook.md) |
| 第 7/8 步 画面 | [display-first-pixels.md](display-first-pixels.md) |
| 第 8/9 步 输入 | [input.md](input.md) |
| 第 6/9 步 存储与 SD | [storage.md](storage.md) |
| 第 2/9 步 配置代数 | [settings-persistence.md](settings-persistence.md) |
| 第 4 步 隔离网络 | [network.md](network.md) |
| 第 8 步 媒体状态/容量 | [media-state-and-capacity.md](media-state-and-capacity.md) |
| 第 8 步之后 成像/录像 | [imaging-and-recording.md](imaging-and-recording.md) |

## 当前进度矩阵（启动视角）

| 阶段 | 状态 |
| --- | --- |
| 资产导入与身份固定 | 通过（仅 2.01 ALLLANG） |
| QEMU/内核/DTB/initramfs 到 shell | 通过 |
| guest 环境（模块、服务、字体、身份、上电种子） | 通过（按 profile） |
| 原应用 bootin/im 启动 | 通过 |
| 首设（语言/日期） | 通过（原 GUI 操作验证） |
| 拍摄主界面 HUD/MENU + 主要按键 | 通过（限定回归） |
| 虚拟 SD 读写/热插拔/保存导出 | 通过（含独立 fsck/SHA） |
| 配置跨重启恢复 | 部分（有限结果，完整验收进行中） |
| 取景（CMOS 实时图像） | 未通过（区域仍黑） |
| 媒体选择/容量真实业务状态 | 调查中（REC 提示链未闭合） |
| 照片 / 录像 / 真实合焦 | 未通过 |

## 启动排查速查表

以下都来自项目实际遇到的问题；右栏是不能外推的范围。

| 检查层 | 本项目实际有效的做法 | 局限 |
| --- | --- | --- |
| 原资产 | 固定身份、大小、SHA、源码固定资产清单 | 只支持已核 2.01 ALLLANG |
| 工具链 | 分开宿主工具和 Sony glibc 2.25 guest ABI | 宿主链接通过不保证 guest 可加载 |
| 内核 | 核实际串口 command line 和执行标记 | shell 不证明相机应用启动 |
| DTB | 修改 chosen/initrd 描述并保留预留区 | A7C II 地址不适用于其他板 |
| initramfs | 区分 ext2 原 initrd 和生成 cpio | 大镜像解包仍受 guest RAM 限制 |
| 根文件系统 | 原依赖顺序、guest 链接与执行权限检查 | 文件存在不等于服务可用 |
| 串口 | 完整日志、唯一 RC 标记、跨块异常监视 | 混入日志会污染数据导出 |
| 首帧 | 真正执行绘图、解码、带租期复制 | AP OSD 不是 CMOS 图像 |
| 最小可观测面 | run 身份、输入清单、console、原返回、内容摘要 | 单个 ready/成功码不能代替终点 |
| 退出 | 调试恢复、原存储屏障、导出、owner 恢复 | 清理成功不能把业务失败改成成功 |

## 证据入口与版本顺序

- [本包说明](../../README.md) 与 [本包验收](../../validation/README.md)：独立包实际范围。
- [研究 README](../../../a7c2-re/report/2026-10-17-qemu-native-camera/README.md) 与 [STATUS](../../../a7c2-re/report/2026-10-17-qemu-native-camera/STATUS.md)：研究基线及历史纠正。
- [九项验收](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/nine-feature-acceptance.md)：按功能看剩余合同。
- [完整系统状态](../../../a7c2-re/report/2026-10-17-qemu-full-system/STATUS.md)：只作独立路线对照。

报告通常保留旧失败和旧“待验”；先看“最新结果/更正”，再读过程。
同一篇旧段落里写过“根因已定”，不能跳过后续撤回说明。
本组各篇列出具体证据入口，不把 native/full 的运行结果混成本包的新运行。

## 事实回核记录

本次只做源文档/源码回读，未重跑原实验，未把既有结果称为本次动态验证。

| 抽核事实 | 回核原文/源码 | 处理 |
| --- | --- | --- |
| 两个语言字体大小/SHA | `runtime/analysis/language_fonts.py::FONT_SPECS` | 只保留路径、大小和摘要 |
| RGBA4444小端及B/G/R输出 | `runtime/analysis/ramfb-viewer.c::convert` | 明确是软件模型 |
| Thumb ADR16相对寻址 | native `report/cp-barrier-static-correction.md` | 不抄反汇编相对量作绝对地址 |
| opcode9 mask1筛R0、实际通知改R1 | native `report/sd-hotplug-progress.md` | 只称本模型配置修复 |
| Backup bank尺寸/起点及WriteComp低字节 | native `report/backup-noop-sync-contract.md` | 不猜高位或全部SID语义 |
| dispatch1052值域与PP黑电平转接 | native `report/media-producer-frontier/README.md` | 撤回媒体容量标签；所有目录派生媒体标签均需另证 |
| 启动命令行与模块顺序 | `runtime/analysis/qemu-menu-probe.py`、`qemu-kernel-probe.sh` | 只记录当前 profile 实际顺序 |
| 首设→主界面链路 | native `report/first-setup-frontier.md`、STATUS | 首设完成持久化仍未完成，不夸大 |

新增镜头/像素合同只补静态几何、字段和容量检查边界，不计完整快照或像素实测。
CMOS字节/位顺序、plane、freshness/lease、全配置及虚拟AP扫描/关联仍未核为完成。

## 如果你在做别的机型

优先搬走分层、地址换算、内容校验、所有权和失败记账方法。
重新推导内存图、服务 ID、输入码、资源格式和原配置结构。
不要只放宽 A7C II 导入器的型号限制就声称支持新机型。
从第一个尚无内容证据的步骤开始，每次只争取闭合一条边。
