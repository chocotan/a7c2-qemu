# 原 RAM0、init、pivot 与原菜单冷启动

本轮把原用户态冷启动链接入独立产品：从同一内部盘的官方 p3 提取原 kernel/RAM0，执行原 `/sbin/init`，由原 `setup_rootfs` 挂载 p7、`pivot_root`、`chroot`、卸载旧根并执行原 BusyBox `freeramdisk`，再由原 `/sbin/init2` 启动原 bootin/im/appFw。

最终直接执行 `--new-instance` 从本产品官方缓存创建新盘，原首设、拍摄HUD、严格中文菜单及返回、逐键原App32双边和稳定焦点、19卷原内核冻结与QMP0/无信号退出均通过；8份运行源码前后无漂移。停止盘10个实际挂载卷结构均通过，p7与派生时整片相同，p15与官方factory整片相同。[机器可读收据](../../validation/original-cold-boot-20261109.json)绑定原图、源、阶段与保留的失败。

这是显式本机虚拟硬件下的原用户态启动，不是完整 Sony 硬件上电。BootROM/loader、真实 CP 执行、WBI/RAM 热恢复、原 watchdog、USB枚举/认证和成片没有因这一条链通过而升级。本页收据记录独立 CLI 的原链验收。后续源码已把默认 `./start.sh` 与 GTK ON 接入该路线，独立窗口、文件测试及保存的实际结果见[窗口集成记录](2026-11-09-original-cold-window.md)，不借用本页 CLI 结果认证窗口。

## 复现

先按主 README 准备自己的 2.01 ALLLANG BODYDATA、固定 QEMU 源码，完成产品导入和编译。然后在产品目录运行：

```bash
python3 tools/run-original-cold.py --new-instance \
  --output runtime/diagnostics/my-original-cold --seconds 180
```

输出目录必须不存在。`--new-instance` 只从本产品已校验的官方包缓存创建独立内部盘，不使用真实磁盘、系统 dump 或研究仓库。普通构建依赖需要 e2fsprogs、AArch64 GCC/binutils、Clang/lld，以及主 README 中的依赖；`tools/check-host.sh` 会检查。

同一个实验盘再次启动时，指定它的实例目录及新的输出目录：

```bash
python3 tools/run-original-cold.py \
  --instance runtime/diagnostics/my-original-cold/storage/default \
  --output runtime/diagnostics/my-original-cold-second --seconds 180
```

已有实例的 p7 会增加明确的虚拟适配文件，原脚本及未触及文件保持原字节；原 p7 前像和完整树校验记录保存在该轮 `build/` 中。请使用专属实验实例。构建和运行持有产品共享排他锁；另一个产品会话运行时，原链入口在创建输出或改盘前拒绝。实例自己的磁盘租约也持续持有到 QMP owner 与后裔退出。

只做准备、不启动 guest：

```bash
python3 tools/run-original-cold.py --new-instance \
  --output runtime/diagnostics/my-original-cold-prepared --prepare-only
```

这个选项仍会创建实验盘和派生 RAM0/p7，但不执行相机程序。

## 代码边界

| 部分 | 行为与证据 |
|---|---|
| `original_cold_boot.py` | 从当前租约盘 p3 提取 kernel/RAM0；固定原 SHA，原 2.01 导入/原 ELF/观察器构建身份核齐；RAM0 按辅助文件预算生成，最小192MiB；服务逐文件按大小/SHA搬移到 devtmpfs，释放 RAM0 前结束搬移进程 |
| `cold/bootstrap.sh` | 准备虚拟块设备和19个实际容量；最后真正 exec 原 `/sbin/init`，不在适配器中手动替代原 pivot/chroot |
| 原 RAM0 与 p7 | 原 init/init2/setup_rootfs/fstab/驱动列表按固定摘要保留；完整树和未触及硬链接关系核对；派生 p7 写盘后完整摘要读回 |
| `cold/insmod.sh` | 原 init 仍执行原驱动列表；已有有限硬件合同的资源模块走原 insmod/原返回码，其余明确78拒绝，不空成功；Backup 使用从实际文件加载的已验参数 |
| `cold/bootin.sh` | 仅成功完成 init2 准备才进入 AP；已有功能模型、时钟、声效、原viewer复用产品源码；最后 exec 原 bootin，原 im/appFw 未替换 |
| 语言与菜单 | 按原LCD“简体中文”文字及唯一橙色行定位，方向键/ENTER都走原App32；主屏/菜单当前screen、原输入释放边、菜单控件像素和连续稳定帧分别核对 |
| 关闭 | 调用原内核 freeze_bdev 同步冻结19卷，读回1/19；单次正常 QMP quit、owner rc0/无信号、后裔退出才释放租约。这里不把冻结快照称为原相机关机或卸载 |

