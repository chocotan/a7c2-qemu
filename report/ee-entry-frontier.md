# AP EE 入口前置条件：静态证据与动态边界

## 2026-10-26 最新：全部13条图连接已原验，接续302c成像启动

`run-ouc1t64_`/898a03 observer/321冻结输入已同时完成全部13条连接：13份56B完成由原AP258/TID381同sender释放rc0/fault0/ap1；HDMI11两条原内核UPM完整消费/free收据和24条原task_hdmi条件receive/free，OSD12独立16份e1700持久资源/48笔DMM/16次SSOS映射消费均通过。整份选中initramfs保留、本轮双原Fsys flush0/STOP恢复/host三文件摘要/cleancommit/退出双锁通过。独立终审无已证实P1–P3，完整重放一致并拒绝19个破坏反例。见[最终图连接报告](all-graph-connections.md)和[13边收据](thirteen-edges-native-proof.json)。

原AP下一实际请求仍是type0、24B的302c，目标`90030001`、source`80020002`、opaque`80000027`，当前未应答。它使用独立中央sequencer current域`u32[CP RAM 1a52ad4]`，不能借CP cold mode3、BB word或ADF phase填成6/8。正常链已核为external302c→family0/event17→internal3041/mode0→family1/event32d→专用302c/f000回复；直接走通用mapper会选择错误301d。

新源码调查定位variant来自CP构造输入向量+8的Backup键`000300a7`。同一公开CP bank实际4B值为0，并由两份BK4 checksum/whole seed SHA和文件偏移`11ece0`验证，AP表不存在该键。这闭合了公开源variant值，仍不证明原CP构造已执行，也不证明当前状态已是8。若独立确认起态8，variant0会包含module2并要求最终817f；起态6的路径与完成条件另核。见[状态前沿](cp302c-state-frontier.md)和[variant源读回](cp302c-variant-source-readback.json)。

当前继续闭合中央启动writers及family1 phase1/phase3的真实模块消费者，不能把图连接完成计入中央模块mask。EE仍0，帧、JPEG/MP4与capture均未验证。

## 前次阶段：六边已原验，7/8/9/10/13联合集成

`run-4gqygshc`/7ed598 observer/291冻源通过前六条有状态边：六份唯一56B完成由原AP259/TID382释放rc0/fault0/ap1。H8c00沿同一pool完成九DMM/三通知/三次实际mapped读，更新同VEF current、BB expected及Imaging={1,1,1920,1080,3}，末Free后owners/opens/live全0，原命令/格式和NoMem/AB S0/旧ordinal1历史保持。1364/139回归、原libc2.25、独立全部源/内容/11反例、本轮双SD导出/三文件摘要/cleancommit/退出双锁均通过，见[收据](six-edges-native-proof.json)。

按用户要求本批并行实现7/8/9/10/13：7为32B event8+RawPinManager/ordinal15零格式边；8/9/10复用同一12B event6引擎，保存原64B请求并消费独立72B回复；13使用现有HDMI owner写+60共享audio-connected=1并读回，所有原HDMI状态的true分支同效。13允许在11/12未完成时独立验收，因此本批若通过应称“前十条加第十三条”，不能称全部13条。当前仅代码/宿主阶段，新原运行未进行。

11的HDMI当前状态不能从旧日志缺席推得；新observer补齐全部入口审计及旧HDMI photo日志镜像。12实际需要四份peer格式和八份source格式，unit=e1700、双向0102、SSOS和known mask，不能借404池、忽略未知字节或只开放3→3就回复成功。两边按资源、消费者和日志合同继续并行闭合，详见[本批报告](remaining-graph-batch.md)。

已验六边run仍EE0/7连接拒绝/302c未完成，无JPEG/MP4。仅连接/控制格式消费通过；原CP/RTOS/页表/硬件和图像帧未验，`capture_verified=false`。

## 前次边界：前两边已通过，第三/第四边并行集成

`run-en0re8bn`在33c007 observer/282同轮冻源上通过首数据/格式边与第二type8控制边；原AP258/TID381两份唯一56B回复均free0/fault0/ap1。type8 marker及posthook零格式副作用、旧SSYN数据/cache/引用退役保持，715/139回归与独立消息/归档/SD复核通过。本轮双Fsysflush0、全树三文件摘要/cleancommit和退出双锁已核。见[第二边报告](imaging-control-edge.md)。

剩余11边仍negative，第一条type3 `{3,2,0,90050004}`→`{3,1,0,9058003f}`已并行实现，117宿主组合场景通过，原ADF为10对象/slot4；分支只有握手，type5-only guard不选中，不能声称PCM/新B0或时钟消费。第四BB OUT1→VEF IN1等值格式边也已并行实现104项测试，包含同步f008和实际SSYN02/DMM Close/Free0，尚未原运行验收。

原图planner最后仍停在未完成302c；起态/variant/模块mask消费者未知，禁止空ACK。EE1/0/0、取景黑、JPEG/MP4零、capturefalse。主会话统一接公共profile/observer/ownership并用唯一VM串行验证，各代理继续独立边的实现/审查。

## 前次边界：首条图边/控制格式通过，继续type8边与成像启动

`run-509c5q1z`已实际消费第一条9005 OUT1→InfraBB IN1的握手与格式：sink marker写1/读回、真实DMM404映射SSYN80B/16B payload解析、cache5={0,1,1920,1080,0}、Free退役后唯一56B回复由原AP258/Common381释放rc0/fault0/ap1。本轮双Fsysflush0/host全树3SHA/cleancommit/退出双锁通过；592/139回归、原ABI和独立源/日志内容复核通过。旧run9rv漏marker保持partial，不回填。见[报告](imaging-first-edge.md)与[收据](imaging-first-edge-native-proof.json)。

下一实际type8 `{8,2,0,90050004}`→`{8,1,0,9284074a}`已源审，需普通握手和独立sink marker；posthook因index0不在3fe mask退出，无DMM格式。本阶段正在实现，尚未原运行通过。其余12条连接仍negative，后续302c/24B实际存在但模块转换起态/variant/选中消费者尚未闭合，不预ACK。

EE仍1/0/0、拍摄HUD中央黑，host只有83B INPUT/database/XML。JPEG/MP4均无，`capture_verified=false`；已验的是有限虚拟首边及控制格式，不是原CP/RTOS/页表/硬件成像。

## 前次边界：三笔InfraImaging Get已消费，图连接与302c仍未完成

`run-2r73dber`/65f4 observer/264冻结源通过独立六端口owner的3笔Get：键(0,2,1)/(8,2,0)/(3,2,0)均有精确48B请求/56B独立回复，同原AP PID258/Common381的tid/sender/waiter/lease/指针释放rc0。131相关回归、原libc2.25加载、冷Get独立source/code审查通过；本轮双Fsysflush0/STOP恢复/全树三文件SHA/cleancommit和退出双锁均已核。见[报告](infraimaging-get-90050004.md)与[本轮收据](infraimaging-get-native-proof.json)。

原AP随后实际发13条64B Connect，均明确UNSUPPORTED，最早一条为90050004 OUT1→9284074a IN1。图planner在错误路径继续，最终实际发`302c`/24B到90030001（`00002c302700008000000000000000000000000000000000`），当前Common381在futex syscall98等待；不能因已到302c便认为前面连接成功。现在先恢复首边真实握手、DMM404/SSYN格式发布与source消费/引用生命周期，并并行审计302c的内容依赖。

