# Silent Mode 与快门类型：已核原代码及未闭合链路

范围：只读分析原 `appFw.so`（SHA256
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`）。旧只读代理在turn limit
结束了部分调查；主会话随后用原机器码抽查了本文关键实现、参数构造和getter。没有由该代理或本文
启动VM、写模型、注入事件或宣称拍照成功。

## 结论边界

- 接受真机证据：**Silent Mode ON 也可以选择电子快门**。
- 仿真画面仍显示 `MECH` 不能独立否定该联动。它只证明该帧的显示内容，不能证明有效
  `0x40b1` 命令、capture engine实际选择或成功执行。
- 但本文也没有闭合 Silent 属性变化后的 exclusion/notification/presenter 链，所以不能声称
  当前仿真已经选择电子捕捉。`run-3w1lebcs` 的同页输入仍停在更早的EE/调度前沿，没有照片。
- Silent、普通still快门、间隔拍摄快门是不同模型属性；不要把其ID或枚举编号混用。

## 原sequence与参数构造

### Silent sequence本身不实现电子快门选择

```text
sequence_set_silent_mode ctor  0x312725c
  getter 0x28680bc -> this+0x18 (setting_silent_mode)
sequence_set_silent_mode::run  0x346dc94
  -> 0x34d10c8 -> 0x352d724
```

`0x352d724` 的完整8字节实现为：

```asm
352d724  str wzr, [x1]
352d728  ret
```

所以进入该sequence或得到这个零状态，都不证明电子选择或硬件消费。联动若存在，必须经过
模型exclusion/notification、其它sequence或下游消费者。

### 普通快门sequence构造实际imaging命令

```text
sequence_set_shutter_type ctor  0x310c9e4
sequence_set_shutter_type::run  0x346da90
  -> 0x34cd348 -> 0x3541ecc -> 0x352bde4
  -> 0x3541e2c -> 0x35358b8(destination 0x90030001)
```

构造器快照：

| 对象字段 | getter | 含义 |
|---|---:|---|
| `this+0x18` | `0x28681ac` | `setting_still_shutter_type` |
| `this+0x1c` | `0x2867edc` | `setting_interval_shooting` |
| `this+0x20` | `0x2867f54` | `setting_shutter_type`（间隔拍摄选择） |
| `this+0x28` | `0x28680bc` | `setting_silent_mode`，供后续ADF path使用 |

`0x3541ecc` 原机器码构造type5、参数ID **`0x40b1`**、总长度12B，并调用
`0x352bde4` 后由 `0x3541e2c` 发送到 `0x90030001`。字符串 `0x4c7fa80` 只是函数签名，
实际converter入口是 `0x352bde4`。

converter只接收 `(still, interval_enable, interval_shutter, message)`，**不接收Silent属性**：

```c
if (product_capability_0x1797fb4() == 1)
    message[8] = 1;
else if (interval_enable == 0)
    message[8] = still;             // 原代码仅接受0/1
else if (interval_enable == 1)
    message[8] = interval_shutter;  // 原代码仅接受0/1
else
    original_assert();
```

这证明普通与间隔拍摄使用不同选择，且产品能力可覆盖为1。值1对应电子/silent选择是与原命名
一致的强语义判断，但本文没有重建完整枚举注册表，也不把该编号推广到其它shutter枚举。

`sequence_set_shutter_type::run` 随后另将Silent (`this+0x28`) 与still (`this+0x18`) 送入
`0x34c73d8 -> adf_sys_set_path@0x34ebcec`。这是另一个消费者，不等于已闭合电子capture override。

## 被动模型读回地址

下列getter是**返回单元地址的leaf函数**，不是直接返回枚举值。未来若做只读采样，应在同一
实验阶段读当前进程 `B + ELF_VA` 的little-endian u32；`B` 是实际AppFw load bias。顺序读取不自动
构成原模型事务的一致快照，读失败必须保留，不能当成0。

| 属性 | getter | 单元ELF VA |
|---|---:|---:|
| Silent Mode | `0x28680bc` | `0x7e6f140` |
| Still shutter | `0x28681ac` | `0x7e6f200` |
| Interval enable | `0x2867edc` | `0x7e6efb0` |
| Interval shutter choice | `0x2867f54` | `0x7e6f010` |

例如Silent getter依次计算 `0x7e50000 + 0x4d8 + 0x1e000 + 0xc68 = 0x7e6f140`；
still getter最后为 `+0xd28`，得到 `0x7e6f200`。不要为了读状态而在目标里调用getter。

## 未来只读观察边界

这些地址用于既有自然调用的观测，不是直接调用setter或绕过原调度的授权：

- `0x346dc94`：Silent sequence入口；`x0+0x18` 是构造器Silent快照。
- `0x346da90`：shutter sequence入口；上述字段已经快照。
- `0x346dad4`：即将调用 `0x34cd348`，参数区包含still/interval/interval-shutter。
- `0x346db1c`：即将调用ADF path，参数区另含Silent。
- `0x352bde4`：`w0=still`、`w1=interval_enable`、`w2=interval_shutter`、`x3=message`。
- `0x3541e2c`：可读已完成的12B `0x40b1` 消息，尤其 `+8` 有效选择；比图标或Silent零状态
  更直接，但仍不是拍照证据。
- `0x2688eac -> 0x2688a08`：capture wrapper/executor边界，不是完成点。

## 未闭合项

1. Silent属性 `0x5e1` 变化后，原exclusion/notification是否改写或派生still shutter `0x5e7`，
   或是否调度上述shutter sequence。
2. `MECH` 图标的presenter/resource到模型绑定。
3. 有效 `0x40b1` 命令及其消费/回复；即使证实电子命令，也仍需EE、实际像素、MPR/Fsys写入、
   host持久化和独立JPEG解码，才能接受照片。

当前主阻塞调查已转到 `sequence_clock case1@0x306e5e0`；本文不将该设置问题误称为当前根因。
