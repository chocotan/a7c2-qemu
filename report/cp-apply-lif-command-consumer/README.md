# APPLY 的 LIF `0x1c` 工作项：实际消费者与输出

本次闭合了 `3e9584→a5c422` 工作列表的实际 consumer，并找到了命令 `0x1c` 的条件输出合同。原件表中的该命令长度为 **1 byte**；15 B队列项中的13个未初始化尾字节不进入这次命令输出。这修正了“未知队列尾部必然阻止消费”的过宽结论。

此结果仍不足以放行 type5 前缀：runtime support、可写元数据表绑定、实际DMA/定时器执行和镜头接收未知，另一条44 B替换队列也未完全闭合。源链已追到UART1/DMA1；DMA callback忽略错误位，故最终event3本身不能证明无错误发送。`central_history_complete=false`、`302c_native_verified=false`、`capture_verified=false`。没有启动新 VM、改 observer/build、原 CP、GPIO、ready 或模块 mask。

## 复核

从本成果目录执行：

```bash
python3 report/cp-apply-lif-command-consumer/verify.py
```

显式指定公开原件：

```bash
python3 report/cp-apply-lif-command-consumer/verify.py --cp runtime/analysis/menu-root/cp/cpapp-b.bin
```

要求既有 Python Capstone；不联网或安装依赖。脚本首先检查 CP 原件大小18,090,880 B和 SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，再核验[86个字节窗口](source-pins.json)，共4,068 B（15 B/LIF路径及生产者21窗1,114 B，独立44 B路径12窗816 B，UART/DMA链及桥接20窗1,002 B，延迟入口和双flag4窗264 B，输入flag setter/调用及dispatch表13窗210 B，独立gate反例5窗86 B，slot退休/暂存3窗148 B，release状态与guard8窗428 B），以及实际调用目标、注册槽、元数据表、UART/DMA寄存器和callback。256个序列号的帧算术检查和8个替换槽位检查是条件参考计算，不是运行时帧或镜头消费证据。所有地址为CPVA；仅文件映射地址使用 raw=CPVA−`0x108000`。

## 延迟入口与双flag边界

`98ec9c` 的输入r1在原 `98eca8` 保存到r4；非零分支可走到 `98ed12→9cf8c6`。为零时由 `98ecee→9a7ffe` 读取独立字节 `165d2c1`，若读值为0，`98ecf2` 跳过 `9cf8c6`。这只跳过该callee：入口在此前已有局部计数和其它调用，不是整段无副作用。r1和该字节的启动状态尚未闭合，不能用这道gate为前缀补一个默认不活跃状态。

APPLY设置的是 `A=u8[1b163d4]`；相邻 `B=u8[1b163d5]` 是另一字段。`9d30ee` 设置A=1；`9d30fc` 清A和B；`9d3120` 复制B=A。原 `9d3136` 读取B，构造 `(B==0)`，再与A逐位AND；它的caller `9cfca4` 比较返回值是否为1。对完整byte域，该条件等于 `A最低位为1 && B==0`，不能无依据把任意非零A解释为true。

`9d3136` 是工作 `9cf8c6` 在 `9cfca4` 调用的getter，不是调用工作或唤醒队列的producer。源中的一条分支在 `9cfe5a` 调用 `a4abc0`，随后 `9cfe6a` 才调用 `9d3120` snapshot。验证器核了这两种字段和实际指令，并穷举65,536种A/B条件算例；这些不是原运行时值，也不证明所有工作分支经过同一顺序。详见[APPLY保持边界](../cp302c-prefix-apply-preservation.md)。

`165d2c1` 的真实setter入口为 `9a7edc`，在 `9a7f06` 把输入r0存入byte `165d2a8+19`。值改变时它另在 `9a7efa` 写辅助word `+20=000000ff`，并调用level3 telemetry；该word不是ffffffff，不将setter缩减为只改一位。

已核10处直接调用的显式输入如下；这张表不证明它们在本次启动实际发生，也不是全部计算地址或bulk writer的穷举证明。

| caller PC | 显式r0 |
|---|---:|
| `3b04da`, `3b05bc`, `990f4c`, `9d211c`, `9d24b8`, `9d26d6`, `9d2740` | 0 |
| `990f30`, `9d2514`, `9d2b8e` | 1 |

真实入口 `990f1c` 的前缀先在 `990f30` 置1，经若干原调用后在 `990f4c` 清0。另两处置1属于release状态处理分支；具体条件和执行时点仍需实际输入，不能从clear后零值推导这些分支不发生。工作 `9cff92..9cffa0` 通过原表 `decd58` 间接调用handler：index5映射到 `9d222e`，其中存在上述条件置1；index7映射到 `9d1ff4`，可达 `9d211c` 的显式清0。原release状态值和首次有效handler尚未闭合，不能借中央current或旧cold mode代入。

