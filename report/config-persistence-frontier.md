# 配置持久化：独立调查与原代码核验边界

当前默认native启动路径不保留相机配置：/setting为tmpfs，启动时复制公开seed，
backup.ko以Backup_load=1、Backup_save=0加载。现停止路径只导出SD。
这与已通过的SD持久化是两回事；配置持久化与UI重初始化尚未实现或验收。

最新原相机 live 观察 `run-k770yv_x` 已确认 SID51 的目标两侧记录均存在、尺寸128/128、候选标记1并到达真实保存调用；本轮不走静态 no-op 跳过路径。修正实验导出器对正式合并保留区的精确token检查后，`run-tgx4h4o3` 已取得完整2390264B文件、guest FNV与QMP读回一致、双bank checksum有效和目标128B API值匹配。文件SHA为 `68c6c23677a52849391e27e4cef2fb15c23d5c234fc6b9d9bda60fa7f174170b`；这闭合有限SID51启动记录提交。头部u32实际0x101，低字节1，未把整个字段误当1；初始外层误判保留并另存main有限review。跨新VM无powerseed恢复正在验证，尚不宣布全部设置持久化；旧standalone失败证据不改，环境差异不靠猜测定因。

下一轮真正用户设置的 ID 已按原 AP 的 ELF映射、PLT/GOT及现有伪代码独立定位：语言 `02cf0401`、日期格式 `02cf0403`，均1B、同SID02cf。详见 `config-parameter-contract/README.md` 和已实际通过的只读 verifier。后续只通过原菜单修改，再验原公开同步/文件/跨VM读回，不从SID51启动记录推导整个SID02cf或所有配置成功。

第一次新VM恢复 `run-75e1hrvw` 已在禁powerseed条件下由原getter读回匹配的完整128B启动记录，但晚于app启动的整文件摘要已变化，原总体校验失败。main保留失败，不把该记录回读扩大成整文件或全部设置通过；新对照把getter与整文件摘要放到同一pre-app阶段，较晚变化单独记录。真实菜单两参数helper候选在独立scratch开发，未改生产或假写参数；GUI对照已准备通过真实简中页与日期格式页UP选择另一项，未见指定原页面则拒绝，不用setter补值。

修正阶段对齐后 `run-qdp4fiqt` 已通过完整pre-app文件SHA及原128B getter回读，且未执行powerseed，正常SD保存退出。标准库 `report/config-checkpoint/verify.py` 已实际运行通过：有限SID51的原提交/完整导出/新VM加载/API恢复闭合，整体配置持久化仍false。原用户设置的下一轮 `run_save.py` 已串行启动，需在真实语言/日期页面改变两值、原SID02cf同步、完整文件与API匹配后，再做其新VM恢复；不能套用SID51成功。

## 宿主实例生命周期：已实现的有限范围

`runtime/analysis/instance_lifecycle.py` 已直接维护于权威运行源码，复用原 `setting_store.py` 的私有目录/文件验证，提供稳定目录绑定、非阻塞运行/离线租约、一次性 token 和逻辑重置。原候选与 store 的独立复测为 67 passed；没有操作真实用户配置。

`menu_control.VM(instance=...)` 现在可选绑定已有 owned 0700 实例目录，启动工作线程前获取租约；默认未传实例的 UI 行为保持原 profile。工作线程清理 owned 进程后，确认其进程组也不存在才释放；终止失败或进程组仍在时保留 token 与 owner，`close()` 只有在重试清理确认后才释放。`reset_instance(expected_generation, confirmed=True)` 只允许无活线程、无 owned 进程、无残留租约及清理错误的实例，委托 store 发布 CAS reset 墓碑，不删历史、SD 或外部源。

集成的生命周期/VM/store/控制组合 **99 tests passed**。兼容 GTK、默认启动、快照和控制通道的首轮组合 47 passed、1 failed；失败来自旧裸 Mock 夹具未设置 `_menu_serial_desynchronized=False` 而触发串口保护，已只修夹具，相关控制通道/VM/快照组合复测 **31 passed / 2 subtests passed**。相机 VM 没有因这些 host 测试被启动或清理；测试使用合成 Backup 与进程夹具。

