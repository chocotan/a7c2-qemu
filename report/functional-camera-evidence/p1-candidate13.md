# P1 第十三跑：首设日期完成后的同步阻塞前沿

2026-11-15。仅使用隔离本机 QEMU；未修改产品源码或固件，未访问真实设备，未委派。主证据：`scratch/a7c2-capture-p1-runtime-20261115-candidate13/`；核收入口 `assessment.json`、`storage.json`。本轮首设尚未完成，未进入拍摄待机，拍摄写卡未通过。

## 实际结果

复用 b369 QEMU、`derive-prod-10f203e5529612d0`，RAM CPIO SHA256 `75ba3158e3d4312b025bd10e029359a2ae8bfcd4dc4acb4a7e05fe67bbfb09c8`。两轮 guest 整卡 SHA 均核对生产 seed `71362dfd3446d9de01fc59f1614d1dd7944a88cae19f2d70261f16e41e7e7888`。原运行目录分别为 `runtime/analysis/menu-runs/39af` 和 `15b7`。

首轮保留了诊断失败：原帧压缩传输混入 `BSA_trace`，base64 准入拒绝。唯一重试筛除非 base64 行后仍执行 gzip CRC 和原完整帧校验；以前两份原始失败帧作回归并通过。原 guest 没有 `tail` 普通入口，重试显式改用 `/bin/busybox tail`。所有变化仅在任务驱动，不影响产品。初始尚无帧的 `ui-0-error.json` 保留，没有当作有效画面。

重试逐页走到英文 Creators’ App 页，底部区域 OCR 确认 `Set on the camera`。**该入口使用原 DELETE 键，MENU 返回上一页**；上下方向和 ENTER 会进入手机配对分支，不能靠重复提交固定序列判断首设完成。

关键动作保留为 `retry-1/action-N.json`、`input-N.raw`、`ui-N.*`、`stage-N.raw`：33 DELETE → 区域日期提示，34 ENTER → 区域，35 ENTER → 日期格式，36 ENTER → 日期编辑，37 ENTER 后出现第二次 `UDATE_K_DONE`。原 `CREATE_SCREEN_ARGS call=29 id=0x1db` 随后创建；现有 `check-natural-gtk-input.py` 将此 ID 对应温度设置提示，但本轮没有该页已显示的像素证据。

**ui-37 至 ui-42 的原帧停在日期编辑：sequence=841，完整 SHA256 均为 `bddc725e718fcd823b5b5dcb8599218dfc5c2008ba6c73ac2d469016d4b7986a`。** 后续确认、方向、原 MODE_STILL（41）和 SHUTTER_HALF（42）提交均未产生新显示。43 finish 正常结束输入窗口。

| 验收项 | 本轮结果 |
| --- | --- |
| 日期服务完成 | 两次 UDATE_K_DONE，第二次对应确认日期；仅虚拟完成，非硬件通过 |
| 原媒体入口 | `15b7/console.log` 中 FSYS_FILE_TRACE：Mount `/nondev/rm2` rc0、GetFreeSpace rc0；严格同卡 debugger join 仍未通过 |
| MODE_TRANSITION / ENTER_REC_STILL | 0 / 0 |
| 0x90050004 请求 | 未观察到 |
| Imaging PIN / CONTROL / ADF 业务事件 | 0 / 0 / 0；PROFILE 启用不算业务事件 |
| mailbox / debugger_handoff / broker | false / false / false |
| AP ASSERT_CALLER | 未观察到 |
| 拍摄写卡 | 未完成 |

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| action-33 DELETE 与 ui-33 区域日期提示 | 本机首设入口已通过原输入实际触发 | Creators’ App → DELETE → 原区域日期设置 |
| 第二次 UDATE_K_DONE、创建 0x1db、连续六帧同摘要 | 日期服务已回复，显示随后停止推进；创建页面不等于页面已显示 | 日期编辑确认 → 温度提示创建 → 待核对的界面/保存同步 |
| `retry-1/run-1-evidence/ee-passive-iyfwzen8/result.json` | EE_START_ENABLE=1、EE_STATUS=0、BACKUP_SYNC_PENDING=1 | 首设保存 → 原 Backup_sync_all 屏障候选 → 尚未进入 rec-still |

新前沿是 **BACKUP_SYNC_PENDING=1**，第十一跑为 0。该字节的已核语义见 `ee-entry-frontier.md` 和 `backup-sync-cp-contract.md`：原发送路径置 1，`Backup_sync_all` 返回后才清除。本轮只被动采样 SeqQueueCommon（futex 睡眠、无 tracer），没有采样 AppBackupDaemon，不能把 pending 单字节认定为这次的已证根因。下一次应扩大原被动采样到 AppBackupDaemon、AppFw、ExternalOSDIF 和 GRM，核对 backup 请求/回复与停止绘制的先后；不得直接清 pending 或强制置 EE_STATUS。

## 核收与保留

`finalize.py` 使用两组、两个工作线程核对两轮原始日志与复制件摘要、源码稳定和 QEMU owner 消失。两轮均 QMP quit 确认、QEMU rc0、无信号、租约保持到退出、runner closed。driver rc2 保持失败：首轮为诊断传输失败，重试为 `Functional broker never attached`。所有 QMP 请求通过现有唯一 ID 入口；未执行真实 CP，未验收完整冷/热/WBI 启动。

`storage.json` 核收时逐文件登记新增保留实占 **159,092,736 B**（写该账本和本报告前的统计），文件系统可用 **1,962,266,259,456 B**；实际回收 **0 B，未执行回收**。该数字为 st_blocks 合计，不宣称独占 reflink 块。两份本轮私有 profile 的身份/恢复依赖标记 blocked，原 run 的失活 socket 路径保留待父会话核收；下一消费者为父会话集成、恢复身份审查和下一轮原启动实验。无存活的本轮 QEMU 或 driver，不宣称 endpoint 与私有依赖清理全部完成。
