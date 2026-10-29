# 中央 NEXT：真实写者、路径选择与 callback 边界

已找到中央目标字段 `1a52ae4` 的具体赋值指令：`4b2a62`。它位于真实入口 `4b29e0` 内，值来自选中路径的末状态；后续另一 callback 才可能在 `b1f238` 将它提交到 CURRENT。源码 clear 返回时 NEXT=0 已证明，首次 AP302c 前的 NEXT、CURRENT 和完整内部启动历史仍未知。

一个会影响后续模型的具体反例：**phase=1 不保证执行过 NEXT 赋值**。非零 `1b1df9c` 分支直接跳到 phase 发布处。本文没有修改运行时模型、放宽 type5 白名单或启动 VM；`302c_native_verified=false`、`capture_verified=false`。

## 复核

从本成果目录执行：

```bash
python3 report/cp-central-next-state/verify.py
```

使用既有 Python Capstone。验证器核原件大小18,090,880 B、SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，检查[50个窗口、2,727 B](source-pins.json)的全部原始字节及摘要，另复用[原启动验证器](../verify_cp_central_startup.py)的20窗口 clear/constructor 证据。结果是静态源检查，不是 callback 执行收据。

CPVA 文件映射范围仅 `[108000,1248b80)`，该范围内 raw=CPVA−108000。以下中央字段均为 CP RAM，未将它们减108000读作文件内容。CURRENT/NEXT 是本文对字段作用的称呼，不冒充原符号名。

| RAM地址 | 源中用途 |
|---|---|
| `1a52ad4` | CURRENT |
| `1a52ad8` | 与 snapshot 内 `+1c` 比较的 generation |
| `1a52adc` | 当前 command |
| `1a52ae0` | 路径选择使用的中间状态 |
| `1a52ae4` | NEXT，选定路径的末状态 |

## 注册、准备与提交是不同步骤

原 `4b7264..4b728a` 构造 Thumb callback 指针 `4d6a99`，在 `4b7286` 调用 `7a73be(0,0x16,1,descriptor)`。参数是十六进制 `0x16`；这里没有证据将它称为 timer16，注册也不证明 callback 已触发。

三个真实 callback 入口 `4d6a98`、`4d7484`、`4d9ebc` 均有原指令 prologue。入口与内部 call site 的关系为：

```text
4b7286 → 7a73be(... callback=4d6a99 ...)
  callback entry 4d6a98
    call site 4d6fc0 → 50ff1c(queue=1a6a6c8, callback=4d7485, ...)
    call site 4d6fde → 50ff1c(queue=1a6a6c8, callback=4d9ebd, ...)

  preparation entry 4d7484
    call site 4d7a98 → 4b29e0(snapshot-cell=173efe8)
      4b2a3e → b1f45c(manager=1725858, intermediate, command, snapshot-cell)
      4b2a56 → b1f4ce(manager)
      4b2a62 → store NEXT

  commit entry 4d9ebc
    call site 4dacf0 → b1f1cc
      b1f238 → store CURRENT from NEXT, after native commit guards
```

`4d6fc0` 与 `4d6fde` 是源中的两次提交调用，不能据此声称它们的 callback 已按同一顺序执行。另有 `4dc5d6→50ff1c` 提交 `4d9ebd` 的具体位置；本报告没有为其周围代码另造函数入口。`b1f238` 本身也是 store 指令位置，不是独立函数入口。

## 外层 callback 的 MMIO / IRQ 触发合同

外层 callback 的直接分发机制已进一步核定。初始化源 `7a748c` 的循环经 `7a731a` 向每个record明确写入bank/channel；首项 `17a8508` 对应bank0/channel0。这里的0来自原store及循环初始值，不是从RAM默认零推导。实际执行过初始化仍需独立证据。

按该初始化和原件bank表 `d6feec[0]=f4830000`，注册代码 `7a7320` 复制descriptor并调用以下原配置操作：

