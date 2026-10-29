# 启动自检与首次设置的当前排查

用户提醒：实际相机的快门等开机自检可能阻断系统，首次开机会进入语言选择。
两条都作为独立启动条件核查，不把所有等待归为SD。

## 已有事实

- 自然路径确实创建过scr0099_0001语言页（screen12d），随后显示实际卡错误dialog322/module262。
- 34项语言/DST可用性不等于首次设置完成标志；尚未证明当前语言向导已正常确认完成。
- 当前卡错误本身已追到RM预检查：原stat(80d9016e)返回0/word0=0/word1=0，
  原Common394d0因此在发送RM命令前转39618返回80000004，最终7fffffff→模型2a。
- 这条独立失败不替代快门自检状态，也不证明修复它后立刻进入拍摄主界面。

## 正在执行的对照

用新编译的同一cpio/observer，先无输入，再在30s稳定错误页后经原InfraInput送中心确认键
1ac的按下1/释放0（50ms）。键值、源及队列复用已有native live控制映射。
记录原App队列是否实际消费、原screen创建轨迹及最终软件RGBA；不强切screen、不清media_error、
不直接写language/first-boot标志。配对结果尚待返回。

新增manifest记录InfraInput注入参数；无输入/旧MENU单变量验证器拒绝混入这类注入。
不能只凭发送返回0就宣称dialog已接受确认。

## 独立只读调查

- 快门与开机自检：原sequence_boot依赖、诊断故障模型及可只读采样的getter/字段。
- 首次语言：原触发条件、正常确认后的日期等步骤、持久字段，以及当前module262是否允许确认关闭。

RM真实队列/协议调查继续单独进行，尚未向相机报告任何虚拟卡ready。
独占Fsys helper已新增32B内部传输自检模式，但尚未运行；不把该测试代码当作已建立RM服务。

第一轮20B InfraInput对照已返回：run-ljrftef0/无输入与run-0qg4mptt/确认有相同选定镜像及observer，
最终RGBA均为3496a870…错误页。两次inject发送0，但未见原App队列确认消费，因此不判定“确认无效”。

静态首设分支已找到：209dd68/209ee20在模型1a76非0或1bd==2时进入初始设置，受特殊启动条件抑制。
1a76=extern_param_clock_force_settled，Backup02cf0014，getter2887f58→B+7eda8d0/u8；
1bd=date_time_set_status，getter285fb08→B+7e5df40/u32。主会话已独立核getter原指令。
语言后续选择20bc3dc→1893be0还会去1c6/1e0/1c5/1dd，具体页面及持久写入未闭合。

快门调查目前只闭合通用self_diagnosis_staus(原名)1cf2，getter288df40→B+7ee5b10/240h，
48×12B {category,code,status byte}。原默认status全0，不能区分正常与未收到诊断；
还没有把任何一项映射为机械快门。相关producer/硬门槛继续查，未判快门自检通过。

下一轮改走已验证的原App32B callback，只有观察到screen322的原0200a73b文本后才送Confirm，
同时只读这两个首设字段和诊断矩阵。确认码沿用已验证native ENTER1ac映射，
不把未核的下一行UIBIZ表直接当对应项。保护时机/线程/32B模板及旧MENU回归ASan/UBSan通过，
原对话框只读fixture与输入枚举回归11测试已适配并通过；新运行结果待取。

## 原App确认及首设/诊断实际结果

`run-k3xyvyuz`已取得原App消费证据：在原卡错误文本绘制后，CONFIRM1ac的status1和0均由
App队列读到，repeat0。最终实际RGBA仍为3496a870…同一错误页。
这比“发送0”更强，但仍没有UIBIZ事件/当前controller处理证据，不能直接认定它已接受正常UI确认。
原模块262是否可按键关闭、模板其他字段是否影响转换仍由原handler证据核查。

首设实测date_time_set_status=0、clock_force_settled=1；原force分支确实成立。
主会话独立核2d91560→35aae5c→Backup02cf0014的1B读取及模型直接写入，无反相转换。
当前native seed源码中未找到该key的显式写入；不能据此判定其完整来源或直接清它。

诊断结构576B/48项status全0，并且**全部字节与原初始化模板48b28f8相同**，
模板SHA256=e3945a45ba990d41ed338b305693d09447fa7bed2beca27cab9aa26091196777。
这不是快门通过的证据，也不能单凭相等断言从未收到任何同值事件。
机械调查目前只定位到CP初始化及回调等待，未闭合快门producer→AP故障→主界面阻断链；
CP回调等待含FATAL/timeout仍返回0，不能拿其返回0当成功，更不能把CPVA拿到AP地址空间采样。

正式同run数据见`firstboot-confirm-consumed-proof.json`，相机启动验证保持false。
