# 官方启动流程与产品路径复核

2026-11-09补充：下表保留11月8日默认direct-bootin路径的原结论。新增的[显式原RAM0/init冷启动CLI](2026-11-09-original-cold-boot.md)已推进原init、p7挂载、pivot/chroot、原init2与原UI；它没有替换默认GTK入口，也不表示BootROM/CP/WBI/完整硬件上电已恢复。

本次只读复核使用本产品从用户的 ILCE-7CM2 2.01 ALLLANG BODYDATA 导入的原脚本，以及产品自身的启动代码。输入包 SHA-256 为 `eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31`。不依赖系统 dump、另一仓库或历史虚拟机。

结论：原 AP 的运行路径已有实际证据，产品启动与完整官方冷启动链仍存在下表差异，不能报告为完全一致。默认路线保留 `direct-bootin`；勾选内部持久盘只改变存储后端，不会自动变成原 bootloader/init/pivot 链。

| 阶段 | 官方输入中的行为 | 当前产品行为 | 判定 |
|---|---|---|---|
| 上电与内核 | 原 bootloader、硬件初始化、冷/热模式选择后启动内核 | QEMU 加载包内原内核及派生 initramfs | 完整原上电链未验证 |
| 原 `/sbin/init` | 导出 HOME/TOPRC/allocator/LT_ABORTREASON/WBSHD，加载 drv1，setup_nflash、setup_rootfs | 功能启动脚本补齐这些已知环境，显式虚拟块设备驱动 | 环境及设备功能适配；未执行全部原 init |
| 根文件系统 | `setup_rootfs` 挂载原 root，pivot_root、移动 proc/dev、chroot 后进入 init2 | 在生成的 initramfs 中运行；持久模式挂载真实 `/usr`、`/setting`、`/tmp`、`/log` | pivot/chroot/根卷仍有差异 |
| 内部容量与分区 | 包内 partinf.conf 指定分区容量 | 单个容器：用户区 1,954,545,664B，加两个 4MiB boot 区，合计 1,962,934,272B；19个包派生卷 | 几何及初始19片写后全量读回通过；无包镜像的卷明确生成为虚拟默认卷 |
| 挂载与配置 | init2/fstab 加载卷；`/tmp`、`/etc`、`/var` 共用小 FAT 卷 | 持久模式按原选项挂载，`/etc`、`/var` bind 到 `/tmp`；不在每次启动覆盖已有 Backup/settings | 原卷实际挂载有证据；全部配置语义未验证 |
| 临时加密库 | `WBSHD=/tmp_wbshd/shared.XXXXXX`，init2 为其挂 tmpfs | 补回相同环境及 tmpfs；此前缺失导致 loader 故障 | 修复后原 AP 已越过该故障；所有历史失败保留 |
| 原应用 | init2 普通分支运行原 bootin.elf | 显式启动原 bootin/im/appFw；有虚拟硬件及观察器适配 | 六个关键原 ELF 的 guest 全 SHA 门；菜单/LCD/输入另按实际记录 |
| 热恢复 | 原 WBI/RAM 保留及恢复路径 | 开发面板入口显示未接入 | 未完成 |
| USB | 原 CP/控制器/gadget/EP0、宿主枚举、模式选择、jiritsu 认证 | 已有软件模型和部分观察；宿主 vhci 条件与14槽真实消费仍阻塞 | 枚举/认证/root 未通过 |
| 关机 | 原系统停止写入并同步/卸载卷 | SD 真 flush、设置快照后，持久模式调用原 freeze_bdev 同步冻结19分区并读回状态；失败 thaw 恢复 | 属于隔离虚拟盘冻结快照，原相机关机链仍不同；核停止卷结构，保留FAT dirty原返回码，不用 QMP0 单独证明盘一致 |
| 系统更新与成片 | 原 updater 写入、重启；成像编码后原 Fsys 写卡 | 本轮用户明确暂缓 | deferred，不算通过 |

原脚本均可在导入后的 `runtime/analysis/menu-root/sbin/` 下复核；原 init2 第50行建立 WBSHD tmpfs，第64行启动 bootin。产品对照入口是 `runtime/analysis/qemu-menu-probe.py` 和 `persistent_storage.py`。文件身份以发布清单绑定。

原 ELF 内容一致不能证明所有硬件和启动语义一致；独立软件模型的成功也不证明 Sony 物理 ASIC 兼容。剩余阶段保持未完成，不通过替换原返回值、跳过异常页或生成独立媒体文件提升结论。
