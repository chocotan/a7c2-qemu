# Guarded Backup kernel/PCI 端点：实现与联合启动记录

2026-10-25，接续 [Backup传输](backup-transport.md)。目标仍为原固件拍照/录像并写目录SD。
本页记录新端点和真实数据后端，**尚未验收原Backup同步、EE、JPEG或MP4**。
已通过的 `run-ypxwv89y` 中文首设/HUD/Fsys属于新增硬件关闭的兼容基线，不移作本页通过证据。

## 实现范围

唯一kernel public sender仍在 `virtual-cp/udate-distribution/`。默认只提供既有UDATE；
新bool模块参数 `backup_model=1` 显式启用Backup。未使用第二个sender，没有修改原pending、
EE、sequence/factory或ready字段。

- `backup-endpoint.c`：只接收已核对的40B、`0x903e0811`、opcode30、stage3/0请求。
  回复单独申请4096B，初始化为零，仅复制40B；AP原请求不是4096B可读页。
- stage3执行真实后端冻结、primary字节9置1、全1,419,512B读回，再回复归一化stage1。
  stage0要求当前冻结周期内的新direct DMA完成，随后解锁；不清字节9、不修改checksum。
- 消息发送成功前原请求仍由caller持有；发送后原请求free失败则保留并返回0，避免double-free。
  失败锁存先于事务锁释放；重入/不支持形状/资源失败均不产生正常完成。
- `backup-pci.c`：通过正常PCI APIs查找真实枚举的TEST peer，检查两个BAR资源范围，
  映射数据和控制区，核初始记录，注册public sender后才执行正常 `pcidma_connect(0,1)`。
  默认不访问PCI；显式开启但绑定失败会拒绝加载。

初始源是固定公开ALLLANG第二记录，SHA256为
`a90b46ae1d0fa054daeba321c52dc9d44d6bf32ca6eefcd1efb84fab2116e977`。
QEMU加载时核SHA和精确长度；kernel全记录FNV只用作内容/损坏检查，不替代该SHA来源。
原样FNV为 `5436a35ff036e6b5`，仅字节9置1后的FNV为 `a718b3aa73db052a`。
这是明确的条件虚拟fixture，不宣称执行过boot0或CP固件；当前profile限定全新ALLLANG实例。

## QEMU数据和完成合同

`virtual-pcidma/hardware/test_pcie_peer.c` 的Backup模式使用一个有RAM backing的ROM设备，
**ROMD直接读关闭**，普通读写经过同一组受限回调。数据BAR、高PCI primary窗口、ATU和
观察alias指向相同后端；冻结后普通写入拒绝。特权loader/debug写、热重置不在活动周期合同内。

新增控制BAR1提供明确的虚拟BUP1接口，32位访问：

| 偏移 | 含义 |
|---|---|
| 0/4/8 | magic `0x42555031` / version1 / primary长度 |
| 12 | frozen |
| 16/20 | 64位epoch |
| 24 | 写1冻结并置字节9；写2仅在新匹配DMA完成后解锁 |
| 28 | 被拒绝的普通数据写次数 |
| 32 | 本周期是否有一笔新的、完整匹配的direct DMA |

`sony_pcidma.c` 在实际channel4 read doorbell处理后固化sequence、reset、执行模式、SAR/DAR、
请求/实际字节数及结果；后续改寄存器不能改写这份结果。严格接受controller0/channel4、
PCI `0x404000000` → AP `0x4040ed000`、`0x15a8f8`字节的direct操作。
同总字节数但复制其它地址的LLI明确拒绝；stale/partial/fault不能解锁。
这些设备结果仍不等于原kernel回调已退休或文件已保存。

原host的PCI/CPU MEM ranges同值始于 `0xdffe0000`。带独立控制BAR的虚拟profile将可分配范围
扩到64MiB，CPU window与DTB保持一致；旧无控制BAR的32MiB诊断profile不变。
原kernel实测把BAR0分配到 `0xe0000000`，BAR1分配到 `0xe1000000`。

## 实际验证与保留的失败

- kernel协议/PCI绑定/资源清理/受控并发：**4 tests +57 subtests**，ASan/UBSan及模块ABI通过。
- profile及UDATE/touch/目录入口回归：**15 tests +44 subtests**通过。
- 当前native二进制：`source/build/qemu-TmqLY0/build/qemu-system-aarch64`，SHA256
  `e5d8acdf8afcdeea74fa351ae87734d90e38a0e7e8d9963011f2ff390a04aeb3`。
