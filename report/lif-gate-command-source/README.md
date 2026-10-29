# LIF gate命令Q的实际请求来源

Q=u8[1b18cd5]有明确请求writer：key2、indexab、opff、payload长度1时，从request+30复制实际字节到Q。没有闭合原启动时的最后一次写入或初值，因此不能默认Q=0，也不因此发布六字段零。

范围为公开CP只读静态核对；没有运行VM/网络/硬件/物理SD，不使用private/full数据，不修改运行时或伪造请求。原禁用分支及Q依赖见[完整返回合同](../lif-disabled-gate-return/README.md)。

## 请求解析和写入方向

偏移均相对a75814收到的原请求，数字为十六进制：

| 字段 | 实际宽度/作用 |
|---|---|
| +26 | LE16，取低u8为op；ff写、fe读 |
| +28 | LE16 index |
| +2a | LE16 key；2经df27d0表项到a75994 |
| +2c | LE32 payload length |
| +30 | 写payload起点 |

原局部handler没有验证整个请求buffer可访问长度；严格consumer必须独立检查request+30及声明payload的extent。a759a4..aa比较u32(index+length)<=100，未独立检查加法回绕。

请求表位于1105e58，共400字节、100项（256项）。indexab项1106104原字节`d58cb101`，目标1b18cd5；最后indexff的目标为19f8617。

a75994只取一次table[index]，然后连续memcpy length字节；不是按表逐项复制。opff先copy(request+30→512字节栈临时区)，再copy(临时区→选定指针)。opfe则反向读pointee并写reply区域。返回0只是这个handler的结果，不是命令分支已执行或gate已关闭。

## 覆盖Q的宽写入

| index | 原指针 | 最短覆盖Q的length | Q来自payload |
|---|---|---|---|
| 0f | 1b18cd4 | 2 | +1 |
| a2 | 1b18cd0 | 6 | +5 |
| aa | 1b18cd2 | 4 | +3 |
| ab | 1b18cd5 | 1 | +0 |

按普通不溢出的边界，indexab可接受最多55（85）字节，不能只认单字节ab事件就宣称跟踪了所有Q写入。任何实际历史consumer都要按完整目标区间与Q的交集更新它，并拒绝整数回绕/缺字节；本次没有新增这种writer API或ACK。

## 初始属性和剩余时间边界

已验证000d003a的256字节payload写到1ac029c..1ac039c，不含Q。所读74项context表没有context恰好等于Q；这不是所有属性、构造、别名写都不存在的证明，也没有展开整个初始schema。

E1（原op/key/index/length解析）→F1（请求边界）；E2（256指针表和连续copy）→F2（单字节与宽写覆盖）；E3（现有初始属性目标范围）→F3（不能从该属性给Q初值）。首个缺失仍为真实请求payload、发生顺序及selector前最后一次覆盖。只有真实输入建立Q及后续历史，才可应用[条件禁用路径](../lif-disabled-gate-return/README.md)。

[source-pins.json](source-pins.json)给出4窗口1444字节。主会话独立核其摘要、原copy方向、256表和Q项。`Q_runtime_initial_known=false`、`published_zero_projection_verified=false`、`capture_verified=false`。
