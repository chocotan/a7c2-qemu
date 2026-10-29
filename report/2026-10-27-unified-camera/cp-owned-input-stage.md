# 明确CP输入阶段与本地参数镜像

本轮实现把公有CP属性、源本地参数初始化、不可变复制与LIF位图分别记为实际消费步骤。所有原始文件保持只读，运行代码在`runtime/analysis/`权威目录。范围限本机隔离QEMU研发与host自测，不接真机、物理SD、网络或private/full dump。最终拍摄标准不变：实际CMOS→原编码→MPR/Fsys→虚拟SD→读回解码；当前仍未达到。

## 已接到实际observer的输入路径

默认关闭的`virtual-cp-owned-state-v1`现在执行：

1. 初始化四字节data owner和参数owner，四字节结果known仍为0。
2. 消费原common本地写入：195条指令、7个清零调用，694个确定字节。AE尾调用排除。
3. 只读打开经过host公有资产校验的`/seed-backup.bin`，完整读回/FNV、固定长度、EOF及前后fd身份检查后，明确选择其`ed000`起的CP initial stage。此选择对应原CP primary构造接收的`04000000`逻辑输入，**不是ALLLANG文件offset0，也不是缺属性时fallback**；原生PCI地址别名与执行历史仍未验证。
4. 同一stage事务读取`01250003`和`01250006`，得到本地mode=1、完整256字节profile上下文及profile=0。实际context[0x20]=1，decimal context[20]=0；profile字节为0不等于整个上下文全零。旧provider的PRIMARY策略仍代表文件offset0且缺属性时ENODATA，不改变其含义。`stage[9]=1`冻结后校验不一致的数据拒绝为EILSEQ，不修补checksum。
5. 同一stage读取`00030160`和`0092001c`，实际头0、flags0不满足原`d68 && bit2`导入条件，因此明确选择flag0默认本地写路径。不是拿属性里的零字节填P。
6. 执行999条原默认阶段指令对应的2223个本地写字节，含18个清零调用、一个栈序列化helper和一个176字节复制。与common组合2913/3428字节已知、515未知。未写孔继续未知，完整初始化/AE/c1aa3e未完成。
7. 从当前参数owner实际复制d64字节及known mask到独立view，再显式建立bank0绑定。view保持不可变；后续mutable参数变化不隐式重采样。

随后原4063实际包进入已有190槽消费者。离线用同轮原始字节重放，common+defaults+4063的参数覆盖为**2973已知/455未知**字节；170配置/168语义槽分类及PARTIAL状态不因已知字节增多而自动完成。历史run不回填新初始化步骤。

日志`NATIVE_CP_OWNED_INPUTS`报告各阶段rc、参数本地known覆盖、copy/bank0结果、mode/profile已消费位及实际值；`initialization_complete=0`、`original_CP=0`、`data_3003_known=0`仍明确保留。错误的stage、frozen记录、fd变化、失败Close、source owner或binding错误都会关闭该profile，不生成数据ACK。

## 已实现但尚未绑定原producer的LIF路径

[位图owner](../lif-bitmap-producer/README.md)从有来源的K、能力对象字段、support判据和mode构造原17字节命令0a及25字节逻辑帧。完整配置代次、待消费lease和已消费代次独立；只在25字节实际消费比较成功后记receipt。32字节DMA跨度中的7字节padding保持未知，不生成假的零padding。

显式接收事件才建立a923d0快照并调用[帧解码器](../lif-runtime-input-contract/README.md)。构造或排队返回0都不等于发送成功。所有需要的能力对象数据、K和support来源仍须实际消费；尚未接入的原LIF producer不会被默认值替代。

LIF normal worker的局部清零确实覆盖关键8字节，但发布前可经50ff1c进入原调度器。因此局部clear不能直接变成已发布样本；旧tuple/flags历史、ADJ M/C、kind/Q和完整76块状态provider仍未齐全。四字节data owner仍0/4，不能放行3003。

## 测试与代码入口

```sh
cd runtime/analysis
python3 -B -m pytest -p no:cacheprovider --import-mode=importlib -q \
  test_cp_parameter_state.py test_cp_property_stage.py test_cp_property_stage_file.py \
  test_cp_parameter_import.py test_cp_parameter_view.py test_cp_owned_inputs.py \
  test_cp_owned_state_profile.py test_cp_lif_bitmap.py test_cp_lif_frame.py
```

关键证据与路径：

| Evidence | Finding | Path |
|---|---|---|
| 公有stage完整身份、BK4目录与真实属性payload；冻结差异实际拒绝 | 属性和参数分支来自同一明确CP initial stage，不做fallback | [stage合同](../cp-property-repository-contract/README.md)→[fd loader](../../runtime/analysis/device-models/cp-property-stage-file.c) |
| 原195/999条指令逐步写trace、只读C范围表、poison/known-mask及真实4063字节重放 | 本地已知字节有源且逐字节核对，孔/业务完成不提升 | [common](../cp-parameter-initializer/README.md)→[defaults](../cp-parameter-defaults/README.md)→参数owner |
| 原d64复制和50指针bank表合同；实际C helper读回 | mutable/copy/binding分开，override视图不随mutable刷新 | [参数view](../cp-parameter-publication-contract/README.md) |
| 原0a构造、配置/消费代次和接收快照合同；131072组合矩阵 | 配置不等于发送，SNAPSHOT只发生在接收边界 | 位图owner→帧解码器；原producer仍未绑定 |

`test_cp_property_stage_file.py`另将唯一交付的`report/cp-property-repository-contract/check-original-abi.c`编译为AArch64，链接原libc2.25并在QEMU用户态实际执行，读回未修改的公开seed、mode/profile和默认分支，验证__fxstat(0)与pread的真实旧ABI、失败原子性及errno。该检查不启动系统VM，也不执行原CP固件。

这些测试验证host模型、原字节合同及实际observer helper，不能作为原固件拍摄或原CP RTOS等价证明。完整回归、构建和原libc ABI由统一入口一次运行并独立存档，当前原固件JPEG/MP4结果仍为false。
