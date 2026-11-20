# CP runtime 平台源码移植

此包把**已应用产品 `source/qemu-sony-native.patch` 的官方 QEMU 11.1.2** 转成原 GPIO18 stage 接受的 CP 硬件基板。外部源码输入只有固定 QEMU archive；运行所需固件资产继续由产品的官方 `BODYDATA.DAT` 导入流程提供。`source-origins.json` 中的研究路径只说明代码出处，构建与 staging 不读取这些路径。

当前交付只经过源码比较与文件 SHA256 读回。**新 stager、测试、configure、编译和 VM 均未执行**；主会话统一回归后才能采纳。`full_boot_verified`、物理兼容和成片均保持 false。

## 独立构建入口

在产品根目录，未来需要构建时使用以下命令；本轮没有执行它们：

```sh
bash build-cp-native.sh --help
bash build-cp-native.sh source/vendor/qemu-11.1.2.tar.xz source/build/cp-native-new
```

`NEW_OUTPUT` 必须是本产品 `source/build/` 下未存在的新目录，当前用户所有，路径无符号链接，位于 `/tmp` 之外。预检要求可用空间至少 **80 GiB = 4 GiB source + 12 GiB build + 64 GiB reserve**；无法取得空间数据即拒绝。失败保留输出、日志、恢复源与 `storage.json`，不自动删除现场，也不复用已有输出。

脚本只使用已安装的 Python（含 `tarfile.data_filter`）、Bash、bubblewrap、patch、ninja、C 编译器、make、flex、bison、pkg-config，以及 GTK3、SDL2、pixman、glib、libseccomp 开发文件。DTC 来自产品已固定清单的 `source/dtc/`。不安装依赖、不下载、不 clone、不运行测试或 QEMU；configure/ninja 在断网且仅新输出目录可写的 bwrap 环境中运行。

实际构建顺序是：官方 archive → 原 native patch → `stage-platform.py` → `stage.py` → `stage-notify.py` → `stage-peripherals.py` → configure → `ninja -j2 qemu-system-aarch64`。

产物是 `NEW_OUTPUT/tree/build-cp/qemu-system-aarch64`，旁边的 `cp-notify-build.json` 记录二进制、platform/GPIO18/notify/peripherals 各级收据与完整最终源清单。脚本调用 child `validate_receipt(shape, inherited)` 和 `check-notify-qemu.py::contract(..., require_peripherals=True)` 做文件身份核验；不会调用该检查文件的 qtest/VM main。产品默认窗口入口和默认 binary 不变。

## 最小范围与精确基板

| 操作 | 文件 | 内容 |
| --- | --- | --- |
| 补丁 | `hw/core/null-machine.c` | SMP 上限 4、GIC-400、定时器、watchdog、eDMA gate/legacy direct engine、诊断 OOM RAM |
| 补丁 | `hw/{dma,misc,watchdog}/meson.build` | 仅追加下列三个 runtime C 文件引用 |
| 补丁 | `hw/timer/sony_hwtimer.c` | 只包含相对 native patch 的 CP 严格访问/capture 拒绝差异 |
| 新 C | `hw/dma/sony_cp_edma.c` | 保留原 direct local-RAM legacy 模型以维持基板身份；native child 另选新 eDMA |
| 新 C | `hw/misc/sony_cp_edma_gate.c` | low16 enable/IRQ gate |
| 新 C | `hw/watchdog/sony_cxd_wdt.c` | QOM 类型 `sony-cp-wdt`，原 reset-mode watchdog/SCU 语义 |

GPIO18 与通知模型由既有子阶段追加，不混入平台补丁。原 AP `virt.c`、bus stub、SPAcc stub、input 与 GTK native patch 也不重复打包。研究 CP 树另有 camera-shell/GTK 改动，已比较并作为范围外差异记录；本移植不宣称复制该研究树的所有字节。

`target/arm` 的 `cntfrq` 属性已经在官方版本存在：`-cpu cortex-a53,cntfrq=2000000` 是可选运行参数，不改 CPU 默认频率。`MachineClass.default_ram_id = "ram"` 也已有官方原字节，不新增补丁。Meson 实际引用的是 `sony_cxd_wdt.c`，不存在需要另迁移的 `sony_cp_wdt.c`。

