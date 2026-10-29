# 2026-10-29 当前进度：功能模型已推进，原固件 JPG/MP4 尚未贯通

**当前仍不能完成原固件拍照或录像，`capture_verified=false`。** 最近完整通过的研究代码批次为 `unified-camera-4b3kb4kd`：**5568 tests /7057 subtests、176模块、445份运行源/945项唯一输入，host/guest构建与双原glibc2.25 ABI通过**。已包含后台3006、完整首启与BEGIN/snapshot/ticket/cache128修补；集中1051项也通过。公开包路径与host范围另行验证，原生AP/SDK和成片链仍须新VM验收。`run-qqu0q5oe`使用的旧4693/5740批次及其失败身份保持不变。

本页是公开进度快照，按功能、阶段和剩余证据整理；不是重新执行实验的收据。它只覆盖设备所有者授权的本机隔离 QEMU 与普通虚拟卡文件，不接真实相机、物理 SD 或射频设备。固件输入仍限自有 2.01 ALLLANG；完整系统 dump 路线的结果不并入此包的官方更新包资产范围。

## 当前功能矩阵

| 能力 | 已核实范围 | 当前边界 |
| --- | --- | --- |
| 官方包导入、内核与原应用启动 | 固定 ALLLANG 身份、资产摘要、实际 initramfs；原 bootin/im 启动 | 不分发原固件、字体、seed 二进制或私有配置 |
| 原 LCD、菜单与输入 | 原 640×480 OSD；既有默认 profile 的 HUD/MENU 和主要按键、拨盘有短时限定证据 | 全部按键、长期主界面稳定性和最新功能 profile 的完整首启尚未验收 |
| 首设语言 | 最新 `run-qqu0q5oe` 的 24 步简中选择实际等待 LCD 变化与稳定 | 温度确认模态曾被误作 shooting；不能仅凭 controller `0x343` 放行快门 |
| 虚拟 SD | 原 Mount/Flush、数据库/XML 写入、既有热插拔及跨运行读回 | 最新轮只有两份数据库文件；卷退休、原固件格式化与媒体成片均未通过 |
| 配置恢复 | 语言、日期格式有限参数跨进程恢复及实例代数发布 | 首设完成状态、全部设置覆盖尚未闭合 |
| 虚拟 CMOS、镜头、AF | 明示 RGB888 总线上的实际像素、软件光学、对比度 AF 及编码核心有组件证据 | 原 AP 的 retained frame / producer / lease 仍未与整条拍摄链闭合；原实时取景与真实合焦未验 |
| VDF 图像消费 | 较早原生运行实际完成六个 VDF 周期；每帧 640×480×3 = 921600B，经独立 sink 比对与退休 | 配置/传输消费不代表原 UI 已显示场景或已经拍照；最新 qqu 未到 VDF |
| 软件时钟与初始 BB | State128 FPS→单帧能力 `(fps,1)`，默认 30/1；精确原 0166 初值已纳入软件 identity | 不推断 Sony 物理参数单位；pgf 旧误拒与其失败保持原记录 |
| 首个 enabled/mode1 直方图 | 真实 core→guest 组合 268 项通过；同帧 RGB 的软件 Y/R/G/B 四段各 256 个 u8 柱高逐字节一致，peak=255 | 原 AP/UI 应用、连续更新与物理 bins 语义均未通过 |
| JPEG 主图与缩略图 | Main/MainComp、实际 reply-free、EXIF 同文件内容检查及可读内存边界已有组件验证 | 原 AP→源帧→SDK→encoder→MPR/Fsys→SD 尚未贯通；没有原 JPG |
| Movie | 实际 H.264/packet 核心、原参数/异步传输/ring 合同和同步写观察已有实现与组件证据 | 初始 extent、实际 source/ring 消费、Combine 最终 MP4 与 FSYS_SYNC 内容仍缺；没有原 MP4 |
| 网络/蓝牙依赖 | 隔离 USB 以太网既有验收；显式非射频虚拟 HCI 保留原 BSA 与真实 controller backing | 不代表 Wi-Fi 关联、完整蓝牙或最新功能 profile 稳定；HCI已入当前整批host验证，其并用最新功能profile的原管理连接仍待综合VM |

用户已于 2026-10-28 选择功能模拟优先，独立 profile 为 `virtual-functional-camera-v1`。软件 RGB888 图像总线及虚拟设备政策可以明确规定；严格 profile 保留其原拒绝策略。**物理 ASIC 兼容、原 CP 模块/RAM/RTOS 历史、原硬件 ready 都保持未验证**。组件实际生成/解码 JPEG 或 H.264 只验证模型；不能把主机单独生成的媒体当作原固件拍摄。