还有一个已核的源码反例，说明清 `165d2c1` 不能推出入口不活跃：`3b04c8..3b04ce` 先将实际release bank的 `+198` 写1，紧接着 `3b04d8..3b04da` 又把 `165d2c1` 清0。后续 `3b0c54..3b0c78` 从同一root `10ff418` 读取bank+198，作为r1传给 `98ec9c`，可走非零输入分支。是否实际到达这一分支仍未知；这里证明的是两个gate字段独立，不能把一个清零当作整体无工作。原件 `10ff418` 的初始指针为 `18b8fd8`，运行态root绑定仍需单独验收，不能从该文件值声称当前实际RAM状态。

## release状态的首次选择仍需实际输入

`9d09a8(r0,r1,r2)` 更新的是 `u8[bank+17c]`，不是中央CURRENT。原 `9d09b6` 比较完整r1是否为ff；仅相等时改用旧byte+1，随后 `9d09ca` 写入低字节。因此r1=ff、旧byte=ff时写0；r1=1ff则直接写ff，不能先截断r1再识别哨兵。r0参与诊断编码，不是新状态。r2=1还会清独立byte `1b1624c/1b1624d`，不能省略这些副作用。验证器覆盖256个旧byte和10个显式请求值，共2,560个条件边界算例。

已定位直接reset：当 `u8[1b16270]==7`，`3b09f4..3b0a00` 向bank+17c写ff。这个有条件工作不能冒充已执行的开机构造器；post-clear的实际root绑定、首次调用和其它写者仍未知。

还有一条不要求APPLY双flag谓词成立的state5路径：`9cfca4` 比较结果不是1时可进入 `9cfdbc`；若 `9a7fe2()==0`，继续 `9cfdf2→9df0d6`。这个guard返回1且旧release byte≤4时，`9cfe0c` 给r0赋0d，`9cfe62/64` 给r1/r2赋5/1，`9cfe66` 实际调用 `9d09a8(0x0d,5,1)`。

该guard来自 `u8[1b16430]`。在同一个外层caller，`3b0b9c→9df0e2` 保存四个实参；`9df1bc..9df1d2` 写入的表达式为 `u8((r0 & ~r2) & r1 & (r3 ^ 1))`。原调用点的输入来源为：r0受 `99bc50()==1` 和bank+198控制；r1取byte `1b16158`；r2为bank+162是否非零；r3来自 `9dac5c()`。本文未给这些首次输入补0或1。

写state5仍不证明handler5已消费：在后续原 `9cfe76..9cfe80`，若 `u8[1b16258]` 非零，会立即再调用setter写7；dispatch前另有其它未闭合工作。故state5赋值、保留到dispatch、handler实际执行是不同证据。当前 `first_release_handler_execution_known=false`、`release_state5_write_implies_handler5_consumed=false`，不能以首次clear0或某个写5位置补完整历史。

## E1 → F1：注册对象不是工作执行

原 `a5c016` 设置对象 `19f2d8c`：`+4=a5c04b`、`+c=3e9585`，随后调用 `a918ca(object,3)`。`a918ca` 只检查 index≤3，把对象指针放入 `1a03d18[index]`；它不立即执行callback。

实际 consumer 是 `405eec(3)`：

```text
406086: load table 1a03d18
40608e: load table[3]
406090: load object+0xc
406094: BLX callback → 3e9584
```

`3e9584` 将待处理列表移到 `1716a40`，从15 B队列取记录，再经 `a5c422(record,1716a40,1716a48)` 登记指针。`a5c422` 按首字节替换同类或追加列表项，带原锁操作；它还可能调用 `a94502` 做诊断，但不会在此直接dispatch中央命令。

原 `3e98ea` 将 `slot+1` 指针登记到列表后，`3e98ee..3e991c` 检查队列count，推进读游标并调用 `a5ca5c`。该helper在resource2d操作间递减byte `1104c4b`，返回新的count。队列为空路径在 `3e99e2..3e99ec` 清 `1b187e6`；之后 `3e9920..3e9930` 才将14 B命令复制到暂存区 `1b187ca`。因此环上slot计数的退休发生在后续列表输出之前，暂存复制也不能自动解释为列表中的借用指针已被替换。

这里没有验证实际RTOS对producer、borrowed list和暂存区的调度/稳定性约束，也没有凭这一顺序声称原固件存在竞态。未来有限模型必须独立证明它实际读取的命令身份和字节稳定；count=0或清pending仅说明对应队列字段变化，不能推出列表已输出或设备已消费。

不能将列表登记、移交或queue flag视为镜头完成。`405eec(3)` 还会先检查command4的support，并可通过对象 `+4=a5c04b` 生成其独立头部；随后原 `4060ae` 循环逐项调用 `a90758(command)`，只有support明确为1才进入 `a91e54`，复制命令实际长度到输出。1c记录的消费长度为1，不代表整个通讯payload只有1 byte；其它头部或实际列表项仍须保留。

