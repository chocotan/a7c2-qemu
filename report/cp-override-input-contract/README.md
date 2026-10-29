# Override输入：显式初始化写事件

已找到参数`P+0x1c8`的正向写者：`CP8db6d6`执行`STRD r5,r5,[r4,#1c8]`，其中`r4=P`、`r5=0`，实际覆盖8字节`[P+1c8,P+1d0)`。这是一条显式写指令，不是BSS零值推断，也不是把公开属性里的零值当默认配置。完整constructor、异步通知及原生发布历史仍未闭合，`capture_verified=false`。

范围限本项目已授权的公开ALLLANG离线分析和本机虚拟owner自测，不运行目标固件/VM，不接网络、真机、物理SD或private/full资产。原件`runtime/analysis/menu-root/cp/cpapp-b.bin`长18,090,880字节，SHA-256为`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。CP VA=raw+`0x108000`，仅使用文件映射区间`[108000,1248b80)`；不读取BSS为文件内容。

从本成果根目录复核：

```sh
cd runtime/analysis
python3 -B -m pytest -p no:cacheprovider --import-mode=importlib -q \
  ../../report/cp-override-input-contract/test_source.py \
  test_cp_parameter_state.py test_cp_owned_state_profile.py
```

| Evidence | Finding | Path |
|---|---|---|
| `8db6aa:0446`、`8db6ac:0025`、`8db6d6:c4e97255`及原窗口 | 保存root、构造zero、明确8字节STRD；override字节为该写事件的首字节 | 原参数初始化步骤→局部参数image |
| `8dc67e..8dc698` | wrapper在检查flag之前总调用`8db6a2(root)`；flag非零返回，零则尾调用`8db9bc(root)` | 接受/拒绝属性两条分支都有该写事件 |
| `353d48..353e8c` | 真正READ属性`00030160`到`1659720`；检查头`d68`及`0092001c` bit2，成功才复制d64到mutable root | 属性读取/验证→可选导入→初始化；不同于后续`35416c`的WRITEBACK |
| `b2e150`和`99e250`原窗口 | mutable root=`165a720`，published root=`172fe50`，override位置分别为`165a8e8`/`1730018` | 原publication复制→指针数组首项→getter；本轮未声称实际走过 |

[源合同与摘要](source-pins.json)归档5个主窗口/446字节。测试独立核完整原件SHA、窗口和关键指令，还核公开ALLLANG secondary中的`00030160`确为4096零字节、`0092001c`为零。因此公开属性不能满足导入条件，不能作为override值来源。`1b0470e`是导入路径标记，不能替代初始化写或发布证据。

代码在现有[参数owner](../../runtime/analysis/device-models/cp-parameter-state.c)增加`cp_parameter_state_consume_reset_store`。普通`cp_parameter_state_init`仍让所有字节未知；新函数仅显式消费这一条源已闭合的STRD写，赋零这8字节并设置相应known位。它只允许同owner进程、enabled、首次batch之前且该区域尚未知的情况；重复、跨进程、disabled、无效对象和batch之后的调用均拒绝，失败保持整个owner不变。config/semantic槽掩码、batch、generation和发布状态均不改变。

默认关闭的`virtual-cp-owned-state-v1`构造流程显式调用这一步，并分别记录`parameter_reset_store_consumed`和`initialization_complete=0`。如果后续publication构造失败，日志仍如实保留已执行的reset事实，profile保持关闭。普通参数模块的纯4063测试仍不调用reset，原891已知字节覆盖的历史判据不变；显式执行reset的virtual owner额外拥有这8字节的**局部配置值**。

这不是完整constructor仿真。`8db6a2`后部读取root的标量参数并尾调用`8db984`，后者经AE helper发送工作；flag0还有默认初始化路径。即使局部写事件已消费，仍不证明它们全部执行、后续没有覆盖、真实CP执行过constructor、published root已更新或AP消费过override。新函数不会把局部值导入`cp_start_state_data`，更不会产生3003回复、ACK或ready；实际provider仍0/4，完整76块provider仍ENODATA。

C测试用非零poison填充未知image，核仅8字节和相应mask被修改、邻接字节仍未知，随后实际4063消费保持该区域；同时覆盖重放、fork、disabled和错误原子性。构造fixture新增reset失败分支，核四数据known仍0，且所有业务/发布/EE/frame/capture标志仍false。这里的host测试只证明局部模型行为，不是原生constructor或拍摄通过。