## 分阶段时间线

| 阶段 | 实际推进 | 保留的失败与限制 |
| --- | --- | --- |
| 10-17～10-25：启动与基础功能 | 官方包导入、原 LCD/MENU/主要输入、虚拟卡、有限设置恢复；默认主界面有短时操作证据 | 取景黑、无照片/视频；完整首设状态与长期稳定未验 |
| 10-26～10-27：原控制/图连接 | 同轮 13 条图连接的原消息与消费；控制、帧描述符、编码和原 MPR/Fsys 合同逐层查清 | 图连接/ACK 不能替代像素与成片；完整物理 CP 启动仍缺证据 |
| 10-28：功能 profile | 实际光学/RGB/AF/JPEG/H.264 核心、bridge/broker、低 32 位内存及原 codec 适配；原生 VDF 首次真实消费 RGB | 多轮整批/构建/运行失败按当轮保留，不由修复回填 |
| 10-29：`run-52od7asp` | 原 0141 global/source 精确绑定，实际值 `80946189`；独立 1141 receive/free；六个 VDF 周期 | mode1 ACK 与 1748B 通知已原 free，随后 20a6 `(0,0)` 转换 fatal；无 JPEG/MP4 |
| 10-29：`run-pgf891an` | 实际软件时钟 30/1、六 VDF 加原 0111 | 原 0166 的 `0,0,8,7,1,1` 初值被 neutral-only 策略误拒；已修代码，旧失败不改 |
| 10-29：`run-to9olvu1` | 暴露语言自动化仅等 host submission、未等原 LCD | 语言选择失败，未进入 0166 复测；已修逐键画面消费，不能说该轮成像失败 |
| 10-29：完整基线与 `run-qqu0q5oe` | 4693/5740、构建/双 ABI 通过后原生运行；24 步简中选择及两数据库导出读回 | 温度模态误作 shooting；原系统错误早于 S2；当前未到 3003/VDF/codec，仍无媒体 |
| 10-29：后续完整批次 | 首启、后台3006、实际Core/原收发和内容记录集中修复；新5568/7057全量、构建与双ABI通过 | 旧日志预算与首轮strlen声明构建失败留证；新综合VM/原固件成片待验 |

测试项、子测试与C场景分别计数，不相加；4693/5740和4260/2838保留为较早完整批次。最新研究ready SHA为`d6738e0ce424a0df58df94d72a1613ac5a3ee21696041dd64110282a8a0b901b`，其scope仍要求native端到端验收。

## 最新原生失败定位

`run-qqu0q5oe` 的原 proof 为 `ok=false`，自动化返回 0 不能覆盖它。标作 `shooting-after-setup` 的图像实际是温度设置确认模态。系统错误屏幕 `0x30c` 的创建记录早于自然快门 S2 提交，因此不能说快门导致系统错误；首个错误 producer 尚未唯一确定。

原栈采用两条 SP 锚定连续保存 FP 链，并核对原 ELF 的 LR−4 BL 字节：Common382 等待 `339fa08→3548c20→local 0x21 future`；串行 CameraBackground339 已先停在原 24B `CP3006` 的动态队列回复等待，source 为 `810261c4`。本地 21 回复因此排在该等待之后。直接让 send 返回 ENOTSUP 会遗失原 request/动态队列，也不保证终结 local21，不能部署为修复。

该轮原 Fsys Flush=0，两个数据库文件的导出 SHA 已由宿主实际读回核对，但 `original_volume_retirement=false`、`firmware_format_verified=false`。runner 在 broker 从未 attach 的情况下 closed/safe；独立检查时本项目系统 QEMU 已无。另保留 `host-sd-quit-error` 的 `write to closed file`，**该轮普通 QMP quit 方式未独立证明**，不把进程 absence 当作退出方式证据。

## 后续组件批次的准确状态

