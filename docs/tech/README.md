# 从“别的机型起不来”开始：逆向与仿真工程笔记

这组笔记解决如何把启动故障拆成可观测、可验证的小步骤，不提供可套用到其他机型的硬件地址或完整拍摄实现。

## 阅读前先定范围

对象是 Sony ILCE-7CM2（A7C II）2.01 ALLLANG 的本机隔离 QEMU 项目。
方法来自仓库已有报告与源码；本次整理没有启动 QEMU、连接 GDB、编译或执行测试。
未接触设备、网络、设备私有 setting 或 full/private 输入。
文档仅记录路径、结构、地址、摘要和结论，不附 Sony 固件、字体、镜像或 dump。

本包目前有原厂首设、640×480 HUD/MENU、部分输入、虚拟 SD 和有限配置恢复证据。
取景区域仍黑；CMOS、完整镜头/AF、照片和录像没有通过。
“主界面出现”与“相机能够拍摄”是不同的大步骤。

## 先约定目录和命令

在工作区根目录设置以下变量；`$W` 随你自己的 checkout 位置变化：

```bash
# 执行目录：含 final/ 的工作区根目录
W="$PWD"
PKG="$W/final/a7c2-qemu"
NATIVE="$W/final/a7c2-re/report/2026-10-17-qemu-native-camera"
FULL="$W/final/a7c2-re/report/2026-10-17-qemu-full-system"
```

`$PKG` 是独立包，`$NATIVE` 是研究报告与后续调查，`$FULL` 是另一条系统路线。
只有本包 checkout 时，用 `PKG="$PWD"`，先读本包 README 与 validation。
本组指向研究报告的相对链接需要完整工作区；独立分发本包时可能不可达。
研究运行目录、历史截图和日志默认不随源码发布，不能假定读者已经拥有。

代码块分为三类：只读查阅、以后自行开展实验时的准备命令、历史观测思路。
后两类不是本次已执行的命令；涉及固件输入时只能用自己合法持有的普通文件。
不要把路径变量换成 `/dev/...`，不要把这些仿真步骤搬到真实相机执行。

## 整体推进路线：大步骤及其小步骤

### 大步骤 1：固定输入，让内核先到 shell

读 [启动资产](boot-assets.md)。

1. 确认型号、版本、区域、原包 SHA，而不是只看文件名。
2. 分清 DAT/FDAT、分区镜像、原 initrd 与实验 cpio。
3. 核内核、DTB、initrd 的实际装载关系和 bootargs。
4. 到 shell 后再按依赖加载原模块与相机程序。
5. 用包外路径隔离对照检查隐藏的旧目录依赖。

### 大步骤 2：先证明观察工具可信

读 [地址与调试](debugging-playbook.md)。

1. 把 fileoff、ELF VA、分析器地址、运行基址分别记录。
2. 核第二 PT_LOAD、Ghidra 偏移和 CP ARM/Thumb。
3. 只读捕获真实调用、写点、对象生命周期。
4. 清断点、detach，再独立确认 CPU 恢复。
5. 记录采样上限和失败，避免把“没看见”当成“不存在”。

这个步骤应在第一次读业务状态前完成，之后每个大步骤都要复用。

### 大步骤 3：从黑屏追到第一份可信像素

读 [显示与首帧](display-first-pixels.md)。

1. 分开检查生命周期、绘图、资源解码和输出消费。
2. 核 RGBA4444、小端像素、alpha 和 stride。
3. 真正解 Sony LZ77，而不是对缺失设备返回成功。
4. 在位图有效租期内提交不可变帧。
5. 比较 AP 帧、显示桥和唯一 GTK 画布。

### 大步骤 4：输入进入原消费者并产生合理变化

读 [输入](input.md)。

1. 分开原始键、重映射枚举、业务事件。
2. 区分短按、拨轮增量和档位位置。
3. 用原接收记录与 LCD 变化校准映射。
4. 定位日期确定键等“输入成功、业务断言”的问题。
5. 发现异常后停输入，保留最初故障。

### 大步骤 5：先恢复存储，再验安全插拔

读 [存储](storage.md)。

1. 用原 Fsys 的文件后端证明写入和重挂读回。
2. 补原 RM 查询、通知和掩码选择。
3. 关联消息 owner、原 free、Unmount/Mount 与 generation。
4. 区分在卡 Flush 与拔出后的 retirement 导出。
5. 用整卡、文件内容和 fsck 分别证明不同层。

### 大步骤 6：从“参数变了”追到跨进程恢复

读 [配置持久化](settings-persistence.md)。

1. 对齐原 getter、SID/属性和 Backup 文件。
2. 证明同步真正进入保存，而不是只看返回 0。
3. 校验双 bank、目标记录与完整导出。
4. 用实例租约、不可变代和 CAS 发布。
5. 在新进程、新 VM 中验证原 API 读回。

### 大步骤 7：把隔离链路按协议做通

读 [网络](network.md)。

1. 证明原 USB 网卡驱动绑定。
2. 核 stream 长度前缀、MAC、IP/ICMP checksum。
3. 分别证明宿主和 guest 实际收到应答。
4. 同 VM 做 ON/OFF/ON 与新 nonce 负对照。
5. 保持 USB 以太网与 Wi-Fi 扫描、关联虚拟 AP 的验收边界；后者放到最后单独推进。

### 大步骤 8：提示只是起点，反查真正业务状态

