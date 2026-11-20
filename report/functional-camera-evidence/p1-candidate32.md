# CP周期配置入口已接通，第三十二跑的启动与首设结果

本轮完成候选31独立审查、五文件集成、完整observer/CPIO/生产derive重建和第三十二跑（含一次采集修正重试）。两轮guest均实际接收`0x91170319`，提交`period=100 count=5 phase=0 release_rc=0`，随后原`sequence_boot::run`返回；原`sequence_boot.cpp:1985`未复现。重试结果为：原AP首设继续推进，未确认拍摄HUD。周期服务仍仅实现原回调的配置/释放前缀，真实CP计时器、回调和样本均未实现；没有整机启动或拍摄写卡通过结论。

## 范围、审查与实现

沿用委派的审查→集成→第三十二跑；没有再委派，没有真实设备访问、刷写或信号。使用ponytail最小完整修改与docs-generator（flavor=null），核对ida-reverse证据要求，但没有声称本轮启动IDA或执行原CP。skill引用的本地tool-index/precedent文件缺失；本轮利用已存在的原始字节窗口并直接与原件逐窗读回，未因缺辅助文档中断本地已授权工作。

[独立审查](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate31/main-independent-review-v1.md)无必修项，candidate31原样集成。AP`0x305e680 → 0x34cb3e8 → 0x3513a6c`发送4字节`64 80 05 00`至`0x91170319`，只检查send返回，不等待ACK。CP`0xaca980`注册该SID至`0xaca9db`；`0xaca9da`解码参数，`0xacaa4e`释放请求，之后才在`0xacaa56`安排周期任务。候选没有伪造该任务的完成或周期回调。DIG_LEVEL原路径未修改。

产品新增`runtime/analysis/cp-periodic-service.c/.h`与C自检；`menu-observe.c`增加精确SID与显式`MENU_CP_PERIODIC_SERVICE=virtual-config-v1`路由，`build-observers.sh`将新模块纳入owner object实际链接链。禁用及非目标保持原路径；启动/停止长度分别严格为4/0字节；解析后才释放，释放失败不提交配置；阻塞mutex保护配置与一次释放。日志始终明确`timer_started=0 original_cp_executed=0 samples=0 replies=0 camera_startup_verified=0`。

## 集成与宿主验证

[集成入口和恢复方法](../../../../scratch/a7c2-cp-periodic-integration-20261115/README.md)保存完整前像、源文件前后摘要、构建与恢复读回。原候选基线与当前产品一致才应用，未覆盖无关修改。CPIO仅`simulation/menu-observe.so`改变，成员集合与权限均不变。

| 资产 | SHA-256 / 结果 |
| --- | --- |
| preload | `f283fa05008a8683ac5bda7b69c21fe284b3b9af9809b4ae65a6a951e10e5440` |
| UDATE KO（未改内容） | `837342f6dd72361cee3e4dd1ffedbff1a7f4951e1f628defb37359c17a6334ec` |
| 基础CPIO | `00fd08500029bb2ec3da2e978a20a7d0d7fa86d3a8f7157b1a0fb261fafda821` |
| 实际派生CPIO | `a59cb874d55c56a2234a856906183406e6ad552d24bdb5d82daaea71b57ec373` |
| derivation | `14b79d178680145206125d55ad229d3a7455bc5a540f15a77609ed8a44d9245e` |
| binding目录 | `derive-prod-4758b35a9afc58fc` |
| QEMU | b369原接受构建；首跑`e89f`，重试`df07` |

候选原9命令均rc0，含严格警告、AArch64、ASan/UBSan、8192笔双线程与DIG_LEVEL回归。产品集成后周期服务与DIG_LEVEL重新编译运行通过；UDATE/BB当前入口9方法、94 subtests通过。第一轮复用脚本引用了不存在的`test_bb_0159.py`，导致未收集测试；原失败`product-regression.*`保留，修正入口后另存`product-regression-v2.*`与`complete-v2.json`，没有回填失败。

最终独立核收采用2工作线程、2检查组：部署/退出/原始证据读回，及空间/profile/恢复材料盘点；这不是两次真实拍摄验收。收据为[handoff-final.json](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate32/handoff-final.json)。

## 第三十二跑实际结果

两轮都是direct-bootin AP诊断路线，使用原App32输入，没有强制EE状态或跳过断言。没有执行Sony loader/WBI恢复或真实CP固件。guest preload、KO与1GiB RAM卡全SHA实际读回成功，部署身份与新binding一致。

| 验收点 | 首跑 | 唯一重试 |
| --- | --- | --- |
| 周期配置接收/释放 | 通过 | 通过（console:7899） |
| 原sequence_boot返回 | 通过 | 通过（console:8213） |
| 1985断言 | 未复现 | 未复现 |
| ENTER_REC_STILL | 0条 | 0条 |
| Imaging PIN/CONTROL/ADF commit | 0/0/0 | 0/0/0 |
| 其他断言（不同原行） | 0条 | 0条 |
| mailbox/broker | False/False | False/False |
| 原App32快门尝试 | False | False |
| JPEG/写卡/整机capture | 未验收 | 未验收 |

首跑driver rc2：第五张LCD导出时PCIe printk插进base64行，旧过滤器丢掉含有效数据的整行，gzip CRC失败。原`ui-5.transport.raw`与失败收据保持不变；只移除这条精确已知printk后，外层gzip CRC和原整帧FNV均通过，见`export-recovery.json`。该离线修正不是首跑业务通过。

