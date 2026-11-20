# P1 第三十九跑：face 结果接收配置

本轮先通过实际 QEMU 证明 `0x90060197/type2/index7/12B` 返回 −1020，再实现原 CP handler 可证明的接收地址、掩码及共享设置字节更新。宿主两检查组/两线程共 98 + 426 项、22 子测试通过；生产观察器与独立 initramfs derive 已重建。首次完整运行已推进到同一 SID 的 type2/index6/24B 新拒绝；因新增日志前缀未镜像而缺少 index7 的中止前接收收据，已修正日志保全并建立独立复验。当前不声明 EE、自然快门、JPEG 或写卡完成，`capture_verified=false`。

范围是用户已授权的隔离 QEMU/RAM 卡，不访问真实设备，不修改 AP EE/exclusion/镜头/快门状态。沿用 candidate38/runtime-2 的宿主和 guest 显式 functional profile、HDMI/UPM 原生观察器、broker、只读门禁探针及43动作。按用户要求跳过镜头伸出线。本轮无继续委派。

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| candidate39/trace-baseline，运行 `b299` 的原 console 与 attempt 收据 | 原 AP 的 source80020002、12B wire `020700000200028010000000` 实际 send 返回 −1020；不能仅凭 Imaging3109 推测返回码 | 原 AP 0x3548a5c → 0x90060197 → 原 transport 拒绝 → 原断言 |
| candidate38/face-consumer.json、face-callback.json 与本轮 source-verification-final.json | CP 表0xd75da8指向0x7e9e78，保存启用位、接收地址和16位掩码；回调0x7ec468更新共享键0x6000c的7字节 | type2/index7 → CP handler → 共享16B记录的 +4、+6..7、+8..11 |
| 本轮 integration-final 的 CP/观察器回归、cpio-delta及生产binding | 新接收服务在正确profile下可路由，已有CP owner生命周期回归保持；仅局部模型语义通过 | 原menu observer → profile受限调度 → 既有CP owner → face状态/共享字节 → 原请求释放 |
| candidate39/next-frontier.json 与 face-six-audit.json | 原 AP type2/index6/24B 实际返回−1020；CP处理包含条件gate、DMM句柄解引用及内部0e00投递，超出参数写入模式 | CP表0xd75d94 → handler0x7e9d54 → gate[this+2fc] → DMM0x7fa022 → 88B内部消息 |

小型报告只引用证据位置；原 console、镜像、恢复前像与运行数据留在工程受管 scratch/runtime 目录。原 CP SHA256 固定为 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，本轮逐字节读回原 handler/callback 窗口验证。

## 最小实现与失败处理

- 在已有 cp-background-device owner 中增加独立 face 快照和 type2/index7 接收；不把它加入 type5 opcode 参数表。
- 接受12B且source80020002，保存 request+4 的32位接收地址、request+8 的16位掩码，启用位为1；原 handler未消费的字节保持透明。
- 共享键0x6000c的16B记录只标记7个被原回调覆盖的字节为已知，未知初始字节不被当作有效零；这是本地模型更新，真实共享设置消费者未绑定。
- 原请求每笔释放；释放失败保留指针和 sticky fault。仅原face SID可重试释放，拒绝后台SID代领、回调重入和fork继承。没有独立 ACK、伪造face结果或超时完成。
- 日志分别标明 `handler_executed=1 apply_completed=0 result_emitted=0 completion=0 original_CP=0 capture_verified=0`，不把接收或free提升为完整后端通过。

回归覆盖原wire、全部65,536种掩码、多代覆盖、已知/未知共享字节、错误长度/来源/回调/type/index、原目的地隔离、disabled profile、重入、释放失败与owner重试、generation溢出和持锁fork拒绝。新增入口已登记 `tools/public-model-tests.json`。首轮新测试编译因测试回调const签名不符合既有接口失败，原stdout/stderr和失败收据保留在 integration/；修正后独立 integration-final/ 通过，未回填首次失败。

## 构建与运行入口

从工作区根，先读取脚本再执行。所有入口为一次性收据生成器，已有输出不可原地覆盖重跑。

