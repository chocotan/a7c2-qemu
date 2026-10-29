# OSD pin 130：原契约与有限模型

当前主界面仍未恢复。此模型仅服务观察到的Get `{1,3,0}`，独立保存cold pin metadata；
不宣称原CP任务、图形内部事件、OSD资源初始化、连接或像素消费已经完成。
范围为本机隔离QEMU，固件只读，不涉及真机、物理SD或磁盘直通。

## 证据与结论

CP样本为`analysis/system/cpapp-b.bin`，SHA256
`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。
下表CP代码地址全部是raw offset，CPVA=raw+`0x108000`；RAM地址明确标记CPVA。

| 证据 | 结论 | 实现/验收路径 |
|---|---|---|
| 原RTTI raw`be3b00`；初始化`469a68`、pin ctor`469b06→583582` | owner=`cpgrm::fbm::osdpinif::OsdPinIF`，单独一个pin `{1,3,0,9080003b}`；cold state1/peerff | `osdpin-registry.c`独立owner，不能与PinMem同键对象混用 |
| Get raw`46a840`；`46a85c..a870`构造封套 | 源SID和回复外层SID均9080003b，OSAL目的取原外层动态replySID | 56B回复、自SID封套；原线程pointer/lease/free验收 |
| raw`46a874..a8a0`固定常量；`46a8a4..ac→5843a4`读当前state | 原Get不接收键，固定回复130、当前u32 state、自SID、status0；没有缺键分支 | 当前实现明确收窄为实际130子集，其他键返回transport拒绝，不伪称原始missing行为 |
| raw`46a8ca..e4→ae9340`；CPVA0263796c共享200B | 原Get另尝试向008f013a发图形event80000001，即使回复send失败也尝试 | 当前缺该内部消费者；不发空事件，日志`FULL_OSDPIN_SCOPE`明确event_emitted0/osd_initialized0 |
| `run-aehffq8v` console SHA256=`b45922856071c0dca4d5446621a6d230e1434ba975ce45657db51aad422a39e9` | Common325在PinMem130后等9080003b130；此前没有该owner回复 | 新实验须检查真实REQUEST/REPLY/COMMIT/NATIVE_REPLY_FREE及下一栈，不预判成功 |

主会话独立用Capstone复核了raw`469ad6..469b0e`、`46a85c..46a8a4`和`46a8ca..46a8e6`
的原始Thumb指令，包括自SID、reply flags2、130/status0和200B事件长度。
完整原事件剩余共享字段和消费者尚未动态验证，不能凭头部常量构造成功事件。

## 模型范围

运行代码在`runtime/analysis/osdpin-registry.c/.h`，复用该目录的
`device-models/pin-registry-core.c`本地副本。使用既有默认关闭的`MENU_PIN_REGISTRY=1`，
不引入强制切屏、ready状态或新的无依据开关。

仅允许合法48B Dataflow Get、观察到的完整u32键130、合法本地动态回复地址。
独立对象按原完整构造器写入cold状态；回复不是回显请求，status0只代表metadata查询。
不支持Connect及其它命令。原Get对其它键也固定返回130，而本模型显式拒绝这些未观察请求。
回复传输失败沿用现有core回滚/释放语义，不能声称覆盖原Get忽略send错误的全部行为。

Host测试从`runtime/analysis`执行：

```sh
set -euo pipefail
bin=$(mktemp /tmp/a7c2-osdpin-host.XXXXXX)
trap 'rm -f "$bin"' EXIT
cc -O2 -Wall -Wextra -Werror -pthread \
  device-models/pin-registry-core.c osdpin-registry.c test-osdpin-registry.c -o "$bin"
"$bin"
```

测试核对56B逐字节、自SID与动态目的不同、独立cold状态、原请求/回复释放、
默认关闭、不匹配键/错误command/截断/零replySID拒绝、send失败释放以及事件缺失日志。
host测试不代表原AP动态消费。动态实验单独保存console、manifest、源码归档、RAM和截图。

## 实际Get消费结果

`run-mfj5hx4k`原tid325已消费56B回复并free0，pointer=`0x7fa54a8d40`、lease1，
自replySID/ownSID均9080003b、动态投递81cf61c8。证据见`osdpin-get-native-proof.json`。
3项原生registry回归通过，含将OSD外层replySID篡改为零的负例；冷格式2项正/负例仍通过。
scope日志明确`event_emitted=0,event_consumer_verified=0,osd_initialized=0`。

之后原Common不再等待pin Get，栈为`303d49c←305e434←305e9e8←3209e48`。
UI仍等boot future、截图透明黑；新的等待条件正单独调查，不把Get通过外推为OSD完成。
