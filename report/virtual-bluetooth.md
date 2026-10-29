# 虚拟Bluetooth控制器：原管理连接短时通过，长期运行待验

目的为恢复原固件自然启动中的Bluetooth依赖。当前是显式研究profile `A7C2_VIRTUAL_HCI=virtual-rom-v1`，**默认尚未开启，不代表完整无线功能或主界面稳定已完成**。未使用真机、host现有串口或射频接口，QEMU仍为`-nic none`。

## 原失败与真实设备边界

原`MODEL_SYSTEM_ERROR`（`0100012e`）来自`INFRA_NOTIFY_BLUETOOTH_ERROR`。透传原`BTBlog::errorPlace`后分开两个现象：

- ResourceBluetooth 501行检查ALLLANG保留MAC`FF FF FF FF FF FE`，只是警告，该资源请求最终仍回0。
- Core `startBcmBsaServerCommon`的730行是真正的`/tmp_bt/bt-daemon-socket`等待耗尽。原管理路径没有实际执行启动脚本，owned PTY已分配但最初没有BSA PID或HCI字节。

虚拟profile现在用原`bsa_server`（SHA256 `4e2c75171967ceaf99ddc5f63dde64a905035802c39da16d8b4f2cb560a230ea`）连接新分配的guest `/dev/pts/N`。使用显式ROM、`-r 14`，不下载物理Broadcom芯片firmware；原BSA及其IPC/管理状态机保留。guest中的启动脚本替换明确记录为模型接线，原宿主固件资产不变。

## 有状态的H4控制器

`virtual-hci.c`仅guest AArch64可构建，链接原glibc2.25；host只编译pure core或自有PTY测试。MAC为本机虚拟值`02:00:00:7c:02:01`，manufacturer`ffff`，不冒充实体芯片。保存Reset、事件mask、LE host开关、名字/class、广播/扫描参数和数据；Read命令读回实际backing。无连接/ACL/SCO对端或真实射频，未声明加密/SSP/连接能力；Rand使用原guest `getrandom`。

未知标准或厂商HCI命令回复真正Unknown Command`01`，不是通用空成功。非法包类型/长度/参数失败关闭，不按任意字节重新同步。日志限前1024次及后续2的幂次，实际计数/状态仍保存；不能根据采样日志的行数推断请求总数。

## `07 f0 00` 的证据与实现

`run-j14ei5ky`已实际完成21条原BSA HCI命令后，收到原始`07f000`，旧parser按未支持类型07失败关闭。不是猜测串口echo。