重试仅改私有采集驱动：导出窗口`dmesg -n1`、窗口后恢复7，并保留原传输；已知PCIe日志窄匹配还原必须通过gzip与整帧双校验。固件产物和服务配置未改。重试driver收尾错误为`TimeoutError('Functional broker never attached')`；实际运行前沿为：原首设0x1db自动电源关闭温度说明/选择页仍等待用户确认；预置37个动作在此结束，不能归为CP故障或固件卡死。实际屏幕事件30个，见`retry-1/ui-*.png/.json/.ocr.txt`；EE、Backup及池的只读状态见`passive-*.json`。出现屏幕或没有断言不等于首设已完成、EE运行或拍摄可用。

日期后的原只读状态为`EE_START_ENABLE=1`、`EE_ENTRY_SOURCE=0`、`EE_STATUS=0`、`BACKUP_SYNC_PENDING=0`。当原UI停在0x1db选择页时，这组状态不能作为CP故障证据；下一轮应补完该页的原App32确认输入，再验收ENTER_REC_STILL与三连接，不能直接开门或伪造EE运行。

另发现旧私有驱动的快门readiness用子串检查，误把回显的grep命令里的`ENTER_REC_STILL`和`ASSERT_CALLER`当成事件。原`shutter-readiness.json`保留；基于实际事件行的独立读回为`enter_rec_still=false / connections=false / no_prior_assert=true`，见`shutter-readiness-readback-v2.json`。3组自检和实际原传输通过，修正重放入口为`verify_runtime_readiness_fixed.py`配合`readiness.py`，仅供下一新任务使用；两轮已结束脚本没有改写。这一工具误判没有构成固件新断言，也没有放行快门。

首跑console SHA：`1c8e73837b092cdea3d16d220353ae143241d70a1bdca66f97376fee005e8b79`；重试console SHA：`407f5fdc7b5d3a8a442037086c0fd4c0a91586b05348630af598d90fada8a9b3`。运行原文、ulog含字节偏移/时戳、完整错误与状态分别保存在[首跑](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate32/runtime-summary.json)和[重试](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate32/retry-1/runtime-summary.json)，没有改写历史运行结论。

## Evidence → Finding → Path

| Evidence | Finding | Path / 下一消费者 |
| --- | --- | --- |
| E1：candidate31原AP/CP字节窗口与独立SHA读回 | F1（high）：缺少`0x91170319`配置接收端，AP只检查send | 原AP发送→严格解码→释放→配置记录；真实周期任务仍待后续消费者 |
| E2：两轮guest配置commit及sequence_boot E日志；console SHA见上 | F2（high）：该入口拒绝与1985断言已跨过 | 新observer/新binding→原AP继续首设→后续EE/HUD另验 |
| E3：首跑ui5原传输、窄匹配修正、gzip CRC与整帧FNV | F3（high）：首跑中断来自LCD采集污染 | 保留原失败→私有导出窗口修正→一次重试 |
| E4：重试runtime-summary、屏幕/EE/Backup/ulog | F4（high）：当前运行前沿见正文，尚无拍摄写卡通过 | 父会话核收此运行→按首个真实等待/错误继续；不能把配置接收提升为完整CP |
| E5：两轮唯一ID QMP响应、rc0、租约与socket核收 | F5（high）：本轮owner正常收尾 | quit同ID响应→rc0→退租→原失败保全 |

本地只读复核入口：从工作区根读取`candidate31/review_verify.py`的原字节比较配方及本轮`finalize.py`、`audit-handoff.py`。这些脚本采用独占新收据，不能在原目录重跑覆盖；重现实验须新建任务目录，保持相同输入SHA和完整生产derive/FD合同。原App32快门映射为半按`0x1f1`、全按`0xa7`，实际周期采用half1/full1/full0/half0，须满足原HUD/三连接/无断言准入；不写门控单元。

## 恢复、资源与限制

恢复前像逐文件SHA读回，目录0700、文件0600；原路径与模式见`restore-manifest.json`。回退须确认无后续修改，恢复两个已改源码与完整消费者/CPIO，再按原生产链重建与重新派生binding；未执行回退。

两轮均QMP唯一请求ID与原响应一致、QEMU rc0、无信号、租约保留到退出，QEMU/launcher/socket/FIFO已核收。首跑driver rc2、重试driver rc2如实保留采集或运行前沿状态。`qmp-exit-unknown`记录不能单独当作退出失败，已用原响应与真实rc分别确认。

截至最终两组核收，列项新增保留实占为3,155,787,776B，文件系统可用1,912,046,514,176B；按device/inode去重的st_blocks统计可能重复计算reflink共享extent，不称为独占物理增量。文件系统可用净变化-3,312,386,048B，与任务回收分开；实际回收0B，未执行回收。完整前像、当前binding、两份RAM profile、原始失败与重放材料保留给父会话核收及下一前沿实现，回收前须有替代恢复、明确下一消费者退出和精确引用审计。小型报告/索引及本核收收据另见`report-readback.json`。

未验证真实CP周期样本、Sony冷热启动/WBI、物理ASIC或真实设备；本轮也没有JPEG_ONLY_PASS/写卡通过结论。
