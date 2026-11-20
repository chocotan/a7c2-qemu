# P1 第四十四跑：4080 派生参数合同与 40a1/40b6 参数续推

本轮实现 `0x4080` 的完整派生合同：CP handler `0x357bd4` 先把 request[8] 零扩展写入参数 word +0x1fc，再调用 `0x8da97e` 依活参数区重算 +0x22c/+0x230/+0x234/+0x218。4080、40a1、40b6 均获原 AP 实际运行消费收据；40b4 已按原 handler 实现并通过宿主检查，但其验证跑两次在早期启动门控（system_mode 读回）被基础设施故障拦截，未到参数链，运行消费收据待补。不改 AP 状态、EE、exclusion 或镜头状态，不用构造成功回复跳过原调用链。`capture_verified=false`。

范围为用户已授权的独立本机 QEMU、RAM 卡和原 App32 输入。沿用 candidate43/runtime-3 的 direct-bootin 诊断入口，不能替代原 Sony loader/WBI、真实 CP、物理看门狗或实机拍摄。镜头线按用户指示跳过。本轮续推 3 个命令（40a1、40b6、40b4），未超范围。

## Evidence → Finding → Path

| Evidence | Finding | Path |
| --- | --- | --- |
| candidate43/runtime-3 原失败，wire `050080404100008000000000` | destination90030001、source80020002、type5、4080、12B 返回−1020 | 原 AP → CP 参数 SID → 缺失派生合同 → Imaging3109 |
| `4080-audit.json`、`4080-helper.stdout`、`cp-008da97e-300.json` | CP 0x357bd4：ldrb request[8]→str.w +0x1fc→bl 0x8da97e；helper 三分支重算 4 输出，调试日志无状态效果 | 写入+派生义务 → 本轮 DERIVED_4080 合同 |
| runtime-1 `0082` console `NATIVE_CP_BACKGROUND_PARAMETER_ACCEPT ...opcode=0x4080` 与 `NATIVE_CP_BACKGROUND_4080_DERIVED` | generation38、+0x1fc word 值0、free0、handler_executed=1；branch_known=0、4 项派生输出全 unknown（前值未被任何已实现命令写过） | 原请求构造和原 sender → 既有 owner → 派生未知按 unknown 记账，不伪造零基线 |
| runtime-1 首个负发送 `0x40a1`，wire `0500a14045000080ff000000` | 新前沿 40a1/type5/12B rc−1020 | 续推 #1 |
| `40a1-audit.json`、`ap-40a1-audit.json` | CP 0x8db332：ldrb request[8]→str.w +0x750，表 apply-control 0；AP 0x35362f8 批量构造 | STORE_BYTE owner +0x750 |
| runtime-2 消费 `opcode=0x40a1 ... value=0xff ... free_rc=0` | generation39、+0x750、free0 | 续推 #1 收妥 |
| runtime-2 首个负发送 `0x40b6`，wire `0500b64046000080ff000000` | 新前沿 40b6 rc−1020 | 续推 #2 |
| `40b6-audit.json`、`ap-40b6-audit.json` | CP 0x358bac：ldrb request[8]→str.w +0x780 | STORE_BYTE owner +0x780 |
| runtime-3 消费 `opcode=0x40b6 ... value=0xff ... free_rc=0` | generation40、+0x780、free0 | 续推 #2 收妥 |
| runtime-3 首个负发送 `0x40b4`，wire `0500b4404700008001000000` | 新前沿 40b4 rc−1020 | 续推 #3 |
| `40b4-audit.json`、`ap-40b4-audit.json` | CP 0x358b14：ldrb request[8]→str.w +0x77c | STORE_BYTE owner +0x77c，实现+宿主验证完成 |
| runtime-4 与唯一重试 `attempt-1.json`、`failed-run-4-review.json`、`failed-run-4-retry-review.json` | 两轮均 `capture gate system_mode: missing, corrupt or conflicting readback`，早期启动门控失败，17 项早期参数已消费、深链（4147/4080/40a1/40b6/40b4）未达、0 负发送、无 FirmwareFault | 基础设施时序故障，非参数链失败；一次重试额度用尽，40b4 运行消费待补 |

CP 输入 SHA256：`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。AP 输入 SHA256：`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。原输入只读，不把原固件或批量运行输出加入公开报告。

## 实现和复现

