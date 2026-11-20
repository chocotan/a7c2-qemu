# P1 第十一跑：DMM 用户 LUT 集成与实际分配验证

2026-11-15。范围：将已审 DMM `0x62a` candidate2 集成到当前 `runtime/analysis/`，完整重建 guest observer/声音 helper/设备对象、基础 CPIO 和生产 RAM CPIO，再执行 P1。仅本机隔离 QEMU，不访问真实设备，不重建 QEMU 或宿主功能模型，不委派。

**LUT backing 与原 AP 发起的虚拟 CP 侧分配已实际成功；Imaging、mailbox 和拍摄写卡仍未通过。** 首轮发现真实内核参数的 `:ex` 后缀未被候选解析器支持，保留原失败后作一次最小修正重跑。修正后 `sequence_boot` 完成、原 Fsys 挂载成功，三条 Imaging 业务事件仍为 0，不能把 LUT 缺口记成 mailbox 的唯一根因。

## 集成与构建身份

封存候选：`scratch/a7c2-dmm-62a-lut-20261115-candidate2/candidate.patch`，SHA256 `9f1957c6e8a7f9a06340e7f14cbbea91869b9f667636c834bdfb2f1dd059e80f`。8 文件补丁经 `patch --dry-run --fuzz=0` 与正式应用，10 个源码/依赖绑定全部读回匹配。保留此前 USB、RAM 卡、fsck owner、DDR 与 FD 路由修改。

恢复点与执行脚本：`scratch/a7c2-dmm-62a-integration-20261115/`，含 `restore/`、`restore-manifest.json`、`pre-ex-fix/`、patch/build 日志、源码和 archive delta 收据。恢复时先停止对应消费者，按 manifest 逐文件恢复并核 SHA；完整 guest 对象/CPIO 从对应源码身份重建。旧生产 derive 保留，未覆盖历史收据。

`build-observers.sh` 全量重编译所有设备对象，包括内嵌 `struct dmm_service` 的 `vef-resource-guard.o`、声音 owner 与 sound-table，随后执行 `prepare-menu-initramfs.sh` 与真实 fsck/恢复 owner 生产 derive。初次私有 umask 导致 helper 权限收窄，已按原 archive 权限恢复；最终成员集合和权限保持一致，初次 CPIO 内容仅 observer 与声音 helper 改变，`:ex` 修正后的第二次内容差异仅 observer。

| 产物 | SHA256 |
| --- | --- |
| 当前 guest `menu-observe.so` | `003566410a1e9f62d92a8add250b8807d204fbebae12e1d3ca74a82786b64595` |
| 当前声音 helper | 见 `observer-build-inputs.json`，两轮 guest 读回匹配 |
| 修正后 RAM CPIO/derivation | `runtime/analysis/functional-camera-profiles/derive-prod-10f203e5529612d0/`；完整 SHA 见 `derivation.json` 与任务 `derive-ex-fix/derive-result.json` |
| QEMU（复用） | `b36998138a65b1bd2645ca24bf0dde0c0801d868d1291ec6f9e83ff707d64bad` |
| 1 GiB seed（复用） | `71362dfd3446d9de01fc59f1614d1dd7944a88cae19f2d70261f16e41e7e7888` |

## 两轮原始运行结果

| 运行 | 原 run | DMM 0x62a | 其余结果 |
| --- | --- | --- | --- |
| 首轮 | `runtime/analysis/menu-runs/7851` | `DMM_LUT_INIT pool unavailable`；`transport=-1021` | `:ex` 解析缺口；原失败、guest SHA、诊断和收据保留 |
| 唯一修正重跑 | `runtime/analysis/menu-runs/8426` | `transport=0 status=0 handle=0x8405 address=0x1d020000 bytes=0xbca0` | `sequence_boot` 完成，RM2 Mount/GetFreeSpace rc0；Imaging 0/0/0；mailbox/broker 未出现 |

运行证据：`scratch/a7c2-capture-p1-runtime-20261115-candidate11/` 及其 `retry-1/`；每轮 `result.json`、`integration-analysis.json`、`bluetooth-runtime.raw`、`run-1-evidence/`。两轮原始 `console.log` 与复制件均逐文件摘要核对。重跑减少为首尾两次 UI 截图，并显式标记被动日志截取范围，避免大量 framebuffer 文本淹没串口；首次完整输出仍保留。

重跑 guest 同时确认声音与 LUT 合并 token `memrsv=0x00030000@0x41d000000:uc`，离线实际 DTB `verify_reservation()` 验证 map 和 owner identity。声音自己的容量仍为 `0x20000`。原语音分配保持 `0x8400/0x8401`，LUT 独立使用索引 5。

