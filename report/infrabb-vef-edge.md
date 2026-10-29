# 第四条图连接：InfraBB OUT1 → VEF IN1（格式相同分支）

`run-6uf1qibg`已通过第四条有限等值格式边：同步20B命令copy/Prepare/Execute、实际80B SSYN02写读、216B consumer Close/Free0及唯一56B回复由原AP258/TID381释放rc0/fault0/ap1。本轮四边958测试/139子测试、原ABI、同SD/退出双锁与独立原内容复核通过。见[四边收据](four-edges-native-proof.json)。`infrabb_vef_connection_native_verified=true`仅限本条已验证的相同格式路径，`capture_verified=false`。

## 限定原件合同

完整静态依据见[原静态合同](infrabb-vef-static/CONTRACT.md)，公开CP SHA256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。该文地址为raw，CPVA=raw+108000。此次补核currentinfo ordinal0构造、同步Prepare/Execute和原端口对象，未重复整套启动分析。

本边source=`{0,2,1,9284074a}`（BB 21对象slot5/1789434），sink=`{0,1,1,905a0048}`（VEF16对象slot1/178cab8）。不是已经连接的BB IN1，也不是旧VEF OUT3→PinMem IN1。

64B原Connect、64B0100 peer请求、72B8100回复、唯一56B8001 AP完成，完整S/P与动态caller，source1→2→0、sink1→0、peer完整读回与pending清除。控制信封replySID0，不能沿用Get的自SID信封值。

**同wire会在早启动先被尝试。** 前三边未就绪时只拒绝并增加unadmitted_count，不接管request、不消耗一次性requests、不锁存事务fault；晚些真实图阶段可以准入。同一owner没有reset或重新构造。准入后失败仍保留故障/缓冲且拒绝重试。

## 同步命令和格式实际消费

VEF IN1从currentinfo选择独立**ordinal0**：构造值20B为pinIndex1、ordinal0、code1/component0/flags0、1920×1080。旧VEF→PinMem路径使用ordinal1，必须保留。

内部36B `2002/f008`消息携带该20B，实际复制/读回；context1经wrapper→Prepare把命令state写0，context3和类型表`{1,2,2,2}`选择同步Execute。本分支没有另一个异步模式任务；公共旧命令list只保留，不清空、不声称原CP全局空闲。

Execute要求新VEF IN1已connected0，然后：

| 步骤 | 原合同及本实现 |
| --- | --- |
| VEF allocate | 152B DMM20，unit404、option1、waitFFFFFFFF，creator source905a0048 |
| 写实际backing | 80B SSYN，header word02000000、ETRY type0、key0、offset40/16B |
| payload | `01000000000000008007000038040000` |
| creator Close | 152B DMM25，仅close，owner仍活着 |
| 通知 | 80B1000/0104/38/1，P,S,404,handle,offset0,0，VEF→BB |
| 引用移交 | 同一owner移交，无command21 share |
| BB Open | 216B DMM24，token55、option0、waitFFFFFFFF、semantic owner284 |
| BB实际读回 | 从mapped extent读取80B，核容器/key0，复制16B并与本地已知BB表比较5个语义字段 |
| BB Close / Free | 216B25关闭consumer；216B23 **option0**归还owner，不使用旧option2自动关闭 |

引用顺序为1/1→1/0→1/0→1/1→1/0→0/0。实际pool继续旧世代，physical500000000/CPalias80000000，所有handle/extent/generation/范围有界验证，foreign Speech405/406不动。

只实现**格式相同**分支：code、component、完整u16 flags、宽高都与公开BB表投影相同；payload+4不参与语义比较，但16B全量摘要保留。不同格式时，原实现会改表且因为BB IN1已connected0继续转发同一handle给上游。该转发尚未实现，所以新模型必须fault并保留buffer，**不得Close/Free或以相同ACK假装消费完成**。

BB source8100后的自身posthook因dir2直接返回，不再生产一份格式；VEF sink没有第一边那种额外BB连接marker。

## 所有权、前驱和验收界限

新`infrabb-vef-connection.c/h`与`infrabb-vef-format.c/h`独立维护本地工作/缓存，前置前三边必须同PID、clean且原AP已消费，原旧VEF→PinMem/NoMem、AB失败/AIP S0、两条ordinal、寄存器/时钟及其它registry状态保持。独立消息与buffer引用分别管理；所有外部callback在私锁外，发布前检查fault，最终wire先复制，发送失败/并发free不会重复释放。

原216B helper创建动态2a/owner284临时端点；虚拟同步provider采用显式本地sender身份，不宣称执行了原CP任务、RTOS或页表。原虚拟map验证也不代替原CP page-table属性读回。

104测试含真实前三边和旧VEF/NoMem前置、早启动拒绝后再准入、20B命令copy/Prepare/同步Execute、152/216B消息、SSYN02实际读回、相同/不同格式故障、Close/Free0、独立reply与失败所有权。主会话另复跑第三/第四/pool新API共222项通过。独立8f4review核源语义、引用退役、in-flight free和早准入，无P1–P3。

本轮早启动先拒绝同wire（requests0/faults未变），晚些前三边消费后准入。console12360..12397记录实际请求、20B同步命令（current/command FNV `3c3a32bb6809f4cc`）、SSYN02 packet FNV `472ea89986f7114b`、payload FNV `1a3c540ebc5023bd`、handle8800和最终Close/Free0，再由原AP释放唯一回复。与首边handle8400承接同池世代，无reset/Share21。

四边同run两次Fsysflush0、两export与host三文件全树SHA、cleancommit/owner257760组/QEMU退出/双锁实际独占通过。独立c9逐字节/归档283源/在内存重放严格评价器与SD锁复核无P1–P3；本轮公开收据保留9负边和302c未完成。

默认关闭开关`A7C2_INFRABB_VEF_CONNECT=virtual-infrabb-out1-vef-in1-same-format-v1`要求第三边及完整前置链。不同格式转发仍拒绝；后续第六PinMem路径会触发变化，须真实沿已有三段连接传播并更新现有owner，不能拿本次same-format成功覆盖。没有图像帧或JPEG/MP4成功声明。
