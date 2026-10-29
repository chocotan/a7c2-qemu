# 0401资源输入：公开BK4中的候选完整块

0401的两个header gate背后是有ID/容量的shadow资源，不是两个独立布尔开关。
原表和入口已静态闭合：

| 原CPVA表行 | ID | CP shadow地址 | 注册容量 |
|---|---|---|---|
| d530dc | 02a40000 | 17929b0 | 1200hex =4608B |
| d53184 | 02a4000e | 179d0b0 | 700hex =1792B |

23cc28构造ID/目的/容量vectors，注册749a71 callback。be9e0c按收到的ID
分派payload；749a70把参数重排为(destination,payload,length)，再经
522214/522218 veneer调用原61e60c复制。因此这些bytes可随收到的shadow
消息更新；开机BSS零填不能证明请求时的值。已查dispatch没有显示将收到的
length与注册容量比较；新的仿真backend必须做边界检查，不能默认已有保护。

## 公开seed中实际找到的内容

唯一读入文件仍为原官方ALLLANG更新包的seed副本，2390264B/SHA256
`3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47`。
两个BK4记录的结构/checksum均通过。offset0的section2a4属性数为0；
offseted000的第二个记录有两份完整属性，attr均8：

| ID | 长度 | value SHA256 | 前16B |
|---|---|---|---|
| 02a40000 | 4608B | b0e4d474fb6f284f0b2e9e0f43aafd41dca9b08d508abf90ba280d92f5d42d5b | 003366c09e8080581a00860509339022 |
| 02a4000e | 1792B | ec7c6dfb463622152c086767a50a5a793838efd2273fbfd7c191dc0481a5bbf2 | 00000000000000000600000000000000 |

这是公开原件的值和长度，不是真机setting，也不等于已观察到的CP RAM。
若未来明确支持从该公开记录建立虚拟资源，必须消费完整块及真实后续更新，
不能只取gate字节。该候选的byte0/byte1分别为00/33，另一块byte0为00；
不选择它们为当前分支，更不把33改成负数跳过原77241e工作。

```sh
python3 report/cp3006-start/verify_public_seed.py
```

该只读工具已扩展为四个已知所需key。小标量输出原bytes，大块只输出
SHA/前16B/offset/length，避免把完整原厂资源混入代码报告。所有其它文件
仍在解析前由固定size/SHA拒绝。0051001d/003100a6的旧结果保持不变。

## 装载衔接仍未闭合，不能把查询当复制

主会话核对be901c：它锁定256个bucket、逐ID查be98c6，再由be8fc4→be995c
累计长度或写入调用方size表。**这不是shadow payload装载/复制函数**。
be995c是属性长度解码，遇大块读取该记录中存储的长度，不生产资源内容。
因此“23cc28调用be901c”不证明上述公开块已经复制到17929b0/179d0b0。

Backup_init_cpapp的55df9c建立primary header/table pointers
1a7e85c/e860/e864；55e014另建secondary pointers1a7e868/e86c/e870。
be98c6当前已查路径用primary表。公开seed两记录的属性存在性不同，不能
把第二记录的值当primary运行值或悄悄合并。原55e508的当前已查入口调用
backup_process_start，不是已证明的两表merge。真实record选择、装载、
消息更新顺序和与worker并发的snapshot边界仍待闭合。

## 不变的0401工作前提

24d5c0入口的临时U为4ccB、link L为24B，W是c8B浅指针视图；nextBank
stride19fc。原23cef0的多段复制、真实stack descriptors、静态资源写入和
77241e结果生产均不能跳过。此次只闭合一层资源和候选数据来源，未证明
frame/pool/硬件等待或其不存在，未实现0401/3006成功backend。

## 已归档的上游缺口（按用户优先级暂停）

最后一项在途只读调查独立确认55dca4→55dcc6→55df9c把既存04000000
直接绑定primary。55dca4没有直接Thumb BL候选，55dca5函数指针唯一命中
eb5658初始化表项；尚未闭合表dispatcher及在此之前填充04000000的producer。
这是有界缺口，不证明上游不存在，也不支持把第二BK4提升或合并成active。
按用户“无需死磕、先做其它”的要求，暂不续查这条配置链；下一入口和原始
证据保存在scratch/cp-active-primary/REPORT.md，不再描述该代理为运行中。
