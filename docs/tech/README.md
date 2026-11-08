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

需要验证原 RAM0/init/pivot/init2 路线时，使用[原冷启动独立入口](2026-11-09-original-cold-boot.md)。它创建专属内部盘，默认 GTK 的 ON 尚未切到该路线；原 BootROM/CP/WBI等硬件阶段继续独立未完成。

运行数据写在 `runtime/`，不是输入固件。虚拟卡位于 `runtime/analysis/menu-runs/run-*/SD/`，设置位于 `runtime/analysis/camera-instances/`。关闭窗口会调用本实例的保存和退出流程；如果界面提示保存失败，应先处理错误并保留运行目录。

如果用覆盖目录测试自制程序，先移开覆盖文件再启动原版本。不要用历史 ELF、旧运行截图或空白资源替代导入失败的固件文件。
