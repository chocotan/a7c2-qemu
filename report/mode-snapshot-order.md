# MODE 五档标签绑定已修复；原输入与 LCD 限定验收通过

最新`run-si4_cfdb`已由main逐图核对：P/A/S/M显示各自原字母，AUTO显示原“智能自动”说明页；原包status为3/5/4/6/1，原dial读回1/2/3/4/0、switch均0。下文保留此前错位及调查路径，不把旧轮次改判通过。此通过只限五档选择与原显示，不含曝光行为、MR记忆档或实际拍摄。

仅限隔离QEMU、2.01 ALLLANG。原`appFw.so` SHA256为`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。原输入编码未改；以下不构成MODE完整验收。

`run-7ecmm7no`及`run-4lecvtlx`采用显式`A7C2_OSD_SUBMIT_TRACE=1`，原入口四指令逐字核对，保留全部ABI参数、FP/NZCV并重放原指令。观察点为原`translator_icon_exposure_mode::translate@23a7ae4`：其原指令从model_t+0读模式、+60读类别。每次状态变化重点记录，重复记录限额；最早一轮只记录前256条导致后续采样不足，不采用它单独归因。

实际A/S/M/AUTO输入后：

| 输入档位getter值 | 先到调用：caller205c238，tid420，model+0 | 随后调用：caller1d2c394，tid302，model+0 |
|---|---|---|
| 1（前端请求A） | 0 | 1 |
| 2（前端请求S） | 1 | 2 |
| 3（前端请求M） | 2 | 3 |
| 4（前端请求AUTO） | 3 | 4 |

不同调用点使用不同model_t。`run-4lecvtlx/gtk-mode-a.png`实际HUD图标仍为P；等待4秒未消除旧档。顺序记录不是原子联合快照，不能仅凭线程号命名渲染角色或直接断言调度故障。**后续角色核对已确认205c238来自remote/PTP属性转换，并非绘图入口。先前将tid420称作绘图线程的说法已撤回。**

已核原字节的数据来源：

- `205c1ac`中，`205c220→2059980`填充局部250B model_t，`205c234`调用图标转换器。
- `2059980`从传入snapshot引用解引用后的`+2a2c`读u32写model+0；从snapshot+44f4读model+60。
- 唯一直接调用205c1ac的站点是`24088d0`。外层`24088b0`将其传入x2 snapshot转给该helper；结果true时写property+c，false回退property+8。
- 主线程`1d2c390`传入另一个持久model_t（所属对象+14b88）。两条路径的snapshot获取/更新关系仍待闭合；不能因主线程值正确就宣称整个图标模型已同步。

## 后续核实的 remote/PTP 角色

主会话复核原`2439bc8`指令为`mov w0,#500e`，`243a0b8`直接调用`24088b0`；`243a634/243a63c`的ADRP+ADD引用`41ca2c0`，原字符串明确为`remote_presenter::set_exposure_program_mode(const remote_presenter::remote_presenter_model::model_accessor_exposure_program_mode&)`。所以205c1ac使用共用图标translator后是在把资源ID转换为remote属性枚举，不能把该调用的旧值作为HUD渲染读旧snapshot的证据。

`2440534..2440540`将持久accessor `this+944c0`传给这条链；支持状态及`this+17f50`的bit55控制是否处理500e。已见前置`23ec8ec`调用，但accessor首指针的建立、快照复制/更新时间仍未闭合。没有证据说明remote属性按契约使用前一快照，也没有证据证明它造成HUD延后。后续若观察该accessor，只能检验remote路径自身，不能据此修绘图调度。

另两项仅缩小范围：`run-5e2c8yym`原1003提交ID匹配当时on描述符；`run-9ecqemfc`在1005时按原锁/引用租约重读同bitmap，已记录样本与retained摘要一致。未据此交换on/off、强制notifyDraw或改变1005保留规则。

## presenter 与通用资源消费的后续定位

原槽`5afbc18`（fileoff`5aebc18`）指向`1d2f3d4`，RTTI名字为`22scr0132_0001_presenter`；`1d2f400`调用含三次translator的`1d2b604`。因此已知类归属，但未证明这些实例是当前可见拍摄HUD。后续布局处理后，`1d2f474`调用`this+250`对象虚槽+20，具体目标和可见页面关系仍未闭合。

