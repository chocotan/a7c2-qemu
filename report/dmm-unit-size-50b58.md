# CP DMM unit50b58：原配置驱动的只读容量查询

`run-dvpe50ts`原Common328等待`3552ea4←34d3794←305e780`。
这是dmm_get_unit_size消息receive，不是媒体挂载或某个ready条件。
当前主界面仍未恢复；本项只查配置容量，不分配图像buffer，不声明成像就绪。

## Evidence → Finding → Path

appFw地址均为ELF VA。CP地址均为CPVA，raw=CPVA−108000。

| 证据 | 结论 | 实现/验收路径 |
|---|---|---|
| appFw305e768..77c构造unit50b58/chip1，34d3790→3552d5c | 目的为远端9061003c，不是控制RAM本地0061003c | 独立service，不能混用unit404或既有63a虚拟池 |
| appFw3552ea0等原动态source，3552ee0读有符号i16+2 | request op18/40B，非负reply status时取u32+10 | 独立40B回复、动态目的及原sender/free检查 |
| CP C1AD40 handler、C1BCBC dispatch/EA6464 entry | reply op8018、token从request+14回reply+6、size在+10 | 按原布局，默认无分配handle、无图像物理地址 |
| 原DmmCfg offset96a0 unit记录，576c extent记录 | unit50b58首extent f0，size09600000 | 读取原文件并初始化独立只读lookup状态 |
| appFw305e7a0..7ec从原reply取size，getter2883750返回B+7ecfbf0 | 原固件写main_image_unit_size属性17cd | 仅追加readmem观察，不直接写属性 |

原DmmCfg.bin为43508B，SHA256=`d3466cee62fd86d927236a2c6c37dd633f76cdc181b4ad07a9863696aab76660`，
FNV64=`b17ed6044f6bf2de`；本机独立读回核对。两条原记录：

```text
offset96a0: 580b0500 00000000 f0000000 ffffffff
offset576c: 00000000 13000000 f0000000 00006009 0f010000
```

正常40B请求（本轮初始日志只含字段，此完整向量来自原清零/stores重建，动态raw待捕获）：

```text
18000000580b05000000000000000000000000000000000000000000000000000000000000000000
```

成功40B回复op8018/status0/size09600000：

```text
18800000000000000000000000000000000060090000000000000000000000000000000000000000
```

## 有限模型

`MENU_DMM_UNIT_CONFIG=1`默认关闭，仅允许observe/initramfs且不共用实验send-GOT。
`dmm-unit-config.c`第一次有效查询读取选定镜像中的原`/cp/DmmCfg.bin`，
校验完整文件FNV/长度与已证记录结构，保存unit/firstextent/size；不是将150MiB硬编码成成功回复。
主机/选定cpio另用SHA256核源身份，避免只依赖guest轻量摘要。

只支持观察到的unit50b58/op18/40B/option0、其余已证零字段；token16原样回显。
其它unit/非零未知字段明确transport拒绝，不声称复制原DMM全配置的“未知unit=-3”契约。
reply由原allocator独立创建并绑定lease，request及reply分别真实释放。
原63a分配模型与404控制RAM服务继续独立处理其已有操作，不互相占用单元。

结果表示该原配置unit首extent容量150MiB。没有新保留区、没有分配150MiB内存、
没有给原固件写ready/属性。诊断仅按该run实际appFw bias读B+7ecfbf0的4字节，
必须把原回复消费、原流程前进、属性值分别验收；出版通知也不能仅凭静态调用链声称已动态观察。

host测试包含原配置绑定、坏身份/长度拒绝、token0/1234、严格封套、默认关、
发送失败时原request保留、独立reply释放。当前Sanitizer及QEMU动态验证已启动，结果未预判。

## 动态验收

`run-hobha2ig`实际捕获了上列40B请求及原40B回复。原Common328同pointer7fb67cac40/lease1
释放rc0；lookup日志确认unit50b58→firstextentf0→size09600000，完整原配置身份匹配。
原helper只读B+7ecfbf0得到00 00 60 09，证明原AP属性已写157286400。
`test_native_dmm_unit.py`2测试含property/reply/config/free四种破坏全部通过，失败覆盖旧success。
正式`dmm-unit-size-native-proof.json`明确allocated_bytes0；原model publication callback没有单独动态探针，
因此`original_model_publish_callback_verified=false`，不把静态发布调用当作已独立观测。

同run的面板虚拟配置和DigitalLevel订阅证据亦通过。UI已显示原存储卡错误页并消费MENU，
但未出现拍摄主界面；后续媒体和收尾等待继续单独推进。
