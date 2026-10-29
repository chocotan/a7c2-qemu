# 当前功能验收边界与所缺的最小证据

**2026-10-29 当前完整基线：`unified-camera-3lbiw8e9`，4693 tests /5740 subtests，172模块、442运行源/934唯一输入，host/guest构建与双原glibc2.25 ABI通过。当前原生仍不能拍照写卡：`capture_verified=false`。**

最新`run-qqu0q5oe`语言逐键LCD消费真正通过，但首启把温度模态误作shooting；原系统错误画面30c先于快门。两条SP锚定连续保存FP链和原BL字节证明：Common382在`339fa08→3548c20→local21 future`，串行CameraBackground339已被更早24B/3006/source810261c4的动态queue回复等待占住。尚未到3003/VDF/后继C组/编码。裸返回ENOTSUP不能作为修复：原ed9c4非零send路径折1后遗失request和动态queue，本地21还可能等待独立资源事件。正常3006物理CP模块/掩码仍未验证。

新功能owner将以明示软件设备初始化替代未知物理模块：真实原3006保留pending→同轮实际13连接原free及原HDMI debugger交接→实际Core INIT和STATE128同实例完整读回→原request真实释放→独立12B/3006回复→原sender实际receive与free0。只在完整因果链后计functional transport，不提高CP模块、hardware/image ready或capture。main可信libObj返回eda50/原BL39b3fd97双读、动态source绑定、guard29延迟桥、末13实际free推进和TLS接收票据已接，owner/C wiring/真实Core组合/checker正同批完善，**尚未整批测试构建ABI，也无新VM证明这条链已通过**。

首启修复定向75 tests /139 subtests和4个直接调用方通过，仍须新原生完整首启复验。现成非射频虚拟HCI/原BSA计划加入下一综合运行，保持实际命令/backing与原IPC，不忽略系统错误；其host测试不在旧172集合，已加入新整批。SystemError首producer并未唯一确定，不承诺一项修复消除全部错误。

qqu原Fsys Flush0后两DB导出/宿主摘要通过，卷退休及firmware-format仍false；没有JPEG/MP4。runner broker-never-attached/safeclosed，本项目系统QEMU实际已无；closed-file quit错误保留，退出方式未独立证明。详[本轮失败收据](verification-with-language-and-background3006-failure.json)。旧卡已用不可复用。后续原1006自然producer、retained RGB/FrameCapture接口、真正ResizeEnc1500cmd2/P128 writer、Movie初始extent/ring/Combine最终MP4与FSYS_SYNC内容仍缺；最后必须原AP/编码/MPR/Fsys/SD同轮独立解码。

以下为此前阶段及严格物理profile边界，保留其当时结果；其中“正在整合”不代表当前代理状态：

最近完整代码批次 `unified-camera-9js4cyzh` 为 **4260 tests / 2838 subtests、168模块、438运行源/896冻结输入**，host/guest构建和双原glibc2.25 ABI通过。原生 `run-52od7asp` 已验证原0141真实global/source `80946189`精确绑定及独立1141 receive/free，六个VDF周期均有921600B实际RGB sink消费/读回/退休和原AP free。mode1 ACK与1748B通知也已原free，随后AP3549328在20a6 `(0,0)` 转换处fatal；**mode1传输与AP业务应用分开，尚无原JPEG/MPR作业或JPEG/MP4**。此前rk07的0141误拒/超时仍见[历史分层收据](verification-with-startup-stage-mode1.json)，不回填。

当前新组件：五条neutral BB配置OP9（32→192/class5），首个enabled/mode1 histogram OP10（8→1192/class6），独立1148与1034B210c通知。真实core→guest组合268项通过，四段软件Y/R/G/B各256个u8柱高由同一实际RGB独立计算并逐字节核对，request/ACK/notification三个lease实际释放。唯一snapshot ID、真实event_role、三lease join及线程交错检查已完成；主接线C/SAN 98项、profile98项通过。[范围与未验证矩阵](../functional-histogram/README.md)。**仅支持neutral配置/首帧通知；原AP/UI应用、连续histogram、非neutral参数和物理bin语义仍未验证，不能称完整直方图功能恢复。**

20a6新软件owner由实际State128 FPS生成精确 `(fps,1)`，默认30/1，非canonical clock在ACK前拒；3projected/72zero，253场景×strict/SAN通过。原AP尾部三个完整converter与13个标量的zero域已静态核对，无新增非法零。时钟五字段/source generation及新golden的证据接线尚在整合，**还没有新原生运行证明AP已完成mode1业务应用**。

