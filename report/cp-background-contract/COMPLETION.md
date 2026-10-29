# 3007控制完成的原判据与有限引擎

本页仅记录官方2.01 ALLLANG的已核静态链及当前代码边界，没有原guest成功回复/恢复验收。CPVA=RAW+108000；具体有界原转录位于研究工作区`scratch/cp3007-completion-mask/`。

## 原boundary、path与最终事件

`b1f1cc→4b2b54`仅比较boundary低13位选中的requested/returned。8000不选择模块；8001只选择slot0。随后`b1f3e6`检查阶段位置，`b1f4a8`检查路径位置，结束才提交目标current并发布最终值。这里没有额外全13模块相等或busycount为0的循环；未选模块不能因此被标记完成。

完成消费者实际为：

```text
b1fa04 → b1f29c(read-clear final value)
 → 4b637c(cmd3007 → family1/event304)
 → 4b5fe4(real allocate/copy/send900302d9)
 → 4b3e90(family1 handler)
 → 4b58b0 → 4b59e8 → 4b5ed4 → b229b4 → 4b6b2c
```

event304的32B消息在写family/event之前清零，其余24B无generation/opaque/模块数组。最终普通3007分支没有重新比较保存的generation或pending；不能将生命周期保留要求误写成“原event必须generation匹配”。pending/busy在前面的真实路径结束时已清理。启动prepare/busy/path查找与generation分配仍是实际要求：不能因为最终event没有token就绕过启动过程。

**两个mode域分开**：3007启动入口`b218a4`传完成方式mode0；mode1走`b22946`另一producer。它与CP实现模式word1107178的mode3不是同一字段。

`b208ba`在payload dispatcher中调用两个已绑定observer；`4b5874`更新exec-handle。返回值未作最终门槛，不代表任意callback都可省略。`b20d94→b20cac`为诊断消息分配/时间戳/发送，其返回未被`4b6b2c`检查；它不是全模块业务门槛。最终普通reply仍需保存目标有效、实际分配12B、设置source90030001、成功发送及失败释放。不能以走到producer当成功投递。

## 当前有限引擎

`runtime/analysis/device-models/cp-cold-control.c/.h`实现显式fresh mode3/cold控制profile，借用调用方的实际资源bank：

- 解释原两段descriptor序列，保留完整u16及mask；按组/路径推进、保留generation/busy及read-clear内部结束值。
- slot0只在所支持的真实资源条件下消费原12B参数；资源未释放会阻8001，即使引用已退到0也不能通过。
- 0b01只建立已闭合的13B控制字段，不伪称descriptor/threshold消费者完成，observed保持未完成。
- 0c06只实际写并发布双bank的+24两字节，getter从发布bank读回，明确不是完整72B快照/反馈合同；observed同样不伪填。
- 其余模块保留requested/pending/observed独立状态。内部结束值3007仅表示本有限profile所选边界/路径结束，不表示这些模块或图像硬件ready。

该引擎拒绝其它CP模式/命令，不能用于活跃恢复、反馈回调、任意运行态或已有成像任务；调用方必须保证资源bank生命周期。它尚未注册90030001原消息消费者，也没有发送f000。原observer、exec-handle、真实消息owner/queue/free与模式/冷前提绑定仍需在接入阶段逐项保留；不能把新内部结束值直接当原AP恢复证据。

对应C测试`test-cp-cold-control.c`使用真实分配及别名，验证mask0/1、zero-ref但backing未free仍阻塞、释放后推进、未选模块保持pending、部分字段发布、read-clear、重复generation与fork隔离。host+ABI门控`b76b8ee70`按其输出记录；没有模拟固件照片或主机录像冒充拍摄。
