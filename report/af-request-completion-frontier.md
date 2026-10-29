# AF正反向调查：半按分派入口已定位，完成链未闭合

原run-3s6hb0e1只证明P场景的半按/AF-ON各1/0被原App32 thread302收到。
HUD变化不等合焦，未取得独立镜头动作、AF结果或AE完成证据。

两位代理独立查请求与完成。反向侧仅核身份/旧文档，没有找到normal AF
notification、结果字段、有效条件或AP modelconsumer，未交付新原字节。
Main已保存未完成记录，不把它描述成“完成通知从未收到”——通知身份与
观测覆盖本身都未知，无法据缺日志下这样的否定结论。

请求侧用本机Kuna找到半按候选入口1ad9c0c和8项member表，main核原
AP99960744B/SHA2562ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b：

- 1ad9c0c先把事件参数交1ac2748，将返回索引乘16取成员函数/adjustor，
  保留原message，执行真实间接tailcall。它不是已证直接AF调用。
- 1ac2748解析事件高byte和low12bits；两个family经过原表转换，其它
  直接使用low12bits。该函数没有独立证明自定义设置绑定；初稿将其称
  runtime binding-selected已纠正。actualevent→index→selectedmember仍需关联。
- candidate1b3a818含真实gate、25bf840 modelAPI调用及2060000事件比较。
  这是后续窄入口，不证明该run实际选择此member或已有AF wire。

原CPae1642片段属于既有403d releasehandler调查，不能升级为AF请求合同。
其ae16e4原常量40000000与模型保留的04000000不是同一mask，初稿混称
power-on inhibit已纠正；不修改原mask，也不生成新的ready/focus-success。
source80020002的reply门槛及该handler的maintenance仅证明局部控制行为，
不证明正常AF完成。

## 后续同题独立核验：属性调用不等于AF wire

新一轮两位代理回答同一候选问题，不互读或互补分工。第一位仅复核旧原件
和两个已有窗口后因工具入口问题结束，未落报告，main已保存诚实handoff。
工具没有自动建立1b3a818函数索引不证明入口不存在，也不妨碍直接原字节核验。

main独立核25bf840/208B窗口（其首函数止于25bf8b8），SHA256
7d487810b32ad68c4c609c48d235798907a83300b752943df57e0129b281bdaf。
该函数以内部ID48fe经过368312c/36eb21c/36eb3f0/3683218，调用25bf6ac。
后者400B原窗口SHA256
f752b18d787b9136323d13417f44de3acf46c9d4005a334f20468b4606edc4b2，
可见28a06b4读取、表48b180c分支及344a属性长度4/value1的处理分支。
未闭合该属性的下游observer到真实AF消息的边，不能据函数名或ID构造AF服务。

已有288B member窗口只是前缀，后续仍有分支；未证明整个member没有AF发送。
没有取得真实cmd/source/destination/token/free合同或合焦结果。另一位同题
调查随后已交付并经主会话核验：原字符串ELFVA48c69c0/63B确为
set_cursor_off_in_home_screen()，SHA256
b237a6ff7bdfe2b5ae367100960d38bd2ddccb7c050a68655022ce4962655274。
因此该具体调用不能作为半按AF请求。两位均已结束，不再描述为运行中。

main还核1b3aa80→1aec444保留原msg，后者按msg+8分派；02060000分支
在1aecfc0构造010001c3，再进入1aec894带状态条件的公共转发尾。
这是具体输入事件转换边，尚未证明本轮实际半按选择此member，也没有
闭合真实镜头AF消息或正常完成。后续只沿此精确转发和实际输入关联推进，
不重查光标关闭包装器，不把模型属性或内部事件直接命名为AFwire。

仍缺：实际AF请求cmd/source/token/ownerfree与normal AF结果producer、
数据字段/有效性及对应APconsumer之间的关联。不存在可据此实现空AFbackend
的合同。两份原调查和main逐字节勘误保留在scratch/native-af-request-kimi/
及scratch/native-af-completion-deepseek/，本项暂存而不继续宽泛搜8个候选。

## 40xx候选全部证伪非AF，真AF驱动改道（main已核代理取证，本轮）

代理（kimi，`scratch/af-handler-identify-kimi/`）把此前缩到的8个40xx候选逐一证伪——每个经AP producer自身assert路径的函数名字符串（`infra_wrapper_imaging::detail::*`）直接命名，main已核全部字符串存在于appFw.so：

- **4036**(ae18f2)=`set_still_lock`(@0x4c7e444)——S1半按锁定（event 0x17d路径，caller 0x34d1508）；最接近AF但是**锁定命令**非对焦驱动
- **4039**(458d68)=`set_capture_end`(@0x4c7e574)
- **403e/403f**(4585e8/4587c0)=`set_focus_magnification_mode`(@0x4c06549)——MF辅助放大，非AF驱动
- **406a/40a5/40de**=`set_release_key_spinal_setting`(@0x4c04937)——释放键子参数（CP侧40de委派4036/4038）
- **4074**(ae1fde)=CapIdTblMgr SetMprInitEnd（0xdeadbeaf启动记账，无AP消息producer）

