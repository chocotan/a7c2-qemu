# A7C II QEMU 模拟器

## 这是做什么的

在 Linux 电脑上运行 Sony A7C II（ILCE-7CM2）的原厂固件，通过一个相机外观的窗口查看原厂界面、操作菜单，方便研究和调试相机软件，无需连接真实相机。

目前可以进入拍摄主界面和菜单，**还不能拍照或录像**。拍摄主界面的取景区域仍是黑色。

## 现在有什么功能

- **运行原厂固件**：从自己的 2.01 ALLLANG 版 `BODYDATA.DAT` 导入内核和相机程序。
- **显示原厂界面**：显示 640×480 相机画面，支持简体中文首设、拍摄主界面和菜单。
- **操作按键和拨盘**：通过窗口操作主要按键、拨盘和菜单；部分按键对应的拍摄功能尚未完成。
- **使用虚拟 SD 卡**：原厂程序可以向虚拟卡写入数据库等文件，关机后保存为电脑上的 `card.img`，下次可以继续使用。
- **保存部分设置**：已验证语言和日期格式在关闭整个窗口、重新打开后仍能保存和恢复，也支持确认后恢复默认设置。全部设置的保存尚未验证，启动时仍可能再次出现首次设置。
- **隔离网络通信**：支持模拟器与宿主机之间的虚拟 USB 以太网通信，暂不支持真实 Wi-Fi。

## 如何启动

需要 **Linux x86_64、Python 3.12+ 和 X11/Xwayland 桌面**。建议准备 32 GiB 内存和至少 20–30 GiB 可用磁盘。

首次使用前准备好：

1. 自己的 **ILCE-7CM2 2.01 ALLLANG `BODYDATA.DAT`**，其它版本暂不支持。仓库不提供 Sony 固件。
2. 下载 [QEMU 11.1.2 源码](https://download.qemu.org/qemu-11.1.2.tar.xz)，放到 `source/vendor/qemu-11.1.2.tar.xz`。版本和校验信息见[下载说明](source/vendor/README.md)。
3. 安装 Python 图形和加密库、QEMU 编译工具链，以及虚拟磁盘工具。下面的 `check-host.sh` 会列出缺失的命令、模块和开发库。Python 构建环境还需提供 pip、setuptools 和 wheel。使用普通用户运行，系统需允许 bubblewrap 使用用户命名空间。

在本目录执行，先检查依赖和源码，再导入固件、编译并启动：

```bash
./tools/check-host.sh
python3 tools/check-source.py
./start.sh --bodydata /path/to/BODYDATA.DAT --prepare-only
./build-qemu.sh
./start.sh --bodydata /path/to/BODYDATA.DAT
```

把 `/path/to/BODYDATA.DAT` 换成自己的固件路径。依赖检查提示缺什么，先补齐再继续。脚本不会自动下载源码或安装依赖。

窗口出现后按 **ON**，等待启动，选择语言并完成日期设置，即可进入拍摄主界面和菜单。

首次准备和编译完成后，后续启动只需：

```bash
./start.sh --bodydata /path/to/BODYDATA.DAT
```

也可以将固件放到 `incoming/bodydata/BODYDATA.DAT`，以后直接运行 `./start.sh`。

关机时按 **OFF** 或关闭窗口，等待保存完成。虚拟卡保存在 `runtime/analysis/menu-runs/run-*/SD/card.img`。下次继续使用某张卡时，指定它的路径：

```bash
./start.sh --bodydata /path/to/BODYDATA.DAT \
  --sd-image /path/to/previous-run/SD/card.img
```

相机设置默认保存在 `runtime/analysis/camera-instances/default/`，下次自动恢复；虚拟 SD 卡需要用上面的参数手动选择。

### 使用 overwrite 替换固件文件

想测试自己修改的程序或库，把文件放到本目录的 `overwrite/` 下，按相机内的路径排列。例如替换相机中的 `/usr/lib/appFw.so`：

```text
overwrite/
└── usr/
    └── lib/
        └── appFw.so
```

正常运行 `./start.sh` 即会自动加载这些文件；固件不在默认位置时，照常加上 `--bodydata`。也可以指定其它覆盖目录：

```bash
./start.sh --bodydata /path/to/BODYDATA.DAT \
  --overwrite-dir /path/to/my-overwrite
```

目录中的普通文件会替换相机内同路径的文件，路径不存在时会新增。只能使用普通目录和文件，不支持符号链接。

覆盖只影响本次生成的启动镜像，不会修改原始 `BODYDATA.DAT` 或基础固件文件。要恢复原版，移走覆盖文件，并在下次启动时不再指定自定义覆盖目录；默认的 `overwrite/` 也应保持为空或不存在。替换不兼容的程序或库可能导致启动失败。

## 接下来准备实现什么

- **取景画面**：模拟 CMOS 图像输入，让原厂程序显示实际场景。
- **镜头和对焦**：补齐镜头通信、自动对焦和曝光控制。
- **拍照和录像**：打通原厂成像、编码和存储流程，将照片、视频保存到虚拟 SD 卡。
- **完善操作体验**：补齐剩余按键和拨盘功能、相机声音，以及虚拟 SD 卡热插拔。
- **完善设置保存**：保存首次设置完成状态，并验证更多参数能够跨次启动恢复。

以上功能仍在开发中，没有确定的完成时间。详细进度和验证结果见[验证记录](validation/README.md)；源码来源与许可证见 [SOURCES.md](SOURCES.md) 和 [THIRD-PARTY.md](THIRD-PARTY.md)。
