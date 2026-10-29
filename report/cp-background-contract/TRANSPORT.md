# 实验性3007原消息链接入

状态：host-only门控已过；首轮私有run-4d24ai94实际未启用服务（见下文失败记录），不算本版本原guest成功回复/恢复。默认关闭；不能将内部控制结束值、send返回值或本页测试当作拍摄ready。

## 原AP所有权依据

main另核原`libObj.so` SHA256 `c0897d72a40bf0a161fa7f89e9a34eef4d19e0506c7817a5c11a6f53897cdbbc`，ELF VA ed9c4开始的实际调用与PLT符号：

- ed9ec以type2a/owner102建dynamic queue；eda24以destination90030001、24B、count1调用`osal_valloc_msg_wait`，**原request属于CP目的池**。
- eda34给request设置该dynamic source，eda44只写u8 type0，eda48写u16 command；eda4c异步发送，返回0后进入动态队列接收等待。成功路径没有再free原request。
- edaec用dynamic queue ID调用`osal_free_msg`释放收到的独立reply。

因此实验服务不能混用两池：成功接受后free原request用90030001，reply用实际dynamic source分配/发送/释放；echo的是原opaque，不是伪造消息token。原helper未初始化byte1及+8..23，不能假定总零。main核原CP3abb0a的u8 type读取、3ae09e的3007 TBH目标4b6120及其直达common event构造：本命令只取opaque/source，未消费这些保留字节。当前实验profile限定24B/type0/3007，**忽略原来未消费的保留字节**，不因栈残留拒绝合法请求；其它命令/类型不属于此overlay，保持原传输所有权与返回语义，不宣称它们已建模。

## 当前实现

`device-models/cp-background-device.c/.h`连接有限cold引擎与原OSAL IO回调，按实际控制boundary/path结束后才构造独立12B reply。**只拦截type0/3007**，不替换SID90030001上其它通道；未覆盖的命令/类型返回unhandled交由原传输决定结果，既不新增成功返回，也不消费其packet或宣称其硬件副作用。已识别3007的坏长度/source仍拒绝。已知未完成模块仍pending，不回填observed；状态日志注明`hardware_ready=0`。

- 不持有model mutex等待pool allocation，也不持锁调用send；AP可在send返回前同步free reply。
- 原地址一旦释放就从lease指针索引清除，但保留ticket到send结算，避免同址复用误接。错误free ID拒绝；真实release失败保留lease可重试。
- send失败只释放尚未早free的独立reply，原request仍caller-owned；锁存fault，不把失败转成成功。send成功后才free原request，free失败如实记账，不用错误返回值误导caller重复释放。
- 分配失败/lease容量满/坏envelope不会消费原request。首次入口在获取mutex之前原子登记并校验PID，连初始化中途fork也会拒绝继承状态。有限资源bank必须共享，不能为了idle临时换一个空bank。
- 成功接受后的原request若free失败，保留其指针/所有权并输出地址；free hook仅允许匹配CP owner的重试。不会把该失败丢成无人记账的请求，也不会把fault后的新请求当作清理成功。

原完成observer副作用仍在独立核绑定，**未以未知callback为no-op做原guest成功验收**。模式/冷前提、exec-handle/observer与真实queue/free的接入验收必须继续保留。

## 开关与资产边界

SDK/GTK入口使用`A7C2_CP_BACKGROUND=virtual-mode3-cold-v1`实验opt-in，只允许自然启动profile。`start-menu.profile_environment`显式映射为guest的`MENU_CP_BACKGROUND`，仍过滤任意继承的MENU研究开关；低层probe也支持直接设置MENU值。要求initramfs+observe，拒绝实验send-GOT hooks并用。`qemu-menu-probe.py`对**最终选中的newc**核原CP摘要，唯一普通文件/路径/ancestor/hardlink等复用`initramfs_identity.verify_image`，所以派生overlay也必须保持模型支持的CP字节。其它文件仍按既有任意安全相对路径overlay，不建立文件名或GUI类型白名单。manifest区分CP实现mode3与请求完成mode0，并记录未选模块未完成、hardware_ready=false；私有driver在输入前要求实际manifest profile与请求匹配。

`menu-observe.c`已加dispatch/free hook；`build-observers.sh`将三个新C模块一起编入本地source archive/observer。默认未设置开关的行为不启用该服务。完整新observer编译及相关门控按对应版本输出记录，不能把早期独立.so crosslink等同于本次完整构建。

## 验证范围

### 原guest有限控制消费通过，整体恢复未通过

`b7529bed0/run-dx52p7qy`实际manifest准入且原CP摘要相符；source gate38/19和完整observer编译通过。原请求tid275/source810261c7，native ticket1执行3组控制路径。成功入原动态queue后，原request以CP pool90030001释放rc0；AP原helper在libObj+edabc读取reply状态后，经原free调用edaec返回地址**edaf0**释放独立reply，rc0。main用同run RX base7fa0024000核caller7fa0111af0→edaf0；free前实际12B为`010007300000000000f00000`，不是仅凭send0或创建对象推成功。早先阻塞的3007已越过，后续原thread340发出了40d1等新控制。