生产改动在 `runtime/analysis/device-models/cp-background-device.c`：新增 `DERIVED_4080` 合同（写 +0x1fc 后调用 `derive_4080`）。`derive_4080` 是 `0x8da97e` 的逐指令直译：W[21c]==1 分支输出常量 2/2/2 且 B[218]=(W[214]==1)；B[2a4]==2 分支全零；否则按 W[1fc]/B[228]（选择 W[224] 或 W[200]）/W[208]/W[204]/W[20c]/W[210] 重算。三分支选择序与原指令一致。关键诚实约束：原 helper 无条件覆写 4 个输出；当某输出的输入字节未被证明已知时，该输出按 unknown 记账（known=0），陈旧已知值被丢弃，绝不以零基线顶替。运行实证：runtime-1 中 4080 派生行记录 branch_known=0、unknown_predecessors_dropped=4——与"无已实现命令写过 0x21c/0x2a4 区"一致。

40a1（+0x750）、40b6（+0x780）、40b4（+0x77c）为同一 STORE_BYTE 模式：request[8] 零扩展 word 写入，apply=1（表 apply-control 0），free 原请求、不加 ACK。既有 owner 的来源、尺寸、重入、故障锁存、free 和 fork 守卫全部保持。

测试登记在 `runtime/analysis/test_cp_opcode_batch.py`：4080/40a1/40b6/40b4 加入 256 值域、错误来源/尺寸、free 失败、重入、fork 与全 opcode 场景；`update_expected` 对 4080 做独立三态转录（与生产实现独立成文、逐值对账）；wire 场景用实际失败 wire（4080 值 0、40a1 值 0xff、40b6 值 0xff、40b4 值 1）核对零扩展、邻接未知与原请求释放。新增 `device-models/test_cp_derive4080.c`：以 include 真实设备源的方式直接驱动真实静态 `derive_4080`，覆盖三分支全值域（W208×W204、W20c×W210 全 65536 组合）、全部未知路径、部分字已知、以及"已知输出被未定派生失效且保留原字节"的覆写语义；该文件不进 observer 构建，无生产面新增。

受管任务目录为 `scratch/a7c2-capture-p1-runtime-20261115-candidate44/`。pre-change 基线以 candidate43 闭合收据锚定：restore/ 由 candidate43/restore + 其 runtime-3 diff 重建，逐文件 SHA 与 `final-verification-3.json` 的 after 摘要一致（prepare.py 独立断言）。`integrate.py` 执行 candidate34 主管线（两组两线程宿主检查 + observer 构建 + CPIO + derive），driver 通过完整 SHA 绑定。恢复按精确差异反向应用，保留其他已存在未提交修改。原失败收据保留，不回填。

## 运行与资源

第一轮 `0082`：4080 消费闭合（generation38、+0x1fc 值0、free0、派生 4 输出 unknown）。`final-verification-1.json` 两组两线程通过：UPM 两笔、all13 accepted、broker attach、guest observer SHA256 `ee0330cbf7a4444d77ca6458edf75089292ffb164d9838e3f8497cfd64ac8cf7`、93 文件归档完整读回、detach、唯一 ID QMP quit、QEMU rc0、无信号、租约到退出。单轮覆盖 25 个参数 opcode（含此前分散在各轮的 4147/400f/40d3/4151）。原运行仍以 FirmwareFault（40a1 前沿）失败，不记拍摄通过。

第二轮（extend 2）`40a1` 消费闭合（generation39、+0x750 值0xff、free0）；`final-verification-2.json` 通过，同项生命周期全闭合；新前沿 40b6。第三轮（extend 3）`40b6` 消费闭合（generation40、+0x780 值0xff、free0）；`final-verification-3.json` 通过；新前沿 40b4。

第四轮（extend 4）`runtime-4` 在动作1早期失败：`capture gate system_mode: missing, corrupt or conflicting readback`。`failed-run-4-review.json` 两组两线程确认：干净退出（quit/rc0/无信号/租约/runner 关闭）、SYSTEM_MODE write n=1 已现、早期批量参数（401c..4177）17 项消费、深链 4147/4080/40a1/40b6/40b4 未达、无负发送。唯一重试 `runtime-4-retry` 同文件（逐文件 SHA 比对、未重建产物）后同因失败；`failed-run-4-retry-review.json` 确认同类基础设施门控故障、同样未达参数链。两轮失败与 40b4 实现无因果证据（失败点在参数链之前的无关子系统门控），但按纪律一次重试用尽后停止，40b4 运行消费收据待下一跑补。

EE 0x7e34c58 current 未到 RUNNING、capture_inhibit 未清零、无自然 4038/JPEG——`capture_verified=false` 不变。快门前深链推进到 40b4（含），40b4 之后的下一前沿尚未观测（第四轮未达）。

空间门禁为 64GiB 余量加 12GiB 新增峰值，已通过；生成前可用字节见 `manifest.json`。最终新增实占、保留原因、下一消费者及实际文件系统可用量由 `storage.json` 记录。当前不回收受保护原日志、恢复前像和当前 derive；这些材料交父会话核收，不能仅因是 scratch 即删除。
