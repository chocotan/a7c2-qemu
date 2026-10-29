# 原 SID 同步的零返回不保证文件写入

独立代理提出候选，main已重新读取原件核对指令与ELF重定位。该路径确实允许
“返回0但跳过保存”，但最新 owned VM 现场**没有走此跳过分支**：两套目标记录均存在且尺寸匹配，候选标记为1，实际到达保存调用。不能把静态可能路径当作已经确认的历史失败原因。
没有调用内部helper、修改内核数据或写文件来绕过此条件。

## 原件和定位

`runtime/analysis/menu-root/usr/kmod/backup.ko`，144976B，SHA256
`167715ebd8086b0751e95396ecc214c4d65ec54e11a9f2737a05664e03ad237b`。
这是ET_REL，不是有固定运行VA的ELF；下文KO地址为 `.text+offset`，文件偏移另加0x68。
原函数名取自符号表/重定位，不把附近不相干的反汇编标签当名称。

## 候选条件与真正的保存调用

`Backup_sync_subsystem@2ea0` 的 `2ed8` 有CALL26重定位至
`__backup_sync_subsystem_mp@2ca0`，后者持load/save mutex并在
`2cc0:ccf5ff97` 以 `(sid,0,0)` 调本地helper3f0。

helper先加载文件至独立缓冲，遍历相应子系统记录，并使用两个独立解析上下文：
Overwrite（被保存缓冲）和Temporary（来自Backup_bin_start的原存储）。

| .text偏移 | 原字节 | 作用 |
|---|---|---|
| 478 | bf0f0f29 | 局部 `[x29+78]` 初始化0 |
| 548 | 00000094 | CALL26→Overwrite_Data_SearchId |
| 554 | 00000094 | CALL26→Temporary_Data_SearchId |
| 55c | 7f0200f1 | cmp x19,0 |
| 560 | 041840fa | ccmp x0,0,4,ne |
| 564 | 60feff54 | 任一记录为空跳过 |
| 56c | 00000094 | CALL26→Overwrite_Data_GetSize |
| 578 | 00000094 | CALL26→Temporary_Data_GetSize |
| 57c | 5f23206b | 比较两侧尺寸低16位 |
| 580 | 81fdff54 | 不同则跳过 |
| 588 | 21008052 | mov w1,1 |
| 58c | a17b00b9 | `[x29+78]=1`，在复制前置候选标记 |
| 5ac | 00000094 | CALL26→memcpy，复制匹配记录 |
| 5d0 | a07b40b9 | 读取候选标记 |
| 5d4 | 60010035 | 非零才跳600进入保存 |
| 5e0 | a07b40b9 | 未保存路径返回原标记0 |
| 610 | 00000094 | CALL26→backupfile_save_file(0,buffer,Backup_bin_size) |
| 614 | a07b00b9 | 保存返回码覆盖候选标记 |

另有 `6c8→Backup_bin_start`、`6d0→Backup_bin_size` 的ABS64重定位。
所以返回0既可能是保存函数成功，也可能是没有任何匹配保存候选而完全跳过该函数。
API读到128B、且与文件不同，不能单独证明上述两套解析上下文都找到同一ID和尺寸。
这里的候选标记也不是逐字节差异检测，不能把它命名成已证dirty位。

本次只核上述局部路径，不排除更早的bank选择、加载失败或实际文件路径差异。
原helper只处理其遍历得到的记录；不能通过直接把候选标记写1来“修复”。

## 用户库至KO的分派补核

原 `libbackup.so` 的 `Backup_sync_subsystem@2258` 将result初始化-1，SID截成u16，
以service003e014d、selector0xf、单个SID参数调 `backup_sync_msg@1a10`。
PLT1530的GOT13018重定位绑定该符号，不是内核函数的直接调用。

`backup_sync_msg` 通过原 `osal_valloc_msg_wait` 分配112B，把selector放消息+0、
参数数目放+8、单个SID放+0x20，然后经 `osal_snd_sync_msg` 同步发送。
仅传输返回0时，才把消息+4复制到外层结果槽；它自己的返回0不能取代结果槽证据。
PLT1570/15d0/15f0分别绑定分配、同步发送、释放函数。