原主JPEG SDK/MainComp合同已静态闭合：1226c4与旧Without_Pin11b654是不同对象/入口，Main ACK返回0、DONE由另一MainComp对象处理；不能仅放宽旧quality检查或复用同一对象回调。正在扩展共享adapter并保留实际原Exec/原OSAL request、真实Core编码、输出SDS lease读回和原Res/Close。输入帧producer/lease与1006/event9自然producer、type/source/真实总长度仍未知；不得把reader最低长度当原包长或强发event9补齐。

52故障已独立保全两生成DB文件，实际broker CANCEL0/128→DETACHED/physmode/debugger、errors=[] / safe=true后仅一次普通QMPquit正常退出，无QEMU信号；GUI/专属display及既有双锁收尾已核。原host Fsys-save仍false，旧失败保持；旧卡o99qcjv6不可复用。当前新源码未冻结/完整回归/构建/双ABI，不可用旧ready启动它；待全部稳定后新空卡/intent一次综合VM。

graph 的 vvfat-only BB PIN_QUERY 修复仍要求真实 Get/原 free 内容 join；q2 的第14条 free 原字节被 warning 插入打断，不补造或回填旧负例。录像原 UI FHD/AVC/AudioRecording-Off、自然 Stop→Close、同步初始 extent/source lease、Combine 最终 MP4 贡献与 FSYS_SYNC checker ingestion 仍欠内容证据。`capture_verified=false`。

**2026-10-28 路线更新：** 用户已明确批准独立 `virtual-functional-camera-v1`，对未公开 ASIC 图像布局与总线采用明示的软件 RGB888 模型。下方物理/原 CP 源合同未知继续适用于严格 profile；新功能路线由实际虚拟设备行为和完整原 AP/MPR/Fsys 数据链验收，物理兼容性仍单独为 false。核心、控制/桥、原codec/JPEG SDK及低32位内存设备、同帧内容收据和当前批次13边checker已集成并全量自测。host解码与组件通过不能提升为原AP成片；实际SDK请求、输出lease、原接收释放和最终SD文件的同轮因果证据仍待验。

功能路线的下一份成功证据必须在同一轮关联：真实原 SDK 请求、模型实际帧/编码结果、guest lease 写回读回、原 MPR/Fsys 请求及完成、虚拟 SD 两次导出一致和 JPEG/MP4 独立解码。host 独立生成文件、probe 仅 rendered=1、send0 或配置暂存都不能满足；`capture_verified=false` 保持。

严格profile的既有源合同代码轮`unified-camera-f3_eny7y`为3253 tests、381 subtests、0失败，398运行源、789项输入/归档逐成员读回一致，构建和双原libc2.25 ABI通过。见[历史收据](verification-with-encopen-and-bank3.json)。其最后系统VM`run-nzx01uc3`仍3003等待、EE0、无原JPEG/MP4；该历史边界不等同于上方功能profile最新进度。

本轮已经把独立config word2→copy→bank3→getter/FLAGB0事件接进owned bootstrap；未知recopy会撤销其knownness。原EncOpen的98h参数解析已补，原setter Md2d60及metadata队列寿命也已正向闭合byte88=0。它们分别是局部源消费、组件解析和静态生产者证据，不证明原worker当前值或实际逐帧YC/SDS lease；新parser未接原runtime编码入口，gap63保持。

只读源调查已经追到VBB实际寄存器编程；继续增加地址复制或完成通知不能代替像素布局与消费证据。下表给出可以声称的范围，以及升级下一层结论必须具备的内容。

| 域 | 已有内容型证据 | 当前缺口 | 最小闭合证据 |
|---|---|---|---|
| CP启动 | 四字节算法、同stage公有mode/profile/ALH、本地参数写、独立bank3/FLAGB局部传播、LIF有限握手/cache | 3003结果仍0/4；M/C、gate/Q历史、worker实际发布、full76源根 | 源可闭合的初始化/输入/调用/发布链及同epoch字节；注册指针或BSS位置不提供当前值 |
| CMOS/光学/AF | 真实RGB、光学/对比度AF和codec组件在HOST内存组合测试 | 原AP/SDK未消费这些帧；原帧lease/格式未接 | 同一有界源帧经实际原请求所选输入被读，内容/epoch/extent可核对，不能仅记录配置或计数 |
| 原JPEG | 原尺寸保存/SOF、coding表、IRQ路由；decoder SOS模板；实际HOST JPEG输出/独立解码 | native YC顺序/plane、scan/restart控制与coherent lease | 同一原输入格式定义或同lease字节行为；encoder固定a0/a4常量不能命名restart或把typed host baseline改称native |
| 原录像/VBB | 单EncOpen98h参数解析、原byte88=0 producer/metadata寿命、原请求/元数据、88→96、环/借用AU/NAL及源寄存器编程；87行数值归一化 | pixel direction、row/plane extent、packing/bit depth、真实engine completion、ES源载荷 | 指定寄存器的规范或绑定同一实际buffer lease的读/写/完成行为；不能从gate非零或start=1推出像素已完成 |
| SPS尺寸 | CPU writer Q14/Q18的H.264语法、队列指针和条件8421路由 | opaque worker selector、实际header选择、Q与实际P/B关系 | 正向transport/selection或字段copy证明；coded grid与logical crop分开，不把full count/masked field混用 |
| 原MPR/Fsys/SD | 异步描述符/回调/worker追踪、原Open/Read/EOF/Close、双flush/host摘要、独立decode checker | 无原codec媒体输入，因此没有原成片写回 | 同一实际源帧→原codec作业→原MPR/Fsys贡献span→原读回/两次导出→独立JPEG/MP4解码；写回checker本身不证明帧来源 |

