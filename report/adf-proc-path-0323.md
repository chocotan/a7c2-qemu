# ADF proc SetPath 0323：NoMem完成后的实际前沿

范围：公开ALLLANG 2.01、隔离native QEMU，不含真实设备或私有setting。
当前默认关闭的独立虚拟音频控制后端已在 `run-kao1n0qd` 通过原AP实际消费。
仅验证控制子集，不标记硬件音频、PCM、帧、EE或拍摄成功；下一真实前沿为0336。

## 最新实施与验收边界

显式选择 `A7C2_ADF_PROC_PATH=virtual-source7-idle-v1`，需完整受保护NoMem/DFS/TCIN/
Backup自然profile、新UI首设与目录SD安全导出；缺省关闭，拒绝YC、ready、事件注入和旧UI强制激活。
时钟策略名 `virtual-source7-control-events-v1`，1ms为明确虚拟控制周期，不是原MTG频率或CMOS帧率。
计数器只能由真实guest `timerfd` 一次性定时器到期推进，getter、注册或轮询都不推进计数。

完整冷态流程现在逐项消费：

| 时点 | 真实模型工作与读回 |
|---|---|
| 请求接收 | 冻结原12B envelope及动态caller，保存queued配置/独立原请求所有权；异步worker接管，未回复 |
| 定时器之前 | 完整读取固定公开seed，四key含58007b=1；Glee能力word1推导F0，pin1保持；同步prelude owner{1,1,1}；canonical routing cache比较相同后排AF8B；全冷global0→Stop3→phase1 state4，观察低两输出请求位全0，三项path0清理无硬件工作；priority2 Start仅登记 |
| 第1到期 | hardware7计数→同epoch cache5→非空私有source5订阅通知入队/取出；priority2消费queued Start，pending配置有效/global1，资源准备/5gate/16系数，129保存本次counter1并保持pending；priority4真实解释AF、七笔disable全字写零与响应消费；129同计数仍等待；AVIO stage0 |
| 第2到期 | 计数真实改变，129按24位模差完成并注销工作；AVIO stage1无字段写但必须消费 |
| 第3到期 | AVIO stage2/changed-touched字段读回；callback只清AVIO mask2、保留请求位1；进入stage5，仅登记priority2 input，不能同pass回扫低优先级 |
| 第4到期 priority2 | 消费input作业→Glee control30真实保存/清driver callback/同步callback0；notification2在input pending1与pending配置1时排12B内层完成，source9058003f；随后stage7 notification0提交active配置/清pending/global2、排B0；返回后才清input submitted/pending/job |
| 第4到期 priority4 | 真实解释B0及七笔disable全字写零、匹配成功响应消费、command sequence2；Glee为空访，不增加第四个输出job |
| 事件之后 | 关闭timerfd；验证所有临时工作排空，实际取出内层完成并解析status，再OR00580000构造独立外层1323；真实send/原请求free，只有原AP成功free该回复才计ap_consumed |

旧Idle Stop没有被省略，也未将global直接设2走同path快捷完成。stage24是转换表sentinel，未模拟执行。
原内层完成早于notification0/config commit及input pending清除；模型保留这一内部通知顺序，
仅将外层可见发布保守地延后到全部自有工作/B0响应排空，不声称原异步relay的精确时序。

源码在 `runtime/analysis/device-models/adf-{proc-device,public-config,idle-resources,input-state,
aip-gates,aip-coefficients,aip-disable,aip-commands,avio-output,source7-clock}.{c,h}`。
普通文件/长度/EOF/FNV读回依赖既有host完整SHA/BK4身份先验；原libc无现代fstat导出，
使用其syscall wrapper保留普通文件校验。共同资源guard沿用严格已知Speech域，
两块外部Speech不释放、不清零、不重映射，metadata冻结不等于数据冻结。

宿主联合回归 **217 passed / 62 subtests passed**；包含无事件、仅两事件、仅三事件均无正常回复，
回绕、错代、回调重入、分配/发送/清理/原请求释放错误、错误owner、持锁fork等反例。
模型经历两个输入callback P2和一个stage2错误cache写回修复并独立复核关闭；
最终冷态/AF-B0/内层relay审查64e无已验证P1–P3。
原固件ABI observer `ab62f38d5e768030a34a38e3561cd77c5d1cce00e6c371eb45e3f8347fc558c9`，
237项冻结源码摘要全部一致，关键实现已由readelf确认真实链接。生产QEMU e235未替换。

### 原固件联合运行 run-kao1n0qd：控制消费通过

