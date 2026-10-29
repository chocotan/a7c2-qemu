# unit431退休边界：动态输入仍禁止覆盖

**本轮只闭合静态所有权接口，不证明任何已保存run满足安全复用条件。**
独立 `cmos-source` 的单租约测试不能代替原固件DMM引用的退休证据。

## 已纠正的判断

原av-cam raw `0x1d42f8` 调 `0x1d4964`，处理的是已完成NV12输出队列。
后者在 `0x1d4a4c` 明确加载类型 **0x639**，并在 `0x1d4a60` 调Share。
这不是unit431释放，也没有等待unit431所有读者。
原件SHA-256为 `90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`；
这里的raw地址加 `0xffffffc001000000` 才是KVA。

## 三条不能混为一谈的所有权路径

| 路径 | 原始位置 | 能证明什么 / 不能证明什么 |
|---|---|---|
| Last-pin keeper换引用 | handler `0x1c2e34`；旧image Free `0x1c300c`，新image Share `0x1c3184` | 静态有条件替换；不等于RC作业完成 |
| RC作业输入释放 | callback `0x1d3138` → `200b:1383` → handler `0x1d1ebc` → input Free `0x1d2744` | 成功执行可证明该作业放弃输入；不包含keeper或其他分支 |
| DMM全体引用/打开状态 | 原 `dmm.ko` op28 GetUnitInfo | 聚合计数快照；仍需排除稍后重新Share的已发布作业 |

keeper通过 `0x1c3238 → 0x278b88` 释放旧image，通过
`0x1c32bc → 0x278eec` Share新image。分支器 `0x1bb39c` 的附加下游还会在
`0x1bb70c` Share image，因此一次Free不等于最后一个读者退出。

主会话已逐指令复核：`0x1d2734` 从 `job+0x6c` 载入原input handle，
`0x1d2738` 设置option2，`0x1d2744` 调 `0x278b88`。
SA在已观察的这条支路读取RC输出，不是原unit431；SA完成不能替代input引用统计。

## 原DMM op28与op2a必须分开

以下是 `dmm.ko` **`.text` 段内偏移**，不是av-cam raw或运行KVA：

- op28处理函数 `0x5408` 在 `0x544c` 调 `dmm_unit_ctrl_GetUnitInfo@0x97d8`。
- 它把reply `+0x0a/+0x0c` 作为reference/open输出参数，`+0x08`为extent数量，
  `+0x10`为总尺寸，`+0x14`为类型；status是 `+0x02` 的s16。
- `GetUnitInfo` 先验证handle generation；`0x9838–0x9844` 分别读取unit记录
  `+8/+9`的reference/open计数并写入上述输出。
- 原Free在 `0x94d4–0x94e8` 发现reference>1时只减一，**返回仍为0**。
- injector目前的op2a只取得分段/映射信息，不是引用计数证明。

主会话已用原模块窄窗口反汇编核实以上字段与Free返回路径；尚未在guest发送op28，
也没有宣称它返回了某个计数。ET_REL反汇编中的未重定位BL立即数不能当最终运行目标。

## 允许下一代写入前必须具备的证据

如果生产者明确保留自己的一个owner，则至少需要：

1. 同一有效handle generation、unit431类型、原allocation PA/容量身份；
2. 原op28成功，reference恰为1且open恰为0；
3. 所有已发布作业、keeper、fan-out的生命周期账本闭合，不能再取得旧代引用；
4. 每个相关RC作业均自然完成并成功释放其input，而不是只看到callback入口。

这些条件未满足就保持一代字节不变并拒绝下一帧；超时只报告lease阻塞，不能授权覆盖。
当前 `run-9qby4xza` 虽有三次RC callback，未记录input Free和聚合计数；
`run-ks9_80je` 的配置也不证明完成。重复中性字节掩盖竞争，不能证明动态帧安全。

只读调查已结束（达到轮次上限，非穷尽）；没有证明存在直接发给生产者的聚合退休通知。
不修改DmmCfg、不强制Free、不清busy、不注入完成。当前YC保持原诊断配置，
后续应先加入有身份关联的只读计数/生命周期观察，再考虑动态源。

## 中性诊断源的最小安全修复

`build_metadata_and_frame` 对未压缩中性源现只在首次发布前写入一次0x80，
后续两次仍逐次计算并记录完整摘要，但不再重复store可能仍被消费者持有的像素。
这不改变任何像素内容、格式、三次提交或验证条件，也不是取得了退休许可。
旧compressed-luma实验不在该修复范围，不能由此提升为安全动态YC。

`test_yc_immutable_source.py` 编译实际builder，首次调用后以 `mprotect(PROT_READ)`
保护完整5184000B像素，第二、三次构建若尝试写入会触发故障；该测试及既有失败
资源测试共4项通过。AArch64 freestanding编译/链接通过，临时构建未安装进guest
资产，运行中实验继续按原构建receipt评估。原DMM/keeper/RC计数运行证据仍缺失。

## 默认关闭的op28观察实现

新增 `A7C2_YC_OWNERSHIP_OBSERVE=1`，只允许与未压缩YC诊断源一起使用。
launcher仅在显式请求时创建本次guest标记 `/simulation/yc-ownership-observe`；
该标记禁止预先藏在initramfs中。injector在发布前和有限drain结束后各查询一次，
tag分别为 `0x4c01/0x4c02`，等待有上限、不pump、不Share/Open/Free、不推进完成。
失败只保存否定证据，不能授权覆盖或改变原三次帧提交的结果。

补核原模块 `.text+0x5e90` 的opcode长度表确认：**op28回复为40B**；
`.text+0x8550–0x8558`设置回复source为 `0x0061003c`。回调只接受该source的
规范化同值、40B完整回复、当前tag、原type/capacity及合法计数；保留原40B hex。
回复没有回显handle/PA，所以身份来自单个在途tag与此前原op20/op2a记录的关联，
不能宣称reply本身重新读取了PA。

同时修复旧通用DMM回调无条件复制216B的问题：原回复长度随opcode/extent变化，
现在按真实长度有界复制并清零未接收部分，过短header拒绝，不再越过40B回复读内存。
这是边界安全修复，不是放宽短回复验证。

`yc_ownership_evidence.py` 要求唯一原unit431 allocation、两次顺序完整的request/reply、
原hex与打印字段相同，重复/迟到/缺失/失败均拒绝。即使 `refs=1/open=0`，报告仍输出
`retirement_verified=false` 和 `overwrite_authorized=false`。live SD导出附带观察结果，
但观察失败不冒充SD导出成功或照片完成；静态probe在安全收尾后严格拒绝未通过观察。

新build receipt绑定模块SHA与C/header/descriptor/build/check脚本SHA；开启观察但安装
旧模块或源码已变化会在启动前拒绝。构建前须取得本runtime的 `.menu-probe.lock`，
不能替换正在运行实验的资产。相关15项host测试及临时AArch64模块ABI检查通过，
后续含initramfs/收尾/被动采样/CMOS的扩展回归为24 passed、15 subtests passed，
Python编译、diff检查和旧成果脚本同步检查通过。安全安装正以非阻塞锁尝试；
尚没有取得guest的真实op28计数。
