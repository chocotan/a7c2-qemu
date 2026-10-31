# 图像源与显示配置的当前进展

最新综合状态见[10 月 31 日进展](2026-10-31-current-progress.md)。下文保留 10 月 30 日源码移交及其验证范围；后续研究已核对历史同次运行的三份 AP 源数据共 514304 B、功能 CP 独立读回和原 callback 返回，最近原运行仍无 JPG/MP4。

本次源码更新补齐原 SDK 图像源读取和模式尾部的显示位宽配置。运行代码、ABI、构建归档依赖、桥接、profile 与正式内容检查器已经一起移交；公开包的实际 host 测试结果记录在[发布收据](../../validation/2026-10-30-publication.json)。**仍没有由原厂程序拍下并保存、独立解码通过的 JPG 或 MP4。**

| 功能 | 已实现的范围 | 继续未验证 |
| --- | --- | --- |
| 原 API40 图像源 | 绑定原请求及分配，完整读取真实 AP 源字节，分块保存、功能 CP 写入/全量读回、退租后原 callback | 原全局 writer 排除、物理 DMA/ASIC、原 CP RAM/RTOS、通用反复上传 |
| 015e 显示位宽 | selector0 的软件 RGB888 策略；真实 Core render/sink/读回/retire；完整168B回执和独立115e生命周期 | 原 selector0 的物理位深、下层f039效果；研究主线已实际消费015e，后继异常仍待恢复 |
| 原按键与快门观察 | 保留原输入路由，新增全按入口四个有宽度/读错误记录的只读门值 | 原 branch 实值、全按后的原 JPEG/MPR 请求提交与完整拍摄 |
| 成片与硬件 | 内容检查继续要求原 AP、CMOS、编码、原 MPR/Fsys、虚拟卡与独立解码整链 | `capture_verified=false`，物理 ASIC 兼容性仍 false |

这些增量属于显式的 `virtual-functional-camera-v1` 功能模型，默认启动器和原严格 profile 的选择没有扩大。已有菜单、虚拟 SD、有限设置等功能继续按[验证记录](../../validation/README.md)各自的范围理解。现有截图保留为本项目实际启动窗口，没有用主机生成媒体代替相机成片。

实现与可直接运行的 host 复现入口：

- [原 AP 图像源读取](../../report/functional-face-source-snapshot/README.md)
- [显示位宽、RGB 消费和原回复](../../report/disp-bit-width/README.md)
- [本包源码与第三方许可](../../SOURCES.md)

10 月 30 日移交未运行新 VM、原 Sony ARM ABI 测试或 GUI 验收。当时研究主线另报告原015e已经实际经历OP12/class7/168B、RGB读回、原request释放、独立成功115e与原sender receive/free；随后在首次设置的教程阶段出现`SeqQueueCommon`异常，尚未进入自然全按或原codec提交。该有限结果属于研究主线，不是本包新跑的native验收，也不证明完整首启或拍摄恢复。研究源冻结身份与本包host结果继续分别记录，旧失败不回填。
