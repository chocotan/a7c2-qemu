# REC槽2无卡：当前证据与尚未闭合的映射

## 最新首写证据：旧模拟器错误修改照片媒体选择

run-5163p5er在原Application_System_Init入口之后，硬件watch捕获
still LIVE7e6e7f0从0→1。主会话按选中observer摘要、gate符号和完整函数
原机器指令确认，writer是模拟器plane_config_send的KEY_GATE_OVERRIDE，
不是原固件初始化或备份载入。此前仍值1的观测须保留此限制，不能继续
据其追原固件默认值或改RM槽来消除提示。

main已在该VM安全退出后移除整组七项业务裸写，不写新值替代。
host实际函数sentinel回归41项/24子测试通过；修复后run-7s_eex47自然简中
首设/HUD/MENU与原八输入回归通过，stillLIVE0、mount1/2=2/0。
原REC不再显示槽2无卡，改为“存储卡无空间”；实际卡仍有大量空闲，
下一缺口为任务50原容量消费者，不能写容量值掩盖。SD独立SHA/fsck0/
Flush0/owner恢复通过；仍无照片录像。[完整首写及修复回归证据](media-firstwrite-root-cause.md)。

## 硬件事实更正：A7C II只有一个物理卡槽

用户补充确认A7C II为单物理卡槽。本报告中的slot1/slot2、ed1/ed2、
RM1/RM2/RM3及原“插槽2”提示均须按固件内部标识分别取证，不能由它们
推断相机存在第二个物理卡槽。此前“两个槽”表述仅保留为原模型名索引，
不代表本机硬件拓扑。共享固件的逻辑编号、机型能力选择、状态通道或提示
参数转换均是待核假设，当前尚未确定是哪一种。

下一问题改为：单物理槽在本机对应哪个原RM端口/AP媒体实例，以及录像
为何展示编号2。不得通过新建第二张卡、任意改槽选择或强写已挂载状态来
掩盖映射缺口；该硬件事实不自动否定已验的RM2数据库/XML写入和持久化。

run-hcrppdg6原App32收到REC的1/0后，main实际打开原LCD确认提示：
“无存储卡。无法拍摄动态影像。插槽2”。同run虚拟RM2文件卡真实保存
DATABASE.BIN和MEDIAPRO.XML，整卡独立SHA/fsck0/owner resumed已另验。
二者不能互相抵销：Fsys文件写入不证明录像选槽的AP状态已提交，UI提示
也不证明整个文件卡后端失效。没有为消除提示修改录像槽、原模型或有卡通知。

## 本轮调查结果为partial

reader只复读原RM适配源码及历史报告，没有提取新ELF字节，也没有读取本轮
run或公开seed。因此没有查明录像媒体选择model ID、UI槽2→logicalRM2、
配置记录索引/selector→AP状态bank之间的typed映射，未形成可用修复。

实际源码返回：opcode9的112B布局包含三条36B记录，首字段0/1/2；仅第二条
填+4=1、+8=2、+16=20hex。opcode2的selector102返回3。字段真实语义仍须
从原消费者证明，不能把第二条索引直接称作“机身槽2”。

## 挂载枚举勘误

旧公开MMC-BOOT-TRACE.md第二十/二十一节已经明确：model IDs ed1/ed2为
两槽media_mount_state；1=MOUNT_RUNNING，2=MOUNT，0=NOT_MOUNT。
拍摄门槛1af17b0附近的==1检测是挂载处理中时退出/延后，不能解释为“必须
有卡/已挂载”。主会话没有用它推当前槽状态或写入任何值。