有界枚举复核已结束，仍未证明P在相关类型中等于0或1。main重读原字节还明确ABI：第二槽`1d2c3a0`构造的是**x3=this+14dd8的地址**；`1d2c3a8`加载的**x1=*(*(this+258)+6e8)是输出参数**。原translator `23a7af4`将x3存入x20，`23a7b04`向x1+3c写入，`23a7b24`才从x20读取model[0]。因此6e8链不是模型源getter，不能沿输出参数反推输入。现有C观察的model来自第四参数x3，参数地址匹配widget的证据仍保留；源模型首字的生产者/类型仍未闭合。三张名称表首项名称、名称指针重定位项也不是数值枚举证据，下一步只查类型对应原名称lookup与索引换算。

main独立核原`view_icon`虚表`58e0838`：槽+140指`17e9a10`，返回`widget+1d8`参数；槽+150指`17eb1a4`，原函数按字节`widget+204`及资源字段`widget+214`分支。后者对应参数+3c。原`17eb5b8`调用`ImageElementBase::setImage`，`17eb5f0`调用`ResourceManager::getImageSize`；存在条件资源重映射，不能把原资源ID直接当最终提交ID。

新的显式观察仅做参数地址与`widget+1d8`的身份比较，或对原表`41b23a0`前18项（六种模式图标变体×三种类型）的资源族采样；不保留后再解引用旧widget。记录匹配槽bitmask、原资源ID、原字节204和原始时钟结果，**每个dial值最多32条，visibility_unproven=1**。诊断筛选不限制生产GUI模型或改变widget处理；匹配地址也不等于页面可见，消费者入口不等于已经绘制或提交。主机测试须验证不改widget、采样额度与别名、errno保持后，再做串行原固件运行。

此次调查辅助器曾误写旧`scratch/mode-snapshot-lifecycle/`中的`elf-metadata.json`、`1d2c1c0-1d2c500.{bin,asm}`、`23a7d20-23a7d60.{bin,asm}`。已记录此取证范围偏差；未自动回滚以免覆盖已有工作，生产未由该代理修改。本文结论依据main重新读取的指定原库摘要、ELF映射、虚表、原字节，不依据被改写的旧元数据。

## 实际参数与 widget 的匹配结果

`run-v6a2vl63`实际记录38条消费者样本，dial0..4分别16/4/4/4/10条，所记录条数未达每档32条；不据此宣称所有符合筛选的调用都已覆盖，仍受资源族/身份筛选及观察覆盖限制。参数槽bitmask为2的实例确实与当前消费者`widget+1d8`地址相同，原消费者读到的资源如下：

| dial | 匹配槽1的原资源字段 |
|---|---|
| 0 | `02001a76` |
| 1 | `02000000` |
| 2 | `02001a75` |
| 3 | `02001a7a` |
| 4 | `02001a77` |

main查看原LCD组成的`mode-resource-review.png`：请求P仍为自动说明，请求A/S/M/AUTO分别显示P/A/S/M。这证明延后仍存在，不能仅凭原资源字段改变称绘图正确。实例的页面可见性、这些ID的独立字形映射及`setImage`条件重映射后的实参仍未证明；两个MODE枚举域也不能仅凭数值相同当作同一域。SD另已独立读回与export摘要相符、fsck0、owner resumed；整体仍false。

该观察随后在原`17eb5ac`记录重映射后传给`ImageElementBase::setImage`的实际ID及该槽最后观测的model0；不解引用旧model，不更改资源。原三条MOV、BL目标`165f100`及链接返回`17eb5bc`均按字节校验/重放，生成机器码另已复核，不以自造返回值替代原调用。主机实际C helper ASan/UBSan覆盖不变性、采样额度、多槽别名、阶段有效位和errno保持。

实际`run-xev1psh5`记录67条，dial0..4为26/8/8/8/17条（两阶段共用每档32额度）。22条匹配槽1的有效setImage实参均与原资源字段相同，该槽最后观测model0数值也分别为0..4。这只排除这些样本发生ID重映射变化，不证明枚举标签/资产字形、控件可见性或最终提交正确。main核晚帧仍为请求A/S/M/AUTO显示P/A/S/M，整体false；SD读回与export相符、fsck0、owner resumed另行通过。

下一对照明确仅P/A两位置：请求A后用原MENU进入并再返回，不追加MODE请求，复核同一原dial和LCD。脚本显式报告省略其它档位的范围；不改变公开默认流程，也不增加猜测编码。此对照用于区分标签/状态解释与页面重入更新，结果需人工核图，不能提前认定修复。

