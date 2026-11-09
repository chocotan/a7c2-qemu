# 原 AP 的 QEMU RAM 保存与恢复

后续已接入同一 GTK 窗口的实际 RAM 保存／恢复，见[窗口使用与原 AP 验收](2026-11-09-window-ram.md)。以下保留独立 CLI 的实现和当时证据。

## 范围和边界

该路径只证明同一持久虚拟盘上的 **QEMU RAM/设备状态 roundtrip**。它不是 Sony WBI 执行、物理热启动、完整 BootROM/loader/CP 启动，也不证明拍照或录像。对应字段始终分别记录：`sony_wbi_resume_executed`、`full_boot_verified`、`capture_verified`。

不连接真机或物理 SD，不使用 `exec:` 迁移 URI，不向活动 QEMU 附加 GDB，也不直接写 guest 内存伪造恢复状态。

## 产品入口

```sh
cd final/a7c2-qemu
```

也可用 `--new-instance` 从当前公开 BODYDATA 缓存创建独立虚拟盘。RAM 流可能达到数 GiB，应把输出放在空间充足的本项目 `runtime/diagnostics/` 或 `analysis/scratch/<任务>/`；不要使用主机 `/tmp`，它不是公开发布资产。

当前默认 QEMU 保留旧的非迁移准入。RAM 验收须先运行 `./build-qemu.sh --stage-only --sony-device --ram-state`，再把日志打印的 `STAGED_QEMU_BINARY` 以绝对路径传给本次入口：

```sh
A7C2_RAM_QEMU=/absolute/staged/build/qemu-system-aarch64 \
python3 -B tools/run-original-cold.py --instance /path/to/virtual-instance \
  --output /path/to/fresh-output --seconds 90 --ram-roundtrip
```

候选必须与同 stage 的 `persistent-flash-build.json`、`ram-state-source.json`、当前模型源和二进制摘要匹配；默认 proof 不得套到候选上。`source/ram-state/stage.py` 只包含 hwtimer、SPACC 和 UI input 三个精确输入的状态迁移，不是完整机器迁移审计。

## 实际顺序

1. 原 `original-init-v1` 冷启动，完成原 AP 的 MENU→拍摄 LCD 往返和 19 卷持久存储冻结。
2. 通过 guest 串口读取 `boot_id` 与 `/proc/uptime`，保存源 LCD。
3. QMP `stop` 后校验同一磁盘 inode/长度/SHA-256；`getfd` 通过 `SCM_RIGHTS` 传递本地 socket，QEMU 以 `fd:` URI 写出迁移流。
4. 只有迁移 `completed`、源为 `postmigrate`、QEVM 结构和完整流摘要有效时才生成保存回执。
5. 源只执行一次普通 QMP `quit` 并验证返回码。目标以同一持久盘、同一 QEMU/内核/RAM0 摘要和 `-S -incoming defer` 启动。
6. 目标加载前先核对回执、流、磁盘和运行资产；QEMU 消费迁移流后必须为 `paused`，再执行 `cont`。
7. 恢复后必须满足：相同 `boot_id`、guest uptime 未回退、新 LCD 有真实内容、目标控制台没有重新执行冷启动、原 MENU 产生新帧并能返回拍摄界面。磁盘仍须与保存时逐字节一致。

任一阶段失败都保留源/目标输出；不以冷启动代替恢复，不把保存成功写成恢复成功。

## 实现与主机检查

- `runtime/analysis/original_ram_restore.py`：有界 fd 迁移、QEVM/摘要检查、同盘绑定、guest 身份和原 LCD/MENU 验证。
- `tools/run-original-cold.py`：复用既有原冷启动、持久盘租约、正常保存与 QMP 退出链，增加 `--ram-roundtrip`。
- `runtime/analysis/qemu-kernel-probe.sh`：只有显式原冷启动、GTK live、无 USB 设备/宿主 SD 且观察超时为 0 时才允许 `-S -incoming defer`。
- `runtime/analysis/test_original_ram_restore.py`：主机 socket 确实读写 QEVM 数据、guest 身份解析、流/盘/二进制绑定和源失败不启动目标。