Main独立校验原AP99960744B/SHA256
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`，
按数据读取VA41e6b38/41e6b50各24B，对值顺序均为0/2/1；精确三个原slot1
枚举名称存在（NOT_MOUNT/MOUNT/MOUNT_RUNNING）。VA168ca34/168ca8c原
指令分别构造ed1/ed2。表的名称ID→名称指针完整链未在本次独立重做，所以
语义仍明确引用旧报告，不把名字存在当运行态内容。main-enum-check.json
保存原窗口size/hash和该限制；表按data解释，不使用线性反汇编的udf伪指令。

## 精确后续与边界

下一步需要原RM opcode9消费者或录像选槽getter中的一条实际转换链，关联
同次REC选择值与ed1/ed2的真实状态。挂载原序列入口写1、后段写2的旧合同
可作索引，不能直接调用setter或原exec_mount模拟完成。

此次没有新VM、原配置读写、真实SD或私有setting，尚未证明槽选择错误、
状态通道错误或挂载状态未提交。其它曝光/AF/拨轮独立调查继续，不因这一
缺口停住全部任务。

## Main补证：原MediaCommon路径索引（尚非机身槽映射）

后续main校验官方native-assets.json中的libInfraMediaCommon.so435520B，
SHA256 `d7cd602e9348e51703a6d3da396cfda949ea306856df7fa0deb62df1ff4ca974`，
对其导出函数mcmn_drv_rm_getrmindex(39b20/92B)与getname(39b7c/60B)做
固定原窗口取证。原字符串prefix57167为`/nondev/rm`；getname的三项表79d80
明确为index0→`/nondev/rm1`、index1→`/nondev/rm2`、index2→`/nondev/rm3`。
getrmindex在前缀成功后按第11个字符减ASCII'1'，并对尾部NUL/范围作拒绝；
无效路径默认返回3。不能把该索引1等同UI“槽1”，也不能把字符串rm2直接等同
UI“槽2”。get_bus_connect_type(4ef24/120B)走C00C6301 ioctl并检查返回状态，
亦没有在此闭合UI录像选槽。

主证据保存在scratch/main-native-rm-index/original-rm-index.json，含PT_LOAD
映射后的表/函数原字节、size与SHA；不是复读旧报告。此处未改变端口配置或
media状态。下一缺口仍是原RM记录/路径索引到AP实际录像slot/bank的转换，
所以目前不给“错槽”根因或修复结论。

## 定向动态回读已实现，结果待验

主会话新增media_state_readback.py，原getter28787f0/2878818的20B指令及
地址算式经固定官方AP摘要回归，分别返回7e80dd0/7e80df0。只读helper绑定
本run唯一已观察FRAME_DRAW_ENTER的tid，先核该task映射appFw，再用既有
menu-readmem读各4B，不调用原getter/挂载序列、不写原模型或配置。

显式A7C2_MEDIA_STATE_READBACK=1才启用；仅在原Flush/STOP/导出/CONT已
完成且owner resumed之后执行一次，保存原始输出和返回码。不把字段直接叫
物理slot，也不把读回值自动转成有卡或capture通过。映射缺失只echo错误并
返回串口shell，不exit；串口异常会留错误并交既有fault保留/恢复路径，不
在未知串口状态下追加命令。此次不能由字段状态单独推所有挂载语义或可拍性。

原件地址、绑定拒绝、原始parser、真实host shell返回及既有SD/fault/锁交接
回归17 passed（0.19s）。bce01b19f串行单VM验收已启动，尚未收到结果；
两路独立代理同时核RM记录消费者和录像选择/提示来源，各自ownscratch。
不将候选初始值或单物理槽事实直接写成已修复。

## 原提示资源核对

录像侧代理未闭合REC选择谓词，且未保存报告；main已补存其partial交付并
独立校验官方中文资源100480B/SHA256
f136388b71e9431313002aee23f9c972b56e92602123b76b4786e0d3d872fb33。
文件offset5568处完整UTF8文本已包含“无存储卡。／无法拍摄动态影像。／插槽2”，
5530为槽1变体，fa84另有不带槽编号的变体。因此资源中已有整条槽2文本，
不能继续把“2”假设为printf运行时格式化参数；真实选择器仍未定位，不能从
字符串本身证明当前选槽模型、机型能力或接口故障。

字符串前a8a1001e等头字节的ID/type结构未解析，不作为原resourceID。
代理ELF命中转换有误，77个02150012字面命中不等分派consumer。此项保留
精确缺口而不改原文本、提示编号或设置。两侧partial不提升为根因结论。

## 原opcode9消费者：字段映射已补证，暂不改回复

RM侧交付后，main逐字节核官方MediaCommon3d1ec/792B（SHA256
cd8783987b416e986e5a24276b87d0c6607f37875e0e37a535391a3b27501c11），
确认该mcmn_drv_rm_init发送opcode9、成功copy70hexB、按24hex步长遍历固定
3项。记录+8进入子模块mask，bit0/1/2分别使用+0c/+10/+14设备号；392a8
分派20hex到`/dev/mmca`。因此当前第二记录(+0=1,+8=2,+10=20hex)确实
走逻辑index1/rm2的MMC端口，与实际open路径一致，不是把数值2直接当UI槽号。

主会话同时纠正代理初稿：payload首word实际为1，不是记录数量3；fixedloop3
不能证明物理三槽。不存在已证的“唯一解析器”，rec+4class含义及AP能力/选槽
仍未完全核实。该阶段是验证现有回复的一段consumerplumbing，不是协议修复。
不能由RECslot2文本反推rm2就是本机物理槽，也不新增虚拟卡记录。

3c848整段mountbody有3abd8/39800/3b164等选择路径，没有直调1cfc8；
后者另经driver+278函数指针dispatch。初稿的直接边不能由函数名补齐，
PLT/实际driver绑定和AP媒体模型提交仍需核验。main固定原四窗口证据保留在
scratch/main-native-rm-index/consumer-main-verification.txt。当前等待同run
只读模型回读，不更改opcode9或原挂载状态。

## run-gykn__z_：原AP媒体状态第一次实际读回

修正后的串行gate已实际完成首设、机身输入、REC、SD恢复及只读诊断。
本run原FRAME_DRAW_ENTER唯一tid302，检查其appFw映射后读/proc/302/mem：

| 原getter cell ELF VA | guest地址 | 4B原值 | RC |
|---|---|---|---|
| 7e80dd0 / ed1 | 7f461cadd0 | 02 00 00 00 | 0 |
| 7e80df0 / ed2 | 7f461cadf0 | 00 00 00 00 | 0 |

依据既有原枚举，只能判该时刻共享模型1已挂载、模型2未挂载；不是两物理槽。
实际读回在console5531行SD_RECOVERY=RESUMED之后，5547行起出现原值。
REC及其“无存储卡／无法拍摄动态影像／插槽2”截图在此前，main已打开截图
并核全部22PNG RGB摘要。不能把回读值当REC门槛执行瞬间的值，也不能仅从
slot2文本断定实际设置一定为2，但“原AP完全无已挂载实例”的说法已被本次
直接证据排除。下一入口为实际录像选择模型及其消费谓词。

原App32序号81..88的C1/half/full/REC各1/0匹配；consoleSHA256
4c9cebf09ef906ef1349d145197e49db66381a0f1a85e4591250536e4650a9a4。
helper在runtime-manifest.json中SHA181227ab3d4482e3da8b58f208927e910308f8d899784cab941a111d8e5e9715，
不是仅检查C构建清单。SD独立全树/摘要与重新fsck.fat-n通过（RC0），原Flush0、
owner恢复，卡SHAaef854f2993de5d98b0cc8818a17c7d63721fe41f3dfe91a28e33de78fbe8f09。
仅DB/XML，无照片/视频候选；整体driverproof仍false。限定review保存在本run
media-state-consumer-review.json，未回填旧整体结论。

## 下一次回读：录像选择值

描述符边界校正后，`setting_still_recording_media` 为ID59f，
`setting_movie_recording_media` 为ID5a0。初始misaligned候选不是最终ID绑定。
代理给出的247b938及24ab518等候选实为位图置位函数，主会话读原body后排除，
未调用它们。实际2867680/28676a8返回原still/movie对象；原消费者
2b13d98/2b13e68读object+10hex，已独立pin。因此诊断新增两个只读4Bcell：
7e6e808（still）、7e6e828（movie），仍在同run SD恢复之后读，不调用固件API。
注册代码表明movie枚举数值0/1，still0/1/2；标签及业务映射尚未闭合，
不能把数值直接当物理槽号。相关14项host/原件pins检查通过，新动态值待验。
旧run的两cell原始回读和review保持原范围，不以新parser回填旧结果。

## run-gnnkjosz：选择值实际读回

**后续语义纠正：以下still/movie两个值属于metadata+10hex缓存，尚不是独立
live字段。raw读回有效，但不得据此判定REC当前选择。**

串行新gate已完成，四项原始读回均RC0：mount1=2、mount2=0、
still选择=0、movie选择=1。绑定本run唯一原绘图tid302，原appFw映射检查通过。
原REC截图仍为同一“无存储卡／无法拍摄动态影像／插槽2”，main已打开并核像素。
SD owner恢复发生console5545行，四项读回5567行起；不是REC瞬时gate观测。
因此当前存在照片/录像两个设置值不同的直接证据，但不能仅据数值1就称
录像选择了物理第二槽。原消费者映射及单槽能力/初始化校正正分别定向核查，
尚不改用户选槽、回复或挂载状态。

全部8个原机身事件和22PNG RGB匹配；全FAT16树仅DB/XML及目录，产物候选0。
原Flush0/owner217恢复、host重跑fsck0通过；整卡SHA256
4d9cd8b735b2bc053f01a83a423b4555458c977e37b822bde6ad964846e64073。
consoleSHA256为7b6cd21d70f11d54bcb860ff23e24920b271655c9582697223ac9e6442b2b333。
本run runtime-manifest核helperSHA9a7d913c3561c6a5b657eb512b94b47bbd6345c5d9d42412a445e45e057abd76；
限定review为media-selection-consumer-review.json，旧driver整体false保持。

## 消费者复核：metadata缓存与live字段分离

本轮代理扫描只追metadata getter后+10hex的读取，未覆盖实际live accessor。
main核原setter1bf5d4c：2867694返回的地址存入x22，1bf5dc8通过该指针写输入；
它独立于28676a8返回的metadata对象。原业务predicate如187599c直接调用
2867694、读word后比较1。相应live字段为still7e6e7f0（286766c）、
movie7e6e810（2867694），本次四项run尚未读。先前main将缓存直接简称选择值
不够准确，现已纠正review和STATUS，不把0/1提升为REC当前选槽证据。

2b13e10仅证为一般设置refresh/apply，未证REC调用链；其本体不调mount
不能推出REC不做转换。只检查directBL后3条指令的扫描也不能证明全局唯一writer，
更不能排除alias/间接或bulkcopy。两个2a331xx恢复handler可作已证实例，
不作为真实挂载状态唯一来源。下一次诊断保留原四字段，并增加两个liveword，
同样只读且在SD恢复之后执行；原setter/业务reader的pins及15项回归通过。

## run-1nypesoh：六字段回读完成

六项读取均RC0，tid302绑定及appFw映射检查有效。顺序读回结果如下，
仍是REC及SD恢复后的观测，不是atomic或REC瞬时predicatetrace：

| 字段 | 原u32LE值 |
|---|---:|
| mount1 / mount2 | 2 / 0 |
| still metadata cache / live | 0 / 1 |
| movie metadata cache / live | 1 / 1 |

这提供了metadata/live区别的动态实证：still并不一致；movie实时值1已直接取得。
不能从值1直接推出物理第二槽，也不能由缓存一致推原REC具体消费了该字段。
当前不再重复相同readback场景，等待原校正器/业务映射形成具体下一步。

main已打开本run原REC图，仍为“插槽2无卡”。8条原事件、22PNG RGB、全卡SHA
与FAT16全树通过，另重跑hostfsck0；原Flush0、owner217恢复。卡仅DB/XML，
产物候选0，卡SHAb9549987b62030bb05bd78e82c8ed4d8e86612d3cf3d775b01cf64dd9fa25671。
consoleSHAfd163f3faa7b273b8cf7d09952cb8d49fdd46859f5fa984a8072bc73e051b280；
SD恢复console5538行，原回读5566行起。runtime-manifest的helperSHA
8694f1804673bcc53577f98008fa094dfafaa99fba3df3354e8ee9378e5b15f7已核。
限定review为本run media-live-consumer-review.json，原整体false保持。

## 命名校正器核对：当前不是可实施修复

Grok调查到原函数26e2c44，对应prettyname
`correction_setting_movie_recording_media_contradiction`。main独立匹配完整
668B窗口SHAf2d21154c733b210bcfdeda8ee0bcab58cc51670f897e82143a702f335cba378，
核指令确认它先要求simul_rec==1、still live==2；然后按其它flag和挂载状态
调整still ID59f。25158b0/80B亦核原摘要；并未据函数名称当作movie setter。

当前run读回still live1不满足该入口的第二条件。这里没有观测到函数实际调用，
不能由事后值推断过去从未调用，也不能把现在mount1/2的值套到过去调用时刻。
本体未见直接写movie live，但间接commitdispatcher2506ff0未追，不能把有限
结果说成所有传递调用绝无影响。main另从原name表505c120核ID3069名称为
osd_transfer_image_status；numeric0/1含义及运行值仍未知。

该入口当前暂停，不调用它、不改438d分派项、不把movie1当它产生的错误值。
本轮未形成设置或协议修复。下一定向入口为原NoCard提示资源在AP内的实际
表引用及选择分支；已找到同low16的0200a1a8三处data候选，须先证明命名空间
与文本关联，不把low16相同直接当REC代码证据。无新增VM测试。

## 提示记录关联到原谓词，准备被动观测

最新静态结果已由main复核原ELF重定位：记录58fe850的+28指向1875afc，
+50指向377b098（含0200a1a8）；另记录58fea30的对应项指向1875c9c及377ebf8。
R_AARCH64_RELATIVE的原r_offset/addend逐项核验，RW file偏移按VA-10000处理。
main核完整谓词116B/84B，SHA分别为
f509050a4740523b3e1f3fa852ea0451f4836350cec2d646f1306056743d8716、
96f48c64a568460436ab2935077ca70f425ea995153a83fb53248b1d393ce29c。
两者都比较still live==1及mount2!=2，第一条还要求G286cfc8==0或G2879804==1。
它们不读取movie live。只能确认消息列表与同记录谓词关联；尚未证明REC选中哪条，
也未证明0200xxxx到UXC1e00xxxx的namespace转换，不能把静态布尔值当原调用。

新增默认关闭的被动GDB观测`--media-predicate-probe`，只在原REC提交前挂四个
硬件执行断点（两个entry及原MOV w0后return点），记录caller/stack、原字段和返回值。
不调用guest函数、不改寄存器/业务值、不用softwarebreakpoint。日志最多128事件，
达到上限明确标truncated并关闭断点，不宣称全覆盖。entry/return按原栈帧配对。

使用既有owned run/PID/原AP SHA/readbackbase/Unixsocket绑定和QMP恢复确认；
CPU恢复未证实继续保留VM，确认安全才导出SD。独立评审发现的两点已修正：
媒体与原queue观察模式互斥；trace错误或结果缺失独立上报，不以CPU恢复成功掩盖。
host63项含原字节pins、callback错误/上限、旧queue启用拒绝、QMP/生命周期/SD保留
相关回归通过。真实断点行为及REC调用证据尚待新单VM，不提升capture_verified。

## run-snf7m9ix：谓词真实执行与返回已取得

原1875c9c命中64次、返回64次，所有栈配对成功、原w0均1，LR归一caller均
1883194。entry字段一致：still/movie live1/1、mount1/2为2/0、额外两gate为1/0。
另1875afc未记录到，但第128事件后明确达到上限并关闭全部断点，不能证明其
不调用或后续无其它规则。断点在host REC提交前启用，但日志没有逐事件时钟，
不能把所有64次都归因于原REC已消费；只证明这段观测窗口内确实原执行。

SIGINT正常清理、未强退、无traceerror、无unreturnedentry，独立QMP确认CPU
running后完成SD。8事件/22PNG与全卡SHA/全树独立通过、重跑fsck0、原Flush0、
owner217恢复；DB/XML以外没有产物候选。卡SHA
44ec9066793aca7f02a7040a4b0a2cb93a513c6fdacf087039e9c92eb9c06c11，
eventlogSHA2ad906a80f5fb7a989f68553fd66910c572aaaf0f9a86c6087fb6cb2b3aab06d。
main实际打开REC截图，仍为“插槽2无卡”。限定review在本run
media-predicate-consumer-review.json；原整体false不改。

该caller带来新精确入口：原1883160从参数x1首u16取规则index，经GOT5ba52f8
取tablebase58f03a8、stridea0，调用record+10hex谓词；返回后可能按其它gate
替换成record+28hex的byte值。后续18831f4再按优先级选规则，因此原谓词true
还不是最终提示选择。main完整核原172B evaluator，SHA
7ad78d8d291de38a4eafa2f3a836db743d0bed8e175ad992732a6ca1c6d1c878。
实际规则recordbase须以该tablebase计算，先前“anchor+28/+50”仅是人为锚点。
候选1875afc对应index16e/base58fe868，1875c9c对应index171/base58fea48，
真实predicate/member偏移分别是+10/+38，不再把锚点当struct起点。

## 下一步：观察最终规则选择

在同一默认关闭的私有GDB设施增加`--media-policy-probe`：只断18831f4入口与
188331c原返回点，按原70hex栈帧配对。读取原返回规则号，再核原tablecount876
及GOT表指针，读选中record的predicate、priority、targetword、message-list及其
首u32。不执行predicate、不改结果、不解释0200到1e00命名空间。
FFFF保留为原“无选中项”；其它越界、表身份不符或消息指针超原rodata均记录失败。
新增host单调时钟与REC提交前的host标记，区分提交前采样；仍不把host提交
等同于原REC已消费。事件上限/独立CPU恢复/SD导出/error传播继续保留。
相关64项回归通过（新规则解码与界限/原字节pins含在其中），动态最终规则待验。

## 首轮最终规则观测的host失败及修正

b52fd3bdf/run-__u5936d失败于host：main编辑时把queue_watch.start缩进到了
REC条件之外，body循环第一项C1就对None调用start。尚未创建GDBconfig或发REC，
没有原最终规则证据，不归因于固件，也不称观测通过。原失败和proof false保留。

已把start及提交时钟恢复到REC条件内，新增回归直接抽取并执行实际production
body循环AST，分别验无观测、predicate、policy三种模式的按键顺序和唯一启动点，
不再仅测试观测类而漏掉调用位置。相关67项通过。自动关闭路径有独立SD导出：
卡全文SHA3bce3851f688b1bda29fffedb7d0fe5fb294ee2a2e876e970e79ee7cb4e47658，
host重跑fsck0、原Flush0、owner217恢复已核；存储恢复不消除观测失败。
限定失败review保存在本run media-policy-failure-review.json。下一轮修正后重验。

## run-vxnfl8qv：最终选中规则171与消息列表已读到

修正后gate成功。原18831f4共有64对entry/return，caller均18833d0；host REC提交
标记前3次返回FFFF（未选中），之后1次FFFF、60次171。所有171调用的entry时钟
也在host提交之后，首个171原返回发生在标记后142.481118ms。它不是原按键消费者
PC的精确时钟，不超出该时序范围推论。128事件后明确截断，不称完整后续覆盖。

运行时核原876项count和GOTtable identity后，真实选中记录为index369/171，
recordVA58fea48，predicate1875c9c、priority116、policybyte1、target33a，
message-list VA377ebf8，首u32为0200a1a8。因此此前静态候选已推进到实际选中
规则及其原消息列表。entry字段仍still/movie live1/1、mount1/2为2/0，谓词
读still live而非movie live。原LCD依然显示“无存储卡／无法拍摄动态影像／插槽2”。
0200a1a8到UXC1e00a1a8的namespace转换仍未独立验证，不用同low16补完该边。

GDB正常SIGINT退出、无trace/cleanup错误、无未配对entry，独立QMP确认CPU running
后原Flush0/SD owner217恢复。8原事件、22PNG RGB、全卡摘要/全树、重跑hostfsck0
通过，只有DB/XML、捕获候选0。卡SHA
3df14a8784a61a3fd73671726327d286749a81327ea5ed3aab565edeece9b28c，
eventSHAf52beaafb6b98cc36b0f5d74f9b73e1647f704fef89404d6c07721abf44067ce。
本run media-policy-consumer-review.json限定true，原整体false保留。

来源清单边界：runtime-manifest核media_predicate_watch.py摘要aa094c0f…，但当时
未包含共享request_queue_watch.py和host checker；wrapper曾检查两者且main冻结，
不因此声称manifest已覆盖。已补后续run的两项清单，旧manifest不回填。
当前下一项是实际still live1的初始化来源及单物理槽能力配置，禁止直接改为0消提示。

## 资源key对应已核：1e不是需要转换的namespace前缀

主会话继续核原libObj（SHA c0897d72a40bf0a161fa7f89e9a34eef4d19e0506c7817a5c11a6f53897cdbbc）
导出符号`libra::RecordPtr::getResID()` at11ce38，其尾调123e3c。
后者LDR原header、AND03ffffff，再仅对kind3做bank插入；本key的kind为2，直接
返回mask结果。84B原helper SHA52b44e391d26ab4231de2ae5dba5dd227f77c51fb9a0c4206039545720625aee。
1242f0的原header构造反向亦把type低5bit移到bit26后与keyOR，不把它当namespace。

因此UXC原header1e00a1a8的确切ResID是0200a1a8，type bits为7，正是已选规则
消息列表的原u32。对应UTF8文字在5568开始，限定NUL窗口内完整为
“无存储卡。\n无法拍摄动态影像。\n插槽2”，原资源全文SHA再次匹配。
此前保留的“namespace conversion未知”是假设的未闭合边；现在由原格式实现
核清，无需编造prefixrewrite。完整动态TextSprite/render调用链仍未采样，
不能将这项静态key对应扩成所有UI消费已验证。

原pin和解码过程保留scratch/movie-nocard-dialog/original-resource-key-proof.txt；
新增原件/资源key回归，13项相关host检查通过（含已有观测及snapshot子集），
不与先前67项相加宣称全面功能通过。后续source manifest同时补共享watch及host
checker，旧runmanifest不回填。两路调查继续仅追still live初始化及单物理槽能力。

## STILL写入链：事务ID397a已核，初始值来源仍未知

来源侧交付后，main独立核原描述符5ad9460起64B及RELA
5ad9488->1bf5c58：它把STILL属性59f、普通setter1bf5c58和高层setter1c28bac
关联在同一描述符。后者经1b6eb2c菜单值转换后进入25e56dc，使用事务ID397a、
早期4B参数，再调用25e54c4更新同一live字段。常量1在dirty标志位上，
不是初始still1的producer。2a7ee58从保存单元8370b50恢复到同一字段，也未证
本run实际调用或保存单元的原始值。

此处397a只命名为原事务/dispatch ID，不能直接当BKP持久化键。36eb21c以
(ID-379d)*1d索引内存表，返回值还覆盖了调用者早先的width4栈word；未证后续
参数仍是简单{width,data}，也未证存储文件/offset。1b6eb2c->1b6ea8c在B8步长
item表里按entry+4匹配输入、返回entry+60，找不到返回-1；具体表源和值未知。
因此不能把高层setter当作传入值恒等映射或本run数字1的来源。

原bytes/hash证据保留scratch/still-media-value-origin/main-verification.txt；
该调查当前提供精确写入入口，没有产生可实施修复或新的VM结论。单物理槽能力
侧仍在独立调查，不调用setter、不覆写事务/BKP或默认选择值来隐藏NoCard。

## 单槽能力候选与实际机型索引入口

`PRM_FEATURE_MANAGER_num_of_media_slot`及其DOUBLE/SINGLE标签存在于原参数
调试表。main核相邻连续指针run起点57fd340、该项相对候选ordinal10；尚未将其
证明为wire/property ID。代理所述bodydata→product_model→能力赋值→各normalizer
链只由名称支持，不能当原代码合同或据此改能力值。

main已找到实际update_product_model函数1797b84：调用三指令getter285be30读取
7e504d8的word，检查不大于25，经370cb50的26项跳表映射后写5bc35b0；后续
feature getter据该索引查询常量表。这只证机型输入到表索引，不等已定位槽数量
getter。索引文件初始值25不能代替运行值，也不直接代表槽数量。

现有只读诊断增加FEATURE_PRODUCT_MODEL_LIVE与FEATURE_PRODUCT_TABLE_INDEX两word，
均固定原VA，沿同run原task及appFw映射验证，不调用固件API、不写机型或能力。
原12B getter、444B映射函数和stores已有pins；69项相关回归通过。
下一独立单VM取得这两个新值，同时能力侧只追槽数量真实getter/数值合同。

## property0a的固定getter与能力名关联边界

能力侧追加结果已由main核原16B分派row（VA5b2be78/file5b1be78）为
{fn1798134,id0a}，其24B函数用5bc35b0索引读取370e3e8的26word常量表。
表值为1/2/3；原消费者2244e64明确把1与2/3分到不同路径。
main原bytes/hash在scratch/single-slot-capability/main-slot-getter-pins.txt。
getter与20项PRM名字表同序的绑定仍是结构关联，尚未核名字resolver/dispatcher；
不把它升级为完整能力正常化消费者合同。

代理“main已确认A7CII运行index25”的说法已纠正：25仅是原文件初始值，当前
b2f71a009尚待实际回读。不能据此称A7CII固定index25、或将raw2/3推成物理
槽数/CFexpress种类。待实际index到达后可直接按原固定表复算此getter输出，
标明是derived值，无需再起VM或调用固件API；不把它当FEATURE_MANAGER/HAITA
实际缓存已消费的证明。无代码改动，当前运行源码继续冻结。

## run-8j1lvsyz 超时停滞：已恢复并取得机型输入

用户追问后主会话检查发现，b2f71a009并未成功返回：原driver在诊断时串口超时，
后来host任务退出，但保留GUI/VM约4.5小时，不能继续称它是正常等待结果。
真实原因是八字段诊断被拼成过长物理行，BusyBox交互shell截断后留下不完整if，
显示续行提示符`>`，连完成标记都未收到。新增字段未实际执行；后续诊断/取消
继续拼入该不完整输入，host在无deadline的清理等待中保留VM。原失败proof不改。

本次恢复先核owned host/child PID及stdin pipe身份，只发Ctrl-C+换行丢弃未完成
输入，取得原主提示符后才逐条发送短的只读命令。得到原取消回执
SD_FSYS_CANCELLED seq890194963345765 pid217及Flush rc0，owner217为S(sleeping)。
原发布card.img与candidate.img的全文SHA均
b5ef840ed38658c51040c23fac938a07c148910326b565cc1ecc21448979fa5e，独立fsck0。
确认以上内容后仅中断owned host的永远等待，QEMU正常退出；再关闭本轮遗留
GUI/Xvfb，无SIGKILL，不碰其它VM。原export.json仍保留false，恢复证据另存。

恢复后实读product-model VA7e504d8=09000000（u32LE9），table-index
VA5bc35b0=10000000（u32LE16），均原menu-readmem/RC0；不是文件默认25。
该原getter1798134的固定表[16]=1，只能标作按运行index计算的getter输出。
具体physical-slot语义及原exclusion缓存消费仍需证据，不能由此单独判能力错误。

修复已实施：诊断改为各物理行不足200B的多行if；serial_command发送前核含真实
sentinel的各行不超1000B；一次事务超时后标记失步，连cleanup也不再盲发。
诊断errorJSON保留此前已完成的SD导出结果，避免后续失败覆盖唯一成功证据。
新增实际host-shell八字段+真实sentinel、超长行未发送、超时拒cleanup三项回归，
相关72项通过。新单VM b543c3ee4验证完整短行读回与自动退出，运行源码冻结。
源码主会话只在前一VM退出之后修改；新测试不改变机型/能力/媒体状态。

## 默认加载器调查的当前收口

最新代理确认1bf20e0仅8B `mov w0,#1;ret`，main原字节复核通过；它在菜单描述符
中被复用，未证调用者把返回值用作默认设置。数字1不能据此当初始化producer。
代理所举59f0000000加载基址不属于已验证run，已排除，不影响原ELF live VA。

