# 启动流程 12 · 横切：地址校准与只读观测纪律

本篇不属于某一步，而是贯穿启动全程的纪律：读任何业务状态之前先固定身份和地址，
观测时证明读到的是本次活对象，结束后独立确认 CPU 恢复。

变量见[索引](README.md)。本次只回读源码与报告，没有连接任何调试端点。

**10 月 31 日状态**：完整研究批次 9070 tests / 10006 subtests 与独立内容读回通过；对原 run64 的新内容复核仍 INCOMPLETE，阻塞在控制记录/精确内核尾注分帧和研究工具所需的原模块只读验证。最新原运行的严格收尾通过，原正式 capture/graph FAIL 与无媒体结果保留。详见[当前进度](2026-10-31-current-progress.md)和[摘要](../../validation/2026-10-31-progress.json)；下文第 9 节保留 10 月 29 日的等待与退出问题，不将其当作最新运行结论。

先声明边界：观测不是零干扰。入口探针会改装载中的代码，GDB 硬件断点会暂停 CPU，
首写观察会显式延迟初始化。所以"定位证据"不等于"功能恢复"，
本页也不提供改寄存器、改内存、调 setter 的捷径。

## 1. 先固定文件身份，再谈地址

任何地址笔记之前先记原件的路径、大小、SHA256
（已核 `appFw.so` 为 99960744 B，SHA256
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`）。
`qemu-menu-probe.py` 每次启动前把源码、观测器、关键库的摘要写进
`runtime-manifest.json`，并用 `initramfs_identity.verify_image`
核对**实际打进 cpio 的字节**——源码里有 trace 不代表 guest 装的是它。

观测器自身先自证（`check-menu-observe`、`menu-regs --selftest`、
readmem 正负对照），结果只证明工具合同，不证明相机初始化完成。

```bash
# 执行目录：$PKG；对已导入的自有 ELF 只读查阅
cd "$PKG"
readelf -lW runtime/analysis/menu-root/usr/lib/appFw.so
sha256sum runtime/analysis/menu-root/usr/lib/appFw.so
```

## 2. 四种地址坐标系，逐段换算

同一个十六进制数可能是 fileoff、ELF VA、分析器地址、运行地址。换算按段表：

```text
若 p_vaddr <= VA < p_vaddr + p_filesz：
    fileoff = p_offset + (VA - p_vaddr)
运行地址 = 已核装载偏移 + ELF VA
超出 p_filesz 的区域（BSS）没有对应文件字节。
```

已核锚点：appFw 第二 `PT_LOAD` 为 `vaddr=0x51b7718, off=0x51a7718`，
这段满足 `VA = fileoff + 0x10000`，属性表 `0x5584c38` 必须按此映射。

踩过的坑：把第二段 VA 当文件偏移，曾导致"appFw 未建屏"的误判；
旧测试和被测字典共用同一份错偏移"互证通过"。
`+0x10000` 只描述这份原件的这一段，不外推。

另一个读回纪律：`menu-readmem` 返回码 0 不保证读满——**非零短读也返回 0**，
必须核对实际长度。

## 3. 反编译器地址先归一，再核原字节

Ghidra 语料的 image-base delta 是 `0x100000`：`FUN_0313d400` 对应 ELF VA
`0x303d400`，归一后再按段查文件。不要把它和第二段的 `0x10000` 混加。
语料不是原厂源码：间接调用、缺参数、函数边界都要回原字节核——
曾把地址落到的字符串桩当函数。

## 4. CP 镜像：先核 ARM/Thumb 边界

`cpapp-b.bin`（18090880 B）混有 ARM 启动码、Thumb、文本和数据，
全库线性解码会产生假函数。本镜像用 `CPVA = raw + 0x108000`；
Thumb 指针的 bit0 与指令地址分开处理。
已核的 ADR16 例子：`CPVA 0x3642d0`（raw `0x25c2d0`）的 `03 a1`，
目标 = Align(指令地址 + 4, 4) + imm8×4 = `0x3642e0`——
反汇编显示的 `#0xc` 是相对量，不能当绝对地址抄。

历史教训（全部撤回过）：把 `0x1109230` 起的 Gamma 曲线指针矩阵
（每条 1025 个非递减 u32）当成字符串偏移表；把防尘 barrier
（已核局部只有设置/一致性校验）当成成像启动屏障。
"数值加猜的基址偶然落到字符串"不构成寻址证据。

## 5. 停点读对象：绑定线程、调用帧和生命周期

指针值相同不代表还是同一实例。观测要同时记录 run、原 ELF 身份、
ASLR base、caller、线程和原调用帧；在构造后关联对象，在析构或
原 owner 释放时结束关联，不同址复用对象续接。

