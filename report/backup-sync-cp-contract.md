# Backup_sync_all：原 CP 请求、消费者与数据边界

接手入口：[2026-10-25交接文档](../HANDOFF-2026-10-25-BACKUP-STARTUP.md)，含运行状态、路径、复现命令和未完成项。

本报告记录原始字节、既有运行证据和 native 模型的接入条件。原固件 JPEG/MP4 仍未产出；本次接续时没有运行中的 VM。启动 loader 的数据选择与传输顺序已有静态证据，PCI 地址映射与实际 Backup DMA 尚未完成集成。范围沿用本项目 [AGENTS.md](../../../AGENTS.md)：本机隔离 QEMU、公开 ALLLANG 输入，原始资产只读。

## 运行时的实际等待

`run-00t3xfkx` 的 `AppBackupDaemon`（tid462）内核栈为：

```text
backup_get_cp_data+0x3c
Backup_sync_all+0x64
backup_osal_call_func+0x3cc
```

被动结果还显示 `BACKUP_SYNC_PENDING=1`，AppFw 在原条件变量上等待。原 `backup.ko`（ET_REL，以下地址均为 `.text+offset`）在 `0x3070` 调用 `backup_get_cp_data(3)`；helper `.text+0x1520` 调 `osal_rcv_msg_tmo`，超时为 `-1`。保存的返回地址落在这次调用的返回点，因此当前等待发生在**第一次 CP 请求的回复**，早于 CP-data DMA、文件保存和 SD flush。原始 `osal_snd_msg` 已走过返回0后的本地分支，但这不是 CP 消费证明。

原模块身份：backup.ko SHA256 `167715ebd8086b0751e95396ecc214c4d65ec54e11a9f2737a05664e03ad237b`。其 `Backup_sync_all` 只有在 `backup_get_cp_data` 返回0后才到 `.text+0x30e8/0x30f0` 的 `backupfile_save(1)`。

AppFw 的 daemon 调用点 `0x2ff0cf4` 随后直接回到公共分支，没有读取 `w0`；这不构成注入失败或成功来绕过的依据。失败返回会绕过原 `backupfile_save`，成功返回则还需要真实 CP 数据和后续 DMA，二者都不能由 daemon 的继续运行反推。

## 第一请求：目的地、字段与所有权

主会话重新读取了 helper 的原始跳表，而不是沿用未完成的转录。`.rodata+0x80` 的 entry7（opcode `0x30`）为192，所以 `.text+0x138c + 192*4 = .text+0x168c`。该分支将第三 个变参放入目的地修饰位；`backup_get_cp_data(3)` 的第三变参为1，因此：

```text
0x803e0811 | (1 << 28) = 0x903e0811
```

第一请求的主体分配为40B，原字段如下（动态 reply queue 除外）：

```text
+0x00  u32  0x30
+0x04  u32  0
+0x08  u32  0x903e0811       # destination/target1
+0x0c  u32  reply_queue      # osal_dynamic_id(0x2a,0x3e,...) 的结果
+0x10  u32  1
+0x14  u32  1                # ceil(40 / 4096)，原 helper 计算
+0x18  u32  1
+0x1c  u32  1
+0x20  u32  3                # 第一变参/同步阶段
+0x24  u32  0
```

helper 在 `.text+0x14e8` 设置源为动态 reply queue，`.text+0x14f4` 发送，随后 `.text+0x1520` 等待；收到后 `.text+0x154c` 读取回复 `+4` 并复制给调用者。第三变参只用于目的地 target1，不应误写成 `+0x20` 的参数。

原字节 `.text+0x12c0..0x12d0` 对40B计算块数1，`.text+0x13b0` 将它写到 `+0x14`；本次纠正先前转录的0。CP 接收循环则在 `0x55e48e/0x55e49a` **分配4096B回复**，在 `0x55e3d0/0x55e3d6` **复制4096B**，不是按40B请求尺寸分配/复制。后续适配必须核实原消息页容量、长度字段和所有权，不能在40B主机对象上照搬4096B读取。

`backup_get_cp_data` 随后还有独立阶段：`.text+0x2bec` 的 `backupfile_get_cp_data`，以及第二次 opcode `0x30`、参数 `(0,0,1)` 的交换。`backupfile_get_cp_data` 在 `.text+0x70bc` 调 `pcidma_transfer_async`，再等待其完成；不能把第一次回复或 DMA 排队返回0当成数据搬运完成。

第二请求是 `stage=0,arg1=0`，CP 执行解锁；第一请求的 `stage=3` 设置 primary header `+9=1`，随后锁定/cache，stage0不清该字节。AP 第一回复失败仍经 `.text+0x2c90` 进入 DMA，DMA 失败仍经 `0x2c74` 发送解锁，最终返回第二次回复状态。因此单独的 `Backup_sync_all` 返回0也不足以证明数据传输成功，必须核验实际字节、DMA IRQ/callback 和保存内容。

