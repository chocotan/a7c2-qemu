# 参数common初始化：694字节本地写入

本成果把原`CP8db6a2..8db980`的**195条直线指令**恢复成694字节的确定本地写入，含7次真实`61ed00`清零调用。默认关闭的虚拟参数owner实际执行这组写入，不再只供应单独的8字节override reset。普通`cp_parameter_state_init`仍保持全未知；AE尾调用、flag0默认初始化和原CP启动历史不因此完成。

范围仅限公开ALLLANG、离线源分析和本机C自测。不启动目标代码、VM、网络或物理设备，不使用private/full dump或真实SD。CP原件长18,090,880字节，SHA-256为`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。CP VA=raw+`108000`，只读文件映射范围。`[8db6a2,8db980)`共734字节，SHA-256为`66c4be97db5c9d3296965f6ab47881e0c18160b125a0079af202c62cf66d3944`。

从成果根目录验证：

```sh
python3 -B report/cp-parameter-initializer/extract_common.py
cd runtime/analysis
python3 -B -m pytest -p no:cacheprovider --import-mode=importlib -q \
  test_cp_parameter_state.py test_cp_owned_state_profile.py test_cp_owned_inputs.py
```

[提取器](extract_common.py)是这个固定窗口的有限常量追踪，不是通用ARM/CP模拟器。它核完整原件SHA及窗口SHA，解码195条指令，仅支持本窗口实际出现的move/add/load/store/stack和固定零函数调用。未知指令、未知写值、越界地址或额外调用均直接失败。`61ed00`的312字节实现也固定原SHA，不能靠函数名假定清零语义。没有把BSS/未知寄存器当零，所有源读取和调用后易变寄存器均按实际已知性追踪。

[逐步写证据](common-local-stores.json)保留每条写的PC、目标offset、长度和字节值；生成的[只读C表](../../runtime/analysis/device-models/cp-parameter-common-init.inc)将最终694字节压成连续范围。源方法不读取被重写参数根的文件初值，未写字节仍未知。典型已知内容包括`P+1c8..1cf=0`、`P+214=2`、`P+668=5`、`P+670=5`、`P+678=4`、`P+67c=8`及`P+d5c=1`；这些是本地参数字段，不是业务完成/generation发布收据。

`cp_parameter_state_consume_common_stores`要求同进程、enabled、尚未stage且所有known位仍为空。只应用生成表的字节和known位，保留batch、config/semantic槽掩码及发布状态。重复、fork、disabled、先执行reset或先消费batch后调用均拒绝，不覆盖已有状态。调用者需外部串行化。

| Evidence | Finding | Path |
|---|---|---|
| 原734字节、195条指令与固定zero-helper | 694字节值不依赖未知源参数 | pinned CP→有限常量追踪→只读范围表 |
| C输出镜像/known掩码与独立提取逐字节一致，未知存储以A5 poison检测 | 只写已证范围，邻接未知字节不提升 | actual C consumer→readback |
| 原同轮4063字节与190槽原setter映射 | common694和真实批次891组合得到**1544已知/1884未知**字节；槽语义掩码不变 | 显式local初始化→实际包字段消费→PARTIAL |
| 原construct及helper错误场景 | 初始化步骤可留证，后续输入/发布失败不回填已完成 | virtual owned-state构造→stage/profile/copy/view |

对历史`run-nzx01uc3`的4063仅作只读字节输入重放，不把新common阶段回填到旧run。原190槽消费者保持170配置消费、168语义闭合的分类；完整参数图像仍PARTIAL，不能仅凭1544已知字节发完整快照。

原本地段末尾读取`P+120`、`P+138`并在`8db980`跳入AE工作，本提取器在跳转前停止；flag0的`8db9bc`也未执行。因此日志明确`initialization_complete=0`。这些已知本地字节只在自己的显式虚拟source操作里成立，不证明原CP已启动、异步任务已消费或published root已更新。参数copy和bank0绑定由独立view owner记账；四个3003结果、EE、帧和capture不随本模块提升。
