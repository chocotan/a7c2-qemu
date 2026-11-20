# 原 CP `0xf5410244` 静态归属

本页为既有 [CP 启动进展专题](../2026-11-11-cp-boot-progress/README.md) 的补充证据，主线进展以该专题为准。

本次只读原件并生成小型分析材料，没有修改产品、运行测试、QEMU、socket、固件或设备。结论：原 CP 将这个地址明确配对命名为 `MTG_REG_CDC_FCS_OFST`；它有真实配置写入与读回消费者，不能再简单叫作未知 ready/status 寄存器。其物理寄存器语义、复位值和本次启动可达性仍 unknown，不能据此填入成功值。

## 固定输入和证据

原件 `analysis/system/cpapp-b.bin`，18,090,880 B，SHA256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。只在文件支持区间 `[0x108000,0x1248b80)` 使用 CPVA=raw+0x108000；MMIO、BSS 不作为文件偏移。

本轮证据根：`scratch/cp-f5410244-attribution-20261114/`。`initial.json`、`followup.json`、`named-wrappers.json` 保存对应原始字节、窗口SHA及来源身份；同名 `.asm` 保存 objdump 原指令。所有分析脚本写文件、审查后执行。使用已安装 `/usr/bin/arm-none-eabi-objdump`，没有启动 IDA 服务。

| Evidence | 原字节及消费 | Finding |
|---|---|---|
| E1 `initial.asm` getter | `c0be6a MOVW r0,0x244; c0be6e MOVT r0,0xf541; c0be72 LDR r0,[r0]` | 确认32位读取指令计算地址 `f5410244`，不是未经证实的物理总线映射 |
| E2 `named-wrappers.asm` | `b87cac..b87cc4` 将 `r0=f5410240,r1=4,r2=240,r3=fe27f7` 交 `b83e08`；紧接 `b87cc8..b87cd8` 将 `r0=f5410244,r1=4,r2=244,r3=fe280b` 交同一函数 | 地址与原命名明确配对，不是仅靠邻近字符串推断 |
| E3 `named-wrappers.json` 字符串 | CPVA `fe27f7`=`MTG_REG_CDC_FCS_SEL`；`fe280b`=`MTG_REG_CDC_FCS_OFST`，原始ASCII、NUL、SHA均保留 | 原固件命名可确认；不擅自展开 MTG/CDC/FCS 缩写 |
| E4 `followup.asm` | `b9a882` 的参数结构+0低4位写 `f5410240`，结构+4低26位写 `f5410244` bits0..25，结构+8写bit31；读回并DSB | 它是被配置的字段，不是凭地址就可当作 ready；bits26..30 在该setter被保留，其语义unknown |
| E5 `followup.asm` | `b9a90c` 从 `f5410240/244` 读回，输出 `sel=low4`、`offset=low26`、`over1v=bit31`（最后两个描述仅按结构/原字符串解释，硬件单位unknown） | 对应参数有读回消费者，不能随意置零而称硬件兼容 |
| E6 `followup.asm` | `ba119e..ba11ae` 直接将r0写 `f5410244`、读回、DSB、返回 | 存在独立整字写入口；`writer-xrefs.jsonl` 只有函数指针编码候选 `e99b58 -> ba119f`，未核该表的真实分派/初始化作用 |
| E7 `named-wrappers.asm` | `b89992` 循环四个12B元组，`b899b6 BL b9a882; b899bc BL b9a90c; b899c4 BL b8826e` | 有配置/读回比较式例程；**未确认是启动初始化，不能因采集标签含initialization就视为启动必经** |
| E8 `initial.asm` callback | `c0d03c` 读取 DFS status；计数 `*[1a8b654]>=4e20` 且 `byte[1b1fa2e]==0` 才在 `c0d072` 读本地址，结果作为4B payload交 `c0d8e0` type46，然后置一次性flag | 该已知路径是有限条件下的日志消费；回调是否建立、计数初值/频率和实际读值unknown，不预测下一次fault |

配置路径 P1：命名wrapper `b87ca8 -> b9a882`，读回wrapper `b87cfe -> b9a90c`。普通调用者还包括 `6e0a60 -> b9a882`、`b27c56 -> b9a90c`，均已核邻域指令；不把有限调用者追踪写成全程序CFG。

## 地址族与 Sony 开源内核

原 `b9f128` 程序访问 `f5410a70`，与已有 `final/a7c2-re/report/2026-11-10-a7c2-hdmi-raw-feasibility/CP-CONSOLE.md` 的 P2S 线索一致，但它不是本地址命名的主要证据。命名以 E2/E3 的同一次调用参数为准。

Sony 官方内核本机来源 `sources/sony-ilce7cm2-ver201/`；历史提取收据 `kernel-extraction.json` 标明来源 `https://oss.sony.net/Products/Linux/DI/ILCE-7CM2_Ver201.html`，归档 SHA256 `99a6f717659a87a60fd92475edcfe734f73617874650c6aa1d28ca71e2140d3d`（本轮读了收据，没有重新hash整个归档）。

`arch/arm64/boot/dts/cxd/cxd90057.dtsi:62` 的 iomem 映射声明 phys `0xf0000000`、virt `0xfffffffff0000000`、size `0x0e000000`；`drivers/udif/mach-cxd900xx/include/mach/platform.h` 的 IO_ADDRESS 与 CXD900XX_IO_BASE/VA 给出同样 AP 地址约定。它们只说明 AP 通用映射覆盖此数值范围，**不证明 CP MMU/地址别名、物理译码或此字段的语义**。这些文件完整SHA已记录 `followup.json`。

对上述 CXD DTS 与 UDIF 平台源的有界 rg 未找到 `f541` 或 `MTG_REG_CDC_FCS` 定义；这个否定结论仅限查询域，不是全部内核或闭源CP源码的不存在证明。一次全内核地址片段查询命中其他架构/密码表等无关字串，未作为本地址证据。

## 执行记录与限制

成功执行四次原字节采集/引用扫描（collect_address、collect_consumers、collect_names、两次复用原cp_static_windows，共五次成功宿主命令；按命令计数，不是测试组）。没有测试/设备组通过结论。

两次分析失败均在保存结果前停止：第一版 collect_address 的宽范围候选数超过守卫（rc1），收窄到0240..0248后成功；collect_tables 使用错误的命名字符串VA，断言rc1，因此 **tables-and-kernel.json未生成**，不能把预期表/源清单当成结果。正确的原strings raw `ed73d9/ed740a` 应加108000为 `fdf3d9/fdf40a`，末轮脚本仍为未修复候选；无需它即可由E2/E3确认寄存器命名。失败原stderr由工具会话保留，未另写完整原始日志。

半字边界 MOVT f541 编码扫描得到1624候选，其中附近MOVW低字0240..0248有22个组合，记录在initial.json；部分组合跨越重写，是编码候选不是合法寄存器数据流。没有发现完整32位字面量 `f5410244`，但本次已确认MOVW/MOVT消费者，故字面量缺失不表示无访问。

未恢复寄存器 reset/default、内部时钟单位、硬件触发关系、全部初始化调用链、CP MMU和运行期实际值。没有映射新MMIO或编造ready/ACK。新材料下一消费者为主会话静态证据核收；未执行回收，无新增后台owner/租约/socket。原 `storage.json` 留在本报告目录并如实标记委派轮次结束时未测实占；主会话另立读回与空间补充账本，不改写旧账本，也不据此宣称完整功能通过。
