# 只读快门 gate 观察器 v1

本组件用独立、默认关闭的 `qemu-readonly-shutter-gate-v1` profile，观察原固件 final 入口、`d570` 条件跳转前以及两个后继入口的寄存器。它用于定位快门请求停在哪个分支；成片仍须由原 AP 发起、实际帧被编码器消费并经原 MPR/Fsys 写入虚拟 SD 后独立解码。

## 观察范围

| 站点 | appFw 相对地址 | 记录含义 |
| --- | --- | --- |
| `final_entry` | `0x1af16dc` | 原 16B prologue 或既有 Main 8B stub 执行前，含 X0/X1/X2/X3/LR 与 trigger 低 32 位 |
| `d570_cbnz_pre` | `0x1af1834` | exact `LDR W0; CBNZ W0` 同 TB 字节核对后，在 CBNZ 前读取实际 W0 |
| `successor_1724_pre` | `0x1af1724` | 目标入口执行前的原寄存器 |
| `successor_1838_pre` | `0x1af1838` | 顺序后继入口执行前的原寄存器 |

只有 exact gate 窗口能建立或冲突候选基址。其余三个弱站可以先注册；未绑定或异基址时只累计 `unbound_callbacks`，不读寄存器、不出成功行、不耗成功配额。完整不支持的已知窗口使整组失效；仍兼容原 prologue 的短前缀保持 unknown，禁止跨 TB 拼接。

插件只使用 API7 的 11 项只读接口。`read_register` 必须返回 true 且长度恰为 8B（CPSR 为 4B）；X0 的合法 NULL handle 按描述符名字识别。event PC 来自翻译期地址，GDB PC 原值可能延迟；SP、TTBR0_EL1、TPIDR_EL0 缺失时保留 unknown。每站最多 16 条成功行，故障最多 32 行，单行小于 2048B。源码不写 guest 寄存器、PC、栈、内存，不调用 guest helper 或注入事件。

`source_next_pc` 是由同次 X0 低 32 位计算的源码预测。各站独立采样与数值上下文匹配不证明原 AP 调用配对、唯一进程/线程/地址空间、分支边或指令退休；所有 Main/AP 身份、retirement、store/return、capture 和物理 ASIC 兼容性标记保持 false。

## 构建与验收

使用原 `4e85c70b…` plugin-enabled QEMU 候选及固定 API7 header，独立构建目录不会替换生产 QEMU、旧目录卡候选或 v2/v3 插件。真实构建入口是：

```sh
python3 report/2026-10-31-qemu-shutter-gate-observer-v1/build-runtime.py \
  --candidate-audit "$CANDIDATE_AUDIT"
```

在公开包根目录执行，并将 `CANDIDATE_AUDIT` 指向已核验候选的静态审计收据。构建器输出新的 receipt 路径，绑定 exact source7、独立 fixture7、真实 schema SHA、contract SHA、插件 SHA、编译命令和 nm/readelf 原输出。外部 schema 摘要键唯一为 `trace_schema_sha256`；contract 含实际 schema 摘要而不含自身摘要。所有新 profile JSON 边界拒绝重复键和非有限数，包括额外字段内的数值与指数溢出。

研究完整批与公开包验收分开记账。公开默认 host/model 入口不执行 actual API；新 C mock 与依赖它的 same-run reader 测试沿用既有外部 header/构建前置分类，缺前置不计为通过。显式实际 API 入口缺少六项输入必须失败，不能改为 skip。

研究侧验收按一次完整批执行：

1. strict C11、ASan/UBSan、真实 C mock trace/strict parser、host profile/caller 与 GTK pointer 回归；保留旧 v2/v3 回归与双原 ABI。
2. 显式资产阶段执行 `integration/test_actual_scope_plugin.py`。普通 host 阶段仅冻结此源码，不执行或用 skip 替代；必须提供六个 `A7C2_SHUTTER_GATE_V1_TEST_{QEMU,PLUGIN,OUTPUT,SCHEMA,RECEIPT,FIXTURE_SOURCES}` 环境变量。
3. 四个自有 guest case 为 `original_entry`、`existing_main_stub_entry`、`one_byte_gate_mutation`、`short_tb`。正例先 gate warmup，再执行 40 次入口、共 41 次 gate 和 21/20 次两后继；每个 case 先运行 baseline，再运行同字节 guest 加插件。核对独立 GPR/SP/CPSR/token/source64/栈/code dump 和实际原始 trace，不从 trace 填补预期值。
4. 只有新完整批及父独立读回通过后，才准备全新 guest、空虚拟卡、intent 和 nonce，进行一次原固件综合 UI 观察。默认无 receipt 仍只准入旧候选；4e85 必须经显式匹配的 `scope_build_receipt`。

`integration/fixture-source-pins.json` 必须从公开适配后的实际字节重新冻结 fixture7，不能复用研究侧 pinfile 或 build receipt。六字段导入审计严格核三条实际 argv/返回码/原输出，以及分别列出的 11 项 QEMU imports、普通 libc/GLib imports 和 DT_NEEDED；普通 imports 不计入“恰 11 项 QEMU API”。same-run reader 保留原始 LF 行号、字节偏移、摘要及原字节，并核正常 owned exit、库/源码/schema/receipt/audit 与实际 Main 来源元数据。

首次源码集成阶段只完成静态审合，未把旧批次或旧 run 的成功当作本组件 ready。执行结果以本次独立完整批、actual API manifest 和父读回收据为准；自有 guest 通过也不表示原快门、CMOS、编码或拍照录像已经恢复。

未验证的边界：原 final 内实际 gate 分支、原 AP→CMOS→codec→MPR/Fsys→虚拟 SD 成片，以及物理 ASIC 兼容性。
