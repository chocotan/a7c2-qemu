# 第十八跑：绑定40b8与0159的原发送失败；不批量伪造CP应答

本轮用独立追踪候选、现有生产derive和原AP实际运行，确认了两笔发送失败：`90030001/type5/40b8/12B` 的原OSAL返回 `-1020`，随后Imaging3109；BB `92840747/0159/10B` 也返回 `-1020`，随后BB949。两条都仍归调用方所有。`0118/22B` 的发送返回0，并实际进入kernel receiver的`BB_K_PANEL_PENDING generation=1 pending_mask=3 applied=0 completion=0 backend_missing=1`。因此“0118尚未到接收端”这一旧前沿已推进，但LCD/EVF应用和1118完成后端仍缺。

范围来自本轮父任务：静态/历史调查全部可见CP命令，评估最小正确批处理，并做一轮运行（失败可重试一次）。没有进一步委派，没有修改生产C/H、KO、CPIO或derive；只有本报告及独立scratch候选新增。原CP未执行，仍是direct-bootin AP及虚拟CP模型；拍摄、JPEG和写卡均未通过。

## 运行证据与因果

任务入口为 [candidate18/README](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate18/README.md)，完整返回值及原console位置在同目录`runtime-summary.json`。

唯一重试原run为`runtime/analysis/menu-runs/3c83/`。实际console关键行：

| 行 | 原观察 | 可得结论 |
| --- | --- | --- |
| 3174 | `P18_OSAL_RESULT destination=0x92840747 opcode=0x118 bytes=22 rc=0` | 原发送接受；不等于完成 |
| 3177 | `BB_K_PANEL_PENDING generation=1 selector=3 pending_mask=3 request_retained=1 applied=0 completion=0 backend_missing=1` | candidate2的0118保留接收已真实可达 |
| 3182 | `NATIVE_CP_BACKGROUND_UNHANDLED ... source=0x80020002 type=5 opcode=0x40b8 size=12 delegated=1` | background overlay未消费此消息 |
| 3184–3185 | 同tid369 `P18_OSAL_RESULT ... 40b8 ... rc=-1020 errno=1020 raw=0500b8400000000000000000` → `Imaging3109` | 40b8原发送失败与断言现已绑定 |
| 3195–3198 | `BB_K_REJECT ... command=0x159 rc=-1020`，同tid353 `P18_OSAL_RESULT ... rc=-1020 raw=0d2059010a0001800700` → `BB949` | 另一个独立未实现BB命令；不是40b8的别名 |

原AP反编译`analysis/appfw-decompile/corpus/parts/7/0x003530000.c`中VA`35358b8`的`execute_infra_cmd_i`，在`osal_snd_msg(param_1, message)`非零后报行3109；只有输出指针非空才等待future。BB949也仍是send非零，不能再解释为分配/池耗尽。

本次追踪库位于LD_PRELOAD的`file-media-config.so:menu-observe.so`之后，供observer内部`real_send_msg`继续解析到原libosal。它只在原发送前保存最多32B消息及size/source，发送后记录原rc与errno；不在转交后解引用消息、不分配OSAL消息、不free、不发送回复、不改返回值。host自检覆盖原rc=-1020、errno保持、失败消息仍活及成功callee立即free；ARM动态依赖最高GLIBC_2.17，guest传输后完整SHA读回。调试库仅写guest自己的`/tmp`，主机TMPDIR指向任务目录。

首跑`2153`在AP前被串口1000B单行守卫拒绝，原因是base64块1024B；唯一重试仅改700B块与相对任务路径。首跑和重试均原QMP唯一随机ID、quit、QEMU rc0、无信号、租约到退出、runner_closed；前者不是业务失败复现。两轮原证据均保留，不改旧收据。

## delegated=1的实际含义

`cp-background-device.c:native_cp_background_dispatch`只消费type0、24B的3007。40b8等其它命令记录`UNHANDLED`后返回0（这里0表示**本overlay未处理**），不改`*result`、消息或所有权。`menu-observe.c`继续经过后续模型，最后交给原`real_send_msg`。`delegated=1`不承诺成功、ACK或超时。

原内核全局public sender由`udate-distribution/client.c`通过`osal_reg_public(&sender_handle)`注册。它当前只路由BB目的、启用的Backup目的和UDATE目标，未支持目的直接返回`-1020`，不消费请求。最早16条`UDATE_K_UNSERVED`有日志上限；早期电源/UPM请求已用完上限，不能据40b8附近没有该日志否定这条路径。本轮从原OSAL边界实读40b8的-1020；配合源码能定位到当前未支持目的的拒绝合同，不需假设等待超时。

## 原CP的40b8合同