它找到的raw writer2773018直接把w0写7e6e7f0。main继续闭合到实际分派API
28bb120：fieldID作为首参数，base5584c38、stride30hex，调用record+18hex，
第二参数w1成为writer的w0。ID59f的实际record为5595a08、函数指针5595a20。
这给出可观测的原scalar写入口，但没有证明它在boot何时被调、值1由何处加载。
不能调用此API来跳过初始化。原pins在
scratch/still-media-default-loader/main-live-writer-dispatch-pins.txt。

常量回调、typed option、vector复制与RAM恢复都尚非实际默认值来源或BKP key。
目前不把静态候选升级为修复；当前短行验证任务完成后先核8字段及自动清理，
再决定最窄的原写入观测位置，不继续以相同末态读回来代替初始化证据。

## run-r3ogewti：长行修正的真实验证完成

八字段原读取均RC0，完整值mount2/0、cache0/1、live1/1、product9/index16；
原完成sentinel收到，driver退出0，无cleanup_error/保留资源，本轮owner进程及
QEMU已退出。SD原Flush0/owner恢复、独立全树/摘要及重跑fsck0通过，卡SHA
388c8520cc3506be2b8481e2f15444cea3a71c3bc626dbea956ff7a1c9840c9f；无捕获产物。
8原输入与22PNG摘要匹配，原整体proof false仍保留。

