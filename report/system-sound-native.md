# 原提示音数据的 native 保留RAM与配置消费

`run-ypsslyoq`中，提示音地址查询之后实际出现25条0329注册和25条032c分项音量配置，
四个原pool worker均回到空闲栈；Common已越过四token汇合，继续到032a等待。
完整逐字段配置验证及篡改负例另行运行；本结果不代表音频播放、OSD或拍摄主界面完成。
该项后续验收已通过：2测试含6种篡改负例全部通过，25个kind的范围、实际slice摘要、
分项音量读回及原waiter free均已核对。正式证据为`system-sound-native-proof.json`。
其中5个原描述的size为0；这些是按原请求注册的空描述，不是5份实际音频流。

范围是本机隔离QEMU和原ALLLANG资产，不接真机或物理SD。所有模型源码使用native的
`runtime/analysis/device-models`本地副本，不从full-system实时引用。

## 数据与地址

| 项 | 值与含义 |
|---|---|
| 原文件 | native `menu-root/cp/SysSound.bin`，66368B / 0x10340 |
| 原文件SHA256 | `5d94c660c48afde364fbb936105abdaf5c35f8bf8fc0bfd6945cd12146f6824a` |
| 虚拟保留RAM | 物理`0x41d000000`，容量131072B / 0x20000 |
| 返回audio phys64 | `0x81d000000`，显式虚拟映射，不声称原boot allocator位置 |
| CPU/bus offset | `0x1d000000`，与实际物理backing区分 |
| 全区内容 | 原66368B + 64704B全零尾部 |
| 全区QMP SHA256 | `d4d940aa686f53103b1baef800f60fc9cffd2d27cab36530bfbddca1afa2c918` |

## Evidence → Finding → Path

| 证据 | 结论 | 实现/验收路径 |
|---|---|---|
| 前轮033f transport拒绝后原Pool2 assert | 不能靠错误降级、占位地址或跳过断言解除此等待 | 初始化真实RAM owner后才启动应用 |
| native-sound-region最终profile、16条上限、foreign overlap及DTB owner检查 | 该区与Linux分配页/其它适配器隔离 | 启动与offline均调用同一reserve；真实libfdt负例 |
| helper加载原文件、逐字节读回/校验零尾后原子发布metadata | ready只表示本owner有实际数据，不表示相机ready | `/tmp/system-sound.ready`仅在helper成功后建立，应用启动门控 |
| sound-table消费者以只读mmap独立核原文件与整区 | 地址响应和table slice对应真实内容 | 033f返回前整区验证，0329逐slice读回/digest，原waiter free |
| 终态独立QMP导出131072B | 主机可核guest写入及余区 | 整区与源+零尾逐字节比较，保存system-sound-ram.bin |

默认关闭的`MENU_AUDIO_BOOT_CONFIG=1`启用音频配置及其必需的sound owner，
要求`--initramfs --sony-timers --observe`。最终cmdline只有一次
`fullsystem.sound-owner=1 memrsv=0x00020000@0x41d000000:uc`。
从当前14条reservation基线增加为15条，ramfb可到16；超过原表上限一律拒绝。

构建从冻结的本地源码生成`/simulation/system-sound-owner`，生成资产白名单只增该helper。
选定cpio中源音文件和helper都要验证摘要；本轮helper SHA256=
`7674677c8d7321c2203d335ccd3f5a15c0ae0c51760cf48c5c9b0c1db956fbe6`。
DTB SHA256=`7c4c482e2ea2d0ee50c8eefcaebdfe06e38df2dc73113e302a52b30cf53c2725`。
这些仅描述本轮产物，后续重建应读取对应运行清单。

## 本轮观测

原线程编号因启动helper而变化，不能继承前轮的322/323/324：本轮pool为324..327、
Common328、StillCa330、UI290。原326发033f，独立24B回复返回地址81d000000，
相同pointer=`0x7f9cf8b100`、lease2的原waiter释放rc0；随后完成25次table请求及25次per-kind volume请求。
原4个pool均停在空闲`34b9528`；Common新栈为
`34e5788←34ebddc←34c7404←305e47c←305e9e8`，最后实际请求是
`0d202a030a0001800700`。032a尚未实现，正单独核原协议。

StillCa字段依旧initial_arrived0、slot states0；UI继续等boot future。
5张RGBA截图仍每像素透明黑，不能宣称提示音配置恢复就等于主界面完成。

## 复核

在`runtime/analysis`中：

```sh
export A7C2_NATIVE_SOUND_RUN="$PWD/menu-runs/run-ypsslyoq"
python3 test_native_sound_verifier.py
python3 device-models/verify-system-sound-config.py --native "$A7C2_NATIVE_SOUND_RUN"
```

验证器直接读取native清单/summary、选定音源/helper身份、实际DTB和QMP字节。
逐项核对033f、25个独立kind、启用slice范围/内容摘要、25条音量读回和原waiter释放。
负例破坏源区、零尾、profile、helper身份、释放记录及bootargs重叠，必须拒绝。
scope固定为配置/内容消费，`audio_output_verified=false`、`camera_startup_verified=false`。