EE仍1/0/0、group0 current2f queued31→40；host仅78B INPUT/database/XML，无JPEG/MP4。`infraimaging_get_native_verified=true`仅指三个Get，`connection_verified=false`、`DMM404_format_consumption_verified=false`、`capture_verified=false`。

## 前次边界：BB0110已消费，实际90050004查询等待

`run-42_4pb06`用25eff observer/263冻结源完成有限target3/opmode0虚拟BB工作：source-image同owner提前构造、86笔前驱保持模式状态、实际0110写opmode、1760B数据与有效mask复制读回一致、双级work/两次21a、唯一独立1110回复由原AP释放rc0/fault0/ap1。本轮双原Fsysflush0/STOP恢复/全树3文件SHA/cleancommit/owner112459与组/QEMU退出/双锁实际独占均通过，无SIGKILL。见[BB0110报告](bb-set-mode-0110.md)和[通过收据](bb-set-mode-native-proof.json)。

回复释放记录未单列PID/TID，收据保留这一边界；紧接着原Common382/PID259实际发送下一48B查询，证明原序列前进：

```text
target=90050004 source=81cf61c4 bytes=48
c461cf81a0a0a0a00100300018000000300000007f000000001000001800020000000000020000000100000000000000
```

主会话已核AP实际语义：`get_infra_pin`位于`connect_infra_pin`内，是连接前的第一次Get；保存FP候选为dataflow33c5c→appFw3510ff0/3511158/35113a4→35a9c98/35a9eb4→34dc514→339d998→33aaa3c。原用户栈两份采样均在syscall29，前后SP/PC相同，但不是原子采样或正式unwind。栈内实际source `{90050004,0,2,1}`、sink `{9284074a,0,1,1}`；AP期待56B外回复/32B内回复，返回完整owner/type/direction/index必须等于输入，再查询第二端并进行后续连接。见`next-90050004-AP-source-pins.json`（ELF和原栈字节摘要）。

该source SID没有既有native handler，不能借用sink的infrabb owner。CP source构造/初态/回复与sink后处理正独立调查；第一个Get子步骤和完整连接分别验收，不预置connected。EE enable/source/status仍1/0/0，group0 current2f/stop0、queued31→40，卡上仅74B INPUT/database/XML，没有JPEG/MP4。虚拟BBState不等同原CP live RAM、两级本地task策略不等同原RTOS调度，`capture_verified=false`。

## 前次边界：032d原AP已消费，实际set_mode0110等待

`run-6_xlrsnt`用a2eb observer/253冻结源与同一a0d候选，通过完整20B格式、同Monitor Notify2新B0、同bank累计21写/读回、真实guest event9及AVIO同mask8单NoOp工作；原Common381释放132d rc0/faults0/ap_consumed1。SS活动与Monitor+243保持未知，旧AB1/task0x1004及七条未检历史保留，不强造S1。

本轮两次原Fsys flush0/STOP/恢复、host全树3文件摘要/cleancommit、owner38107及组退出和双锁实际独占通过，无SIGKILL。原失败`run-t558xqh9`与首轮032d启用链失败`run-c2idzc8s`分别保留。见[032d报告](adf-set-output-032d.md)与[原运行收据](adf-set-output-native-proof.json)。

随后原AP实际10B `0110`：`0d2010010a0001800000`，目标92840747，动态source81cf61c4。AP API为`infra_wrapper_bb::detail::set_mode`；本轮原输入两个u32是(2,0)，builder转换为尾部0000，不能按空参数ACK。候选原栈链`34e5788←34e7c84←34c59c4←339d91c←33aaa3c`与两份同轮快照吻合；它仍是raw栈扫描，不冒充正式unwind。CP处理工作与正确状态域仍需源证据，不能从AP可兼容raw0推出本请求应回0。

CP路由已进一步定位到BB/DISP ExecModeHandler event19，原1110成功reply为raw0而非ADF命名空间；真实模式任务另行排队，状态owner和子任务尚未闭合，不能空ACK。详见[BB set_mode0110](bb-set-mode-0110.md)。

EE enable/source/status仍1/0/0，Backup pending0；Still/快门后group0 current2f/stop0，queued31/40。JPEG request0，SD只有INPUT/database/XML，没有JPEG/MP4。`capture_verified=false`。

## 前次边界：0336原AP已消费，032d输出配置等待

`run-t558xqh9`以c436 observer/247冻结源完成0336元数据实际消费：
同实例clock继续5…8真实guest expiry、公开393B视图/222写回读、原AB1/task0x1004保留，
原Common381释放1336 rc0/faults0/ap_consumed1。它不是PCM、CMOS或拍摄证明。

下一实际26B请求032d：`0d202d031a000180000001000101010100000000000000000000`。
该轮SD flush/STOP超时，GTK整体false；匿名overlay/guest cache未保全，仅host树保全。
全部自有进程/QEMU/双锁已释放，NoSIGKILL；不得借旧run的SD成功抬本轮保存成功。
见`adf-set-input-native-proof.json`、`adf-set-input-0336.md`及后续032d报告。

## 前次边界：ADF0323已消费，0336输入配置等待

`run-kao1n0qd`在独立source7控制后端完成4个真实guest timerfd事件、完整冷Stop/Start、
AF/B0解释/寄存器读回、内层通知2先于配置通知0、input排空和relay；
外层00580000回复由原AP tid381成功释放，faults0/ap_consumed1。
验收见 `adf-proc-native-proof.json`，不是原硬件时钟/PCM/帧/拍摄证明。
SD原Fsys3文件/全树字节摘要/cleancommit及全部owned组/QEMU/双锁收尾通过，无SIGKILL。

下一真实请求 `adf_set_input` 0336为14B：`0d2036030e000180000200000000`，
Common381两份边界一致的候选链 `34e5788←34f2bec←34c6ec4←339d6a8←33aaa3c`。
EE enable/source/status仍1/0/0、Backup pending0，group0 current2f/stop0，queued31/40。
下面0323等待是已越过的历史前沿；静态后续路线仍只按真实消息消费逐项验收。

## 前次实际边界：NoMem完成，ADF0323等待

`run-ba2cnxt9` 已在严格已知外部Speech资源隔离下完成虚拟NoMem两阶段、
005a0000回复及原AP释放rc0/faults0；没有释放或清零外部Speech缓冲。
内容型验收见 `vef-nomem-native-proof.json` / `vef-path-frontier.md`。

同轮下一真实请求为 `adf_proc_set_path` 0323：`0d2023030c00018000000000`，
三个u8为path0/mode0/format0，Common tid381候选链
`34e5788←34f26e4←34c6e84←339d61c←33aaa3c`；原kernel仍osal_rcv_msg_tmo，
两次读回边界不变。EE enable/source/status=1/0/0、Backup pending0，
group0 current2f/stop0，Still与快门后分别queued31/40。
ADF消费、缓冲/pin/input-state/callback及独立sysnd owner待闭合，见 `adf-proc-path-0323.md`。
原Fsys三文件/全树摘要/cleancommit及全部owned进程与双锁清理通过，仍无JPEG/MP4。

### 0323之后到EE提交的原AP静态路线

以下由公开AP原字节、ELF PT_LOAD和既有反编译交叉核对；**本实例只实际走到上面的0323等待**。
后续请求、callback、CP业务及像素均未据此标记消费。所有原非零fatal门禁保留。