## CP 原始接收者和 opcode 0x30 分支

在原 `cpapp-b.bin` 中，CPVA 定义为 raw offset + `0x108000`。已定位：

- `0x55e3ac`：在 `0x003e0811` 上运行的接收循环；收到消息后调用 `0x55e08c`，再按原消息 `+0x0c` 的动态 queue 构造回复、发送并释放原消息。
- `0x55e08c`：原始 `0x27..0x34` 分派器。其 inline TBB 表的 opcode `0x30` 项为 `0x9e`，目标为 `0x55e20a`。
- `0x55e20a`：读取消息 `+0x20` 和 `+0x24`。当前请求的 `arg0=3,arg1=0` 走原 `Data_SetSuspendComp(1)`、backup 锁定、`Data_GetHeader`/`Data_getSize` 和 cache 操作路径，随后回到接收循环的回复发送路径。回复的状态位于消息 `+4`。

CP 的 `0xbe9bd4` getter 在参数 `1` 时直接返回当前 header 的 `+0x18 + +0x1c`；参数 `0` 才计算并检查后续 BK4。这与 AP `Data_getSize` 的 type 方向不同，因此这里的 CP size 可以描述当前 primary（与 AP 第二 bank 的1419512B相符），不能拿 AP 的 type1 语义误推 CP 必须再有第二个 bank。这是布局/尺寸线索，仍不是初始装载证明。

这证明了一个具体的原始消费者和其处理位置，不证明它在当前 QEMU 中执行。当前 CP core 并未运行；生产 UDATE 内核模块占用唯一 public-sender，非 UDATE 高地址消息仍保持原始无服务委托。因此不能把现有 `UNHANDLED` 或等待改写成 CP 成功，也不能再注册第二个 public sender 来“解决”冲突。

## 启动数据来源：静态链已定位，运行期映射仍待闭合

CP `Backup_init_cpapp` 的入口 `0x55dca4 -> 0x55dcc6 -> 0x55df9c` 绑定 `0x04000000` primary；初始化表中 `BACKUP_INIT` 前有 `PCIEIF_INIT`（callback `0x56a921`）。新增证据来自单独提供的 decoded boot0（基址 `0xfe040000`），不把该比较资产加入 ALLLANG 运行清单。

`Load Backup CP@0xfe04eea0` 经原 BK4 getter 取下一记录、两条记录的数据长度，绑定下一记录读取 `fa0006`，最后恢复 AP root 绑定。`Trans Backup CP@0xfe050630 -> 0xfe052fc0` 的调用顺序为：

| 顺序 | 来源 | 配置目标（尚须加 BAR 基址） | 长度 |
|---|---|---|---:|
| 1 | AP next `0x4040ed000` | `0x804000000` | `0x15a8f8` |
| 2 | 上一项目标指针 | mailbox `0x800107f18` | 8B |
| 3 | `BKUP` 标志 | mailbox `0x800107f10` | 4B |
| 4 | AP root `0x404000000` | `0x80415b000` | `0xec915` |

这些数值按公开 seed 原 getter 重算；AP next 保留高位，不能误写成 `0x40ed000`。`BKUP` 发布早于最后一段传输，不能由标志出现断言两段全部完成。传输包装也未逐次检查返回值。

**地址域必须分开：** 传输 primitive `0xfe05e24c` 把 PCI context `+0x58` 加到配置目标；初始化虽清零，BAR enumerator `0xfe05e5c0` 随后把首个有效 BAR 的分配基址写入该字段。因此发出的 PCI 地址是 `B + T`，不能预设 `B=0`。NOR 有64GiB BAR2/3配置，且其 EL3 页表对 `0x804000000` 为恒等映射；CP A32 bootstrap 对 `0x04000000` 也为恒等映射。两者不能由页表或数值低位相同推成同一 backing。

运行期 AP `backupfile_get_cp_data` 把 type1 记录首 word `0x04000000` 经 `arch_p32_to_p64` 转成 **PCI 源 `0x404000000`**，AP root 则在 **AP 本地物理 `0x404000000`**。这两块内存不可因数值相同而合并。仍需闭合 endpoint inbound/SoC 映射，或明确验证独立虚拟 PCI 数据后端的合同。

### 公开 seed 的条件初始内容

`Load Backup CP` 的15项读取位于第二记录绑定期间。`0xfe05b6c0` 只为已分配的副本建立32B链表节点，没有回写 BK4；`0xfe04f1c0` 恢复 root 绑定。

