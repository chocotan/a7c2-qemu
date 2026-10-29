# 镜头产品/光学资料核验

三原件SHA/大小通过；[verify.py](verify.py)实跑退出0、53项PASS（[结果](verify-results.txt)）。仅写本目录，未运行固件。

- E1→F1：AP351fdb8以分支做wire0/1/4→model2/1/0；CPa4950a/a49510拼00040100（LE字节00 01 04 00），无独立AP表。
- E2→F2：P=*[1a03cdc]，u16LE[P+67]是独立身份键。8B资料全零才由a99862查1107184/rawfff184的98×16B表；键≥1000h先/10。记录为u32键/指针/8B资料。完整产品枚举名、上游回包生产者未知。[域](lookup-domain.tsv)。
- E3→F3：a99942/a999de→a497fa：L+14/1c为焦距范围{mm×10,10}，+24/2c为光圈范围{BCD十分位,10}，均为u32对。formatter40cbd8实际引用%d-%dmm与F%s-%s；第二端零则复用第一端。AP3520a48..54取前两分子到事件+5c/+60。当前焦距、端点排序未闭合；不能混用当前光圈u16尺度。
- E4→F4：状态4选10faaec/rawff2aec的a0B模板，初始缓存10e2e80相同。四组{0,10}及----，含非零能力；+88/+8d动态，前8B零。a49898重置范围/名称。NONE产品语义未闭合，模板非完整2044包。

原VA/raw/指令：[AP](ap-pins.txt)、[光学](ap-optical-copy.txt)、[CP](cp-pins.txt)、[模板](cp-tables.txt)。Path为上述callflow；时间线见EARLYREPORT.md。libObj仅核身份。

## CP 镜头装载回包产生者+队列（main已核代理取证，本轮）

代理（deepseek）取证`scratch/lens-attach-producer-deepseek/`（REPORT.md，含E1-E9证据附录），main独立复核CP原字节（Thumb，CPVA=raw+0x108000）确认属实：

- **产生者链**：`a494e4`（raw 9414e4）建镜头状态块到`0x19ee084`，wire立即数`a4950a`=movw r1,#0x100/movt r1,#4=`00040100`，经`ldrb [0x1206d4b]`移位映射0/1/2→0/1/4。唯一消费者是0x2044子块getter `8d6cc6`（raw 7cecc6），表项`d937e0={0x2044,0x8d6cc7}`（main已核字节`44 20 00 00 c7 6c 8d 00`）。
- **载体**：type-6通知、子码`0x2044`，OSAL**源`0x90030001`→宿`0x80020002`**（main已核发送方`b1fb5c`：movs r2,#2/movt r2,#0x8002；源stamp `4b3c88`：movs r1,#1/movt r1,#0x9003）。全量快照`353c18`→0x2040（0x6d4B）、增量`353c3e`按脏位逐条发（0x2044=索引46）。

**未闭合（诚实）**：标记表项46脏位的attach/detach事件未钉——`8d9fd6(opcode)`全部5个调用方传`0x2001/0x2049/0x204f/0x2051/0x2035`，无一传`0x2044`（main已核该结论的取证逻辑）。AP接收端偏移沿用prior报告未重核。这是**产生者+队列已钉、attach推送触发未钉**的部分闭合。

## 当前焦距（live mm）AP读取链已钉（main已核代理取证，本轮，部分闭合）

代理（kimi，`scratch/lens-current-focal-kimi/`）追当前焦距产生者，main独立复核AP原字节（ARM64）确认关键pin属实。**当前焦距 = `u32@0x7e5c428 / u32@0x7e5c448`（分子/分母），有效性 `u32@0x7e5c408`**。

- **UI消费 0x23d1e78**（main已核0x23d1f70 `ldr w19,[x3,#0x2da8]; ldr w1,[x3,#0x2dac]`+`udiv`）：model+0x2da8/+0x2dac 相除，有效性 model+0x2da4。
- **model同步 0x2e3ce80**（孪生0x2e46eac）：经指针getter填充——`287ed34`→num `0x7e5c428`（main已核adrp链 0x7e50000+0x4d8+0x5b000+0xf50）、`287ed5c`→den `0x7e5c448`、`287ed0c`→flag `0x7e5c408`。
- **传播器**（main已核）：全.text扫描**无绝对STR到num/den**；它们经getter返回指针被写——num `0x29fa22c`（store @0x29fa24c，源=`0x835e780`）、den `0x29fa194`（store @0x29fa1b4，源=`0x835e7a0`），另镜像到0x83ae760/780/7a0。flag有绝对setter @0x27671cc。
- **与身份键/范围的关系（重要）**：当前焦距**不在**P记录（`*[1a03cdc]`，键`u16[P+67]`）、**不在**2044 a0B镜头块（2044只带范围{min,max}*10,10与名字）；2040全快照转换器`3549330`**不触碰**焦距字段。当前焦距是**独立属性槽**，与当前光圈(201b)平行。

**未闭合（诚实）**：主源槽`0x835e780/0x835e7a0`也无绝对写入者——经属性DB指针表间接写；**谁写它们、值是否来自CP**（2040的某20xx块或独立notify）未钉，需动态watchpoint或DB set表解析。这是**AP读取链已钉、最终产生者未钉**的部分闭合。