KO `backup_osal_call_func@7aa8` 用 `selector+1` 索引半字跳表；selector0xf的entry16
指向 `7e78`，该段从消息+0x20读取SID低16位，在 `7e84` 通过CALL26调用
`Backup_sync_subsystem`，再把返回值存到消息+4。
不是仅凭见到同名API就认定分派：main已核跳表重定位、entry值215和目标
`7b1c+215*4=7e78`。

这闭合了当前请求的前端选择与回填，仍不能替代候选记录/路径的实际观测。

## 下一项最小观测

在owned VM中读取KO加载的.text基址和原件身份，在目标SID同步期间只读观测：
记录ID为0051004a时，`55c` 前的overwrite/temporary指针、`57c` 前的尺寸，以及
`5d0` 的 `[x29+78]`。若未找到候选，则查各bank解析上下文；若已经置1，则沿
实际保存目标和原返回码继续。不以保存到另一bank猜测替代现场，已有完整双bank文件已留证。

现有 `run-fy4bc6df` 证明文件未变，但没有这些内核局部值。此报告不是根因已定或保存通过。

## 已准备的只读观察候选

`scratch/backup-branch-observer/observer.py` 提供四个硬件断点的采样逻辑及错误/清理记录；代理已结束，未连接任何 socket 或启动 VM。main 完整复核候选与原 KO，并独立运行其 host 夹具 **13 tests passed**。

寄存器依据已另核：w23 在3fc取SID低16位，4a8左移16；w24在53c合成记录ID；55c的x19/x0是两套 SearchId 返回，57c的w26/低16位w0是尺寸。5d0读`[x29+78]`；610记录保存前参数，未知记录ID保持未知。CALL26 运行立即数由重定位改变，候选核 BL opcode 与604/608/60c安全原指令，不按静态零立即数误拒。

候选不提供自主墙钟中断和连接所有权判断，也不从无hit或到达save调用推出文件已提交。下一步须为新 owned 实验单独接入安全中断、清理和独立 QMP CPU恢复核验，再观察原 helper；这些动态步骤尚未完成。候选和main交接记录不等于已命中本次 no-op 路径，`save_verified` 与 `noop_branch_verified` 继续 false。

main 已另备 `scratch/backup-branch-observer/owned_gdb.py` 与 `run_smoke.py`：私有派生 kernel launcher 只给本次新 VM 增加 Unix GDB socket，不改变正式 queue-debug 门禁。GDB 进程由此 caller 创建，墙钟中断只发给它；清理要求自己的四个断点删除、detach 成功，再以独立 QMP 状态和串口事务确认 CPU 恢复。6 项 caller host 夹具通过，包括未确认 detach 不发 cont、恢复失败保留路径、错误不包装成功和保存事务内运行位置。

首次动态冒烟仅布点并取消，不调用任何 Backup sync API。它放在 ready 后无回复超时的保存事务中；清理不确定时保留 owned VM，避免父控制器启动计时器误清理目标。

### Owned GDB 接线冒烟：已实际通过

`run-ggxyk1ol` 读到原模块 `.text=0xffffff80004e9000`，guest 原 KO 摘要与固定样本一致；全部运行指令校验匹配。保存调用的运行 BL 字节 `1e190094` 与静态零立即数不同，按 opcode 校验正确通过。GDB 进入 armed 状态，主会话中断实际记录 SIGINT，删除四个自己的硬件断点并 detach；独立 QMP 和随后原串口事务确认 CPU 恢复。没有触发 sync，hits 为空是本轮预期范围，不解释为未进入保存分支的证据。

main 重核 `backup-module-identity.txt`、GDB 原日志、`backup-branch-smoke.json` 和正常关闭结果：errors/cleanup_errors为空、remaining_breakpoints=0、detached与cpu_resume/serial_after_resume均true、debugger_returncode=0。SD 原 Flush=0、owner恢复、整卡重算SHA `61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727`、独立fsck=0。候选自己仍不宣称验证整个 KO，加载来源身份由 caller 的 guest 摘要另证。

### 原 SID51 同步的分支观察：已准备并运行，结果待核

