# 虚拟 CMOS 帧源

实际原厂HUD上的虚拟CMOS预览见[UI截图](../../docs/images/virtual-cmos-ui-hud-20261120.png)和[实跑收据](../../validation/virtual-cmos-ui-preview-20261120.json)。它由guest RAMFB消费者在原OSD透明层后合成，并直接经QMP截图；显式使用 `MENU_VIRTUAL_PREVIEW=functional-cmos-chart-v1`。LCD预览640×480与照片7008×4672使用同一确定性色卡场景，原CP/YC传帧和物理ISP尚未验证。

拍摄功能模型在 640×480 和 7008×4672 尺寸默认从本模块取得 Bayer 采样，再解马赛克为 RGB；不需要设置 `A7C2_VIRTUAL_CMOS_PROFILE`。该默认值属于拍摄功能模型，默认 `./start.sh` 的原厂窗口拍摄接线仍未完成。

本模块生成自产色卡：18 个彩色色块、6 级灰阶、深色间隔和两条细节方格。两条黑白横带是输入场景的细节测试目标，用于观察离焦、Bayer还原和压缩效果，不是写卡产生的坏行。它不使用第三方图片或商用色卡的测量数据，也不是色彩校准目标。两个尺寸通过整数坐标缩放使用同一场景，再按各自像素的 GRBG CFA 选择通道；RGB 必须由这些 Bayer 样本解码，RAW采样与 RGB 共享源。传感器模型的14位样本左移两位保存在 `uint16_t` 中；最终ARW按原厂描述符保存14位有效值于LE uint16容器，不能把模型的内部表示当作文件布局。它是软件功能模型，不代表原厂 CMOS、ISP 或内部总线。

[![33MP虚拟CMOS色卡的600×400缩小预览（宿主模型生成）](../../docs/images/virtual-cmos-color-chart-preview.png)](../../docs/images/virtual-cmos-color-chart.png)

[完整色卡PNG](../../docs/images/virtual-cmos-color-chart.png)尺寸恰为7008×4672，由 [`render_preview.py`](render_preview.py) 调用真实 `sensor_config_parse("7008x4672")` 和 `sensor_frame_rgb`，直接采样全尺寸GRBG Bayer后解码生成，不是640×480放大。图片本体无附加标注画布，来源保存在PNG元数据中；上方600×400预览从同一33MP图缩小。二者均为宿主生成，并非原厂程序写卡成片。历史写卡收据继续引用原样本，替换场景不会追溯改变旧证据。复现时将 `TMPDIR` 指向本项目任务目录后执行该脚本；脚本自检全尺寸、代表色块、保存读回像素及来源元数据，并自动回收临时编译库。见[本次生成收据](../../validation/33mp-color-chart-20261120.json)。

- `sensor_config_parse(NULL, ...)`：640×480；`"7008x4672"`：显式全像素配置；未知配置拒绝。
- `sensor_token_next` / `sensor_token_valid`：绑定配置代次与非零帧序号；序号耗尽返回 0，调用方需切换配置代次。
- `sensor_frame_bayer_into` / `sensor_frame_bayer`：采样帧，容量以样本数计算。
- `sensor_demosaic_rgb` / `sensor_frame_rgb`：按实际 GRBG 邻域生成 RGB24。
- `sensor_downsample`：整数方框降采样；调用方释放返回缓冲。

`../virtual-optics/optics.c` 是拍摄渲染消费者，`../../runtime/analysis/build-functional-camera-model.py` 将该模块编入模型并封存源码归档。`A7C2_VIRTUAL_CMOS_PROFILE=legacy-checker` 仅用于旧图案对照。

本批检查由 `test_sensor_core.py` 覆盖采样值、CFA 边界、代次、短缓冲拒绝与默认光学消费者：两线程集中验收共2582项通过。第107轮原厂程序实际消费默认CMOS帧，生成640×480 JPEG并写入虚拟卡，原文件读回、双整卡导出和独立解码均已核实；见[同轮收据](../../validation/default-cmos-runtime-20261120.json)。归档脚本误标模型路径的原失败独立保留，没有将整个后处理流程改记通过。

`test_sensor_core.py` 新增两个尺寸下的原始 CFA 色彩、RGB 色块、灰阶及边界验证；光学默认合同仍核对焦点模糊、曝光、步长、代次和 FNV。这些宿主检查与以下原厂运行结果分开记账。

## 原厂未压缩RAW写卡结果

![卡内原ARW经独立LibRaw解码后的900×600预览](../../docs/images/captured-raw-dsc00001-20261120.png)

此图来自第117轮 `48b4` 原虚拟卡内的 `DSC00001.ARW`，由LibRaw完整解码为7008×4672 RGB后缩小，非上方宿主色卡重绘。原菜单RAW-only／L／UNCOMPRESS与自然 `0x4038` 进入原 `libarw`→Fsys，提交、回调、完成及返回均成功。文件67,223,552B，`Compression=1`、14位GRBG、Bayer区65,482,752B；两次1GiB整卡导出一致，卡内全文摘要一致，独立 `raw-identify`／`dcraw_emu` 均返回0。见[公开收据](../../validation/33mp-uncompressed-raw-runtime-20261120.json)和[拍摄调查报告](../functional-camera-evidence/p1-candidate184.md)。

host/guest自定义运输层的无损RLE将98,224,128B RGB压至2,527,401B，guest还原后交给原厂消费者；它只加速工具之间搬运，不改变像素或最终ARW的UNCOMPRESS格式，也不证明原机采用压缩总线。

第117轮写卡后的适配器清理报 `-EPROTO`，旧失败保留；QMP退出已确认，但资源退休仍未验，`capture_verified=false`。后续生命周期源码修复待主会话统一回归与新实跑。默认窗口拍摄接线、真实CP/ISP/物理CMOS、RAW＋JPEG、其他RAW压缩模式及录像尚未由本轮验证；显式软件预览已有上方独立收据，不能据此提升原视频通路。
