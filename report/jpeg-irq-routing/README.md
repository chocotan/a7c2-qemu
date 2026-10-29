# JPEG完成中断：LIRO注册与Linux路由

公开原件的JPEG device0完成中断注册号已核为61（3d），其余四路62..65；不能把此前的syncsel表45..49当IRQ号。以下是源码与字节证据，尚不是guest JPEG运行证明。

## 原件与复核

`runtime/analysis/menu-root/system/av-cam.bin` SHA-256 `90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`；`runtime/analysis/menu-root/usr/kmod/liro.ko` SHA-256 `b4bd80cc614751e0092ee19e89cb90632db580bc01f23f1a1df23544e9b10186`。主会话独立复核8个原字节窗口，共2168 B，见 [source-pins.json](source-pins.json)，该文件初始SHA-256 `29c98c8d42affad009fd1fd601910e76114c6c2df9f37ed71e0fe291d99100ba`。

下面K为av-cam的raw偏移，不使用CP的raw+108000规则；其运行KVA按原模块基址ffffffc001000000加K。liro函数地址注明.text偏移，source-pins另记录实际文件raw offset。

## 注册与handler

K2f934的生成式注册函数在K2f950..2f96c遍历Kbd6d38、stride20，每项加载u32编号，再把后移8字节的T_CINH地址传给K2ee1c（LIROdef_inh）。

| device | 编号 | descriptor K | T_CINH K | handler K |
|---:|---:|---:|---:|---:|
| 0 | 61 / 3d | bd7358 | bd7360 | 2aef90 |
| 1 | 62 / 3e | bd7378 | bd7380 | 2aefe4 |
| 2 | 63 / 3f | bd7398 | bd73a0 | 2aefec |
| 3 | 64 / 40 | bd73b8 | bd73c0 | 2aeff4 |
| 4 | 65 / 41 | bd73d8 | bd73e0 | 2aeffc |

各T_CINH的三个原u64为0、实际handler KVA、1；这是文件内已赋值数据。K2ee1c从模块API+2f8取函数，liro实际从.init.data复制698字节到API+48，而.init.data+2b0重定位指向具名def_inh：48+2b0=2f8。绑定有复制与重定位证据，不是按API序号猜测。

liro `def_inh(.text+1778)→os_request_irq(.text+1378)` 调内核 `subsys_request_irq`，携带原61..65、wrapper `.text+16f0`、flags10000、名字和对应JPEG handler。CPU选择会按内部位图规范化，不能只凭描述符1写死。

Linux wrapper按编号查inhs、核CPU，经SIMD/FP保存包装调用实际handler；JPEG各handler设置device索引0..4，汇入K2aef98→K2afcf8读回/处理设备状态，再发原12 B事件。返回后，LIRO wrapper向KVA **fffffffff13a2010写原61..65** 并执行dsb sy，才返回handled=1。完成模型不能省掉这个额外应答。

## subsys_request_irq不改编号

官方GPL内核 `linux-kernel/drivers/misc/subsystem.c`（完整文件SHA-256 `07b3c54ff25f59b7222f084cb94e1d1c0375262bd760e8a56b06dfe1cb833acf`）的85..115行使用同一irq调用 `irq_to_desc` 和 `request_irq`，设置IRQ_NOPROBE/IRQ_NOAUTOEN、handle_simple_irq，清disabled并把depth置0；该函数没有编号加减转换。

这闭合LIRO61→Linux IRQ61的源路线。后续编号调查进一步核原DT、实际公开内核GICv2代码和UDIF固定分配；结果见下节。

## GIC编号合同已闭合

官方DT节点 `/interrupt-controller@f13A0000` 为arm,gic-400、linear-map、无linear-offset，GICD=f13a1000/1000，GICC=f13a2000/2000。公开 `vmlinux.bin` 6,610,952 B，SHA-256 `620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2`；其OF记录的实际callback在raw5dec60，字节 `2c64640880ffffff`，指向GICv2 gic_of_init（raw5c642c），不是该镜像中的另一份GICv3同名符号。

关键不只是linear-map：原 `udif_map_irq` 实际raw5d0048..5d0054为 `02078052 01048052 5d36f997`，给udif_alloc_irqs传base32/count56。官方 `drivers/udif/mach-cxd900xx/platform.c:526..547` 构造SPI=irq_base−32，并固定要求Linux irq_base调用__irq_domain_alloc_irqs；586行保留32..87。GICv2 translator把SPI加32、allocator逐项建立virq32+i↔hwirq32+i。该范围没有被之前UDIF表项/GPIO/PPI占用；动态IRQ下界为288。固定分配失败是初始化错误，不能暗自改成另一组编号。

| device | Linux IRQ / LIRO EOIR值 | GIC INTID | SPI / QEMU外部输入 |
|---:|---:|---:|---:|
| 0 | 61 | 61 | 29 |
| 1 | 62 | 62 | 30 |
| 2 | 63 | 63 | 31 |
| 3 | 64 | 64 | 32 |
| 4 | 65 | 65 | 33 |

原GICv2 gic_handle_irq读GICC+0c、通过domain查映射；LIRO的KVAfffffffff13a2010由已证静态IO alias映射到GICC+10（EOIR）。QEMU当前候选源的hw/intc/arm_gic.c:382..395对外部输入加GIC_INTERNAL=32，所以输入29产生INTID61。主会话独立核原内核完整SHA、上述OF callback和32..87分配指令、官方GPL分配函数及当前QEMU输入语义；新增 [irq-number-contract.json](irq-number-contract.json) 与早期注册pin文件分开保存。

这证明编号和地址合同，不证明实际guest已成功注册/启用/设target，也不证明状态清理、DMA输出、IRQ触发/ack已执行。第一份source-pins.json的GIC=false只限定当时注册锚点的覆盖范围，未将后续证据回填为旧运行结果。

Evidence E-reg为五项原描述符、注册循环、API重定位及wrapper；Finding F-number为真正注册号61..65，并由GPL封装原号传递；Path P-IRQ为设备状态→原LIRO/Linux handler→JPEG事件→原编号ACK。实际guest注册/中断消费、DMA、真实JPEG产物/Fsys仍待验，`capture_verified=false`。
