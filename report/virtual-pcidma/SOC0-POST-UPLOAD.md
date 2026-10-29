# controller0 上传后控制与平台 link 判据

7bda调查代理只交付`EARLYREPORT.md`和静态partial结论，没有完成或执行验证器。主会话保留其原结果，并另编写、实际执行`verifiers/verify_soc0_post_upload.py`：原Image身份、60条指令pin、4个完整范围hash、ops指针与两张four-lane分支表通过。不是runtime／状态producer验收。

原Image基址`ffffff8008080000`；以下代码位置为raw offset。

## 原平台 link callback

probe 2497D0..2497E8把`45FED0`写入ctrl+158的ops字段；该表+18为`249330`，非空。通用dispatcher 246768先读这个回调，只有NULL才走DBI+72C默认谓词。

原249330完整函数经字节hash及指令核定，读取W+201B8、取bit1作为返回值。因此实际原SoC链路判据为**W+201B8.bit1 (`RDLH_LINK_UP`)**。W+201AC.bit2是LTSSM控制，W+200AC.bit2是SRAM初始化状态，三者不能混淆。兼容TEST root host或通用DBI默认link检查不能替代此平台回调。

## 上传后有限控制

| 地址 | 已核消费方式 | 不能推导的状态 |
|---|---|---|
| W+20018 | bit29已置位时才清除PHY_POWERDOWN，随后barrier/delay | 不证明PLL／lane已校准 |
| W+20380 | bit4已置位时清CLKREQ_FW；置PERSTN_MASK bit1 | 不产生SRAM／lane-ready |
| W+20380 / W+2038C | 已有63pin合同：设置debug selector1F0000后读lane状态，lanes4以低F为零成功 | 不能把只读status恒零 |
| W+20274 | mask78FFFF；先读、清mask并写、再读后OR mask写 | 不是仅一条OR写，也不等pending已ACK |
| W+20278 | 同上，mask04000000 | 不产生IRQ或DMA完成 |
| D+710 | `(old & ~003F0000) | 00070000`，four-lane跳表已核 | 控制值，不是link-up |
| D+80C | `(old & ~1F00) | 0400`，cold host setup另清再置bit17 | 控制值，不是lane校准结果 |
| D+890 | 清bit0 | 不能混称AUX频率 |
| D+B40 | 写1，是AUX频率设置 | 不证明实际时钟波形 |

W+20380.bit6和D+8BC.bit0是已独立核过的DBI写许可序列，原Root Port config身份与资源必须保持真实。以上寄存器的其余位／reset值／延迟没有由本次静态检查补造。

## 仍未闭合

SRAM-init bit2 producer、lane状态producer、真实link训练与peer条件仍缺。SRAM timeout后仍apply、link timeout后仍notify等历史失败语义保持，不能把通知或control latch当成功。弱boost/timeout hook与可选ASPM分支来自GPL线索，本次60pin验证不额外声称已闭合所有这些callee。

主会话另外检索了公开同名SRAM-init接口，仅找到Rockchip／其他IP类比，未建立CXD90057信号绑定或timing证据，不用于放开本机原host。当前[SRAM数据子层](PHY-SRAM-CONSUMER.md)仍不发布bit2／lane-ready／link-ready。

## DBI 路径白名单（soc0-dbi-path，290pins 原件核验 PASS）

主会话实际复跑`scratch/soc0-dbi-path/verify.py`退出0（verification.log）。19步白名单带指令位置，关键语义：

- ro_wr_en/dis内联：`W+20380.bit6`清/置与`D+8bc.bit0` RMW顺序核定；VID=`104d`、DID=`911d`、class=`0604`均为**16位写**（最终`245e2c: strh w2,[x0]`）；`D+03e`单字节；command=`(old&ffff0000)|107`；中断行/脚`(old&ffff00ff)|100`；bus numbers=`(old&ff000000)|00ff0100`。
- shadow BAR：`D+100010/100014`写mask `ffffffff/7fffffff`，`D+010/014`写值4/0；`D+8d4` AXI timeout仅weak hook返回0..1ff时写（默认不写）。
- AER：下游配置读前`D+104`写`ffffffff`（W1C清除），读后非零则回写观测位并使配置失败。
- iATU：`D+900==ffffffff`才选unroll（`300000+index*200`，寄存器组08/0c/10/14/18/00/04）；否则viewport按序`900/90c/910/914/918/91c/904/908=80000000`直写，`908`读回bit31最多5次。下游01:00.0：region1 type4、target`01000000`、CFG0 `dffc0000`读取；root 00:00.0首读直接`D+0`不经viewport。
- **不能当普通RW**：`710/80c/890/b40/8d4`指令只证明访问用途不证明整字可写/reset值；`004`上16位status、`104` W1C、`8bc`许可控制、BAR mask语义、capability链表位置与只读值均未闭合——两个setup body不读`034` cap pointer也不搜索PCIe cap，不能用全零/伪造capability值宣称闭合。

源文件保留在scratch（research evidence）；静态合同不代替硬件/runtime验证。
