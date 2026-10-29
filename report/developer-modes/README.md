# 原厂开发/调试模式与当前模拟器的关系

结论：这套机制对启动分层、注入和内存诊断有用，当前已复用其中的原bootin正常启动入口与标准loader preload机制；它没有直接提供当前显示、SD热插拔、USB网络或CMOS/编码的硬件仿真。不能把“调用了原接口”都叫“已经打开原开发模式”。

本次按用户提供的`change_mode.sh + bootin.elf`模式截图调查，原件来自公开2.01 ALLLANG资产；没有使用真机、私有setting或full/private，没有执行切换脚本。两个独立reader均已结束部分交付，main另核当前生产接线和原bootin关键窗口。所有模式可运行性均未动态测试，字符串、脚本声明与原指令证据分开。

## 当前已经使用了什么

| 当前功能 | 实际依赖 | 与原模式的关系 |
| --- | --- | --- |
| 原固件启动 | `run-menu-probe.sh`末尾显式`--bootin`；`qemu-menu-probe.py`调用原`bootin.elf 'target=qemu ' dmode=3` | 已复用原boot manager的正常APP阶段，不是开了一个通用开发总开关 |
| observer/设备适配库装载 | 启动命令拼`LD_PRELOAD`，装自研`file-media-config.so`、`menu-observe.so` | 已用标准loader入口；没有通过change_mode p写dmode/preload文件；不据此声称原3p已实测 |
| 原LCD、HUD、MENU | 原GUI加自研GPE/OSD适配与QEMU显示输出 | 模式本身没有生成帧；preload只是承载适配库的入口 |
| 按键、拨轮 | `inject-key.c`与控制器按已核布局使用原osal消息队列，原程序消费事件 | 原消息接口复用；不是一个dmode输入开关提供全部功能 |
| SD文件系统/热插拔 | 复用原Fsys与原文件后端；file-media-config显式配置EXISTMEDIADRIVER，再由自研RM设备/状态机发送真实通知，原Parse/Update/Unmount/Mount处理 | 确实用了固件已有的文件测试后端和API；通道mask、通知、租约及安全导出仍是我们实现，不能靠切dmode得到 |
| 隔离网络 | QEMU xHCI/usb-net、原kernel USB以太网驱动、宿主用户态peer | 没有借原开发模式或原Wi-Fi开关伪造链路；不是实际无线关联 |
| 配置保存/恢复 | 原Backup_nread/sync_subsystem与原文件，宿主快照、校验、实例代/CAS及启动两seed恢复 | 使用原配置API；持久化生命周期由本项目实现，不是DEV文件直接提供 |
| overwrite | 宿主按manifest生成私有派生cpio | 与change_mode模式文件不同；不是原升级/服务模式刷写 |
| 调试器/串口 | QEMU `-gdb unix:/out/request-queue-gdb.sock`及宿主GDB；自建kernel cmdline console=ttyAMA0、guest init shell | 不依赖截图中的原gdbserver a/b模式或development.txt恢复串口 |

依据为权威runtime中的`run-menu-probe.sh:35`、`qemu-menu-probe.py:764–798`、`inject-key.c`、`file-media-config.c:mcmn_param_init`、`usb_network.py`、`user-settings-checkpoint.c`、`firmware_overlay.py`、`qemu-kernel-probe.sh:22/83`与`request_queue_watch.py`。这些说明当前源码接线；实际显示、输入、SD、网络和配置的已验范围仍各见现有验收报告。

## 各入口对开发的帮助

* **阶段0/1/2/3**：原init2默认3，模式0跳过bootin；原bootin帮助和main原指令确认1/2/3分别选`s g r u`、`s g r u l`、`s g r u l i a`阶段参数。适合区分GlobalInfra、LIRO和appFw的启动问题，可减少一次加载全部服务时的噪声。实际QEMU阶段停机/恢复尚未测试，不能声称已有原自然开机完整对照。
* **preload及内存工具**：原脚本为LeakTracer、jemalloc等准备配置，可以研究内存问题和既有诊断设施。当前公开资产在脚本预期路径有LeakTracer/jemalloc，未找到预期efence/ASan或/usr/bin/gdb/gdbserver；脚本有分支不代表发布了全部依赖，更不证明ABI、FIFO或内存工具能正常工作。
* **DEV串口标志**：`development.txt`含DEV时，change_mode尝试修改kemco的console参数。这不是脚本全部模式的总开关；我们QEMU已自行提供串口，因此对当前界面和文件保存不会额外解锁功能。
* **updater与Senser**：原init2以`/setting/sen/smode == UU`另启sen.elf；up.sh使用另一组updater标志。它们是各自的服务/维护入口，不与dmode合并。不能因Senser名字或TestMode字符串就断言能模拟CMOS、镜头、AF或编码；没有这样的动态证据。

## 对截图“p可装任意库”的收窄

原change_mode.sh的p分支确实将第二参数写入preload文件，但它写入的模式是 **3p**，不是字面p。只读脚本到此还不能认定bootin会任意加载文件内容。

main按PT_LOAD映射核原bootin（23960B，SHA`dab3ce4b6c28a6c9ffd9f0b893dce1d08f3ee7302a09df87e518409e728be2f2`）：

1. `402518..402530`把模式后缀大小写归一，P置flag bit6。
2. `402c50`按bit6进入分支；`402c74..402ca8`读取`/setting/mode/preload`，最多512B、截断NUL到511。
3. `402cc4..402ccc`界定恰好4项。表`403f08..403f47`每项16B，首指针分别为LeakTracer、efence、jemalloc、ASan路径，另指针为工具附加环境。
4. `402f64..402f8c`通过原PLT strlen/strncmp比较文件内容前缀，只有匹配时`402fb8..402fc8`调用setenv(LD_PRELOAD, **表项路径**,1)。没有把任意输入文本直接传给该setenv路径。
5. `402ed4..402ee4`也按bit6决定事后unsetenv(LD_PRELOAD)。所以不能只因脚本接受任意第二参数，便把该preload文件分支描述为通用任意库入口。

这是特定原分支的静态结论，未穷举额外env机制或所有exec参数，也未运行模式切换。不建议把现有显式preload直接替换成3p后假定等价。正常3的条件分支不在此清理preload，当前实际observer消费也另有运行证据；不由此推所有模式的继承行为。

另外，change_mode.sh在参数判断之前已经可能创建/chmod模式文件及修改console；连`--help`都不适合当作无副作用的探测命令。本次只读，没有运行它。updater版本/区域子命令也不是当前仿真的必要入口。

## 后续建议

优先把1/2/3用于**独立虚拟实例的分阶段启动对照**，保留当前已验正常模式作为基线；再评估LeakTracer/jemalloc是否具备完整依赖。开发模式不会提供缺失的CMOS帧、镜头响应、CP完成消息或编码输出；这些仍按现有消费者合同推进。没有必要为已能在QEMU中使用的GDB和串口另切原服务模式。

`verify.py --root runtime/analysis/menu-root`已由main执行，核三份原资产摘要、模式后缀与阶段选择、preload分支原字节、四项表及预期工具路径存在性。输出中动态模式验证、切换执行和capture保持false。A/B的未完成bootin反编译及未执行脚本仍按其报告保留，不冒称代理完成了main上述原指令补核。