| 顺序 | 静态调用、实际格式和门禁 |
|---|---|
| 1 | 0323返回后339d61c读输出，339d620非零→339d710→原fatal35aa4b4；零才339d6a4→34c6e98→34f2abc **adf_set_input/0336**，模板`0d2036030e000180`，14B→12B，92840747。内部缓存相同可能不发，外层仍要求输出0。 |
| 2 | 原getter33870d8==1才339d7b0→34c7c18→34ec5f0发 **2500:0225**，12B→24B/909a015a；共同339d8dc→34c72d8→34ead94 **adf_set_output/032d**，模板`0d202d031a000180`，26B→12B/92840747，非零fatal。本实例getter未知。 |
| 3 | 339d918→34c5998→34e7b74 **set_mode 200d:0110**，10B→12B/92840747；339d938→34c6bd8→34ea364是原直接写输出0的8B函数，不是0325。之后339d9b0→3546320 **CP302c**，24B→12B/90030001；339d9c8→3549328 **4073 mode0**，12B→12B，只等控制回复，不登记2040。 |
| 4 | 既有key1016仅source2且ee_enable0才等待；原对象+100cc/+100d0只接受(0,0)/(0,1)/(1,0)，其它fatal。通过后339f414→34cb708→3535ee4发 **4063** 参数批次0xa04B；原353787c直接写输出0只说明发送路径，不证明CP已应用。 |
| 5 | 后续40f9、402d、4014、条件40c8、4057、单向40ed、对象+10150==7才415f。339fa08→34d1788→3548c20向8102021f发本地20B **opcode21** 并等20B回复，不是boot的opcode20。分支当前值和具体业务仍未知。 |
| 6 | 第一组339fa58提交A=338e924、339fa78提交B=3386a80，339fa88汇合。A前面有模型0144/backing7e5c260分支，该值不在现有三项EE快照；两支共同尾部是 **409d等待→4072发送→3003等待**，3003/90030001为24B→16B并检查reply+8=f000。B为BB before-set-output，均须原任务返回。 |
| 7 | 第一组后339fa9c→34cb908→3546244发 **3012**，24B→12B；第二组C=33974e8、D=338e164，339faf0汇合。C→33971bc置byte+4=1、3549328发 **4073 mode1**，登记key2040，先等控制回复，再3549448→3531300等完整快照。不能以前面mode0代替。D为BB after-set-output，当前分支未知。 |
| 8 | 两组返回后339faf8/339fb04都汇入339fc30；339fc4c加载模型0304、339fc5c加载1、339fc70→338d998，338d9f4把1写入getter28623f0指向的 **7e67700**，339fc78→338b528发布模型变更。此为原EE控制提交点，单独也不证明首帧或拍摄。 |

下一实际观测必须先看到0323的真实完成消费，随后区分0336/032d是否真的发送，
再按真实前沿推进；不预先应答静态列表、不写EE状态跳过这些工作。

## 2026-10-25 UDATE实测后的新前沿：sequence_set_touch_panel

`b4d205550/run-bh0ryvgh` 已在真实kernel public-sender边界完成一次UDATE
`REQUEST→QUERY→RESPONSE→DONE`，响应status=0、timer elapsed=363、type4 target1、
`request_free_rc=0/faults=0/request_retained=0`。manifest、initramfs、observer、模块SHA和
`UDATE_K_REGISTER: rc=0`均匹配，目录SD也实际绑定256000000000B；这不是首轮用户态hook
空跑，也不是128MiB RM卡实验。

但UDATE完成不等于拍摄启动完成。后UDATE passive Common栈不再含先前reason-1 SET返回
候选，原sequence名称表和栈/反编译把最强下一等待候选定位为 `0xbe sequence_set_touch_panel`；
raw stack尚未正式unwind，名称表也只是静态ID映射，仍需entry/worker观测确认：
`0x3470328→0x34c6158→0x34e8b00→0x34e552c`，向 `0x92840747` 发
`200d:0146` 的10B请求并等待12B回复。console:2616直接记录
`raw=0d2046010a0001800100`，未见对应 `0x1146` 回复；CP回复/F02F边界见
`report/touch-panel-frontier.md`。当前没有新 `MODE_SCHEDULE`、transition run或EE
启动，EE仍为0；clock entry一次不等于clock全量完成，后续group0仍需重新取证。

GTK首次截图前的guest命令返回1导致超时，未执行自然快门。`SD/export.json`保留
`flush/STOP timed out`/`cancel_armed_no_reply`/`ok=false`，没有原SD mount/write/flush/commit；
host只有未变诊断 `INPUT.BIN`。已按无SD数据的限定前提用一次正常SIGINT收尾并清理所有
owned进程，未使用SIGKILL；详细分类见 `run-bh0ryvgh/udate-evaluation.json` 和恢复评估。
下一步只调查touch-panel原协议，不以空ACK、EE写入或伪造完成替代。

## 2026-10-24 调度链更新：CP3007之后是sequence_clock

本节覆盖下列旧“EE入口候选”解释，但不把任何中间里程碑提升为拍摄成功。原模式设置、
队列和工厂现已分开验证：

1. `run-czntw0ko` 在原队列看到三次 `0x2f sequence_mode_transition`；
2. `run-8jxqfsd_` 看到它们进入 `model::create_sequence@0x24cc968` 和表工厂
   `0x248ff44`，但没有 `sequence_mode_transition::run@0x33aa0d0`；
3. `run-zg71acyj` 的依赖观测误用了 `object+0x14` 实例token，不能用于否定前序。
   后续按原 `0x303c780/0x303c794` 改为 `object+8 → control_block → +8 sequence ID`；
4. `run-zwe5fiq_` 的修正依赖观测没有 `0x303d93c` 前序注册；`run-i2mfz9pl`
   在 `0x303cb84` 看到其它序列，却未见 `0x2f` 进入出队后的等待/run；
5. `run-e9s7uztz` 在 `0x3222ad0` 直接读取group0：三次 `0x2f` 调度时当前对象均为
   `0x2a sequence_boot`，`stop=0`，已有队列计数188、232、262，读取长度均为
   `4/8/4/8/8/4`。这建立了boot占用/FIFO证据，不再把transition描述成已在自身future等待。

该baseline的 `cp_background_profile=None`，原始3007没有对应有限服务。随后
`run-q6opaylg` 通过 `A7C2_CP_BACKGROUND=virtual-mode3-cold-v1` 显式准入，实际manifest
和CP SHA均匹配。原3007完成独立reply入队、原request释放、reply释放及原caller核对：

```text
NATIVE_CP_BACKGROUND_ACCEPT ... reply_queue_rc=0 request_free_rc=0
NATIVE_CP_BACKGROUND_REPLY_FREE ... wire=010007300c00018000f00000 rc=0
NATIVE_CP_BACKGROUND_FREE_CALLER ... rc=0
```

此控制消费不是硬件ready。重要的是，三次 `MODE_SCHEDULE` 的当前对象随后均变为
**`0x83`**，原名表解析为 **`sequence_clock`**，而不是boot；队列计数为175、219、249。
因此有限3007服务确实让原group0越过了boot当前占用，下一阻塞是clock，不是继续宣称
`sequence_start_ee`缺失或boot仍卡在3007。原3006后来由tid294/source `0x810261c4`
发出，有限服务按范围记录 `UNHANDLED/delegated`；未生成3006成功回复。由于3006出现晚于
clock成为current，仅凭时间顺序不能把3006命名为clock等待，须继续核clock分支。

