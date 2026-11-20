# P1 candidate49：type0 预览请求接收与实际首设校准

本轮实现准确匹配的 type0 `0x301a` 接收和请求释放，尚未实现 CP 内部预览状态机。现有 AP、CP 接线及 JPEG 接收优化全部保留。运行验证使用独立虚拟 SD 卡和原始 App32 按键；真实设备、原整机镜像未写入，`capture_verified=false`。

范围和授权见 [scope.md](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate49/scope.md)。原始指令、宿主检查与运行证据位于 `scratch/a7c2-capture-p1-runtime-20261115-candidate49/`。文档按 docs-generator 的普通逆向报告（flavor=null）规则组织。

## 已确认的原语义

| 证据 | 发现 | 实现路径 |
| --- | --- | --- |
| `source-audit.json`；AP `0x3544b84..0x3544cb0`；原 corpus `parts/0/0x001710000.c` | `301a` 为 `EID_PREVIEW_MODE`；AP 参数0/1/2映射wire[8]=0/2/1；send的等待、输出指针、输出长度均0 | 不分配回包，不伪造业务返回 |
| `type0-source.json`；CP `0x4b6064` 跳转表与 `0x4b6246..50` | 读取request[8]，将其复制到零化32B内部事件+16，event8102；公共尾部复制token和source并提交900302d9 | 接收层保存完整wire和mode；central8102状态机缺失单独记录 |
| bac2 `console.log`、`shutter-readiness-41.json`、`ui-41.ocr.txt` | 实际已有ENTER_REC_STILL、三项readiness均true、拍摄页FINE/MECH；“首设未完成”的交接结论错误 | 保留已实证动作；快门前检查当前readiness和OCR，禁止盲发快门 |

## 修改与恢复

修改产品 `runtime/analysis/device-models/cp-background-device.c/.h`、`test_cp_slot_retire.c`、`runtime/analysis/test_cp_slot_retire.py`。前值及完整SHA256见任务 `restore/` 和 `source-audit.json`；恢复时逐文件核对快照，再使用原构建入口重建observer及CPIO。不得用旧二进制覆盖新接线。

`301a` 仅接受 destination90030001、source80020002、type0、12B；byte1及尾部保留为不透明数据。所有权沿用既有请求退休层：串行状态保护、重入拒绝、PID隔离、释放失败保留、单调代次；错误类型不会误入type5路径。`NATIVE_CP_BACKGROUND_PREVIEW_PENDING` 明确输出 `internal8102_delivered=0 preview_mode_applied=0 ap_reply=none handler_executed=0 completion=0`。

## 宿主验证

两线程、两组检查。首次宿主回归失败原因是旧alias测试只改opcode、没有按新协议同步type；产品没有启动VM。原失败日志保留在 `integration/`，修正测试后另立 `integration-2/`：

- CP背景/slot/批量opcode：3 passed、22 subtests passed，slot内部覆盖256参数字节、所有错误类型/长度、fork、并发、重入和释放失败。
- 原有接线/receive：3006 passed；修正仅发生在测试夹具，未再次重复已通过的重型接线检查，复用收据记录在 `receive-wiring-reused.json`。
- observer与CPIO已重建，成员及权限保持，唯一CPIO内容差异为simulation/menu-observe.so；独立RAM卡派生清单保留。

## 运行验证

独立运行 `menu-runs/b84d`。当前结果以任务 `final-verification.json` 为准；本段在完成后补记。启动者 `run.py --resume` 带有已核身份的owner恢复流程：driver写出SERIAL_OWNER_RETAINED后调用既有recover.py，通过独立lcd-qmp socket核验uid、run inode、QEMU SHA256后发送唯一ID的query-status/quit。未闭合capture仍拒绝退出，所有场景不发送信号。

覆盖限制：这条路线运行原AP，但未执行真实CP固件或Sony loader/WBI恢复。接收退休通过不能说明central8102已消费，不能替代自然4038、RGB/JPEG、写卡和两次导出验收。

## 空间与保留

前置空间、12GiB新增峰值和64GiB余量见 `source-audit.json` / `integration-2/budget.json`。最终新增、保留、回收和可用空间以任务 `storage.json` 为准。原失败、当前绑定及源恢复点保留给父会话核收；未执行回收，不把候选删除量记为回收。
