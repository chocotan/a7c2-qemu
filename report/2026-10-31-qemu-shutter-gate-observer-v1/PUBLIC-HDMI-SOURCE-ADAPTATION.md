# HDMI shutter-gate-v1 公开源码适配交接

状态：`BLOCKED_PENDING_COMBINED_PUBLIC_VALIDATION`。本轮只做源码合入、AST/摘要/引用核对，未运行测试、编译、项目模块函数或 VM。原 `PUBLIC-VALIDATION.md` 与旧 validation JSON 保留上一 sealed package 的失败历史，不代表本次新源码已通过。原 Main、rootModel、实际 API7 执行、capture 与 physical 的验证结论均未提升。

## 源码范围

仅改四个已有 Python 文件：`runtime/analysis/hdmi_upm_watch.py`、`runtime/analysis/test_hdmi_upm_watch.py`、`runtime/analysis/scratch/verify_hdmi_edge.py`、`runtime/analysis/scratch/test_verify_hdmi_edge.py`。watcher 与 HDMI verifier 的生产字节分别与父审 Native4 的 `70350e27…`、`c3eafd13…` 完全一致。公开版本原固定 package 根、旧测试适配、六个 `SOURCE_SETS` 完整 tuple 和旧 v2/v3 路径保留；没有改 runner、允许的节点、生产路径/owner/receipt/opcode/receive/free/mailbox/retained-image 判据。

`read_config` 仅给精确 shutter-gate profile/schema 32 KiB 解析预算，旧默认关闭与 v1/v2/v3 仍为 16 KiB。三个配置消费点使用同一 reader。新 HDMI 分支实际核对 source7/fixture7、独立 schema/contract、原始 JSON 字节摘要、同代 Popen/nonce/退出链接，原 UPM/条件释放与成片判据继续独立执行。

## 默认公开 fixture 的边界

`synthetic_shutter_binding` 复用旧 v2/v3 envelope builder，固定源根回到本包 `BASE.parents[1]`。真实读取只包括当前公开源码：source7、fixture7、schema/contract、host helper、driver 与 source reader；构建、audit、command、manifest、parent/supplement、library 和 QEMU 的输入全部是测试临时目录中的 `HOST_METADATA` 文件字节及其 SHA。library/QEMU 是明确的惰性文本，不能执行。1193 成员和 242 模块是计数判据用的合成 metadata，未声称真实 cohort 运行。manifest 中的生产状态字面值只用于测试输入，外层 `evidence_kind=HOST_METADATA`，全部执行/成片/物理断言保持 false。

唯一的新增外部校验替身位于 fixture 的 `graph.source_module` scope-profile 分支：仅替代 `scope_observer_profile.validate_build`，断言传入的 public 根、receipt 和 QEMU 路径恰为此 fixture 的输入，返回在任何负例修改前保存的独立 metadata 深拷贝；每次返回也另作深拷贝。其他 source module 仍用原实现。未替换 `_condition_shutter_gate_binding`、receipt reader 或完整 `source_proof` 来制造正例，未改生产固定根。

默认新增测试静态计数为 watcher 16 函数 / 79 向量、HDMI 12 函数 / 121 向量，尚未执行。HDMI 前七组实际调用原 dispatcher/新 helper，覆盖精确角色、根/schema alias、旧代/nonce、Popen 和 metadata/audit 摘要拒绝；三种 audit 同时检查 claimed hash 改动与真实 JSON 字节改动。原 Native4 中五组历史 replay 测试在公开版收窄为：共享 reader 实际解析及消费点 AST、旧预算实际解析、无原件依赖的 snapshot body/header 拒绝、缺失条件 free 拒绝、真实 digest reader 的 retained 字节拒绝及原调用点 AST。它们不提供完整 `verify_hdmi_upm`、完整 source-proof replay、TCG、真实 ELF/import/export 或实际 API7 通过证据。

新增测试不读研究 parent-readback、旧 batch、私有 build、ready、插件或运行日志；`reader_config_fixture` 内 `/HOST_TEST/.../final/a7c2-re` 等绝对路径均是惰性假字符串。旧模块已有的外部 replay 测试原样保留，未做整模块 skip，也未把它们纳入本轮新增 pure fixture。

## 父会话后续验收

父已准备公开 libfdt/dtc/DTB、官方 QEMU 归档、原 API7 header 和独立 Crypto 输入；本 worker 未改动或 import 这些 ignored assets。上一 sealed 包的 745 条分类和否定结果仍有效保留。本候选需要在所有相关修复接齐、source freeze 更新后进行一次集中 source-patches / 81 adapters / host / C models 回归；原 Sony/ABI、真实 QEMU/API7 与原固件消费按明确 per-node 外部 stage 验收。缺输入继续 BLOCKED，不把 HOST_METADATA 当外部 stage 的替代品。

`SOURCE-ORIGINS.json`、`SOURCE-SHA256SUMS` 与 source inventory 待父统一冻结，本轮没有写入假定已更新的摘要。四源摘要、相对 source-base-copy 的补丁、父先前两个 public test 改动的保留情况与静态检查详情在 package 外的本轮 source-only 交接中记录。

## Evidence → Finding → Path

- E-001：四候选输入 after SHA 核对、source-base-copy 与 sealed 四源 before SHA 对照、实际 after SHA；证据类型仅为静态源码字节。
- E-002：AST 核对原 watcher parser/checked_read/owned_config/revalidate 和既有测试不变；旧 scope 分支去掉新增分派后 AST 不变；`SOURCE_SETS` 六项、原 UPM/receive/free/mailbox 等未改函数 AST 不变；新增函数无私人来源/replay fixture 依赖。
- F-001（source-only，evidence_ids=[E-001,E-002]）：公开源可独立生成 HOST_METADATA 测试输入；尚不能判定运行回归或真实 API 通过。
- P-001（callflow）：source-base-copy → 四源精确合入与 public fixture 适配 → 静态交接 → 父统一 freeze / 集中回归 / 显式外部 stage。当前停在静态交接。
