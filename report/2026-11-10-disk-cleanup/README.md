# 磁盘清理（2026-11-10）

用户要求在继续开发前清理 `final/a7c2-qemu` 的磁盘占用。本次只做回收，不改代码、不启停 VM、不碰另一个仍在运行的 `analysis/scratch/` 工作副本。

## 结论

- 项目树：311 GiB → 162,066,022,400 B（151 GiB）。
- 逐项实际回收 **171,316,031,488 B（159.55 GiB）**，27 项。
- 文件系统可用量：基线 49,547,931,648 B → 233,600,643,072 B；整盘差额含并行工作副本的写入，不作为本任务回收量。

明细、逐文件 SHA、inode／mode／mtime／ctime、保留副本映射、恢复步骤和拒绝项都在
[`runtime/research/disk-cleanup-20261110/`](../../runtime/research/disk-cleanup-20261110/README.md)
（`summary.json`、`storage.json`、`dig-verified*.json`、`sd-dedupe.json`、`misc-removed.json`）。

## 主要动作

1. **失败现场 RAM 转储挖零洞**（151.8 GB）：8 份完整 `guest-memory.elf` 原地 `fallocate --dig-holes`。字节、长度、inode、mode 0400、mtime 全部保持，SHA256 与同目录 preservation 收据一致；只有分配块和 ctime 变化。先在自建样本上验证同一代码路径。
2. **构建 staging**（15.3 GB）：删除 `source/build/qemu-??????` 11 个 `mktemp -d` 残留；`runtime/sources/qemu-11.1.2/build-*` 的已安装产物保留。
3. **完全相同的重复项**（4.0 GB）：1 份诊断盘态、4 个 SD 镜像、2 个失败导入 staging 目录；每组保留逐字节相同的副本，删除前后核 keeper 的 inode／长度／SHA。失败 staging 的 `failure.json` 原文入账，`incoming/BODYDATA.DAT` 与成功缓存保留。
4. **测试临时物**（0.24 GB）：pytest 缓存与自检样本。

## 保留

- 8 份已挖洞转储仍是完整失败现场（每份剩 0.43–0.50 GB 非零数据），5 份本就稀疏的转储未动，全部收据未改。
- `runtime/diagnostics` 剩余 46.3 GB 为 25 个互不相同的历史盘态，判为唯一状态，未删未压。
- 各 run 的 cpio payload（58.1 GB，99/100 摘要不同）、`runtime/tmp/readme-old-import-misi5xd3`（重导入前后备备份）、`validation/tmp`、`source`、`incoming`、`.git` 全部保留。
- 两个 VM 已退出但仍持租约的 `usb_control.py` 服务（pid 704033、973090）及其 `run-fiffdvzr`／`run-n6myt_bm` 目录未动；未发信号、未强关。

## 未执行

未关闭任何 VM、未发送进程信号、未操作 loop 设备或物理盘、未清理 `analysis/scratch/` 下的并行工作副本。`validation/tmp` 中活进程的 cwd 原样保留。
