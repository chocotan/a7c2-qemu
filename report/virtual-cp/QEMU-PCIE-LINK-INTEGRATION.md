# QEMU PCIe Link-Up Integration (Task #80 phase 2) — PARTIAL, BUILD NOT YET RUN

Status: source integration applied; **compile not yet verified**; derived DTB **not yet generated**; no guest run attempted (out of scope).

## What was applied

Working tree: `source/build/qemu-pcidma-work/qemu-11.1.2` (qemu-11.1.2 + native/usb patches + phase-1 PCI DMA engine).

1. **Model files copied** from `report/virtual-pcidma/candidate-mw33q1n1/qemu-11.1.2/hw/misc/sony-pcidma/` into the working tree's `hw/misc/sony-pcidma/`:
   `qemu_phy_init.c`, `test_pcie_peer.c`, `ccf.c/h`, `phy_clear_job.c/h`, `phy_calib.c/h`, `phy_sram.c/h` (10 files). The engine files (`sony_pcidma.c`, `registers.c/h`, `lli.c/h`) were already present. Copied set is self-contained (only QEMU headers + its own headers); it does not depend on `scu.c`, `test_pcie_scu.c`, `test_ccf_scu.c`, `test_root_dbi.c`, or `qemu_phy_sram.c`, so those were not copied.

2. **`hw/misc/meson.build`**: the existing `CONFIG_ARM_VIRT` line was extended to add `test_pcie_peer.c ccf.c phy_sram.c phy_clear_job.c qemu_phy_init.c phy_calib.c`.

3. **`hw/arm/virt.c`**:
   - Added `#include "hw/pci/pci_bridge.h"` (pci_bus.h was already included).
   - Extended the existing `if (g_getenv("QEMU_SONY_PCIDMA"))` block (same env gate as phase 1; default OFF, menu machine unchanged) to create, in order:
     - `pcie-root-port` at `PCI_DEVFN(1,0)` (chassis 1, slot 1) on `vms->bus` (the GPEX host from the existing `create_pcie(vms)`);
     - `a7c2-test-pcie-peer` endpoint at DEVFN(0,0) on the port's secondary bus, with a 16 MiB RAM BAR (`memory` link) and a host observation alias at `0x600000000`;
     - the phase-1 `sony-virtual-pcidma` engine (unchanged: MMIO `0xf7380000` prio 2, `pci-memory` -> `vms->bus->address_space_mem`, IRQ GIC SPI 166);
     - `a7c2-test-scu-phy-init` with `port`/`peer` links set **before** realize, then its 13 MMIO windows mapped exactly as the candidate: SCU/CCF `0xf1388000 0xf1388300 0xf11e0380 0xf1160380 0xf11a0380 0xf1220380 0xf1120380` (prio 4), plus `0xf11c0000, 0xf11e0384, 0xf7000000 (DBI, prio 1), 0x602000000 (PHY SRAM upload), 0xdffc0000, 0xdffd0000 (ATU, prio 5)`.
   - Unlike the candidate (which splits SCU creation before `create_pcie` and defers realize), everything is created in the single post-`create_pcie` block because the port/peer links exist by then; ordering is equivalent.

## How to enable

`QEMU_SONY_PCIDMA=1` (any value) at qemu launch. Unset = byte-identical default menu machine.

## DTB derivation (PENDING — commands verified against run_probe.py but not executed)

The menu probe uses `runtime/analysis/qemu-virt-board/virt-packed.dtb` (override via `MENU_DTB`). Derive the link-up DTB with the same mechanism as the validated candidate runs (`report/virtual-dma330/dma330-probe/run_probe.py` lines ~321-331):

```python
# base   = runtime/analysis/qemu-virt-board/virt-packed.dtb
# official = runtime/analysis/unpacked/firmware.tar_unpacked/0800_appli/setting/cxd90057.dtb
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location('iomap_board',
    'report/virtual-pcidma/iomap_board.py')
board = importlib.util.module_from_spec(spec); spec.loader.exec_module(board)
board.prepare(pathlib.Path(base), pathlib.Path('<new-output.dtb>'),
              pathlib.Path(official),
              all_pcie_wrappers=False, ccf_provider=True,
              phy_upload=True, dma_window=True)
```

This adds: 5 `sony-test-iomap-N` windows (0xf1056000/0x2000, 0xf11c0000/0x40000, 0xf7000000/0x1000, 0xf7300000/0x1000, 0xf7380000/0x2000), syscon `sony-test-scu` (clock-controller + rst phandles), `sony-test-ccf-consumer`, and `sony-test-pcie0` (copy of official `/soc/pcie_i`, status=okay, clocks/resets re-phandled to the test SCU, interrupt-map remapped to GIC SPI 166, MEM range widened to 32 MiB). Boot with `MENU_DTB=<new-output.dtb>`.

