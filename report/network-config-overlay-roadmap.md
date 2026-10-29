# 网络、配置与 overwrite：实施和验收路线

本文把早期只读方案与主会话后续原字节核验、实际实现和实验结果对齐。方案交付不等于功能全部完成。旧阶段稿保留在 `scratch/ui-config/REPORT.md`，不改写其当时观察；其中行号及“待查”状态不再作为最新结论。

下表路径相对本成果 `runtime/analysis/`；行号对应本次记录，后续修改以函数名定位。独立包 `final/a7c2-qemu/` 是已提交快照，后续功能须验证后再移交，不把 native 中的 WIP 算入独立包。

## 插入点与当前状态

| 位置 | 当前职责 | 后续接线 |
| --- | --- | --- |
| `camera_ui.py:183` `_build_header`、`:437` `wifi`、`:543` `update` | 已有 Wi-Fi 开关及确认值同步 | 保持 GTK 不阻塞、后端失败不乐观显示成功 |
| `menu_control.py:144` `enqueue`、`:231` `_run` | 有界结构化控制队列，逐条请求/回复 | 配置保存和重置沿此通道，禁止另开串口写入 |
| `menu_control.py:184` `stop`、`:200` `close` | 原 SD 保存成功后才关闭 | 真正配置提交接通后加入同一关机事务 |
| `menu_live.py:291` `run_live` | 分派网络、SD、输入和快照 | 注入受控配置回调；不允许 UI 传 shell 文本 |
| `wifi_toggle.py:40` `WifiLink`、`ethernet_peer.py:34` `EthernetPeer` | 原接口 UP/DOWN、带新 nonce 的宿主 ICMP 探测 | 功能已实现，独立包继续单独复验 |
| `start-menu.py:18` `profile_environment` | 清理环境并显式透传已支持开关 | 新开关必须 natural/non-natural 两分支核对 |
| `qemu-menu-probe.py:521` 起 setup | seed Backup、加载 backup.ko，再复制 seed-setting | 恢复时先修顺序，禁止后一次复制覆盖恢复文件 |
| `setting_store.py:304/322/329` `commit/load/reset` | 宿主不可变代、摘要、CAS、离线逻辑重置 | 生命周期租约、真实 guest 导出、GTK 重置仍待接入 |
| `firmware_overlay.py:131` `build_overlay_initramfs` | 普通文件覆盖/新增，原件不变，派生镜像校验发布 | 每个实质补丁另验消费者及固定地址兼容 |
| `qemu-menu-probe.py:233` overwrite 选择 | 根据输入构建本 run 派生 cpio | 显式 no-op、补丁版本前置条件和兼容报告可继续完善 |

## 网络：已有实现与复验

已在 native 原相机 run 完成接口和宿主探测 ON/OFF/ON，并接入正式默认 UI profile。`run-z3cma1bq`、`run-ayg9rr1n` 是已核验结果；独立包另行验收，不套用旧目录结论。

关键实现是 QEMU sysbus xHCI + 原 kernel USB 网卡驱动，stream 每帧带 4 字节大端长度；peer 保持到 run 结束，OFF 关闭 guest 接口。ON 必须取得 `10.0.0.2` 且收到本次 seq/随机 nonce 匹配的 echo reply；OFF 必须接口确实 down 且真实新探测无回复。原 `QEMU_SYSTEM_DIR` 被显示分支覆盖、过长 Unix socket、MAC/ICMP 校验和问题均已分别修复。

复验顺序：新目录安装程序身份→原相机启动→同一 VM ON/OFF/ON→各次接口与探测证据→SD 保存→正常退出。换 run、旧应答、send 返回 0、UI 颜色均不能代替链路结果。普通宿主系统的 `ping(8)` 路由与用户态 peer 探测是不同交付范围，目前交付为后者；不因此引入真实网络或宿主 TUN。

## 配置：先闭合真实提交，再接保存和重置

确定缺口是每次重建 `/setting` tmpfs、重新复制官方 seed，且没有真实 guest 配置导出/恢复。**不能再声称 `Backup_save=0` 是全局写文件开关**：原模块重定位不支持该解释，单独改成 1 的对照实验也未得到提交文件。

