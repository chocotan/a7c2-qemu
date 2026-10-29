# 4000 set_movie_format：单独的有限诊断阶段

`run-a547uk6q` 的原AP消费409d后，实际并未直接执行4072：worker378先同步发送4000/20 B，并停在该等待。原请求为 `0500004027000080050100000000000000000100`，source80020002、destination90030001。保存栈含完整请求、appFw3535b04/3546014/34cba34/3389214/338ea00和futex98；它是等待强候选，未冒称正式unwind。

公开CP SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，18,090,880 B；CP地址仅映射范围用VA=raw+108000。公开appFw SHA-256 `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。

## 源码合同

AP3545ab8明确名为set_movie_format；3546010调用共享helper，参数20 B请求、匹配opcode4000、复制12 B回复。3546014只把reply.u32(+8)与f000比较。线上cookie.u32(+4)是opaque80000027，不等于OSAL source；仍必须准确回显。

CP参数表10fab8c第一项20 B为 `{4000,35421d,0,0,35d0e5}`；type5 dispatcher35cf70执行checker35d0e4和handler35421c。support行d939f0为enable1/logging1。实际请求转换为内部rate0，矩阵f812dc+5×7+0原值为1；这只核可接受输入分支，未证明格式完成。

| wire偏移 | 宽度 | 本次值 | 诊断审计槽 |
|---:|---:|---:|---:|
| 8 | u8格式码 | 5 | 0 |
| 9 | u8原rate_a | 1 | 1 |
| 10 | u8原rate_b | 0 | 2 |
| 12 | LE32条件字段 | 0 | 3 |
| 16 | u8格式相关输入 | 0 | 4 |
| 17 | u8条件输入 | 0 | 5 |
| 18 | u8条件输入 | 1 | 6 |

不能用连续复制byte8起四字节来代表这些字段。byte11/19在所核handler不消费，但保留在完整20 B wire/hash中。原u32(+12)非零才更新165a750；本次是0，故审计该输入不等同写入原条件状态。七字段mask7f只证明拷贝/读回，不证明内部转换或业务应用。

35421c→35448c把opcode/cookie/真实source/callback354551存pending165b498；8dad54移到active165b488。8db16a调用354550，必须满足原状态条件才写f000/返回12：

```text
R = b2ddb4(); P = u32[R+c]; Q = u32[R+4]
u8[P+942] != 0
u32[Q+14] == u32[P+3b4]
u8[Q+11] == u8[P+3b0]
u32[P+c0] == u32[P+3cc]
```

这些条件目前未执行/未闭合。诊断profile仅提供独立12 B控制回复 `010000402700008000f00000`，并明确success byte1原来未赋值、virtual0/source_byte1_known0。原立即拒绝f001分支的byte1确为0，但不能把失败包的初始化证据借给成功包。

## 实现和门禁

新profile精确值 `diagnostic-cp-movie-format-v1` 复用A7C2_CP_CAPTURE_FORMAT/MENU_CP_CAPTURE_FORMAT，默认关闭。旧EE profile不增加4000白名单。新owner位于 `runtime/analysis/device-models/cp-movie-format-diagnostic.{c,h}`，只接本次已知12 B body `050100000000000000000100`，允许cookie准确回显；其它尺寸/type/source/body拒绝且不取所有权。

构造顺序为402d→startup控制→EE控制→movie owner。movie初始化失败同时禁用本profile的EE控制，不能绕过4000进入4072。movie前驱必须同PID、旧cohort实际完成、409d独立回复由自己的原sender释放，且当前4000 sender与409d一致。后续4072/3012另用after-movie guard，必须等4000原AP实际free成功、七字段mask/读回一致；每个已完成回复保留自己的sender=waiter校验，未要求所有阶段共用一个线程。

原续接源路线已核为：338e9f4执行409d；338e9fc→338866c内部执行4000；338ea3c执行4072单向；338ea5c执行3003。没有在该函数尾部发现其它本次必走同步控制；不把代码相邻3000/3001/3030错误标为下一实际请求。

3000/3003都含四个状态数据字节；3030含源status/data，另有明确status6路径；3001最终回复未闭合。它们都不进入这个诊断owner，不发泛化ACK或填零数据。

## 自测与验收界线

本owner的50个C场景在严格C11/ASan/UBSan下通过；与旧控制/真实Ctor/前后门禁、光学JPEG和新SOS后段适配联合104项通过。完整2514项/304子测试/363冻结源与原ABI通过，observer为54008e413435a7d5f85e6fc8b009c2088fa85db52c8df522cb2ad7359c376d8b。

`run-nzx01uc3` 实际由原AP258/TID378释放4000独立12 B回复，rc0/fault0/ap1，七字段5,1,0,0,0,0,1和mask7f一致。随后4072单向原requestfree0、mask3读回、reply/ACK=none，再发3003/24 B；保存栈与futex98指向该数据等待。EE0/无JPEG请求或媒体产物；SD双原flush0/三文件SHA/owner组退出/双锁/GDB detach通过。收据 `runtime/analysis/menu-runs/run-nzx01uc3/cp-movie-format-native-evaluation.json` SHA-256 `9915c5e6dcf5b6004f2bcfc0f8a9d9b415812de8f345a3cff4d1b5fba428719e`。

Evidence E4000来自上述完整原包、保存栈和源合同；Finding F-step为409d与4072之间需要独立4000完成；Path P-mode为原AP请求→有限七字段审计→诊断12 B回复→原sender真实free→4072单向消费→3003真实数据边界。格式业务应用、CP current/dependencies、generation/published/native/EE/frame/capture均不提升；`capture_verified=false`。
