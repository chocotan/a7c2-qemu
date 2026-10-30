# 显示位宽配置与真实 RGB 消费

原模式切换尾部的 `200d:015e` 已接入既有 VDF owner。功能模型完成真实 RGB 帧消费、独立读回和退租后，才释放原请求并发送独立 `115e`。**本包本次只执行 host 组件与内容检查测试，没有新增 VM 验收；原厂拍照录像和物理 ASIC 兼容性仍未验证。**

## 软件策略与原回复

原业务类为 `VDF::VdfDisplayCmdSetLineValidBitWidth`，原请求的 selector 是一个 byte。物理 selector 的位深含义及下层 `f039` 的真实效果尚未闭合。本功能 profile 明确定义 **selector 0 = 软件 RGB888、每个 R/G/B 分量八位**；这不表示 Sony 物理 selector 0 就是八位。其它 selector 继续拒绝。

原成功回复使用转换后的 `0x00590000`，不是全零状态：

| 边界 | 完整内容 |
| --- | --- |
| 原请求 | 10B：`0d205e010a0001800000`；destination `92840747`，source 保留该次完整动态 AP 值 |
| 功能请求 | OP12、Input8 全零；必须已有 INIT 和 active 640×480、stride1920 的 RGB 路由 |
| 实际工作 | 获取并 render 光学帧 → 独立 sink 复制所有 921600 字节 → 逐字节/FNV 读回 → retire → 独立保存并读回 Config8 → 提交 |
| 功能结果 | 168B、class7、token0；末尾八字节为该次保存配置的完整读回；config/frame 代次各增一 |
| 原成功回复 | 独立 12B：`0d205e110c00018000005900` |
| AP 消费条件 | 原 request free0 → 独立回复分配/读回/send0 → 原 sender 实际 receive → 同线程本轮 ticket/free0 |

相同配置重复请求也必须实际消费一帧。旧 Config48 的尺寸、FPS、曝光、镜头配置、显示与 BB bank 和直方图保持。输入错误、未知 selector、部分配置、busy、活动录像、待取编码结果、损坏回执或失败释放均不能以成功 ACK 跳过。已发生的真实帧阶段计数会保留，不回滚成“没有执行”。

共享字段与精确策略见 [functional-vdf-bit-width-abi.h](../../runtime/analysis/functional-vdf-bit-width-abi.h)。Core、Guest bridge、VDF owner、host broker、profile 和正式内容检查器使用同一合同。模型构建的源归档也包含该 header。

## 复现宿主测试

从本仓库根目录执行；需要既有 C 编译器、pytest、libjpeg 和 FFmpeg 开发库：

```bash
python3 -B tools/test-public-models.py -k 'bit_width or functional_camera_bridge or functional_vdf_broker or functional_vdf_wiring'
```

测试包含严格 C11 与 ASan/UBSan、真实 Core + Guest owner 组合、完整 168B 独立 golden、软件 bank 隔离，以及 header/长度/selector/回执/代次/线程/ticket/free/send 的故障场景。传输与 OSAL 使用 host fixture，测试不执行 Sony 程序、不启动 VM，也不产生相机照片。

正式 [内容检查器](../functional-camera-evidence/check_evidence.py) 还要求原请求与保留 payload 文件、同实例实际 Core proof、五条生命周期记录及完整原 ACK 字节逐项匹配。独立 ACK 正确只是一个必要条件。

## 证据与剩余边界

| Evidence | Finding | Path |
| --- | --- | --- |
| E-width-code：共享 ABI、Core、bridge、owner 与正式检查器；身份见 `SOURCE-SHA256SUMS` | F-width-policy：selector0 的八位含义限于本软件 RGB 模型，物理枚举仍未知 | P-width：原015e → OP12 → 实际 RGB sink → retire/Config8读回 → 原 request free → 独立115e → 原 sender receive/free |
| E-width-tests：上述公开 host 命令与严格/消毒构建的逐字节、故障和生命周期检查 | F-width-host：组件内容链可在 host 验证；研究主线另已报告原015e链实际消费，本包仍未新跑VM，后继首启异常待恢复 | P-width-check：生产 Core + owner → 完整168B oracle → 真实分配/释放 fixture → 内容检查拒绝缺证 |

本次实际结果见 [公开发布验证](../../validation/2026-10-30-publication.json)，研究冻结来源见 `SOURCE-ORIGINS.json::display_source_port`。旧模式尾部等待实验的正式失败结论保留；本次代码不能把旧运行改成成功。快门入口的四个新增只读门值是非原子观察，不是原 branch 的实际取值，也未证明与该等待的因果关系。

最终成片仍须原 AP 触发、真实虚拟 CMOS、编码消费、原 MPR/Fsys 写虚拟 SD，以及完整读回与独立 JPEG/MP4 解码；`capture_verified=false`、`physical_ASIC_verified=false`。
