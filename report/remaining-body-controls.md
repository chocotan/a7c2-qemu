# 机身控件补齐：C1、半按与全按分开

按用户最新优先级，暂不继续深挖3006和省电复位；已有证据保留，回到可独立推进的
机身输入与UI。此项没有关闭省电、循环取消APO、改原状态或生成拍摄完成通知。

## 本次改动

唯一GTK相机窗口沿用原布局，将快门处拆成上下两个独立按钮：半按／全按。
新增SHUTTER_HALF的输入目录项，并启用此前没有raw code的C1目录项：

| 控件 | 原始raw | 原canonical | 原名称证据 | 当前验收边界 |
|---|---|---|---|---|
| C1 | 66 | e | 58b14e0行的value=e，string=UIBIZ_KEY_TACT_CUSTOM | 当前自定义动作/LCD待验 |
| 半按 | 1f1 | 1d | 58b15d0行的value=1d，string=UIBIZ_KEY_TACT_LOCK | 点按触点，不保持；AF/AE待验 |
| 全按 | a7 | f | 原raw→canonical映射及既有CAP分派 | 单独点按全按；拍照/写文件未完成 |

原AP SHA256固定为
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。
1120项raw表3704b98与反向表3706e98独立核对；保留原initializer的first-duplicate
表中58b14e0/58b15d0是文件偏移，对应ELF VA 58c14e0/58c15d0。
名称行均按16B `{value,length,pointer}`读取，再按声明length读string，
不以字符串邻近关系或full方案代码注释替代原枚举身份。

已有App32/Infra20两通道各使用自己的原wire；新两项复用现有受控按下/释放命令，
没有新shell输入、持续按住状态或新的应用事件注入。C1、半按、全按仍verified=false，
界面可发送不等于真实自定义功能、AF或capture已通过。曝光补偿无明确绑定，仍不可发送，
没有凭相机外观把它等同于DOWN。其余三个拨轮/AF-ON/REC映射保留原证据和未验边界。

MODE注释同时与已有run-si4_cfdb限定验收同步：P/A/S/M/AUTO的原LCD已通过，
MR及真实曝光消费仍未验。不修改此前运行证明的结论。

## 验证

新增原件名称/value与两raw绑定核验，以及两通道下C1/半按/全按分别生成完整1/0
消息的检查，避免错发canonical或把半按转为全按。GTK fixture增加真实XTest点击
三按钮分别入队的测试；仍用FakeVM，不能算真实固件功能验收。

本轮回归包括test_app_key_remap、test_app_input、test_confirm_input、test-menu-control，
以及显式owned Xvfb/displayfd下的test_camera_ui。

实际结果：原件映射/控制接口/回归 **25 passed + 2 subtests**（9.73s）；
隔离 GTK 真实点击 **25 tests OK**（18.79s）。
首轮失败已定位为测试把名称表文件偏移当成ELF VA（相差0x10000），
改为ELF VA 58c14e0/58c15d0 后通过；原件行值0xe/CUSTOM、0x1d/LOCK未变。
未启动相机VM，也不在主桌面发键；C1/半按/全按仍不是AF或拍照通过。
后续短窗口原固件交互必须单独验收。

真实验收脚本预检发现新增C1/半按/全按没有固定点击坐标，原先b99613d07
尚在等待外部VM、未启动owned VM时已取消；不称其完成任何交互。
新driver直接从当前GTK实例导出已映射按钮的窗口相对中心，再由XTest点击；
缺geometry则明确失败，不回退到旧坐标。输入提交事件必须匹配本次控件名称。
测试实际driver的status/constructor closure和sustain拒绝分支，连同既有保留通道
回归共8 passed（0.05s）。这些仍是host工具验证，不证明原固件已接收。

随后ba75663c3在ready之前超时，未新建相机run：scratch等待启动器持有
`.menu-probe.lock`，而原run-menu-probe.sh又在fd9取同锁，形成自我等待。
这不是固件/按键失败。已改为等待和身份检查后释放外层锁，真正native入口
自己持有构建/VM锁。对实际launcher.main运行无VM fixture，child用真实flock
非阻塞获取同锁，1 passed（0.02s）；没有残留owned run-menu进程被观察到。
新b19af185c已启动，结果待收取；不从ready超时推广任何C1/快门功能结论。

## run-hcrppdg6：实际原接收与LCD限定验收

b19af185c已完成，实际CP冷态/HCI profile绑定正确；原driver仍保留overall ok=false，
另外保存body-controls-consumer-review.json（只限定输入消费/人工LCD核对）。
原App32 thread302连续收到各控件完整1/0：C1/raw66序号81/82，半按1f1为83/84，
全按a7为85/86，REC1f0为87/88。不是只靠send0或GTK队列提交判断。

主会话打开原640×480PNG并重算RGB摘要，与driver的不可变snapshot记录匹配：

- C1：原“智能自动”模式限制提示；不能当自定义参数成功改变。
- 半按：从前一C1提示返回原HUD；context受提示框影响，不当作独立AF/AE验收。
- 全按：HUD一部分消失，但没有capture/encoder完成证据，不算拍照。
- REC：原“无存储卡。无法拍摄动态影像。插槽2”对话框；不算录像。

