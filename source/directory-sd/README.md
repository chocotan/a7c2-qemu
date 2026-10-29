# 目录 FAT 工作副本

`vvfat.c` 是从锁定的 QEMU 11.1.2 `block/vvfat.c` 出发、供审查和生成补丁用的项目内工作副本，不再使用 `/tmp` 保存修改。这里不是另写宿主文件系统：正式运行仍是 QEMU 原生 vvfat，补丁只覆盖已实测的固定容量、FAT32 元数据、原 Fsys 写序、Linux 页写回边界及嵌套 mapping 生命周期。`virtfs/9p` 不是 USB/SCSI SD，不能替代本路线。

正式可复现构建仍由上级 `build-qemu.sh` 从原始源码包解包，依次应用已校验的 native、directory-sd、USB 补丁；它不会直接编译这个工作副本。`source/qemu-directory-sd.patch` 是原始文件与本工作副本的统一差异，`source/qemu-directory-sd.json` 固定补丁及修改后文件摘要。修改工作副本后运行 `python3 source/directory-sd/regenerate-patch.py` 重新生成补丁及摘要，再从干净源码构建验证。脚本同时生成 QAPI `BlockdevOptionsVVFAT.total-sectors` 的补丁，不需要 `/tmp` 工作源码。

## 写回边界

原 Fsys 会先写目录数据并同步，再写 FAT。`vvfat` 的 qcow 层因此可能暂时含有尚未映射回宿主目录的数据：中间和重复 flush 都必须真实同步 qcow，并可幂等成功；只有 FAT/目录一致时才执行宿主提交和文件/目录 `fsync`。实际 qcow/宿主写回错误不吞掉。backend 发出实际待提交/已提交状态事件，宿主快照必须确认跟踪就绪且最后不是待提交，并要求原 Fsys 读回及退出后的精确文件内容，不能把中间 flush 当作最终保存。

新创建的 FAT 8.3 名称可能按 vvfat 默认策略在宿主上落为小写；验证器使用唯一、不区分大小写的 FAT 路径解析，仍拒绝符号链接、歧义及任何内容差异。

Linux 页写回还可能把文件末尾页的少量扇区写入后继空闲簇。只有当前一簇是已使用且结束的完整链、当前簇 FAT 为空闲、并且 qcow 仅有连续前缀的部分扇区时，才将该簇视为未引用页填充；完整、稀疏或任意未归属写入仍拒绝。`array_insert` 新增的 mapping 和 direntry 区间也分别显式初始化，避免嵌套目录继承残留状态。

