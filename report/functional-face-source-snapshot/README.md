# 原 AP 图像源的功能读取

本组件把原 SDK 的 API40 请求接到显式的 `paused-source-snapshot-v1` 软件图像总线。它读取同一请求对应的完整 AP 源数据，写入功能 CP 缓冲区并完整读回，完成退租后才调用原回调。**这不是 Sony 物理 DMA/ASIC 的实现，也没有证明原厂程序已拍出照片或视频；`capture_verified=false`。**

## 请求如何完成

运行代码位于包内 `runtime/analysis/`，无需相邻研究仓：

| 环节 | 实现与条件 |
| --- | --- |
| 原请求绑定 | `menu-observe.c` 验证调用位置、原 API40 全部字节、两个描述符、原分配记录、PID/TID、单元和长度。无法绑定时保留原 SDK 的返回行为。 |
| 所有权 | `functional-face-{dmm,registry,runtime,ap-observer,native-ap,proc,sdk,transfer}.c` 保存分配、打开、共享、原消息 receive/free 与回调顺序；成功码不能代替实际内容。 |
| 完整源读取 | `functional-face-source-snapshot.c` 与 `functional_face_source_snapshot.py` 使用 OP11。在协调暂停窗口中复核原请求、CPU 地址空间及 winning RAM row，再对完整范围读取两遍并比较字节。 |
| 别名拒绝 | 源范围、CP 页、SDK 页和邮箱页必须在可确定的 RAM 映射中互不重叠；未知映射、I/O、跨 region 或无法排除的 backing 别名均拒绝。 |
| 分块与退租 | 源结果使用独立的高位 token 空间。每块绑定原请求和实际顺序，完整重组后比较全量 SHA/FNV；最终 release 必须覆盖全部字节。不能回落到 Core 生成图像。 |
| CP 消费与回调 | Guest 把真实源字节写入已登记的功能 CP 缓冲区，完整读回比较；源和目标退租成功后才进入原回调。已接管后的失败保留原栈帧与故障原因，交给既有 owner 收尾。 |

支持单元为 `0x1d9`、`0x1da`、`0x1db`，大小分别为 409600、51200、53504 字节。此实现只处理每个单元的一次初始化传输；未承诺后续反复上传或动态复用。

暂停窗口只证明这次 CPU 地址空间下的完整读取与保存内容。两遍相同不证明原全局 writer 已停止，不证明真实硬件 DMA、原子性、原 CP RAM/RTOS 或物理 backing 对象的身份。相关验证标志始终为 false。

## 复现宿主测试

从本仓库根目录执行；需要既有 C 编译器、pytest、libjpeg 和 FFmpeg 开发库，不启动 VM：

```bash
python3 -B tools/test-public-models.py -k 'face or source_snapshot'
```

该入口允许严格 C11 和 ASan/UBSan 编译，禁止 QEMU、bubblewrap 和 VM 启动器。新增测试直接提取生产入口或链接生产 C 模块，只有原 SDK、OSAL、内存读取和主机传输边界使用明确的 host fixture。原 Sony ABI 链接、原件窗口验证和未分发的历史运行重放按范围跳过。测试产物写入被忽略的临时目录，不随源码发布。

## 内容证据如何判定

正式离线检查器为 [check_face_source.py](../functional-camera-evidence/check_face_source.py)，由 [check_evidence.py](../functional-camera-evidence/check_evidence.py) 调用。它连接本轮原请求、完整源读取、暂停/恢复回执、保留的分块内容、功能 CP 全量读回、原 callback 及清理记录。缺一个环节就拒绝或报告缺证，不凭 ACK、日志标签或相同摘要独自宣布完成。

| Evidence | Finding | Path |
| --- | --- | --- |
| E-source-code：上述生产 C/Python 与 `SOURCE-SHA256SUMS` | F-source-model：完整读取、分块、读回与退租具有明确的软件合同；物理映射语义未证明 | P-source：原 API40 → 绑定分配及请求 → OP11 完整读取 → 分块传输 → CP 读回 → 双侧退租 → 原 callback |
| E-source-tests：上述公开 host 命令、真实生产代码的成功及故障用例 | F-source-check：host 可验证字节、顺序、错误保留及 scope 拒绝；不能由此提升原 AP 或 capture 状态 | P-source-check：host fixture → 实际模块 → 正式内容检查 → 缺证/篡改拒绝 |

本次发布的实际执行范围见 [验证收据](../../validation/2026-10-30-publication.json)。源研究的冻结批次身份保留在 `SOURCE-ORIGINS.json::display_source_port`，与本包自己执行的 host 测试分开。原厂固件、私有设置、原始运行日志及源数据均不随包分发。