这个接线仍**不提供原 guest Backup 保存/恢复**。最终 GTK 尚未绑定稳定实例、没有完成配置保存事务或重初始化 UI；原提交条件仍见后文。不能把 host reset 墓碑当作已恢复相机配置。store 按路径重开目录的接口也不提供抵御恶意同 UID 并发祖先替换的原子保证；当前保证针对遵守同一路径/租约的协作控制器。

### 原相机 VM 的生命周期实证

`run-zer0zfba` 使用权威 `VM(instance=...)` 可选路径实际启动原相机，运行中同一实例的另一个控制器取锁被拒绝，host 重置也被拒绝；正常 SD 保存和 owned 进程组清理后，另一控制器成功重新取锁。原检查结果为 `live_exclusion_verified=true`、`live_reset_rejected=true`、`stopped_reacquisition_verified=true`，终态 exited。

main 另读该 run 的 review、原导出结果和实际卡文件：32 段 guest/QMP 摘要一致，整卡 SHA `61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727` 与 export 一致，原 Flush=0、owner恢复、独立 fsck=0。该有限结果在 `instance-lifecycle-review.json`，并保持 `configuration_persistence_verified=false`、`guest_reset_verified=false`、`capture_verified=false`。

这完成的是宿主租约与真实 VM 退出清理接线。没有在这次实验修改并恢复相机菜单设置，也没有触发真正 guest 配置销毁，不扩成完整任务完成。

## 同题独立调查与主会话裁定

两位代理独立调查同一问题，均已结束。A报告在scratch/config-persist-a/REPORT.md；
B未保存承诺报告，主会话收取其最终结果并诚实保存于
scratch/config-persist-b/MAIN-HANDOFF.md。一致不替代原指令证明。

- 原保存路径名是模块参数默认值，不应称作不可变硬编码。
- strings中的vfs_write、writeCmp或锁名不能证明保存时序和持久性。
- 两份seed原件均为2390264B、SHA256
  3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47。
  因此load后再复制seed存在覆盖恢复文件的设计风险，但本轮没有观测不同内容。
- 不接受未经实现的host目录bind方案；guest不能直接访问host目录。
- 不接受“SD已传4MiB所以串口可传配置”的推断：SD数据经保留RAM/QMP，
  不是串口流；现有QMP路径也不能被泛化为不可用。
- 每次run的SETTING目录不是跨UI进程的稳定实例标识。恢复损坏文件时
  必须报错并保留旧证据，不能静默回seed冒充成功。

## 原Backup_sync_all的明确门槛

主会话独立核原backup.ko：144976B，SHA256
167715ebd8086b0751e95396ecc214c4d65ec54e11a9f2737a05664e03ad237b；
原libbackup.so：14232B，SHA256
6a3c5f6067620c00d790cbe520844acdbb721fa5d0e7433b00a227f922ab9d0d。

用户库Backup_sync_all在VA2294，52B窗口SHA256
5b4fad490d749df36548a82423e9cff344ae1fc864cb84afb2f29745c5176815。
其调用1530时携带命令003e014d，返回局部结果；尚不把该调用命名为
已闭合的完整ioctl传输合同。

KO的同名函数在.text+3010，272B窗口SHA256
6f24d1fedc17068c676efddae0e0da503ce03709c437266261e7b88f84f25db1。
根据原重定位，3044调用backupfile_lock_load_and_save，3070先调用
backup_get_cp_data(3)。只有返回0才在30e8设置参数1，并于30f0调用
backupfile_save；失败支路绕过文件保存，随后解锁并返回错误。
不能以空CP成功应答绕过，也不能宣称sync_all在当前有限CP下必然可用。

Backup_preserve与Backup_rewrite涉及已有文件加载、校验或保留副本；
它们不是仅凭名字即可采用的RAM提交接口。其用途与副作用尚需完整核实，
本轮没有调用它们或改任何配置参数。