`adf-proc-native-proof.json`和本轮`adf-source7-native-evaluation.json`核验：
原AP PID258/Common tid381实发0323，独立worker tid1037执行四次真实guest timerfd到期。
每次expired1、observed≥deadline，下一deadline严格为前次observed+1ms；
hardware7/FB/cache5计数与epoch均逐次1/2/3/4，无getter推进。
四条非空source5私有订阅通知分别入队/取出；第1事件Start/AF消费/129同计数等待，
第2事件真实改变后129成功；AVIO三个stage分别只在事件1/2/3消费，input3末排队4执行。
phase2内层完成排队时input pending和pending配置均1，随后phase0提交配置，
再input排空、B0真实消费/匹配响应，最后inner relay和外层发布。
AF/B0命令各消费1次、sequence2、14笔disable写入/读回，保留active0400原位；
16系数/5gate读回、canonical cache/四key/prelude/全冷Stop的证据齐备。

精确12B实际回复为 `0d2023130c00018000005800`，动态目标81cf61c4，source92840747，独立分配/入队。
原请求free0、clean_completion1；原Common381随后释放同一reply指针，
rc0/faults0/retained0/ap_consumed1，证明原waiter实际消费。
外部Speech8400/8401仍live、同轮初始创建强归属通过，没有free/clear/remap。

原Fsys仅3文件：406B mediapro.xml、9670656B database.bin、93B INPUT；
全树字节/hash、cleancommit、owner/组/QEMU退出及双锁可独占全部通过，无SIGKILL。
这不升级原MTG触发身份/频率、CMOS、PCM、音频输出、帧或JPEG/MP4拍摄标志。

Common现真实等待 `adf_set_input/0336`，14B：`0d2036030e000180000200000000`，
候选链`34e5788←34f2bec←34c6ec4←339d6a8←33aaa3c`。
Still与快门后EE enable/source/status仍1/0/0、Backup pending0，group0 current2f/stop0、队列31/40。
下文保留分阶段静态调查与历史前沿；当前运行结论以前述原证据为准。

## 实际请求与边界

`runtime/analysis/menu-runs/run-ba2cnxt9/nomem-qualified-evaluation.json`已核验
NoMem两阶段、005a0000回复与原AP释放；随后Common tid381发送：

| 字段 | 同轮实际值 |
|---|---|
| 目标/source | 92840747 / 81cf61c5 |
| 长度 | 12B |
| 原字节 | `0d2023030c00018000000000` |
| body+8..11 | path0、mode0、format0、保留0；三个u8，不按bool解释 |
| 原AP调用候选链 | 34e5788 → 34f26e4 → 34c6e84 → 339d61c → 33aaa3c |
| 原kernel边界 | osal_rcv_msg_tmo，采样前后同一syscall |
| EE / Backup pending | 0 / 0 |
| group0 | current2f / stop0，Still入口和快门后分别queued31/40 |

这些是同轮实际发送及无暂停读回，不宣称完整unwind或原子全局状态。
本轮HUD、自然快门输入、原Fsys三文件全树读回、cleancommit和全部进程/双锁收尾通过，
仍无JPEG/MP4。

## 原AP构造与消费

原AP appFw.so SHA256：
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。

- wrapper编号94位于`34c6e58`；`34c6e80:e2ad0094`调用`34f2608`，返回`34c6e84`。
- 原调试名在`4c68940`：`adf_proc_set_path`。
  `4c67449`格式串为`%s  path:0x%x, mode:0x%x, Format:%x`。
- `34f2650:a1018452`构造200d，`34f2660:61648052`构造0323；
  `34f266c:81018052`为12B，`34f2674:c1ff8f12`构造8001 flags。
- `34f2658:bf5b00b9`先把body四字节清零，后续按输入对象枚举设置各u8。
  实际全零不自动说明硬件已停、资源空或无需工作。
- `34f26d4`/`34f26dc`构造目标92840747；
  `34f26e0:93cbff97`调用原void `send_and_wait_cmp_i@34e552c`。
- `34f26e4:a06b40b9`读取实际12B回复+8，再在`34f26e8`调用`34e349c`做状态转换。
  发送失败沿既有原断言路径，不误写回复清零值为成功。

原函数在输入对象+2c等于1时有软件早返回；本实例实际走发送路径。
不得写这个条件、EE gate或ready状态来绕过消费。

## 已闭合的CP路由与完成封装