SD镜像134217728B经main独立SHA256核对为
`d25afa4d4147866b980506e904c5d9bf52937f35b02cc2a62491d36258d6a11d`，
主机fsck.fat -n为0，原Flush rc0、owner resumed。main只读解析整棵FAT16目录树，
文件只有DATABASE.BIN（9670656B）和MEDIAPRO.XML（406B），及其PRIVATE/M4ROOT
目录，无照片或视频文件。存储通过不改变REC槽2提示或成像未实现结论。
console SHA256 `3dd8cbb31bc459b52d9ab5532d9438bca4e37acde2c2bd0e27cd6f04c7d487eb`。

## 下一轮MR/拨轮工具已集成

原代理scratch候选的无fuzz应用/逻辑5项及真实GTK/XTest四位置检查先行通过。
待上一VM结束后main才修改production driver，加入--mode-wheel-probe：实际popover
坐标、MR1/MR2/MR3/P、三个轮左右配对、45秒budget、精确提交名匹配，之后仍走SD
export/安全cleanup。先返回拍摄上下文再执行；原固件是否实际进入对应模式须逐图复核，
请求P不代表P已生效。集成后真实driver closures共12 passed（0.08s），非原固件验收。

## run-gd179z41：MR2/3标识与后拨轮曝光补偿限定通过

bbe945e71结束后main核对原App32 thread302：序号81..84依次收到MODE statuses
7/19/20/3（MR1/MR2/MR3/P）；85..90收到前/后/控制轮各一次fffffc00/400。
全部10项在10.82s探测段内提交，原输入字节和顺序核验通过，未进入60秒sustain。
main逐图核对contact sheet及11张原PNG的RGB摘要，与driver不可变snapshot相符。

- MR2、MR3的原HUD分别有MR2/P、MR3/P标识，返回P后原P标识可见。
  仅证明选位和该场景显示，不能推所有已存参数都正确回载。
- MR1即时帧与之前智能自动HUD相同；未额外等待settle，保留未验证，不能称失败或通过。
- 在已显示P的场景，后拨轮左一次将原曝光补偿显示从±0.0改为−0.3；右一次返回±0.0。
  这是特定P上下文的真实业务显示响应，不是通用曝光补偿键绑定、传感器曝光改变或编码完成。
- 前拨轮左右、控制轮左右均被原线程消费；部分HUD有变化，但无明确参数数值证据，
  不判其拍摄参数功能完成。无镜头时空白快门/光圈区也不用于推断拨轮用途。

原driver ok=false保持；run新增mode-wheel-consumer-review.json限定ok=true。
console SHA256 `f257a9623eaa44cb3b0512ab9ab9e31e5936a58600eb6426b53262070ee9d5db`。
128MiB卡经main独立摘要核验
`660db00f6d6da8b40a8f35f9617870f768642f49d26be8e1ca1e39f50bb871d6`，
主机fsck0、原Flush0、owner resumed；不因此宣称拍照/录像通过。

## run-3s6hb0e1：MR1等待后的原HUD及独立半按/AF-ON

b2af2127a已经结束。MODE7（MR1）原接收序号81，普通等待4秒后原LCD明确
显示MR1/P标识；MODE3返回P的序号82，原P标识再次可见。这补上上一轮即时
截图未settle的显示缺口；没有重写旧图或把参数完整回载算通过。

回到P且没有C1提示框后，原App32 thread302依次收到半按1f1的1/0（83/84）
以及AF-ON f000004的1/0（85/86）。main打开MR1、半按及AF-ON原PNG，并重算
全部5张focus-controls截图的RGB摘要，与driver不可变snapshot一致。后两项仅见
HUD元素变化，没有独立合焦、镜头动作、AE结果或AF完成事件证据，故只通过输入
消费，不提升AF/AE。不会以无镜头取景黑色区域或当前HUD变化当对焦成功。

run保存focus-controls-consumer-review.json：限定ok=true、autofocus_verified=false、
camera_capture_verified=false；原gtk-input-proof.json总体false保持。
console SHA256 `915f143c47fd758e43f2e0790bba0c2a9396a736d5060ccecbcb370d59a8f387`。
main独立重算128MiB卡SHA256
`c52f4d46fdfc92cbc3de10ca2c69e404a6e719bdd813ea0cf27abcd5593b9f22`，
与export一致；主机fsck0、原Flush0、owner resumed。该存储结论独立于MR/AF功能。

至此MODE八档（五基础档及MR1/2/3）的原输入和HUD标识各有限定场景证据。
未验项仍包括完整MR参数回载、任意反向/跨照片录像组合、前轮/控制轮参数作用、
AF/AE与拍照录像。三个独立子代理继续处理槽2映射、轮上下文及只读证据工具，
不追加full/省电/3006深挖。

## 相关但暂停的full尝试

切换优先前启动的一次full官方派生run-6mvt0p0_已自然结束：runner exit1，
尾段明确FULLSYSTEM_STAGE_FAILED，且camera_startup_verified/
viewfinder_verified/capture_verified均为false。按键0x1f1/0xa7/0x71c9/0x1f0
都曾实际发送到原输入队列，但这不是拍摄结果；未据此继续full调查或重试，
按用户要求不再占用主线。
