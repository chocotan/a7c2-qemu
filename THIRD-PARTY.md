# 许可证与公开分发边界

顶层 [LICENSE](LICENSE) 是项目自行编写代码和文档的 MIT 许可证，不会覆盖第三方或 Sony 原始内容。

| 内容 | 许可/边界 | 随附文本 |
| --- | --- | --- |
| 项目启动器、辅助模型、GUI、测试 | 项目 MIT；文件内第三方声明优先 | `LICENSE` |
| QEMU 完整基底（使用者自行下载）及 Git 内的 QEMU 源码修改补丁 | QEMU GPL-2.0 及各上游文件声明；修改 QEMU 的补丁按相同适用许可，不作为纯 MIT 原厂源码 | 用户下载的完整归档内 COPYING/LICENSE；`source/licenses/QEMU-GPL-2.0.txt`、`QEMU-LICENSE.txt` |
| DTC | GPL，以文件 SPDX/上游说明为准 | `source/dtc/GPL`、`README.license` |
| libfdt | GPL/BSD 双许可，可选 BSD-2-Clause | `source/dtc/BSD-2-Clause`、`source/licenses/libfdt-BSD-2-Clause.txt` |
| fwtool SDK、FAT 子集 | ma1co MIT | 各 vendor 目录的 `LICENSE.txt`、`source/licenses/fwtool-MIT.txt` |
| 宿主 Pillow、PyCryptodome、GTK 等 | 由使用者安装，保留各自上游许可；不被顶层 MIT 重新授权 | 宿主发行包/可选本地依赖原始 license metadata |
| Sony BODYDATA、原内核/库/字体/设置、派生镜像与伪代码 | Sony/相应权利人的原许可；不在本源码分发内，也不按 MIT 授权 | 使用者自行取得官方输入 |

`runtime/analysis/vendor/host-python/` 是被忽略的本地验证加密依赖，含预编译扩展；不属于本源码清单。`incoming/`、`runtime/bodydata-cache/`、`menu-root/`、`unpacked/`、运行日志/卡/截图同样不属于公开包。不要用 `tar runtime/` 或直接压缩整个工作目录分发；仅分发源码清单内文件及对应 SHA 清单。原始固件与用户修改的原库也不能因被本脚本读取就视为项目开源源码。
