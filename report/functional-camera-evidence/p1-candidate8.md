# P1 第八跑：完整 guarded 链已准入，BB/Imaging 同步断言仍复现

第八跑在独立 RAM 卡状态上执行一次实际 QEMU 运行，目录为 `runtime/analysis/menu-runs/a5a9`。**原 AP 仍触发 `infra_wrapper_bb:906` 和 `infra_wrapper_imaging:3109` 两处断言，mailbox、debugger handoff、broker 与 Fsys 同卡均未验收通过。** 这次确认第七跑已经启用了委托要求的完整 BB/Imaging guarded 链；单纯重复设置这些变量不能解决当前前沿。

仅操作本机隔离虚拟机，不连接真实设备，不修改固件、产品运行源码、共享 QEMU/CPIO 或历史失败收据。文档使用普通技术报告结构（`flavor=null`）。原 Sony loader、WBI 恢复、原 CP RTOS 与物理硬件均未覆盖。

## 配置和输入

启动前逐项检查 TCIN inactive → DFS selector → VEF NoMem → ADF source7 Idle → ADF set input/output → BB set mode → Imaging image/control/audio → InfraBB VEF image/control，及后续第七跑已有的 PinMem/HDMI/CP/functional profiles。PIN registry/control-memory/cold、public ALLLANG、单 CPU、BusPower、iCrypt、Backup 同步、16 项兼容基线全部保留。

相对第七跑，**只有 `TMPDIR` 改到本任务目录，新增 guest 变量为 0**。`BB_MODE_CONFLICTS`、`ADF_CONFLICTS` 及 `qemu-menu-probe.py:321` 的 one-card 排除项均核对；未设置目录 SD、其他卡、USB 网络、native AP/CP link、RAM restore、帧/ready 强制注入或 409 探针。`backup_profile.validate_functional_camera_media` 实际通过。

复用已核验只读输入：

- QEMU `b36998138a65b1bd2645ca24bf0dde0c0801d868d1291ec6f9e83ff707d64bad`；无需重建或新增二进制副本。
- CPIO `74c708dca7098651cc01bf7ddbcd34e76d7f1e105f52e9b7ddbc58ece758c5ca`，1,492,625,848 字节。
- Seed `71362dfd3446d9de01fc59f1614d1dd7944a88cae19f2d70261f16e41e7e7888`，1 GiB；本轮独立 profile 为 `runtime/analysis/functional-camera-profiles/profile-de21f36c4c143dfc0fc7842270e04b01`。
- 有效 DTB DDR 8 GiB，QEMU 实际进程 `/qemu-system-aarch64`，四字符 run 名，最长 endpoint 107 字节。

脚本复用第七跑运行器，增加精确配置差集和前置校验。因而 traceback 仍引用 candidate7 的实现路径，8 MiB ulogio 转储仍名为 `candidate7-ulogio.bin`；**本轮文件位于 a5a9，内容与摘要均独立，不能按文件名归属到旧运行。**

## 结果和更具体的前沿

| 阶段 | 本轮证据 | 结论 |
| --- | --- | --- |
| Guest RAM 卡 | 两次全卡 SHA 和长度读回匹配 1 GiB seed | 运输/内容通过；`/image_mmca` 为 observer 复制件，不能代替原 Fsys 挂载 |
| 模型准入 | BB 与前三条 Imaging/InfraBB profile 均记录 `enabled=1 first_missing=none` | 配置已启用 |
| 前三条 Imaging 实际业务 | 对应三个 `FULL_IMAGING_*_CONNECT` 前缀各有 4 条 constructor profile 记录，业务记录均为 0 | 未观察到这些模型完成请求/回复/原 AP 消费；不能宣称连接完成 |
| InfraBB→VEF | `UNADMITTED predecessors_not_ready=1 requests=0` | 依赖未满足，守卫正确保留 |
| InfraBB→VEF control | `UNADMITTED four_predecessors_not_ready=1 requests=0` | 后续连接仍受阻 |
| 旧 VEF→PinMem 路线 | `FULL_PIN_CONNECT_COMMIT metadata_connected=1 format_pending=0 buffer_released=1` | 部分旧路径执行；不等于完整 Imaging 链通过 |
| 原 AP | 两处相同同步命令断言 | 第七跑前沿复现，无推进 |
| mailbox / debugger / broker / Fsys / capture | 均为 false | P1 下游及拍摄写卡未完成 |