## Build (PENDING)

Not yet run. Planned: acquire `flock runtime/analysis/.menu-probe.lock`, reuse `build-qemu.sh`'s bwrap configure args, build only `aarch64-softmmu/qemu-system-aarch64` in `source/build/qemu-pcidma-work/build`.

## Verified vs pending

- Verified: file copies (hashes match candidate sources at copy time), property names in `qemu_phy_init.c` (`port`, `peer`) and `test_pcie_peer.c` (`memory`) match the virt.c wiring; candidate virt.c block faithfully ported.
- Pending: clean compile, derived DTB generation, guest link-up / `pcidma_enable()` / transfer (requires a guest run; explicitly out of scope for this phase).

## Risk / known limits

- If compile fails, likely suspects are minor API drift in the ported files (they were written against the same qemu-11.1.2, so risk is low).
- shortcut: DBI window priority (1) assumes no explicit ATU test device is co-enabled in this tree; the working tree has no `QEMU_SONY_ATU_TEST` path, so this is safe here.
# QEMU PCIe 链路集成（Task #80 阶段2/3）

（worker 调查 + main 落地编辑与构建；详见 QEMU-PCIDMA-INTEGRATION.md 的 probe 机制与 bwrap 更正）

## 集成内容（main 核 worker 编辑 + 自行构建验证）

menu QEMU（`source/build/qemu-pcidma-work`）集成完整 PCIe 链路，env 门控 `QEMU_SONY_PCIDMA`（默认 OFF）：
- GPEX host（create_pcie 已有）+ pcie-root-port DEVFN(1,0) + `a7c2-test-pcie-peer`（16MiB BAR）CP endpoint
- PCI DMA 引擎 `sony-virtual-pcidma` @0xf7380000、IRQ GIC SPI166（阶段1）
- `a7c2-test-scu-phy-init`（13 MMIO 窗口：SCU/CCF 时钟复位、PHY SRAM、lane 校准、LTSSM、DBI@0xf7000000、ATU）——candidate mw33q1n1 已验证拓扑
- 派生 `virt-pcidma.dtb`（iomap_board.prepare，含 sony-test-pcie0 节点+syscon），经 `MENU_DTB` 选用
- blacklist 解除 `__udif_init_pcidma`+`__udif_init_udif_pcie`；`QEMU_SONY_PCIDMA` 经 bwrap `--setenv` 传 QEMU（关键修正，否则设备不建）

## 验证结果（真实运行，诚实）

- **构建通过**（全部模型文件编入，3 设备注册）。**回归通过**（默认 menu 不回归）。
- **PCIe 链路起来了（重大里程碑）**：`dw-pcie f7000000.sony-test-pcie0: link up` + `PCI host bridge to bus 0000:00`——DW host 驱动 probe 派生 DTB 节点，对我的 SCU/PHY 模型跑 DBI/ATU/LTSSM，链路真实起来。
- **但崩在 pcie_clkreq_init+0x98** 访问 `0xf1160380`（SCU 时钟窗，模型 region 3 仅 4 字节）报 paging request。candidate 验证运行（native_soc0_host）**未**访问 0xf1160380——这是 menu boot 完整 probe 路径与 candidate 测试路径的真实分歧（candidate 未撞到的覆盖缺口）。**引擎使能未达成**（崩在 clkreq，未到 enable）。

## 下一调试点

pcie_clkreq_init 经 `udif_devio_virt(dev,ch)+GENERAL_SIGNAL_CTRL` 访问 0xf1160380；其有 `if(!srst_stat(dev,ch)) return;` 早退——menu boot 走了全程（srst_stat≠0）而 candidate 可能早退。需查：region 3 是否真被映射（QMP 内存树）、srst_stat 的 reset 状态分歧、访问尺寸是否超 4 字节。属迭代寄存器级调试。

## QMP 决定性诊断 + guest 侧定位（本轮）

**QMP `info mtree` 实证**：`0xf1160380-0xf1160383 (prio 4, i/o): test-phy-init-region3`——region 3 在 QEMU 侧**确实被映射**。崩溃 `Oops 96000007`（EC=0x25 数据中止，DFSC=0x07 翻译错误）是 **guest 侧页表/ioremap 问题，不是 QEMU 映射缺失，也不是模型拒绝**。QEMU 集成（设备建模+映射+链路）经 QMP 证明正确。