原名表/vtable依据：`0x83`名称为 `sequence_clock`，表入口 `0x248f0d4`，构造
`0x3109974` 使用vtable address point `0x5b31a18`，其 `+0x10` 指向
`sequence_clock::run@0x306f494`。`run-wqtwlrj3` 进一步记录
`MODE_WORKER sequence_id=0x83 deps=0`，随后 `CLOCK_SEQUENCE case=0x1 flag_44=0`，
所有读取长度正常。因此clock已进入run且无序列依赖等待，当前精确下层是case1的
**`0x306e5e0`**；其它7个case不是本轮路径。case1原代码先由 `0x36ecb34`
读取初始日期/时区，再经 **4字节thunk** `0x36ecb04 → 0x36ec96c` 构造32B reason-1 SET；
`0x36ecaac` 调用 `osal_snd_sync_msg(0x80900141)`，返回点是 `0x36ecab0`。
不能把该thunk当普通16字节prologue patch，也不能把sequence/model/API/OSAL ID混用。

`run-2ry47pfd` 的passive snapshot提供同一边界：`SeqQueueCommon` 的syscall29/ioctl
`0x80000006` 前后不变，wchan为 `osal_wai_sem_tmo`，`raw_stack_collected=true`。
有界栈候选依次包含多个 `0x36ecab0`、`0x306e624`、`0x306f54c`、`0x3209e48`。
这与reason-1 SET尚未完成高度一致，而不是GET或model-lock候选；但原始栈未正式unwind，
仍保留为强证据而非完整frame链。接收端正等待本地资源/MWF还是kernel distribution-done，
需另由接收线程证据区分。`run-v_605ywl` 的无ptrace passive采样随后在Common自己的
原始栈中找到 `libosal_udate+0x2ef4` receiver、`+0x2f5c`（调 `udate_set_date`）、
`+0x41ec`（调 `udate_set_date_nr`）、`+0x3d34` 和 **`+0x3ebc`**（直接kernel SET返回点），
并与AP `0x36ecab0/0x306e624` 共存。故当前已进入kernel日期SET，不是仅AP等待，也未停在
`+0x40cc/+0x3cb0` 的本地semaphore。独立 `UDATE_ASYNCSET` 的futex idle不属于该同步路径。
libosal_udate SHA256为 `5a61d80cc95fbda9496bf3424c4a58fb77a3085f494e2401ba0eda91397a8df9`。
原 `UDATE ... ignoring NODEV[-1020]` 路径明确可容忍该资源错误，不能单独命名为当前阻塞。
`run-ou4e0ac5` 进一步直接读取请求方 `/proc/.../stack`，得到
`osal_wai_sem_tmo → udate_wait_for_distribution_done+0x74/0x148 → udate_get_localtime`
`→ udate_set_date → udate_proc_read_clock`。这已是kernel distribution-done等待的动态证据，
不再只是静态候选；无需把 `UDATE_ASYNCSET` 的idle或被忽略的RESOURCE `-1020` 命名为该等待。
静态原分发线程同时证明type1→type2查询→真实timer/date/timezone响应→更新接收端状态→type4
的顺序，因此不能只对type1回一个空完成。

首轮 `run-38y7a1k_` 给出重要否定：没有任何 `NATIVE_UDATE_*`，原kernel仍 `Skip snd to 0x5c5`，
clock仍为case1/current `0x83`。原因是type1由 `udate.ko` 在内核直接发送，LD_PRELOAD用户态
`osal_snd_msg` hook看不到；不是profile或单元测试可以解决的形状问题。同轮旧GTK脚本的
`--host-sd-dir` 未消费，实际为128MiB RM卡，因此也不能作为目录SD验收。

生产实现已迁到 `report/virtual-cp/udate-distribution/client.c` 的kernel public sender，用户态C
模型仅保留协议参考，不再注入observer。新profile为 `kernel-public-roundtrip-v1`，只处理
`destination=0x909005c5`、source/base `0x809005c5`、44B、type1/reason1/async；type2的
body `+0x0c` 是动态回复queue，type4使用target1接收侧通知source。失败、超时、无效响应不发送
正常type4；同步 `+8!=0` delegated；type4已发出后的原请求free故障单独保留并计fault。
目录参数已改为真实 `A7C2_DIRECTORY_SD` + 256GB manifest核对，UDATE输入前还要求
`UDATE_K_REGISTER: rc=0`。用户态参考 **2项+21子测试**、kernel client **2项+15子测试**通过；
这些不是新的kernel VM结果。协议和所有权详见 `udate-distribution.md`。尚未证明clock完成、
transition run、EE1或JPEG/MP4。

此前CP3007 A/B observer C SHA256
`ac27a3e67b9970102ff0e34a1dd18920356160a8604c524e4774cfc5d554f6d7`，SO SHA256
`0ad2114189781e4afabbc6eeba9d6dda9f2d1ed659a14a095c654a1671956316`；三套件20项通过，
有限CP传输/资源回归3项及18个子测试通过。A/B导出、fsck、FlushVolume、owner停止/恢复
均通过，host目录只有诊断 `INPUT.BIN`；没有原JPEG/MP4、EE1、Still执行或拍摄验收。

## 最新基线快门实测：run-y8219f7y

本轮在已复验的简体中文逐页首设/HUD基线上，仅增加自然快门与启动/JPEG/Fsys观测，
没有YC/RC/SMP2。`id=0/count=565`实际内容屏出现后，原AppFw接收点记录同TID321的
`INPUT_EVENT32 n=77..80`，依次为半按`0x1f1/status1`、全按`0xa7/status1`、
全松`0xa7/status0`、半松`0x1f1/status0`，四个提交均0/32B，无BAD_ARGS。
因此本轮证明**原队列接收**，与历史未发出/阻塞的静态实验不同；下游dispatcher处理及
Still语义仍未证明，不能把队列receive直接当拍摄消费。

mode-transition/enter-rec-still/实际JPEG请求/异步Fsys照片写均0，原run_i返回1次。
原SD flush=0，守护导出成功且fsck=0；正常清理，无保留VM、无cleanup错误，运行锁释放。
独立只读7z列目录：128MiB FAT16，空闲124246016B（118.490234375MiB），只有
`PRIVATE/DATABASE/DATABASE.BIN`和`PRIVATE/M4ROOT/MEDIAPRO.XML`两文件及九目录，
没有JPEG/MP4。原Fsys容量结构最后为
`ff77,ecfb,ec00,ec00,0,0,200,4`；`word1*word6*word7=124246016`与host目录工具一致。
原`Fsys_GetFreeSpace@0x34de0`末尾`0x34f64..0x34f98`计算的数量也为非零；
HUD橙色剩余张数0不能归因为“卡满”。上层张数/recordability为何0尚待原路径定位，
也不能直接断定是拍照阻塞条件。

该run的`verify-baseline.py`独立断言顺序/原接收/探针武装/导出SHA/host文件列表/容量匹配，
输出`baseline-shutter-evidence.json`；未改原`natural-shutter-request.json`中的保守判据。
卡SHA `6fd281e91a0c177f6cb3729863a2df1d0c9c621e2e1eaeca9fef6f653dd1377b`。
仍没有实际照片；下一步追下游输入路由与剩余张数的原计算路径，不写EE/ready/张数。

### 非零FAT空闲与零张数并不矛盾：原预算保留量

后续只读调查发现原`libmpr.so`的Still预算先扣基础`0x12c00000`（300MiB）和附加量。
main窄窗口复核`12ce4c..12ce98`与`12d964..12d990`：`ldr w1,[3adbe0]`、
`mov w0,#0x12c00000`、32位加法、从原64位预算相减、`cmp/csel`在不足时取0，
再除以单张估算大小。`CalcStillRemain`预算张数0时还会把槽标志OR2。
附加量来自backup项`02f90025`乘13MiB（调查地址`130810..130830`，尚无运行读回）。
`GetStillRemain`还存在媒体状态/槽映射等提前返回，不能单凭静态扣减便断言
`run-y8219f7y`一定命中该分支。

