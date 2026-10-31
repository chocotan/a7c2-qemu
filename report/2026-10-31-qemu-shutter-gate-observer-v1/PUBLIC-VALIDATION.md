# 隔离公开包 shutter-gate-v1 验证

本次仅集成公开源码与软件组件。状态：`BLOCKED_PUBLIC_PACKAGE_ASSET_AND_HEADER_PREREQUISITES`。正式公开仓库未由本 worker 写入，尚未发布；原 Main、native UI、capture 与 physical 均为 false。host/model 结果与研究批独立记账。

## 范围与复现

源为公开 tracked 白名单与父批准的 Normal-NC identity 页表/向量/unaligned probe 33 源候选。默认关闭的只读观察器和严格 profile 判据保持；source7/fixture7 从公开适配后字节冻结。

在包根执行 `bash tools/check-host.sh`、`python3 -B tools/check-source.py`、`python3 -B tools/test-host.py`、`python3 -B tools/test-public-models.py`；两个 adapter/runner 回归模块另外以相同 VM 拒绝审计执行。完整执行收据和 skip node IDs 位于 `validation/2026-10-31-shutter-gate-v1-publication.json`。不得将外部前置失败计为通过。

| 阶段 | rc | 实际统计 |
| --- | ---: | --- |
| script-sync | 0 | {} |
| host-dependencies | 1 | {} |
| source-patches | 1 | {} |
| adapters | 0 | {"passed": 81} |
| host | 0 | {"passed": 278, "skipped": 58, "subtests passed": 76} |
| models | 1 | {"passed": 6074, "failed": 494, "skipped": 1566, "error": 0, "subtests passed": 354, "errors": 249} |
| actual-missing-env | 1 | {"failed": 1} |
| models-targeted | 1 | {"passed": 403, "failed": 1} |

缺失前置：Crypto/Cryptodome、固定 QEMU 上游源码归档、包内固定 API7 header 与原 Sony 资产。没有引入依赖或借入 ignored 构建。新 C mock、same-run reader 与实际 API 三个命名外部模块不进入默认模型列表；实际 API 缺六环境输入保持硬失败且无 skip。原 ABI、ARM guest、QEMU 源补丁实际应用与真实 UI 仍未在此隔离包执行。

## 研究历史边界

父已接受 `unified-camera-pvebt_i6` 的 10203 tests / 10581 subtests、242 模块、1193 输入及四组无漂移。这里仅记录来源，不复用其插件、收据或 ready 来验收适配后的包。t7 的 host builder 测试时序失败、iii 的实际 API 失败与 kq 的 stub 实际 API 失败均保留其否定历史；后来的 Normal-NC 修正版成功不改写这些失败。私有日志、guest、真实 build receipts 与虚拟盘不随包提供。

## Evidence → Finding → Path

- E-001：本次 source-port 绑定逐文件 before/candidate/after SHA、研究父读回和适配后 source7/fixture7。证据类型为源码清单；复现为对逐项包内文件计算 SHA-256。
- E-002：本次 publication JSON 记录每阶段 rc、输出 SHA、统计、skip node IDs 和 stable 输入；原始 host 验证字节保存在父接收的隔离证据目录。复现命令见上。
- F-001（validated，evidence_ids=[E-001,E-002]）：仅在上述实际通过的 host/model 范围内确认集成。外部前置与运行资产仍阻塞完整公开包验收；未证明 Sony 成片。
- P-001（callflow）：tracked 静态快照 → SHA 核准 33 源 overlay（E-001/F-001）→ 集中 host/model/adapter 检查（E-002/F-001）→ 父独立核收后决定发布。残余风险是未执行资产阶段与原固件成片链。

本报告使用通用技术验证结构；不适用恶意软件/ATT&CK/IOC 分类。

默认 models 中的 `integration/test_shutter_gate_trace_checks_v1.py` 实际依赖真实 C mock/API7 header，首轮有 190 个 setup error；保持原失败，没有合成 header 或整模块 skip。该分类问题仍阻塞默认入口。完整 models 未重复执行，最终只复测已修的 adapter、host 记录器和 socket/SAN 夹具。