原CP `cpapp-b.bin` SHA256为
`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，
CPVA转文件偏移为VA−108000。主会话对先前9处及后续25处共34处锚点逐项读原件核对，均一致，
收据 `runtime/analysis/menu-runs/tcin-tests-20261025/adf-proc-initial-static-pins.json`。

| CPVA | 原字节 | 原作用 |
|---|---|---|
| 1c538e | 4b01 | 0323 TBH项→1c55de |
| 1c55de | bc200790fde1 | 转内部event bc |
| 1c414e | 0a04 | event bc TBH项→1c482a |
| 1c482a | 304605f0eafa | 调1c9e04 relay |
| 1c9f68 | 3f2040f2477303a90c22c9f25800c9f28423e4f03df2 | 发向9058003f，source92840747 |
| 66b050 | 0021042218234160c16142620522026307224263c0e90f310821c0e916110266 | Idle ctor path0及sequencer初态 |
| 66b0c2 | 0ef02ffa0ef097fb01280fd1 | 查询可选AIP/AVIO分支 |
| 67983e | 012c03d1039818b1012515e00025 | 两个独立sysnd owner条件 |
| 1b7bd0 | 059840f4b004 | ADF service status OR 00580000 |

relay `1c9e04`把三个wire u8转为内层2004/0102/12/0001，notify由path派生，
path2为1，其它已识别路径为0；本实例精确内层为 `042002010c00010000000000`。
`1c9eac→69772c`保存requested path至12061ee。

`ProcMsgSetPath::Execute@17c450`经669288选择序列。
立即完成要求1787880==2且当前path一致，冷态原始零不能满足这个前提。
`17d4a0(0)`返回Idle对象12207e4，ctor66aff0显式定义path0、sequencer初态0及转换表。
Idle准备66ac48处理两个controller（671c3e(2/0)→671b44）及其五个stocker，
再处理三个pin-buffer manager（185cd8(2/1/0)→185b0c→6740a4）；不能省略为一笔path写入。
输入阶段66b25a可能直接完成，也可能通过66b2a3/17a968向sysv scheduler登记668481 callback。

配置owner12205c0：66936c保存pending配置/request id/valid；669386投影到active并清valid。
callback66921e按阶段0→state2并提交配置、阶段1→state4、阶段2→17c5e8生产内层完成。
内层为2004/8102/12/1/status@8，1b7b88消费并OR ADF域00580000。
外层69cf12生产200d/1323/12/8001；成功字节为 `0d2023130c00018000005800`。
1c78e0查原sender，565204独立分配、bec024设置92840747 source、564b38发送，
失败由565300释放临时回复；不就地改写原请求。
697738仅在status00580000时提交requested path12061ee→success cache12061ef。

## 独立sysnd owner：公开值1与原Glee能力1

可选分支679524→6797f8要求 `sysndPinImmediately==1 && sysndSuperimposed!=0`。
前者来自配置key58014a（descriptor d12ff4，offset1a/size1），
后者来自70b19e接口vtable+1c的control0b响应+4。
原getter忽略control返回值；清零的查询结构不能作为驱动消费成功证据。

主会话调用既有verify_public_seed，先核验完整固定SHA及两个BK4 checksum，
再确认CP记录ed000中key58014a长1/attr0/文件偏移1331d0，原字节01；
key5e028a长4、值20000000，selector20选择原Glee系统217144。
收据 `adf-public-sysnd-owners.json`；不以公开文件值冒称原CP运行registry已绑定。
固定seed2390264B，SHA为3dab4f0d…8fe47，运行读取锚FNV64为6109fb020e03a76e。

control0b经217398→70cf3e→221258纯能力表。subtype8/9首个输出u32都为1、return0，
不查询PCM或当前混音活动。故原参考两个owner组合为true，不能拿0327 inputless caps推导false。
原Glee能力1保持；当前不以另造cap0跳过未知AIP/AVIO工作。

## path0资源准备：各自owner与同步两阶段

两个controller为ProcPinCtrlAudio1221068、ProcPinCtrlYc1229bd4。
path0选择mode0；busy标记+41a0==1时拒绝，其余更新模式并清理各自stocker：
Audio0/Audio1/AudioAc3/ExtCodec实例10d9f1c/10da5b8/10dac54/10db2f0，
Yc0为10df9b8。各容量20，count0的ClearAll直接返回0；非空确实会归还token，不能清零冒充消费。

三个pin-buffer manager为WrAudioPin122e570、Write122e890、Read122e4e4。
path0的vtable+28均返回0，因此跳过异步创建；按原phase1、phase2同步登记，
pending清0、路径0、done_mask3。674142仅在mask3允许后续读回，否则efff。
虚拟后端必须给各owner建立明确空记录与lease，不从类名推断不会别名Speech；
外部8400/8401保持原handle/epoch/引用历史，全局DMM空闲不作为主张。

## 输入调度、Glee控制与回调

selector0经66af26强制得到输入状态1；66aeb8输出请求参数0，必须走一次工作。
owner12200a0的+0=request、+4=pending、+8=callback、+c=parameter、+10=submitted_callback。
66b25a先登记Idle listener，17a968登记priority2/668481到32项scheduler，再保存callback/param0。
真实scheduler67d268经1965fa被调用；只登记不算消费。

668481→17ab9c→17ac80先置pending1并快照callback，再发control30/parameter0/callback66848d。
原21722a→70b350为纯控制函数：保存参数与callback，清driver callback，再同步调用callback(0)，return0；
70b370/control31读回参数及callback，完成必须为0/0。这段无PCM/DMA/时钟/硬件寄存器读取。

66848d→17ad58调用保存的Idle fanout，listener移除并推进阶段后，才清submitted callback与pending；
control返回后再移除scheduler、清registered callback/parameter/request。
不能先清pending、直接标完成或以control返回0代替callback。

`device-models/adf-input-state.{c,h}`已实现这个明确的虚拟输入子集：
独立32项工作队列、五listener、有界首次generation1、真实enqueue/consume/控制函数调用/嵌套回调/配对读回，
未知、重复、旧代、提前清pending、坏读回、跨代回调均fault且不标本次complete。
宿主C sanitizer与NoMem相关回归共32项通过；尚未接入observer或作为原固件完成证据。

新子模块独立复核发现两个P2并已修复、再次审查dfe确认关闭：
提前/递归/完成后重复fanout先验证活动control事务与唯一未消费listener；
跨代回调在清submitted/pending前拒绝，保留原request/job/callback元数据。
构造只接受全零新存储，不能重置活动工作。新增相关宿主回归33项通过，
资源准备模块另含470个拒绝不改元数据反例及外部1MiB Speech不变；它们仍不是原生ADF消费。

`adf-public-config.{c,h}`另已实现对固定seed普通文件的逐块实际读取、精确长度/EOF/FNV读回，
从CP三个固定key位置构造独立只读owner，重载/错内容/坏长度/未知key/查询计数溢出均拒绝。
它依赖既有host完整SHA/BK4身份校验，不以FNV代替源文件身份认证；未声称原CP registry已绑定。
加入该模块后相关宿主34项通过，原ASan/UBSan亦通过；仍未链接observer。
三个前缀模块另用AArch64目标与原libc-2.25做no-undefined链接检查，
原固件没有现代fstat导出，因此保留普通文件/长度校验并通过其syscall wrapper使用SYS_fstat。
原符号syscall/pread均解析至GLIBC_2.17；仅前缀ABI检查，不冒充完整ADF/原生消费。

## 原Glee true分支的AIP和AVIO工作

Idle66b0bc在pin1/cap1时读取AIP状态178865c及10ef2d8+1c：
前者0调用17d524 prestart再17d5d8(seq,1)；前者1/后者3直接后者；其它状态先结束旧请求并登记等待，
不能凭无输入任选分支。原67de4c初始化两个状态为0，但只作为明确虚拟冷态的参照，不称当前CP已是0。

prestart17d524通过AudioIpIf owner1a74f64/vtable e908ec/+24=51f6f4发control113(参数0)、129。
113路径b6b726清内部owner1116340的+c/+8，协调状态后b6c904→b6cc64消费16项系数，
并涉及f48a3900 bit8的RMW及其它reset/gate；仍需逐项闭合硬件动作。
129/51ee24保存时间与delay，登记priority2/b6bfff，不能入队即当延迟完成。

AVIO17d5d8(seq,1)设置请求位1、登记(seq,offset24,discriminator1)，
control3读mask后置bit3，再control2(70b706)提交带完成callback66b62b的工作。
环容量60、每项12B，正常bit3变化排入type0的stage0/1/2，只有最后一项携带callback。
父owner+20的直接完成分支当前不采用；mask相同也需一项工作，不能空ACK。
66b62b完成后清AVIO mask2，不得顺手清请求位1。

### AVIO三阶段的有限shadow后端

实际21843c/ProcVsync每次仅弹出一项，218584完成stage后才调用该项callback。
本次target8/change8→21d884，stage叶子不读PCM、不分配、不启动DMA、不访问MMIO或busy。
共享shadow B128a718、changed D128a788、touched T128a7a0，动作严格为：

| stage | shadow RMW | changed第一word | touched第一word |
|---|---|---|---|
| 0.1/0.2 | B+10 bit27置1、bit26清0 | 原字段不同时OR00080000 | 总OR00080000 |
| 0.3/0.4 | B+18 bit30与bit26置1 | 不同时OR08000000 | 总OR08000000 |
| 1 | 无配置动作，但必须消费独立工作项 | 保留 | 保留 |
| 2.1/2.2 | target bit0为0时B bit18置1、bits16..17置2 | 不同时OR4 | 总OR4 |
| 2.3 | B bits24..26置source&7 | 不同时OR8 | 总OR8 |

其它字段、字节和位图word必须保留，changed与touched不能合并。
source缓存120638b非ff则取覆盖值；ff才取配置1acb4ad，来源key00f900d2。
固定公开CP记录文件offset152b2c值01000000，AP同key为ffffffff，不能混用。
虚拟后端需显式绑定自有初始shadow/route cache，不能将未闭合的原运行shadow当BSS零。
`adf-avio-output`的有限队列/字段消费子模块正在实现；它不提供完整Idle或音频硬件完成。

### 事件与时间：不推断50Hz、不以墙钟替代source5

后续原字符串216e14确认216d48为 **BootExit排空路径**，不是正常Vsync生产者。
564fac也是注册处理函数分派器，非已证明的普通收包；它找unit41 descriptor+8处理请求40B，
其中+18字面4e20不能当已知周期/单位，request内结果也不能由函数返回0替代。
70bbca是共同空态判据（Output count+34、Input count+40、gio count+2c全0），不是可强写的ready位。
这条候选因此保留为否定结论，不用于驱动原生时钟。

正常候选已上追67a10c：按序调AIP1、AIP2、Glee总体ProcVsync217038，再其它后端；
AIP1的vtable+1c确实是b6d210→b6d290→b6ee72。67a10c的真实调用/消息来源仍待闭合。
Glee总体第一项调用Output21843c，故本次output控制之前没有PCM消费前置；
不将此扩张为整个音频后端不需要PCM。调试avio_audio/av命令不能当自然tick。
三个队列项必须三次真实消费者调用，不能一个事件清三项。

AIP getter b6bf72→6bb7b2(selector5)只读缓存1789e80，自己不推进时间。
更新入口1e68fc通过538ea8取时态并写cache；计数源/启用状态仍待追。
129比较要求current!=saved(+74)，即使delay0也必须变化；
随后按 `((current-start(+7c)) & 00ffffff) >= delay(+78)` 判断，而非signed墙钟差。
AIP scheduler b6ee72由b6d210任务中的b6d290调用；事件派发owner仍待闭合。

## 子模块实现与阻塞矩阵

| 子域 | 当前内容型验证 | 原生ADF完成 |
|---|---|---|
| 资源准备 | 两controller/五空stocker/三pin两阶段，470个拒绝不改元数据反例、独立审查通过 | 未集成 |
| 输入工作 | 实际priority2 enqueue/pump/control30/嵌套callback/control31，两个P2修复复核关闭 | 未集成 |
| 公开配置owner | 完整guest文件读回、三个CP原值，host SHA/BK4先验+运行FNV；原libc前缀ABI链接通过 | 未集成 |
| AIP16系数 | 原mode0黄金窗口已独立核对，16项低14位RMW/保留上位、3904.bit24清除，sanitizer通过 | 只此字段子集，不能代替reset/gate/129 |
| AVIO队列/shadow | 三stage原RMW已闭合，source1有公开来源，有限实现进行中 | 未完成 |
| AIP gate/事件时态 | b69dfe清理副作用、source5计数生产、任务唤醒分别调查 | 保持pending |
| 原始0323传输 | request/内外message/status/所有权静态合同已闭合 | 尚未实现整体reply，未验原AP消费 |

相关宿主测试当前36项通过；不与既有NoMem测试集合合计，不把子模块测试当固件启动证据。

## 剩余与当前验收界限

继续闭合AIP16系数/reset/gate/ready、source5时间生产和任务唤醒语义；
不能任选timer频率称原生Vsync，也不能修改getter或global阶段让等待成立。
资源/输入/配置及AVIO子模块不能单独授权整个0323回复。
只有全部具体状态/资源工作由明确后端消费并读回，才集成精确00580000回复、观察原AP释放，
随后推进0336/032d等实际前沿。成像、编码、JPEG/MP4另验。

`adf_proc_path_verified=false`、`ee_verified=false`、`capture_verified=false`。
