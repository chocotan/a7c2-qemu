# 原首设后的 APO1 自动关机：已捕获原包，唤醒仍未完成

同一新版窗口已实际逐页选择简体中文、以后设置阅读器、完成首设并打开中文 MENU。随后等待60秒会进入原 shutdown、LCD全黑；恢复显示尚未验收。此前蓝牙原管理状态短时读回1，只证明该启动依赖通过，不代表此后的电源状态已经恢复。

本报告仅本机隔离QEMU、官方2.01 ALLLANG，无真机/物理盘/真实无线。原`appFw.so` SHA256为`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。AP地址均为ELF VA；原状态没有裸写，错误没有屏蔽。

最新全部线程的同run证据已把group0 active boot及后续取消积压接到**原CameraBackground的3007状态转换等待**，见[当前boot依赖与虚拟接口边界](boot-cp-background-blocker.md)。MODE五档原显示已另行修复，但原boot收尾/省电恢复和拍摄仍未通过。

## 原始通知与屏幕

### 首设后进入菜单却触发 APO1（`98bc`）

原厂触控说明在第一笔 `MENU` 后仍显示；后续 `ENTER` 进入了原厂主菜单。`runtime/analysis/menu-runs/98bc/console.log` 第 13879 行记录 `0x920143`、原因 `8`，第 13921 行进入 `SHUTDOWN_ENTER`。`scratch/a7c2-apo-menu-round10b/runtime-1/` 的 `ui-43.png` 是菜单，`ui-45.png` 是黑帧；第 14148、14157 行完整接收原半按按下、释放，`ui-46.png` 仍为黑帧，未确认唤醒。菜单设置尚未改动，未进行拍摄。`result.json` 记录 QMP 退出确认、`rc=0`、未发送进程信号、租约持有至退出；试验失败实物保留。

这一轮确认等待操作时会触发自动关机，但不是 c184/L24 全按不执行的因果证明。对照操作按[原厂手册](https://helpguide.sony.net/ilc/2360/v1/en/contents/0601B_power_save_start_time.html)选择“设置 → 电源设置选项 → 自动关机开始时间 → 关”，不动温度保护。下一轮仅在隔离 QEMU 菜单画面等待宿主操作时使用已绑定的 QMP owner 暂停、恢复，避免将等待时间混入菜单测试；是否关掉仍以退出、重进后的原菜单值和实际原厂通知为准。

### 设置回读与第二次复现（`75e7` / `c35b`）

`75e7` 通过原厂菜单将省电开始时间从 1 分钟改为「关」，确认后退出并重进核实选中值；温度保护仍是「标准」。快门前的 guest 日志游标命令因 BusyBox 缺失 `stat` 而返回 127，所以本轮未发快门。隔离实例正常退出。用同一 AArch64 BusyBox 在宿主跑完整采样时，又确认旧命令的 `head` 也找不到，且末尾 `true` 掩盖返回码。下一轮脚本改用固定日志描述符和有界 `dd`，已通过同一文件游标、追加窗口、按键所属线程、残行、换文件与超限检查；验证使用合成日志和 QEMU 用户态，尚未在原厂快门路径执行。

`c35b` 第 64 步的按下和释放均被应用接收；随后控制台第 29074 行记录 `0x920143`、原因 `8`，第 29115 行进入 `SHUTDOWN_ENTER`。最后完整检查点是第 63 帧；本轮没有重新回读设置，没有开始拍摄或写卡。broker 已断开调试器，但没有完成邮箱解绑，隔离实例与磁盘租约仍保留。下一轮的宿主监视可直接区分 APO1、owner 保留、正常到帧和预算耗尽，两组宿主测试合计 31 项通过；不把监视通过算作拍摄或关机通过。

`c35b` 的 broker 事件 2508 首报读超时；事件 2510 保留模型取消结果，2511 的清理记录显示邮箱解绑超时、断开调试器时又收到了旧 QMP 回复。现有代码已改为发送或接收失步后锁存该连接，阻止后续命令继续写入；不改变邮箱解绑、持盘或退出门。定向宿主验收 20 项通过，含 135 个子用例。本修复未应用到正在保留的 `c35b`，也未在新 QEMU 上验证。

### 短 socket 实跑与宿主启动修复（`bd4b`）

`bd4b` 已在真实 QEMU 中核到同一进程的 4 个私有短路径监听器，并抵达 Linux shell。宿主 driver 随后在建立 QMP 控制前重复关闭已置为 `None` 的启动探针 socket；原失败收据确认了 `AttributeError`。本轮没启动相机应用、没到第 42 帧、没发快门，不能记为拍摄通过。

核对同一代际、四监听器及无在途写入后，独立恢复记录取得一次匹配的 QMP `quit` 回复和进程退出；QEMU launcher 返回 0，driver 仍以 2 保留原失败，磁盘租约持有到退出，未向 VM 或 owner 发信号。没有改动 `c35b`。第 18 轮修复了重复关闭和早期失败通知，19 项定向宿主测试通过，已启动新隔离盘；同轮省电回读、快门、JPEG 和整卡读回尚待验证。

### 第 18 轮同次启动对照（`1273`）

`1273` 用原厂菜单从 1 分钟改为「关」，重新打开选项核对并返回拍摄页。第 85、87、89、91 帧分别与此前人工确认的菜单、重开选项、返回菜单及拍摄页逐字节相同，温度保护仍为「标准」。本轮原厂控制台未见 APO1 或关机序列。

原厂应用在同一 PID/TID 下消费了半按、全按、全按释放和半按释放。实际 guest 的日志游标与有界追加读取通过：inode `21`，起始偏移 `10928443`，收据和原始日志留在 `scratch/a7c2-apo-menu-round18/runtime-1/`。仍只见释放进入执行层并发 `0x4039`，未出现 `0x4038` 或自然写卡；整卡导出检查按合同跳过。QMP 退出确认、QEMU 返回 0、租约持有到退出、零信号。下一步沿[全按路径调查](functional-camera-evidence/p1-candidate184.md)核对实际分支，省电没有解释这次复现。

### 最新：实际队列写点与取消对象静态链

`run-ns8rhlui`真实私有Unix GDB观察在原`24d8774`命中caller`262aafc`及单个request100；随后取得16次硬件计数变化，含`0→1→2→3→0`。发布写位于`24cba50`、停在`24cba54`；清零写位于`24cce14`、停在`24cce18`，同时原Q的前后指针均回到Q。观察上限16已实际触及，不将之后未记录的时段作否定证据。它证明该队列被处理，尚不单独证明同一R执行了取消序列。

main核原字节，实际批处理入口`24cc968`先依据每个request+8回调及批次计算+770，再按单项gate`24ccaa8`决定调用或跳过，最后释放原R/vector/node并清Q。单项分派表`5578920[100]→248db58→3242580→3110694`：构造函数的GOT`5b940d0`指向`5b3acd0`，实例vptr=`5b3ace0`，RTTI原名确为`N5model25sequence_power_off_cancelE`、run槽`5b3acf0=33dccb8`。构造后进入`3222ad0`；因此下一动态目标已收窄为**同一R→构造出的S→manager map分支/组队列→run或析构**，不再猜原门控是否关闭，也不由计数/free称消费已完成。map非空分支的业务语义仍不命名为重复/合并。

本轮两条正确sequence入口探针均实际ARMED，覆盖期间`POWER_SEQUENCE_ENTER=0`；60秒后的三张原LCD逐像素全黑，恢复false。调试器达到限额后正常detach，无强杀；CPU query确认running。SD独立读回SHA256 `2741c1bd8fe3a744030c267c175df4b5072fb29cbdb295c39e1cdf4f0ce8dc65`与export相同，原Flush rc0、fsck0、owner resumed另行通过。run内`queue-watch-review.json`保留限定范围，详见[只读观察方案](request-queue-watch.md)。

### 原计时重载与真实按键之间仍有上游缺口

### 同一R到取消对象的实际五点与观察缺口修正

后续`run-gbywdh97`实际匹配同一原R，+770读回1，命中248db58 handler；3110694 ctor及32425b8返回捕获同一新S，vptr验证为取消序列，raw18按原STRB读取1、raw1c/+20/+24为0；同一S随后进入3222ad0 manager（ID100、flags1/1）。这五个当前调用点的证据有效；尚未取得组入队/run/析构。

原观察器随后只等3222b64，主机结束观察的SIGINT被它误记为Unexpected stop。独立评审与main核原字节确认**3222b5c的CBZ可直接到b68绕过b64**；因此本轮未命中b64不是manager阻塞证据，更不能以之后同址对象当原S。原`queue-watch-result.json`错误与新`sequence-handoff-review.json`保留，未回填旧轮为成功。LCD三张晚帧仍全黑。GDB正常detach、无强杀，CPU运行确认，SD独立SHA256 `54749f67b6e89eab6b6a4d8479552339e806cb3e350d2269577b52c3b376f39a`、fsck0/owner resumed另行通过。

修订观察点为两支共经的b5c，增加原manager调用帧/返回边界、构造后即安装run/dtor生命期终止、R释放终止；只在原活对象/队列借用点读取。另将异常GDB退出后的CPU恢复移至独立私有QMP通道，任何后续串口/快照/GUI teardown前核运行；不能确认则保留own GUI/VM/Xvfb/控制邮箱，不硬杀持卡进程。新版本按host回归→无固件双monitor fixture→单一原固件VM依次验，不把本轮部分证据推广为恢复通过。

精确call/jump查询原`33b2b0c`为0，但main核到原虚表`5b38b40`引用它，RTTI明确为`N5model19sequence_mss_reloadE`。原run经`34da608→35a138c`构造并发原920204，包装器取原返回状态；它也是sequence对象，不能把它当作已经接通的直接按键回调。真实按键/半按到该对象的构造、登记及运行尚未闭合，没有为此主动发920204、改原超时或切换生产输入通道。该静态零xref不构成“从不调用”的结论。

### 原先捕获的通知

### 组队列实际关联、队头身份与原消费者

修订后`run-w3l7ybsv`确实走NULL hash分支，绑定原manager帧并把同一取消S关联到group0尾node+10，原count为254；覆盖期未见目标run/dtor，正常主机停止观察，无Unexpected错误。CPU独立QMP确认running，SD独立SHA256 `498b7ad9be0811956c4d78659296038f685e9c3952f6258f6050a4562f4bd0ee`、fsck0/owner resumed。下一版`run-g3kuuq9o`再次确认同一S入group0/count254，并在原组锁借用点读到**pending队头为`sequence_set_release_lock`，ID132（十六进制，十进制306）**，metadata中的manager与当前实例相同。它只是pending队头，不据此称它正在执行或造成阻塞。

后版实际生产`run_live()`的host回归覆盖SD会话输入Timeout/OSError/RuntimeError锁存fault、拒后续普通input/snapshot但保留失败/恢复export入口，非SD仍抛错；driver每个wait循环复核debugger。`b8ea4f973`为74 passed、2 subtests，加GDB导入与无固件双QMP fixture通过；实际g3kuuq9o CPU/own清理安全、SD独立SHA256 `5a35b30b7eb26b494a4b4de7f97de221586012b78b1bd064cab454a8845bdcbc`、fsck0/owner resumed通过。真实guest“强杀GDB＋独立QMP持续失败＋在途输入”的组合未注入，不能由这些host/正常guest结果称全部异常已验。恢复LCD仍false。

main已从现有公开源码注释取得窄候选并核原机器码，**`3209d48`确为组队列消费者**：r0=manager、r1=groupCtx；root=ctx+10、mutex=ctx+28、condition=ctx+58。`3209dd8`取node+10到S，count减1、unlink/free node；`3209e08`存S到ctx+88，解组锁后`3209e44`调S虚槽+10。run返回后重新锁同组mutex，`3209ebc`调用删除析构、`3209ec0`清ctx+88，再解锁。group0的ctx=manager+310，故active槽=manager+398；不再仅凭旧诊断注释称其用途。下一在原enqueue组锁下读取active身份（区别于pending head），然后GDB退出/CPU恢复后用已有只读menu-regs捕队列/池线程；原worker启动/注册及真实等待原因仍待证，不会手动调用init/run、重置锁或清queue。

`run-phyxlklp/console.log`的实际记录：

```text
POWER_NOTICE cmd=0x920143 src=0x80920021 bytes=16
             word4=0x8 word8=0x1b wordc=0x21
             mono=116.662723696 wall=116.662778624