源代码 `device-models/infrabb-vef-connection.c:112` 的 `dependencies()` 明确要求前三条连接 `connections=1`、`ap_consumed=1`、clean completion、format/buffer 退休等实际状态，还要求旧 pin、VEF path、ADF input 和 registry 状态。`enabled=1` 不能满足这些条件。当前 console 没有提供前三条连接进入业务后的完成记录；精确缺少哪个上游原请求、为何没有被这些模型处理，仍需继续核对接收路由，不能由缺日志直接归因为某个硬件。

原 ulogio 同时保留 `register_callback` 的 `l_err=FFFFFC04 qid:0184E0D91`、`send_sync_msg/call_sync_api` 的 `FFFFFC04`、多条 pin topology 连接失败、DMM `alloc_core=-3` 和媒体 `0x1000` 挂载错误。ulogio SHA 为 `e704351b89f472b44f1bb91a23c7a50ff527b0bda45055a9ae2ba147af86ec2b`。这些是后续调查输入，尚未闭合到两处断言的因果链；环形缓冲区物理偏移不代表全局时间顺序。

## 验证与退出

独立读回 **2 个检查组 / 2 个工作线程**，均通过：产品源文件前后 SHA 稳定、精确环境差集、全部 MENU 导出、17 份原始证据与归档完整 SHA、有效 DDR、全卡 SHA、QMP quit、Popen wait、owner 消失、租约直到退出和 runner safe-to-close。

QEMU `quit` 成功、实际返回码 0、未发信号；驱动实际返回码 2，明确代表原 AP 故障，不能把 QEMU 受控退出记为业务成功。未采集原 AP 进程的独立退出码。异常监视器只读收集 reg/call/code/stack，没有修改寄存器或内存，没有恢复原 AP 执行。没有第二次 VM 尝试。

首次核收脚本错误地把终端宽度插入的 `CR CR LF` 当成命令缺字，失败留在 `finalize.stderr`。仅对该确切折行字节修正解析、增加合成断言后，第二次核收通过，未重跑 VM；结果为 `finalize-2.stdout` 和 `verification.json`，旧失败未回填。

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| `preflight.json`、两轮 environment、guest constructor 行 | 第七跑已启用完整链，第八跑无新变量 | host 校验 → guest 导出 → constructor 准入 |
| `wait-analysis.json`、a5a9 console、`infrabb-vef-connection.c:112` | 准入与连接完成是两个不同阶段，前三条实际消费缺证，第四条受阻 | 上游原请求/路由 → Imaging 三连接 → InfraBB VEF dependencies |
| 两条原断言、8 MiB ulogio、异常监视器采样 | 相同前沿复现，根因仍未定 | 原 AP 同步请求 → 报错/等待 → notify_model_system_error → abort |
| `verification.json`、`driver-exit.json`、consumer receipt | owner 正常退出，失败状态保持 | QMP quit → wait rc0 → 租约结束 → runner close |

全部原始运行证据与脚本在项目根的 `scratch/a7c2-capture-p1-runtime-20261115-candidate8/`。下一步应追查前三条 Imaging 原请求/接收路由以及 callback 注册的 `FFFFFC04`，同时保留 DMM/Fsys 的独立未闭合线索；重复添加现有环境变量没有新增价值。

复现脚本为 `verify_runtime.py`（会创建新 VM 和独立 profile）；因本目录以排他写入封口收据，复现时应建立新的专属任务目录并显式设置其 `TMPDIR`，不能直接覆盖本轮文件。`finalize.py` 验收已完成运行，`account.py` 输出逐项空间账本。**未执行回收，实际回收 0 字节**；新增实占、可用字节及保留原因见任务 `storage-final.json`（`storage.json` 为首轮记账快照，保留不覆写）。原失败、独立卡状态、归档和非活 socket 路径保留给主会话核收，核无活引用和恢复依赖后才可处理精确白名单。
