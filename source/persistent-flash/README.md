# 可复现的持久虚拟闪存组件

这里是产品运行需要的有限组件，不是另一套模拟器或内核源码仓库。

- `flash-core.c/.h` 和 `flash-qemu.c` 实现一块普通文件后端的虚拟闪存。父进程必须持有排他租约并传入同一文件描述符，设备核对 inode、device、容量与几何；拒绝物理块设备。
- `stage.py` 在产品固定 QEMU 补丁和 PCI stage 后加入设备。默认不实例化；只有精确 `persistent-flash-cold-v1` profile 和父进程 FD/dev/ino 才启用。产品 MMIO 基址为 `0x0b010000`，避开 USB 网络控制器的 `0x0b000000..0x0b004000`；guest 模块显式传入相同基址。
- `sony_persistent_flash.c` 是可读的 guest 块驱动，包含实际大 bio 拆分。`sony_persistent_flash.mod.c` 保存原 4.9.337-scel+ 模块描述。
- `abi/` 是编译该模块实际需要的406个公开内核依赖头，包含原配置与两个强制预包含头，总资产约2.4MiB。来源为 Sony 公开 Linux 4.9.337 内核；保留各文件版权和许可证，GPL全文在 `COPYING`。不需要另外下载或复制完整内核树。
- `abi-manifest.json` 绑定全部必要源文件的长度、SHA和相对编译命令。编译器内置标准头由已安装的 AArch64 GCC 查询，不随项目复制。

重建模块使用普通主机依赖 AArch64 GCC/binutils 和 Python pyelftools：

```bash
python3 source/persistent-flash/build.py \
  --source source/persistent-flash \
  --output runtime/analysis/persistent-flash-module/build-local
```

输出目录必须是新目录。构建检查 AArch64 ET_REL、原 vermagic、768B/64字节对齐的模块布局和39个原内核符号；编译通过不等于原guest加载通过。只以产品内部源资产重建的候选初版与已验驱动相比，除build-id外运行ALLOC区段和103项语义重定位完全一致；后续按原 Linux brd 语义补齐写前/读后 `flush_dcache_page`，预期符号明确新增这一原内核导出，不再将新版本称为初版字节一致。原guest组件证据另行保存。

`tools/check-persistent-native.py` 用本产品BODYDATA导入的原内核、模块与QEMU，在独立4MiB虚拟盘做实际1MiB写入/读回、原guest SHA、主机整盘比对和正常QMP退出。它是短组件验收，不是原AP冷启动、完整相机容量、Sony物理eMMC、完整固件更新或拍摄写卡的验收。

这组代码随产品构建维护，未接入或未通过的启动/迁移能力不能因设备被编入而标为完成。原始固件、设备私有设置、虚拟盘和生成的模块/QEMU二进制不随源码发布。

正常持久关闭使用自有模块的 `quiesce` 参数，调用原内核 `freeze_bdev`/`thaw_bdev` 同步并冻结全部19个分区，保存block-device/superblock引用。失败按原接口逆序解冻；实际state/count必须读回为1/19。文件系统冻结保留打开句柄，不冒称只读重挂或原相机关机。`test_freeze.py` 用生产C函数核正常、幂等、失败回滚及解冻失败时引用保留；原guest另按实际执行验收。