`backup_reset CP@0xfe04d2cc` 可在转发前调用原重置路径。原重置源为当前项数据后面的默认值，属性 `0x74` 决定适用项；属性bit7的重复项使用 `003e000c + 1` 份。公开值是**一字节 `0x0c`**，原函数先初始化32位临时区，再复制该字节，得到13份。重跑逐项比较得到：

| 记录 | 可重置项 | 其中重复项 | 与重置源不一致 |
|---|---:|---:|---:|
| AP root | 6608 | 2022 | 0 |
| 第二记录 | 32 | 2 | 0 |

两记录的 `00510052/00510053` 均为四字节0。故对**这份固定摘要的公开 seed**，已分析的加载副本和重置操作不改变第二记录字节，可作为显式条件初始 fixture；不能据此宣称运行时选中了它。`Switch Bkup` 的内存路径检查 cookie及write-complete字节，文件路径还在 `.bin/.bak` 间选择；公开 seed 的 `+8=0` 不证明原内存路径已被接受。未执行 boot0，也未向 CP shadow 或 AP root 写入这些数据。

对已保存的多份 `SETTING/Backup.bin` 做只读比较时，公开 seed 第二 bank SHA 为 `a90b46ae1d0fa054daeba321c52dc9d44d6bf32ca6eefcd1efb84fab2116e977`，常见保存值为 `84c4f1c633ec633ffc2e4481408bf80216e7e8900ff2a018f3970d67448d4d46`；逐字节差异仅为 `+9: 00→01` 与 `+0x20: 57→58`，payload 没有可证明的 CP 更新。这种文件 hash 差异不能作为 CP DMA 或启动装载证据。

## 已有 WBI 快照的限定检查

另只读检查了官方 WBI 重建内存 `analysis/evidence/wbi-snapshot/sony-build-memory.sparse` 及其 section 映射。它含有真实日志/格式串中的 `cp_backup` 和 Backup 符号，但原 CP `backup_async_recv`、`backup_osal_interchip_func`、`Backup_init_cpapp` 的精确指令序列未匹配，公开 Backup root/bank1 header 也未匹配；扫描到的若干 `BK4` 位置的 cookie/字段不合法或是字符串表，不能当作有效 BK4。真实日志中的 `cp_backup=0xffffff800a73d000` 也没有直接等同当前 CPVA 或初始数据地址的映射证据。

这些是该快照和匹配范围内的否定证据，不证明启动装载路径不存在，也不支持从 WBI 任意提取一块数据冒充 CP primary。

## 当前边界与下一步

- 已证：第一次回复等待、原请求和CP消费者、boot0记录选择与传输顺序、公开seed重置幂等性、BAR基址参与寻址。
- 未证：当前CP初始RAM与地址映射、Backup实际DMA/第二交换/保存、EE和固件JPEG/MP4。
- 原会话调查 `058147fc-6078-413`、`a9cf443d-f2ab-479`、`04b5f3dc-2cfc-4e9` 均已结束并取回；不再描述为运行中。
- native 的正常构建尚未包含该PCI DMA集成。但 [virtual-pcidma](virtual-pcidma/README.md) 已有独立候选的原API 256B双向数据/IRQ/callback验证，应复用它并检查大块传输、PCI独立backing、ATU和当前目录SD构建兼容性。
- Backup服务只可扩展现有kernel public-owner。阶段3必须有真实冻结的数据，原DMA实际完成后才能按阶段0解锁；逐层验证数据、ownership、原文件保存和自然EE/快门。不重复无新增条件的黑屏VM等待。

## 可复验检查

从本成果根目录执行，两个比较资产路径需显式提供：

```bash
python3 -B report/cp3006-start/verify_boot_backup.py --boot0 "$BOOT0" --nor "$NOR"
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider report/cp3006-start/test_boot_backup.py
```

原件身份、ELF重定位/指令、公开seed地址/重置投影检查通过；针对修改/截断输入、重复项第二份内容差异和64位地址的**6项回归通过**。首轮新增检查误把 `003e000c` 当u32，被真实输入拒绝；核回原一字节值及临时区初始化后修正，未放宽身份校验。

证据链：`run-00t3xfkx`内核栈→第一回复等待；pinned boot0/NOR/CP/AP指令→记录选择/消息与地址合同；固定seed逐项比较→条件初始fixture；独立PCI DMA测试→可复用传输实现。最后两者尚未在native拍摄运行中连接，因此所有capture/DMA完成标志继续为false。

相关证据：`runtime/analysis/menu-runs/run-00t3xfkx/ee-passive-91lewosw/`、`backup-sync-evaluation.json`、`cp3006-start/AP-BACKUP-DATA.md`、`cp3006-start/INIT-DISPATCH.md`、`cp3006-start/SHADOWS.md`。