多行输入会先回显`> echo LABEL_BEGIN`，旧parse未锚定行首，导致原JSON后续字段
raw_output包含此前字段。实际原text里每项值和RC完整存在，main独立按独立标签
行复核；另存media-state-readback-main-reparsed.json，不回写旧JSON。parse已修为
仅匹配独立输出行，加入交互回显回归。该修正不要求再起一轮相同VM。

下一实验默认关闭：在原Application_System_Init调用前有界10秒调试等待，
从明确原pid/base marker装硬件数据watchpoint到7e6e7f0；只记录初始值、真实
写入、PC/LR及有界栈，不调用setter、不改寄存器或model/BKP。基线若已1则不能
当首次初始化证明。该实验影响调试时序，结果只用于定位writer，不作自然开机
性能或成像验收。相关77项host回归通过，独立评审和真实实验结果待验。

## 早期写入观测的评审修正

独立评审发现退出时未统一清理早期watcher、旧marker不能保证连接早于init、
部分记录后异常stop可能漏报。真实VM尚未启动；三项先修正后验。
所有live/外层finally在quit/terminate前先guard_shutdown，CPU恢复未确认则保留
owned host及VM，不因host退出触发bwrap连带销毁。标志位是observer自身volatile
调试门：10秒等待中为1、结束为0；GDB连接暂停CPU后实际读1才装watch，过期即拒绝。
这只改变显式调试实验的观测器，不写原业务字段或BKP。异常stop不因已有write记录
而免报；只有指定watchpoint完成或SIGINT清理可正常结束。