## E2 → F2：`0x1c` 的条件消费长度是1

15 B槽位由1 B队列bookkeeping加14 B命令记录组成。原 `a5c366` 在 `a5c3c6` 按 `index*15` 定位槽位，`a5c3ca` 将bookkeeping byte置0，再由 `a5c3cc..a5c3d6` 复制14 B到 `slot+1`。原 `a5c700` 只初始化命令记录首字节 `1c`，因此入队复制确实读取并搬运其余13 B未知源字节；这里不把它们补成零，也不把按字节搬运解释为业务消费。后续列表/输出的命令指针与槽位bookkeeping须区别。

原件 `u32[1107030]` 的文件初始指针为 `120553c`。`a90772` 取6 B记录 `table + command*6`，复制三个u16；它受 `a90f42→a90758` support检查控制。

`0x1c` 对应记录地址 `12055e4`，原始 bytes：

```text
1c 00 01 00 02 00
```

三个word为 `{0x1c,1,2}`，第三字段的业务名称未确定。`a91e54` 从metadata的第二word取得长度，再调用原 `61e60c(destination,record,length)`。在这份表绑定和support有效时，消费的是首字节 `1c`；`a5c700` 没初始化的13 B尾部没有被该复制读取。

这是条件源码事实：`1107030` 是可写的指针位置，support数组在 `1719e40`；本轮没有把它们的当前值读作已知，也没有从文件初值推导原运行已经采用了该表。support不满足时该复制不会发生；不能将“无输出”解释为成功设备操作。

## E3 → F3：输出进入真实通讯请求和发送队列

consumer caller 为 `a910a8(2)`：它检查源对象 `1a03cdc` 的 byte+22低两位，借用 `a902c8(0x440)` 缓冲，调用 `405eec(3)`，取输出地址/长度，复制到借用缓冲+5。

有非零输出时，原指令 **确实**执行：

```text
a911aa → a9366c → a48382 → a478c4
a911ba → a9688c(2)
```

`a9366c` 把 mode、指针和u16长度投影到通讯参数。`a48382` 构造：

| offset | 来源 |
|---:|---|
| 0 | `f0` |
| 1..2 | payload长度+8，LE u16 |
| 3 | mode低三位，本caller设为1 |
| 4 | 实际 `1b1a7b0` 序列字节 |
| 5.. | 实际命令payload |
| N+5..N+6 | bytes `[1,N+5)` 求和后的LE u16 |
| N+7 | `55` |

若payload仅 `1c`、mode1，序列号是显式输入 `s`，9 B条件帧为：

```text
f0 09 00 01 s 1c checksum_lo checksum_hi 55
checksum = 0x26 + s
```

例如s=0：`f0090001001c260055`；s=255：`f0090001ff1c250155`。参考验证遍历了256个s，不把任何一个当作原运行值。

`a48382` 尾调 `a478c4`。独立核对 `a474c8/a475da` 表明：`1101fb0` 是步长 `0x324` 的记录索引，buffer地址和u16长度分别保存在记录 `+0/+4`；`a478c4` 将**记录索引**放入 `19edf2c` 环队列，受resource2b锁和队列状态规则约束。这里不能把索引当作buffer指针。这证明提交，未证明物理发送或镜头接收。`a9688c` 通过 `50ff1c` 将 `40c0ed` worker排到 `1a04258`，其case2还读取通讯状态与待处理记录、检查type/长度/顺序并注册后续处理。原 `406bdc` 查询metadata后，`406be6` 读取第二word（命令长度）做比较；这里不能凭反编译临时变量把它误称为第3字段或设备响应长度。不能删除这些操作直接回成功。

Kuna最初把 `a910a8` 的发送分支截断成空块。本次以原Thumb指令核到 `a9118e..a911e4` 的真实提交及worker调用，随后用显式函数末界重新反编译。原字节pin和验证器以这些实际调用为依据，不采用截断伪代码作为无副作用证明。

## E4 → F4：44 B替换队列的实际reset和completion边界

独立调查确认 `a4a3f2` 构造44 B零记录，经 `a4a430(record,replace=1)` 提交。在旧tail合法为0..7时，它清count，保存旧tail作为head，写replacement flag=1，再把零记录复制到下一槽并将count设为1；记录byte+1d仍为0，不能称为完成。

原指令确定的字段如下，不能把tail/count名称互换：

| CP RAM字段 | 作用 | replacement路径 |
|---|---|---|
| `19ee708` | head | `a4a48a` 保存旧tail |
| `19ee70c` | 最后写入的slot index | `a4a504` 保存next-tail |
| `19ee710` | count | `a4a472` 先清0，`a4a50c` 发布1 |
| `19ee714` | replacement flag | 置1 |

