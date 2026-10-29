# 模块2服务00920162：CP本地HCRN缓存

该服务已静态闭合：`92a20845`为CP本地同步服务，回调c0dd1a处理`UPM_CMD_GET_HCRN_URA/00920162`，将最近消费的16B H/C/R/N缓存覆盖到原请求buffer。它在调用时不查询AP UPM、CMOS或时钟硬件。主会话已独立核验[16个源窗口及原件摘要](cp-slot2-service-00920162-source-pins.json)，并从AP `.data+e8`读回静态初始tuple `[0,6,26,31]`。**运行时注册、AP发布及CP更新仍未验证；302c与capture仍为false。**

## 本地注册与路由

CP bec01c将可选参数r2/r3置0，进入564d60。该CP分派器认为：非负handle为local；负handle若`handle&70000000==10000000`也为local，其余才走remote。92a20845匹配本地分支564df0；queue ID0845在root120f7c0下的层级索引为4/1/0/5，不能据AP OSAL对domain的不同规则将它误认远端。

原initializer c0dc50以r0=92a20845、r1=1a8b678、r2=c0dd1b、r3=0调用5648f8注册同步callback。通用wrapper为bebc34，actual callback为Thumb c0dd1a，argument为0，owner block+14保存同步descriptor。initializer忽略注册返回码，因此执行了initializer不能证明原注册成功。

通用wrapper先解queue锁，以`r0=payload,r1=callback_arg`调用actual callback，再加回锁并返回transport0。回调的return寄存器不作为响应状态；transport0也不是H/C/R/N中的任何word。没有原子128bit snapshot的源证明。

## 精确返回数据与更新

c0dd1a仅比较payload首word00920162；命中后从11f70f4加载四word，覆盖全部16B请求。响应不保留命令，也没有f000业务status。

| payload | CP缓存 | 字段 |
|---|---|---|
| +0 | 11f70f4 | H |
| +4 | 11f70f8 | C |
| +8 | 11f70fc | R |
| +c | 11f7100 | N |

c0dc8c/c0dc90显式将CP缓存四word清0。后续CP power worker596b60接收queue9092083f，00920256经表项596be2→596e30，复制message+4起16B到同一缓存。因此getter只能返回“初始化后且尚无已消费更新”的零缓存，或最近实际消费的发布值，不能写死tuple。

AP原件的静态发布记录是`[0,6,26,31]`，与CP初始零缓存不同；这也不是AP运行时值。其发布链为：UPM `.text+53f0`构造20B`[00920256,H,C,R,N]`→k_upm_snd_cp_comm(+27c70)构造含length20的24B本地消息，source80920021、dest80920022→worker callback(+27a70)按length经upm_notify_wrapper_async转发9092083f→CP worker消费并写cache。

AP off-factor policy会更新该record，例如+6ac0..6ae4、+6c2c..6c54复制选中记录后发布，clear_hcrn(+5d58)恢复C/R/N=6/26/31并发布。Backup00920020参与producer中的R归一化，不是getter现场读Backup。H/C/R/N的字段顺序已证；字母全称和完整enum未据此命名。

## 原caller的消息生命周期

模块2 caller328d18..328d8e：

1. 565204(handle,&P,16,1)分配；先尝试wait0，fffffc01分支可按传入wait1重试。P-0e为u16 refcount=1，P-0c为source，P-8为长度16，并写前后canary。
2. bec024(P,90030001)写source metadata；初始16B为`62019200000000000000000000000000`。目的仍是handle92a20845。
3. bec01c同步分派。成功才将原P四word复制到working C+de0/de4/de8/dec；失败保留这些原字段。
4. 565300(handle,P)以P-18内部header经bec070减引用，最后一引用释放storage。callback不增引用，不把getter分配交给publication worker。分派成功/失败均只释放一次；分配失败不分派也不释放。

原失败分支包括：参数/过大payload/无pool分配返回fffffc00或fffffc06，实际分配失败fffffc01；local owner或同步callback不存在返回fffffc04；本地分派缺pool返回fffffc00并受诊断设置影响。另一个remote-sender-absent返回0分支对此handle不可达，不能作为空响应成功理由。

unsupported模拟后端也不等于这些原失败分支已实际执行。失败必须如实记录；不能以默认0、AP静态tuple或虚构transport成功填working字段。

## 有限后端与后续验收

可实现三个有实际数据效果的虚拟CP操作：注册并初始化该服务的零缓存、消费完整20B00920256更新、执行识别00920162的同步cache复制。未知命令/handle不扩成通用ACK。cache读回必须来自同一owner的已消费数据，publication chronology与runtime coverage另留证；新actor不会自动声称原CP注册或AP发布已发生。

当前 `cp-upm-hcrn` 宿主模型回归通过 **15 passed**，使用严格 C11、ASan/UBSan；覆盖CP初始零缓存、完整 `00920256` publication、`00920162` 同步in-place复制、未知命令/handle、短包/未知mask、publication失败保持旧缓存、查询失败和fork/重入边界。该回归不证明原运行时注册、AP publication 或 native 302c 消费。

新宿主模型不能代表完整模块2：后续真实运行仍需绑定AP发布数据、虚拟CP消费该数据、同步getter写回和caller四word复制/释放。应以非零发布记录区分真实数据消费与未触及的零buffer；服务成功不代替其它8c736a业务、正常view刷新或中央module boundary。