77项相关host回归通过，含两层退出guard、恢复未证时保留、过期门拒绝与部分trace
原ABI observer构建与独立复审正在完成，均不替代真实首写证据。

原ABI构建已exit0，实际新产物是runtime/analysis/menu-observe.so（329776B，
SHA2569ff71bbe0db7d4870051599f1747001b9f113ef4731e6206a041a7b219f37bb0），
包含本轮pre-init gate完整格式。menu-root/simulation副本需由既有initramfs准备流程
安装，不能拿尚未安装的旧副本冒充新构建或guest消费成功。复审与真实运行待验。

复审确认两P2已修，但又实证启动异常的直接QMPquit绕过guard，以及guard日志写满
会抛错逃出保留。两项继续修正：QMP统一函数在任何quit发送之前先guard；日志写入
失败best-effort，不影响unsafe状态下保留host。新增实际QMP函数执行回归和模拟
ENOSPC保留回归，82项通过。最后两项由main直接检查并测试，未宣称第三次独立
评审通过。新串行首写实验baa8f812a已启动，原业务字段/寄存器不写，结果待核。

## 首写实验第一轮失败、自检gate排除及重验

baa8f812a/run-r0w4qxau并未取得首写证据。启动自检check-menu-observe也提供
Application_System_Init stub，原gate先在其pid194发出，计算base7f9c80010c
不对齐；随后真实pid217/base7f3b678000另发gate。host误接第一个便失败退出，
而“唯一性检查再过滤”的次序即使多等也会拒绝两个marker。原GUI首次导出也RC1，
原driver失败、保留VM；结果不称初始化失败或硬件watchpoint成功。

