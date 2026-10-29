# REC可录制状态：校验链与真实写入入口的纠正

Task50仍未闭合，没有改容量、recordable或ready，也没有录像成功。最新原REC仍选0x223；本轮只推进状态来源调查。下述main补核与独立A的partial分开，不因地址相同就认定找到原消息生产者。

## A的有限交付与main核对

A/B均已结束并实际落盘`scratch/media-producer-a/REPORT.md`、`scratch/media-producer-b/REPORT.md`，互未读新报告，main已取回全文。A核原input+0xb60/+0xb64与属性102d/102e的对应、另一个导入缓冲步长2074、两个直接caller属于设置恢复/导入。B也独立识别出校验角色，并把两个字段追到设置序列化键。main逐字节复核映射、2074复制和键常量流，认可这些有限事实，不认作运行时消息来源。

此前把379d称作输入snapshot长度不正确：wrapper在x2传379d字节清零缓冲，snapshot仍从x0传入。main另核2e1b068向`buffer[property_id]`写1，并调用另一个索引标记循环；因此它是按属性ID索引的一字节状态表。不能把其长度当数据输入长度。

## 更关键：旧“apply→生产者”解释撤回

main核原28bbcc8：它按propertyID从56c4118中取24B记录，取回函数指针、参数及长度，再调用谓词。102d对应28bbaf4是min/max/step范围检查；102e对应28bbad4是索引与byte表检查。返回值为合法性结果；相关诊断调用记录ID/value，而不是对当前模型值做store。

2e2232c的已核字段路径依次读取snapshot+b60/b64、传ID102d/102e给这个validator；不合法时标记上述状态表。2f55920..2f55944先按mode*2074复制模板到导入缓冲，随后解析，再调用这条校验路径。**这不是已证的运行时媒体状态发布链。** 不将恢复/导入验证碰巧读同一属性ID当作实时媒体消息来源；先前“write-table56c4118”“59e的stub返回1所以不可写”等推断也撤回——该表上的返回值不能证明写入权限。

这里不宣称所有谓词或整个大函数无副作用；只限定已核102d/102e路径的角色和缺少live writer边。没有动态执行这条路径，也没有通过写入值来验证。

## 当前可用的真实property入口

main直接从原5584c38+ID*30hex读取：

| 属性 | +08基值accessor | setter +10 | setter +18 | +08 cell |
| --- | --- | --- | --- | --- |
| 102d | 278c618 | 278c624 | 28483ec | 7e83b28 |
| 102e | 278c648 | 278c654 | 28481dc | 7e83b48 |

两个102d setter将w0写入7e83b10/b18，两个102e setter将w0写入7e83b30/b38；与+08 cell不同。main后续进一步核出下文的基值/运行值层差别，撤回先前把+08等同当前状态的说法。所有地址按原PT_LOAD并计入ADRP后高位ADD，未使用已撤回的7ead84c等地址。

后续可在owned只读硬断这些setter入口，记录w0、LR和原栈，以判断初始化/恢复路径还是运行时消息生产者；也需继续核shadow→current的提交者。它是调查候选，不是已执行采样，更不是许可调用setter。原直接store扫描受限于地址构造形式，不能由“只找到一个writer”证明所有写入仅走某API。

`verify.py`已main实际运行：只读固定AP身份、上述原校验窗口、2074复制及真实property表绑定；live producer、runtime probe和capture均false。本段静态补核没有执行VM或触及外部full路线实例，后续输入对照由下述独立Task67跟踪。

## B的新增边与main复核

序列化map登记将`02cf0f05`绑定dst+b60，将`02cf0b91`绑定dst+b64；main对原2f50200..2f504c0中的callee-saved w23常量流做有界解码，两处登记时实际值与B一致。它们是设置序列化键，**不能改称CP/媒体通知消息ID**。B提供的2ecd99c memcpy和2ecd948转换store是这条解析路径的候选读点，尚未执行；不因在那里能看到同样数值就认作运行中生产者。

main另只读公开ALLLANG seed（固定SHA3dab4f0d...18fe47）：同编码的Backup条目02cf0f05为4B零、02cf0b91为1B 1e，即0/30；这只是数值对照，没有把MR序列化流格式与BK4文件格式混同，也没有据相等断言当前run的初值读取路径。`verify.py --seed runtime/analysis/menu-root/seed-backup.bin`可复核原条目，所有live因果标记仍false。

下一步保留真实setter/提交者方向，同时做真实输入对照：现有fixture为128MiB FAT16，transport与RM已支持对齐4MiB..2GiB普通镜像。main已核高DDR initrd始于440000000，1GiB输入加原cpio仍不碰500000000控制区；新建1GiB FAT16、实际BPB/fsck后沿原REC观察，不写任何容量响应或recordable字段。这个单独案例只能说明更大合法FAT16输入是否影响本次门槛，不是穷举格式/容量，也不预设它一定修复。Task67独占admission自然等待外部VM，前置空间检查不足8GiB即不写。