## 实施和验收要求

先闭合原提交与一致性条件，再实现host稳定实例的校验导出和原子发布。
恢复必须发生在原driver加载前，且不得被后续seed-setting复制覆盖。
通过原固件改菜单参数后，跨新VM与新UI进程，用原API及UI双读确认。
未提交崩溃数据的恢复边界单列，不承诺零丢失。

最终唯一GTK提供销毁并重新初始化，须预览范围并确认；仅当前已停止、
租约安全的owned实例，默认保留虚拟SD，不删除原固件、共享缓存、
overwrite源、外部SD源或其他实例。没有实施任何销毁操作。

## 后续主会话核验：SID清单和保存参数语义更正

两位同题提交接口调查均已结束，未闭合完整helper合同。A仅完成符号调查，
提取脚本在命名冲突后没有重跑；B交付bank0合并和文件写路径原窗口，但
初报未更新，最终结果由main收取。两份均不能当作已实现配置保存。

main随后用仓库现有BackupFile只读解析固定公开seed并校验checksum：
bank0头长256B、SID项6B，声明819个SID槽位、37680属性槽位，124个
非空SID、29176个有效属性；dataOffset231264、dataSize737717、bank0
共968981B。元数据清单和重现脚本保留于scratch/config-persist-main/。
存在性不是可写或已提交证明；不得盲遍历SID。实际有SID超过255，
也不能把锁表低8位索引误当作SID合法上界。

此前把Backup_save=0直接称为所有写回路径的闸门，证据不足，撤回该解释。
main核原KO的Backup_save符号重定位仅在.init.text+268和参数表；原init
19c..1b0分支只选择是否打印日志，然后回同一路径。当前没有证据证明
这个参数门控公开subsystem保存函数。/setting为tmpfs、启动重铺seed、
尚无host导出恢复仍是配置跨VM不保留的确定原因。

原低层写函数5d40只在vfs_write返回精确请求长度时成功，短写/错误返回
失败；它以101041/101241标志打开文件，包含O_SYNC。filp_close返回被忽略，
故仍不能扩展为所有文件系统故障和断电持久性均通过。

main已准备有限checkpoint实验候选：仅同步公开SID51/启动记录0051004a。
该公开seed记录128B、最初前六word均0，既有seed-power-on通过原API设置
mode/type等并读回。候选不新增Backup_write或裸写；先要求API当前值与
文件确有差异，再调用公开sync_subsystem(51)，核真实文件checksum、
WriteComp和完整128B、再次原API读回，并经原有保留RAM通道导出文件。
该候选准备时仅在scratch/backup-checkpoint，尚未原ABI构建或guest执行。
后续执行结果见下；它始终不代表全部AP/CP设置、原子多SID一致性或最终UI完成。

## 已发生的 checkpoint 失败与受控对照

首次实验 `experiment-ch94yqoj` / `run-37v8lcwr` 已经构建并执行，不能继续标成“未运行”。
原始串口给出：

```text
backup.ko: ** NO SAVE MODE **
BACKUP_CHECKPOINT_BEFORE sid=0x51 key=0x0051004a api_bytes=128 different_from_file=1
BACKUP_CHECKPOINT_SYNC sid=0x51 rc=0
```

helper 随后返回 34，即文件布局、WriteComp 或记录字节校验未通过；没有进入恢复 run。
旧 helper 把这三个原因合并为同一返回码，因此不能进一步猜是哪项错误。
`sync` 返回 0 不构成提交证据，该 run 是失败记录。

后续受控实验在同一候选上显式选择 `--backup-save 1`，并在返回 34 前打印布局有效性、
WriteComp、记录是否相等以及前六个 file/API word。它使用既有原 API 种下的公开启动记录，
不新增配置写入；只有真实文件与原 API 全字节一致、校验和通过、独立新 run 经原 API
回读一致才算该记录通过，不将该实验推广成所有设置保存。