公开CP原件SHA256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，18,090,880B；地址是CPVA，文件偏移为VA−108000。Capstone直接从当前原件复核，完整字节保存在任务`cp-pins.json`，汇编为`cp-disassembly.txt`。

- 表项`10fb884 = {40b8,3589c9,0,0,362985}`；支持表`d939f0+(40b8−4000)*8`与既有前缀合同一致。
- handler`3589c8..3589f6`：读取`u8[request+8]`，零扩展存为`u32[P+170]`，P=165a720；可选诊断日志，返回内部1。
- checker`362984..3629ae`：模式1时比较incoming byte与`u32[P+170]`，不一致只诊断。
- 公共dispatcher`35cf70`对source80020002先checker、清记录old-state，调用handler；本记录apply-control=0，故`35d080`调用`996fec`，设置`u8[1b16058]=1`。handler的内部1不是给AP的业务ACK。
- 此支持命令的正常路径没有单独成功回复；unsupported支持项另有type1/statusf001分支，不能套作40b8成功。公共apply的后续工作包含异步状态/队列，见[既有apply合同](../cp302c-prefix-apply-preservation.md)。

可以实现一个持有参数、保留apply pending并正确消费请求的局部owner；但只存byte就报告CP apply完成不成立。当前CP cold owner并未包含同一权威参数/apply/中央sequencer历史。故本轮不把40b8及其它未知命令白名单化后统一返回0，也不伪造f000。

## 历史命令全集与最小语义

输入取六个实际console：303e、7161、3f3d、097e、2e73、bdd2。权威计数在`cp-input-census.json`，以原INPUT_AUDIT的`pid+sequence`去除重复导出，按对应BYTES拼回完整消息；是API入口次数，允许嵌套，**不是CP消费次数**。初始`historical-opcodes.json`保留原UNHANDLED文本出现次数，可能包含后续日志导出，不能拿它替代本表。UNHANDLED只观测90030001，会漏掉90040193已被其它模型拦截的命令。

P为165a720。下表计数为六份去重API记录汇总；简短handler按当前原字节复核。复杂handler只描述已核前缀及既有报告，不把窗口外逻辑记成已闭合。

| SID | opcode / 次数 | 原最小行为与缺口 |
| --- | --- | --- |
| 90030001 | 3006 / 3；3007 / 4 | type0中央控制，不属于type5配置；3007已有有限cold模型，3006不能generic ACK |
| 90030001 | 4001 / 2 | +8/+9/+a/+b写P+69c/+698/+6a0/+6a4；apply-control1 |
| 90030001 | 401c / 3 | 有符号byte+8累加P+2ec，byte+9写P+2f4；公共apply |
| 90030001 | 4022 / 8 | 多字段比较、变化计数及P+6c8/+6ac等更新；完整handler尚未关闭 |
| 90030001 | 4023 / 8 | P+688与+720更新，多门控可能发8306→中央3031；禁止空ACK |
| 90030001 | 4028 / 8 | gate允许时有符号累加P+2d8并写+2e0/+2e4/+2e6；公共apply |
| 90030001 | 402a / 5 | byte+8→u32[P+160]，apply-control1；最小纯配置候选，但目前302c observer仅记历史，不是真消费 |
| 90030001 | 4043 / 4 | byte[P+2bd]=1；公共apply |
| 90030001 | 404e / 4 | 配置gate选择P+7a7计数或内部0901发送；apply-control1不代表无异步行为 |
| 90030001 | 4051 / 4 | byte+8→u32[P+d18]；公共apply |
| 90030001 | 4070 / 4 | 提交50ff1c callback，能异步向AP发1010；公共apply |
| 90030001 | 4077 / 1 | P+d38赋值、50ff1c异步callback、b1f2b0结果写186fc08；公共apply |
| 90030001 | 4084 / 16 | byte+8→byte[P+337]；公共apply |
| 90030001 | 409c / 4 | byte[P+b52]自增；公共apply |
| 90030001 | 40af / 5 | byte+8→u32[P+164]；公共apply |
| 90030001 | 40b8 / 7 | byte+8→u32[P+170]；公共apply；本轮准确失败包 |
| 90030001 | 40c5 / 4 | byte+8→u32[P+3a4]；公共apply |
| 90030001 | 40d1 / 4 | byte+8→u32[P+d14]；公共apply |
| 90030001 | 40ed / 4 | byte+8布尔化→byte[P+bb2]；公共apply |
| 90030001 | 40fb / 8 | byte+8→u32[P+af0]；公共apply |
| 90030001 | 4102 / 4 | byte+8→u32[P+bec]（eye AF参数）；公共apply |
| 90030001 | 4139 / 4 | 复制176B到P+870，置byte[P+86f]=1；下游consumer缺；apply-control1 |
| 90030001 | 4177 / 4 | byte+8→u32[P+1c4]；公共apply |
| 90040193 | 4037 / 24 | still_unlock单向控制；现有imaging-device限定selector/无capture子集、修改仲裁并发内部focus controls，不回AP成功包 |
| 90040193 | 4039 / 6 | set_capture_end，属于释放生命周期；本轮未闭合原CP完整完成/所有权合同，禁止空ACK |
| 90040193 | 403d / 41 | release-inhibit，原12B type1回复回显token/statusf000；活动release时须延期；现有有限模型已实现无活动子集 |
| 90040193 | 40a5 / 1 | release-key spinal setting；不在上述350项参数表，本轮未关闭其专用receiver，禁止并入参数类 |

