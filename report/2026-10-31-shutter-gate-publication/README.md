# Shutter-gate v1 公开源码与 host 验证移交

本次交付装配已冻结的 shutter-gate v1 源码、host 前置声明及 config-content 修正。**原固件 JPG/MP4 尚未完成；`capture_verified=false`，native UI、original Main 和物理 ASIC 兼容性均未因此通过。** 独立公开包的八阶段结果为 `PASS_HOST_PUBLIC_PACKAGE_ONLY`，`overall_external_validation_passed=false`。提交与发布由父会话最终审核；本交接记录的 `published=false`。

## 范围与使用前提

授权范围为公开源码装配、读回与离线静态检查。没有启动 VM/QEMU、操作真机或真实 SD，也没有复用其他会话的进程、虚拟卡或运行目录。新包保留独立运行布局；Sony 原件、完整 dump、私有 setting、guest、卡、插件和 helper 二进制均不随源码交付。

读者从 Sony 官方更新渠道取得 **ILCE-7CM2 2.01 ALLLANG**，按[包内资产准备说明](../../docs/tech/01-firmware-assets.md)和[主入口](../../README.md)在本地准备。已固定的 `BODYDATA.DAT` SHA-256 为 `eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31`。本次发布装配没有再次导入原件。QEMU 上游归档是[显式外部输入](../../source/vendor/README.md)，本包不会自动下载。

[requirements.txt](../../requirements.txt) 已声明 `capstone>=5,<6`、`pyelftools`、Pillow 和 pycryptodomex；主机预检同步检查所需导入。第三方 Python 的 `RECORD` 只作为本地依赖清点元数据，不能把 site-packages、Capstone/Crypto 二进制或 libc/helper 产物加入 Git。

## 八阶段的实际结果

以下计数来自同一已完成验证，阶段顺序和预期返回码均经父独立核对。它们属于原冻结的 **2378 个源码文件**，没有把随后新增的两份发布文档算成已重跑全套测试。

| 阶段 | 实际/预期 rc | passed | skipped | subtests passed | 结论 |
| --- | --- | ---: | ---: | ---: | --- |
| crypto-import | 0 / 0 | — | — | — | 依赖导入通过 |
| script-sync | 0 / 0 | — | — | — | 根脚本同步只读检查通过 |
| host-dependencies | 0 / 0 | — | — | — | 显式 host 前置检查通过 |
| source-patches | 0 / 0 | — | — | — | 三段 patch 和 DMA/ATU/PCI 源身份通过 |
| adapters | 0 / 0 | 81 | 0 | 0 | 通过 |
| host | 0 / 0 | 302 | 34 | 76 | 通过；保留原跳过范围 |
| models | 0 / 0 | 8477 | 106 | 10420 | 通过；231 模块、24 个明确外部 host-scope 节点的边界不变 |
| actual-api-missing-env | 1 / 1 | 0 | 0 | 0 | 精确一个 failure、零 error；缺少显式 actual API 输入时按预期拒绝 |

八个阶段均 `expected_status=true`、`inputs_stable=true`。最后一项是负例通过，不能宣称 actual API 正例执行成功。原始日志、逐项 skip、前置和控制账本保留在本地验证证据中，公开摘要见[机器可读收据](../../validation/2026-10-31-shutter-gate-host-package.json)。

## 固定输入与两个独立读回

| 证据 | SHA-256 | 范围 |
| --- | --- | --- |
| 原八阶段 `result.json` | `1304bc588673289413a543aeeed3880b3508416882e9fb4f9389938f32b91a24` | `official-eight-stage-b26de404b2fa4ab181359b7cde251dab` 的实际结果 |
| 父 `ACCEPTANCE.json` | `6fcdaed5451450139b4e464d71b69325b7a0a3a02ab550f613e14dc39718bd1a` | 独立读取全部 4206 项及匹配控制账本 |
| 父 `all-content-readback.json` | `1d520604284dcc7707aa812fc1723203dfd0826555455bb9fb0db428022abe77` | 全内容摘要读回证据 |
| `candidate-frozen-inventory.json` | `14b98f8993dee8fa07b49712ac018552d9ab6f85eb3b494b638935aa6a6e94ee` | 唯一可装配源码白名单：2378 项 |
| `candidate-frozen-prerequisites.json` | `80b077b06fc51d6e1d4b857bd996dbd81d160dc8d711730d78ab9ef26754040a` | 424 项本地 host 前置，不发布 |
| `external-assets-manifest.json` | `1ff21c0fac4069700644fd7ba94d7f95c044341d249fa0b9e382c498167534a9` | 1404 项外部资产，不发布 |