该受控对照已在 `experiment-sokhigp0` / `run-g4c2soj1` 执行：串口确认实际
`insmod ... Backup_save=1`；同步返回0，后续结果为
`layout_valid=1 writecomp=0 record_equal=0`，仍以34失败。记录前六word的file值均0，
原API值为 `0,2,1,1,0,1`。因此“只改save=1即可保存”的方案不成立。
但当前检查只覆盖bank0，尚不能断言整个文件未变化或另一bank没有更新。

后续候选在失败返回前也把完整2390264B文件放入既有保留RAM窗口；host在原失败
事务结束后用QMP导出，核guest摘要，再分别解析两个BK bank的checksum、WriteComp和
目标记录。诊断不会把失败改判成功。候选的失败文件解析、摘要拒绝与C布局测试共3项通过；
真实双bank诊断结果待定。

完整留证对照已执行于 `experiment-pkom202g` / `run-fy4bc6df`，仍返回34：

| bank | 文件偏移 | 尺寸 | checksum | WriteComp | 目标记录匹配API |
|---|---:|---:|---|---:|---|
| 0 | 0 | 968981 | 有效 | 0 | 否 |
| 1 | 970752 | 1419512 | 有效 | 0 | 否 |

host导出文件与guest FNV一致，main重新计算2390264B完整文件SHA256为
`3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47`，恰为公开seed。
因此本次没有把API中的改动提交到该文件，不能再解释为只漏看另一个bank。
仍不排除真正提交需要其它原API、异步条件或保存到另一条路径；需要源码/调用链证据，
不重复相同参数试验，也不把固定返回成功或直接编辑文件作为修复。

后续独立调查提出一个无需文件写入即可返回0的分支，main已重新读取原KO和libbackup
核对指令、原重定位及selector跳表，详见 `backup-noop-sync-contract.md`。
只有overwrite/temporary记录都存在且尺寸匹配，helper才置保存候选标记；标记一直为0则
跳过 `backupfile_save_file` 并返回0。用户库service003e014d/selector0xf到KO
`Backup_sync_subsystem` 的实际分派与结果回填也已补核。
这解释API为什么可能成功无写，但未观测实际指针、尺寸或候选标记，不能认定当前run已命中该分支。
下一步应只读核这几个内核局部条件和实际目标路径，继续保留原失败结果。

## bk 命令语义：独立报告与 main 复核

`usr/bin/bk.elf`：18952B，SHA256
`97e9673e94ed7896f10bd0354a20ed2690d81f3ced14c0deb56a62a58ecba347`。
main 独立核对了真实分派表及 PLT/GOT 重定位绑定：

| 命令 | 分派表 VA → handler | 实际调用 |
|---|---|---|
| r | `414110 → 401f1c` | `4019ec → 400ff0@plt → GOT414080 → Backup_read` |
| g | `414230 → 401b34` | `401ae8 → 401060@plt → GOT4140b8 → Backup_get_attribute` |
| d/dr | `414210 → 401fb0` | `402060 → 400f00@plt → GOT414008 → Backup_reset` |
| d/ds | 同上 | `4020c4 → 401030@plt → GOT4140a0 → Backup_reset_subsystem` |
| d/da | 同上 | `402018 → 401080@plt → GOT4140c8 → Backup_reset_all` |

所以 `r` 是读取，不是 reset。`r0/g0` 后缀选择 interchip ChipID=0，而裸 r/g 走本地 MP；
`r0 0` 会跳过零 ID，不能用来证明实际读取；g 的零 ID 错误路径也不是正常探针。
工具主分派忽略 handler 返回值，故仍须核对实际输出 ID、长度与原始字节。
运行时应使用实际存在的 `/usr/bin/bk.elf`，不能假定 `/usr/bin/bk` 别名存在。

原来另写的 config-commit-probe 不能用 `VM.owned_process` 调串口：它是启动器 Popen，
不是 qemu-menu-probe 中持有 guest stdin 的 Popen。该脚本已在启动前阻断。
继续复用上述已有 checkpoint 候选，从真正 guest 串口事务中取证。