| 身份 | SHA256 |
| --- | --- |
| QEMU archive | `731b5681e4bb18be313231579b8efd0296c5b015fa36dc533874b639ba838016` |
| 原 native patch | `29a84ae7a23897af25279f3c438bef387a01d59137767e0362631d4c294f78f8` |
| 平台补丁 | `84b5740d41e930f3fba64679b4a0365704067648477e963cccd3bd4f5fa72baa` |
| GPIO18 之前的 `null-machine.c` | `8d4e4ab5863c5bd8408ba276f13c5f58b93bf1048750a68bb450e0fc4de06af3` |
| 原 GPIO18 收据 | `f7f94f364bd1509957d9b5aea8370dab2ae02fe874237efc0081a8728024be0d` |
| 冻结历史通知父收据 | `79041461b7b834ef3c1610bb98eff521574d567c5f789d5eb7d62b65b7d67c1e` |
| 干净生成的通知父收据 | `1efa461744f73cea3199f2dd14cd0b361608c9d0760e1e4b99069e732b618a14` |
| 冻结 legacy `notify-qemu.c` | `a7f4031567c724700420259ac5bcc3170349ed5a15f5e55fcbca0dada03ecda4` |

逐源 before/after、完整模型 SHA、未改上游文件、原 AP UI 范围外差异均在 [`source-origins.json`](source-origins.json)。未删改 legacy callback；child 将独立 `native-notify-qemu.c` 写到 `hw/gpio/notify-qemu.c`，构建入口遵守 child 的输出清单。

## Stager 的准入、幂等与恢复

单独 staging 的输入必须是新 native-patched 源树：

```sh
python3 -B source/cp-boot/stage-platform.py /project/owned/native-patched-qemu
```

stager 先验证固定源清单、native patch/manifest、所有 before 与未改源、所带 C 模型及后续 GPIO18/legacy notify 源 SHA；在内存中解析精确补丁，核全部预期 after。任一未知基准、部分已改源、额外占用目标、符号链接或 SHA 漂移都会在首次修改前拒绝。它先把五份将修改的原源保存并读回到 `cp-platform-before/`，再写输出，最后建立新的 `cp-platform-stage.json`。

同一级重复调用必须同时满足原 recipe、全部模型输入、完整收据、所有输出、未改源与备份 SHA。已经叠加 GPIO18/notify/child 的源树不再是本级 after，重新调用 platform 会拒绝；构建入口按依赖顺序只调用一次各级，不把此拒绝放宽成“已应用”。失败留下的备份或临时文件同样拒绝直接重用。

子stage明确接受两份完整父SHA：历史冻结收据 `79041461…`，以及当前冻结 `stage-notify.py` 干净生成的 `1efa4617…`。二者的硬件输出相同，历史收据另有旧失败出处字段。新的公共构建保留自己生成的父文件原字节，不复制历史 `source_update` 标签，也不覆盖旧收据。child 与运行准入均绑定本次实际父文件SHA；其它父版本拒绝，新链的实际执行仍待统一验证。

恢复材料是逐级 `*-before/` 和收据。需要回退时，先停止使用该树，按 child → notify → GPIO18 → platform 的逆序依据各级输出 SHA 核定当前内容、恢复原备份，并核对 before SHA；不要把 platform 备份直接覆盖到仍处于 child 状态的树。最简单的独立回退是保留现树和所有失败证据，改用另一个未存在的新输出重新构建；默认窗口 binary 从未被替换。

## 模型边界

GIC 在 `0xf13a1000/0xf13a2000`，512 INTID；四 timer 在 `0xf1042000 + i*0x1000`、INTID 413–416；watchdog 在 `0xf1052000`、原 SCU `0xf1388300`；eDMA gate 在 `0xf11e0274`、INTID 403，legacy engine 在 `0xf6780000`。这是既有显式功能模型，按对应 `QEMU_CP_*` 环境变量启用，默认不创建设备。

4 MHz timer/watchdog 时钟仅 nominal，未校准；timer capture/未知控制位拒绝。secure timer INTID30 仍是显式 hypothesis。watchdog IRQ 模式和 identification 寄存器未知；legacy eDMA 无 LLP、PCIe remap、STOP 与完整错误类型。OOM backing 的页对齐 padding 不证明物理 RAM alias。没有迁移/VM save-restore 支持承诺，也没有 AP↔CP/fullboot/成片验收。

[`../test_platform_port.py`](../test_platform_port.py) 只编写了固定清单、拒绝边界、原源备份、幂等与父文件原字节身份测试，本轮未运行。统一回归由主会话安排。

源码遵循所附 C 文件的 GPL-2.0-or-later 标识；原 QEMU 文件的版权保留在精确差异上下文及上游源码中。