这只通过3007控制消费/所有权。60秒后LCD仍黑，原APO1 factor8也实际捕获；StillCa initial_arrived/predicate仍0。晚期实际wire出现3006/source810261c4，CameraBackground栈为eda8c←ee6fc←ee82c。main起初仅看紧邻的ee6f0 MOV301c未能归属，随后闭合真实共享尾：上游type12/wordC42→ee5f4比较42→ee600 MOVw1,3006→ee608跳ee6f4，**绕过**ee6f0→ee6f8调用ed9c4→returnee6fc，wire/栈一致。这是下一真实3006等待，不是libObj版本或栈损坏。只读ptrace采样仍有一般侵入性限制，且Common340两次无REGS，不能说它已空闲或退出；后继命令/初始输入/省电恢复继续调查，不套3007回复。

SD main独立hash=`3dbdaf0bcc1f4e5f634f43ec85bea5c94fe426a6812df3837b48a02addc165ff`，匹配export、fsck0、owner resumed。原driver整体ok=false保留；run内`cp-background-consumer-review.json`的ok=true严格仅限本段消费/释放范围。没有真实照片/录像或CMOS/AF完成声明。

`b9228898b`的5项pytest、15项子测试通过：实际C ASan/UBSan覆盖正常队列、send内同步free、立即同址复用、分配/发送失败、原request及reply free失败/重试、错误ID、8lease容量、真实DEV backing占用、坏形状/disabled/fork；另含资源/cold引擎及源码快照回归。测试版本transport C SHA256 `472c6b8b5451f24ec7d8f793db190ab8b6b81b6c134d1bc57c33439a9e560be6`。

完整整合构建`b36a28946`通过38项host/17 subtests及同步检查，但独立评审随后找到首次`owner_pid=0`且mutex已锁的fork窗口，旧通过没有覆盖它。修订为加锁前原子claim PID，并用链接器包装真实pthread lock，在首次锁已持有时精确fork；子进程须直接拒绝、不能等继承锁。`b116b3696`通过38项host/18 subtests（transport自身新增第16个case）及完整observer原ABI重编译，源码前后绑定一致；C SHA256 `b30dcb1f2765e2b2a3ea64fe3999235c78210854b626cd9ffd84c9eb995e7d3d`。该版本也覆盖accepted-request释放失败的保留、错误owner拒绝、正确owner重试。旧warning按原文件保留，不当作构建失败或已修项。

main另只读核当前551686144B基础newc：唯一普通CP条目的摘要与支持原件相符；最终实验启动仍重新核**实际选择的**newc，不能用基础cpio检查代替派生镜像。迄今没有本服务的原guest queue/free或LCD恢复通过证据。

### 首轮实际入场失败（不算新服务验收）

`b5a0f914b/run-4d24ai94`的host gate 5/16和编译通过，真实中文首设/初始MENU可见；但runtime manifest的`cp_background_profile/asset_identity/model_mode`均null，console无任何`NATIVE_CP_BACKGROUND`事件。原因是实验只在外层传MENU值，被SDK正常隔离过滤。60秒后三张原LCD均黑；这不能证明新backend失败或成功，也没有本轮power-factor证据（passive power开关未传）。源冻结/原始结果保留，不回填。

本轮实际3007为`00c107307f000000201e172e7f000000c361918000000000`，保留字节并非全零；旧parser的零尾条件即使启用也会错误拒绝它。新增C regression使用此原始24B形状，要求消费控制流程、回显opaque7f、正确移交/释放reply；没有把保留字段变成业务参数。

SD全图main独立重hash=`d4385a992a5321c464c81688bf1e2925badf880200c7a9488be53438ce347edc`，匹配export、fsck0、owner resumed，仅限存储收尾通过。run内`cp-background-admission-review.json`记录否定结论。新一轮以显式A7C2映射、SDK实际profile门控及被动power观察重验，不沿用首轮exit0称恢复。

### 第二轮启动期abort（范围错误已定位）

`b06c51cc1/run-jju6sg4f`实际manifest已准入profile且CP摘要相符；host隔离/38项测试/18 subtests及编译通过，guest却在settle触发SIGABRT，未到3007。最后CP输入为DispSwi356的type5/40b8。main由保存的FP链定位到原`CamUserIf3535a64`发送结果非零分支→`35aa4b4`→libc abort；原字符串为`false`、`lib_assert.cpp:46`、`notify_model_system_error()`。新服务的SID级拒绝把不属于3007控制范围的type5变成了-1021。

修订为命令级overlay：17个C lifetime case中加入真实type5/40b8的**unhandled且result不被写**回归，保证不接收、不free、不发reply，由原传输保持其既有语义。未知通道仍未模拟，不将原传输返回值当新模型成功。记录器还漏将新prefix镜像stderr（与内存/file记录不同）；现补`NATIVE_CP_BACKGROUND_`，避免把console无tag误判为没执行。该轮无SD导出/owner恢复证据，不假称干净；原exception/stack/manifest及run内crash-review保留。

```sh
cd runtime/analysis
python3 -m pytest test_cp_background_device.py test_cp_sync_resources.py -q
```

mock IO只证明C的数据与所有权，不证明原kernel队列已消费、source池确已释放、boot已返回或原LCD恢复；这些须在单一私有QEMU继续取证。没有照片/录像或完整镜头/CMOS/AF验收。