- `/var/tmp/backup-pci-qtest-f8e_9rpf/`：该版本公开fixture读回、篡改/截断拒绝、所有被测普通alias写冻结、
  完整channel4搬运、真实GIC、stale/LLI拒绝和CPU BAR窗口通过。
- 前一32MiB版本 `a590e6e…` 的BAR/DBI回归和目录SD设备回归通过；该原始binary另存
  `source/build/qemu-TmqLY0/build/qemu-system-aarch64.before-control-window`，未冒充当前版本。
- 原生产程序 `e23589c…` 与已验证启动候选 `d435865c…` 均未被替换。

失败未改成成功：

| 失败 | 实际原因与处理 |
|---|---|
| `ba14a570…` 构建 | 额外PCI头引入同名register_read/write；改用QEMU类型前置声明 |
| `backup-pci-qtest-u4ys5x7i` | ROMD直接读未按较短alias截断，错误消费最后248B；保持负测并关闭直接读 |
| `backup-pci-qtest-qsqdjgd6` | 关闭ROMD后仍调用ROMD flush触发断言；改为回调数据的dirty bookkeeping并按自然对齐分割访问 |
| 独立review P1 | LLI结果可借旧direct寄存器；现在固定实际模式并加不同目标LLI反例 |
| 独立review P2 | 先释放busy再锁存fault存在竞争；已改原子锁存优先，并加释放边界重入测试 |

这些设备正负trace均应按其binary SHA解释，不能因后续修复回填旧结果。

## 首次联合启动：已走到原PCI，控制访问宽度失败

`run-pp631e6d` 已实际启用CP3007、UDATE、touch、guarded Backup及新目录SD。
原kernel的PHY/link/host枚举成功，两个BAR均正常分配；进入
`insmod sony_udate_distribution.ko backup_model=1` 后发生同步外部中止：

- `console.log:621`：原host `link up`。
- `console.log:635/636`：BAR0=`e0000000..e0ffffff`、BAR1=`e1000000..e1000fff`。
- `console.log:938..945`：`__memcpy_fromio+0x80`，调用者 `backup_control_read`，故障指令 `39400023`（LDRB）。

原 `__memcpy_fromio(...,4)` 使用字节尾部循环，不能用来读取32位专用控制寄存器。
已改为显式volatile u32 +屏障，数据区仍用原IO-copy API。单测现在拒绝以data-copy访问控制区，
交叉编译指令已核到 LDR W/STR W；全部4+57回归保持通过，没有放宽控制BAR访问合同。

本轮没有public sender绑定、原Backup请求、UI或快门；无SD导出文件。宿主只保留未变的诊断
`INPUT.BIN`，commit无pending；owner进程/组不存在，主锁和目录租约可独占取得，未发SIGKILL。
失败及清理见 `runtime/analysis/menu-runs/run-pp631e6d/guarded-startup-failure.json`。
**不能将本轮归类为Backup协议或拍照成功，也不能称为已发生原Backup DMA。**

仅修正控制访问宽度后的第二轮正在独立新目录运行；以其实际日志和结果为准。

## 运行入口与后续判据

`runtime/analysis/backup_profile.py` 在目录USB profile之后组合新的DTB、只读fixture和硬件开关，
核当前源码/二进制/派生脚本/DTB身份。`qemu-menu-probe.py` 要求有效收据、当前模块、唯一sender、
全新ALLLANG实例，并传入 `backup_model=1`；GTK在输入前要求实际 `BACKUP_K_BOUND`。

显式配置是 `A7C2_BACKUP_SYNC=virtual-primary-v1`、`A7C2_BACKUP_BUILD` 指向当前组合stage，
同时使用既有CP3007/UDATE/touch及新的目录SD。`--candidate-build` 必须指向同一stage。

后续验收次序：真实后端绑定 → 原stage3消费/读回/回复 → 原DMA bytes/IRQ/callback → 原stage0 →
原保存/pending清除 → UI/group0/EE → 自然快门 → 原MPR/Fsys JPEG及独立解码。
录像的原编码、mux/close、MP4帧和时长另验，任何中间通过都不抬成完整拍摄。
