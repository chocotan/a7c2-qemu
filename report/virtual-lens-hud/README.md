# 拍摄主画面底部快门/光圈/ISO 虚拟镜头 HUD 显示

## 现象与根因

此前在默认 `./start.sh`（`original-init-cold` / `direct-bootin`）以及 `virtual-cmos-ui-hud-20261120.png` 中，拍摄主画面（`scr0132_0001_presenter`）顶部和两侧图标正常显示，但底部曝光信息栏（快门速度、光圈、ISO）完全空白，原因由两部分叠加：

1. **A7C II 原厂 AP/CP 双平面拆分（主要遮蔽原因）**：
   - `appFw.so`（SHA256 `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`）中，`view_mp_shutter_speed`（`0x181d05c`，`x=57, y=445`）、`view_mp_aperture`（`0x181b660`，`x=199, y=445`）和 `view_mp_iso_sensitivity`（`0x181ca04`，`x=421, y=441`）均自带完整的 AP 端 `view_text`/`view_icon` 绘制实现。
   - 在 ILCE-7CM2（`model_index=25`）上，`0x1797dbc()` 读取 `0x370e728[25] == 0`（`!= 1`），导致 `translator_mp_aperture`（`0x23dc2c4`）、`translator_mp_shutter_speed`（`0x23dc6bc`）和 `translator_mp_iso_sensitivity`（`0x23e7880`）均将 `param.use_cp_mp_draw`（对象偏移 `+0x2b8` / `+0x2c1`）置为 `1`，期望由物理 CP ASIC 的硬件 MP-OSD 平面（通过 `0x8280074d` `CpWidget` 与 `mp_distributor`）绘制底部曝光栏。
   - 因此三个 `view_mp_*` 控件在 AP 侧直接提前返回，即便模型有值也不在 AP OSD 上绘制（连 `--` / `F--` 也不出现）。
2. **默认启动路径缺少 CP 镜头/曝光状态通知**：
   - 默认 `./start.sh` 启动后，`appFw.so` 的 `0x80020002` 接收线程未收到来自 `0x90030001` 的 `type=6` 镜头与曝光通知（`0x2044` 挂载镜头、`0x201b` 光圈、`0x200e` 快门、`0x2036` ISO），导致初始 `shutter num=0 den=0`（`view_mp_shutter_speed::0x181ce10` 在分子为 0 时隐藏控件）且 `aperture_x100=0xffff`。

## 实现方案

- 新增软件虚拟镜头/曝光编码模块 [`virtual-lens-hud.h`](../../runtime/analysis/device-models/virtual-lens-hud.h) / [`virtual-lens-hud.c`](../../runtime/analysis/device-models/virtual-lens-hud.c)，按已核原厂 `appFw.so` 解析器布局编码 4 条 `type=6` 通知（`source=0x90030001` → `dest=0x80020002`）：
  - `0x2044`（`0xa0`B，`0x351fdb8` → Event `0x7a`）：虚拟已挂载镜头（`"Virtual 35mm F4.0"`，`state=1`）
  - `0x201b`（`0x14`B，`0x3531ba0` → Event `0x99`）：光圈 `F4.0`（`400`，范围 `400..1600`）
  - `0x200e`（`0x28`B，`0x35190c0` → Event `0x26`）：快门 `1/125`（`1/125`，范围 `1/4000..30/1`）
  - `0x2036`（`0x0c`B，`0x3521310` → Event `0x25`）：ISO `100`（CP 字节 `0x0b` → AP 枚举 `5`）
- 在 [`menu-observe.c`](../../runtime/analysis/menu-observe.c) 中增加 `MENU_VIRTUAL_LENS_HUD=1` 支持：
  - 通过逐条指令校验的 `arm_entry_probe` 挂接 `view_mp_aperture`（`0x181b660`）、`view_mp_shutter_speed`（`0x181d05c`）和 `view_mp_iso_sensitivity`（`0x181ca04`），仅清除各自 `use_cp_mp_draw` 标志（`+0x2b8` / `+0x2c1`），完全交由 `appFw.so` 原厂控件在 AP OSD 上绘制。
  - 在非严格 CP 证据 profile（`!functional_camera_enabled && !cp_owned_state_enabled`）下，通过真实 OSAL 队列向 `0x80020002` 发送上述 4 条通知，并输出 `VIRTUAL_LENS_HUD_ARMED` / `VIRTUAL_LENS_HUD_PUBLISHED` / `VIRTUAL_LENS_HUD_WIDGET` 诊断记录。
- 在 [`original_cold_boot.py`](../../runtime/analysis/original_cold_boot.py)、[`start-menu.py`](../../runtime/analysis/start-menu.py)（可用 `A7C2_VIRTUAL_LENS_HUD=0` 关闭）及 [`qemu-menu-probe.py`](../../runtime/analysis/qemu-menu-probe.py) 中默认启用 `MENU_VIRTUAL_LENS_HUD=1`。

## 验证结果

- 主机单测（ASan/UBSan + `appFw.so` 原指令字节核验 + 启动器环境校验）：[`test_virtual_lens_hud.py`](../../runtime/analysis/test_virtual_lens_hud.py) 通过。
- 隔离 QEMU 冷启动实测（`tools/run-original-cold.py --cold-flag force --no-verify-sha`）：`ORIGINAL_COLD_RESULT True`，QMP `screendump` 拍摄主画面底部已原厂样式显示 `1/125`、`F4.0`、`ISO AUTO`（`i📷` 自动档），切换 `M`/`A`/`S`/`P` 模式后同步显示 `±0.0` 及对应原厂模式选框（实拍截图见 [`docs/images/virtual-lens-exposure-hud-20261121.png`](../../docs/images/virtual-lens-exposure-hud-20261121.png)）。

## 边界说明

- 本实现为软件虚拟镜头/曝光状态发布与 AP 端原厂 HUD 控件渲染，不模拟物理 E-mount 串口或物理 CP ASIC。
- 拍摄模式切换与前拨轮焦点高亮（如 M 档转动前拨轮将 `F4.0` 框置橙）由原厂 UI 响应；拨轮对 CP 曝光参数的闭环步进仍依赖完整 EE/CP 曝光控制链。