## 不能由现有资料直接升级的结论

- [VBB gate配置来源](../imola-vbb-input-configuration/README.md)证明同址write-side含配置，但read/write硬件语义不一定相同。不能称纯bufferReady，也不能以gate0选streaming或让设备伪造nonzero。
- [原CPU颜色reader](../cpu-jpeg-codec-evidence/README.md)支持YUY2/UYVY/NV12，不代表camera allocation选了其中任一个。现有有界搜索也不证明整份固件没有software JPEG。
- [SPS队列](../imola-header-job-queue/README.md)的F是第二参数管理上下文；105268为pin窗口起点而非constructor入口。 [具体route](../imola-header-dispatch/README.md)为8407→conditioner1b、8421→header19，当前仍为条件关系。
- [MCU ISA核查](../imola-ipsx-isa/README.md)中MIPS64可解码不等于实际语义；unknown…001c、70000026等不能当作乘加或NOP。有限normalizer的普通指令证据不能推广到全MCU。

## 像素格式证据需要区分什么

若以后获得公开SDK/寄存器定义或现成的参考缓冲，它需要绑定到同一original0或JPEG输入的具体配置、尺寸、pitch、地址/lease和处理阶段。仅一个Y/C名称、stride=2*W、一个已编码JPEG、通用library format、全零/全FF或中性平场样本不足以区分Cb/Cr顺序、行padding与tile边界。有效参考需包含可区分的luma/chroma与跨行变化，并标清其来源；不要求也不授权当前会话访问真机或私有配置。

当前仍按源证据推进：可验证的数值/协议块实现后整批自测；未解释的硬件操作不以success ACK或独立host媒体代替。[原AP失败处理核查](../cp3003-ap-failure-contract/README.md)已证立即send非零会fatal assert，非F000被局部忽略也不提供CP错误回包来源，当前没有可用合法降级。[LIF完整前缀](../lif-initialization-prefix/README.md)仍无M/C值来源；先清零时的历史P不能用后来绑定反推；989d5c具体初始化路径已闭合为参数getter，不写M/C，其对象运行时历史仍未证明。[新条件writer](../lif-input-conditioned-writer/README.md)可在selector6输入下按index写M/C，record在adjustment表暴露；实际输入与启动执行未知，不作为default。实际整机VM留到相关数据合同可执行后综合验收。

[零分支START后继](../native-video-zero-branch-frame-input/README.md)已收取并核12窗口/6792B：在实际call134688→1363a4处重接旧source-record合同，14fcd4得到的是S88编码输出数组，136e1c运输其START配置。它不提供YC输入平面或frame回调；继续在同一输出metadata链增加copy/通知，不能补出真实帧来源。原始CMOS/ISP输入producer、同配置像素布局/lease与实际完成仍需正向证据，相关值继续ENODATA/UNSUPPORTED。

进一步[CP3003 producer核查](../cp3003-error-producer/README.md)已证外层拒绝也调用16B/F000/四数据completion；guard返回-1/-2为内部控制，不是已证wire status，不能实施错误包推进。[RC真实SOURCE](../cmos-isp-resize-input-source/README.md)为T+08→J+10，地址J+18，来自P+70/+78；T+90/J+98是destination。最小新上游缺口是1d2f00之前P+70/+78的writer、同帧lease/producer；下游是2108d8/210bbc/210c3c背后的命名输入格式与实际传输。12窗口/9932B仅证明字段/descriptor编程，不证明YC像素消费；两项后继共22窗口/17744B源核查不增加3253代码测试数。