| MMIO地址 | 原代码访问 |
|---|---|
| `f4830040` | `2740fc(0,0,0x16)` 写入输入选择 `0x16` |
| `f48300b8` | `274190(0,0x16,1)` 写入该输入的配置word=1 |
| `f483000c` | `7a7278` 读改写，清bit0，保留其它位 |
| `f4830010` | 同函数读改写，置bit0，保留其它位 |
| `f4830004` | IRQ分发器读取pending快照 |
| `f4830008` | 原回写/ack accessor写入该快照 |
| `f4830020` | 取callback实参；数值、单位和时点未知 |

配置word=1的硅片业务含义尚未确定，不将它单独解释为传感器已使能或已产帧。`274190` 的TBH表entry `2741c6` 为 `d0`，因此source0x16选择 `27433a` 的 `+b8` 分支；这不是假定所有输入共享同一寄存器。

IRQ表原始三个word位于 `eafb60`，为 `{0x25,0,0x7a7541}`；初始化另在 `7a7522` 调用 `5e4fd4(0x25)`。已闭合的分发链为：

```text
IRQ entry 7a7540 → 7a7546(0)
  7a7550 → 7a72ca → read [f4830004]
  7a755a → 7a7298 → write snapshot to [f4830008]
  7a7578..7a7580: only if snapshot bit0 is set
    → 7a737e(record17a8508)
    → 2743dc(0,0) reads [f4830020]
    → descriptor thunk637074
    → callback4d6a98(read_value)
```

实际descriptor采用直接thunk：源 `4b725a` 明确给adjustment寄存器r4赋0；`637074` 从descriptor+8取得callback，将MMIO读值转为r0再跳转。`4d6b24` 引用原字符串 `int_HS0`（`4d71dc`），仅记录该固件标签，不据其名称推导timer、水平同步波形、CMOS完成或像素ready。

这闭合了软件如何消费已到来的pending条件；未证明IRQ实际到达、硬件清pending的效果或 `0x16` 上游生产者。即使该bit为0可在此跳过slot0，也不能用未观测到该IRQ排除全部其它软件提交或中央writer。

进一步独立核验原API入口 `274634`：其诊断参数引用字符串 `GetCaptureCounterValue`（`2746ac`），校验logical slot后尾调同一 `2743dc` accessor。这个名称支持把读值归为capture counter接口，不确定造成capture的信号，也不给counter附加未经证明的频率或时间单位。

另有独立的全局初始化控制：`7a74a6→7a725a` 写 `f49300ec=0`；`7a74ae→7a723a(0)` 写 `f49300e4=0`；`7a74b4→7a7244(0x17)` 写 `f49300e8=0x17`；初始化尾 `7a753c→7a724e` 写 `f49300ec=1`。这些是具体写入值，物理功能未命名，不能当作已闭合的CMOS启动前提。

只读上游调查在公开CP和限定GPL SoC/clock/device-tree范围内未找到输入22的信号定义或与具体producer的连接。此阴性仅表示该次搜索没有取得对应定义；不证明不存在定义，也不把相邻MTG real/dummy同步控制自动接到该输入。当前边界仍是 `未知producer/wire → bank0 input22 → 上述capture/IRQ路径`。

## NEXT 从路径末状态取得

`4b29e0` 首先要求 busy byte `1b1df9a==1`。generation 为0或与 `word[*snapshot-cell+1c]` 相同时才继续；不能从缺少运行态值推导 generation 默认是0。

在 skip byte `1b1df9c==0`、phase byte `1b1df9d==0` 的路径上，`4b2a3e` 调 `b1f45c`，以 `1a52ae0` 和 `1a52adc` 查 manager 的表。`b1f48c` 通过 `BLX r1` 调用选中的路径 getter，将返回路径保存到 manager+8。

`b1f4ce` 从 manager+8 取路径地址；非空时返回 `u16[path + 2*u16[path]]`，即所列路径的末状态。getter 自身对空路径返回0，但本轮未证明实际选中的路径、运行态绑定或错误处理的可继续性，不能据此为未知 NEXT 补0。真正写入为：

```text
4b2a4e  movw r0,#5858
4b2a52  movt r0,#172
4b2a56  bl b1f4ce
4b2a5a  movw r1,#2ae4
4b2a5e  movt r1,#1a5
4b2a62  str r0,[r1]
```

这不是读本地 Backup `300a8`、BB/ADF mode，也不是从 CURRENT 隐式复制。