`scratch/backup-branch-observer/run_checkpoint.py --smoke-run .../run-ggxyk1ol` 复用已过的 owned 清理路径。只通过原 helper 调公开 `Backup_sync_subsystem(0x51)`，不写候选标记或原业务字段；保留 `Backup_save=1` 受控参数，继续不把它当全局闸门。

新私有 overlay 只提供现有 checkpoint helper 和其短调用脚本；基础镜像不改。观察结束先清断点/detach/确认 CPU 恢复，再将 helper 已导出的失败文件从保留 RAM 读回，核 guest FNV 与双 bank/目标记录。原 helper 若返回34也保留该失败，不因调试会话成功把配置保存标成成功。当前该动态观察已串行启动，尚未取得目标指针、尺寸、候选标记的最终结果，原 no-op 因果仍未下结论。

派生 launcher 的 AST/Bash 与失败导出原始字节匹配夹具已实际通过。首次准备测试因包装后缩进锚点未更新而拒绝，修正为正确的函数内层级后通过；没有因此启动错误 guest 或放宽代码匹配。

### 实际分支结果：run-k770yv_x 已排除本轮走 no-op

主会话独立读取完整观察 JSON 与原串口：192 个完整样本，低于256上限，没有截止或读错误；95次 SearchId、95次尺寸比较、一次候选检查和一次保存前调用。目标 `0051004a` 在55c两侧指针均非零，57c两侧尺寸均128；5d0候选标记原四字节 `01000000`，610参数为 `x0=0`、非空buffer、`x2=2390264`。这证明**本轮实际进入原保存路径**，不能继续把“SearchId为空/尺寸不同/候选未置位”当作该次原因。

原公开 API 返回0；helper没有输出原先的 `BACKUP_CHECKPOINT_MISMATCH`，而是输出 `BACKUP_CHECKPOINT_DONE rc=1` 后退出36。根据实际执行的 helper 控制流，它已通过 bank0结构/checksum、WriteComp=1、目标完整128B与API相同、第二次API读回一致，失败发生于随后完整文件导出。未取得完整文件，仍不提升成全部配置或跨VM持久化通过。

导出拒绝原因已定位：该旧 helper 只接受独立 `memrsv=0x00400000@0x41e600000:uc`，本次正式live命令行实际为合并 `memrsv=0x00900000@0x41e100000:uc`。同一个4MiB窗口在后者内，生产 `sd-window-export.c` 已支持两种精确标记；旧 helper 在映射前即拒绝，既未覆盖窗口也未取得新文件证据。修正只让实验helper按相同token边界支持这两个已核保留布局，重复/缺失/前后缀污染仍拒绝。ASan/UBSan保留区夹具及原布局parser2项、成功/失败导出模式匹配夹具1项均通过。

GDB清理、detach、QMP与串口恢复均通过；原后续SD正常保存退出。现场有限结果另存 `main-checkpoint-branch-review.json`，原observer的 `save_verified`/`noop_branch_verified` 仍false，未篡改。下一轮只补完整文件经guest摘要/QMP、双bank解析及目标记录核验；不再重复寻找已排除的本轮空候选解释。旧standalone失败与当前live结果的环境差异尚需另查，不能把当前成功路径追溯改写旧run。

### 完整文件读回：run-tgx4h4o3 的 SID51 有限保存已证

修正实验导出保留区识别后，原 helper 实际输出 `BACKUP_CHECKPOINT_EXPORTED ... fnv1a64=a61da19cdadef6b5`、`BACKUP_CHECKPOINT_DONE rc=0`，外层串口事务也为0。经同一保留RAM/QMP导出的完整2390264B文件，main独立FNV匹配，SHA256为 `68c6c23677a52849391e27e4cef2fb15c23d5c234fc6b9d9bda60fa7f174170b`，与公开seed摘要不同。

两个bank均由原BackupFile解析并校验checksum：bank0大小968981，bank1从970752起、大小1419512。bank0目标128B记录 SHA `ebe21a8d3986f1f5fdc13cc1444e511580b831b56a4f991d2da65d429806f339`，前六word为 `(0,2,1,1,0,1)`，与原seed-power-on经原API设置的值相同；bank1仍是原全零启动记录。这支持本轮有限SID51文件提交成功，不支持所有AP/CP设置或跨VM恢复通过。

