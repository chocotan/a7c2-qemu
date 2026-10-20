# QEMU 源码下载

请使用者自行下载官方 [qemu-11.1.2.tar.xz](https://download.qemu.org/qemu-11.1.2.tar.xz)，放到本目录：

```text
source/vendor/qemu-11.1.2.tar.xz
```

文件大小为 141,815,216 字节，唯一接受的 SHA-256：

```text
731b5681e4bb18be313231579b8efd0296c5b015fa36dc533874b639ba838016
```

下载后，在仓库根运行 `python3 tools/check-source.py`，会验证归档、DTC 及两阶段补丁应用前后身份，不编译、不启动 VM。版本/摘要同时绑定在 `source/manifest.json`，不能用其它版本替代。

按用户要求，Git 不包含该大归档，不分卷，也不使用 Git LFS；本地下载归档被 `.gitignore` 排除。构建和启动器不会自动下载。完整 QEMU 许可保留在官方归档内，仓库另有 `source/licenses/` 文本。DTC、项目模型/启动器、两阶段 QEMU 补丁及许可证直接纳入 Git。

本次发布准备对上述官方直链执行 HEAD，返回 HTTP 200、content-length 141815216；未重新下载归档。链接后续可用性由上游决定，构建始终以固定 SHA 为准，也接受使用者保存的同 SHA 离线文件。运行不读取旧研究树。