`a4a4c2..a4a4e0` 将旧tail加1，仅在结果为8时回到0，再以 `19ee5a8 + next_tail*44` 为复制目的地址；`a4a4e6..a4a4f0` 先复制44 B，随后才更新tail/count。8个条件算例仅覆盖合法旧tail 0..7，不给未知或非法索引补默认值。

提交后还有两类真实清理：`19ee580+8*j` 的五个flag，以及 `25e038a+0x24*j` 的64个flag。原 `a51d98` 的循环终点为 `0x900`、步长为 `0x24`，这里的64由原指令计算，不能把整条提交当作无副作用的日志。

`a56248` 的原注册目标 `991ff0` 使用level3的 `9b78f8` telemetry；该callback不是队列实际consumer。`a4a784(slot)` 只查询slot+1d状态。`a4a726` 根据live record `169d928`、谓词和active index `1b18372` 更新队列完成byte；**尚未闭合queue→live record的转移，故不能从零记录的条件完成规则倒推原队列已经消费**。

本轮核算12个44 B窗口合计为816 B，以原字节窗口长度为准。另已找到completion更新的caller `992f2e`，其前有 `a5476a→3e2804` 光学工作；该前后顺序仍不证明它就是dequeue，报告没有把邻近工作当作真实记录转移。

## E5 → F5：环队列经过staging进入UART1 / DMA1

`a47962` 在resource2b下读取 `19edf2c[read_index]`，将byte `19edf58` 以modulo10推进；`19edf50` 是第十个ring slot，不是另一个游标。`a47c2a` 按步长 `0x324` 取记录的地址和长度，复制到 `S=*(u32*)19edee8`，然后将所有相同源地址记录的 `+0xc` 置0。原pool record在DMA开始前已经退休，后续设备使用的是staging副本。

`a48084` 返回该staging地址，不能称它为固有的incoming accessor。`406ae0` 的事件2处理先检查queue和发送busy，再dequeue、校验待处理记录；在不允许分派的状态可走拒绝/收尾，不能绕过状态guard强行发包。

源 `a48382→a475da` 保存的记录跨度为 `L=(N+0x17)&0xfff0`。因此一字节body对应的协议header长度为9，实际copy和DMA跨度为16 B。额外7 B frame padding的原内容未知；它们不是原APPLY队列那13 B尾部，也不能用零值冒充已知值。

具体硬件提交链：

```text
406d76 → a9368c → 3e1a94
  → DMA1 callback=a48acd, configuration={5,8,0}
  → 581240(channel1, descriptor)
  → bf69c2 register writes
  → bf6c62 enable
  → UART1 at f1001000
```

初始化 `3e1c54→bfc2a8(1,1102074)→bfbe9a` 写入UART1地址。提交检查source/peripheral四字节对齐和 `L%4==0`；`581240` 还要求channel已初始化且非busy3。静态table将logical channel1映射到controller0的hardware channel1。

| register | 具体作用 |
|---|---|
| `f1058120` | DMA source=S |
| `f1058124` | destination=`f1001000` |
| `f105812c` | word count/control |
| `f1058130`, bit0 | DSB后启用channel |

DMA1中断检查 `f1058000 & 2`；发生后禁用channel，经 `f1058008/f1058010` acknowledge，并从 `1a80c94` 调callback。`bf7074` 确实把 `f105800c & 2` 的错误状态传给callback，但 `a48acc` 在使用它之前覆盖r0，因此不能根据后续timer或event3判定发送无错。

完成源链为 `a48acc→timer10(delay=*(1102078),callback=a48b05)`；timer ISR `bfb088` 调用callback，随后 `a48b04` 停UART DMA request、停DMA1、清理UART，再次安排timer10，delay字段为300，callback为保存的 `a91b67`。第二次timer经 `a91b66→a9688c(3)` 排入event3；`a912de` 清busy `1a03ae1`，再按状态决定后续事件。timer字段单位、运行态初始化及实际device acceptance尚未验证，不赋予毫秒等未经证明的单位。

## 下一条尚未完成的边

Path P1：公共APPLY产生命令1c → 15 B队列 → 实际LIF列表消费 → 按metadata长度复制 → 协议组装与记录索引ring → staging copy及原record退休 → 原UART1/DMA1提交 → IRQ/两次timer/event3。整条源链已明确到寄存器和回调，实际运行数据、DMA错误状态和镜头接收仍需内容证据。

还须核对runtime support/table来源、真实UART/LIF peer返回消息，以及这些操作是否影响中央start/current。44 B队列的dequeue→live record→zero-command dispatch是另一条独立缺口；现有源链不能代替该未知项。

当前不新增 `40b8` 或其它APPLY命令白名单，不发302c回复，不把LIF输出当CMOS帧、JPEG或录像。
