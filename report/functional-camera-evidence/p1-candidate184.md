# c184：全按未执行，释放请求正常调度

范围：仅在本地读取已有 A7C2 QEMU 运行证据和原 AP ELF。未修改固件或隐私状态，未另启 QEMU。

## 结果

c182 与 c184 都收到了完整的快门输入。两轮的唯一拍摄执行入口命中都来自全按释放，而非按下。c184 的 `0x7e` 对象确实创建并进入调度；该对象是释放路径创建的，不代表拍摄成功。仍未观测到自然 `0x4038`、JPEG、原写卡或整卡读回，`capture_verified=false`。c184 记录 QMP 退出确认、进程 `rc0`、无信号。

## 证据

路径以项目根为基准；不复制原始日志。静态地址均为 ELF VA。

- **E1**：`final/a7c2-qemu/runtime/analysis/menu-runs/9a26/console.log`。用 `rg -n '^OBS (SHUTTER_FLOW site=final|SHUTTER_API site=execute|SEQUENCE_QUEUE .*request_id=0x7e|MODE_SCHEDULE .*sequence_id=0x7e)'` 查看全按采样（16068）、释放执行（16080）、入队（16081）、调度（16082）。行 16084 记录原 AP 发出的 `0x4039` wire。
- **E2**：`final/a7c2-qemu/runtime/analysis/menu-root/usr/lib/appFw.so`，SHA-256 `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。用 `llvm-objdump -d --start-address=0x1af16dc --stop-address=0x1af1848` 后接上述 ELF 路径复核全按分支。同法复核 `0x24ccac4..0x24ccae0`、`0x248f1b0..0x248f1dc` 和 `0x336a024..0x336a084`。
- **E3**：`final/a7c2-qemu/runtime/analysis/menu-runs/9a26/model17c-watch-result.json` 中 16 个站点已撤除，`model17c-yield.json` 记录交接原因 `upm-mailbox-announcement`；接手处理邮箱的 `hdmi-upm-watch-result.json` 未安装这些站点。
- **E4**：`scratch/a7c2-capture-p1-runtime-20261115-candidate182/runtime-1/run-1-evidence/console.log` 行 15026、15038 对照全按采样和释放执行。`scratch/a7c2-capture-p1-runtime-20261115-candidate184/runtime-1/attempt-1.json` 记录 c184 业务与退出状态。

## 判断

**F1：隐私模型状态与全按提前返回吻合（E1、E2、E4）。** 全按 `0x02070000` 到达 `0x1af16dc`，入口日志显示 `a1=0`、局部值 `0`、模式 `2`、模式选项 `0`、`0x7e67fc8=0`、`0x83337e3=0`、`0x7e5d570=1`，读回长度完整。根据该入口采样，`0x1af1834` 的 `cbnz` 会跳去清理返回，跳过 `0x2688f44` 的按下调用。采样非原子，未直接记录该分支命中；静态路径与两轮只见释放执行吻合。这只适用于这条全按分支，不等于所有模式都受该字段控制。

**F2：`0x7e` 不是缺工厂（E1、E2、E3）。** 释放 `0x020f0007` 后执行函数参数 `a0=0`，原请求入队为 `0x7e`，请求 `+0x10` 字节为 `0`。`0x24ccad8` 通过 `0x5578920[id]` 调用工厂；`[0x7e]` 指向 `0x248f1b0`，后者尾调用 `0x336a024`。该函数先调用构造器 `0x3369aec`，再尾调用 `0x3222ad0`，因而调度保留 `0x24ccadc` 的返回地址。`MODE_FACTORY` 表探针 `0x248ff44` 只覆盖 `0x2f` 的入口；`0x570830` 附近是重定位记录，不是实际分派表。构造探针在快门前已撤掉，零命中不等于未创建。

**F3：释放参数符合提前结束路径（E1、E2）。** `0x2688a08` 保存输入边沿值，`0x2688b38` 分支将其作为显式参数（选择字节 `1`）传给 `0x24d2d84` / `0x2493dd4`。构造器在选择字节非零时把请求 `+0x10` 字节复制到对象 `+0x20`，不读全局 `0x7e5d6b8`。`run()` 在 `0x34bfcbc` 对该对象字节为零的路径调用结束包装函数。c184 观察到 `0x4039`，未直接记录 `run()` 的分支命中或完整栈。

链路：全按 → 条件提前返回；全按释放 → `0x2688a08(0, …)` → 请求 `0x7e` → 构造/调度 → 观测原 AP 发 `0x4039`。不能以释放侧的调度或结束消息作为拍摄通过证据。

**静态复核（同一条屏幕控制器路径，不外推到其他输入方式）。** `0x1af1724…0x1af1750` 是局部对象清理和返回，不调用拍摄执行。`0x1b54444` 在不同事件分支设置不同 trigger；c184 的原始全按样本实际传 `0`。`0x2688a08` 是 `model::execute_cap_seq_i(bool, model::s2_trigger_t)`：同一次调用存入边沿并打包请求，并非释放从旧按下继承边沿。`0x2688eac` 在 `state_d498=0、mode=2` 时另读 EE，`0x24d2dbc…0x24d2dc8` 再检查队列使能字节 `0x7e4e608`。c184 的 `runtime-1/fast-gates-pre-shutter.json` 早已读到 `ee_status=1`、`system_mode=2`、`capture_inhibit=0`；释放日志 16078–16081 也读到 `EE=1` 并经 `0x24d2e14` 入队，证明该次释放的队列使能通过，不等于捕获了全按时的两道内部判断。原始样本优先于“EE 未测”的静态报告表述。

参考：`scratch/a7c2-postsetup-shutter-20261119/REPORT.md`。采用其控制流与符号复核，不采用“调整宿主 `finish` 顺序”或“等待 `V==0`”作为拍摄前置。`V` 非零的判断只在本控制器的零 trigger 路径适用；真机正常拍摄时用的状态或分支尚未取证。

**L24 复现（run `d9d0`，仅取拍摄窗口）：** `runtime/analysis/menu-runs/d9d0/console.log` 16542 行记录全按，16549 行记录原厂控制器入口 `trigger=0`、`V=1`、`original_branch_observed=0`；16554 行是释放，16562–16567 行只见 `bool=0` 执行、`0x7e` 入队与 `0x4039`。这些都早于 26453 行的独立 POWER 输入。复现支持同一阻塞位置，但没有新增实际分支证据。

**省电关闭后的同轮对照（`1273`）：** 通过原厂菜单关闭 `Power Save Start Time`、重开读回、回到拍摄页后再全按；无原厂 APO1 或关机记录。`scratch/a7c2-apo-menu-round18/runtime-1/` 保留 `apo-menu-readback.json`、`shutter-consumed.json` 和 `fast-gates-pre-shutter.json`：四个快门边沿均由 PID 324/TID 419 消费；快门前 `mode=2`、`capture_inhibit=0`、`V=1`。`runtime/analysis/menu-runs/1273/console.log` 51253 行采样全按时 `trigger=0`、`V=1`，仍标 `original_branch_observed=0`；51272、51277 行仅见释放执行 `a0=0` 和 `0x4039`，没有 `0x4038`、JPEG 或写卡。因此省电未造成这次全按不执行，但该轮仍未新增原分支取证，不能仅凭入口采样扩大归因。QMP 正常退出，`capture_verified=false`。

**另一条原厂直接分派路径（原 ELF 静态复核，当前未见执行）：** `0x1b54518` 调用 `0x188f990`，它读取调用入口 `a1` 指向的首个 32 位分类值，按无符号值接受 `0..2` 或 `6`。通过随后守卫的路径在 `0x1b54620` 调 `0x26acf98`，其内部经 `0x26acf14` 的条件分支，在 `0x26acf74` 直接调用 `0x2688eac(..., 1, trigger)`，不经过 `0x1af16dc` 的零 trigger 检查。`1273` 的现存日志只有分类指针，没有分类值，也没有这条按下执行路径的正证据，不能给未知分类取功能名或直接改值。

现有 `SHUTTER_FLOW site=core` 全按探针新增 `direct_inputs_v=1`，只读取该分类和五个原守卫输入。`direct_reads` 保留每笔字节数，日志仍标 `atomic_snapshot=0 original_branch_observed=0`；失败读取不可当作零。宿主两组 8+6 项通过，并交叉编译了 AArch64 对象。记录位于 `scratch/a7c2-shutter-dispatch-cross-v1/storage.json`。当前 `b369` 没有 TCG 插件 API，旧分支插件亦绑定另一构建。随后已独立完成封存链接和单成员 initramfs 读回（构建/归档两组 67 项通过），见 `scratch/a7c2-shutter-dispatch-overlay-v1/storage.json`。新版采样尚未在实际 guest 装载；原有 initramfs、运行观察器和保留实例未改动。

**历史原指令跟踪与写者复核（`iztn71wy`）：** 完整保全位于 `final/a7c2-re/report/2026-10-17-qemu-native-camera/runtime/analysis/scratch/functional-shutter-gate-v2-hdmi-admission-plan-next/postexit-run-iztn71wy/`。`original-evidence/readonly-scope-trace.log`（SHA-256 `a3a4165d5ce4e4126bf3b42e145a1096b677ca50e54f2cc5cebd8e93aa319df8`）第 2–4 行连续采到 `0x1af1830` 从 `base+0x7e5d570` 加载、`0x1af1834` 分支前 `W0=1`、`0x1af1724` 提前返回入口；三条的 vCPU、TTBR0、TPIDR、SP、X29、X23 相同。与同一运行控制台 1754、21184、21191、21194、21201 行交叉核对：AP 的 AppFw base 命中同一数值，且全按入口 `a0` 等于分支现场 `X23`（原 `0x1af16fc` 的 `mov x23,x0`），释放才出现 `execute(bool=0)`。这是该分支真的提前返回的运行侧证据，不再只是入口状态预测；原 `shutter-gate-reader.json` 的线程身份、调用配对及 `branch_edge_verified=false` 不升级，也不代替 c184/L24 自身的分支收据。

**`1` 的来源不是写卡故障，也不能归给某个首设按键。** 原 ELF `.rodata` 在 `0x4b45948` 有 `{0x17c,1}`；`0x28bc058…0x28bc068` 按 8B 项取模型 ID 和默认值地址，调用原发布入口 `0x2ae00a8`。历史 `iztn71wy` 控制台 1833 行从返回地址 `0x28bc068` 观察到 `0x17c` 发布 `1`，发布前当前值为 `0`；c170 的 `model17c-watch-events.jsonl` 另有原 store `0x276797c` 前后两笔，`W0=1`。原厂 `process_power_on` 在 `0x209ee50…0x209ee9c` 只在 `0x447==1`、`0x17c==1` 且更早守卫通过时才提交 `0x267b7a8(…,0)`；L24 入口日志 4844 行实读 `0x447=0`、`0x17c=1`，未记录后续实际分支。这支持沿原厂状态发布与正常录制 UI 的转换查缺口；不证明必须重启，也不证明应篡改隐私设置。

## 备注：boot 期 SHUTTER_API 扫描不是快门

c186 L6（run c711）在首设期间出现过 12 条 `SHUTTER_API site=call/wrapper`，调用者 `0x1b24050`（非快门路径的 `0x1b23d48`），参数 `a2=0..5` 递增。这是启动期状态扫描，与快门全按无关；判读时以 `site=execute`（`0x2688a08`）和 `SHUTTER_FLOW site=final`（`0x1af16dc`）为准。

## 首设收尾的原厂路径

c184 的 `ui-40.ocr.txt` 对应 `0x1e6` 触控说明，最后一键后 `ui-41` 和快门前 `ui-42` 都读到 `FINE 33M`、`MECH`。控制台记录 `rep_boot` 转入 `rep_shooting`，`0x29b` 创建后又回到拍摄画面（`CREATE_SCREEN_ARGS` call 37–39）。没有发现仍打开的首设页；这不能证明设置已持久提交。`first-setup-complete-43.json` 是宿主动作标记，不是固件确认。

**复核：宿主动作顺序不能证明快门按早了。** `scratch/a7c2-capture-p1-runtime-20261115-candidate184/runtime-1/verify_runtime.py:250` 的 `finish` 只退出宿主循环；`setup_complete` 只写两份标记，并不向 guest 发消息。c184 在全按前已出现 `rep_boot -> rep_shooting`（9520）、`ENTER_REC_STILL`（9527）和三笔 Imaging 提交（9705、9729、9764）；原静态拍摄序列在进入录制时也读到 `system_mode=0x2`（10766–10767）。因此 `mode=2` 不能证明仍在首设中，挪动标记也不能改变 guest 状态。是否仍有未了结的实际 UI 或拍摄前置，保持未证实。

[索尼 ILCE-7CM2 首设说明](https://helpguide.sony.net/ilc/2360/v1/en/contents/211h_initial_settings.html)和[静态影像拍摄说明](https://helpguide.sony.net/ilc/2360/v1/en/contents/0301B_shooting_still_images.html)均未把关机或再次启动列作拍摄前置；后者明确说明全按后写卡。下列 POWER 事务是独立诊断，不是绕过或修补快门链的依据。

- `0x262a138` 在事务参数 `w2` 低字节非零时更新模型 `0x447`：调用 `0x28649e4/0x28649f8` 取得当前值和镜像访问器，向 `0x262a0b4` 提交 `1`，再调用提交函数 `0x25610ac`。`0x262a110` 是当前值的写指令。`dlg_rec232_controller(OFF_BY_KEY)`（`0x1aa081c`）与 `scr7191_0001_controller(OFF_BY_KEY)`（`0x22e495c`）均调用 `0x262a238(..., 1)` 到达此处。当前值位于 `0x7e6a7c8`；不预设该模型的正式名称。
- 开机 `process_power_on` 里的 `0x209ee50…0x209ee9c` 读取同一个 `0x447`，必须等于 `1` 且隐私当前值等于 `1` 才提交原厂状态事务；之前还要求日期/强制时钟判定通过以及 `0x209d6d4` 返回零。c184 的启动快照中 `0x447=0`、隐私当前值 `0` / 镜像 `1`；c184 按既定拍摄范围未做原厂 POWER 关闭，没有这一关闭事务的动态证据。
- c184 的旧就绪 JSON 也不能作为反证：其原始查询只抓 guest 日志最后 256 KiB，结果为空；同轮宿主控制台 9527、9705、9729、9764 行包含原录制入口和三笔 Imaging 提交，均早于快门。原收据保留；后续应从同次运行全控制台的真实 `OBS` 行取证，不把 OCR 或宿主动作标记作为固件首设完成依据。

**第 9 轮字段定名：`0x447` 不是首设完成标志。** 原 ELF 登记项 `0x5ef9110` 的 ID 为 `0x447`，其 `+0x20` 指针经 `R_AARCH64_RELATIVE` 指向 `0x58645c0` 的四值表：`0=POWER_OFF_ORIKS_OFF`、`1=POWER_OFF_ORIKS_BEFORE_POWER_OFF_SEQ`、`2=POWER_OFF_ORIKS_AT_POWER_OFF_SEQ`、`3=POWER_OFF_ORIKS_AT_MODEL_SUSPEND`。原代码独立印证：`0x262a1c8` 提交 1，`0x33dbaf0` 所在原关机序列提交 2，`model_suspend()` 的 `0x27595ac`、`0x2759794` 分别提交 3、0。`0x447` 是开关机生命周期内部状态，没有证据表明应手动改它或将其提升为拍摄前置。`0x17c` 则是 `is_accepted_privacy_notice`（0 未接受、1 首设期间接受、2 已接受）；原值表 `0x587c990` 和三条枚举字符串已逐值核对。只有后者被 `0x1af1834` 的零 trigger 分支直接检查。两者都不是 SD 卡、JPEG 或对焦选项。

对原 ELF `.text` 的 BL/B 与 `R_AARCH64_RELATIVE` 扫描，`0x262a238` 取得 8 个直连点，无相应 RELATIVE 槽。`dlg_rec232`、`scr7191_0001` 的 `OFF_BY_KEY/OFF_BY_PANEL` 各提交一次非零标志；两者各有一笔 `w2=0` 的通知调用。`scr0039_shutdown` 亦有一笔 `w2=0` 通知以及一笔键/面板共用的 `w2=1` 提交。`0x262a138` 的直接上游仅上述包装器；普通确认键不应凭动作名称归入这些 `OFF_BY_*` 分支。扫描范围不覆盖所有间接写者。另查到 `0x267ed74` 从属性描述符 `+0x10` 取值后进入 `0x17c` 底层事务，不是字面写零；其是否参与当前拍摄路径未取证。

历史 `f0zcce1d` 同一 AP 进程的原控制台在 18895–18900 行读 `0`，20907 行全按入口读 `1`，随后 21003 行已切换到电影模式（`mode` 请求 3），27828–27833 行后置读取为 `0`。不能将后置 `0` 归因于单独的松开快门或档位切换。c184 与 L24 的按前、按后独立读回均为 `1`。旧 `5090zp6q` 的电影→照片切换虽已改变原厂 mode，画面仍停在 Movie 并在全按前被场景守卫拒绝；旧代的 `0x403f` 放大复位返回 `0xf001`，当前 c184/L24 已观测到真实 `0xf000` 回复、接收及释放，但尚未重新验证切档后拍摄。

## 关机停滞观察（c186 L21/L22，独立诊断）

- L21（run 6b0b）：镜像 `REG_ASYNC/REG_SYNC/DYNAMIC_ID` 后，在该观察器实际输出的注册记录中未见 `0x9003` 族。可确认该运行中的虚拟 `0x1010` 向 `0x90030001` 投递返回 `-1020`；有限日志不能证明真机的消息路由或消费者不存在。
- 动态注册 `0x809161xx`（appFw+0x35a5878，回调 `0x35a52a0` 比较 `osal_get_msg_src==0x91000040`）在关机前已多次出现，最后两条关机期记录后仍有原厂命令推进，不能当作停滞位置。
- L22（run cf42）：只读线程快照看到执行过 sweep 的线程 474 `SeqQueueDispSwi` 位于 `futex_wait_queue_me`。这不能确定具体等哪个条件，也不能把它与 `0x1010` 投递失败建立因果关系。对九个 `0x8092xxxx` 回调的静态复核未发现匹配的 `0x1010` 解析器；撤回“落在批量队列”和“因果闭合”的说法。详见 `scratch/a7c2-ap-1010-landing-20261119/REPORT.md`。
- L23（run 50a1）：请求者 SID 的替代路由只观测到开机期入队，尚无 AP 消费证据，也未实际发送 POWER 键。不能用它推断关机或拍摄结果。
- L24（run `d9d0`）：独立关机诊断未取得正常关机收据，二启未执行。恢复收据记录备用 QMP 端点退出请求、未向 VM 发信号，之后检查原 QEMU PID 已不存在；未补写原 QEMU 退出码或正常关机收据。运行日志及失败盘保留；不再重跑这条关机路线来验证拍摄。

## 关机链前沿（c186 L19，v3 修复后）

隔离实跑（POWER→同盘二启诊断）在 L13 定位关机 VDF panel-off 断言后，经 reject_raw 字节证据三轮修正常量，L19（run 39ec）实现：POWER 键消费 → 0x403d interlock 加锁 → VDF `FULL_VDF_PANEL_OUT_OFF`（实测载荷 `{3,11×0,2,0}`）两笔全部通过、bb_ipsx:978 断言消失 → 触控面板关闭（enable=0 applied=2）→ CP 0x4070 worker（gen4）→ **0x1010 完成投递 rc=-1020（0x90030001 无消费者）** → 0x403d 解锁 → 关机停滞：标志 0x8838af8 保持 00，无 POWER_DISPATCH/SHUTDOWN_* 事件，GUI 事件继续。

下一缺口：关机期 AP 对 0x1010 的接收语义（启动期 AP 不等待，关机期是否等待需证据）；与 c176 期“0x1010 无消费者”观察同源。

`0x206114c` 是回放启动写入 `1` 的路径，不是全按恢复。已经核实正常 POWER 到 `0x447` 和开机重新评估的静态链路，尚未证明在本机 QEMU 启动条件下这些事务可被持久消费。若单独验证这条前置链，使用新隔离实例、现有原厂 POWER 流程和同一内部盘重启，不重新播种内部盘；分别记录正常关闭、`0x447`、原状态事务及全按执行。关机不是写卡通过条件，不直接改状态、不补发 `0x4038`；拍摄验收仍要求真正全按、自然 `0x4038`、JPEG 和整卡读回。

## 下一步

**拍摄主线（不做 POWER 或二启）：** 在同一次已进入拍摄态的启动中用原按键区分按下与释放。下一实验证据优先取 `0x1af1834` 的实际分支和 `0x2688a08` 的边沿参数。`0x1af17fc` 的非零 `w22` 路径不读该隐私值；零值路径的 `0x1af1834` 对任何非零值均同样提前返回。`0x2688f44` 把按下位 `1` 经 `0x2688eac` 传给 `0x2688a08`；执行入口保存的是本次调用的边沿，释放侧不会从先前按下继承这个参数。仅凭这些静态指令不能判定正常 UI 该走哪一路，也不证明首设时机、隐私状态或关机是根因。验收不变：真正全按、自然 `0x4038`、JPEG、原 MPR/Fsys 写卡和整卡读回。

## 第21轮（run 9d21）：direct_inputs 首采 + APO 全程缺席

菜单链 42–91 与第18轮参考全链对齐（52 滞后一帧、57 超前一帧，工具内建偏移纠偏，零盲放）；`Power Save Start Time=Off` 确认（live 83 ENTER→84=265f10a5 全等）并重开读回（ui-87=fe23c12b、ui-91=82c07d10 均与参考逐字节一致）；`apo-menu-readback.json` 按实测帧 SHA 写出后 action-92 capture 发出。

**快门结果（仍是 only-release，但首次拿到全部直采值）**：四边仍由原 App32 消费（`shutter-consumed.json original_app32_consumed=true`）。`SHUTTER_FLOW site=core`：`state_d428=2`（mode 2）、`inhibit_83337e3=0`、`transition_67fc8=0`、`press_local=0`、**`direct_inputs_v=1 direct_class=0`**、`direct_6efb0=0 direct_d9ac0=0 direct_6f070=0 direct_82310=0`、**`direct_33ba5=0x1`**、`direct_reads=4/4/4/4/4/1`。`site=final`：`press_local=0`（执行层仍只收到 bool=0 取消类调用）、**`duplicate_d570=0x1`（V=1，门控层 epilogue 分支条件成立——iztn71wy 历史结论首次在同轮采到）**、`original_branch_observed=0`。业务计数：`0x4039`×4、`0x4038`=0、JPEG=0、write-retired=0、POWER_NOTICE/SHUTDOWN_ENTER=0（**APO 整轮缺席，省电 Off 生效**）。

收尾：`qmp_quit_confirmed=true`、QEMU rc0、零信号、runner closed；driver rc2 仅为 capture 后未派发 action-93 finish 的良性动作期限超时（下一轮快门后应补发 finish）。`capture_verified=false` 如实保留。下一前沿：反编译 `direct_class` 生产者（a1 结构首 32 位，接受集 {0,1,2,6}）与 `0x7e5d570` 的写者，判定全按为何被分类为 0。

## 第22轮（run ce56）：候选输入未证明起拍

定时省电由 1 分钟改为 Off，并在原菜单重开读回（frame 91）；屏幕开合联动未改，frame 100 已回原拍摄页。完成首设的日语是本轮旧动作序列的选择，并非固件语言限制。后续复用已验证的原厂简体中文选择器。

在 App32 输入单独试验 `0x1f3`，客体原始 `KEY_RECV` 记录同 PID/TID 消费 `0x1f1↑/0x1f3↑/0x1f3↓/0x1f1↓`。内部键表的 `0x1f3 → 0x02130000` 只是静态映射；旧只读探针未覆盖这些候选码，所以不能从缺日志判定翻译是否发生。未观测自然 `0x4038`、属于本次拍摄的 JPEG 或实际写卡。撤回 `0x1f3` 产品默认变更，观察器只补候选码过滤；不改固件状态、快门类型或路径。

旧收据解析器固定期望 `0xa7`，不能归类该原始回执。driver 最终记录串口完成标记超时，未进入 P4 checker；QMP 确认退出、QEMU rc0、零信号、租约保留至退出。没有验收拍摄写卡。

## 第23轮（run 6eaa）：直接快门实跑与原厂键码重映射

首设后不再进电源菜单，原 still 就绪后 3.817 秒内取得同一 App32 线程的四条输入（序号 85–88），共 347.599 秒完成。`passed-p1-transport` 仅证明链路和退出：QMP quit 已确认、QEMU rc0、零信号、租约保留至退出。无 `0x4038`、归属于此轮的照片 JPEG 或整卡导出，P4 跳过。新版探针已安装，记录了旧半按的 `0x1d → 0x02060000/01`，没有观察到候选全按预期的 `0x02130000/01`；此轮未修改省电设置，未见 APO1 或原厂 shutdown 介入。

重新读回官方 AppFw 的原始键转换表（VA `0x3704b98`，1120 项，首个重复项有效）、逻辑键名表和动作表。`0x17951c0` 在 App32 消费后先重映射第一字，因此按键表里的逻辑 ID 不能当作原始输入码：

| 原始 App32 键码 | 逻辑键码 | 原名 | 已核用途 |
| --- | --- | --- | --- |
| `0x1f3` | `0x1f` | `TACT_WIDE` | 广角键，动作表 `0x020f00f7` |
| `0x1f1` | `0x1d` | `TACT_LOCK` | 锁定键，非机身半按 |
| `0x1f4` | `0x20` | `TACT_FOCUS` | 机身半按候选；无通用动作表行，仍须实测特殊分支 |
| `0xa7` | `0x0f` | `TACT_CAP` | 机身全按，动作表 `0x02070000` |
| `0x030f1d2d` | `0x1f3` | `SIRCS_DSC_SHUTTER_ON` | 红外遥控快门，动作表 `0x02130000`；不是机身全按 |
| `0x03ff1d2d` | `0x208` | `SIRCS_DSC_SHUTTER_ON_UM` | 另一条红外遥控路径，`0x020f0067` |
| `0x1c000005` | `0x352` | `BLUETOOTH_LOWENERGY_SHUTTER` | 蓝牙遥控路径，`0x020f004d` |

这解释了两轮直接注入 `0x1f3` 为什么不能证明 `trigger=5`。下一轮只在独立虚拟实例测试 `0x1f4` 半按候选与原 `0xa7` 全按，不修改产品默认键映射。硬件帘、焦点状态及直接全按分支未获运行结论。

## 第24轮（run e9b0）：机身按键已达分派，拍摄前置未就绪

原厂 App32 线程 419 消费 `0x1f4↑/0xa7↑/0xa7↓/0x1f4↓`，见 `scratch/a7c2-apo-menu-round24/runtime-1/shutter-consumed.json`。同轮控制台 10543–10548 行记录全按的 `0x0f → 0x02070000` 和分派入口。进入照片模式且三条 Imaging 连接已提交，不等于可以拍摄：10548 行实际采到 `capture_inhibit=1`，10559–10560 行释放路径实际采到 `EE=0`，未命中实际执行入口。采样不证明门控的全部内部先后，不能据此断言此前 `EE=1` 的全按故障已解决，也不能证明半按功能已正常。

整轮 347.285 秒，QMP 已确认退出，QEMU rc0、零信号且租约持有至退出；无自然拍摄请求、JPEG 或卡导出。第25轮只增加一次最多30秒的原厂状态窗口：照片模式稳定、`EE=1` 且 `capture_inhibit=0` 才发同样的快门输入，否则保留读回与原始记录并结束。不写 guest 状态，不修改产品默认。

## 第25轮（run dd00）：禁止位清零后仍只执行释放

`shutter-readiness-samples.json` 有 17 次只读采样，首笔 `EE=0/inhibit=1`，约 10.52 秒后末笔变为 `EE=1/inhibit=0`；无强制写入。随后原厂消费机身快门四边。控制台 12405 行同一次全按进入 `0x1af16dc`，入口参数 `a1=0`，读到通用禁止位 `0x83337e3=0`，隐私模型 `0x17c`（VA `0x7e5d570`）为 `1`。两者是独立字段。第 12446 行仅见释放执行 `a0=0`，EE 仍是 1；第 12892 行只有结束命令 `0x4039`，未见自然 `0x4038` 或照片写卡。

原指令 `0x1af1834` 对任意非零值提前返回，因而不能把 `1` 或 `2` 当作通用拍摄禁止位，不能把清零当作确认隐私，也不能断言把枚举从 `1` 改为 `2` 就解锁拍摄。最新入口快照非原子，实际分支证据仍与同一历史 GDB/TCG 样本分账。后续定位原厂首设确认后真实的状态事务与机身拍摄分派，不改隐私值、指令或原始收据。

整轮 348.377 秒，QMP 已确认退出、QEMU rc0、零信号、租约持至退出。P4 未执行，`capture_verified=false`。

## 第26轮（run cfd5）：原厂红外快门起拍，取帧前互锁改变

同轮读回 `RELEASE_WO_LENS_LIVE=0`（允许无镜头释放），没有写设置。原始 App32 红外键 `0x030f1d2d` 产生 `0x02130000/1`（控制台 12253/12293），原厂执行接口分别收到 `(press=1, trigger=5)`、`(press=0, trigger=5)`（12259/12297）。12849 行原厂 AP 发送 16B `0x4038`，12851 行现有虚拟拍摄后端接管该请求；这不是机身快门通过。

守卫首检通过后，原厂 `0x403d` 在 12857 行重新加 `0x8000` 成像锁，模型状态查询（12862）返回了同一个实例的 128B 状态且传输无错，随后工作线程在 12900 行报 `-ENODATA`，原厂在 12930 行才解锁。现有复查要求不含这个互锁位；这段时序足以解释该拒绝，尚未验证修正。没有 `FUNCTIONAL_CAMERA_MODEL_ADMISSION` 或 `FCAM_OP_FRAME_CAPTURE` 传输，不能将错误解释成合成 CMOS 未实现或没有数据。现有虚拟帧源已在功能模型中实现，但这轮从未调到它。真实 CP 的传感器链不在本轮范围。

P4 等待 120 秒后失败，未导出虚拟卡；800 秒只读监视到时退出，QEMU、卡和 owner 仍按安全合同保留，`quit_sent=false`。下一步是验证已接收请求在短暂互锁期间如何有界等待并在原厂解锁后复查，保留身份、租约和成像前置检查，不直接清互锁。JPEG、写卡和故障后正常收尾未通过。

## 第27轮：只重试已接收请求的短暂成像互锁

`runtime/analysis/functional-capture.c` 的工作线程只在复查失败且快照显示本进程拥有的成像链处于单独的 `0x8000` 互锁时继续等待。重试窗口为 1 秒，用单调时钟；每次等待前释放原资源预约，重读同一实例的模型和当前代次，并重新执行完整准入。请求入口、其他互锁、资源拒绝以及正常退役判据未改。没有清锁、重放输入、生成替代 JPEG 或强关保留实例。

两线程定向验证：工作线程/资源夹具 66 项（含 ASan/UBSan），调用接线 31 项，全部通过。隔离交叉编译与归档读回通过：观察器 `2ab9ae1548afe3f5d98567c1f90827b0c0957f4c3dd6461c79aadfe87d8e6061`，归档 `4ca0c56e10d1176a3053a6a6bab8d0c94a87490827d9e8bc70b008bff52519ee`；新时钟调用绑定 `GLIBC_2.17`。默认归档和 `cfd5` 不变。

实跑 `9584` 接收原厂 `0x4038`（控制台 14857），随后完成成像准入（14861）并发送 `FCAM_OP_FRAME_CAPTURE`（14863）。这一轮没有证据证明必须经历互锁重试；可确认它到达了此前未达的取帧调用。模型返回 `-ENODATA`、零像素，不是成像互锁复查返回的错误。旧监视器替代项发现保留收据后退出，虚拟机及卡未释放，未见 JPEG、原厂写入或双卡读回。

## 原厂照片格式到取帧的配置接线

`9584` 的 14491–14545 行记录原厂 `0x402d` 事务完成及 AP 释放回复；core 的 op17 原来仅接受主机显式 `CONFIGURE` 等路径设置的 `capture_configured`。现仅在传感器已初始化且当前路径仍是 640×480 活动 VDF 时，接受同一模型已完成逐字节读回的原厂照片格式作为另一条配置证据。未初始化、未配置、非法照片格式和失活路径依旧拒绝。

两组定向宿主验收通过（真实模型 2 项、照片格式接线 232 项）；真实模型场景取得完整 640×480 RGB888 帧，并检查当前代次和原请求、像素摘要。用原配方在独立目录构建，模型 `e1535e843686bf8de4e81a24af446ee318eb9f9983e1b57cf765e9cc3c6ca6bd`，默认模型未换。尚未在 guest 中消费新模型，`capture_verified=false`。

## 第28–29轮：隔离模型的启动与 P4 身份绑定

第28轮 `0e41` 未启动 QEMU：runner 已复验候选模型，后续 RAM 卡租约仍复验旧默认件，触发源码摘要不匹配。保留 `scratch/a7c2-apo-menu-round28/runtime-1/attempt-1.json` 和独立 prelaunch 账本，不把这次拒绝标成取帧或 QMP 失败。

第29轮只在显式隔离 RAM 卡路径传入候选模型，runner 与租约均使用现有模型身份验证。启动 manifest 同时索引模型库、构建收据及源码归档，P4 使用已记录的隔离路径，默认分支不变。broker 仍从固定只读 FD 加载并读回摘要。第28轮模型/校验器两组共 22 项加 94 子用例通过；租约修复后，第29轮两组共 16 项加 5 子用例通过，其中验证候选模型确实抵达租约的模型检查，错误在读取盘输入前拒绝。新隔离观察器归档读回未改默认件。

第29轮 `2970` 绑定到新模型，接到原厂 `0x4038`（控制台 13031），并从模型读取了状态（13033）。后台复查与 `0x403d` 重新加锁交错（13038–13039），随后在取帧调用前返回 `-ENODATA`（13040）；原厂稍后解锁（13110）。这与第27轮的 op17 模型拒绝不同。观测未直接读取失败瞬间的 busy 与回复计数。QEMU 和卡仍保留，未导出，`capture_verified=false`。

## 第30轮：覆盖互锁消息和回复的短暂忙态

工作线程仍只在识别到同一模型和正常成像资源时等待，且不接受其他禁止位或故障。现在 0x8000 互锁、成像命令处理中和回复未释放，均可触发原有单调时钟 1 秒窗口内的复查。每次等待前释放预约，随后重读模型并完整检查；成像准入调用若再次遇到忙态也走同一规则。诊断记录有效互锁、忙态和活回复计数，不改原厂请求或置位，不提前宣布写卡成功。

双线程定向宿主测试 107 项通过（工作线程 76 项，接线 31 项），新增测试覆盖加锁处理中、解锁后活回复、再次加锁、其他禁止位和无关忙态拒绝。隔离归档 `6f16e0d0fbaf507325dacf4b8434b881a687f6cb462882c43f4d1b057f690244` 已读回，沿用第29轮候选模型。

实跑 `7c41` 进入照片模式。30 秒内取得 47 次只读就绪采样，`EE` 从 0 变为 1，禁止拍摄位始终为 1，末笔禁止计数为 1。未发快门，因而没有复验成像准入、取帧、JPEG 或写卡。QMP 正常退出，QEMU rc0、零信号，磁盘租约保留至退出。保留 `scratch/a7c2-apo-menu-round30/storage-post-exit.json` 及原始收据；未动旧实例。

## 第31轮：保留禁止来源和实时取景状态转换证据

第30轮的原厂禁止来源探针已启动，但 `CAPTURE_INHIBIT_SOURCE` 和 `EE_TRANSITION_TRACE` 当时未镜像到控制台。第31轮只把这两类已有的限量观察记录镜像到控制台，不更改拍摄条件、快门动作或取景等待窗口。两组定向测试 18 项通过；独立构建、归档读回和启动前模型绑定检查通过。归档 `e62c6785e5aede9e0563b0d0d8bbd5fefe41a147583e31eb272ff7681bd76e37`，沿用第29轮候选模型。

实跑 `1454` 的 13451–13453 行录到原厂模式线程将 EE 当前和影子值置为 `1`，提交后探针处的排他条目 `0x7b` 仍为 `0x1294`（EE 未运行）。10355 行的 `0xcb9` 是被联动的拍摄动作 ID，并非可据此命名的根因。30 秒内 45 次采样，末笔 `EE=1`、禁止位和计数均为 `1`；超时未发快门。QMP 正常退出、QEMU rc0、零信号，租约保留至退出。

静态复核：`0x339fc70` 进 `0x338d998` 写 EE 当前值和影子并置更新标志；提交函数 `0x338b528` 接 `0x2506ff0(0x304)`。原 EE 分发表首项 `0x27f5584` 返回 `1`，正常分支将模型 ID 交给以 `0x7e4e630` 为基址的延后通知队列，不走即时 `0x2490e18`。该路径能解释状态值和排他缓存有时间差，但第31轮未记录队列实际消费，也未在超时处复读排他条目，不能断言该队列一直未消费或最终只剩 EE 一项。

## 第32轮：超时时补读实际禁止输入

复用第31轮已验证归档和候选模型，仅在原就绪窗口超时时、同一 AppFw 进程仍存活时，额外执行一次既有范围一只读命令。原始输出和字段读回分别落盘；核同一 PID、加载基址，保留原超时错误，不调整快门守卫。历史真实样本验证通过（EE 当前、EE 排他值、日期、保存目标以及原读取范围），隔离启动前绑定检查通过。

实跑 `33b0` 的末次范围一读回同时记录 `EE=1`、禁止位和计数为 `1`、排他 `0x7b=0x1294`。日期值 `0`、镜头联动 `0x1406`、介质 `0x4ecf`、目标槽 `0x526a` 与其他已知规则均不在阻断值。已知规则中只有 EE 缓存仍落在阻断状态，与总计数 1 一致。原 30 秒窗口内 47 次采样，未发快门；末次规则读回之后、QMP 退出前，控制台 16683 行出现对 `0xcb9` 的 `inhibit=0 count_before=1`。这是原厂撤销的写入前记录，不等于已读回清零。QMP 正常退出、QEMU rc0、零信号，租约保留至退出；原始规则快照和收尾见 `scratch/a7c2-apo-menu-round32/`。写卡未验。

## 第33轮：等待原厂迟到撤销

沿用第32轮观察器和候选模型。原 30 秒截止时仅在读回匹配稳定照片模式、EE 已运行、单一禁止计数和 `0x7b=0x1294` 时，才继续同一轮只读等待，总上限 60 秒；若截止后的同一进程读回已确认就绪，也须在该上限内。实际快门仍要求原有 `shutter_ready` 判据，无强制清除或额外状态写入。用第32轮原始实测状态验证只允许等待、不允许按快门；两个来源、不同排他值、EE 未运行和模式切换均拒绝延长。隔离预检查通过。`4076` 本次在 27.2 秒读回拍摄许可，无需宽限。原厂遥控快门（不是机身全按）发出自然 `0x4038`；同一请求 `a91ecbe4a6fd9e44` 的 `op=17` 读回了 921,696 字节（96 字节头、640×480 RGB），模型及目标摘要一致。控制台依次见 `natural-request-owned`、`FUNCTIONAL_CAMERA_MODEL_ADMISSION` 与 `FUNCTIONAL_CAMERA_TRANSFER seq=40..55`。JPEG 入口记录 `request-rejected rc=-90`；未写卡，后端超时后保留 VM、卡与 owner（未发 QMP quit 或信号）。

### JPEG 原厂消息读取

- **封装未发现长度差异。** 原厂 `Main`（`libInfraAvbbc.so:0x1227d4`、`0x122aec–0x122b00`）和 `Without_Pin` 都发送 80 字节消息体；SID `0x82830752` 由 `OsalSndMsg` 进入 `SetDataflowMsg`，原厂 Dataflow `0x32538` 和 `0x32658` 追加 24 字节头，`0x34154–0x34168` 将实际总长传给 OSAL 分配器。
- **发现可解释拒绝的读取不兼容。** `osal_uipc.ko` 的消息池映射调用 `remap_pfn_range`（`0xdfc`），没有 `vm_ops->access`。该 guest 内核拒绝对 `VM_PFNMAP` 走普通 GUP；`/proc/self/mem` 在未传输字节时返回 `EIO`。旧适配器把读失败和长度不符统一记录为 `-EMSGSIZE`，所以 `4076` 未实测区分两者。
- **候选修复。** 仅对 JPEG OSAL 请求和回复的固定大小读取，在普通权限与范围检查已通过而 proc-mem 返回 `EIO` 时，用本进程私有非阻塞 pipe 的内核 usercopy；不修改消息、原厂代码、长度或来源校验。仍拒绝的报文增加预期/报告长度、读取返回码与最多 32 字节前缀。
- **验收与产物。** 两线程定向覆盖正常、ASan/UBSan 各 6 项；请求和 ACK/DONE 注入 proc-mem `EIO` 后仍可独立解码夹具的主图与缩略图，103 字节请求仍被拒绝。隔离观察器 `102bbbb648d98e32344a87892b11b6496af8e86536cdf97e6ec0f2bbf767c5f8`，initramfs `309fcba887264678a78d1208aba5f4cfd3e6ac9d734f2954d877b8e1ef276312` 已完整读回；默认运行产物未换。尚未在原厂运行链重复验证该修复，也未验出 JPEG、原厂写卡或双导出。

## 第34轮（063b）：语言场景已建立，实际像素未更新

隔离观察器正常启用 JPEG 适配器，原厂 UI 控制台第 7024 行创建 `0x12d` 语言页；但显示导出只有第 5056 行发布的 `sequence=1/pixel_source_seq=1`。首设阶段保存的 `ui-1000.png` 至 `ui-1073.png` 共 74 张，SHA-256 均为 `441da7236f6ffdd8fb4cdfa2d9ce7b8d8df8cf2f7a8e82c530714d92266ce613`，640×480 RGB 像素全黑。原厂加载过语言页资源；未取得可供验证的显示输出。没有发出首设按键、菜单或快门，不把场景 ID 当成看到了画面。

25 秒语言页等待以原错误退出，`attempt-1.json` 确认 QMP quit、QEMU rc0、零进程信号、租约持有到退出。后台监视器 rc0 是正常生命周期核对通过，不是本轮业务通过。JPEG 请求、写卡、导出及 `capture_verified` 均未通过。停止态占用见 `scratch/a7c2-apo-menu-round34/storage-post-exit.json`；本次未执行回收。静态核对表明现有 RAMFB viewer 同样从 HOSD 文件取像素，仅替换截图接口不会推进 `pixel_source_seq`，还需确定启动路径中的像素发布差异。

## 第35轮（7118）：一次 DOWN 探测暴露首键超时回归

在原厂创建 `0x12d` 和输入线程后，本轮只发送一次 DOWN。`INJECT_KEY_SEND` 对按下、释放均返回 0，但没有 `INPUT_EVENT32` 消费记录，也没有新像素发布。新适配器在 12 秒报 `Original first-setup key not consumed: DOWN`，随后 QMP 正常退出、QEMU rc0、零信号，未进入 JPEG 或写卡。

第33轮 `driver.stdout` 的实际首键/第二键耗时为 133.435/83.126 秒；因此第35轮的 12 秒首键门是验收适配器回归，不能单独归因为原厂失效。第36轮仅首键允许 180 秒、前三键其余为 90 秒、后续为 20 秒，仍按真实回执立即推进，不恢复每键 600 秒；若再失败，保存该 UI 线程的 `comm/wchan/stack` 和有界的原接收点日志。黑帧是否在迟到的输入后解除、JPEG 修复及写卡仍待实跑。

## 第36轮（e705）与源码回归对照

首键 DOWN 等待 180 秒后仍无原 App 消费；`firstboot-input-timeout.raw` 记录 UI 线程 `AppFw` 的 `wchan=futex_wait_queue_me`，调用 `futex_wait→do_futex→SyS_futex`，不是输入队列返回点。QMP quit、QEMU rc0、零信号，无 JPEG/写卡。

对照最后能完成输入的第33轮与首次失败的第34轮：两个隔离构建的 `menu-observe.c`、`headless-osd.c`、`functional-capture.c` 逐字节相同，启动环境仅实例路径/inode不同；业务源码差异仅为 `functional-jpeg-codec.c` 的请求/回复读取修复（测试文件及身份清单另异）。第34轮另外用等待可识别中文画面的新适配器替换了第33轮既有动作流。故不能把本次黑帧归给 OSD 源码修改；首设驱动和原厂等待条件需要分开定位。第37轮将在等待早期用既有 `menu-regs` 读取 AppFw 的用户态 PC/FP 链，同时保留有界回执等待，不补 ACK、不清信号量。

第37轮 `144f` 的提前取证已经取得 `AppFw+0x2f3aa30 ← 0x24cce7c ← 0x1e78eb8 ← 0x17a6314 ← 0x1796ef4`。这与既有条件变量屏障一致；但本轮没有 `BACKUP_K_REPLY` 不足以说明正常路径必须经过虚拟 Backup，且 pending/daemon 尚未同时采样，不能把历史 Backup 结论直接套到当前首键。QMP quit、QEMU rc0、零信号，未进入 JPEG/写卡。第38轮改用产品已有 `collect_passive`，同轮读取 pending、AppBackupDaemon、ExternalOSDIF、GRM 等最多16个线程，证据不足时保持 unknown。

## 第38–39轮：Backup pending 与持久盘写入推进

第38轮 `4f9d` 的 `firstboot-input-passive.json` 实际读到 `BACKUP_SYNC_PENDING=1`；AppFw 仍是相同条件变量等待，ExternalOSDIF 在原 OSAL 接收路径，GRM 线程在 futex。AppBackupDaemon 不在 CP 回复等待，而是在 `sony_persistent_flash command → generic_make_request → submit_bio → FAT write` 路径。本轮随后按首键超时正常 QMP 退出，未验证 JPEG 或写卡。

第39轮 `6de8` 做两次采样：`BACKUP_SYNC_PENDING` 均为1，daemon 均在运行；虚拟盘 mtime 从 `1795114994461056165` 推进到 `1795115014914049486`，块数不变。第一栈在 `persistent_flash command+0x34`，第二栈已到 `end_buffer_async_write → bio_endio → pf_make_request+0x294`。这证明同轮写入有推进，不能把单一栈位置称为死锁，也不证明 Backup 已结束。JPEG 和拍摄写卡仍未验；下一轮只在有该推进证据的情况下延长首键上限，收到原输入后立即继续。

## 第40–43轮：从持久盘写入定位到 UIPC 固定块耗尽

第40轮 `b0a3` 把首键窗延到360秒，双采样和宿主盘 mtime 仍显示写入推进，但总运行约602秒后仍没有原输入消费。该结果排除了“再延长同一个等待窗即可解决”，后续不再重复相同配置。第41轮 `bba4` 在超时前保存终态：`BACKUP_SYNC_PENDING=1`，AppBackupDaemon 进入 `osal_valloc_msg_wait → uipc_oom → alloc_fblock`；AppFw 仍在条件变量等待。两轮均 QMP quit、QEMU rc0、零信号，未进入 JPEG/写卡。

第42轮 `260e` 的池读取失败，原始 transport 明确记录 `head: applet not found`；空文本不能作为无池数据或无阻塞证据。该轮保留为采集器失败。第43轮 `90aa` 改用同目录已有的 `passive_backup.collect_passive`，以 `dd if=/proc/osal/uipc bs=32768 count=2` 读取原 proc 两个阶段；独立解码器自测通过，实际得到826行输出。

第43轮池与历史快照对照：

- 本轮 `fblock free=0`，但 normal vblock 仍有520,512字节连续空闲块；不是简单的总内存不足或4096字节回复没有连续空间。
- 本轮 `msgs=8742`，`GMSGQ 3E0` 为8,728条；历史 `df07` 快照为 `msgs=11`、`3E0=2`、`fblock free=561792`。固定块主要被该动态回复族持有。
- 同版共享库与 `maps` 全量符号化证明，AppBackupDaemon 的调用链是 `appFw+0x2ff07ac → … → appFw+0x367f758 → libosal_uipc.so+0x7fe4`，即 `u_osal_snd_sync_direct` 的内核 ioctl。`appFw+0x367f718` 是原日志时间戳的32字节同步请求，不是 Backup 专用40字节请求或4096字节回复。
- 因而不把 `3E0` 直接归给 Backup endpoint，也不清 pending、不扩池、不伪造 Backup 成功。第44轮新增仅匹配 `0x803e*` 的32条有界发送归因日志；包装保留原函数指针绑定语义，不改消息、所有权或返回结果。观察器 `c82800a56432a4c7c1bfa9cf57eee6331d7165b2645b01e40fe06250dd1dd8c8`、initramfs `21001e548f5381f71f7df045566da5280dda269be82dc037810116ba2669aec3` 已读回，业务通过仍待实跑。

第44轮 `2ab6` 最终没有任何 `DYNAMIC_803E_SEND`，而 `3E0` 仍精确为8,728条，`msgs=8743`、`fblock free=0`。这排除了当前用户态功能模型经统一 `real_send_msg` 边界发送该族消息，但没有证明原内核或内核模型是谁。原内核 `.config` 明确未启用 kprobes，不能走该路线。第45轮仅在隔离 watcher 副本中，用实际 `module_texts['osal_uipc']+0x3bf8` 的条件硬件断点观察 `osal_snd_msg`，核对入口四条原指令，最多记录32条 destination/source/bytes/caller/消息头并自动停用；不改产品 watcher、不写 guest 代码、不改变消息或返回值。其实际证据尚未取得。

## 第45–58轮：从观测边界到 `backup_sync_msg` 洪峰

第45–47轮的隔离 watcher 路径错误均留档，没有当作原系统失败；第47轮保留的 `f498` 未强杀。第48轮证明断点可命中，但内核地址有符号转换使消息读取失败；第49轮读到4条普通 DMM 消息。第50轮确认 watcher 在两条 UPM 收据后提前 detach，第51轮在 early model17c 增加断点仍只有 early2/runtime4，说明洪峰发生在更早的原模块初始化阶段。

第52–54轮逐步排除符号获取错误：guest shell 时 osal_uipc 尚未加载；setup 前缀实际能成功加载；kallsyms 不提供该符号。第55轮改为 setup 在 osal_uipc 加载后分段，以 `/sys/module/osal_uipc/sections/.text + 0x3bf8` 并核对入口指令，pre-setup 捕获6条普通消息。第56轮加入公开 `osal_snd_sync_msg/osal_snd_sync_direct`，第57轮加入内部 `__osal_snd_sync_msg/__osal_finish_sync_cb`，仍只有这6条。第58轮才发现过滤条件本身排除了 `0x003e` 与 `0x903e`：改为按 bits16–23 的整个 `0x3e` 模块族后，立即取得32条，其中29条来自内部 `__osal_snd_sync_msg`，目标主要为本地 `0x003e014d`、来源 `0xa5a5a5a5`，3条才是普通 DMM。

原代码与二进制复核闭合了业务归属：`backup_sync_msg` 以 service `0x003e014d` 分配112B，并经 `osal_snd_sync_msg` 调用；`backup.ko::backup_osal_init` 确实为同一 qid 注册同步回调。`menu-observe.c` 里旧的 `if(0)` 分支注释也明确记录该 daemon 会产生数万次调用。原 `backup_sync_msg` 总是释放并返回0，因此不能简单声称“正常回复没人释放”；当前必须继续核分配/发送/释放的实际对应关系。旧分支的“直接回成功、无 CP 存储”仍是禁用的假实现，不能作为本次修复。第59轮加入 `osal_free_msg` 追踪消息指针，区分 UIPC 分配请求积压、所有权错误与真正的回复未消费。

## 第59–65轮：排除单纯 fblock 泄漏，定位到原 Backup 处理吞吐

第59轮同一消息指针被反复复用；第60轮16次 `osal_free_msg` 返回均为0。第61轮32条小窗口没有命中 `free_fblock`，曾作为控制块未归还的候选证据，但不能外推为永久泄漏。第62–64轮修正模块加载顺序和 watcher 初始化后，仍在 AppBackupDaemon 前达到32条上限。第65轮把上限提高到1024，实际取得182次 `__osal_snd_sync_msg`、182次 `osal_free_msg`、332次 free 返回、325次 `free_fblock` 和3次普通 DMM 发送。故控制块确实会归还，先前“只进不出”的判断被新证据否定；真正问题是原 Backup 工作负载生产速度超过处理速度，最终把有限 fblock 队列打满。

消息体偏移12的字不能继续当作统一返回码解释；`libbackup.so` 的结果字位于 reply+4，原 `backup_sync_msg` 本身也总是释放并返回0。`backupfile_save_file` 每次写文件最终经 `vfs_write`，而虚拟块设备旧实现每次 WRITE 都在宿主执行 `pwrite` 后立刻 `fdatasync`。这与同轮观察到的持久盘 mtime 持续推进、AppBackupDaemon 最终等待 `alloc_fblock` 一致，支持“处理端被逐写同步拖慢”的方向，但不是允许伪造成功或扩大池的理由。

第66轮准备显式候选 `QEMU_A7PF_WRITEBACK_FLUSH=1`：每次 `pwrite` 和错误检查保持不变，只在该精确环境开关下省略 WRITE 后的宿主同步，原块设备 FLUSH(op=4) 始终执行 `fdatasync`；默认路径仍每次 WRITE 同步。核心普通及 ASan/UBSan 测试通过，新增同步计数验证 writeback WRITE 为0次、FLUSH 为1次、默认 WRITE 仍同步。隔离 QEMU `df6144a095f8cfbde49c454a9872129811ee9c831051417639e7129a4ddeb4b9`，不替换产品 accepted binary。功能相机 artifact 校验只在该环境变量为1时接受这个固定 SHA，其他配置不变。

第65轮另确认中文首设适配器在603秒内没有发出后续首设键，持续等待缓存黑帧变成“可识别语言页”。产品 helper 因此增加显式 `allow_unchanged`：仅语言选择允许缓存帧不变，放行依据仍是原键按下/释放消费与精确 `MYingHeiC-GB18030-SJ_wIcon.ltt` 打开事件；默认画面变化要求和其他首设页判据不变。中文/身份定向测试173项、294个子测试通过。第66轮是隔离收据逐字节相等断言的预检失败，第67轮是旧环境基线拒绝新构建路径的预检失败，均未启动 VM；第68轮才用于实跑该组合候选。JPEG、写卡和 `capture_verified` 仍未通过。

## 第68–74轮：身份门闭环与中文首设实际完成

第68轮在 Session 仍使用默认旧 binary/旧 persistent 收据时停止；第69轮 launcher 子进程只认识旧两个 QEMU SHA；第70轮证明 launcher 环境没有携带 writeback 标志。随后把固定 SHA 候选规则同步到 artifact 与 inherited-FD 校验，并在 launcher 环境字典中显式传递该标志。`bwrap --clearenv` 的持久盘参数中也增加精确 `--setenv QEMU_A7PF_WRITEBACK_FLUSH 1`，非法值 fail-closed；直接读取实际 bwrap 命令行确认该参数存在，不是只通过宿主静态检查。第72/73轮分别更新 launcher SHA 与 observer 输入身份；observer/overlay 二进制 SHA 均保持不变。上述预检失败均保留，未记作原系统业务失败。

第71轮 `2b24` 首次在该组合候选下完成整个简体中文首设：36个原键均有按下/释放消费回执，实际帧依次经过 language、privacy、setup-on-camera、area、date/time、temperature、creators/touch guide，最后稳定为 `shooting`。这证明 writeback 下原 Backup 不再把首设阻塞到 fblock 耗尽，也证明缓存黑帧本身不应阻止有原键和字体日志支撑的语言导航。首设后宿主分析耗时过长，原厂 APO 早通知出现；随后合作停止标记被驱动消费，QEMU 正常退出、零信号，未提交拍摄。第72轮以后改为首设完成后立即逐帧推进原厂省电菜单：每步等原键回执和实际帧，并核对参考动作的帧变化/不变转移；任何转移不符或 APO 早通知都停止，未核实 Off 前不允许 capture。拍摄、JPEG 与写卡仍未通过。

## 第75–89轮：Off 读回、JPEG 入口与 watcher 边界

中文首设后的菜单参考不能机械复用日语动作表：新 helper 已到拍摄页，而旧表在 `ui-42` 仍有触摸指南。实际改为原厂 MENU 打开主菜单，以 `3/57` 列表导航到 `53/57` 电源设置，选择「自动关机开始时间」的「关」。第一次只选 Off 时出现“是否更改设置？”确认框且默认「取消」，已明确记录该失败；后续动作改为 UP 选「确定」再 ENTER。`ui-110` 设置页为「关」、`ui-111` 重开仍高亮「关」、`ui-114` 返回拍摄，最近多轮均读回成功。原厂 APO 不再作为后续拍摄借口。

第81轮 `3a64` 已记录自然 `0x4038`、921,696字节原帧、88,788字节 JPEG 输出及原 ACK；完整消费者与写卡链尚未闭合。随后 `main_config()` 返回 `-80`（`-ELIBBAD`；此前误写成 `-EPROTO`），原厂重试，未完成原 MPR/Fsys 写卡。新增只读 `main-config-fields` 诊断只覆盖 getter 之后的字段比较；本次虚表槽检查失败发生在它之前，不能因没有该诊断而继续假定三元组不符。231项 JPEG 定向测试通过。第83/84轮完全取消菜单暂停后均在取帧前超时，第81轮有暂停则能取帧，证明 debugger/broker 交接会影响业务时序。逐键暂停又在长菜单中触发 APO；只在菜单打开和快门前暂停也在快门前失步，因此没有把这些轮次记为 JPEG 或写卡通过。

另发现 `record()` 同时向 `/dev/console` 写带 `OBS ` 的镜像、向 `/tmp/menu-load.log` 写无前缀记录，后续诊断 tail 会产生同 job/同 FNV 的重放。`require_natural_capture_closed()` 曾把重放误报为 overlap。解析器现只把直接 `OBS FUNCTIONAL_CAMERA_CAPTURE` 作为状态迁移，非 OBS 重放仅作诊断；直接 OBS 重复、write-retired 和双导出要求仍严格。159项相关测试通过。第89轮新增显式 `A7C2_HDMI_UPM_DISABLE=1`，只禁止诊断 watcher attach，保留 mailbox、自然拍摄及 P4 判据；测试证明不调用 `hdmi_upm_watch.start` 仍保留绑定。该开关的后续第97轮结果见下文：禁用的 watcher 同时承担 UPM 邮箱服务，不能把整条服务视为可删的被动诊断；`capture_verified` 仍为 false。

## 第90–97轮：修复首设重按并实际走完短菜单

首设没有随机变更。第93/95轮的快速适配器在第一次 ENTER 后只刷新一次，读到仍可识别的旧 privacy 页便再次 ENTER，跳过正常的「通过相机设置」选择，误入 `0x212` 手机配对/Creators’ App 等待。此前只补页面名和猜取消键没有修复切页顺序。第71、81轮成功收据已经包含固定首设路径及该选择页上的原 DELETE，不应把该遗漏归给新固件流程。

现在快速适配器恢复调用产品 `firstboot_step()`：沿用真实按下/释放回执、已变化且稳定的页面要求、未知页不确认和最新图像回调。语言选择保留显式快速路径，不逐键截图；按键消费后保留0.3秒间隔。意外配对页可识别但自动停止，不把尚无成功证据的取消键写成通用规则。另修复 `wait-owner.py`：QEMU rc0/正常退出不能把失败的首设报成 `--ui-ready` 成功；必须有当前轮 `ui-ready.json`。

集中宿主回归使用2个工作线程、2组：原厂首设控制器93项，快速适配器/失败监视器/普通菜单键回执11项，全部通过，源码前后稳定。证据：`scratch/a7c2-firstboot-transition-acceptance-v1/result.json`。这些是宿主检查，运行证据单独如下：

- 第96轮 `e8aa` 实际走完中文首设，36个原键；从首张首设帧发布到完成收据48.828秒。UP从 `3/57` 回到 `2/57`，没有绕到末页；该短路径假设已否定。其后原厂自动关机，外部精确身份 QMP quit 已确认并观察退出，原驱动未回填 `qmp_quit_confirmed`。
- 第97轮 `2208` 使用修复后的共享控制器，36个原键，从首张首设帧发布到完成收据47.193秒。该时间不包含建盘、guest启动和首设前等待。
- 第97轮菜单使用原 MENU → 原触屏设置图标 `(24,402)` → `44/57` 设置首组 → 8次DOWN → `53/57` 电源组；沿原选项及功耗确认框选择「关」，重开后再返回拍摄。`ui-68.png` 设置页显示「关」，`ui-70.png` 重开仍选「关」，`ui-73.png` 为拍摄页，主会话逐图核对后发布同轮 `apo-menu-readback.json`。不再进行50次DOWN的长导航。

第97轮随后请求拍摄，但43次只读样本始终为 `EE=0 / capture_inhibit=1`，来源行 `0x7b=0x1294`，驱动没有发出快门。原控制台32646行有 `FULL_HDMI_UPM_MAILBOX_INIT`，37396行有 `arming-timeout-or-status`，没有邮箱消费收据。此轮 `A7C2_HDMI_UPM_DISABLE=1` 同时去掉了实际邮箱服务；“禁用纯诊断不影响链路”的说法不成立。QMP确认退出、rc0、零信号，租约持有至退出，P4标为 `skipped-no-natural-capture`。首设/Off通过与拍摄失败分别记账。

## JPEG getter槽位修正与第98轮合批

主会话读回原 `libInfraAvbbc.so` 重定位：ParameterControl虚表地址点为 `0x1a8020`；`0x1a80c8` 对应 `GetValueEjRm@0xa4654`，即64位整数重载；`0x1a80d0` 对应 `GetValueEjRPv@0xa46e4`，即指针 getter。因此运行代码的严格槽位比较应读取 `vptr+0xb0`，原 `+0xa8` 偏了一项。`-80` 正是该比较返回的 `-ELIBBAD`，不是后续字段比较的 `-EPROTO(-71)`。

代码只修槽位及相应溢出边界，目标仍必须严格等于已绑定的原 getter；同步改fixture、文档与pin用途描述。新增否定场景把 getter只放回旧槽而让正确槽为空，要求拒绝。2线程集中验证：JPEG233项（普通及sanitizer）、拍摄资源76项，全过、源码稳定；证据 `scratch/a7c2-jpeg-slot-acceptance-v1/result.json`。

隔离观察器 `69a0448084d916ae63e0ef44120f4023400ace53782036294a7ba55999762a55`，归档 `d3e18cafab3d82081faecf6ce83eef7a2d3e0de3e4fe9a8847900efafc83afdb`、1,492,693,432字节，均完成归档与输入读回。产品默认件未替换。第98轮合入该归档、已证首设/短菜单，并恢复原UPM服务和所需的早期身份绑定。其实际结果如下，仍不提升为完整写卡通过。

存储：第96/97轮账本分别记录保留实占3,070,783,488和3,139,497,984字节（写账本前，未包含共享目录中的归档）；保留首设成功证据、独立设置盘和恢复依赖，下一消费者为检查点审查与精确引用审计。新归档的4GiB新增峰值预算在构建前登记；本批未执行回收，实际回收0字节。盘点时文件系统可用1,209,501,847,552字节。未完成新轮核收前不宣称全任务清理完成。

## 第98轮 `90e8`：原JPEG MainComp已闭环，Fsys来源尚未闭环

首设、Off设置/重开和拍摄页三帧再次实际通过（`ui-68/70/73.png`）。原控制台34186、34191行分别记录两个 `FULL_HDMI_UPM_MAILBOX_CONSUMED`；恢复的是实际邮箱消费者，不能继续将它当作无业务作用的纯诊断。

同轮自然 `0x4038` 后，主图88,788字节、缩略图2,627字节的原 `MainComp Exec` 均返回0（44785、44812）；各自的原 DONE、原配置长度写回、原输入引用释放和输出保留均为0（主图对应44791，缩略图44816–44819）。这验证了 `+b0` 槽位修正：运行中取得同一原控制对象的非空配置指针，原消费者实际写回长度。软件帧源/编码模型、原消费者与物理传感器仍分别记账，不称真实CMOS或物理ASIC已通过。

三笔通知被原AP消费后，44859行先出现 `fault-retained rc=-116`。其后原Fsys创建 `A:/DCIM/100MSDCF` 并发出 `DSC00001.JPG` 的两段写请求（44867–44870）：头部61,440字节，主图88,788字节，总有效长度150,228字节；主图段FNV与同轮JPEG输出一致。原异步提交和回调记录为0，但严格保存连接器返回 `write-source-refused rc=-18`，没有文件内容读回或双整卡导出，故不能从这些返回码推定文件已正确保存。

静态源码中，缩略图DMA的代次/引用要求可返回 `-ESTALE`，保存匹配器的源范围不属于本轮输出owner可返回 `-EXDEV`；旧日志缺少DMM查询原参数、当时引用数和Fsys源地址，尚不能唯一确定是哪一字段先错。保持全部守卫，不将引用置1、不接受任意可读地址、不伪造写入。`90e8` 按原合同保留，`quit_sent=false`、未发信号；`storage-retained.json` 登记本轮目录3,129,004,032字节、run目录17,567,744字节和当前归档/构建依赖，均不回收。

## 第99轮：一次补齐DMM、DMA和写源观测

`functional-capture.c` 仅增加功能profile内每job最多48条 `FUNCTIONAL_CAMERA_OUTPUT_DIAGNOSTIC`：记录已处理与未处理的输出DMM查询（含 `0x28` 保留句柄）、实际caller/handle/option、三个输出span的CPU/alias/容量/代次/引用数、缩略图DMA源与目的地址，以及每段Fsys写入的原地址/长度/摘要。记录器在锁外调用，保存errno；测试确认日志不改变原消息、返回、capture状态或输出引用。没有放宽来源、生命周期或读回条件。

首轮集中验收保留一个 `-Werror=misleading-indentation` 编译失败（由同一fixture扩散为78个setup error），写卡组64项通过；修正排版后仅复验受影响的strict/sanitizer两组，各39项通过。源码稳定，原失败不覆盖，未变的64项结果按原收据保留。证据：`scratch/a7c2-capture-output-diagnostic-acceptance-v1/`、`v2/`。

新观察器 `e34e9f47378fd6e80bb7099f601c6dd86d688e6a9e6cef8ca43b816606034683`，归档 `cd11151056024fc05c67e53ea3b39ff298c21425a0d4b55b96169ce563eac947`、1,492,696,112字节，已完成隔离构建和归档读回。第99轮沿用第98轮的首设/Off/UPM/JPEG路径，仅合入上述观测；该轮实际在快门前被下述独立UPM断点问题阻断，没有取得DMM/DMA/Fsys新字段，也不能记作第98轮写源问题再次复现。

## 第99轮 `e937`：UPM断点重复停在同一load站点

首设输入已推进到原拍摄页（`setup-11-enter-02/03 shooting`、`setup-12-page-00 shooting`），随后下一次串口截图没有完成，首设完成收据尚未生成。720秒宿主阶段截止后监视器报错；原owner按 `HDMI/UPM debugger detach unconfirmed` 保留，`quit_sent=false`、`must_remain_stopped=true`。未发MENU、省电未设置、快门未发送，不能把这轮当写卡实跑。

离线核原五条事件，不连接保留实例：bridge(1) → send(2) → receive(3) → load(4) → load(5)。第4/5条都是kernel TID289，同一task、`SP/X29=0xffffff8009293d90`、同一接收槽 `0xffffff8009293db0`、同一消息 `0xffffffc15c7fe480` 和相同16字节body。第4条已经把关联器stage从receive更新成load；第5条因此在 `stage=='receive'` 守卫失败，报 `Wrong original body load`。现有原始数据没有表明消息或所有权发生了变化，不能将其误归因于首设或固件行为。

直接源码原因：`select_breakpoints()` 对全部active lease持续启用load/consumer等站点，没有按已证明的协议阶段关闭上一站点；配合always-inserted硬件断点，continue时可在尚未执行的同一个load PC再次停止。修正仅让每个active lease启用其下一阶段：receive→load，load→consumer，consumer→branch，branch→handled，handled→free_entry，free_entry→三种allocator，allocator→free_return。关联器本身不接受重复，不合并/丢弃原事件；新增测试仍要求真正重复load被拒绝。

新增14个阶段选择矩阵用例（含两笔lease已满时bridge必须关闭）和1个重复证据否定用例，连同功能邮箱交接以2线程验收。首轮保留了新fixture常量遗漏、bridge满额落入stage分支的 `KeyError`，以及正向模拟GDB在失败时进入生产保留循环导致的210秒超时。修复后v2完整组429项中427通过、2个新fixture因缺少 `tracker.context` 失败，协调器6项通过；生产正向双lease完整收据路径已通过。仅补fixture context后，v3重跑完整15项新矩阵并补5项主动早报，全过；生产watcher在v2/v3及当前的SHA均为 `138f7c0613a10b2ad5d2de5a6cd3bda3ed3d821489cd01d9604e5ec89df6e651`。唯一case去重为429项watcher、6项协调、5项早报，证据 `scratch/a7c2-upm-stage-acceptance-v3/host-consolidated.json`；旧失败和超时原样保留。

首设/菜单监视器另补即时错误检查：读到当前run的retained-owner或 `must_remain_stopped` 收据时立即报错，不再重复打印最后一帧直到720秒。该检查不生成首设完成标记、不关闭实例，也不替代真正 `ui-ready.json`。

第100轮只移植经过AST定位及完整读回的host选择器，保持第99轮同一guest观察器和归档，未重建QEMU或大归档，也未改原实例。30秒心跳、910秒观察硬上限及即时错误检查均已接入，其实际结果见下节。第99轮盘点保留目录实占3,109,330,944字节、原run证据4,153,344字节；下一消费者为owner批准的正常调试器恢复/detach和引用审计，未执行回收。

## 第100轮 `7ef3`：确定两个输出所有权缺口

UPM阶段选择器实跑取得两份原邮箱收据并确认detach，未再停于重复load。中文首设、Off设置、重开Off与拍摄页通过；同一实例的action-74随后触发自然`0x4038`。主图88,788字节和缩略图2,627字节的原MainComp再次返回0。拍摄仍失败且按原合同保留，未发QMP quit或进程信号，`capture_verified=false`。

48条/job的有界诊断实际记录了21条。主会话从原控制台离线核得以下顺序，未连接或修改保留实例：

| 原消费者事件 | 同轮实际结果 | 对应缺口 |
| --- | --- | --- |
| 三个输出handle先query2a、各share21，再各free23 | 三个share只有新增的1份引用；free后缩略图引用归0 | 发布1006时没有把每个新unit的初始引用移交AP |
| 缩略图DMA，诊断n=10 | header/thumbnail引用均0，返回-ESTALE；目的alias也落在软件header范围之外 | 初始引用缺失和头部分配未接分别阻断同一操作 |
| 原MPR共享header/Aux | 实际unit为`0x80d61/0x27f`，handle为`0x41b/0x41c`；未被本轮输出owner处理 | 原header/Aux分配落入其他内存提供者 |
| Fsys两段写，诊断n=15/16 | header CPU`0x7e54a68000`在本轮owner之外；主图CPU`0x7e206c4000`、提交90,112字节在本轮Main范围内，有效88,788字节 | -EXDEV来自头部来源，不是主图字节或同代JPEG配置 |

原MPR小窗口反汇编进一步确定：`0x2b1eb4`构造**op0x20 allocation**，unit位于请求`+4`、`+8=0`、`+12=0xffffffff`、option位于`+22`；`0x2b2224`为option1分配封装，发送返回点仍为已绑定的`0x2b1f08`。原代码没有从MPR封装发出旧fixture预设的“op28按type查询”。主会话另核`0x2b2040–0x2b2138`，回包status=0才走正常解析；不采纳子代理将该比较反读成“必须大于0”的说法。小窗口/完整反汇编保留在`scratch/mpr_win.txt`、`scratch/mpr_full.txt`，仅用于本机证据核收。

## 输出所有权与原分配的合批修复、宿主验收及第101轮

权威修改位于产品`runtime/analysis/functional-capture.c`与`report/functional-capture-output/capture-output-memory.{c,h}`。1006的真实发送包装在暴露消息前，为metadata/Main/Thm三个已验证句柄各预留初始引用；发送接受或同一消息已有真实receive/free时提交。只在发送确定失败且未观察/使用时撤销，已提交或已被原DMM使用的引用不能取消。该步骤是新unit发布的所有权移交，不清除原AP状态，也不把引用计数写死成就绪条件。

header/Aux接入原op20，只接受已观测的`0x80d61/0x27f`与原40字节/option1格式、原MPR发送点、同代输出owner和原mapbase。各自的第一次成功分配获得1份引用；重复分配拒绝。旧的“op28按type分配”fixture已移除；share21回包与失败撤销使用真实unit，消除原先把header恢复成unit1的错误。未观察到的失败分配可撤销，已观察的发送保持保留。DMA的正引用、代次、源/目的范围与逐字节读回，以及Fsys同代匹配/完整主图/来源范围判据均保持。

全部实现与fixture同步后一次集中使用2个工作线程：集成/接线127项，输出内存、DMA/保存、原Exif组件69项；**196项通过，0失败、0跳过，源码前后稳定**。包括strict和sanitizer、原share/free后仍有1份引用、最后一次free才归0、未发送撤销、inline接收后错误不得撤销、分配失败、重复/未知unit、错误caller/option与真实header unit的free回滚。原Exif组件相应多释放一次分配初始引用，实际原free计数为5；该组件仍明确`notifications_sent=0/original_AP=0/Fsys_saved=0`，不作为拍摄写卡业务通过。收据：`scratch/a7c2-output-ownership-acceptance-v1/result.json`及两组原stdout/JUnit。

隔离观察器构建完成：`cc2c2c8b080787c7da46a53b30f5c1c40d1ccb3b686a2f22e3c14bf96354c8df`；新归档`e00c7bd293b3b23b41157e83cb770bc70543ebe42e6b09103565d89ec09c93c1`、1,492,698,344字节。原产物保持；构建前登记4GiB峰值加64GiB余量，构建器完成私有输入、完整归档和产物读回。第101轮已用新独立状态启动，沿用第100轮首设/短菜单/UPM路径，仅替换这份观察器；40GiB保守新增峰值与64GiB余量另在本轮`storage-start.json`登记。30秒心跳、910秒硬上限、retained-owner即时错误均保持。其自然DMA/Fsys、文件读回和双整卡导出尚待实际结果，`capture_verified=false`。

## 第101轮 `d79c`：DMA与原写入完成，发现host读回顺序互等

第101轮自然`0x4038`及两路JPEG再次完成。原日志44593–44594明确记录缩略图DMA成功：2,627字节，header/Main/Thm在使用时各有1份引用，原调用者和同代alias范围正确，复制后读回FNV一致。44603–44623记录原Fsys对`A:/DCIM/100MSDCF/DSC00001.JPG`发出61,440+88,788=150,228字节写入；两段均通过`capture_save_match`，原submit、callback、finished和callback-return均为0/已返回。五个输出handle的最终free23全部为0，header/Main/Thm引用归0。至此第100轮两处输出所有权缺陷均取得真实消费者证据。

但该轮**没有执行文件读回或整卡导出**：`p4-capture-wait-failure.json`保留120.185秒/205次检查的原失败，`exports_started=false`，VM仍保留，未quit或发送信号。原因是host驱动`export_after_capture()`先调用`wait_capture_closed()`；后者等待`write-retired`，而`retire_saved_output()`必须先收到真实文件readback/coverage才会退休。`file-media-config.c`又只在原flush处理器调用`fsys_native_write_readback()`。原flush由导出入口发起，所以旧host顺序互等。这是首次走到完整写入后暴露的接线错误，不将原写入返回0提升为文件内容正确。

修复只动host：产品`functional_camera_runner.py`复用同一严格自然拍摄解析器，另提供“可发起原flush”的前置检查，要求同pid/job/request/frame、同写token、匹配源及完整原submit/callback/finished/callback-return，验证cookie、长度和真实返回。它不生成退休或拍摄通过。新P4顺序为该前置→原flush与双整卡导出→原有严格capture/resources退休→双导出收据→退出门。两阶段使用独立收据和轮询原件，原最终判据不变。

两条并行只读调查确认五handle已全部释放，且`FSYS_SYNC_INCOMPLETE(-2010)`只使同步写观察表失效，不进入此异步JPEG读回和flush返回码；不把两段source-match的rc1称为文件读回。仅对本次host变化跑了10项轻量定向检查（2线程、8+2），包含保存的101轮日志“可flush但未退休”、7个否定场景与flush/双导出先于严格退休的顺序；未重跑196项、未重建guest或重复扫描大归档。

第102轮`f1fc`沿用同一观察器和归档，仅安装新host顺序。中文首设及`ui-68/70/73`三帧已核，action-74已原子提交；当前执行原拍摄/flush/读回，监视器240秒硬上限，出现保留状态立即报告。`capture_verified=false`，等待实际文件与两份整卡证据。

第101轮保留目录盘点实占3,127,357,440字节、原run证据18,882,560字节，另立`storage-retained.json`；下一消费者为离线核收与owner批准的正常恢复，未执行回收。盘点时文件系统可用1,181,826,252,800字节；第102轮运行中，尚不宣称收尾完成。