恢复先核原取消回执908421185377183/Flush0及owner217为S。尝试第二QMP连接
b17cf56a4在欢迎消息前timeout，尚无Flush/读数据；不冒充恢复成功。后改通过
原GUI控制器既有export_sd动作，b134f6020完整成功，新sequence910772522034771、
owner恢复、cardSHA61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727，
独立全卡摘要及fsck0通过。旧失败report另存，恢复记录另存，不回填观测true。
核卡与CONT后中断owned host等待，QEMU正常退出，再关闭本轮遗留GUI/Xvfb，无SIGKILL。

源码只在前VM退出后修改：observer自检及未对齐base不再发实验gate；host共享同一
合法identity筛选函数，先过滤、后检查唯一性，无合法项继续等，多合法项仍拒绝。
原buildidentity和GDB实际gate=1检查仍保留。显式早期模式串口就绪后，还须看到原
GUI_MODEL_COMMITTED非零packets才宣告ready；不把任意GUI导出RC1忽略或无限重试。
83项相关检查通过，含真实stub/real marker顺序复现与首次GUI发布等待。
新串行任务b98871489重验首写，运行源码冻结；尚无新的首写结果。

## run-cydfn8br：真实gate连接成功，未映射冷代码页导致trace失败

b98871489并未取得写入证据。GDB已连上真实gate并核active=1，但在Linux内核
PC停机时提前读原raw-writer2773018页面，QEMU返回Cannot access memory，
尚未装数据watchpoint、initial_value=null、writes0；不得称初始化字段不存在。
原未执行代码页可以尚未建立guest PTE，先前只在应用运行后做的runtimecodepin
检查不能直接前移到该时刻。失败JSON及原日志保留。