因此128MiB控制卡确实小于原基础保留预算。下一对照使用独立新建、BPB/fsck/SHA核验的
1GiB空FAT16种子（现有`A7C2_SD_IMAGE`通道），保留128MiB控制资产与失败证据，不改保留量。
这次只允许原固件正常计算/写卡；只有实际HUD/原状态变化才报告容量问题解除，仍不等于
JPEG/拍照成功。种子脚本固定路径、O_EXCL、仅普通文件，不打开物理盘。

输入调查也核实原转换器读`status/repeat`选择按下/释放，已核范围内不以`prev_status`
判释放，未证明`from_type=0`被拒；下一实验维持四记录格式，新增默认关路由观测，
不把猜测字段变更混入容量对照。

---

本报告记录独立调查A/B及main的逐字节核对。两份报告给出的是不同阶段的局部依赖，
不是以多数票定根因；未闭合部分继续保留。
没有执行新动态观测，没有改变EE状态、通知或请求完成值。

> **后续动态更新（2026-10-24）**：上述“没有执行新动态观测”只描述本报告最初调查。
> `run-s7s9lcww` 后来以只读 maps/status/wchan/syscall/4096B 栈快照观察到
> `EE_START_ENABLE=1`、`EE_ENTRY_SOURCE=0`、`EE_STATUS=0`；自然入口探针虽成功武装，
> mode-transition、enter-rec-still、run_i_return 和实际 JPEG 请求均为0命中。
> 首个由完整原调用链定位的启动等待是 CP `0x403d set_release_lock`，不是已证 still 条件。
> `run-2hkxvsd4` 只证明默认关闭的释放锁回复服务能处理原请求；该轮含已撤回的临时
> NULL 初始化返回值，且可选快照缺失导致提前收尾，不是拍摄启动或拍照验收。
> 现已恢复原线程句柄返回；自然拍摄仍未接受。
> 随后的 `run-g9imyc_6` 找到 AP 消失的直接原因：`appFw.so` 延迟绑定
> `iCrypt_HasPublicKey` 时符号不存在，`im.elf` 被动态链接器终止。故这些0命中
> 不能解释为 still 条件已执行但未通过。下一实验启用固件自带原 `libInfraCrypt.so`
> 的全局符号环境；不得用固定“有公钥”返回替代。
> 再后的 `run-zg27xysi`/`run-3f8axpzr` 证明当前 SIGABRT 仍不是已证 EE 门禁：
> 原 ulog 明确给出 `sequence_boot.cpp:1436(error=0x11)`，UPM 探针全0且409分支0命中。
> 实际失败来自 `set_buspower_setting` 的低15位 `0x2f6` 同步端点缺失（-1020→0x11）。
> 正以固件原 BusPower/USB 模块恢复该接收端；在自然 `enter-rec-still` 真正命中前，
> 本文下列 still 条件继续保持候选，不能提前当成当前阻塞。

原件 `runtime/analysis/menu-root/usr/lib/appFw.so`，99960744B，SHA256
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。
按ELF PT_LOAD映射；下列代码都在VA=fileoff的第一段，不能推广到第二段。

## 最值得动态核验的候选

`enter-rec-still@0x339d450` 中存在如下确定条件：

```c
if (*(uint32_t *)(base + 0x7e5dd40) == 2 &&
    *(uint32_t *)(base + 0x7e5c240) == 0)
    call_34d19c8();  // -> 354912c，key 0x1016 同步路径
```

第二个字段由现场原日志 `ee_start_enable_state %d` 与getter共同指认。
第一个字段仅证为getter `0x285f8b0` 返回对象+8，不擅自命名。

| VA=fileoff | 字节 | 已核指令 |
|---|---|---|
| 285e8c4 | 80af02d0 | adrp x0,7e50000 |
| 285e8c8 | 01ad97d2 | mov x1,bd68 |
| 285e8cc | 00601391 | add x0,x0,4d8 |
| 285e8d0 | 0000018b | add x0,x0,x1 → 7e5c240 |
| 285f8b0..bc | 80af02b0 010c9bd2 00601391 0000018b | 返回7e5dd38，现场取+8 |
| 339da18 | 1f000071 | cmp w0,0 |
| 339da1c | f8179f1a | cset w24,eq |
| 339da20 | 7f0b0071 | cmp w27,2 |
| 339da24 | e0179f1a | cset w0,eq |
| 339da28 | 1803000a | and w24,w24,w0 |
| 339da34 | 98000034 | cbz w24,339da44；条件假则跳过 |
| 339da40 | e2cf0494 | bl 34d19c8 |
| 3549174 | d9028252 | mov w25,1016 |
| 35491b4 | d99fff97 | bl 3531118，登记同步上下文 |
| 35491c4 | 4fa0ff97 | bl 3531300，具体等待实现未闭合 |

若该分支实际执行，则相关调用必须先返回，才能继续到EE1置位块。
尚未证明实际run执行过此分支或阻塞于此；它是候选，不是已定根因。

## EE1附近普通分支不能解释全部阻塞

`0x339faf8` 的cbnz及 `0x339fb04` 的b.ne都跳向 `0x339fc30`，随后汇入置位准备。
`339fc4c: 80608052` 加载模型编号0x304，`339fc5c: 20008052` 加载1，
`339fc64: a09300b9` 存入调用参数，`339fc70: 4ab7ff97` 调原setter `0x338d998`。
因此不能把这两个近端分支误当成“EE0就永远不可达EE1”的证明。

## 另一个必须返回的本地同步边界

`0x339fa08 → 0x34d1788 → 0x3548c20` 构造20B请求：
`u32+0=0x10`、`u32+4=0x21`，目的SID0x8102021f，预期20B回复。
`3548c3c: 20048052` 是 `mov w0,#0x21`；不是0x20。
返回后内部比较回复+8与0x30并写调用者输出，但外层未按这个输出再分支。
已证要求是调用能返回，不能称外层必须等一个推定的成功常量。

此前动态资料中的 `0x20 → CameraBackground → CP3007` 是另一条消息链。
没有现场调用栈连接前，不能将二者混同，或把CP3007定为本函数的唯一阻塞。

## 下一项只读观测

在owned run私有GDB/QMP中，于 `base+0x339da34` 设置硬件断点，读取w24及上述两个字段。
必须记录是否命中；未命中也是结果。不得通过写字段或注入key1016通知“帮助推进”。
若命中且w24=1，再核 `0x3531300` 等待的对象和真实通知来源；若未命中，沿实际栈重新定位。

独立的 `sequence_start_ee@0x347618c` 与本路径的callback A共用 `34cb808→3546040`。
enter内3003的局部顺序现已核实如下；EE1置位点本身不是3003发送点，也不是已证首帧回调。
主运行没有3003不能单独证明根因必在CP；防尘设置barrier也不构成传感器启动屏障。

## B报告与main复核：两组异步汇合及3003的位置