该对照首轮仅在host输入准备失败，未启动VM：mkfs默认63sector/track把BPB总扇区取为2097144，而普通文件为2097152 sectors。fsck虽0、FAT本身合法，但不满足当前RM后端要求的全长几何，所以严格前检拒绝。原512B BPB、返回码和失败输入SHA `0eeff184920d54f9cdadba0971adfd11b476e67df780ecf514538a5ff3f5f6d1`均保留在`scratch/media-capacity-comparison/fat16-1g-_ju5_4fh/`，不作容量反证。

main仅修host格式化参数为64heads/32sectors，并在assert前保存mkfs/fsck/BPB证据，未降低后端校验。真实32MiB FAT16小测试验证总扇区精确等于文件大小、fsck0、已存在文件拒绝覆盖，1test通过。新1GiB对照已重新调度，原固件/REC结果未收取；本节继续保持producer/capture未验。

第二轮`run-t9_2um0g`中host输入已有效，原文件SHA `cb597447b6e387a015fe82781c039db87005c372d3c665d05dab59e4197e6dde`、BPB2097152sectors与1GiB精确对应、fsck0、源文件未变。但guest在解包约1587381KiB原始cpio时OOM，没有shell、appFw或REC。主会话前检只核initrd地址区间而未计解包空间，这是试验预检不足；失败不能解释成容量条件无效。

原因已在原console和启动器核到：设备树只给kernel5GiB（reg长度140000000），Sony工作区保留后可用1190024KiB。QEMU -m24GiB并不自动扩大kernel可用内存。默认128MiB路径的通过不能推广到完整1GiB回载；Task68记录该输入资源上限，不改已发布P的内存或容量。

当前重试采用仅适用于已证空白数据区的lossless表示：host证明FAT metadata prefix+零尾部与完整输入全SHA相同；data-only cpio只新增这个prefix，原appFw/observer字节身份仍核验。guest在独立tmpfs创建并bind同一逻辑1GiB普通镜像，全OpenSSL SHA匹配才允许原bootin启动；Fsys仍对真实文件/BPB计算容量，未改原容量回包/模型/Backup，也没有扩大RAM或跳过debugger原AP身份规则。host真实tmpfs测试确认全文件SHA相同且读取零洞不增加已分配块；非零尾部则拒绝编码，连同格式/驱动静态测试3passed。guest和REC仍待实测；若有正向变化，还须同表示的128MiB控制区分容量与交付变化，不能据单一案例宣布根因。

首个稀疏case `run-mxbcqae0`也没有运行REC：原BusyBox dd精简配置不支持conv=notrunc，构造子脚本set-e在此退出，SHA启动门阻止bootin，原App/Frame/RM/FsysMount日志计数全0。GUI exporter rc1来自原程序没有启动，不是容量判据。GUI保留后main核owner/socket和上述门条件，仅退出这一个未进入固件的无效VM，再在backend已退出状态正常关闭GUI，pidfd确认旧GUI消失；`main-unstarted-trial-close.json`明确Flush/retirement=false，未冒保存成功。原失败、原控制目录和输入源保留，外部VM未干预。

重试之前main实际执行**同一原BusyBox ARM二进制**（SHA `c3297a7086efe9a001c39fa98d74d125992cf3225cf353ab6ff2238d827c7799`）的dd，使用qemu-user只操作本机私有tmpfs普通文件：移除conv选项后seek保留prefix，逻辑1GiB、已分配299008B，全SHA仍与原cb597447...6dde相同。此证明在`original-busybox-dd-proof.json`，不是guest完整实验的替代。格式/无损编码/原BusyBox seek/私有程序语法等4tests实际通过。新case同时pin原BusyBox在选用cpio中的SHA，guest全镜像Hash仍是启动前置条件，不将前述准备失败全局化为容量无关。

实际重试`run-lptxo5re`现已正常完成。main独立核guest启动前全SHA=源cb597447...6dde、实际RM image_bytes=1073741824、原Fsys成功GetFree结构八word为`ffee,fd95,fd00,fd00,0,0,200,20`。512B/sector×32sectors/cluster=16KiB，65518总cluster减601已用=64917空闲cluster，约1014.33MiB；独立fsck也报12files/601of65518/rc0。

主会话看原LCD仍为“存储卡无空间。”，完整64对原selector entry/return中62次223、2次ffff，未返回0/cleanup错误0，独立CPU恢复true。256个4MiB窗口guest/QMP摘要一致，完整1GiB输出卡SHA `468ecc45a007f9a9bd8a1f082d732e5d18427efe0b718e31c9936a7867d5114f`、原Flush/owner resumed、正常GUI自动化关闭通过。原输入保持cb597447...6dde。限定核验落在run的`main-large-card-comparison.json`，原自动proof不改。

结论仅为这组真实更大FAT16输入仍未解除原REC拒绝；不排除其他容量/格式/配置条件，不把交付编码差异当单因素因果结论。Task67这个有效输入案例完成，capture=false。以下旧named字段的层角色纠正仍适用，不能把它们0/30与本例合并宣称实时状态没变化。

