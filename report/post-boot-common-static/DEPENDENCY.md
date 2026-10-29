# boot future完成之后：CameraBackground的原CP等待

`run-coojlkn6`的Common328已不再等待最初的boot future；它当前在原收尾请求的另一个future里。
UI已经显示存储卡错误页，这仍不是拍摄主界面。本文只记录原依赖，不合成future完成或设备回复。

## 同run动态证据

console SHA256=`285701e64d05e75e53a8468937510c3b98c03e9b41c297f838c1d990aeb73d44`。
原Common328发往8102021f，source80020002、20B：

```text
1000000020000000000000000000000000000000
```

原CameraBackground在本轮是tid287（不能复用另一run的285），实际线程名截断为CameraBackgroun。
它接收8102021f后，当前阻塞在动态队列810261c7，调用点libObj ELFeda8c。
同一run libObj bias=`7f9ceee000`，其栈为`eda8c←ee460←ee82c`，
上层libc/线程封装的LR没有误减appFw bias。Common栈仍为
appFw ELF`310194c←34f4f74←3535b04←3548cbc←34d1774←305eb88`。

## 原控制流与协议

| Evidence | Finding | Path |
|---|---|---|
| appFw305e9e4调用run_i，305e9ec调用future completion；305eb84才调34d1748 | 当前收尾栈在最初future完成之后 | 不继续称“UI仍等bootfuture”；实际UI已回消息循环 |
| appFw3548adc→35358b8发送8102021f，request{10,20,...} | 收尾通过原CameraBackground事件请求 | 被动捕获原message，不直接写promise |
| libObj ee434..45c匹配10/20并调ed9c4(command3007) | CameraBackground等待不是原20B未被处理 | 原worker的下一层CP请求才是当前待查依赖 |
| libObj ed9ec创建type2a/owner102动态queue；eda24分配24B、eda4c发送90030001 | 原命令type u8+0=0、u16+2=3007、OSAL source为动态queue | 实际24B payload须另行被动抓取；未赋值部分不能假定为零 |
| libObj edabc读reply+8；F001/F002及其它分支分别处理 | 成功/错误值不能按一般f000套用 | 必须先闭合CP3007consumer及真实副作用，不能空ACK |

libObj后续对F001返回0；F002设置本地状态并发送3029；其它响应有针对3027/300a的特殊路径。
这只是AP消费分支，不足以命名F001为“成功”或据此构造虚拟回复。
CP90030001的原receiver/table已在既有`main-screen-entry/cp-cmd/REPORT.md`恢复，
但那里的40b8/402a/40af都是no-wait设置，不能用于当前3007。

## 反编译范围纪律

首轮`await-chain-kuna.json`对3535880/305e9fc使用了内部指令入口，已识别前者是清理函数内部、
后者是完整sequence_boot::run的收尾部分。保留原结果及Kuna警告，不将其恢复的入参当作完整函数原型。
主会话随后直接核原prologue，正确函数入口为35358b8、305e9b8，
`verified-entry-kuna.json`为重新定点导出；最终语义仍以原指令与同run消息/栈为准。

原CP3007的consumer由独立只读调查进行；主会话已加有限被动捕获24B消息。
存储卡错误由另一个独立调查追踪，未假定两条依赖同因，也没有改真实设备或传感器状态。
