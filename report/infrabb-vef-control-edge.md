# 第五条控制边：InfraBB type8 OUT0 → VEF type8 IN0

`run-32p8nupi`已通过第五条有状态控制连接：原AP258/TID381消费唯一56B完成并释放rc0/fault0/ap1，owned表实际查出ordinal14且未选格式后处理，前四条历史及本轮SD保持。1102项联合回归/139子测试、原ABI和独立本轮内容复核通过。见[五边收据](five-edges-native-proof.json)。`infrabb_vef_control_connection_native_verified=true`仅指有限虚拟控制边，`capture_verified=false`。

## 这条边的源合同

实际端口为source `{8,2,0,9284074a}`（BB21对象slot9/object1789514）→sink `{8,1,0,905a0048}`（VEF16对象slot14/ordinal14）。早启动和拍摄图阶段均曾实际发同一条请求，AP caller会变化，不能固定前轮81cf61c4/61c5。

公开CP原件SHA256为`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`；下表为raw，CPVA=raw+108000。

| 原地址 | 内容 |
| --- | --- |
| fe7898 / fe797c | BB source属性 `{8,2,0,9284074a}` / 对象1789514 |
| c412b0 | VEF构造记录 `{index0,type8,dir1,SID905a0048}`，重排为pin属性后构造 |
| c40ed8+284 / +28c | VEF实例实际虚表指向5f8628 ordinal查找、5f868c对象查找 |
| 10c748 | sink peer Connect→583818保存peer/state0、发8100 |
| 10c7e8 / 10c820..2c | sink后处理仅选择ordinal1、2、3；ordinal14走10c860 OtherPIN并返回 |
| cdc16→ce02c / cdaf0→cdec2 | BB0001与8100分派→5835ca/5839a6 |
| ce08a..ce09a | BB type8跳过独立marker分支；不能复制第二条边的01acad0f写入 |
| cec90 / cec9c | BB source direction2立即退出格式posthook |

父独立核完整表、对象、实际虚表和7段摘要，证据`infrabb-vef-type8-control-source-pins.json`。本边**无marker、DMM、SSYN、currentinfo更新、f008命令或新时钟/MMIO工作**；这来自具体ordinal/方向分支，不是对type8的猜测。

## 有状态消费与前驱保持

64B原Connect→64B0100 peer请求→72B8100 peer回复→独立56B8001 AP完成，完整S/P/SID、source1→2→0、sink1→0、peer读回/pending清除。控制消息outer replySID0、OSAL source按完整owner设置，回复目的地取原dynamic caller。

要求前四条边同PID、clean/AP已消费、第四同步命令已返回/格式匹配/缓冲退役，新的slot9/14冷态Get回复释放。VEF owned table真实查到ordinal14，记录键/状态与`owned_table_readback=1`后才认定posthook未选。旧第一/第四格式cache、ordinal0/1、NoMem、AB失败/AIP S0、其它端口和mapped backing前后保持。

早启动前驱未就绪只增加unadmitted_count、返回caller-owned拒绝，不消费一次性requests或置fault；拍摄图阶段可正常准入，同一owner没有reset。准入后的失败则锁存故障/保留所有权，重试不能清历史。

## 开关与测试

```sh
A7C2_INFRABB_VEF_CONTROL_CONNECT=virtual-infrabb-control0-vef-control0-v1
```

默认关闭，要求第四边及其完整publicALLLANG/a0d候选/同256GB目录SD/new UI/firstboot/自然快门/安全导出前置。guest为`MENU_INFRABB_VEF_CONTROL_CONNECT`；host intent的运行验证标志均为false，不代替实际消费。

`infrabb-vef-control-connection.c/h`复用原BB/VEF registry和公共资源guard9，日志前缀独立；外callback在私锁外，发布前复查fault、预存wire后send、inline及in-flight free防重复释放，失败后clean=false保留，未排队原request仍归caller。

新增109场景覆盖完整真实四前驱、两dynamic caller、早拒绝后晚准入、owned ordinal读回、独立allocation/正确owner/坏消息/分配发送释放错误/fork/递归/并发free和历史保持。host profile195项/139子测试通过；父43模块联合1102项/139子测试通过。独立863实现/接线review无P1–P3。

本轮compiled observer为`7cc66542d4e387d3341c47cdd9d09e8ec68a31e25df4f6f6eacfec21581d33c9`，291冻结源；console SHA256=`95a49ca45adfe64ee150c781070ca12d2f981fda38a183eb10a087f082630198`，同轮源归档=`669349fe15e9bf159b6f4992daecfb02f532ae2212ef854813e6aadbaa079da6`。归档构建未链接第六端点，未把并行未链接测试文件的变化算已执行代码；启动意图明确列出那一项变化，其余已编译输入/二进制身份保持。

console12446..12455的实际五边消息检查通过。更早的SetPath真实虚拟完成记录status22=1/known1/writergen1/writes1，独立于NoMem state2，来自producer而非第六边强设。共享forward接口虽已编译，本轮没有直接运行计数读回，因此不据缺日志宣称forward counter实测为0；第六仍未运行。

新严格验收脚本实际验证5组全文握手与same-waiter释放、两种mapped格式、引用退役及所有8负边。编写代理中断前已完成17项self-check；父修复“通用files索引应包含全部原库”的错误假设：所有12个选中initramfs原库仍逐个读回SHA必须一致，索引本来存在的再交叉核对，8项索引遗漏如实记录。没有伪造字段、没有删除库读回。父执行全断言通过；独立981又核291源/原库/实际initramfs与observer/QEMU、重放评价器和SD锁，无P1–P3。

两次真实Fsysflush0，seq1459520496165822/1459521423143526，STOP恢复、host三文件尺寸/SHA与两export全等、cleancommit及owner301377组/QEMU退出/双锁实际独占通过。该run仍8条Connect拒绝、302c未完成、EE0、JPEG/MP4零。

第六条将真实改变格式并经过三级转发，不能套本条无格式分支；其另行构建和原运行验收中。