## phase=1 的原分支反例

原 `4b2a08..4b2a14` 读取 `1b1df9c`；非零就 `BNE 4b2acc`，跳过路径选择和 `4b2a62` 的 NEXT store。`4b2acc..4b2ad6` 仍将 `1b1df9d` 置1。

因此即使将来观察到 phase=1，也须独立证明本次 NEXT 的赋值及对应 generation/path。这个分支只证明旧 NEXT 可以被保留，未确定旧 NEXT 的值。提交端的其它 readiness、boundary 和 path-end 条件见[既有4139源调查](../cp302c-prefix-4139-preservation.md)；本报告不把准备 phase 与提交完成合并。

## clear 的证明截止于返回边界

既有 `60d354→61ed00` 显式清理范围 `[120a418,1b85f5c)` 覆盖 NEXT。NEXT 相对起点的偏移在128 B块内为 `4c`；原 ARM store `61ed78` 的 `STRDGE r2,r3,[ip],#8` 在该轮 `ip=1a52ae0` 时，以第二个零 word 写入 `1a52ae4`。

这证明 clear 返回时 NEXT=0。之后还有已知1111项 constructor 执行，本文没有证明整个 constructor 和内部事件历史保持 NEXT=0，也没有声称直接 setter 的清单覆盖计算地址或 bulk 写入。

## 内部3005生产者的边界

另外一处直接START调用 `47550e→4b28d8(3005,0)` 已沿实际入口核对：生产者入口 `4750e8` 引用CaptureStart诊断，调用者是已排队callback内的 `b0dc68`。`b15e58` 在 `b15e96→50ff1c` 提交callback `b0db5b`，但排队存在不证明该次callback已执行或发生在首条AP配置之前。

生产者先在 `4751f0` 调 `b1f140(3005)`，返回0时 `4751f4` 直接跳到拒绝分支。原native320表中command3005恰有四行，均翻译为3021：

| CURRENT | path中的两项状态 | translated command |
|---|---|---|
| `4e` | `38,4e` | `3021` |
| `8` | `38,8` | `3021` |
| `4f` | `38,4e` | `3021` |
| `9` | `38,9` | `3021` |

这是DualRec拍摄转换；原表没有CURRENT0/command3005这一pair。按同一表绑定且busy=0/CURRENT=0时，具体生产者在START前被拒绝，因此不能把它称为自主开机起态来源。真实runtime表绑定、current和busy仍未观测，不能借本表为原运行补0。

这个拒绝分支并非无副作用：`b1f140` 查询时在 `b1f156` 写busy镜像 `1b1df9b`；`47522e→b20a4a(seq,0,1)` 构造handler0/event8200的32 B通知，经 `4b5fe4` 发送到 `900302d9`。若独立byte `1a5347a==0`，还发送event0203。收尾另调用 `b0dfea` 和 `ae263a(0x40000)`；后者不被本报告擅自赋予时间单位。实际下游通知消费和对其它状态的影响仍未验证，不能用一个拒绝或错误码替代完整历史。

## 仍需闭合的第一条边

首次相关 AP 请求之前，是否有内部 START 建立 busy/command/generation，随后 preparation callback 经 `4d7a98→4b29e0` 在 generation 合法、两个 bypass 条件允许的状态下执行到 `4b2a62`？这一首次有效执行、选定路径和与 commit 的先后关系仍未证明。

[内部START源合同](../cp-central-internal-start-contract.md)已记录具体 producer/consumer 及它们的输入依赖；缺少 AP3000/AP3003 不能排除内部路径。`7a73be` 注册项的pending/IRQ dispatcher已闭合，下一条直接缺口是输入选择 `0x16` 的真实上游生产者和配置前提，随后仍需补首次START、snapshot/generation/path及同一代次的实际消费顺序。

`post_constructor_next_known=false`、`runtime_next_before_302c_known=false`、`callback_execution_order_verified=false`、`record_initialization_execution_verified=false`、`irq_delivery_verified=false`、`upstream_input_0x16_producer_known=false`、`central_history_complete=false`。实际 JPEG/MP4、EE、镜头和 CMOS 均未因本报告推进而验收。
