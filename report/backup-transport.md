# Native Backup 传输：独立 PCI 内存与完整长度 DMA

2026-10-25 接续 [启动交接](../HANDOFF-2026-10-25-BACKUP-STARTUP.md)。本项推进 native 拍照录像写目录 SD 的启动依赖，**尚无原固件 JPEG/MP4**。新增结果是隔离 QEMU 中的真实数据搬运与中断，不是 CP 固件执行、Backup 同步或拍摄验收。

## 已完成的数据边界

原 `backup.ko` 的 `.text+0x7054..0x7060` 指定 controller0、channel4、read方向；`.text+0x70bc` 提交 PCI→AP，公开第二记录长 `0x15a8f8`（1,419,512）字节。`cp3006-start/verify_ap_cp_backup.py` 已加入原字节核验并执行通过。

新增 `QEMU_SONY_BACKUP_TEST=1` 默认关闭，必须同时选择已有 PCIe TEST peer。它只添加：

- PCI 地址域 `0x404000000` 的2MiB固定窗口，指向已有16MiB peer RAM 的开头。
- 同一个 PCI AddressSpace 的 ATU；寄存器映射优先级2，高于 PHY DBI 的1，保留 CFG 窗口更高优先级。
- 该 profile 的 eDMA预算2MiB，满足整笔Backup长度；其它profile仍为1MiB。

AP本地 `0x404000000` 仍是独立 `sysmem`，不能与PCI同值地址合并。此固定窗口是**明确的虚拟板级译码，独立于原TEST BAR的command/bridge开关**，不声称复原NOR/CP硬件别名。2MiB窗口只覆盖primary合同，不声称承载两条完整BK4或完成CP启动。

QEMU候选SHA256：`99b9882a072d25a89cfaa534b2ad97106552f84e25c601059782fdf34d6c7a80`。

| 检查 | 实测结果 |
|---|---|
| 原长度、controller0/channel4 | PCI `0x404000000` → AP `0x4040ed000`，全1,419,512B匹配 |
| 数据域隔离 | AP root完整保留，源完整保留，目标前后guard保留 |
| ATU与DMA同后端 | 通过ATU改写1MiB之后的字节，随后的DMA实际读到改动 |
| 真实中断 | masked不进GIC；unmask产生IRQ198；W1C后撤销 |
| 默认关闭 | 无固定高窗口/Backup ATU，预算仍1MiB；高源访问abort且AP不变 |
| 错误高地址 | 不截断、不别名到有效低地址，只有abort |
| 末尾读取失败 | 保留此前已搬运的数据，不生成done，只有abort |
| ATU停用 | aperture写入不再改变peer |
| 旧BAR/DBI回归 | 配置/桥窗口/command gating、双向数据、RO锁恢复全部通过 |

测试使用非对称合成数据；有效payload摘要为 `3ca7b0cf10140192a775aa2e4ce507425be7c34e8576f911a5d9d00075bff089`。没有加载公开seed到CP后端，没有运行原kernel、AppFw或自然快门。

证据已读回比对SHA后归档到：

- `runtime/analysis/scratch/backup-transport-20261025/backup-pci-qtest-inupbu4g/`
- `runtime/analysis/scratch/backup-transport-20261025/pcie-peer-qtest-zim6jiv4/`

各目录含 `result.json` 和原始 `qemu.log`。两个qtest实例均正常QMP退出，不持有目录SD。

## 构建与复现

`virtual-pcidma/stage_hardware.py` 将既有DMA/ATU硬件源码和板级片段集中到一个构建步骤，诊断构建器及 `build-qemu.sh` 共用。输入的原源码和DMA patch按既有摘要检查，重复应用或未知源码拒绝；收据记录模型、片段、最终virt/Meson及binary摘要。三项staging回归通过，含native的真实patch应用分支。

native组合保留原GTK/SDL、USB、vvfat及qcow1构建选项。新增 `--stage-only` 保留构建检查及既有合成QEMU输入自检，只产出候选与收据，不安装、不启动相机固件，保护现有已经验收的目录SD基线。组合候选已完成构建，SHA256为 `d435865cfc7b279d749149d60eb83b48e72281fc520b677266695c8d75408581`。
原生合成输入自检、GTK可用性、libfdt符号检查通过；同一二进制分别通过上述完整Backup qtest与
256GB目录SD设备测试，后者验证已有文件读取、保护扇区拒绝、实际宿主写回、flush/clean commit及正常退出。
两者尚未在同一台原固件VM的启用硬件组合profile中运行。后续 `run-ypxwv89y` 已在新binary上
验收原固件首设及原Fsys元数据保存，见下一节；这是新的实测，不继承旧Fsys结论。
原生产二进制读回SHA仍为 `e23589c44386c19417551c982e394b7a4e779f8e68a72f2964b705aca1e96c0d`。
完整相对路径和未完成标志见 [组合验收收据](backup-transport-validation.json)。

从本成果根目录执行：

```bash
bash report/virtual-pcidma/hardware/verify.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider report/virtual-pcidma/test_stage_hardware.py
python3 -B report/virtual-pcidma/build_candidate.py
bash build-qemu.sh --stage-only
```

硬件测试显式接收上面构建输出的候选二进制路径：

```bash
python3 -B report/virtual-pcidma/test_backup_hardware.py "$QEMU_BINARY"
```

