# 虚拟 CMOS 帧源

拍摄功能模型在 640×480 尺寸默认从本模块取得 Bayer 采样，再解马赛克为 RGB；不需要设置 `A7C2_VIRTUAL_CMOS_PROFILE`。该默认值属于拍摄功能模型，默认 `./start.sh` 的原厂窗口拍摄接线仍未完成。

本模块生成确定性的 GRBG 测试图案：14 位样本左移两位保存在 `uint16_t` 中。它是软件功能模型，不代表原厂 CMOS、ISP 或 Sony ARW 的物理格式。

- `sensor_config_parse(NULL, ...)`：640×480；`"7008x4672"`：显式全像素配置；未知配置拒绝。
- `sensor_token_next` / `sensor_token_valid`：绑定配置代次与非零帧序号；序号耗尽返回 0，调用方需切换配置代次。
- `sensor_frame_bayer_into` / `sensor_frame_bayer`：采样帧，容量以样本数计算。
- `sensor_demosaic_rgb` / `sensor_frame_rgb`：按实际 GRBG 邻域生成 RGB24。
- `sensor_downsample`：整数方框降采样；调用方释放返回缓冲。

`../virtual-optics/optics.c` 是拍摄渲染消费者，`../../runtime/analysis/build-functional-camera-model.py` 将该模块编入模型并封存源码归档。`A7C2_VIRTUAL_CMOS_PROFILE=legacy-checker` 仅用于旧图案对照。

本批检查由 `test_sensor_core.py` 覆盖采样值、CFA 边界、代次、短缓冲拒绝与默认光学消费者：两线程集中验收共2582项通过。第107轮原厂程序实际消费默认CMOS帧，生成640×480 JPEG并写入虚拟卡，原文件读回、双整卡导出和独立解码均已核实；见[同轮收据](../../validation/default-cmos-runtime-20261120.json)。归档脚本误标模型路径的原失败独立保留，没有将整个后处理流程改记通过。

7008×4672 仅是帧源能力：当前拍摄传输仍受 64MiB 结果缓冲和原厂 640×480 格式事务限制。RAW 写卡、实时取景、录像及物理兼容性尚未验证。
