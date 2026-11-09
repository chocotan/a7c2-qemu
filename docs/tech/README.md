# 构建与启动排障

在 `a7c2-qemu` 目录运行。除了 README 列出的主机工具，外部只需要自己的 ILCE-7CM2 2.01 ALLLANG `BODYDATA.DAT` 和 QEMU 11.1.2 源码归档。

先检查本机依赖与输入：

```bash
./tools/check-host.sh
python3 tools/check-source.py
./start.sh --bodydata /path/to/BODYDATA.DAT --prepare-only
```

QEMU 归档应放在 `source/vendor/qemu-11.1.2.tar.xz`。缺少归档或摘要不同会明确拒绝，不自动下载或改用其它版本；固定身份见 [来源说明](../../SOURCES.md)。准备过程从 BODYDATA 导入原厂程序、内核、布局、语言和字体；不读取相机 dump、研究仓库或历史实验目录。

准备通过后构建并运行：

```bash
./build-qemu.sh
./start.sh --bodydata /path/to/BODYDATA.DAT
```

首次运行可能出现语言、日期或教程页面。窗口显示的是固件实际 LCD；取景黑色或某个拍摄操作未完成时，不表示产品已经支持相机成片。当前功能范围以 [根 README](../../README.md) 为准。

无参数默认 `./start.sh` 已实际完成原 RAM0/init/pivot/init2、中文首设、原 HUD／菜单往返与正常保存退出，见[默认入口实跑与首帧等待修复](2026-11-09-default-cold-entry.md)。[窗口接线、文件开发与保存](2026-11-09-original-cold-window.md)及[原冷启动独立 CLI](2026-11-09-original-cold-boot.md)保留各自验收；原 BootROM/CP/WBI 等硬件阶段继续独立未完成。

显式 Sony USB 候选已在原 init2 Senser 服务模式通过本机 VHCI 枚举、配置1／4端点、原 jiritsu 七步认证、19B版本、worker Uid/Gid四列全零、preload中和读回与同轮正常保存退出。构建、隔离依赖及CLI用法见[USB报告](2026-11-09-usb-jiritsu.md)；普通AP菜单USB路径与通用大OUT模型仍未完成，旧失败run不跨轮回填。

窗口内 RAM 会话、保存并退出、同盘恢复原 MENU 和继续操作已实际通过，构建及操作见[窗口 RAM 使用与验收](2026-11-09-window-ram.md)。独立 CLI 的 QMP fd 迁移和 WBI 分账保留在[RAM 恢复说明](2026-11-09-ram-restore.md)；Sony WBI、物理热启动和拍摄不由此提升。

运行数据写在 `runtime/`，不是输入固件。新原 cold 默认虚拟卡为 1GiB FAT16；非零种子、全卡读回和跨冷启动验收见[1GiB虚拟SD](2026-11-10-1g-sd.md)。虚拟卡位于 `runtime/analysis/menu-runs/run-*/SD/`，设置位于 `runtime/analysis/camera-instances/`。关闭窗口会调用本实例的保存和退出流程；如果界面提示保存失败，应先处理错误并保留运行目录。

如果用覆盖目录测试自制程序，先移开覆盖文件再启动原版本。不要用历史 ELF、旧运行截图或空白资源替代导入失败的固件文件。
