# 实际dialog262的模型与自然Mount错误路径

补充纠正：下文早期“RM查询”标签的服务80cf016d已查明为原MediaConfig配置表查询，
valid byte不代表卡状态；实际字段、消息类型4完成包及错误转换表见`CONFIG-QUERY.md`。

当前实际dialog索引262、文本资源0200a73b已动态核实。
这份记录闭合模型名称与原writer的静态链，实际失败的服务返回码仍待本轮捕获。
appFw地址均为ELF VA，原SHA256为2ea02f7e…539b；不从文字推测错误域。

## 必要模型输入

| 模型 | ID | getter | 数据地址 | 本轮实际值 |
|---|---|---|---|---|
| media_mount_state_slot1 | ed1 | 28787f0 | B+7e80dd0 | 2 |
| media_error_slot1 | edd | 28789d0 | B+7e80f50 | 1 |

主会话独立核完整predicate187f8dc：先比较mount state2，再比较media error1，
之后还有显示/模式抑制条件。因此两值是必要条件，不是完整充分条件。
getter28789d0虽然也用于另一个module233，但这里确实是262自身的第二项，不应再当作无关候选。

原metadata基址502ba98、stride10h，ID记录为{type,ID,name_length,name_offset}，字符串池5063468。
ed1/edd记录503a7a8/503a868指向原字符串507faab/507fc11。
主会话直接按同原ELF读出两项名称，并交叉核自然错误字段：
**media_mount_error_slot1/slot2=1cf3/1cf4**，getters288df68/288df90，数据B+7ee5fa0/B+7ee5fb8。

## 原writer与阶段值2

原`sequence_media_mount::exec_mount`入口337ac38，名字由原日志字符串4c31e70确认。
处理slot0时337b064..b0ac提交mount_state1；正常尾段或错误尾段都可在3380cec后提交2，
实际helper33794a4写值。因此mount_state2不能称为mount成功。

3380f40读取局部错误标志FP+94，非零时提交media_error_slot1=1，零时提交0。
原run3381eb8在exec_mount返回后仍会发01000146完成事件；这也不证明成功。

## 错误来源分层

```text
337af74 → 34d30c8 → 35513c0(Mount)
                       ├─ 本地media注册查不到：直接模型错误1d
                       └─ 35505e0 → 同步服务00b08170
                                      └─ 原buffer+0c service error
                       → 354fbf8映射模型错误 → 337af78读取
                       → 25a9844 → 25a96f8保存media_mount_error_slot1
```

主会话独立反汇编35513c0、35505e0、3599c6c：原请求逻辑头1000/cmd2/flags1/len10h，
media_id@+8、service error@+c；实际sync_call使用40B OSAL buffer。
本轮没有新增替代服务，只包装原osal_snd_sync_msg前后观察，原函数始终被调用。

服务原值0/10映射0/26并继续GetStatus，8映射24走Locked，7/13映射23/29走Unsupported；
通用失败可保留FP+94=1。1..6/9/11/12及其它未列值有通用错误路径，
不能从最终2/1倒推具体错误码，更不能把MediaMount错误等同后续Fsys_Mount失败。
后者另有模型media_filesystem_mount_state_slot1（f06），与这里是不同层。

## 当前最小观测

- 在原sync服务00b08170入口/返回记录command/media/status和transport rc、原buffer完整字节。
- 不改变返回值或请求，不生成ACK；transport rc与buffer service error分别记录。
- 只读自然media_mount_error_slot1/2，尤其检查本地1d与实际服务返回的区别。
- 保持无MENU、boot type1/dmode3，未清media_error，也未挂占位SD。

原provider `libInfraMediaMount.so` SHA256=
90571d016f5f80b4c8cb4d9ff80c7600d19e0199a1ab7cfa6e9ee5d79587f612，
公开符号`InfraMediaMountThread::Mount`位于该库ELF9bd8。
Kuna正恢复device-open/getinfo错误转换，便于解释实际RPC结果；不提前判定缺文件或坏FAT。

## 首次动态采集与同步阶段边界

`run-vzk9iksr`已读到自然`media_mount_error_slot1=2a`、slot2=0，
state/error两个必要输入仍为2/1。原tid332向00b08170发送GetInfo(cmd1,48B)和Mount(cmd2,40B)，
同步返回rc0、当时buffer+c也是0。**这不是最终Mount成功**。

主会话复核原35505e0、3599f3c和callback355014c：初始同步请求之后，原调用者还从动态私有队列
等待另一份完成消息并复制回同一逻辑buffer，最终原错误才在3551440被读取/转换。
因此首次sync wrapper只覆盖接受阶段，不能把其0与后续model2a拼成“模型写错”结论。
2a是354fbf8映射的未单列值分支，仍需采原最终service值。

另已独立核原provider676B函数：在实际`mcmn_drv_open`之前，Mount会经
原`MWF::EventWrapper::SendAndRecv`向**80cf016d**发228B查询。
logical header为1000/3/cc，media_id在+18h；返回0后还检查+1ch有效位并拷贝+20h设备名，
再到9d14调用mcmn_drv_open，之后才getinfo/setpower。
因此这条RM查询也是可能的先行失败处，不能直接归因于设备open或FAT。

新增观察：原异步send/free时保存对应最终消息字节，以及原MWF查询方法入口/返回。
MWF wrapper只转发原方法；ASan/UBSan host fixture证明参数/数据/返回值/errno透明，
短buffer和关闭开关时不越界或额外记录。新的原provider二库selected-cpio身份检查亦已接入。
最终消息及RM结果动态采集仍在运行，见`media-mount-first-capture.json`保留首轮边界。