POWER_MODEL event=0x100003c state=[0x11,0x2,0x2]
SHUTDOWN_ENTER state=[0x11,0x2,0x2] mono=116.675304880
```

原因子表`57fce58`将输入7命名为KEY，8/9为APO1/APO2，90为SYSTEM_ERR。因此**本次输入因子8是原APO1自动关机**；不是仅凭等待长度猜定时器。`word8/wordc`及转换后的三元组的进一步语义仍须核，不能直接命名成开关/重启状态。

`00920143→callback_off_cmd@35a3a40→通知70→2dce920→MODEL_POWER_OFF 0100003c→1b23e58`；原`1b24354`选择screen309。原屏幕表`58d37d0`确认309是`scr0039_shutdown`，343/346/347分别是拍摄/菜单/boot controller。shutdown入口`20a0bc4`经`274cfe0/274cedc`记录`set_pre_power_off_seq`。原SYSTEM_ERR标准分支选择30c，与此帧309不同。

原getter`285f8d8`返回`base+7e5dd88`的状态存储；本次只读记录其三字，不改状态。kernel打印时间与host等待窗口不同，不据早期dmesg数字推导实际省电设置。

## 输入与恢复的限定结果

- 直接App32通过`5503e0`，原Infra20通过`807a0020/92840747`；两者都实际完成指定中文首设和MENU。
- Infra20在`libObj`更新键缓存、强制from=1并经原callback转App32。它与直接App输入不等效，但本次MENU也没有在APO后恢复画面，不能据此宣称已接物理唤醒。
- `run-7eagcw4z`之后的Fn采图遇共享`ui-display.ppm`被自动快照改写的测试竞态，原失败保留。新测试只读取VM已校验PNG的不可变序号副本，核其RGB SHA；该测试修复不代表Fn已通过。

原恢复输出入口已静态定位为`0092015a→INFRA_POWER_ON 71→MODEL_POWER_ON 0100003d→API3b0b`，或`00920145→INFRA_POWER_OFF_CANCEL 72→MODEL_POWER_OFF_CANCEL 0100003e→API3b0c`。它们是原电源管理器的通知，**没有向AP直接注入这些包冒充设备恢复**。仍须找到原活动重置/省电时间设置与真实虚拟电源输入的消费路径。

后续显式实验通过原allocator向原UPM发16B请求`{920142,8,0,0}`（source92840747→dest80920021），由原kernel生成`920145`。首轮`run-i1fx01n3`误把void `osal_set_msg_src`残留x0当返回值、没有发送，已纠正原型，失败保留；`run-w54hcpok`及后续才真实发送成功。该实验默认关闭，仅在已观测APO1后请求一次，不代表正常物理唤醒。

`run-l6f2wi2w`原920143/920145分别发生于mono117.951/119.754；字节checked、完整ABI重放的入口探针确证随后命中`20a079c`取消专路，未命中`20a073c`普通power-on路。两路都可创建公共boot308，因此早期仅有308并不足以区分；当前已完成区分。308与上述347原boot controller不是同一对象。像素仍黑且无343，整体恢复仍未通过。此前`run-k7li_uui`按create_screen实际UI tid302取栈，处在原输入接收循环，不能继续称其卡在future或promise。

原取消wrapper`262ab3c→262a8ec`更新多个模型属性。后续独立复核原虚表/RTTI纠正了本报告的入口误标：**取消序列run为`33dccb8`，`33dcf50`属于`sequence_power_on`**。RW槽`5b3acf0`（fileoff`5b2acf0`）实际指`33dccb8`，RTTI为`N5model25sequence_power_off_cancelE`；`5b3ad40`指`33dcf50`，RTTI为`N5model17sequence_power_onE`。先前由邻近源字符串把后者标作cancel的判断已撤回。`33dd04c`是power-on内重发`01000090`的分支，不能直接当取消序列进度。

真正cancel的构造快照含`+18/+1c/+20/+24`。原`33dccdc`依据`+18`选择`34dac88`或`34dacc8`，再受其它原快照值及返回结果约束。`262a8ec`以`(1,0)`调用三处API形成`100/a3/4ed`请求；只有`[7e4e608]`非0才入原队列`7e4e5d0`。请求消费→处理器、调度器→run仍未闭合，不能直接归因某个属性或因缺日志认定未执行。没有补发内部事件或裸写属性。`36eb21c/36eb3f0`只作profile耗时/次数统计，不是业务分派。

纠正后的实际`run-eag31593`记录了原APO1、原`920145`和`20a079c`命中；两个sequence入口探针均安装，但本次覆盖期间没有任何`POWER_SEQUENCE_ENTER`记录，故没有对象字段可报告，不能将其补为0或称历史上从未执行。晚期MENU、主界面、重开MENU三张640×480原LCD图逐像素全黑。原SD仍保存成功，main读回SHA256=`33197cca898c6c418b4018af2673e8edb4e4cf8cac4da85f56c70a3c9f676f30`、fsck0、owner resumed。`sequence-entry-review.json`保留总体false。

下一观测边界缩小到请求100的原门控：`24d871c`在原锁内取`7e4e608`字节至w23，`24d8728`的CBZ决定跳到`24d8780`退出或继续构造并经`24d8774→24cba1c`发布。只读记录该实际w23值及publisher入口，保留CBZ的两条原分支；不设置门控、不直接调用API、不创建替代消息。publisher入口记录不等于消息已被消费。

静态直接STRB搜索另找到两个原函数：`24cb93c`在同一`7e4dc38`锁下将门控字节置0（store `24cb960`），`24cb978`置1（store `24cb9a0`）。这是ADRP后8指令内直接写入的候选集合，不是穷尽所有写法；其实际调用时机尚未核，未调用这些函数或裸写该字节来强行打开队列。

实际`run-3skx40nj`把此假说进一步缩小：原`920145`后进入取消专路，`POWER_REQUEST_GATE`记录`original_gate=1/value=1/argument=0/caller_app=262aafc`，且原`24cba1c`发布入口执行、队列为`7e4e5d0`。所以本次不能归因为门控关闭，也无需调用上述setter。仍未看到sequence run入口，下一未闭合环节在发布后的消费/处理/调度。发布入口不等于消息已消费。

请求构造`2494bcc`原件另已核：分配778B，+0写ID100、+4写原uxtb参数、+8写原参数x2、+10复制原handle的u8或置0、+770初始0。这些字段的业务意义不得靠名字补齐。相邻`24cba60`按ID查找并删除/保留batch的控制流不能直接称作调度器。该run晚期MENU仍逐像素黑；SD main读回SHA256=`c751bd9c248d8a1cd3f6d69ca41517f787ccefa6b9d10d89cb882c5aea6f7581`，fsck0、owner resumed，总体仍false。

末端三个静态候选也未闭合消费：`25061ec`属于`2506054..2506218`，`25065c8/2506760`属于`2506520..2506808`；所见登记回调返回对象加入新向量，再经`2506114/2506690/2506700→24cba1c`发布。这些回调发生在入队前，不能拿它们证明消费已发布的同一个request100；去重失败释放的是新建对象。后续须以同一节点/batch/request的可达性、出队写点及后继调用关联，单看计数或free不足以区分丢弃和交付。

下一静态分析使用独立官方AP副本核计数`Q+10=7e4e5e0`及别名引用，禁止改原件；若需运行观察写点，仍只在本机隔离QEMU调试。当前尚未安装计数写监测，原队列门控和状态均未修改。

## 观察方法与否定结论纠正

### 用户要求的最新中文首设重试

`run-3b2woc1z`按当前入口在私有显示环境重跑，显式virtual-rom-v1、只读电源观察开启、自动撤销实验关闭。主会话人工核图确认原简中选择、阅读器“以后设置”、机上设置后拍摄HUD及中文MENU；60秒后为全黑，MENU未恢复像素。原通知在mono118.142978624为`920143/src80920021/factor8`，随后原power model及shutdown入口执行，因此整体仍不通过。保存前管理状态00发生在关机后，不用它推断此前蓝牙是否连接。

SD原Flush/恢复及导出通过，main独立读回镜像SHA256=`e3c579ac6a86a98595a7764e19aba4c8b386af43a153971af076a66ea4cd6412`，fsck0、owner状态resumed。该run的`chinese-setup-retry-review.json`保留整体false与限定通过项，未把黑帧、数据库/XML或SD保存当成拍摄/录像完成。

`A7C2_CAPTURE_POWER=1`仅显式启用原字节校验的入口探针；保存ABI参数、FP参数及NZCV，完整重放原指令。`35a3a40`原CBZ保留；另外观察原power-model和shutdown入口。默认关闭，不构造关机/唤醒事件。

前两轮虽记录ENTRY_PROBE_ARMED，但新增前缀没有加入既有console镜像，只写有界内存日志；所以“终端没看到”不证明回调没执行。修复`POWER_/SHUTDOWN_/SD_ACK_`日志输出后才得到上述通知内容；旧失败结论没有改成成功。

同run已实际看到`SD_ACK_BIND`四个非空函数指针，以及`SD_ACK_RETRY_WORKER … detach_rc=0 ack_only=1`。它证明独立确认管理线程创建，**不替代guest故障注入或实际ACK重试消费证据**。原Fsys正常保存/恢复另见[SD持久化报告](native-sd-persistence.md)；本run卡SHA为`52fd77a9be155096ef103e9eedb461232b096e61f8a112e058bb2ec82af4455e`。

## 第19轮（run 1d52）：Off 写入路径走通、等待预算缺陷终止实跑

第19轮在隔离观察器（menu-observe.so `13934a8e…`，overlay `5600bf5e…`）下复现第18轮菜单链：帧42与第18轮逐字节相同（`5ba90a96…`）。逐帧匹配导航中三处UI漂移（43、57、79 附近）均以 refresh+人工核帧纠正后重新对齐，最终 `76→87` 段与第18轮完全一致：`Power Save Start Time` 选中 Off、ENTER 确认（84→86）、重开取值画面（87）。`apo-menu-readback.json` 未写出，快门未发出。

终止原因不是 guest 故障：`wait-apo-early-notice.py` 的帧等待预算锚定在 owner 启动时刻（`started+budget-now`），菜单导航至 1266.9s 时预算耗尽，监视器写下 `stop-after-action` 协作停止标记，driver 以 `TimeoutError('APO experiment stopped before dispatching the next action')` 收尾。退出本身干净：`qmp_quit_confirmed=true`、rc0、零信号、lease 持至退出、runner closed；`capture_verified=false`、`status=skipped-no-natural-capture`。证据保留于 `scratch/a7c2-apo-menu-round19/`（attempt-1.json sha `1dba7637…` 同轮收据）与 `menu-runs/1d52/`。

修复（第20轮起生效）：`watch()` 改为只读——单帧窗口 ≤150s、超时仅返回码 3、不再写任何停止标记；运行总期限完全交还 driver 的动作 deadline。宿主测试 `test_wait_watch.py`（2 项）验证只读超时与帧回报。第20轮首轮启动 5.9s 失败已归档：外层缺 `A7C2_SETTINGS_RESTART_PROFILE=functional-ram-card-independent-internal-v1`，环境合同断言拒绝（attempts=[]、未启动 QEMU）；带上该键后 `session.prepare()` 自行派生本轮内部盘实例，run `b459` 正常进入启动。

### b459 的真实结局与第21轮

第20轮 run `b459` 带组合 profile 键重启后走得更远：首设 41 键 156s 完成、MENU 帧42 于 315.8s 产出，但 327s 在 broker 挂接前失败——宿主环境还缺 `MENU_MODEL17C_RUNTIME_OBSERVE=virtual-model17c-runtime-ro-v1`，`model17c_early` 默认关闭直接返回 None，UPM watch 退化为无绑定的 scope-only 模式（`model17c_runtime` 不进 watch 配置，`seconds` 120≠2700，bridge 事件无 `kernel_task`）。随后产品缺陷被第一次触发：`Correlator.feed` 的 bridge 分支无条件引用仅在有身份时赋值的 `tid`，抛 `UnboundLocalError`，driver 以 "did not prove both original native lifetimes" 收尾。QEMU 干净退出（rc0、零信号、`qmp_quit_confirmed`），`capture_verified=false`；证据保留于 `scratch/a7c2-apo-menu-round20/` 与 `menu-runs/b459/`。

产品修复：bridge 分支现在先 `require(task is not None, 'Identity-less bridge observation cannot prove a lease lifetime')`，明确失败代替未绑定变量崩溃；回归测试 `test_identity_less_bridge_fails_closed_instead_of_unbound_local` 以真实 upm/osal_uipc 模块构造 Correlator 验证。第21轮 run `9d21` 补齐两个宿主键后 `early_observer armed=true`（94.6s），model17c 绑定恢复。
