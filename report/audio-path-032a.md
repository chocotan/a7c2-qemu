# 032a：SystemSound 路由配置

当前Common在`run-ypsslyoq`已越过初始四worker完成join，随后实际发送
`0d202a030a0001800700`到92840747，等待032a回复。主界面未恢复。
本模型范围是独立虚拟路由缓存与空闲控制状态，不执行真实音频MMIO，不证明播放。

## Evidence → Finding → Path

CP地址以下均标为CPVA，raw=CPVA−108000；appFw明确使用ELF VA。

| 证据 | 结论 | 实现路径 |
|---|---|---|
| appFw ELF34ebcec构造200d/032a/10/8001，末两字节mask/unused | 实际mask7，不是音量7，也没有kind参数 | 保留原10B域；不用032c的per-kind语义 |
| CPVA1ca6b2..ba取u8+8并AND7，relay到ADF9058003f的2004/0202/12/1 | 原wire高位被屏蔽 | 模型先wire&7，测试fd→5和f8→0 |
| CPVA19bb74的AdfSystemSoundPath::Execute→67dd78；CPVA10e1bd4初始0 | 全局独立u32路由缓存 | state.system_path，独立于音量/表项 |
| CPVA67dd92..b4在0→非零时发AudioIpIf control127/argument0 | 需实际消费控制，不是只回成功 | 独立virtual path register写读，记录control计数 |
| CPVAb6c1dc对f48a3c0c bit0做RMW；上层argument0令bit1、argument1令bit0 | 非零→0空闲时执行相反操作，其他位不变 | 虚拟register仅改bit0；播放不支持，所以request_active0 |
| CPVA67ddc8..dc的active分支注册67ddfb deferred callback | 活跃播放停路由是额外异步路径 | 当前模型不支持播放，不声称已实现此callback |
| relay OR580000，原AP复制/free12B | 回复132a/12/8001，状态00580000 | 原消息所有权/lease及同waiter释放检查 |

主会话已独立复核CPVA1ca6b2/67dd78/b6c1dc原Thumb指令。
RTTI `18AdfSystemSoundPath`、缓存及状态投影来自Kuna反编译后关键指令交叉核查，
不把Kuna合成地址直接当原始VA。

## 状态与边界

零→非零：保存mask，消费control127/argument0，virtual bit0置1。
非零→非零：更新缓存，不重复消费127。
非零→零（idle）：消费control127/argument1，virtual bit0清0。
零→零：保留零，无新控制。模型初始virtual register0是本虚拟owner配置，不是原MMIO读回。
所有操作在既有audio mutex下执行，send失败回滚状态并释放临时回复。

新增逻辑使用既有默认关闭MENU_AUDIO_BOOT_CONFIG，不增加无关开关。
host测试包含掩码、unused byte、双向切换、不重复控制、发送失败回滚、坏封套及所有旧音频测试；
ASan/UBSan通过。真实固件消费仍需动态reply/free/状态记录与后续栈验收。
`verify-native-audio-path.py`要求同run完整sound backing先通过，并核实当前cold7路径的每个字段。

## 动态结果

`run-7t6lu6an`原Common328实际发cold7请求，回复pointer=`0x7fb1454a80`、lease54，
原waiter释放rc0。COMMIT明确记录previous_path0、cached/readback7、control127/argument0、
control_consumed1、virtual register0→1并读回1、request_active0/deferred_callback0。
console SHA256=`ce93b21560c1ad8b5a5022427f616a9d54c3d18f8fcc16af316193faeaf256bb`。
完整cold7逐字段及cache/control/free篡改2测试均通过。
证据见`audio-path-native-proof.json`，scope固定为cold-idle-route-control，
硬件MMIO/active callback/音频播放/相机启动均明确false。

Common下一栈变为`34e5788←34efa0c←34c8b84←305e554←305e9e8`。
主会话独立反汇编发现ELF34ef9b0构造24B请求到另一个SID912f0335，selector由u8选择3/4。
下一实际raw请求尚待被动采集，当前没有为该端点添加回复；其原owner/状态consumer正通过Kuna调查。
UI仍等boot future，StillCa初始snapshot尚未到达。