- 原BSA `diag_set_lmp_log@4d1e58`：写`len=2/offset=0/payload=[f0,arg]`，类别`2c00`。
- `hcisu_h4_send_msg_now@40d6b8`将该类别转为H4类型07；因此完整请求固定3B，不含长度字节。
- Linux公开[同协议实现](https://codebrowser.dev/linux/linux/drivers/bluetooth/hci_bcm.c.html#417)把`[07,f0,bool enable]`入队，未等待ACK。反向LM诊断数据不是控制请求回复。

本模型目前仅支持**关闭**请求`07f000`：跨read累计3B、保存最后原字节和计数、设置`diag_enabled=false`并抑制LM诊断输出，重复幂等，**不发送任何回复**。未知07子型和开启值仍明确不支持。没有向原BSA伪造七字节Command Complete。

## 最新实际结果与剩余失败

`run-gy8yno8w` 中，原BSA消费该无回复控制请求后继续至至少36条HCI命令，成功读取原guest熵、保存广播数据和名字，**语言首设前**创建真实Unix socket `bt-daemon-socket`、FIFO及`ble_local_keys`。这不是整个首设完成后的正向结果：`run-j8kbpmy7`显示，进入拍摄阶段后Core730再次出现，目录内容已消失。不能写成Core错误已经修复。

原导出符号 `InfraBluetooth::m_isMgtOpen`（ELF VA`34509`）按每run实际PID/库基址读回，首设前后均为0；首设前该状态本身不证明失败，原延后启动尚未执行。完整新版窗口中文首设结束后仍出现原“系统出错”。**原client管理握手尚未通过**，早期socket存在不算功能完成。

剩余错误定位：`libInfraBluetooth`的5041行通过共享error尾部`170b0`记录，真实调用在`1750c`，PLT`a5a0`对应原`CBTCoreProcess::startProcess(bool)`，以true调用并得到非零返回。不能只根据日志caller=`170bc`附近的另一个line常量判断分支。已新增原`BTBlog::upperAPIReturn`的500/501有限透传观察，继续区分原boot/start结果；不修改其返回值或mgt状态。

继续核原`BTUtils::CProcess::startProcessViaIM@3d24`发现，函数复制固定命令`/usr/bin/startBTCore.sh &`；`3b78`申请动态回复ID，向`0094020a`发送260B，body=`00940023+256B命令`，等待后读回复`+4`到局部退出状态。但上层只核transport返回，不核这个退出状态。真实broker日志有该命令及ret0，后台子进程实际是否成功不能由此判断。实验profile现保留原im stdout/stderr，读回脚本摘要/内容与目录前后状态，继续核子shell/preload/目录生命周期；没有用空执行应答替换broker。

主机ASan/UBSan、全65536标准opcode错误行为、自有PTY双向字节、分包/重复诊断/no-reply测试已通过；这些不替代上述管理连接、原主界面、AF、拍照或录像验收。

## 按原请求启动与下一处真实配置拒绝

后续不再提前手动启动BSA。`startBTCore.sh`由原执行broker调用时显式声明PATH/库路径/清空AP preload，每次写独立PID日志；虚拟UART也在该原请求内创建，使它与原BSA处于相同启动和文件系统阶段。`stm_system`已核对子进程以空env调用execve，原库脚本不能依赖SDK父shell环境。

`run-u4c92j0x`已实际显示新版窗口里的主拍摄UI和中文MENU，但不能据10秒样本判长期稳定。之后`run-9911ic43/run-m2u23c98`更早进入原BSA配置回调并触发**原**`libInfraBluetooth`的`b780 brk #1000`，PC按本run映射确认属于原库，不是observer。

原调用栈是`pvtCoreDmSetConfigSetBTParam@10820`，调用`sony_dm_set_config(tBSA_DM_GET_CONFIG*)`返回1后执行原失败断言。它经Core `19438→191e8`发送dest`81a10589`、op1/len`2e8`，body从+8开始。后续调试不能把断言旁`008f0139/cmd0e`的bool回成1来掩盖这个错误。

UART原字节已精确找到两个失败请求：

| 原请求 | 旧模型结果 | 当前实质改动 |
| --- | --- | --- |
| `2006` payload `200020000300000000000000000700` | 20ms非连接广播被旧4.0/100ms约束拒绝`12` | 显式虚拟HCI/LMP5.0 legacy广告profile，合法边界20ms，保存整个15B参数；其它可选LE能力仍为0 |
| `fc01` payload `feffffffffff` | Unknown Command`01` | 仅补6B地址写入的实际controller RAM，`1009`读回相同值；不修改ALLLANG Backup，不为未知vendor命令通用回0 |

旧请求39/40/41已证明原固件广告数据、`ILCE-7CM2`名字和Scan Response实际进入controller backing；不是独立主机界面或伪造BSA IPC结果。无数据的upper-return额外诊断已移除，保留有证据的errorPlace与有界UART原字节日志。

## 原管理状态读回与60秒反例

修复后的`run-zyqcbz_l`实际完成同一新版窗口的简中首设，原主拍摄UI与中文MENU可见；按真实PID217和本次原库基址读取`m_isMgtOpen@34509`得到`01`。原socket/FIFO/keys存在，UART配置实际进入backing；未出现此前Core730或配置断言。**这只通过短时管理连接，不代表60秒或完整无线功能。**

延长同路验收的`run-miw820mp`在MENU后等待60秒，原日志出现`model::set_pre_power_off_seq`及screen`309`，LCD变全黑；随后MENU/Fn/播放和三轮均未恢复画面，最终mgt读回`00`。errorPlace仅见Resource501警告，不能据此把黑屏归为已证实的蓝牙错误，也不能未经调用链核对就称自动省电。该run的`gtk-input-proof.json`保持false并记录人工复核失败，所有相同黑帧均不计控件功能通过。下一步追原关机触发与正常唤醒消息；显式HCI profile仍未改为默认。

后续`run-phyxlklp`已实际捕获原UPM`00920143/src80920021/factor8`，原表确认APO1自动关机；不能把该轮mgt关闭误称重新发生蓝牙启动失败。原始通知、shutdown三元组、输入通道限定与仍未恢复的唤醒见[APO报告](native-apo-power.md)。