`additional-pins.json`另核4001表及handler；4037/4039/403d/40a5不在这张表，不能用查不到表项推断它们不存在。4037子集见`imaging-device.c`及测试；4039/40a5命名来源见[AF前沿](../af-request-completion-frontier.md)。本轮没有声称这两项专用CP handler已完整逆向。

## 批处理选择与下一步

**源语义实现（建议产品路径）**：在一个CP参数owner保存准确字段、输入来源/尺寸/顺序和apply dirty状态。首批可为40b8/40af/4084/40fb及402a，但前四项须接公共apply后端或明确pending且不让后续依赖把它当完成。复用现有full_imaging_io的分配/释放/返回合同，成功queue接受才转移所有权，失败保持caller owned。需要接cp302c历史observer的唯一状态源，避免一边消费一边仍标unknown或用cold0覆盖真实历史。工作量是参数接收+apply工作闭环+所有权/并发/负例测试+guest重建/derive/运行，不能降为5行switch。

**显式diagnostic opt-in**：可在独立实验profile接受严格命令并记`diagnostic=1 config_applied=0 completion=0 capture_verified=0`，只验证后续控制路径；禁止给完成型命令造ACK、禁止计入shooting ready/JPEG_ONLY_PASS。实现短，但会改变历史/错误路径并掩盖关键apply依赖，不能作为默认产品修复。本轮选择更小且无语义改变的trace，而非先放宽后补合同。

现在应同时处理两处精确前沿：CP40b8参数/apply owner，以及BB0159 receiver合同（固定原输入10B、source81cf61c6、payload0700）；随后再跑，不能仅凭40b8不再断言宣布BB949修复。0118已经真实保留，下一独立门为LCD/EVF应用、读回及1118投递/AP释放，不能随手补完成。

## Evidence → Finding → Path

| Evidence | Finding | 下一闭合路径 |
| --- | --- | --- |
| 3c83原console3182–3185，独立原rc追踪+AP原send分支 | 40b8的确原send=-1020→3109，高置信 | 准确参数接收/所有权→apply后端→重跑 |
| 3c83原console3195–3198，kernel BB_K_REJECT与原rc | BB0159独立拒绝→949，高置信 | 0159原CP合同→BB receiver→重跑 |
| 3c83原console3174/3177 | 0118接收已到pending，applied/completion均0 | 实际LCD/EVF后端→1118→AP d1/free |
| 当前CP完整SHA、cp-pins原字节与350项表 | 40b8是参数写+公共apply，非独立ACK | 同一参数/apply/中央history owner |
| 六console的pid/sequence/完整BODY审计 | 覆盖全部可见28种目的/类型/opcode组合；文本UNHANDLED非全集 | 按receiver分类逐项闭合，未知仍拒绝 |
| 两轮consumer/attempt/result及原QMP随机ID入口 | 两轮quit+rc0、无信号、租约到退出；生产源稳定 | 保留原证据供父会话核收 |

## 资源、恢复与限制

没有生产语义改动，停止使用额外trace即恢复原运行组合；当前产品及生产derive保持原身份，无需恢复写入。首轮失败与重试均自然关闭，无活QEMU/租约/socket；精确核收见任务`finalize.json`。任务目录与两个原run的初步实占约35.8MB，实际回收0B；精确字节、全文件SHA及项目盘可用字节见任务`storage.json`，封账脚本自身和报告均一并读回。原证据、候选源码和自检保留给父会话复核，回收条件是核收后替代消费者接管并通过身份/引用审计；未执行回收。

本轮适用ponytail、ida-reverse和docs-generator，普通固件逆向flavor=null。技能相邻tool-index不存在，复用了实际可用的Capstone、当前CP原件、现有AP corpus和实际产品入口，未启动或争用外部IDA。未执行真实CP固件、Sony loader/WBI、SD更新、真实设备或完整拍摄链，也未把诊断trace通过记成业务通过。