主机ASan/UBSan测试另外验证1MiB预算在任何读写前拒绝，显式2MiB预算实际搬运完整数据，以及错误高地址/末尾故障。这不替代上面的QEMU/GIC证据。

## 原固件启动自测：新候选通过，拍摄仍未验收

`run-ypxwv89y` 使用同一 `d435865c…` 组合候选、公开ALLLANG和新建256GB目录卡，新增
Backup/PCI硬件保持默认关闭；未启用CP3007/UDATE/touch，未按快门。本次验收是新binary的
原启动兼容性，不是启用Backup服务后的恢复实验。

GTK测试新增 `--candidate-build`，在目录USB profile组装后选择候选；发出输入前按运行清单
核实际二进制SHA，拒绝收据不符、诊断构建或运行了其它binary。候选启动参数与既有自然启动
观测回归共 **11项 + 13子测试通过**。生产程序SHA仍为 `e23589c…`，未替换。

主会话核对17份640×480原LCD截图摘要并逐页审阅：简体中文选择、可访问性、隐私声明、
机内设置、区域/日期、温度提示、教程、数据库准备、拍摄HUD和稳定中文菜单均有本次图像。
HUD显示 `9999 / J-FINE / 14M / AF-S / MECH`，中央取景仍黑，不算CP liveview或拍摄成功。

原Fsys和宿主证据：

- `console.log:3140` 原Mount返回0；数据库首次Open在3165返回 `0x80000051`，11714再次打开成功，11814写入9,670,656B；保留这条早期失败而不覆盖。
- XML在11823打开成功，11832写入406B；11885出现实际目录commit完成。
- 最终退出导出序列 `1366294747401982`：12340原FlushVolume返回0，12354块设备fsync返回0，12383 owner恢复。
- GTK保留的先前导出序列是 `1366293903591120`，同样成功；两次文件清单/摘要完全相同。
- 宿主全树实际只有 `INPUT.BIN` 69B、`private/database/database.bin` 9,670,656B、`private/m4root/mediapro.xml` 406B，全部重新读回摘要与最终导出一致，没有JPEG/MP4。
- 最终commit为 `pending=false/closed_pending=false/transitions=22`。后台任务退出0；主会话补查owner PID/进程组均不存在，无QEMU进程，主锁和目录租约锁可独占取得。未发SIGKILL。

原 `gtk-input-proof.json` 的 `ok=false/images_require_main_session_review=true` 保持不变；
单独的 `startup-evaluation.json` 记录主会话逐图、内容、退出验收，避免把自动化完成抬成完整相机成功。
`startup-cleanup-assessment.json` 记录进程/租约补证。上述文件位于 `runtime/analysis/menu-runs/run-ypxwv89y/`。

启动settle后、GTK导航前的被动采样得到 `EE_STATUS=0/BACKUP_SYNC_PENDING=0`；这不是最终HUD时刻
的读回，也不是已解除完整服务profile的Backup屏障。未测最终EE、原Backup DMA、自然快门或编码。
启用硬件与原服务后的同VM联合启动仍为下一步。

复现（从本成果根目录；目录参数必须是单独新建的测试目录）：

```bash
python3 -B runtime/analysis/check-natural-gtk-input.py --new-ui --firstboot \
  --simplified-chinese --export-sd --host-sd-dir "$TEST_DIRECTORY" \
  --candidate-build "$COMBINED_BUILD_DIRECTORY"
```

## 下一步的原服务合同

原消息/初始内容证据仍以 [Backup合同](backup-sync-cp-contract.md) 为准。新的只读调查补全了消息容量边界：

1. AP请求只有40B。原OSAL高目标分配路径对40B分配128B总块，body位于块+64；请求末尾有cookie，**不是可读4096B页面**。`osal_msg_size`只报告请求长度。
2. CP接收侧固定申请/复制4096B，不能直接照搬到AP public-sender的40B对象。虚拟适配必须另分配4096B回复、初始化填充，仅复制40B已知数据；零填充是显式模型策略，原传输尾部含义尚未验证。
3. stage3写primary+9=1、归一化回复stage为1，锁定256个bucket，cache clean/invalidate；虚拟整体冻结只能在所有模型写者遵守它时代表这个子集，不能宣称真实CP mutex已执行。stage0解锁，不清+9、不重算checksum，动态reply queue可与stage3不同。
4. 回复发送成功前不能释放原请求；失败由原caller回收。发送成功后消费原请求，free失败则保留且返回0，避免double-free。保留不确定的数据/冻结状态，不伪造干净完成。
5. 必须扩展已有UDATE kernel public sender，保持唯一owner；普通PCI初始化、真实连接、seed来源/readback、同一PCI数据后端和资源生命周期需要一起验收。禁止加载会写测试pattern覆盖该peer的诊断传输模块。
6. 原AP路径即使首次reply或DMA报错也会发解锁，最后只返回第二reply状态。因此stage0成功不能作为DMA、Backup或拍摄成功证据。

这些尚未接入运行模块。接下来验证组合构建/DTB与严格内核服务，再用原Backup提交完成数据、callback和保存，最后测原group0/transition/EE/自然快门及MPR/Fsys。硬件NOR高低地址关系仍未知，但不再扩展为native运行模型必须先完成的整套bootloader仿真。