原 `Backup_sync_subsystem(0x51)` 返回 0 但文件仍为 seed 的失败实验已保留。原 helper 存在“两套 SearchId 记录/尺寸不满足，返回 0 但不调文件保存”的路径；尚未动态证明本次恰好走了该分支。原 `sync_all` 另依赖 CP 数据同步成功，不能用空 ACK 绕过。详见 `backup-noop-sync-contract.md`、`config-persistence-frontier.md`。

实施顺序：

1. 只读观测目标 `0051004a` 的两套解析记录、尺寸、保存标记与文件路径，解释真实提交条件；不改标记、不盲扫 setter。
2. 原 API 提交后分别核 API 值与完整 Backup 文件；验证双 bank 结构/校验和、目标字段匹配、独立 guest/host 摘要。取得一致内容后才 `setting_store.commit`。
3. 控制器建立稳定实例目录与覆盖整个 VM 生命周期的排他租约；启动前 `load`，通过本 run 派生镜像恢复。先复制一般 setting，再选定 Backup，避免后续 seed 重盖；逐项核启动 helper 是否改动所需保留字段。
4. 关机同一队列先提交配置、再安全保存 SD，两者都发布成功才关闭。失败保留 VM、旧代和原错误；不静默退回默认设置。
5. GTK 增加“销毁并重新初始化”，列明当前实例和范围、默认保留 SD。仅对已停止且无租约的当前实例发布 reset 墓碑，保留原固件、历史证据、旧配置代和其它实例。全权执行授权不取消产品面对最终使用者的范围说明。

验收至少两次 VM 和一次整个 GTK 进程重开：原菜单修改两个可识别设置→原 getter/LCD 对照→真实提交/导出/发布→恢复后原 getter/LCD 同值。reset 后回到默认/首设，而 SD 原 Fsys 文件仍同摘要。负对照覆盖损坏 current、guest SHA 错误、CAS/固件不匹配、并发 start/reset、发布 fsync 不确定；宿主 store 48 项测试只证明存储组件，不替代这些 guest 验收。

## overwrite：应用、运行效果、回退分开验收

已有安全派生、路径/链接拒绝、空间和故障隔离，host 组合 43 passed / 46 subtests；历史尾标记启动只证明那个有限补丁，不证明任意 ELF 改动兼容。输入目录中的普通文件 replace/add 是当前接口范围；删除、符号链接、元数据操作没有暗含支持。

实施顺序：

1. 记录原官方输入、基础 cpio、每个目标旧 SHA 与新 SHA；源与基础保持只读，输出只在本 run。显式路径错误和无有效变化要显示拒绝或 no-op。
2. 优先选已定位真实消费者的资源/脚本做首个运行验证；证明 guest 实际文件摘要和消费者行为同时改变。只添加未消费标记不通过。
3. 若修改 AP/CP 或固定地址探针依赖，另核 PT_LOAD 地址、原 ABI、注册/所有权与新布局；不能仅调整官方摘要后继续用旧地址。CP background 固定身份限制需明确报告，不强行放行。
4. 关闭后移除 overlay 再启动，核基础 cpio 和原消费者行为恢复。源码缓存、资产和其它运行的摘要保持原值；异常输出留在失败 run，不污染可复用基础缓存。

验收矩阵包含长/短/空内容、普通新增和执行位、相同内容 no-op、源/guest 链接与路径穿越拒绝、空间未知/不足、源并发变化、已有输出和 fsync/link 失败、补丁触及固定地址依赖、真正消费者变化及下次启动回退。任一项失败只缩小支持范围，不把“准确应用文件”扩成“任意固件补丁都能正常运行”。

## 优先顺序与难题恢复入口

当前先完成独立包构建/启动/网络/卡回载和 SD 控制边界；配置真实提交与原拍摄/音频合同遇到难题可暂放，但保留明确下一观测。配置恢复入口为 `backup-noop-sync-contract.md`；overwrite 为 `firmware_overlay.py` 和既有 host 故障矩阵；网络按正式默认 profile 复验，不重新派发已闭合的协议调查。

本计划已可用于实施和逐项证伪。功能完成状态以各专项报告为准，配置持久化/重置与任意实质补丁运行兼容尚未完成。