字段宽度更正：BackupFile把头部+8称为u32 `writeComp`，本次实际为 `0x00000101`（257），另一bank为`0x00000100`（256）；旧C helper检查的是低字节1。最初外层Python把**整个u32必须等于1**作为成功条件，错误地留下 `save_verified=false`，现已按原C有限条件修正未来验证并保留u32/低字节两个值，不抹掉旧结果。main另存 `main-file-checkpoint-review.json` 为限定保存通过，原observer结果仍不回填。不能猜其高字节的全局语义。

主会话完整重核后已启动下一VM恢复对照：只使用这份validated文件派生替换两份seed，禁用seed-power-on，在原相机app启动前由原 `Backup_nread` 对完整128B读回；之后核guest完整文件SHA及正常SD退出。派生Python/Bash/原始marker匹配的host夹具通过。该恢复动态结果尚待核，`configuration_persistence_verified` 继续false。

### 第一次恢复：原记录匹配，较晚整文件校验失败

`run-75e1hrvw` 在原应用启动前实际输出 `BACKUP_RESTORE_MATCH ... bytes=128 fnv64=44053e8048d74457`、restore RC=0；main核该FNV与前轮完整目标记录一致，两个seed overlay均为已验证文件SHA，私有launcher确实没有`--seed-power-on`。这已证明有限原记录能在新VM经原driver读回，没有由powerseed重新写同值。

但原验证器把“原应用启动后的整文件SHA”与恢复输入做强制全等，读到 `1d29af0179cf27f2df5aa5e6813d777d8c927e62d3ff4d7426a238b1ec73f08c` 而失败。现场没有启动前整文件SHA，所以不把这一轮总体改为通过；另存 `main-first-restore-review.json` 保留有限回读true、整体false。启动期间具体writer尚未观测，不能凭摘要变化猜是哪项原设置提交，也不能据此说恢复源不正确。

修正后的对照把整文件openssl摘要与原getter回读放在同一原应用启动前脚本内；较晚SHA仍必须实际读到，但单独记录是否变化。它不跳过源身份、目标128B比较或原API检查，只把时间阶段对齐。相应派生AST/Bash/精确原始marker夹具通过，第二次恢复已单独串行启动；完整配置和UI重初始化仍不标通过。

### 第二次恢复：有限原记录保存与新VM恢复闭合

`run-qdp4fiqt` 已实际通过：禁用powerseed，在app启动前原getter完整128B读回FNV `44053e8048d74457`，同阶段原 `/setting/Backup.bin` openssl SHA与保存文件 `68c6c23677a52849391e27e4cef2fb15c23d5c234fc6b9d9bda60fa7f174170b` 完全一致。main直接核console里的两个原始marker及两个seed的overlay清单。后续原app启动后文件又变为 `1d29af0179cf27f2df5aa5e6813d777d8c927e62d3ff4d7426a238b1ec73f08c`，该变化如实另记，未假定具体writer。

恢复VM正常退出，原SD Flush/恢复成功；main独立整卡摘要与export相同、fsck=0。有限“原公开SID51提交→原文件完整导出→新VM加载→不依赖powerseed的原API读回”已闭合，不再称该有限原提交接口完全不可用。旧失败、首次恢复整体false和两个bank差异继续保留。

成果内独立标准库复核器已执行通过：

```bash
python3 report/config-checkpoint/verify.py \
  --saved-run runtime/analysis/menu-runs/run-tgx4h4o3 \
  --restored-run runtime/analysis/menu-runs/run-qdp4fiqt
```

它核完整文件、双bank/checksum/目标记录、原导出FNV、公开同步与helper返回、pre-app文件SHA/原API读回/两份seed身份，输出的通过范围仅SID51启动记录。`configuration_persistence_verified`、`all_settings_verified`、`capture_verified`仍false。下一项实际用户设置是通过原UI更改语言/日期并验SID02cf，与这项原提交机制分开追踪。
