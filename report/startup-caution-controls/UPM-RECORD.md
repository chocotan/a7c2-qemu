# 原UPM对启动记录的消费

本记录服务于“启动参数是否导致错误”的假设核查，不据此宣称loader全部字段与真机等价。
原件为native `menu-root/usr/kmod/upm.ko`；Kuna按符号名反编译，关键存储指令用原objdump复核。
下面地址为原ET_REL `.text` section内偏移，不是appFw ELF VA或CPVA。
Kuna JSON中的4xxxxx为其合成装载地址，不作为guest runtime地址使用。

## 已证字段路径

| 原位置 | 证据 | 可以确认 |
|---|---|---|
| k_upm_setup_boot_factor 3cd8；3cfc..3d18 | Backup_nread(0051004a,buffer,80h) | seed-power-on与原UPM使用同一128B启动记录 |
| 3d88..3db0 | 从记录+4开始复制10个u32到UPM状态+0c..30 | record[1]/[2]/[3]/[5]不是未消费的任意填充 |
| k_upm_setup_boot_factor_default 4188；41b4/41bc | w2=2，store到同UPM状态+0c | seed缺省mode2有原默认值依据 |
| 3d80..3db4及3f28分支 | 额外Backup0051000f为c时，可能覆盖部分复制值 | 不能仅凭seed打印值等同最终UPM状态 |
| 3dc0..3dec | 写Backup0092001b/1c | 原启动记录消费还伴随原内部配置更新，不是只读enum比较 |
| k_upm_init_boot_factor 41d8 | 注册同步callback80924127，再走原setup | 必须保留原服务消费者，不在AP模型里直接硬写boot结果 |

主会话独立核了3cd8函数prologue、Backup调用和3d88后的原load/store，及4188默认函数的明确常量2。
Kuna输出支持相同复制/覆盖逻辑，没有在这些函数中找到SD/Fsys错误判断。
这不能证明下游不会根据boot字段选择不同的媒体/初始化流程。

## 保留的未知项

`seed-power-on.c`当前在mode原值为0时补2，固定boot_type1，并在eecap/bis为0时补1；
这些是显式实验loader描述符。原UPM消费和合法范围不等于已经恢复原cold-boot的完整几何/上下文。
特别是额外0051000f及其它启动记录可能影响最终值，不能盲扫1..8或把一个能出图的分支叫作正确。

后续通过当前原sequence对象的只读字段捕获与真正dialog消息/producer继续判断，
没有因此更改boot type、调用未知ABI或伪造媒体ready。