父验收对 **2378 source + 424 host prerequisites + 1404 external = 4206** 项核对实际内容、大小、模式、UID、nlink 和控制账本；外部项含 155 个 guest 链接、1290 项 Sony 原件/派生资产，普通外部文件共 3,032,646,539 字节。资产准备与内容核验不等于执行 Sony 原库或拍摄。

装配先对 2378 项逐项复制并读回，再仅新增本文和公开 JSON 收据。为让读者找到新结果，仅追加 `SOURCES.md`、`validation/README.md` 和 `SOURCE-ORIGINS.json` 的发布追溯，并刷新 `SOURCE-SHA256SUMS`。这四项已有元数据与两项新增文档明确单列为装配后的变化；其余 **2374 项**继续与原 frozen map 的 bytes/mode/size 完全相同。校验清单覆盖最终 **2379 项**，沿用排除自身的规则；最终公开树为 **2380 项**。没有制造自哈希循环。

## 本次已验的公开差分

- 默认关闭的 `qemu-readonly-shutter-gate-v1` profile、只读观察器、严格 parser、构建/fixture 接口和 input/caller 接线一并装配；`source7`、独立 `fixture7` 均绑定公开适配后的实际字节。
- profile/receipt/schema/contract/源码身份和 owner/权限/新输出条件继续严格核对；没有借用研究运行收据来准入公开包。
- shared config reader 只给**精确新 profile** 32 KiB 解析预算；旧 profile 继续 16 KiB，内容复核和 live revalidation 保留。两个读取方与独立 HDMI reader、同次来源和 32 KiB 边界检查纳入冻结输入。
- host 依赖声明增加 Capstone/pyelftools 的明确前置；保留原 Unix socket 边界、测试 scope 和外部 actual API 缺环境硬失败。

逐文件差分仍按原层级查阅 [shutter-gate 来源账本](../../tools/source-port-shutter-gate-v1.json)与[config-content/依赖修正账本](../../tools/source-port-shutter-config-content-v1.json)。后者对列出的文件和依赖字段覆盖前者的旧摘要，最终文件身份由根 `SOURCE-SHA256SUMS` 固定；本次只追加验收追溯，不重写旧来源记录。

## 研究来源与原固件边界

已验研究配置修正来源 `unified-camera-0eod_0o9` 为 **10403 tests / 10581 subtests，242 模块、1193 输入**，父离线读回已接受；相同1193来源的后继 `unified-camera-r3ns_5uf` 也完成同规模完整验收，其 launch-pin 工具修正没有改变这些业务源码。其原 ABI 和自有 actual API fixture 是研究来源证据。gate 的四个自有 guest case 为 `original_entry`、`existing_main_stub_entry`、`one_byte_gate_mutation`、`short_tb`，保留 baseline/plugin 配对与内容核对。旧来源账本中的 `unified-camera-pvebt_i6` **10203/10581** 是更早的历史，原文和原摘要保持不变。

上述研究通过不提升公开包的 API7 正例或原 AP 身份证明。原固件 `doc4` 运行仍为 **FAIL / rc1 / no JPG**；原失败证据保持不变，capture/physical=false，旧负面证据保留。本包旧 [PUBLIC-VALIDATION.md](../2026-10-31-qemu-shutter-gate-observer-v1/PUBLIC-VALIDATION.md) 与[旧 publication JSON](../../validation/2026-10-31-shutter-gate-v1-publication.json)保留此前缺前置失败，本文记录的是后来同一冻结输入具备明确前置后的 host 结果，不回填旧文件。

