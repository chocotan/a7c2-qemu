# 启动流程 08 · 配置持久化：实例、Backup 与代数发布

配置把两次运行连起来：启动前从实例目录取恢复输入，运行中原固件改值，
OFF 时取快照、存 SD、发布新代，下次 ON 从该代启动。
对应索引第 2、9 步。**有限参数（语言/日期格式）恢复已闭合；
"下次启动跳过首设"仍未完成**——两件事别混。

变量见[索引](README.md)。本次只读源码与公开报告，没有重跑实验。

## 1. 实例目录与租约

`camera_ui.py::main` 经 `settings_instance.default_instance` 使用
`runtime/analysis/camera-instances/default` 作为跨进程的配置身份，
不用某次 `menu-runs/` 临时目录代替。

- 每次发布生成 `generation-<随机token>/`，内含 `record.json`
  （固件身份、状态、长度、SHA256）和完整 `backup.bin`；
  `current.json` 指向当前代。generation 是 CAS 令牌，不是递增序号。
- `VM.start` 先拿 `instance_lifecycle` 的 `run_lease()`
  （非阻塞独占 flock，忙就拒绝），整个运行和保存期间持有，
  进程组确认退出后才释放。
- 权限收紧：实例目录 `0700`、存储文件 `0600`、拒绝符号链接。

## 2. 启动时：恢复输入怎么进 guest

`VM._run` **先无条件清除**宿主继承的 `A7C2_SETTINGS_*` 环境变量
（旧变量曾让空实例选到无关来源），再只凭租约从 store 生成本次输入：

- 有 `backup` 代：`A7C2_SETTINGS_RESTORE=<代目录>/backup.bin`
  加校验过的 SHA256；
- 空实例（`new`）或逻辑墓碑（`reset`）：不提供恢复数据。

`stage_restore` 把这份 Backup 重新解析核验后，在本次 run 私有目录写
**两份同源** seed（`seed-backup.bin` 和 `seed-setting/Backup.bin`——
只替换一处会让加载输入和文件来源分离），生成 `settings-initramfs.cpio`，
并把两份 seed 的摘要加入实际 cpio 的内容核验。

完成标志：当前代、恢复清单、实际 cpio 内两份唯一 seed 同源同 SHA——
不只是"环境变量里出现了一个路径"。

## 3. 运行中：内存值和文件值分开记

有限验收对象两个参数：

| 参数 | 属性 ID | SID/尺寸 | 公开 seed |
| --- | --- | --- | --- |
| 语言 | `0x02cf0401` | `0x02cf`，1B | 1 |
| 日期格式 | `0x02cf0403` | `0x02cf`，1B | 3 |

真实 GUI 选简中/月-日-年，以原 LCD 高亮加原 API 现场值 `25/2` 确定，
不靠菜单序号猜。API 当前值和文件记录可以暂时不同（API 已 `25/2`、
文件还 `25/3` 是合法的中间态）。

踩过的坑：旧实验曾要求"两项都必须与文件不同"才同步，误拒了合法状态。
现在 `save` 模式只要求至少一项不同；正常 OFF 用的 `snapshot`
允许值未变——两者成功条件不同，不为让实验变绿而删 no-op 保护。

## 4. 同步闸门与完整文件校验

同步调公开的 `Backup_sync_subsystem(0x02cf)`。但**返回 0 不等于保存**：

- `Backup_save=1` 不是全局保存开关；单改它的对照没有提交目标记录。
- 原 helper 比较 Overwrite/Temporary 两套记录，都找到且尺寸匹配才置候选；
  没有候选也返回 0。候选非零才进 `backupfile_save_file`。
- 到达保存调用也不等于完整文件已导出。

完整文件校验：`2390264B`、双 bank（bank0 从 0 起 968981B、
bank1 从 970752 起 1419512B）、各 bank checksum、目标字节、二次 API 稳定。
导出经保留 RAM 窗口（`0x41e600000` 起 4 MiB），guest FNV + guest OpenSSL
独立 SHA + host 全文件 SHA 三通道对齐。