```sh
TMPDIR="$PWD/scratch/a7c2-capture-p1-runtime-20261115-candidate39/tmp" PYTHONDONTWRITEBYTECODE=1 python3 -B scratch/a7c2-capture-p1-runtime-20261115-candidate39/start-observed-integration.py
TMPDIR="$PWD/scratch/a7c2-capture-p1-runtime-20261115-candidate39/tmp" PYTHONDONTWRITEBYTECODE=1 python3 -B scratch/a7c2-capture-p1-runtime-20261115-candidate39/runtime-2/start.py
```

当前生产 binding 在 candidate39/integration-observed/integration-result.json，derive 为 `derive-prod-337620c4291bb969`；观察器 SHA256 `cd761aa691463a636d7991511f9cc9475390d82f9ee50c3e38e3c8ece2c654b7`。此前 integration-final 的 derive-prod-9e1154f51c809302 与首次运行保持其原有身份和失败结论。运行器同时核对宿主/guest profile，不沿用 candidate38 首跑遗漏宿主profile的配置。

## 运行、恢复与空间

对照跑 `b299` 已正常唯一ID QMP quit、QEMU rc0、无信号、debugger/mailbox detach、owner关闭且租约保持到退出；其原异常结论保留。首次更新后运行 `6730` 也已正常quit/rc0、无信号、detach及租约到退出；它确切拒绝 type2/index6。独立复验只增加日志保全，结果待最终核收。精确源码前像见 candidate39/manifest.json 和 restore/；恢复只能逐文件反向应用本轮差异，禁止覆盖用户其它未提交修改。此前 derive 和原始输入保持只读。

新增 `NATIVE_CP_FACE_` 前缀进入关键日志镜像名单，避免原断言先于下一次截图时丢失记录；补充回归并在 integration-observed/ 独立重建，相关4项/22子测试和观察器426项通过，不重复未变的全部CP重型回归。最终运行核收、逐项实占和进程/租约状态将记录于 candidate39/final-verification.json 与 storage.json。本轮尚未执行回收。

## 下一前沿的边界

实际24B wire为 `02062770db01000004840000000000000000207000000000`，unit=0x1db、handle=0x8404、count=0。原构造器未初始化头部+2..3，因此探针显示的opcode=0x7027是填充内容，不能当成命令号；稳定标识是type2/index6。

CP原handler先读 `[this+0x2fc]`；条件成立时向0x7fa022查询实际DMM描述符，再构造88B内部0x0e00请求，包含handle、count和最多8个64位条目指针（条目跨度0x1a20）。本轮缺少同实例gate状态、实际DMM extent身份和内部消息消费者。它不是可直接复用的type5参数槽或已证明的空操作，因此没有以通用ACK/丢弃替代。新拒绝现场、原语义和最小后续依赖已保存，EE RUNNING、自然4038、JPEG及写卡仍未验收。

本路线仍是 direct-bootin 诊断，不执行真实 CP、Sony loader、WBI恢复或真实看门狗；局部接收成功不能证明完整启动、物理相机兼容或JPEG写卡通过。

## 父会话复验收尾（主会话，2026-11-16）

- 复验跑 `7737`（runtime-2）QEMU 干净退出（唯一ID QMP quit、rc0、无信号、租约到退出），但 **UPM 观察器实时锁存 `ValueError: Repeated bridge or wrong destination`**：index7 修复后原 AP 第二次进入同一 UPM 调用点（同 key 两笔 bridge），watcher 的重放与实时约束均拒绝重复 key。第二生命周期无 UPM 收据，观察覆盖不完整。
- `finalize.py` 因此正确拒绝（未生成 final-verification.json pass）——runtime-2 保留为**部分观察**现场，不作为 index7 完整运行接收收据；`b299`/`6730` 两个全观察运行不受影响。
- `account.py` 已执行：任务新增保留 3,381,846,016 B、回收 0、文件系统可用 1,890,254,385,152 B（`storage.json`）。
- 后续动作：watcher 需要支持第二次生命周期（同一调用点的重复 bridge 按代际区分）后，index7 完整接收收据才能补验收；该修复已在 candidate40 范围内一并考虑（face 运行时接入后观察点语义变化）。