实际 kernel/RAM0/p7来源绑定、host输入和派生盘在新 launch 租约下再次核 SHA，拒绝 build/launch 间内容变化。原 `/proc/1/mountinfo`、完整 `/proc/cmdline`、Uid/Gid四零、原ELF实际guest摘要、原脚本有序交接日志、LCD与输入边都分别保存。

## 失败及修复

本轮所有失败原结果、日志和私有镜像保留，不回填。

- 初次已实际执行原链，但 checker把 mountinfo 当 mounts 格式读，误报根挂载失败。修后以唯一只读 p7根、原usr卷、无旧initrd挂载及四零UID/GID核对；另留原字节离线复核。
- 显示曾先读到上一boot残留seq1快照，再拒新boot同序号内容。冷链改用已有单盘路径的同一份每boot模拟状态清单，原viewer序号/内容校验不改。相机设置和原配置不在清理列表。
- 初移植启用了pin连接，却遗漏对应保留RAM。原日志明确backing绑定失败；补成对guest开关与原已验8KiB保留区后，原LCD实际显示。旧黑帧不改记通过。
- 固定要求8MiB空闲阻碍已有字体的重启；改为已有字体先核全SHA，匹配就复用，缺失项才按尺寸加余量检查空间、写后再核SHA。准备失败时只尝试一次，不重复把wrapper绑定为“原bootin”。
- 一轮自动menu=true但主会话看图发现PNG仍是HUD。原结果保留并另存否定审查，后续必须匹配原“MENU关闭”控件及稳定菜单像素，不能只看factory调用和HUD变化。
- 原语言导航按字体首次打开后相对步数会偏移到越南语。已改实际中文文字/橙色行内容定位，未知页不发送确认；对应原图和失败保留。
- 一个复用实验盘的原AP结果通过，但停止盘p10有9个孤链/147456B；只读核对其输入盘发现相同遗留。原失败盘未修，最终改为实际用户CLI `--new-instance` 从官方干净卷创建；新盘原AP与10卷结构通过，不能把输入坏盘检查回填成正常。
- 首次干净实例方向键双边已消费，但固定300ms截图没有及时看到焦点。改成每个键必须实际改变并连续两帧稳定后才发下一键，内容判据保持严格。

## 验收记账

源码、构建/host、原AP实际消费分别记账。已有 v4 原init/pivot/init2/RAM释放、可读语言页、4条DOWN/UP输入边和正常退出；v7又实际完成简体中文首设、拍摄HUD、严格中文菜单控件像素与MENU返回。最终发布收据绑定最终源码的同轮原AP运行，不能拿早期通过直接抵作最终版本验证。

正式集中回归两工作线程：host376通过/39跳过/95子测试；cold公共模型与清单subset48通过，真实libfdt/原cold准备边界与现有SMP布局12通过，离线QEMU三补丁/设备源、依赖和旧脚本同步检查均rc0。未改的旧模型/GTK/驱动组不重复重跑；新cold纯host组已注册到250组公共入口，真实board准备集成组另列。

最终原链原图、输入、根挂载、19卷冻结、正常QMP退出与停止盘结构结果见 `validation/original-cold-boot-20261109.json`。所有实验仅本机普通虚拟盘；完整BODYDATA更新、拍摄写卡继续暂缓，recovery归档/镜像删除按用户新指令暂停。