随后 Native 的 14 源新批次不在本次 frozen map 中；该首批实际为10090 passed／1 failed／347 fixture setup errors／10581 subtests，父正补齐旧C片段测试夹具的观察器声明闭包。本次没有移交这些新修改或宣称其验证完成，当前交付仍是上述已验配置修正来源对应的公开源码与独立 host 验包。

| 外部阶段 | 本次状态 |
| --- | --- |
| Sony 原件执行阶段 | `NOT_RUN_EXTERNAL_STAGE`；仅已独立准备并读回外部资产 |
| Sony 原 libc 2.25 执行 | `NOT_RUN_EXTERNAL_STAGE` |
| QEMU-user / native ABI | `NOT_RUN_EXTERNAL_STAGE` |
| actual API7 正例 | `NOT_RUN_EXTERNAL_STAGE` |
| GTK desktop runtime / 原 UI | `NOT_RUN_EXTERNAL_STAGE` |
| 原 AP → CMOS → codec → MPR/Fsys → 虚拟 SD → 独立解码 | 未通过，`capture_verified=false` |
| 真机、真实 SD 与物理 ASIC | 未操作，`physical_asic_compatibility_verified=false` |

## 复核入口与证据链

在已自行准备对应前置的仓库根目录，离线源检查和最终清单读回入口为：

```sh
python3 -B tools/check-source.py
sha256sum -c SOURCE-SHA256SUMS
```

本次 source-only checkout 没有固定 QEMU 归档，直接源码 CLI 按预期 rc1 拒绝；原字节和失败原因保存在本地交接证据。随后对只读的已验 prepared source root 执行同一 `tools/check-source.py`，三段 patch 与 DMA/ATU/PCI 身份检查 rc0；其全部被消费项目源码与本 checkout 相同，临时补丁树仅写本次 scratch。没有把归档、host 依赖或原件复制进 checkout。根 `analysis/sync_repo_scripts.sh --check` 与独立 worktree 的 `git diff --check` 均 rc0，真实 argv/cwd/rc/输出摘要留存本地，公开 JSON 只保留可移植摘要。

完整 host/model 入口和外部实际 API 的明确输入见[验证索引](../../validation/README.md)与[组件说明](../2026-10-31-qemu-shutter-gate-observer-v1/README.md)。本次装配阶段只做最窄静态检查、文档/JSON/清单及来源正反检查，没有为新增文档重跑完整 pytest，也没有把旧八阶段说成对最终 2380 文件重新执行。

| Evidence | Finding | Path |
| --- | --- | --- |
| E-source：frozen inventory、source7/fixture7 和逐文件来源账本；复核为逐项 SHA-256/mode/size | F-source：`validated`、`n/a_re`、高置信；位置为本次源码白名单，仅证明精确源码装配 | P-source（callflow）：冻结源码 → 独立 checkout → 全内容读回 → 明确文档/元数据例外 → 最终校验清单 |
| E-host：上表 result SHA 与父 acceptance/readback SHA；计数来自实际八阶段 | F-host：`validated`、`n/a_re`、高置信；仅 host package 通过，evidence_ids=E-source,E-host | P-host（callflow）：明确依赖与外部资产准备 → 八阶段实际返回码/计数 → 父全内容验收 |
| E-boundary：独立外部阶段未运行、旧 doc4 rc1 与旧失败 JSON | F-boundary：`open`、`n/a_re`、高置信；capture/native/physical 均未通过，evidence_ids=E-boundary | P-external（callflow）：独立外部验收与真实原 AP 成片链仍待实际执行 |

时间顺序为：研究0eod及同源r3ns_5uf离线接受 → doc4 原固件失败保留 → 外部依赖/官方资产准备 → 原 2378 源八阶段 host 验证 → 父 4206 项独立验收 → 本次独立源码装配与发布元数据静态检查。原始本地证据通过上表 SHA 固定，未随 Git 分发原件或运行输出。
