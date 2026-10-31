# 2026-10-31 冻结源码移交

本次更新把 `unified-camera-arzj0n5v` 的已验证源码选择性移交到公开包，增加功能 startup-control、still-format、S2/model17/power-on 观察，以及只读 scope v2/v3 的源码、严格 parser 和 build/profile 接口。公开启动入口、官方 ALLLANG 资产准备、HEVC/Imola 菜单与编码器接口、单卡 RM2 默认策略继续使用包内现有适配。

这是源码移交与受限 host 检查。**原 AP 拍照/录像成片、原 CP/RTOS 与物理 ASIC 兼容仍未验证，`capture_verified=false`。** 本次没有启动 QEMU、导入 Sony 原件、运行媒体解码或复制任何原运行/虚拟卡。研究批次的 PASS 不替代此公开包的动态验收。

## 固定来源

- `inputs.json` SHA-256：`a42366141d1efd70764ccb8ad82c52c001e5dbfc0a28a4f09596fe6b3a6555ce`
- `ready.json` SHA-256：`ecf3dc6dacb8e5d539fe4939ed8cb88e96cd4e54852adda034977242a8395332`
- `inputs.tar.gz` SHA-256：`647dcc26436aa31fd5d8cb3f311173e59de01d0ec646c621f3b216055fb15216`
- 研究批次来源声明：225 个测试模块、1,162 个输入，9,070 tests / 10,006 subtests，双原 ABI 与独立 v2/v3 actual API fixture。这里仅记录其来源身份，相关二进制、原件、收据与运行目录不随包发布。
- 逐文件来源及发布后摘要：[source-port-20261031.json](../../tools/source-port-20261031.json)；整个公开树的最终身份由根目录 `SOURCE-SHA256SUMS` 绑定。

四个检查文件保持该批次的原始成员字节：

| 文件 | SHA-256 |
| --- | --- |
| `functional-camera-evidence/check_evidence.py` | `a808b0bc0be2802cb6efacd7502345e10c596cb542343c3f959ff183e94d1b8a` |
| `functional-camera-evidence/test_evidence.py` | `d4bfd54212b9eb97616f0cf544c7f6ad818ef5bf789e23793a607ba387ed08f1` |
| `functional-graph-evidence/check_graph.py` | `a6a2a7d883bd146c73a90eff200d306cfe634fc99514a04f6cdeb4337a95eea1` |
| `functional-graph-evidence/test_graph.py` | `089c32f656d7a704d7da35c47ba369c49b0680bb941a18554af09154b41494f1` |

未混入同一工作区后续尚未验收的 checker 改动。graph README 也保持冻结成员 `61f5eb4625cb8b84dbd9b77a9437b74be1dfc2c1bd700773a943459521f83556`。

## 在公开包执行 host 检查

从仓库根目录执行：

```sh
python3 -B tools/test-host.py
python3 -B tools/test-public-models.py
```

第一项是已有的无编译器 host 集；第二项允许项目软件模型的 host 编译，但禁止 QEMU/bubblewrap/VM 入口。当前第二项清单包含 219 个模块，本次没有运行完整清单，留待集成者统一验证。既有的资产/原 ABI integration 范围声明保持不变，没有添加新的 skip。

本次实际执行了 Python AST 与 shell 语法检查，以及包适配、scope profile、严格 parser、synthetic builder 和 fixture driver 的受限检查：**227 passed / 672 subtests passed**。测试使用临时 synthetic 文件与 mocked subprocess；未运行 observer C harness、原 ABI 或 actual QEMU API。首次检查被命令守卫拒绝；后续检查识别出 scope driver 中独立的 assembler/bubblewrap 检查混在 parser 集内，现已完整移到下列独立测试，原失败记录保留在移交工作记录。

以下是显式独立测试，不列入普通 host 模型清单，不把缺少输入改成 PASS：

| 范围 | 测试路径 | 前提 |
| --- | --- | --- |
| 原 ELF 指令窗口 | `runtime/analysis/test_model17c_original_asset.py` | 已由公开资产准备路线安装并验证官方 `appFw.so`；缺文件直接失败 |
| 自有 assembly/link | `report/2026-10-30-qemu-readonly-scope-observer/integration/test_fixture_compile.py` | Clang、LLD 和 bubblewrap；保留全部五个 case，无 VM |
| observer C strict/SAN | 两个 scope 组件的 `test_scope_observer.py`，v2 的 `test_late_sites.py`、v3 的 `test_late_callbacks.py` | 明确准备的 API7 header/对应 QEMU 源树；不随包附带研究构建树 |
| actual API | 两个 scope 组件的 `integration/test_actual_scope_plugin.py` | 各自显式 QEMU/plugin/output/schema/receipt/fixture-source 输入；缺失直接失败 |

## scope 接口边界

没有 `A7C2_SCOPE_OBSERVER_BUILD` 时插件默认关闭。提供收据时，profile 会核对实际源码闭包、schema、source-contract、API header、QEMU 和 host ELF 插件摘要；v3 保留精确已审查 QEMU/header pin、canonical path/owner/权限检查与新输出要求。源码和输出都按本包相对目录解析，不读取相邻研究仓。

本包不提供研究插件 `.so`、candidate audit、build receipt 或原运行日志。固定 header 路径仍在包内 `source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/`；这属于显式外部构建前提，缺失或摘要不符就拒绝，不能用普通菜单构建或任意新编译二进制冒充它。源码目录中的 schema/source-contract 历史研究引用用于描述来源；相应历史文件不随包分发。

两个 `build-plugin.sh`、`build-runtime.py` 和 integration driver 的输出都限定在本包 `runtime/analysis/scratch/`；旧 research-root 回退已移除。原 CANCEL、owner、控制 EOF、detach 与未释放存储资源保护保留。失败和超时继续保留原结果，不能据此宣称已安全写盘或关闭。

## 证据与结论

| Evidence | Finding | Path |
| --- | --- | --- |
| E-source：冻结归档成员 SHA 与逐文件发布清单 | F-source：发布源码可追溯到同一已验证代，公开适配单独可见 | P-source：固定 batch → 白名单成员字节 → 发布适配 → 摘要读回 |
| E-host：受限检查的 227 tests / 672 subtests | F-host：本次实际覆盖的路径、信任边界与 parser/builder fixture 检查通过 | P-host：公开源码 → AST/shell 解析 → synthetic host 测试 |
| E-boundary：不分发外部原件、构建收据、运行日志和卡数据 | F-boundary：实际 API/原 ABI/原固件成片没有在本包重验 | P-native：显式资产与新收据准备后，由集成者另行执行 |

旧历史 batch driver 未改造成可直接复用研究收据的 public runner；新 host 清单是本包入口。最新原 run64 的 DB/XML 与黑预览结果不等于 JPEG/MP4，typed 内容复核仍为 INCOMPLETE；本次只引用这一边界，没有复制其日志或升级验收状态。