**关键新方向**：专用AF API在40xx族之外——`infra_wrapper_imaging::detail::set_focus_drive`(@0x4c0669a，main已核)，另有`set_eye_af_mode`(@0x4c05c7f)、`register_cb_af_lock_status`(@0x4c7fbec)。**真AF对焦驱动请求几乎肯定经`set_focus_drive`在不同SID下发出**——那是AF合同的下一个定点目标。

**判定**：若"AF请求"=半按锁定，则**4036@ae18f2**是答案；若=镜头对焦马达驱动，则8候选无一符合。置信度：8个排除全高（函数名字符串+CP handler行为双重证据）。未做：set_focus_drive函数体与其cmd/SID定位（turn上限）；still_lock_comp异步notify仅字符串确认未追。这是**方向性否定+重定向**，不冒充AF合同已闭合。

## AF对焦驱动请求已PINNED（main已核代理取证，本轮，实质进展）

代理（deepseek，`scratch/af-focus-drive-deepseek/`）定位`set_focus_drive`实现，main独立复核AP原字节（ARM64，file=VA）确认全部属实：

- **`set_focus_drive` impl = 0x3539574**（assert字符串0x4c7e680命名；main已核函数体0x3539574起）。
- **cmd = 0x4020，SID = 0x90030001**，12字节type-5消息，**fire-and-forget**（api_id=0，out=NULL）。main已核消息构建：`0x353958c mov w1,#5`/`strb[x29,#0x40]`=type5；`0x353959c mov w1,#0x4020`/`strh[x29,#0x42]`=cmd；`+4`=in_t[0]（ldr[x0]）；`+8`=in_t[8]；`+9`=mode（in_t[4]==0?2:1）；`+0xa`=1；`+0xb`=0。发送点0x3539694 `bl 0x35358b8`（`execute_infra_cmd_i`，main已核size=0xc、SID movk w0,#0x9003、x4=x5=0）。
- **0x4020不在8个证伪的40xx候选中，SID 0x90030001≠0x90040193**——印证重定向假设。
- **`set_eye_af_mode` = 0x353f04c**，同SID 0x90030001，**cmd = 0x4102**，12B。
- **`register_cb_af_lock_status` = 0x352dfa4**：把delegate存到全局`0x9116670`（.bss），无cmd/SID——**AF完成是回调**（合焦状态经注册回调送达，非同步回复）。

**对虚拟模型的意义**：AF对焦驱动请求 = 向SID 0x90030001发12字节type-5消息、cmd 0x4020（fire-and-forget）；合焦状态经`register_cb_af_lock_status`注册的回调异步返回。虚拟镜头/对焦模型需：接收0x4020驱动命令、按mode执行对焦、经回调上报合焦状态。

**未闭合（诚实）**：读0x9116670的invoke点与**合焦状态值域**（focused/failed/searching的具体数值）未钉（turn上限）；set_focus_hold_mode/set_movie_af_refocus_point函数体与AF触发上游事件绑定未做；**0x4020/0x90030001仅从静态字节读取，无运行时确认半按时此路径真实触发**。这是AF驱动**请求侧已PINNED**、完成侧（回调状态值域）未闭合的部分进展。

## AF完成侧（合焦回调）已PINNED——双向闭合（main已核代理取证，本轮）

代理（kimi，`scratch/af-lock-status-kimi/`）钉完成侧，main独立复核AP原字节（ARM64）确认全部属实：

- **invoke点 0x3532960**（main已核：`ldr x0,[x0,#0x670]`取delegate、cbz、`ldr x1,[x0]`取vtable、`ldr x2,[x1]`取vtable[0]、`mov x1,x20`、`blr x2`）。全AP仅3处访问0x9116670：register(0x352dfc8)/unregister(0x352e0a4)/invoke(0x3532960)。
- **签名** `vfunc(delegate* this, const int* status)`——status是4字节堆int，存**入站notify消息+8的u8零扩展**。
- **完成源**：接收循环 0x35314fc `osal_rcv_msg(0x80020002,…)`，接受sender SID **0x90030001**（与0x4020驱动命令同SID），按cmd@msg+2派发——**cmd 0x2004**（main已核`0x3531684 mov w0,#0x2004; cmp; b.eq 0x3532938`）即af_lock_status notify。即**CP→AP异步notify，cmd 0x2004，状态字节在+8**。
- **状态值域**：枚举名经反射字符串钉（main已核全在）：`AF_LOCKSTATE_{CLEAR,CMP,ALERT,UNFOCUSING,FOCUSING}`——**CMP=合焦锁定、ALERT=失败、FOCUSING/UNFOCUSING=搜索中**。**数值映射未钉**（AP分支只转发字节，sequential 0-4仅推断）；缺反射值表xref或CP侧0x2004 producer常量（下一步）。

**AF合同至此双向闭合**：请求=`set_focus_drive`发cmd 0x4020到SID 0x90030001（fire-and-forget）；完成=CP经cmd 0x2004异步notify（同SID）把状态字节(+8)送到`register_cb_af_lock_status`注册的回调（vtable[0]，签名vfunc(this,const int*)）。**对虚拟对焦模型的意义**：收0x4020驱动命令→按mode对焦→经cmd 0x2004在SID 0x90030001上发状态字节（值域AF_LOCKSTATE_*，数值映射待钉）上报合焦/失败/搜索。仍无运行时确认（静态字节证据）。