| enter调用点 | 原字节 | 已核动作 |
|---|---|---|
| 339fa58 | 8eb7ff97 | 提交callback A，保存token |
| 339fa78 | 86b7ff97 | 提交callback B，保存token |
| 339fa88 | 9bb7ff97 | 调338d8f4，对上述两个token汇合 |
| 339fa9c | 9baf0494 | 汇合返回后调34cb908→3546244，构造CP3012 |
| 339fac0 | 74b7ff97 | 提交callback C |
| 339fae0 | 6cb7ff97 | 提交callback D |
| 339faf0 | 81b7ff97 | 第二组两个token汇合 |
| 339fc70 | 4ab7ff97 | 后续提交EE=1 |

main按第二PT_LOAD的正确映射同时核了原qword和ELF RELATIVE relocation addend：

| callback | GOT VA / fileoff | 入口 |
|---|---|---|
| A | 5b5d0f0 / 5b4d0f0 | 338e924 |
| B | 5b54d70 / 5b44d70 | 3386a80 |
| C | 5ba6ab0 / 5b96ab0 | 33974e8 |
| D | 5b96ca0 / 5b86ca0 | 338e164 |

callback A中 `338e9f4→34cbb48→35457ec` 构造409d并等回复，
随后 `338ea3c→34cbb88→354565c` 构造4072发送，
再 `338ea5c→34cb808→3546040` 构造3003请求并等回复。
`354581c:a1138852`、`3545690:410e8852`、`3546068:60008652` 分别加载这些命令。
3003是24B请求、16B回复；它在第一组正常汇合完成之前，不是在EE1提交之后才发送。
静态任务提交顺序不保证并行子任务的运行先后，B/C/D深层等待还未闭合。

`338d8f4→303d674→303d400` 的汇合函数在 `303d498:fe849897`
调用PLT165e890。main核GOT5bc1c50的导入为
`std::condition_variable::wait(std::unique_lock<std::mutex>&)`。
匹配token后 `303d508:b5060051` 把剩余数量减一，特殊token0x2000则走取消返回1。
调用者不检查这个取消返回，故不能把“越过await”解释成所有业务成功，更不是成像完成。

## 下一只读现场的选择

A建议的 `339da34` 用于确认早期key1016路径是否执行；B建议的 `303d498` 用于区分两组汇合。
两点回答不同问题：应先结合已有现场栈判定所处阶段，而不是任意选择一个并把未命中当根因。
在汇合点观测时，需用祖先返回地址339fa8c/339faf4区分组别，并读x22的token数组、
w21剩余数量和相应工作线程栈。任何未命中、取消或读取失败均须保留为否定/未知结果。

## 复用已有AP伪代码后的进一步定位

`analysis/appfw-decompile/corpus/` 与当前AP同SHA；语料索引地址已是ELF VA，
但 `FUN_/DAT_` 名字通常还带Ghidra的+0x100000，必须归一后再与本报告地址比较。
main已实际读取 `parts/7/0x003530000.c` 和 `parts/7/0x003540000.c`：

- 3531118的正文是ushort键到上下文的哈希表插入；354912c把key1016及promise上下文
  放入全局9116568，释放锁后等待，返回后再删除表项。
- 3531300先经303cb68检查future存在，再调用31018f0。后者有共享状态检查与
  `std::__atomic_futex_unsigned_base::_M_futex_wait_until`，支持把这里识别为future等待；
  精确字段和实际等待现场仍需原字节/动态补核。
- 同片35314fc的imaging通知入口中有1016分支：清一项状态、发模型事件，
  随后按相同key查9116568表，复制原消息并进入promise完成候选函数310197c。
  尚未把这一整条分派与完成路径逐指令核完，不能据此注入一个1016。

这提供了比泛称“缺CP前端”更明确的待核通知/等待两端。下一动态现场应检查实际命中与
未完成对象，不能以静态发现一条完成分支就认定当前run正在等它。
语料使用入口与陷阱见 `existing-decompiled-sources.md`。

## 历史现场重新归一化与当前采样

直接在历史文件中搜索ELF VA会漏掉ASLR后的栈地址。main对menu-runs中已保存的
13份 `*stack*.txt` / `*regs*.txt` 重做映射，13份均有唯一appFw offset0可执行映射。
按该基址归一化后有4个future等待命中，来自run-4d24ai94与run-nvmhrunq的两次采样：
ELF LR为310194c，其祖先链包含34f4f74、3535b04、3548cbc、34d1774、305eb88。
这是历史boot收尾的opcode20调用链；没有新证据证明它仍是当前profile的卡点，
也不能拿它支持key1016或enter内两组await正在等待的判断。

为复核当前现场，新增显式opt-in `A7C2_EE_ENTRY_SNAPSHOT=1`：在现有串口事务拥有者内部，
SD导出前调用原只读 `menu-regs/menu-readmem`，记录当前AP maps、三个EE字段和
AppFw/SeqQueueCommon/SeqQueueStillCa/SeqThreadPool线程的原始快照与归一化AP栈。
其它线程逐项列在skipped_threads中，不声称全线程覆盖；采样是逐线程的，不是原子系统快照。
未命中、寄存器读取失败和序列不一致均不能改判业务成功。

工具及相关门禁解析测试11项通过；当前简中首设/原按键/只读快照/SD保存实验结果待定。
这个观测不写模型、通知、future或CP完成包，不证明任何一条控制链已经修复。

### 当前首轮现场：run-6w4sv24z，关键线程读取失败

简中首设、原HUD/MENU和按键流程已执行，SD完整导出经host独立重算SHA256为
`82d3f7810ec02be543adf9516e140087eea394c664aa36e072ff06ae00a7bf31`；
fsck0、原flush0、owner resumed并正常退出。
快照位于 `ee-snapshot-ttvd40ts`，识别204个线程、采样8个，整体 `ok=false`：

| 字段/线程 | 本次实测 |
|---|---|
| ee_start_enable_state | 1 |
| 原入口条件的source字段7e5dd40 | 0 |
| ee_status | 0 |
| SeqThreadPool0..3 | 都见34b9528及线程封装等待 |
| SeqQueueStillCa | 34ae1a8→3209e48等等待帧 |
| SeqQueueCommon | menu-regs返回6，无有效REGS/FRAME |

`menu-regs` 的6是其3秒alarm超时退出，而不是原业务结果码，不能据此推断Common在等待
哪个消息。三个字段的读取是事后逐项采样，不能倒推出早期339da34分支从未执行。
此轮没有证明key1016或两组await是当前阻塞点。

下一轮补读每个目标线程的/proc状态、wchan/syscall、采样前后TracerPid，并纳入
CameraBackgroun、THREAD_INFRA1、InfraNotify。已有tracer时不重复attach，失败原字节保留。
新增状态/已有tracer拒绝测试后该模块9项测试通过；不调大超时掩盖未知等待。

### 补充现场run-x_evenf7：CameraBackground等待3006

204个已列线程中选取11个采样，Common仍未取得寄存器；前状态S(sleeping)、
TracerPid=0，内核wchan为 `osal_wai_sem_tmo`，/proc syscall为29，参数含fd3及
ioctl命令80000006。helper alarm后TracerPid仍为0，没有把寄存器失败当成业务完成。
其它目标线程读取成功，EE三个字段仍为1/0/0（事后值，不证明入口从未执行）。

CameraBackgroun tid275取得有效栈；本run libObj offset0映射基址为7f67d0f000，
归一化后三条祖先为 `eda8c ← ee6fc ← ee82c`。
main读原libObj及已有对应C：eda88调用原收包等待，ee6f8调通用CP查询ed9c4；
该共享尾部可由多个命令到达，不能仅凭ee6fc单独命名当前命令。
同run的原消息日志提供命令证据：

