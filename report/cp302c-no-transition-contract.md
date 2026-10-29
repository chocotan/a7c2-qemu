# 302c的两条专用完成来源

**源码更正：此前将正常3041转换路径当作全部302c/f000回复的必要条件，范围过宽。** 原CP外层另有“3041不准入”时直接发送专用302c/f000的完整分支。该分支先于observer/perform，不start3041，不要求模块完成，不修改中央current；AP仍将其解释为结果0。

主会话独立核验[20段CP/AP窗口](cp302c-no-transition-source-pins.json)、专用producer原始字节及320项命令表中current0缺少3041/3024的事实。这是可实施的原业务分支，**不是无条件ACK**。必须先有有效的中央current与输入历史；当前没有新的原运行验收，也不宣称成像或拍摄完成。

## 外层准入与专用回复

```text
external302c
→ handler0 / event17
→ b1ffba outer dispatcher
→ family0 vtable+8 b20220，event17分支b20364
→ b2232a → b1f140(3041)
→ 返回 !admissible
```

b1f140返回1表示可以开始，返回0表示不准入（包括busy或current/command表不命中）。b20220对它取反；predicate等于1时，b20010选择vtable+1c进入4b4b00，event17的4b4b86从原输入读取cookie/origin，调用b22788生产独立12B回复。

源定义payload为`01 ?? 2c 30 cookie[4] 00 f0 00 00`。byte1没有赋值，虚拟padding可采用明确记录的确定值，但不能说原值已知零。4b6a70独立分配，设置source90030001，复制payload，发送到incoming origin；发送失败释放独立reply。

关键原字节：

| CPVA | 原字节 | 效果 |
|---|---|---|
| b20364 | e06801f0e0ff80f00100d0bd | 查询3041并取反 |
| b2232a | 43f24100fcf707bf | b1f140(3041) |
| b20010 | 9047012802d13068c26925e0 | predicate1选择vtable+1c |
| 4b4b86 | d4e9011228696df2fcf519e0 | 原cookie/origin传b22788 |
| b22788 | 44B，SHA edca941d1bf00ce83b1718169f2ab08fa764ffd732bb104faa8c819cfe84f96a | 专用type1/302c/f000 |

此分支发生在phase0、普通执行资格检查、perform和phase1/3之前，不是“先start失败再合成成功”。b22788直接使用当前输入cookie/origin，不依赖正常perform预存destination。

若绕开外层直接调用event17 perform，guard的非零拒绝会阻止start，而perform不处理该返回值；这不是正确协议实现。

另一条准入为真的正常路径保持：3041→实际module/boundary/commit→family1 event32d→b2275e专用回复。两个producer必须在日志与收据中分开，no-transition回复不得记为mode transition或module completion。

## AP对这条回复的实际解释

AP3546320发24B302c，经35460e4→35358b8等待。3535af8..3535b24复制12B回复并释放原buffer；3546360读取status，3546364比较f000，3546368/6c写`result=(status!=f000)`。因此不转换分支得到结果0；不能自行发一个未证明的负status代替。

## 首个3007的有限构造历史

在明确的source初始化和没有其它状态输入的有限边界下：A构造b21290清self+4起1cB，B构造b20e56清self+4起20B，二者state self+18为0；executor b208f6设置active1/last_event f00。aggregate b1fd1c只绑定指针，b1fe46清两个queue游标。

首event4的phase0选A index6、B index2，state0 member pair均零；执行b218a4→b21702(command3007,mode0)，executor记录event4并inactive。phase1/3选A8/B5，state0 pair零。中央current0选path`0→57→0`，不把未选pending模块视为完成。

3007正常控制完成是**family1 event304**，经4b59e8→4b5ed4→b229b4按mode0回复；不是event307。event304 phase1为A8/B5，恢复executor active1/last_event4，phase3为A5/B5，state0 pair仍零。4b5f28自动处理要求CamMain+20与b21fb4谓词均为1，此有限历史不满足，空queue drain不生成新命令。

b21418→b222b2请求3033，不是自动3003。event307确有异步路径，却不属于本次3007正常完成，不能借它补启动历史。旧cp_cold模式3、handler event4、中央current0是不同字段。

## 实施与验收门槛

有限owner可以从已证source清零/构造建立current0及A/B state0，实际观察3007原请求/专用回复和原sender free后预测其正常完成仍回0；还必须审计所有前缀及对中央状态的作用。未知输入、遗漏internal producer或不完整历史仍拒绝，不能为了使用此分支把原始状态填成0。

在有效current0且idle时，320项表确无3041，因此外层不转换分支成立。后端必须保留原cookie/source、独立reply所有权、原请求与reply释放证据以及原AP同sender消费，记录`no_transition_branch=1/3041_started=0/module_completion_verified=0`。不能清旧pending1f7e、强写EE、宣称CMOS/GPE/帧或真实拍摄。

当前原运行仍停在302c；新实现及精确default-off profile正在独立开发，尚无新回复消费。此前variant0/module2/6或8正常路径研究继续有效，但只约束需要真实转换的分支，不再作为所有302c回复的总门槛。