## 更正观测层：旧0/30不是已证的实时值

主会话此前把5584c38表的+08函数认作当前状态getter，这个角色判断错误，不能靠旧测试“地址与该行+08相同”来证明语义。原28bb0ac分发到+08；原28bb0c8分发到+20，后者在模型值读/写及通知链中与28bb100 setter配对。2619d6c的已存反编译另显示+08作为重置源，+20作为原有效值；main没有仅凭这个反编译命名下结论。

main原字节找到更明确的初始化边：ROM pair 4b39f30=(102d,0)、4b49aa0=(102e,30)；28bc038通过2ae00a8，后者从第二表571a560的+20取得callbacks 2b6ebcc/2c3a010。callback先写+08 cell所在基值，再走值处理链。这证明0/30是初始化/重置层本来就有的值；不能据它们宣称动态媒体状态没更新，也不宣称基值在所有路径永不变化。

`scratch/media-producer-main/accessor-layers.json`保存12个属性两层原函数/指令/标量宽度。102d +20读7e83b10、102e读7e83b30，其他字段也需改层（1052甚至不只是固定减18）。全部实际LDR宽度为4B。Task67已用旧observer正常结束后，main才修N collector：原+08保留为`_base08`字段，unsuffixed改为+20，结果及每事件带`media_observation_revision=2`。原API分发指令、双层24个原LDR/RET、4B宽度、fake双层不同值和硬断清理等42tests实际通过。新的标准128MiB正常原GUI/REC采样由`probe_effective_media.py`在同一admission下运行，独立包尚未发布此修正；不使用旧wrapper的force-reaper。旧日志、原REC提示和规则223原命中仍是各自事实；“媒体属性live=0/30”的旧推断撤回。已验SD原卸载/挂载/全文件Read独立于这组诊断标签，继续有效。

### 又一处撤回：分发表键0x1052不是已证的容量字段

`scratch/media-value-alias/REPORT.md`（独立只读代理，main复核原字节）核出分发表`0x5584c38+0x1052*0x30`六槽：`+08`读`7e84078`、`+10/+18`两setter都写`7e83fd4`与`7e84068`、`+20/+28`读`7e83fd4`。这行不是容量统计：

- 两setter的validator记录`0x56dc8c8/0x56dc6b8`都指向范围`(-15,15,1)`，`0x28bbaf4`做有符号上下限/步长检查；字节、扇区或MB都不可能通过这个值域。
- 运行期转接`0x2506ff0(0x103c)`（ROM表`0x4b93828`六个u32=`103c,103c,1047,1052,1,8`）按条件把`0x103c`的值再分发给`0x1047`或`0x1052`；`0x2624298`的原字符串为`set_picture_profile_black_level`，`0x26243c0`起用`0x1037+(selector-1)`算键，selector=6时正好`0x103c`。
- 名字目录`57f99a0+0x1052*8`确实指向`PRM_media_remaining_capacity_of_memory_for_create_new_folder_slot1`，但**名字目录编号与这张分发表键的同一性没有被证明**，而值域反证了直接等同。媒体枚举记录（`...SLOT1_REMAINS`=1/`...NOT_REMAINS`=0）也存在，同样不能搬给`7e83fd4`。

因此`prm_1052_remaining_capacity_slot1`从媒体字段表删除，改放在`UNRESOLVED_FIELDS`/`UNRESOLVED_BASE_FIELDS`（`dispatch_1052_unresolved_value/base08`），只读保留、不计入任何容量结论；`verify.py`与回归测试锁住值域、转接表与键计算原字节。这也意味着此前"named剩余容量=0"的说法撤回；真正容量消费者仍未知。

### 修正后实际采样完成

后续实现为revision3：所有目录派生标签都改为中性的`dispatch_<key>_value20/base08`；对所有键明确名字绑定未验证，1052另列unresolved。实际采样仍是下文原revision2运行，地址/宽度相同不等于语义标签正确，也不冒作已执行revision3采样。

`run-6frwm5f2`使用正常128MiB输入，revision2实际进入原REC。main逐条核64对entry/return及每事件修订号，两层12个字段都存在；其中102d值层/基值均0、102e均30，其余10字段两层均0，各64次。原selector62次223、2次ffff，原LCD仍“存储卡无空间。”。这重新建立**本轮REC时刻**值层0/30的读数，不能追溯修补旧错误层的日志，也不能凭零值或与初始化相同证明其enum含义、没有写者、或整个启动阶段没更新过。

main核32×4MiB guest/QMP块摘要、完整134217728B卡SHA `f4bc982aae5ec7d7a986d6e2109173c7cff313f0933ab13ca818a78f04c534ae`、独立fsck0/11files/4732of65399、原Flush/owner resumed。硬断未配对0、cleanup错误0、独立CPU运行true；原GUI正常自动化完成、wrapper来源未变且未杀任何进程。限定核验在run的`main-media-value-layer-review.json`，capture=false，实时生产者与零值enum语义仍false。N/P两个collector及测试逐字节同源，各42targets通过；包的完整host结果与发布继续独立核。
