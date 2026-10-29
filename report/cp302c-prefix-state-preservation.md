# 302c 前 type5 参数输入的状态保持边界

本轮不能把全部 type5 配置认定为中央 current 的保持边。已经闭合 20 项接收表绑定及共同 dispatcher；唯一可立即加入有限输入白名单的是 source `80020002`、destination `90030001`、type5、`402a`、完整 12 B。其它输入继续使历史失效，`302c_native_verified=false`、`capture_verified=false`。

[原字节及表绑定证据](cp302c-prefix-state-preservation-pins.json)由主会话从公开 CP 原件独立读回：SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`、18,090,880 B。20 个窗口共 1,362 B；所有地址为 CPVA，文件偏移为 CPVA−`108000`，RAM 不作文件切片。

实际输入首先取自 `runtime/analysis/menu-runs/run-r5a1i38g/central-cp-input-audit-evaluation.json`。另一次独立 native repeat 为 `run-ta52l9mu`：其 `central-cp-input-audit-evaluation.json` SHA-256 为 `5400415b0ea64234149667e86b5d3f80bce1da4396eb983aef3cde2e14c80091`，console SHA-256 为 `18b268b8e480d04bc0e7c2ca92bdddb634ef3f9e18587005303ccf4a678aa7ff`。该 run 同样记录 30 条 type5、20 种 command、完整184 B `4139`、24 B `3007`、24 B `302c` 和后续 `3006`；所有记录仍标记为 API send audit，不能称 CP business consumption。两次 run 都保持 `capture_verified=false`、`302c_native_verified=false`。API 入口可嵌套，计数不称 IPC 投递或 CP 消费次数。184 B 的 4139 正文已完整记录。

## 接收与表绑定

普通 AP source `80020002` 的接收路径为 `4b3a7c → 4b3b04 lock(26) → 4b3b28/35cf70 → unlock → free`；type0/2 才走 `4b6064`。

`35cf70` 使用 `10fab8c` 开始的 350 项表，stride20：`command / Thumb handler / apply-control / old-state / Thumb checker`。支持表为 `d939f0+(command−4000)*8`。下列项均从原件核实 enable1、logging-selector0、old-state0；JSON 同时保留精确的表记录和本轮输入尺寸。

| command | 入口次数 | handler CPVA | checker CPVA | apply-control |
|---|---:|---:|---:|---:|
| 40b8 | 2 | 3589c8 | 362984 | 0 |
| 402a | 2 | 355994 | 35ea5c | 1 |
| 40af | 2 | 3588b8 | 362858 | 0 |
| 401c | 1 | 355034 | 35df88 | 0 |
| 404e | 1 | 355538 | 8db6a0 | 1 |
| 4043 | 1 | 354fec | 8db6a0 | 0 |
| 4070 | 1 | 357028 | 8db6a0 | 0 |
| 4028 | 2 | 355b3c | 35ecac | 0 |
| 409c | 1 | 8db2f6 | 8db6a0 | 0 |
| 4022 | 2 | 8daaa4 | 35f0bc | 0 |
| 4023 | 2 | 355edc | 35f2bc | 0 |
| 4084 | 4 | 357c7c | 36154c | 0 |
| 40fb | 2 | 359f9c | 364b78 | 0 |
| 4051 | 1 | 356bb0 | 3600d8 | 0 |
| 40c5 | 1 | 358fd4 | 363374 | 0 |
| 4102 | 1 | 35a08c | 364114 | 0 |
| 40ed | 1 | 3592e4 | 36380c | 0 |
| 4139 | 1 | 8dacea | 8db6a0 | 1 |
| 4177 | 1 | 35cdc8 | 8db6a0 | 0 |
| 40d1 | 1 | 359768 | 363d24 | 0 |

普通路径调用 checker、清 record+c、调用 handler；apply-control0 时另调用 `996fec`，其效果为 `u8[1b16058]=1`。立即 callback 的参数写入本身不能证明异步链保持 current。

## 唯一已采用的有限接收边

402a 的 `355994` 读取 byte[msg+8]，以 word store 写参数对象 `165a720+160`，随后只有受诊断位控制的日志调用。`35ea5c` checker 比较/诊断；该记录 apply-control1 跳过公共 apply 标记。主会话独立反汇编并核对这两个原窗口及记录 `10fada8`、支持项 `d93b40`。

新 owner 只允许上述完整来源、type 和 12 B 尺寸；opaque 原样记账，不限制成单一 cookie。该动作仅说明本次有限接收保持虚拟中央历史，**不声称实现或消费原配置**，不生成 ACK，不改变 ownership、模块 mask 或中央 current。前后 3007 的合法 402a、错误来源、短包、长包及错误 type 均有严格 C11/SAN 回归。其它19种 command 保持不支持。

## 不能跳过的异步边

4023 的 `355edc` 除参数赋值外，可在 `(P+134|P+198)==0`、旧 P+688 不同于 incoming、且 `(incoming|8)!=8` 时调用 `b20b7c(0)`。本轮两份 incoming 都为2；旧参数门控尚无完整历史。

`b20b7c` 构造 32 B family0/event8306、参数0，经 `4b5fe4` 发送 `900302d9`。原 receiver `4b6698/4b66a2` 经 `4b3e90` 和 family0 注册对象进入 outer `b1ffba`，选择 aggregate+dc actor。专用 `4b4cf0` 的8306分支到 `4b4ffc → 4b5266`；若多项 actor/参数 gate 允许，可经 `4b5620 → b219fc → b21702 → 4b6958 → 4b28d8` 尝试3031。

这证明存在中央 start API 的因果路径，**不证明本轮执行了 start 或改变 current**。完整门控为：`b20476` 先检查 actor `self+20`；随后 `4b4cf0` 的8306分支到 `4b4ffc`，再由 `4b5266` 检查 central actor state、`self+20`、`P+238`、gate byte 和另一对象 `+18`，所有条件通过才经 `4b5620→b219fc→b21702` 尝试3031/3036。actor constructor `b203c8` 清过 `self+20`，但其它 actor event 也能写它，前缀历史没有排除这些写者。

独立读取完整320项命令表确认 current0没有3031/3036项；仅靠“有 start 调用”也不能把 current 改成其它值。`4023` 还继承公共 apply 和异步消费者缺口，因此不能扩展白名单。当前仅允许402a；整段 `history_complete=false`。

404e 的本轮原输入为8 B。若 configuration root `b2ddb4()` 所持指针 byte+2a2 为真，仅参数计数+1；否则 `7ec50e → 7faad4 → 2ab280 → 564b38` 发送12 B 的0901到 `90060197`，其业务消费者另行调查。

4070 经 `50ff1c` 提交 callback475738；worker `51007c` 真实调用 thunk8db644。已闭合的 callback 更新独立 bracketing 字段，并可向 AP 发 type4/1010；它仍继承公共 apply 标记。4139 同步复制176 B到参数对象+870并置 byte+86f=1；该标志的后续消费者也不能省略。

公共 apply 的首级消费及后续 release 工作见 [APPLY 消费边界](cp-prefix-apply-preservation.md)。上述任何未闭合链都不授权把本轮 302c 前 current 定为0、6或8。

## 接续实现

新 `cp302c-no-transition` owner 和 observer 接线默认关闭；实际3007原回复需在发送已返回成功、原sender真实free rc0后才向新 owner 发布前驱证据。全13前置须从各自 owner 的清洁消费快照读取，并保留16份 OSD 资源的2 owners/2 opens；不要求或宣称全局 DMM idle。

正常 `3041` 模式转换与不转换回复分支是独立合同，见 [302c 不转换合同](cp302c-no-transition-contract.md)。新后端目前会在本轮第一个未支持40b8输入处使历史失效，不能以其 host 测试通过宣称原运行302c完成。原 all13 验收、失败 run 和实际输入审计证据保持原样。