该对照已实际完成于`run-4cc9be2i`。main核图：A请求后的HUD为P，进入MENU显示“程序偏移”，返回后仍P且前后RGB摘要相同。对应序号43/45/47的原dial读回均1、switch均0，所捕获输入仅两条MODE（status1、3），其后仅原MENU，不追加位置。故简单MENU重入没有消除差异，问题不只是一张旧HUD图；但仍不能据此唯一分辨标签枚举域与固件模式状态。名称数组的索引与实际枚举值也须以原索引换算/定值消费者另证，不做猜测式偏移补丁。SD独立读回与export相符、fsck0、owner resumed另行通过，总体false。

## 新证据：显式枚举声明及标签绑定复核

后续原参数名称表以ID`1c75`明确命名`shoot_mode_dial_position`，同ID描述项`5f0fa28`指向`5878b90`的16B条目，条目首字明确为数值：AUTO0、P1、A2、S3、M4、MR1=5、MR2=6、MR3=7、SCN8。P名称指针`4cf67a8`是先前VAL字符串的同一后缀存储。lookup候选`36834d8`直接以value*16+8取名，无减数。main已审读并实际执行研究员新增的verify分支，重算原AP SHA及全部三域描述/原字节成功，不把未执行的脚本当已测。PRM日志槽303与该ID及运行时注册的绑定仍保留未知，不用同名替代。

main另外核原`2d4e764`的Still分支和跳表`4b60628=2e00050709585a5c`：dial0..4直接返回exposure0..4；独立exposure参数ID`f8a`及priority域`f8b`也显式AUTO0/P1。与已人工反复看到的原LCD相符，前端`menu_live.py`按旧名称数组顺序绑定P/A/S/M/AUTO的五个status需要逐项复核：候选应为**AUTO1、P3、A5、S4、M6**，MR三项保持原值。此修订针对标签到已有合法原状态的绑定，不对所有值整体+1，不改原转换器或绘图；须封包测试及独立原LCD五档复验后才通过。

修订已落在`menu_live.py`；原字节测试改为读ID1c75描述及每条显式数值/名称，再逐项检查原wire跳表，不再用旧名字数组索引自证。`be6021548`实际61 passed、2 subtests，含封包、原字节、handoff字段宽度/ownership与SD恢复排序，另GDB导入通过。后续独立原LCD五档运行与取消对象handoff已按两轮严格串行启动`b28d8a53d`，结果仍待各自原证据核对，不将主机测试计作模式画面通过。

另修正调用角色：`1aac39c`在转换后把switch/dial交`2549bdc`检查可否变更，允许时经`1aac1b8→1ac66f0`转发；展示出的`2549bdc/2549acc`不是直接写`7ee4750`的证据。数值读回已有实际记录，最终提交与PRM类型绑定不能仅由这一校验调用闭合。

## 修订后的原 LCD 实跑

`b28d8a53d`先完成独立取消对象观测并关闭，再运行无GDB、无自动APO取消的`run-si4_cfdb`。main核对不可变原PNG与其snapshot RGB摘要、原输入日志和同序号getter：

| 请求标签 | 原status | 原dial / switch | 原LCD人工所见 |
| --- | ---: | --- | --- |
| P | 3 | 1 / 0 | P |
| A | 5 | 2 / 0 | A |
| S | 4 | 3 / 0 | S |
| M | 6 | 4 / 0 | M |
| AUTO | 1 | 0 / 0 | “自动/场景选择—智能自动”原说明页 |

![修订后五档原LCD对照；仅host拼版，单帧原PNG与摘要另保留](mode-label-fixed.png)

说明页背景是原固件资源，不是CMOS取景或生成照片。后续一次MENU关闭该说明页回到HUD，不能把脚本的`menu-after-setup`标签单独当作已打开菜单。本轮不验60秒稳定性/唤醒、MR三档、镜头/AF、曝光参数或照片录像，PRM注册绑定缺口也不由这次画面补齐。数值与五档可见语义的错位已由**前端标签绑定**修复，未换bitmap、强制重绘或改原数值转换器；原widget可见性研究不再作为这项限定修复的阻塞。

本轮原Flush/owner恢复与SD独立读回SHA256 `475d82a42c7a0ad5fcb9da387fb20c9d937a5f9219bda56cdc0fbd29ab92a492`相符，fsck0。run内`mode-label-binding-review.json`的ok=true仅对应此表范围，自动整体proof仍false。

下一项验收是实际HUD参数到原绘制/提交的消费关系；remote accessor生命周期仅是另一条尚未闭合的观察链。没有依据增加等待时间、改7025状态或重复发送位置输入来掩盖延后。照片录像及曝光完成度另行验收。