首轮两个测试夹具失败已保留：dup socket 继承非阻塞标志，以及 `runpy` 补丁未写入函数 globals。修正夹具后，RAM/原冷启动集中检查为 **46 passed**；公开模型清单调用方为 **28 passed**。加入显式 retained-stage 检查后集中结果为 **47 passed**。这些是组件检查，不是原 VM 恢复验收。

## 实际 v1 失败与修复

v1 源 AP 已实际启动并完成 MENU/LCD 与存储冻结，但 QEMU 返回 `pre-save failed: sony-persistent-flash`，原始 stderr 为 `retained-state is disabled`。492,168,892 B 的不完整流（SHA-256 `8e0684426a4a5f7060050a6497a6d2d60822b894443c461d587ad192354341d6`）保留且未交给目标；源正常 QMP quit/rc0，目标未启动。

原因是当前 stage 未设置设备已有的 `retained-state` 属性。修复只在显式 RAM 会话传 `QEMU_A7PF_RETAINED_STATE=1`，普通启动仍为 false。独立候选 `454e6a1d6ddf3131cd01d619d510131bcbb531770cd2e6e033b2095eaf98e2a9` 由完整 `build-qemu.sh --stage-only --sony-device` 构建并通过其构建期可执行检查；默认 QEMU 仍为 `b36998138a65b1bd2645ca24bf0dde0c0801d868d1291ec6f9e83ff707d64bad`。候选构建不冒充原 AP 恢复成功，后续实际结果另记。

v3 已实际完成源保存（491,139,793 B，SHA-256 `3d6a0f76a4dfad4d938fa136edf8583b35e863f8f2a6c114301efa533b911890`）、源正常退出、目标 incoming 和 `cont`，相同 boot_id 与初始原 LCD 也已读回。但 MENU 前后 PPM 完全相同，原 UI 没有产生新菜单帧，所以恢复验收仍失败；源和目标均正常 QMP quit/rc0。补入 hwtimer/SPACC/UI input 三项精确匹配的 VMState stage 后，v4 的实际保存/加载成功但 MENU 仍未产生新帧，因此该补丁不是充分修复，v3/v4 都不回填。

当前产品保存前会冻结 19 个内部卷；v3/v4 的目标此前未解冻。后续流程在 `cont` 后通过原模块 `quiesce=0` 读回 `0 0` 再验收，并单独记录恢复后的磁盘变化。

## v5 实际通过

v5 已完成真实源→目标 roundtrip：492,145,379 B 流 SHA-256 `bb962405a2009918cbcd4f1ff1b1730d5cbf78ee793ee9e1b119c287e8deea76`，源 `completed/postmigrate`，目标 incoming `completed/paused` 后实际 `cont/running`。源和目标均普通 QMP quit/rc0、无信号、owner group 退出。

目标 boot_id 保持 `ae3bf0a1-d09c-4e57-ab55-a08cbde15152`，uptime 27.95→28.11 未回退，未重复冷启动；恢复原 MENU 的 640×480 RGB 帧为 213 色，SHA-256 `4a12abe52fd1b40979fa5292cc2425fa10c49e4e2dcf2b6536c12d73a860ff61`，随后返回原拍摄帧。两次 MENU 都有原 App 的按下/释放边。保存盘 SHA `764bd4f9…`，恢复运行后的盘 SHA `ea33acb1…`；inode/容量不变，真实内容变化已单独记录。目标退出前再次冻结 19 卷。

两线程独立复核重新读取 RAM 流、回执、原 PNG、输入和磁盘，结果为 `PASS_INDEPENDENT_CONTENT_READBACK`。公开摘要为[验证回执](../../validation/ram-restore-20261109.json)。这不覆盖完整机器迁移审计，也不执行 Sony WBI 或拍摄。