踩过的坑：漏掉合法分支后把"没命中中间 PC"说成 manager 阻塞；
把 free/计数清零当成业务完成。硬断暂停 CPU 会改变时序，
定位结论还需要无调试的独立复验。

## 6. 写观察找作者：先 baseline，再看谁写

运行时异常值可能来自模拟器自己。做法：先在原初始化入口
（`Application_System_Init`，核过 12B 原指令）读 baseline，
再设硬件写观察记录原 PC/LR。

实际案例：照片媒体字段 `appFw+0x7e6e7f0` 从 0 变 1，
写后 PC 不在 appFw 而在自研 observer 的 `plane_config_send`——
是遗留的 `KEY_GATE_OVERRIDE` 把业务字段误当按键门。
修复是移除全部七项业务裸写；**删除错误强写不等于成像恢复**，
REC 提示的变化另行记账。禁止用断点改值"验证"业务。

## 7. 收尾：删断点、detach、独立确认 CPU 恢复

调试器退出不保证 guest 继续执行。流程：删除自己创建的断点 → detach →
用独立私有 QMP 通道查 `query-status`，只允许对 `debug/paused` 发 `cont`，
再查一次确认 `running=true`。CPU 确认先于快照、存储导出和 GUI teardown。

注意：QMP 的 CPU running 和 guest Fsys owner 的 STOP/CONT 是两层状态，
不能互相代替。恢复不明时保留 VM、租约和现场，错误退出——
不强杀持卡进程制造"已退出"。

## 8. 阴性结果按有界结论记账

每次观测保存完整 console、探针身份、启用标记、entry/return 配对数和
终止原因。要分清：墙钟截止、事件上限、读取错误、观察期内未命中——
"没看见"不等于"不存在"（前 64 KiB 日志曾漏掉注册；源码有 trace
但库没重建也曾制造假阴性）。入口 ready 只表示探针布置完成，
不能叫相机 ready。

## 9. 历史后台初始化与退出证据（截至 10 月 29 日）

2026-10-29 最新完整基线为`unified-camera-4b3kb4kd`：5568 tests /7057 subtests、host/guest构建与双原glibc2.25 ABI通过。BEGIN、同锁唯一snapshot ID、真实receive/free ticket、cache128/readback128和退休后下一周期source绑定已纳本批；集中1051项通过，native内容checker的严格join也已接入。旧1KiB日志预算失败和随后strlen声明构建失败分别保留，新批通过不回填旧记录。原AP/SDK新VM及成片仍未验。

最新 `run-qqu0q5oe` 的两条SP锚定保存FP链与原LR−4 BL字节互证：Common382等待本地21 future，串行CameraBackground339先被24B/CP3006/source810261c4回复等待占住。只看最后一包或时序相邻不能得到这个结论；裸send拒绝会遗失原request/动态queue，不能作为修复。功能owner需要真实同轮13边原free、debugger交接、实际Core INIT/STATE128与缓存读回，再释放原request并发独立回复；只有原sender receive/free0才是transport消费，不等于原物理CP业务ready。

清理结果分开记录：

- runner/broker生命周期：该轮broker从未attach，runner closed/safe。
- 进程状态：独立检查时本项目系统QEMU已无，不干预无关项目实例。
- 存储：原Flush0、两数据库文件导出及宿主SHA读回通过，卷退休/格式化未通过。
- 退出方式：`host-sd-quit-error` 留有 `write to closed file`，普通QMP quit未获独立证明。进程absence不能补证退出方法，也不能把该错误抹去。

内容checker必须消费实际producer记录，严格join同run/source/owner/model/generation/nonce/lease/snapshot与真实字节，缺观察则拒证。HOST_TEST支持夹具不能提升native/AP/UI/capture；原输出日志若截断、缺行或无法唯一关联，同样保留失败。见[完整进度](2026-10-29-current-progress.md)与[原生负例摘要](../../validation/2026-10-29-progress.json)。

## 证据入口

- [当前阶段、内容检查器阻塞与原生边界](2026-10-31-current-progress.md)。
- [本包历史媒体访问器与首写纠正](../../validation/README.md#媒体只读诊断访问器层修正)。
- [地址/资产身份](01-firmware-assets.md)与[当前首启判据](04-app-and-first-setup.md)。

## 如果你在做别的机型

`+0x10000`、`+0x100000`、`+0x108000` 分属三个坐标系，都要重核。
可复用的是证据顺序：原件身份 → 段映射 → 原指令 → 现场对象 → 独立清理。
硬件断点和被动 trace 是定位手段；改状态是另一个实验，别混写成只读观察。