**guest 侧根因方向**：派生 DTB 只使能 channel 0（sony-test-pcie0 唯一 okay 节点），但 UDIF pcie 驱动（mach-cxd900xx/pcie.c，N_PCIE=5）**初始化全部 5 个 channel**——channel 1 的 `pcie_clkreq_init` 访问 PCIEPHY1（0xf1140000）+GENERAL_SIGNAL_CTRL（0x20380）=0xf1160380。candidate 验证运行（native_soc0_host）console 无 clkreq/0xf1160380 访问——candidate 对该 channel 走了 `srst_stat` 早退（reset 状态使其返回 0），menu boot 走了全程。分歧在 `srst_stat` 读的 reset 状态寄存器（`dev->chs[ch].clock.dclk.set`，来自 DTB syscon 的 clock/reset 配置）。

**下一调试点**：对比 menu 派生 DTB 与 candidate 派生 DTB 的 channel-1 clock/reset 配置（决定 srst_stat 的返回值），或对 channel 1 提供正确的 reset 状态使其早退（与 candidate 一致），或确认模型对 channel 1 的 GENERAL_SIGNAL_CTRL 窗口处理。属 guest 侧迭代调试。

## ✅ 完成（2026-10-22，menu 实跑闭环）

**menu QEMU 现带 PCIe 链路 + 可用 PCI DMA 引擎完整启动，并经原始 API 真实传输验证。**

### clkreq 崩溃根因与修复
- **根因**：menu 派生 DTB 只有 5 个窄测试 iomap 窗口（PL330/PCIEPHY0/PCIe 控制器/0xf7300000/PCIDMA），**不覆盖 PCIEPHY1（0xf1140000）**。UDIF pcie 驱动用**固定线性 IO 映射**（`IO_ADDRESS(phys)=0xfffffffff0000000|phys`，经 `arch/arm64/mm/mmu.c::map_io`（CONFIG_ARCH_EJ，`for_each_node_by_type("iomap")`）读 DTB iomap 节点建立）。PCIEPHY1 访问无法翻译→翻译错误（run-kxuqmsf4 崩）。candidate 从未撞到（测试客户端只触那 5 个窗口）。
- **修复**：`iomap_board.prepare(..., all_pcie_wrappers=True, ccf_provider=True, phy_upload=True, dma_window=True)` 重新派生 `virt-pcidma.dtb`（窗口 1 加宽为 0xf1100000+0x140000，覆盖全部 5 个 PCIe PHY）。sha `e7cacc5935...`。
- **关键运行条件**：bwrap `--clearenv` 下 `QEMU_SONY_PCIDMA` 必须经 `--setenv` 传入 QEMU（`qemu-kernel-probe.sh` pcidma_environment），否则引擎设备不创建。

### 验证（run-qjlrx49f / run-2ijfa8g0）
- 0 崩溃；`__udif_init_udif_pcie` + `__udif_init_pcidma` 均 returned 0；boot 完整到 menu（imaging 库 libJiritsu/StillPool/CameraStillDate 加载）。
- **run-2ijfa8g0 原 PCI DMA 真实传输 PASS**（pcidma-client `sony_pcidma_xfer.ko`，env 门控 `MENU_PCIDMA_XFER=1`）：
  - `NATIVE_PCIDMA_CONNECT: controller=0 connected=1 peer_bar=0xE0000000`
  - `NATIVE_PCIDMA_CALLBACK status=0 (write)` / `WRITE_DONE bytes=256` / `CALLBACK status=0 (read)`
  - `NATIVE_PCIDMA_PASS: write+read 256B via original APIs, callbacks status=0, data verified`
- 即 menu UI QEMU 里 **PCIe 链路 up + 引擎使能 + 256B AP→PCI→AP 原始 API 往返传输 + 数据验证**，全真实。

### 边界
- 验证的是单 256B 直传（pcidma-client），peer 为测试 endpoint（a7c2-test-pcie-peer）。LLI、大帧、真实 CP 业务经 pcie-if.ko 的 sender 未验。
- capture tap（sony_virtual_cp_send）仍是 tap 非真实 CP 应答；真实 CP sender（pcie-if.ko→pcidma）是下一步（虚拟 CP 完整化）。
- 默认 menu 回归 PASS。

**这是到 CMOS 的关键使能层：menu QEMU 现有了可用的 CP 互连（PCI DMA），虚拟 CP 可经真实 PCI DMA 路径做消息传输，进而接通 imaging 链（liro/帧）→ 拍照/录像。**