- 完整首启修复：75 tests / 139 subtests 与 4 个直接调用方通过。真实 press/release 后等待 LCD 变化且稳定，按原手机页 DELETE、reader/温度页实际取消；当前 HUD/controller 和教程收尾共同成立才 ready，系统错误禁止注入快门。尚需新原生完整首启复验。
- 后台 3006 owner：已验证版本有 **694 个实际 Core 测试**，包含 strict C11 与 ASan/UBSan。原请求保留 pending，直到同轮 13 连接原 free 及 debugger 交接后，才执行真实 Core INIT/STATE128、同实例缓存完整读回，再原 request free、独立 12B reply、原 sender receive/free。它只证明功能初始化/传输，不证明原物理 CP 模块或 local21/UI 已自然推进。
- 接线组已记录 249 项（其中新增 143）、真实 Core+Control 混合组合 6 项、profile/HCI 100 项定向结果；这些范围与 694 及旧 4693 **不能混作新全量通过**。
- 退休后新source、真实BEGIN、同锁唯一snapshot ID、真实receive/free ticket、完整cache128/readback128和native console镜像已经修复，严格checker按实际记录join；集中1051项与完整5568/7057、构建/双ABI均通过。旧日志夹具1KiB假上限及strlen声明构建失败保留；这不提升原生AP或capture。

## JPG 下一步需要闭合什么

1. 新整批自测、host/guest构建与双原glibc2.25 ABI已通过；发布校验完成后，用新虚拟空卡和本批intent做一次综合原生运行，不逐按钮或opcode启VM。
2. 验证完整首启与原后台 3006 真实消费，观察原 local21 自然返回；系统错误未消除前不执行快门。
3. 从原 AP 的实际 producer 接到 retained RGB source，闭合 SDK frame MainP、key104a 的 128B writer、真正 ResizeEnc1500 cmd2 与 1006/event9 自然 producer；输入 metadata SDS 不能当像素指针。
4. 由原 Main/MainComp 实际请求触发模型消费同帧数据，核原 reply receive/free、输出 lease、原长度写回；Main/Thumb 当前各自 render，跨 selector 同一 sensor frame 尚未证明。
5. 由原 MPR/Fsys 完成请求、callback/worker、原文件 readback、两次 SD 导出及宿主 SHA/独立解码，把真实帧内容与最终 JPG 相连。录像另验 extent/ring、自然 Stop/Close、Combine 与 FSYS_SYNC。

JPEG 仍涉及源帧、原 SDK、编码和文件系统多个环节，不能简化成补一个保存 API；没有确定完成时间。

## 证据与复现入口

本快照的机器可读摘要、完整基线产物 SHA 与最新负例边界见 [进度摘要](../../validation/2026-10-29-progress.json)。来源为已核的 native `STATUS.md` 首段、`2026-10-27-unified-camera/CURRENT-BLOCKERS.md` 首段、功能集成交接首段，以及 `functional-camera-core`、`functional-camera-control`、`functional-vdf-path`、`functional-histogram`、`functional-jpeg-codec`、`functional-background-start`、`functional-camera-evidence`、`native-card-write` 组件说明。后续公开报告中的同名文件可供细查；本页的结论不依赖工作区外链或私有运行目录。

| Evidence | Finding | Path / 下一核验 |
| --- | --- | --- |
| E-baseline：进度摘要中的ready/observer/model SHA、5568/7057及冻结数量 | F-baseline：新完整研究基线通过，限该冻结批次；high，原生仍待验 | 本批输入→host/SAN→构建→双ABI；发布路径/host scope单独验证 |
| E-native：进度摘要中 qqu 的原 proof、两份画面 hash、FP/BL 等待链及卡文件 SHA | F-native：语言消费通过，主界面/媒体失败；high，有界原生结论 | 原 3006 等待→串行 local21 阻塞；修复后需新 run |
| E-components：上述组件说明中的实际 Core/编码/lease 与定向测试 | F-components：实现与局部消费有证据，整机 capture 未验；high，限组件 | 软件帧→原 SDK→原 MPR/Fsys→SD/独立解码仍需同轮关联 |

独立 checkout 的既有依赖/来源检查入口如下。本次文档任务没有运行这些程序、构建或启动 VM；完整研究回归与本包受限 host suite 的结果分别记账。

```bash
# 在 a7c2-qemu 仓库根目录执行
./tools/check-host.sh
python3 tools/check-source.py
python3 tools/test-host.py
```

实际启动与自有固件准备沿用 [主 README](../../README.md#如何启动)，首设判据见 [04](04-app-and-first-setup.md)，成像细节见 [11](11-imaging-frontier.md)，存储与退出分界见 [07](07-storage.md) / [12](12-debugging.md)。此页不新增启动参数或强制通过开关。

公开交付只含软件、可公开 ALLLANG 来源 hash 与 source pins、有限正/负收据；不含原固件、私有 Setting、完整 dump、原 seed 二进制、临时日志或宿主绝对路径。当前 `capture_verified=false`。