```text
NATIVE_CP_BACKGROUND_REPLY_FREE ... bytes=12 wire=010007300a00018000f00000 rc=0
FULL_DMM_UNIT_POST_BOOT_CP_REQUEST tid=275 destination=0x90030001 source=0x810261c4 bytes=24
raw=000006300000000003010000a5a5a5a57000000055555555
```

即原3007响应已被waiter释放，随后CameraBackground发出3006，当前在接收等待中。
未初始化的请求byte1及+8..23不得解释为有效参数。当前有限CP模型只处理3007，
不因这个观察就生成3006成功响应。
这证明CameraBackground侧的当前缺口，不足以把Common所有上层等待归因于它。

下一轮Common不再用PTRACE_ATTACH：从其原/proc syscall边界得到SP/PC，
用原只读menu-readmem保存有界用户栈，前后比较syscall边界，并补读libObj分派对象2eb8e0。
栈内AP地址只能标为候选代码字，不等同已恢复的frame链；未稳定读取或边界变化均记未知。
新版边界/连续字节校验/拒绝已有tracer等11项测试通过。3006依赖交由独立代理复用旧调查核实。

### 3006原转换表补核

独立代理复用了已有slot1/slot2/metadata/shadow调查，main另核原件的三条表记录：

- d97488为 `(current0,cmd3006,provider3669d9,cmd3006)`，不是3007路径。
- d96420的0→1对应12个半字：
  `0101 0201 0301 0401 0501 0601 0701 0960 0a00 0b01 0d00 837f`。
- d96430的1b→1对应15个半字：
  `0201 0301 0401 0501 0601 0960 0b01 0d00 813e 0110 0701 0a00 8041 0101 8001`。

先前研究中的配置0051001d决定直达1还是先经1b；后者另依赖003100a6选择变体。
公开seed里的值/缺项不自动等于运行中CP配置，primary来源仍有未闭合处，不能替用户选最容易完成的路径。
当前32MiB资源预算不代表已分配并初始化所有原设备数据；slot1有限发布/metadata发送器
虽已有实现，但实际订阅投递、其它必选模块消费和正常观察链尚未齐备。

因此下一步是先取得Common当前用户栈和原CameraBackground对象，并沿真实配置/模块边界
逐项接入。成功回复必须由真实选定路径的完成条件产生，不能把3007包改为3006或直接填observed。
代理报告保留于 `scratch/cp3006-current-frontier/REPORT.md`，原错误和未知不回填为通过。

## `RUN_I_RET` 的语义纠正与下一观测点（只读复核）

