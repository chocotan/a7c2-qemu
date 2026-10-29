# 第六条图连接：VEF OUT2 → PinMem IN0 的三级格式传播

`run-4gqygshc`已通过第六条有状态连接及同一handle三级格式传播：原AP259/TID382释放唯一56B完成rc0/fault0/ap1；九笔DMM、三次80B通知/映射读取、同三个权威cache更新及最终Free0/0/live0均核实。本轮SD/退出双锁、1364项联合回归/139子测试、原ABI与独立原运行复核通过。见[六边收据](six-edges-native-proof.json)。`six_edges_native_verified=true`仅限六条虚拟控制连接/格式消费，`capture_verified=false`。

## 当前端口及原件来源

source `{0,2,2,905a0048}` 为VEF16对象slot9，sink `{0,1,0,90590818}` 为PinMem13对象slot0。旧VEF OUT3→PinMem IN1是slot10/1，仍保持原连接和ordinal1历史；不能将新边套到旧owner上。

依据公开ALLLANG CP原件SHA256=`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。关键raw（CPVA=raw+108000）：

| 源证据 | 本边合同 |
| --- | --- |
| c41260 / c1ef4c | 两个独立端口属性 |
| f8580..f8622 / c1f128→5d6bc2 | PinMem完成peer握手后选择type0 manager回调 |
| 5d6b60..5d6bbe | record0构造：raw_flags3、code1、component1、1920×1080 |
| 5d6c7e..5d6d74 | SSYN01/key0/16B生产、Share与本地Release |
| 10d540..10d60e | VEF打开/解析，按OUT2选择**ordinal0** |
| 10d6e0..10d728 | ordinal0下游IN1已经connected0，必须Close后转发 |
| ce326..ce3ac | BB检测component/flags变化、更新同一表并继续转发到已连接的IN1 |
| 36723a / 367486..36754c | 最后InfraImaging OUT1打开SSYN并更新五字缓存 |
| 367560→a3cb96 / 408fdc | 最后Free23/option2，不再多加Close |

父独立核reader、forward和SetPath完成三个原窗口摘要及payload摘要，见`vef-pinmem-input-forward-source-pins.json`。

## 不使用旧cold释放分支

本次16B格式为：

```text
01010300000000008007000038040000
code=1 component=1 flags=3 width=1920 height=1080
SHA256=1fae52ab65d31bdc7fbacb39f39e9c7514dadde0577ee60b4641711f538c38eb
FNV64=37228cd728b41c0d
```

与第一/第四边的component0/flags0不同，BB的same-format-only分支不适用。第四边已经连接VEF IN1，第一边已经连接BB IN1，因此该handle必须依次经过VEF、BB、InfraImaging真实消费。未连接state1的“直接释放”分支不能在这里伪造。

| 阶段 | DMM消息 | owners/opens | 数据工作 |
| --- | --- | --- | --- |
| PinMem allocate | 152B20/opt1、unit404 | 1/1 | 写80B SSYN01/type0/key0 |
| Share | 152B21/opt0 | 2/1 | 增加唯一consumer引用 |
| producer Release | 152B23/opt2 | 1/0 | 先释放本地引用的合法异步顺序 |
| VEF Open | 152B24/wait0 | 1/1 | 实读80B，更新现有ordinal0/current20B |
| VEF Close | 152B25 | 1/0 | 转发同H到BB OUT1 |
| BB Open | 216B24/token55/waitFFFFFFFF | 1/1 | 实读、比较变化、更新现有expected16B |
| BB Close | 216B25/token55 | 1/0 | 转发同H到InfraImaging OUT1 |
| Imaging Open | 216B24/token55/wait0 | 1/1 | 实读80B，更新现有五字cache |
| 最后Free | 216B23/opt2/token55 | 0/0 | 退役，live0；不再追加Close |

三份80B1000/0104/38/1通知依次携带PinMemIN0/VEFOUT2、VEFIN1/BBOUT1、BBIN1/ImagingOUT1完整描述符。同一unit/handle/offset0沿链传递，没有每跳Share、没有独立生成文件或提前Free。

## 真实状态生产与现有缓存权威

VEF的runtime status22来自原accessor backing+22，不等同NoMem state2。构造raw5f8324把whole+20写0；已实现的SetPath(1)完成raw109c3c..109cde通过原setter写入原请求path1，因此追踪值为**1**。新字段记录known、writer_generation和writes；只在原虚拟SetPath工作及读回成功后产生，不在第六边临时强写。

`run-32p8nupi`已记录该真实虚拟producer的status1/known1/gen1/writes1。第六条仅检查这一前驱；0f/11的设备分支不选中。原CP全局writer/RAM未验证，known范围限当前owned profile。

传播更新同一个owner的实时数据，不另造冷缓存：

- 第四边 `.format.current` 的ordinal0更新为20B `0100000000000000010103008007000038040000`；旧ordinal1保留。
- 同一第四owner `.format.expected` 的BB表更新为本次16B格式；原首次command_current、commandFnv、prepare/execute/match历史保留。
- 第一边 `.format.cache` 更新为 `{1,1,1920,1080,3}`，消费计数从1到2；原first handle/FNV/Free/AP完成历史保留。

三个接收API各检查唯一开放consumer引用并实际读80B；Open/Close/Free与消息身份验证由第六端点负责。坏包不改变旧owner缓存；流程中途失败保留真实已发生的局部更新和live handle，不回滚成“从未发生”。

原InfraImaging key0 reader raw582abc只检查SSYN/ETRY/key，不筛header版本/type。本地parser有依据地新增**01/type0**这一有限配对，原06/type1构造不变、交叉配对仍拒绝；没有无边界放宽未知格式。

## 接线、测试与限制

新开关：

```sh
A7C2_VEF_PINMEM_INPUT_CONNECT=virtual-vef-out2-pinmem-in0-forward-format-v1
SEED_BACKUP=alllang
```

默认关闭，要求第五边及完整publicALLLANG/a0d/同256GB目录SD、new UI/firstboot/自然快门/安全导出链。typed manifest固定九操作、三跳、状态生产前驱和cache变更；运行验证字段仍false。

本边source是VEF，因此observer先对这个显式端点派发，由guard10取得一次公共资源锁；不相关请求返回0后继续旧`full_vef_resource_send_enter`。这样不会嵌套获取同一gate，原VEF Get/旧连接锁语义保持。

253场景使用真实五边前驱、现有映射池/三个权威cache，核同H、引用/计数精确增量、全部通知/SSYN损坏、source身份、分配/发送/释放、in-flight free、重入/fork、早未准入和部分失败保存。主联合1364/139通过，所有生产C/H/脚本前后SHA不变。独立709审共享原语、c9eb审完整端点与observer边界，均未发现P1–P3。

## 本轮原运行验收

本轮observer `7ed5983503c6cfe1366b4c83a7869208c68465778859bf24ed9a121bcb2542dd`/291冻结源，同一a0d候选；console SHA256=`f4566a8bc1e7b38ad9575148bfd420c9e790515c92aba9e5a1b3612e56c262b5`，同轮归档=`23f2fef5a41e48590c6e6885300ff62db863f4575aa42cd28772f3802d0766a4`。初ABI归档bbf9…与run自动重压gzip不同；验收硬pin初ABI仍在，run归档按本轮receipt校验，所有291文件的集合/SHA逐个必须等于ABI绑定的宿主回归输入，不能只凭归档时间戳判断源码不同。

console12505..12570给出完整第六事务：H=8c00承接同池第4代，无reset；packet FNV `cc29c69bf5fe4b52`、payload `37228cd728b41c0d`，九DMM/三同H通知与每跳实际读取后，VEF current20 FNV `dd5cab073ba410f8`、BB expected16和Imaging五cache均正确更新。原commandFnv `3c3a32bb6809f4cc`、第四原payload `1a3c540ebc5023bd`及旧ordinal1等历史保持。原AP259/TID382在最终Free后消费唯一回复；本轮六笔完成均free0/fault0/ap1。

两次原Fsysflush0 seq1460866617021147/1460867546029634（pid259/tid344/drive65）、STOP恢复、三文件路径/大小/SHA与两export全等、cleancommit和owner321925/组/QEMU退出/双锁独占均通过。独立8da重放全断言、核实际initramfs/源码/库/消息数据/锁，额外11个破坏反例全部拒绝，未发现P1–P3。

仍有七条Connect拒绝、302c未完成、EE0、JPEG/MP4零。控制格式变化不是图像帧或PCM；第七边正进入实现，其余边分组并行调研，只有实际消费才更新通过字段。
