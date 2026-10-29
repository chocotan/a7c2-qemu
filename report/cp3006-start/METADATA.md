# 0201元数据发送端：有限实现与路由边界

此处给出固定2.01原CP发送端9aa584的typed合同及独立C实现。
`runtime/analysis/device-models/cp-slot1-metadata.c/.h`尚未接入observer或CP服务，
也不是811006e9 registry/receiver、0201完整postwork或3006成功回复。
原CP身份仍为18090880B/SHA256
`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。

## 输入与精确派生

实际work context N指向快照root D；T=*(N+44)是该work已有的bank alias，
不是重新找一个空bank。字段的业务语义未证，只保留原宽度：

| typed字段 | 原来源 |
|---|---|
| x/y/z/w，u32 | D+688 / +6c8 / +784 / +774 |
| q，u8 | u8(*(N+9c)+a) |
| a，u8 | u8(*(N+14)+1c) |
| alternate，u8 | 18b9580+80 |
| t20/t91 | u32(T+20)、u8(T+91) |
| input_I | 有来源的原1107178模式字，仅支持3 |

原a4bd66恒返回2，所以本调用选a99804，而不是旧摘要提到的T+92 fallback。
先按u32计算`v = (t91==1 ? 3*t20 : t20)`（乘3必须先32位wrap），
再算`n = (uint64(v)*cccccccd) >> (t91==1 ? 36 : 35)`，最后取n16。
不能先无界乘3、不能饱和clamp。I3的qmode结果是q在{1,2}时1，否则0；
这是已核模式分支结果，不证明原feature对象指针已初始化。

```text
primary(x)   = [4,2,0,2,1,f,3,f,5]       (x<=8，否则f)
alternate(x) = [4,2,2,2,2,f,2,f,5]       (x<=8，否则f)
map_y(y)     = [0,2,f,3,3,3,f,3,1,2,f,1,4] (y<=c，否则f)
rate         = w+1，仅y∈{3,5,7}且w<=2；否则0
eq1(v)       = (v==1)，不是普通bool(v)
base         = map_y | primary<<4 | eq1(z)<<8 | rate<<10
               | qmode<<13 | n16<<16
altbase      = (base & ~3f0) | alternate(x)<<4
```

## 三种20B格式

所有偏移十六进制、小端；手工编码，不依赖host struct对齐。
原程序只写前18decimalB，末两B来自实际allocator内容，**保留、不校零**。

| 字段 | 偏移 | A | B | C |
|---|---|---|---|---|
| kind u16 | 00 | 0d | 3 | 3 |
| subtype u16 | 02 | 8 | 20 | 21 |
| reserved u16 | 04 | 0 | 0 | 0 |
| aux u16 | 06 | 10 | 0 | 0 |
| flags u16 | 08 | 8000 | 8100 | 8100 |
| packed u32 | 0a | alternate非0用altbase，否则base | base | altbase |
| extension u32 | 0e | alternate非0用eq1(a)，否则0 | 0 | eq1(a) |
| 原未写residue | 12..13 | 保留实际两B | 保留实际两B | 保留实际两B |

C不是B的可选替代。tuple变化时，原先尝试B，再尝试C。

## cache与正常返回顺序

原cache是六个u32 x/y/z/w/q/a，加n16；q/a的u8输入零扩展存cache，
不是eq1之后的值。没有generation递增、validbit或事务token。

1. 捕获完整typed输入和n16。
2. 如果cached.x不同，独立allocate/build/send A。
3. 比较原cache七字段与输入；不同则依次独立尝试B、C。
4. 若各callee正常返回，按原顺序提交x/y/z/w/q/a/n16。

分配或发送失败不阻止后续消息尝试；正常安全清理后仍提交cache。
同tuple下次不自动重试。alternate不属于该tuple，单独变化不触发消息。
`cp_meta_publish`返回0只说明sender pass已结算，结果另列allocation/send
错误；**不代表消息已到registry或订阅者，不能直接满足mandatory postwork**。

## source、owner及明确的安全替代策略

固定逻辑SID=811006e9，20B allocator参数flags0。原payload的隐藏source
初始化为a5a5a5a5，9aa584没有改它；proxy读取并封装该marker。
marker不是动态reply queue，更不能用3006回复池来释放这些packet。

三个packet独立分配。IO适配器必须返回实际20B backing和真实source，
send0移交payload/lease，允许接收端同步退役；非0仍由sender持有。
成功移交后组件不再访问payload。适配器不能保留传入的栈descriptor地址。

主会话独立核对了原失败路径：9aa6c2把sp+20（指针槽地址）传565300，
而565300在56538c直接将r1减18再操作refcount，并没有先解引用指针槽。
因此不能把旧路径称为安全void** free；未运行或复现其故障后果。

**新仿真组件明确选择安全替代策略**：失败时release实际payload/lease，
不复现对未知/栈地址的refcount/free。该修复不是原错误路径字节等价。
若release也失败，组件保留allocation、锁存fault、停止本轮且不提交cache；
允许显式retry_release退役，fault不会自动恢复。持有allocation时拒绝销毁。
不能靠默认send0掩盖失败分支，也不能丢packet后报告移交成功。

## 实现与核验状态

独立C代码复制输入和IO描述符，锁外执行实际IO、拒绝重入/执行期销毁，
PID检查先于mutex。cache必须由调用方按真实cold/history建立，不能每次
用当前tuple创建cache来抑制消息；没有自动reset API。

原固件2.25 libc/pthread/loader AArch64 `-nostdlib -mno-outline-atomics
--no-undefined`独立链接通过。C源码SHA256
`c0537ffd117d063ac479d9b028c2d2cb81c226b96ffeb9648333d4155c0dacf9`，
头文件`bb46f8ff6bfbd17030dd306000ed082dbc81bbcbb364bcd66a69d7120858d525`。
独立逐行静态评审已完成，所检查C/H范围未发现confirmed P0–P3或越界完成
声明；主会话已核对评审/ABI的C/H摘要一致。评审没有执行测试或guest。
实际C ASan/UBSan及相关回归终态已核：**7 passed、35 subtests passed**（0.86s）。
新metadata sender为11个case（3格式/wrap/边界、同步退役、receiver持有、输入/IO描述符
复制、cache、allocation/send/mixed失败、清理失败与显式retry、错误source、fork）；
另有publication7及旧transport17个子测试。这个结果不包括registry真实投递或guest验收。

## 未完成边界

811006e9的真实CP/BB registry路由、订阅匹配和后续lease退役仍未绑定。
main检查的AP/libObj位置都是发送者，旧default-off subscription echo及
81106114 candidate不作为消费者证据。不得新增一个空receiver返回0。
完整N/D、原feature backing、deferred/diagnostic等其它prefix/postwork也
仍需真实接入；此实现和host fixture都不证明硬件ready、guest投递或3006成功。
