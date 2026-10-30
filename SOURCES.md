# 来源与固定身份

本次选择性更新加入原 API40 图像源的完整读取/功能CP读回、`015e` 显示位宽的真实RGB消费与独立`115e`生命周期，并同步ABI、构建源归档、profile、正式内容检查和host测试。selector0仅定义为本功能模型的RGB888八位分量；Sony物理位深与f039效果未知。原厂JPG/MP4仍未完成。

最终文件身份由 `SOURCE-SHA256SUMS` 绑定；`SOURCE-ORIGINS.json::display_source_port` 记录本次逐文件来源与发布适配，旧 `functional_camera_port` 等记录保留原历史身份。本包实际执行范围见 `validation/2026-10-30-publication.json`，研究源冻结结果不抵作本包native验收。

项目代码基线来自同一工作区的 `a7c2-re/report/2026-10-17-qemu-native-camera`；这是来源描述，运行时不读取该目录。本包保留其 `runtime/analysis` 相对布局，未复制 `source/build`、旧运行目录、私有 setting、完整 dump、Sony 原始固件和原厂派生资产。合成 `fixtures/headless-osd.b64` 是测试向量，其来源说明在相邻 README。

逐文件选择与原始 SHA 在 [SOURCE-ORIGINS.json](SOURCE-ORIGINS.json)，最终文件 SHA 在 `SOURCE-SHA256SUMS`。原始摘要与最终摘要可用于识别本包适配变更；清单不是签名或供应链安全背书。

| 组件 | 来源 | 固定依据 |
| --- | --- | --- |
| QEMU 11.1.2 完整归档（Git 不含） | 用户自行下载 https://download.qemu.org/qemu-11.1.2.tar.xz ；本地原归档身份保留在 `SOURCE-ORIGINS.json::external_inputs` | SHA-256 `731b5681e4bb18be313231579b8efd0296c5b015fa36dc533874b639ba838016` |
| Sony 虚拟板/输入/timer 等修改 | 基线 `qemu-sony-native.patch` | `source/manifest.json` 绑定 patch 和逐文件 before/after |
| sysbus xHCI | 基线 `qemu-sony-usb.patch` | `source/qemu-sony-usb.json` 绑定目录卡阶段与逐文件 before/after |
| 256GB目录虚拟SD、DMA/ATU/PCI模型 | `qemu-directory-sd.patch`、`source/directory-sd/` 及 `report/virtual-pcidma/`、`report/virtual-dma330/` | 三段patch身份及硬件staging的真实源码读回；`tools/check-source.py` 离线核验 |
| 功能相机、光学、RGB、JPEG/H264模型与原SDK适配 | 本包 `report/functional-*`、`report/virtual-*` 与 `runtime/analysis/` | 项目源码与实际host测试；物理ASIC/原CP模块和原固件成片仍未验证 |
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
- 增加主机依赖检查、三段patch及DMA/ATU/PCI暂存身份检查、受限host测试入口和显式host编译模型自测；后者需要libjpeg及FFmpeg开发库。
- 纯源码包缺少原ALLLANG seed时，settings的两处字节fixture明确skip；有文件但摘要错误仍失败，无资产的实例/路径测试继续执行。公开host入口不依赖分发原Backup。
- `runtime/analysis/scratch/` 只随附公开检查器实际导入的有限研究脚本源码；旧baseline、绝对路径输入、意图、构建产物和运行数据均未移交。普通使用与软件模型自测分别走 `start.sh` 和 `tools/test-public-models.py`，不把历史driver当当前可直接运行的验收。
- 排除两个只适用于 full-system、且依赖该路线启动器的 ADF/HDMI pin 校验脚本；本机原生运行链不使用它们。

设备协议、CP控制与SD adapter按本次显式来源快照移交，不因重新打包扩展验收结论。原固件和完整派生资产未纳入分发；报告中的有限字节锚点、反汇编与协议研究不冒称Sony原厂源码，也不由项目MIT许可证重新授权原内容。

后续选择性移交分别由`SOURCE-ORIGINS.json`的`settings_port`和`sd_hotplug_port`记录来源快照；旧基线SHA保留，不用最终适配文件覆盖历史来源。SD移交范围为单卡RM通知生命周期、原文件系统退休观察、控制器/GTK及对应测试，保留包内路径和socket保护；可选内容摘要观察默认关闭，研究用4KiB诊断preload不随包发布。标准RM2自然启动默认策略、超时回归和验证说明是本包适配，最终文件身份以SOURCE-SHA256SUMS为准。实际包内动态结论见validation/README.md，未验的拍摄与硬件状态不因此升级。