针对已知 HUD 基线的独立只读复核（原 `appFw.so` SHA256
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`）确认：
`0x305b9b0` 是 `sequence_boot::run_i` 共用 epilogue 的一部分，不是成功返回值，也不是
 enclosing `sequence_boot::run` 完成或 EE 启动的证据。直接到 `0x305b9a0` 的分支包括：

- `0x305b794`：日期信息 switch 的无符号值大于3时的早期出口；
- `0x305c41c`：`0x34da748` 路径的非零操作状态出口；
- `0x305e8a0`：`0x303d674` 后的 ordinary end-of-body 路径，但其返回值被忽略，不能据此证明全部操作成功。

 fatal 块虽然在线性布局上靠近 epilogue，却经 `0x35aa4b4 → __assert_fail@plt`，不能按普通
返回解释。现有 `RUN_I_RET` 记录的 `object=0` 只是探针读入的 `x0`，不是验证过的对象或业务结果。
另外，`0x305e9e4` 调用 `run_i` 后，外层仍在 `0x305e9e8/0x305e9ec` 做后续处理，并可能经
`0x305eb84` 走另一同步路径；所以 HUD 与 `RUN_I_RET` 同时出现并不排斥 boot 仍占 group0。

下一次需要时，在已知 HUD 基线的原调度器 `0x3222bf8`（mutex 后、插入前）只对保存请求 ID
`u32[x29+0x64]==0x2f` 做有界只读快照：`M=x19`、`group=w24`、`G=M+0x310+group*0x90`，
读取 `G+0x88` 当前对象、`G+0x20` 排队数、`G+8` stop、当前对象经 `+8` 指向的 control
的 `+8` ID，以及当前对象 vtable `+0x10` 的实际 run 地址。这样可直接区分 boot
`0x2a/run=0x305e9b8`、clock `0x83/run=0x306f494` 或其它当前对象；未执行该观测前不把
`RUN_I_RET` 或历史 A/B 结果当成当前基线的 EE 根因。该调查未改文件、未启动第二个 VM。

## `run-4xi0tkk_` 直接拍照基线：CP3007 是当前实测前沿

`bf9e65b71/run-4xi0tkk_` 使用正确 GTK→`menu_control.py`→QEMU 入口和新鲜 256GB 目录 SD，
未启用 CP3007/UDATE/touch。中文首设、HUD、Movie→Still、四阶段自然快门和13次 GUI model
commit 均实际发生；原 Fsys mount/FlushVolume、owner 恢复、host commit 通过，host 只有
`INPUT.BIN`、database 和 XML。没有 `MODE_TRANSITION`、`ENTER_REC_STILL`、EE sequence、
实际 JPEG request 或 Fsys 照片写入；`GATE_EE_STATUS=0`，所以仍无照片。

三次 `MODE_SCHEDULE` 均显示 `sequence_id=0x2f`、`group=0`、`current_id=0x2a`、`stop=0`，
队列计数188/234/264。当前 Common 被动栈候选为
`310194c←34f4f74←3535b04←3548cbc←34d1774←305eb88`，并有同run原请求：

```text
8102021f / source 80020002 / 20B
1000000020000000000000000000000000000000
```

原字节核对 `0x34d1748 → 0x3548c7c` 后，本 boot 路径的操作码是 **0x20**；
`0x34d1788 → 0x3548c20` 的另一条路径才是0x21，不能混用。CameraBackground 随后发出
24B CP3007 请求，而本 baseline 没有有限 CP3007 服务。原始栈尚未正式 unwind，故这是
静态调用、原消息和同run栈相互印证的最强前沿，不冒充完整帧证明。

因此 `be1bc93a3` 只加入既有 `A7C2_CP_BACKGROUND=virtual-mode3-cold-v1`，不启用
UDATE/touch，检验该实测等待是否解除并继续测量 clock/EE/Still/JPEG。完整证据见该run
`direct-capture-evidence.json`；SD 导出成功仍不等于拍摄成功。

## `run-pc2zteeh`：CP3007 已推进到 clock，UDATE 是下一边界

CP3007 单变量 run 已正常结束。原 `NATIVE_CP_BACKGROUND_ACCEPT`、12B `f000` reply/free
及 caller free 均实际发生；这不是硬件 ready 或原 CP 执行证明。三次 transition 调度时 group0
当前均由上一轮 `0x2a sequence_boot` 变为 **`0x83 sequence_clock`**，并观察到
`MODE_WORKER sequence_id=0x83 deps=0` 和 `CLOCK_SEQUENCE case=0x1`。

当前 Common 被动栈含 `0x36ecab0`、`0x306e624`、`0x306f54c`，与原 clock case1 的
UDATE reason-1 SET 路径一致；未将该栈冒充完整 unwind。没有 UDATE done、transition run、
EE sequence、实际 JPEG request 或 Fsys 照片写入，host 仍只有 database/XML/INPUT，SD 导出
及清理通过。完整结果保存在 `cp3007-capture-evidence.json`。

UDATE kernel 与 touch 虚拟配置已经有独立协议/ownership 实测，因此不为重复制造已知等待而
再做一次 UDATE-only 运行。`b689f92bd` 复用这两个既有模型和 CP3007，直接检查后续原始
启动、EE/Still/MPR/Fsys 以及 host JPEG；任何回复仍不等于硬件、EE 或拍照成功。

## `run-9f_qv6a2`：UDATE/touch 之后仍黑屏，CP3006 需进一步归因

`b689f92bd/run-9f_qv6a2` 复用了 CP3007、kernel UDATE 和 touch。实际看到
`UDATE_K_DONE`（request_free=0/faults=0）及 touch `REQUEST→DEVPANEL→REPLY_QUEUED→COMMIT→REPLY_FREE`，
因此这两项只在其虚拟协议范围内通过。原 clock case1 已出现，但没有后续 transition/EE/Still/JPEG。

辅助导出缺失文件分支使首张真实 QMP/GTK LCD 截图得以返回；图片实际全黑，不是语言页，
随后原简体中文导航失败，未执行自然快门。没有 GUI model commit，也没有原 SD mount/write/
flush/host commit；`SD/export.json` 保留 `ok=false` 和 `flush/STOP timed out`，host 仅有未变
`INPUT.BIN`。已按 run/container/QEMU-parent/主锁身份和上述无写入证据正常 SIGINT，最终所有
owned PID 消失、主锁释放、host hash 不变、未用 SIGKILL；GTK 初次等待超时及延迟退出也保留在
`directory-recovery-shutdown-assessment.json`，没有把原始失败改写成通过。

本轮原 CP3006 仍为 `UNHANDLED/delegated`。CameraBackground 被动栈归一化候选为 libObj
`0xee808/0xee838/0xeceec/0xed290/0xee7cc`，Common 已回到调度循环候选；这些不是完整 unwind，
也不能只凭一条 UNHANDLED 就断言 CP3006 是唯一阻塞。正在以只读方式核 `ed9c4` 的回复/等待
关系、原消息/free 和 UI/scheduler 证据，再决定是否及如何恢复原 CP3006 生产/消费路径。
完整分类见 `startup-photo-evaluation.json`。

## CP3006 归因复核与 Backup_sync_all 下一观测

独立只读复核没有把这轮 CP3006 命名为已证根因：保存的 CameraBackground 快照早于后续的
CP3006 请求，且 `UNHANDLED/delegated` 只表示分发边界，不证明原 send 成功、进入回复等待或
reply-free。原 `ed9c4` 只有在 `osal_snd_msg` 返回0后才到 `eda88` 的 dynamic queue 接收；
非零发送直接返回。当前保存的 `f000` free 属于 CP3007/source `810261c7`，不能套给 CP3006。
原输入的 `type=0x12/+0xc=0x42` 对应 `ee5f4→ee600(3006)→ee608→ee6f8`，不是另一个
`ee790` 调用点正在执行的证明。因此暂不实现 CP3006。

更直接的 UI 线索已逐指令核实：`run-9f_qv6a2` 的 AppFw tid335 原始栈含
`2f3aa30←24cce7c←1e78eb8←179a314`。`2f3a99c` 在 `2f3aa00` 将
`appFw+0x8838af8` 置1，`2f3aa14` 构造 event `0x12`，`2f3aa2c` 进入条件变量等待；
保存的 futex 地址 `0x7f61a7ba38` 正好等于 `appfw_base+0x8854a10+0x28`。原 switch 的
`2ff0cf4→35aa8dc` 在 `35aa8e8` 调 `Backup_sync_all@plt`，返回后才到 `2ff0cd4` 清 pending
并由 `2ff0ce8` notify。该备份屏障是当前最佳下一线索，但 pending 字节和 AppBackupDaemon
状态尚未在本 run 采样，仍不是已证根因。

为此只扩展被动证据：`ee_entry_snapshot.py` 将 `AppBackupDaemon` 纳入有界16线程优先级，
读取1字节 `BACKUP_SYNC_PENDING`，并把 skipped 列表改为真正未选中的线程；不写 pending、
event、CV 或备份数据。主机快照回归 **13项**通过。`b15355545` 复用相同 CP3007/UDATE/touch
路径，待实际 `AppBackupDaemon` 栈和 pending 值返回后再决定恢复原生产者还是继续排查。

## `run-00t3xfkx`：Backup_sync_all 屏障已获得直接运行时证据

新增被动采样按预期工作：eligible=17、sampled=16，唯一 skipped 为 `SeqQueueStillCa`，
`AppBackupDaemon` 被实际采样，`BACKUP_SYNC_PENDING=1`。daemon tid462 的候选 AP 字包括
`0x35aa8ec`（`Backup_sync_all@plt` 调用返回点）和 `0x2ff0cf8`（消费者 `0x2ff0cf4` 后），
AppFw tid336 仍在 `0x2f3aa30` 的匹配 CV 等待，并有 `24cce7c/1e78eb8/179a314` 调用链。
pending、daemon 和 UI 三侧与原代码一致，构成原备份同步未完成的强直接证据；原始栈仍不是
完整 unwind，下层 driver/queue/完成原因尚不能据此命名。

本轮 UDATE/touch 已完成，但 LCD 全黑、未执行自然快门，EE/JPEG 仍无进展，原 export 仍为
`ok=false`。没有原 SD mount/write/flush/commit，host 只有未变 INPUT；QEMU、父进程、GTK、
Xvfb 已正常退出，主锁释放、host hash 不变，未用 SIGKILL。证据保存在
`backup-sync-evaluation.json` 和恢复评估。无需再重复同样的黑屏等待；下一步只读追踪
`Backup_sync_all` 的原始实现和下层等待（调查 `3ac75ced-7e43-4fa`），再决定恢复路径。

## Backup 请求/消费者已定位，CP 初始数据仍未闭合

主会话随后核对了原 helper 的 opcode `0x30` 跳表和 CP 接收分派，结果保存在
`backup-sync-cp-contract.md`。当前等待是第一次 `backup_get_cp_data(3)` 的回复，早于
`backupfile_get_cp_data` 的 DMA 和 `backupfile_save`。第一请求为40B，目的地确为
`0x903e0811`，`+0x20=3,+0x24=0`，动态 reply queue 在 `+0x0c`；第三变参只负责 target1
修饰位。CP 原接收循环为 `0x55e3ac`，其 `0x55e08c` 分派器的 `0x30` 项精确跳到
`0x55e20a`，处理后才经原接收循环回复 `+4` 状态。

这给出了真实消费者，但没有证明当前 QEMU 执行了它。接续后 boot0 `Load/Trans Backup CP`
已静态定位：AP第二记录先传，mailbox指针/BKUP居中，AP root最后传；公开seed重置比较全部
相同，CP记录32项中两个重复项按13份验证。第一请求 `+0x14=1`，CP回复分配/复制4096B；
原字节检查及6项回归通过。具体地址与原件摘要见上面的合同报告。

当前尚未闭合 PCI BAR偏移到CP backing的映射、native原DMA及第二交换/文件保存；AP本地
`0x404000000` 与同值PCI源不可合并。UDATE模块仍持有唯一public-sender，后续Backup只能
在同一owner内接入真实数据处理。原调查 `058147fc-6078-413` 已结束并取回，启动数据来源
不再是完全未知；保存文件少量metadata变化仍不证明CP装载。复用已有原PCI DMA 256B验证
候选推进native集成，数据完成之前不重复黑屏或发送generic ACK。EE/JPEG/MP4仍未验收。
