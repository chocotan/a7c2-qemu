# CP barrier 静态定位与 Gamma 数组误判更正

先前的“字符串偏移表/名字idx6/平行函数表”解释全部撤回。数值加猜定基址后偶然命中
字符串不是寻址证据；独立代理找到真实消费者，main 已按原字节复核。
本轮没有启动 CP 或证明传感器启动完成，也未改任何 guest 业务状态。

## 原件与复核范围

`runtime/analysis/menu-root/cp/cpapp-b.bin`：18090880B，SHA256
`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。
本文列出区域 fileoff=CPVA−0x108000。CP 开头存在 ARM 启动代码，其余区域混有
Thumb 指令、内嵌文本和纯数据，不能把整镜像从单一起点线性 Thumb 解码当完整覆盖。

## 数组的真实用途

`0x1109230` 起为曲线指针矩阵。main 验证前74条曲线均为1025个非递减u32，
首值0、末值0x1fffe，块长0x1004=1025×4。

- `0x11092c8` 的第38个指针为 `0xe2f7e8`，其样点6值0x2e0；
- `0xe37e30` 是另一曲线的样点394，值0xbf4d。

真实消费链中：`42b892 49f23024` / `42b89a c0f21014` 构造矩阵基址；
`42b8a6 50f82300` 选择曲线。`42b980 55f826a0` 和 `42b99e 55f82250`
读取相邻样点，`42b9ba b5eb0a05` 求差、`42b9c8 a0fb05c6` 乘法插值，
`42ba06 40f829a0` 写数值输出。
诊断名 `0xf90472` 为
`const UInt32 *Camera::PQD::Gamma::GammaTable::GetContrastGammaTable(const UInt8, const UInt8)`。
不存在已证的“曲线样点 + 0x364000/0x350000 取字符串”数据流。

## 真正的字符串引用

Thumb ADR16 使用 `Align(PC+4,4)+imm8×4`。Capstone 把操作数显示为相对量 `#0xc`，
旧扫描按绝对目标文本匹配，导致假阴性。

| 指令CPVA / fileoff | 字节 | 解析结果 |
|---|---|---|
| `3642d0 / 25c2d0` | `03 a1` | ADR r1 → `3642e0`，`CheckSetImageSensorBarrier` |
| `35bf42 / 253f42` | `03 a0` | ADR r0 → `35bf50`，`FW: SET_IMAGE_SENSOR_BARRIER[%d]` |

`35bf4c: 01 20` 是 `movs r0,#1`，`35bf4e: 70 47` 是 `bx lr`。
原来当作串首的 `35bf4d` 位于机器码内。文本真实起点为 `35bf50`，不得继续引用旧地址。

## 找到的两个函数及其有限语义

Setter `0x35bf20`，注册的 Thumb 指针为 `0x35bf21`：

```text
35bf20 017a      ldrb r1,[r0,#8]
35bf22 4af22070  movw r0,#0xa720
35bf26 c0f26510  movt r0,#0x165
35bf2a c0f8e013  str.w r1,[r0,#0x3e0]
...
35bf42 03a0      adr r0,#0xc
35bf44 e8f319f3  bl 0xb4457a
35bf4c 0120      movs r0,#1
35bf4e 7047      bx lr
```

即请求+8的字节扩展为u32，写入 `0x165a720+0x3e0=0x165ab00`。
日志受另一对象标志控制，不是写操作完成或首帧证据。

Checker `0x3642b0`，注册的 Thumb 指针为 `0x3642b1`：

```text
3642b8 76f17ef7  bl 0x8db1b8       ; 返回0x165a720（已独立核其MOVW/MOVT）
3642bc 012d      cmp r5,#1
3642be 04d1      bne 0x3642ca      ; 模式不是1则返回
3642c0 237a      ldrb r3,[r4,#8]
3642c2 d0f8e023  ldr.w r2,[r0,#0x3e0]
3642c6 9a42      cmp r2,r3
3642c8 00d1      bne 0x3642cc      ; 不一致才记录日志
3642ca b0bd      pop {r4,r5,r7,pc}
```

这段是状态一致性校验，没有等待循环、定时器或像素缓冲访问。
不能仅据名字把它等同于传感器上电/首帧屏障。

## 注册表与下一步

`0x10fbdc0` 起连续5个u32为 `4146,35bf21,0,0,3642b1`；相邻行步长0x14，
前一行 `4101,35a29d,0,0,364261`，后一行 `4102,35a08d,0,0,364115`。
已证它把这两个函数配对在标识0x4146下；以下沿AP侧进一步核实该标识，
不再按Gamma样点索引找函数。

### AP 对应路径的定点核对

随后在原 appFw.so 中找到 `0x1714214: c1288852`（`mov w1,#0x4146`），其前置
ADRP+ADD 指向 `0x4c7c4f4` 的 `PID_SET_IMAGE_SENSOR_BARRIER`。
另一构造路径 `0x3538660: c2288852` 同样加载0x4146，并写入12B请求的+2半字；
请求+8的字节按输入枚举0/1转换为1/0，`0x35386b4` 构造目的SID0x90030001，
`0x35386b8` 调通用发送函数0x35358b8。输入非法值会调用0x3529600，不能任意代填。

原件文本还包含 `setting_image_sensor_barrier_t`、
`PRM_setting_silent_detail_setting_image_sensor_barrier` 和
`EVENT_REMOTE_ANTI_DUST_FUNCTION_IMAGE_SENSOR_BARRIER`。
这些证据把该命令关联到传感器遮挡/防尘设置；不构成“发此命令会启动成像引擎”的证据。
本轮没有执行这条设置请求，也不把通用发送器返回或调用者清零结果字当成首帧完成。

在成果目录下执行只读复核（不依赖反编译器）：

```sh
python3 report/cp-barrier-correction/verify.py --cp runtime/analysis/menu-root/cp/cpapp-b.bin
```

输出 `verified` 仅覆盖上述Gamma/ADR/函数指针静态证据，传感器启动和拍摄标志保持false。

独立复核报告及完整窗口保存在 `scratch/cp-table-independent/`，错误研究历史保存在
`scratch/cp-imaging/REPORT.md`，其首页已明确标注作废范围。最终结论以本文为准。