读 [媒体与容量](media-state-and-capacity.md)。

1. 捕获最终选择规则和消息 ID。
2. 区分属性基值、有效值、setter 与校验器。
3. 单独证明名字目录编号和分发表键是否相同。
4. 先构造合法容量输入，再记录业务结果。
5. 对准备失败、OOM、业务拒绝分别下结论。

### 大步骤 9：补齐实际成像、编码与保存合同

读 [成像与录像](imaging-and-recording.md)。

1. 从原消费者反推帧描述符及像素来源。
2. 闭合 lens/AF/AE、buffer lease、freshness 与完成。
3. 证明编码 receiver 实际消费和输出有效长度。
4. 进入原 MPR/Fsys 保存与完成回调。
5. 最后才验照片或录像文件；这一步目前仍未完成。

## 通用启动排查清单

以下都来自项目实际遇到的问题；右栏是不能外推的范围。

| 检查层 | 本项目实际有效的做法 | 局限 |
| --- | --- | --- |
| 原资产 | 固定身份、大小、SHA、源码固定资产清单 | 只支持已核 2.01 ALLLANG |
| 工具链 | 分开宿主工具和 Sony glibc 2.25 guest ABI | 宿主链接通过不保证 guest 可加载 |
| 内核 | 核实际串口 command line 和执行标记 | shell 不证明相机应用启动 |
| DTB | 修改 chosen/initrd 描述并保留预留区 | A7C II 地址不适用于其他板 |
| initramfs | 区分 ext2 原 initrd 和生成 cpio | 大镜像解包仍受 guest RAM 限制 |
| 根文件系统 | 原依赖顺序、guest 链接与执行权限检查 | 文件存在不等于服务可用 |
| 串口 | 完整日志、唯一 RC 标记、跨块异常监视 | 混入日志会污染数据导出 |
| 首帧 | 真正执行绘图、解码、带租期复制 | AP OSD 不是 CMOS 图像 |
| 最小可观测面 | run 身份、输入清单、console、原返回、内容摘要 | 单个 ready/成功码不能代替终点 |
| 退出 | 调试恢复、原存储屏障、导出、owner 恢复 | 清理成功不能把业务失败改成成功 |

## 每个小步骤怎样记账

按各篇的“问题 → 现象 → 误判 → 定位 → 解决 → 剩余”记录。
一次只改变一个明确变量；必须同时改变交付形式时，写出混杂因素。
先自证探针、输入和开关实际生效，再讨论阴性结果。
原失败运行保持原样，另写复核结论，不覆盖总体 false。
区分代码已实现、宿主夹具通过、原 guest 消费、最终功能通过。

主机生成的测试数据可验证通路，不能冒充原固件拍摄。
空 ACK、假 ready、裸写业务字段都不能作为推进业务的捷径。
实际踩过的遗留强写和修复见媒体篇；它说明适配器本身也必须被观察。

## 证据入口与版本顺序

- [本包说明](../../README.md) 与 [本包验收](../../validation/README.md)：独立包实际范围。
- [研究 README](../../../a7c2-re/report/2026-10-17-qemu-native-camera/README.md) 与 [STATUS](../../../a7c2-re/report/2026-10-17-qemu-native-camera/STATUS.md)：研究基线及历史纠正。
- [九项验收](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/nine-feature-acceptance.md)：按功能看剩余合同。
- [完整系统状态](../../../a7c2-re/report/2026-10-17-qemu-full-system/STATUS.md)：只作独立路线对照。

报告通常保留旧失败和旧“待验”；先看“最新结果/更正”，再读过程。
同一篇旧段落里写过“根因已定”，不能跳过后续撤回说明。
本组各篇列出具体证据入口，不把 native/full 的运行结果混成本包的新运行。

## 本次文档收尾的六条事实回核

这里只做源文档/源码回读，未重跑原实验，未把既有结果称为本次动态验证。

| 抽核事实 | 回核原文/源码 | 处理 |
| --- | --- | --- |
| 两个语言字体大小/SHA | `runtime/analysis/language_fonts.py::FONT_SPECS` | 只保留路径、大小和摘要 |
| RGBA4444小端及B/G/R输出 | `runtime/analysis/ramfb-viewer.c::convert` | 明确是软件模型 |
| Thumb ADR16相对寻址 | native `report/cp-barrier-static-correction.md` | 不抄反汇编相对量作绝对地址 |
| opcode9 mask1筛R0、实际通知改R1 | native `report/sd-hotplug-progress.md` | 只称本模型配置修复 |
| Backup bank尺寸/起点及WriteComp低字节 | native `report/backup-noop-sync-contract.md` | 不猜高位或全部SID语义 |
| dispatch1052值域与PP黑电平转接 | native `report/media-producer-frontier/README.md` | 撤回媒体容量标签；所有目录派生媒体标签均需另证 |

新增镜头/像素合同只补静态几何、字段和容量检查边界，不计完整快照或像素实测。
CMOS字节/位顺序、plane、freshness/lease、全配置及虚拟AP扫描/关联仍未核为完成。

## 如果你在做别的机型

优先搬走分层、地址换算、内容校验、所有权和失败记账方法。
重新推导内存图、服务 ID、输入码、资源格式和原配置结构。
不要只放宽 A7C II 导入器的型号限制就声称支持新机型。
从第一个尚无内容证据的小步骤开始，每次只争取闭合一条边。