首轮失败的直接原因是候选 `dmm_lut_reserved()` 对所有 memrsv token 只接受 `:uc` 或无后缀，而原 16 条参数包含合法 `memrsv=0x01000000@0x401000000:ex`。新增 `test_dmm_lut_reservation.py` 提取实际产品解析函数，用真实参数复现失败，再验证严格 `:ex` 支持；十进制/十六进制重叠、垃圾后缀、重复 owner 等继续拒绝。未允许任意后缀。原 36 个边界用例仍通过。

## 验证分账

| 范围 | 结果与证据 |
| --- | --- |
| 直接产品检查 | 两组/两线程，7 条编译/执行命令 rc0；语音旧服务、LUT 生命周期、VEF 资源守卫、实际 launcher 参数；`scratch/a7c2-dmm-62a-integration-20261115/product-checks/result.json` |
| 最终既有宿主回归 | 两组/两线程，22+78 项、39 subtest，0 失败/0 跳过；`analysis/scratch/cp-wait-20261111/usb-msc-host-batch-v4/run-nxku0p8z/result.json` |
| 两轮独立核收 | 两组/两线程，源码稳定、guest observer/seed SHA、DTB owner、原件与复制件、owner 退出/租约；`scratch/a7c2-dmm-62a-integration-20261115/verification.json` |
| 生命周期 | 两轮 QMP quit 确认、QEMU rc0、driver rc2（业务未通过），无信号，租约持有到退出，runner closed，QEMU owner 已消失 |
| LUT 实际分配 | 通过；原 AP `appFw+0x35522a4` 发出的请求获得虚拟 CP 回复；不声称真实 CP 执行 |
| `model_user_lut_files` 整体 | 已越过此前 CP 分配失败点；未专门钩住函数返回，不能把分配成功等同于完整函数/文件导入通过 |
| Imaging / mailbox / debugger / capture | 三连接业务 0/0/0、无 commit、mailbox/debugger/broker false、capture false |
| Fsys | 原 RM2 Mount/GetFreeSpace rc0；严格 `fsys_same_card_verified` 仍为 false，未闭合 debugger/card join |

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| 首轮 `DMM_LUT_INIT pool unavailable`、真实 `:ex` 参数、红/绿解析测试 | 候选解析器误拒合法原启动参数，使 LUT backing 未初始化 | 原 cmdline → `dmm_lut_reserved` → mmap 准入 → `dmm_service_reply` |
| 重跑 `DMM_LUT_INIT` 与 `DMM_LUT_SERVICE status=0 handle=0x8405`、guest hash | 新 LUT 服务实际被 guest 消费并完成该次分配 | 原 AP model-user-LUT 调用 → DMM 请求 → 独立 LUT slot/backing → 原发送者回复 |
| 重跑 `EE_STATUS=0`、Imaging 0/0/0、broker timeout | LUT 修复未自行接通 EE/Imaging/mainline | 原首设/录制入口条件 → 待调查的 EE 转场 → Imaging 连接 → mailbox |

## 剩余前沿

重跑被动读回：`EE_START_ENABLE=1`、`EE_STATUS=0`、`BACKUP_SYNC_PENDING=0`；名为 `EE_ENTRY_SOURCE` 的字段仍仅为 Boot Factor/eecap，值 0 不应当解释为 EE 入口调用次数。本轮没有 AP ASSERT_CALLER，也没有 `INFRA_NOTIFY_BLUETOOTH_ERROR`，未见三个 Imaging 连接请求/完成事件。下一步应追首设结束至 `enter_rec_still` 的原始转场条件与 `0x90050004` 生产者，不能继续假定 LUT 分配是唯一阻塞。

卡仍为空 seed；`A:/PRIVATE/DATABASE/DATABASE.BIN` Open 返回 `0x80000051`，原数据库创建路径与真实有内容卡对照尚未验证。真实 CP、LUT 数据传送/应用、完整冷/热/WBI 启动以及拍摄写卡均不属于本轮通过项。

## 空间与保留

任务 `storage-v2.json` 按路径记录 owner、实占、保留原因、下一消费者和回收条件；补入两份 per-run 私有 profile，早版 `storage.json` 保留不回填。核收时新增保留目录的 `st_blocks` 合计 **4,620,169,216 B**，含恢复点、两份新生产 RAM CPIO、两份私有 profile、两轮原始/复制日志与回归证据；可共享 reflink 块不等于独占文件系统分配。产品替换净增长估算 **-8,192 B**，因此任务新增并保留估算 **4,620,161,024 B**。实际回收 **0 B，未执行回收**；文件系统可用 **1,962,889,531,392 B**，净用量变化另记 **4,682,039,296 B**，不归因于回收。

无活 QEMU、无本轮活租约/调试器。原 run 的已失活 socket 路径随唯一运行证据保留供父会话核收，尚未进行 endpoint 删除，不能宣称全部清理完成。恢复点由父会话集成验收接管；首轮派生包保留用于失败复现，修正派生包供下一次 P1 消费。两份 per-run profile 含私有备份与 board 身份合同，依赖核对未完成，标记 blocked 并保留给父会话恢复/身份核收。没有 `/tmp` 实验材料。
