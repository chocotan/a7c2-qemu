# Common 完成token汇合等待

在OSDPIN Get通过后的`run-mfj5hx4k`和`run-v5hf37qm`，Common325实际栈均为
`303d49c←305e434←305e9e8←3209e48`。这处等待尚未解除，拍摄主界面未恢复。
以下appFw地址均为ELF VA。范围为只读固件研究及本机QEMU，禁止手造完成token。

## Evidence → Finding → Path

| 证据 | 结论 | 下一步 |
|---|---|---|
| `305e430→303d674(S,tokens,4)`；wrapper读`I=*(S+8)`后转`303d400` | 等待的是4个成员函数完成，不是直接检查pin状态 | 采集原SeqThreadPool worker栈，确定未返回的函数 |
| `303d480`读I+b8/head、I+d8/tail；相等时`303d498`等CV | 当前谓词为完成队列非空 | 不强改队列游标，不用topology错误数或媒体位替代 |
| `34b9564`调用成员函数，返回后`34b9574`调用closure | 正常完成通知由原worker自动产生 | 实现该成员正在等待的合法服务，使原函数返回 |
| `303d370`在mutex I+f8保护下向deque I+a8追加token并notify I+128 | completion token证明成员返回，不证明硬件成功 | 原callback/队列/await消费分别留证 |
| 同run的11条Connect中10条明确拒绝 | 拓扑确有缺口，但此token谓词不直接读取这些状态 | 不把拓扑失败直接命名为当前join唯一根因 |

主会话独立复核了`303d480..4a0`、`305e420..434`和`34b9560..578`的原AArch64指令。
当前动态记录只证明队列等待，尚未匹配缺失成员。

## 四个成员

| token数组序号 | 原函数ELF VA | 原提交位置 |
|---|---|---|
| 0 | `3058eb0` adf_set_volume_i | `305dc94` |
| 1 | `305ac4c` adf_get_func_i | `305e04c` |
| 2 | `3060464` regist_beep_signals_i | `305dcb4` |
| 3 | `3062e3c` license_get_i | `305b768` |

提交`305b550→303cf00`从可用队列取token，将I和token写入closure。
`303db70`初始化队列、mutex和CV，可用token是0..10。await收到合法完成token后归还可用队列，
特殊token2000返回1，其余未知token断言；不能人工插入“看起来合理”的值。
run_i返回之后，原`305e9e8→2e06480(*(S+10))`才完成UI等待的boot future。

## 最小只读采集

沿用`MENU_QUEUE_STACKS=1`，将现有线程名筛选从`SeqQueue*`扩为
`SeqQueue*|SeqThreadPool*`，不新增配置开关；`MENU_THREAD_NAMES=1`用于核对census。
这可直接区分空闲pool线程和停在音频/许可原函数内的线程，不先假定哪项阻塞。

如果worker栈仍不充分，再按匹配栈读取await frame+10的S、S+8的I、
run_i FP+110的四个u32 token及I+28/I+a8两个50字节deque头。
Pool=`*(I+20)`，四worker记录stride98；仅active byte+20非零时才读+28/+30的closure指针，
空闲记录可能保留已经释放的指针。所有地址必须来自该run，不沿用另一run的绝对地址。

## worker动态定位

`run-gjwv9_0o`已按线程census采集全部四个pool栈，console SHA256=
`0b8d5a197a35bf130f2e2d5b549ad2c2bb8bade07d61e8b9911bd922aee2d196`：

| 原线程 | 采样栈ELF VA | 对应等待 |
|---|---|---|
| Pool0 /321 | `34b9528←36ec1b0` | 当前空闲，不单凭此声称许可成功 |
| Pool1 /322 | `34e5788←34eac6c←34c72c4←3058ed4←34b9568` | 音量设置，原0330 |
| Pool2 /323 | `34e5788←34ec204←34c73c4←3060a1c←34b9568` | 提示音地址，原033f |
| Pool3 /324 | `34e5788←34ea4dc←34c6f84←305ac88←34b9568` | 音频能力，原0327 |

见`boot-worker-waits-native-proof.json`。本轮没有新请求raw字节日志，协议标号来自匹配到的
原wrapper，不把静态定位称作抓包。下一轮接入native本地有状态audio模型，并单独记录
实际请求、reply pointer/lease及原waiter free。

新增`MENU_AUDIO_BOOT_CONFIG=1`默认关闭，能力来源显式为virtual inputless配置缓存，
不是推断原相机硬件状态。volume实际消费op4控制并读回level；playback仍拒绝。
033f/0329要求独立sound backing owner和原SysSound内容读回，当前未初始化时明确拒绝，
不以常量地址冒充已加载声音；真实保留区方案另行只读核查。
