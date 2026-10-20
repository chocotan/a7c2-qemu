# 来源与固定身份

项目代码基线来自同一工作区的 `a7c2-re/report/2026-10-17-qemu-native-camera`；这是来源描述，运行时不读取该目录。本包保留其 `runtime/analysis` 相对布局，未复制 `source/build`、旧运行目录、私有 setting、完整 dump、Sony 原始固件和原厂派生资产。合成 `fixtures/headless-osd.b64` 是测试向量，其来源说明在相邻 README。

逐文件选择与原始 SHA 在 [SOURCE-ORIGINS.json](SOURCE-ORIGINS.json)，最终文件 SHA 在 `SOURCE-SHA256SUMS`。原始摘要与最终摘要可用于识别本包适配变更；清单不是签名或供应链安全背书。

| 组件 | 来源 | 固定依据 |
| --- | --- | --- |
| QEMU 11.1.2 完整归档（Git 不含） | 用户自行下载 https://download.qemu.org/qemu-11.1.2.tar.xz ；本地原归档身份保留在 `SOURCE-ORIGINS.json::external_inputs` | SHA-256 `731b5681e4bb18be313231579b8efd0296c5b015fa36dc533874b639ba838016` |
| Sony 虚拟板/输入/timer 等修改 | 基线 `qemu-sony-native.patch` | `source/manifest.json` 绑定 patch 和逐文件 before/after |
| sysbus xHCI | 基线 `qemu-sony-usb.patch` | `source/qemu-sony-usb.json` 绑定前一 patch 与逐文件 before/after |
| DTC/libfdt | 基线公开源码树；上游 https://git.kernel.org/pub/scm/utils/dtc/dtc.git/ | `source/manifest.json::dtc_source_files` 全树逐文件 SHA；不依赖本地归档/构建结果 |
| fwtool SDK 和 FAT 子集 | 基线公开副本；上游 https://github.com/ma1co/fwtool.py | 原始文件 SHA 及相邻 MIT 许可证；保留已有解密 API，不自动下载 SDK |
| device-models | 基线的公开副本 | 相邻 `UPSTREAM-COPY.json` 为历史共享模型出处，本包运行/构建只读本地模型，不读取 full-system/private |

发布准备时对上述官方归档直链执行 HEAD，得到 HTTP 200 和 141,815,216 字节；未重新下载文件或核验 Git revision。构建身份仍以实际归档/源码 SHA 为准，而不是推测上游最新版本。`manifest.json` 中 `dtc_sha256` 是历史归档记录，构建实际校验随附的完整 `dtc_source_files` 树。

按用户最终要求，QEMU 归档由使用者自行下载，不纳入 Git、不分卷、不使用 LFS；本地已有归档保持忽略，固定身份记录为显式外部输入。项目补丁、DTC 与许可证均完整纳入 Git，构建器不会隐式下载或接受其它摘要。

本包必要适配：

- 移除 initramfs 准备脚本的相邻真机 setting 备用路径，只保留官方 ALLLANG 来源。
- 修正兼容 `start-menu.py` 的工作根为本目录；移除网页控制器历史研究截图读取，保留网页源码。
- `start.sh` 使用包内临时目录并关闭 Python 字节码写入；构建入口增加不触发构建的帮助信息。
- USB socket 短别名迁到 `/var/tmp`，仅替换当前用户、同一运行目录的旧链接，拒绝删除其它文件；避免宿主 `/tmp` 配额限制。
- 增加主机依赖检查、源码两阶段身份检查、受限 host 测试入口、中文文档和清单。
- 排除两个只适用于 full-system、且依赖该路线启动器的 ADF/HDMI pin 校验脚本；本机原生运行链不使用它们。

设备协议、CP 控制、SD adapter 和采集能力保持该基线，不因重新打包扩展验收结论。未引入 Sony 反编译伪代码或冒称拥有原厂源码。