踩过的坑：头部 WriteComp 实见 `0x101/0x100`，旧外层曾要求整个 u32 等于 1，
留下整体 false；现在只记录不猜高位语义。旧 helper 不认识合并 memrsv 布局
而在导出前拒绝——导出失败不能算成原保存失败。

## 5. OFF：snapshot → SD → CAS 发布

`export_with_settings` 串行执行：**先配置 checkpoint，再 SD 导出**
（两者共用保留 RAM 窗口，顺序反了会取到另一事务的数据）。
SD 成功后 `publish_snapshot` 走 CAS：重新 load 当前代、比较
`expected_generation`，旧提交不能覆盖新代；写新代 → 逐项读回 fsync →
原子替换 `current.json` → fsync 目录。

注意 `PublicationUncertain`：指针替换成功但目录 fsync 失败。
报失败并保留 VM，不盲重试，也不宣称旧代仍 current——下次必须重新 load 核对。

全部成功才更新 `settings_generation`、退出 VM、释放租约。
任何一步失败：恢复 running/faulted、保留 VM。
历史那次 SIGTERM 中断导出的失败保留在案，信号来源仍未知。

```bash
# 执行目录：$PKG；只读查看保存事务、CAS 和不确定发布处理
cd "$PKG"
rg -n 'PublicationUncertain|generation|fsync|reset' runtime/analysis/setting_store.py
rg -n 'snapshot|restore|lease' runtime/analysis/settings_instance.py
```

## 6. 下次启动：新进程、新 VM 里回读

验收分阶段：pre-app 核实际 cpio 两份 seed 唯一同源、完整文件 SHA、
原 getter 回读；post-app 的变化另记（原应用启动期间合法提交别的内容，
不要求整文件永远等于源）。

已闭合的证据链：

- SID51 的 128B 启动记录在新 VM 禁用 powerseed 后仍由原 `Backup_nread` 读回；
- 语言/日期从真实 GUI 的 `25/2` 文件恢复，post-app 仍读回 `25/2`；
- 本包完成过**整个 GTK 进程关闭后**新 GTK 从同实例代启动、
  原 API/file 仍为 `25/2` 的跨进程回读。

踩过的坑：post-app 全文件 SHA 不同不能直接当恢复失败（要分 pre/post 阶段）；
第二 GTK 截图过早只证明机身窗，不算原页面视觉复验；
默认 `1/3` 的往返不能替代真实改值证据。

**"跳过首设"是独立验收项，目前未通过。** Backup 里相关标志
（`0x02cf0014`、`0x01070140`）在 seed 和保存文件中已是 01，
既不能倒推"字节没保存"，也不能直接写 1 跳页；模型日期状态、
force 位、特殊启动分支是另一编号域，尚未闭合（见 first-setup-frontier）。

## 7. 逻辑重置

"销毁并重新初始化"按钮：仅在实例已有保存代、VM 已停止且清理完成时可用；
确认框说明保留虚拟 SD、历史代和运行资料。后端 `reset_configuration`
重新走一遍租约和 CAS 防线（不是只看按钮禁用），发布 `state='reset'` 的
逻辑墓碑，不删除旧代。成功后下次启动从首设开始。

"销毁"是逻辑重置，不是数据安全擦除。

## 证据入口

- [no-op、实际保存分支与双 bank](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/backup-noop-sync-contract.md)
- [真实菜单保存/恢复与实例接线](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/user-settings-progress.md)
- [CAS、权限和不确定发布合同](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/setting-store-contract.md)
- [首设判据的未完成边界](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/first-setup-frontier.md)
- [本包独立补验及其视觉局限](../../validation/README.md)

## 如果你在做别的机型

双 bank、SID、属性格式要重新逆向，偏移和 WriteComp 数值不能套用。
可复用的是验证链：改值 → 提交 → 内容校验 → 不可变代 → 新进程原 getter 回读。
快照、恢复、重置、SD 保存是四个不同事务，每个失败点的保留行为都要写明；
首设是否跳过由原启动条件和实际页面另验。