此轮实际首设/原输入/REC都走完，SD成功后host正确上报observation_error并退出1，
没有遗留VM。独立全文SHA1fe06822887601edfca8820833beaa8cff277318267a2125010a863fdca5d259、
host重跑fsck0及原owner恢复已核，原GUIowner进程不再存在；限定失败review另存。

修正先在observer等待前只读一次目标BSS word，触发正常只读缺页，不写原值。
GDB先装原Application_System_Init入口1796918的硬件执行断点；真正到该PC时
再核原12B指令和当前字段baseline，然后删除entry断点、安装4B硬件datawatch。
这既绑定原调用时刻及地址空间，也避免提前读取冷writer代码页。相关83项回归
通过，fake GDB明确断言原entry指令只在entry停机后才读取，不以测试冒充guest命中。
新单VM b23d41a38运行，source冻结，首次写入来源尚待原实际记录。

b23d41a38后续终态为host等待门失败，尚未启动ownedVM：原外部相机结束后又有
新的full-system相机进程出现，wrapper按单VM规则拒绝并发。这不是新的GDB/固件
实验失败，无新run、无本轮SD待恢复。主会话核日志后更正状态，不据此改实验代码。
wrapper现对外部替代进程重新绑定pidfd继续等待，但总deadline仍为原30分钟，
没有增加kill/新并发VM权限。2项回归验证替代进程等待及原child锁释放通过。
新排队任务b3b3decbd继续同一首写实验，真实相机结果尚未取得。
