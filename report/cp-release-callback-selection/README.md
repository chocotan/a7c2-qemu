# release reset callback：选择器、驱动者与输入来源

`3b0674` 已确认是 `3af500` 表遍历器同步调用的、受selector控制的callback。已找到三处直接driver调用和一种能写入reset条件字节的原调整服务请求机制；这些绑定没有证明它是开机构造器，也没有确定首次执行、首次写入或它们的先后。

本轮只读分析使用公开CP原件，未执行请求或固件。`history_complete=false`、`302c_native_verified=false`、`capture_verified=false`。原普通type5配置白名单保持原范围。

## 复核

从本成果目录执行：

```bash
python3 report/cp-release-callback-selection/verify.py
```

需要既有Python Capstone。验证器首先检查原件18,090,880 B和SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，随后核对[15窗口、1,780 B](source-pins.json)的原始字节、摘要、调用点、字段和表布局，以及1,024个条件selector输入类别。后者是源分支的参考计算，不是运行时观测。

CPVA文件映射范围仅 `[108000,1248b80)`，范围内raw=CPVA−108000。RAM字段只从实际load/store指令推导，未减108000读成文件内容。

## callback record与本地同步顺序

表根 `deb8bc`，步长16 B；record8地址为 `deb93c`：

```text
+0: Thumb callback 003b0675
+4: selector bytes 00 01 01 00 01 00 00 00 00 00 00 00
```

真实入口 `3af500` 在 `3af516` 保存输入r2到r5。循环在 `3af5be..3af5c0` 读取 `record[4+selector]`，非零才由 `3af5c4/3af5c6` 以r0=r5执行 `BLX r1`。因此reset callback实际入口是 `3b0674`，实际间接call PC是 `3af5c6`；它收到的是walker的输入r2指针。

每次callback返回后，`3af5c8` 将record推进16 B并取下一个callback，直到指针为0。这个循环给出了单次walk内的同步顺序；没有确定哪一次walk最早执行。也没有给r1–r3附加未经证明的业务参数名。

令D为实际release bank的byte `+1a4`，F为 `u8[1b16148]`。selector来自以下独立字段，不能借中央CURRENT、旧CP cold mode或BB/ADF mode代入：

| 条件 | selector | record8启用 |
|---|---:|---|
| D=0 | 0 | 否 |
| D=5且 `9a7fe2()==0` | 1 | 是 |
| D=5且 `9a7fe2()!=0` | 2 | 是 |
| 其它非零D且F非零 | 3 | 否 |
| F=0，D为1/2/3/4 | 5/4/6/7 | 仅D=2时启用 |
| 其余 | 8 | 否 |

四项映射是原word表 `3af818={5,4,6,7}`。release bank通过 `10ff418` 的实际指针访问；原件中的初始指针值不能充当本次运行绑定证明。

## 三处直接driver调用

| driver真实入口 | 调用 `3af500` 的PC | 实参来源 |
|---|---|---|
| `99247c` | `992526` | r0=`u8[*(C+0xc)+0x328]<<8`；r1=`u8[1b15ffd]`；r2=C |
| `99247c` | `992572` | 相同字段来源，位于另一分支 |
| `993db2` | `993df8` | r0=`99d494()`返回值；r1=0；r2=C |

C分别为driver的原始输入r0。前两个调用受 `*[18b7f68]` 选择的分支控制。source中的C是driver上下文指针；下文调整请求使用独立的P，不将两者混成一种消息。

三处直接调用的存在没有确定driver的原注册或触发源，也不是所有计算调用的完整枚举。当前继续追driver的producer以及D字段的实际writer。

## reset条件字节的一种请求写入来源

已有[APPLY合同](../cp-apply-lif-command-consumer/README.md)核定：在callback内，`3b09c2..3b09ce` 读取byte `1b16270`；只有读值为7才由 `3b09f4..3b0a00` 向release bank+17c写ff。这个条件reset不是已执行的开机初始化证明。

原件另有一条请求机制可写该字节：

| 数值域 | 原件绑定 |
|---|---|
| registry type 4 | record `110f7d4`，通过 `b22f1e` 绑定table/count |
| pointer table slot e0 | `10fedf0 + 4*e0 = 10ff170`，文件初值指向 `1b16270` |
| 调整服务request selector 5 | record `e795b0={5,b2491f}`，handler真实入口 `b2491e` |

registry type4、调整服务request selector5、普通AP type5配置是三个不同的编号域。不能因值都是5，就把普通type5前缀当作已执行了这条调整写入。

真实函数 `131bd0` 在call PC `131cc4` 调 `b22f1e(4,10fedf0,100)`，此处100为十六进制。绑定函数遍历 `110f7a4` 的12 B records，将table/count存到匹配type的 `+4/+8`。注册函数存在不证明本次初始化已经执行，table也仍是可写绑定。

调整dispatcher真实入口 `4b7730` 从请求P读取字段：

| 字段 | handler实参 |
|---|---|
| `u8[P+0x26]` | r1 |
| `u16le[P+0x28]` | r2，即index |
| `u8[P+0x2a]` | 调整request selector |
| `u8[P+0x2b]` | r3 |
| `u32le[P+0x2c]` | 第五实参，即n |

只有 `(u8[P+0x26] & 0xfe)==0xfe` 的该分支进入上述调整handler表；在 `4b7980` 实际 `BLX r6`，r0=P。分发前还有原 `b25aa8` 调用，未在本轮将其视为无副作用。

`b2491e` 以32位index+n与注册count作无符号比较，通过所选分支后取 `registered_table[index]`。当r1=0xff时，`b2497c` 将P+0x30的n字节复制到临时buffer，`b24986` 再复制到所选目的地址；两个调用均为原ARM `61e60c`。因此在原table绑定、index=0xe0且n=1的有界条件下，目的地为 `1b16270`，内容来自payload。本文只验证这一个有界case的来源，不建立通用请求copy准入规则。

写入后原代码在 `b2499e` 继续调用 `9944f6`，不能把此handler缩减为写byte再返回成功。实际调整请求、注册绑定及前后工作均未观测；这里解释了一种源代码允许的生产机制，未证明值7在首次reset测试前已出现，也未排除其它writer。

## 下一条缺口

仍需取得第一条实际driver触发、release bank+1a4和辅助字段的来源、首个启用record8的selector，以及reset字节的首次写入顺序。原callback表、局部同步顺序和请求writer分别成立，尚未连成首次启动历史。

`runtime_root_binding_verified=false`、`first_callback_execution_known=false`、`first_reset_byte_write_known=false`、`adjustment_request_observed=false`、`adjustment_side_effects_fully_modeled=false`。本成果没有新的VM、原CP执行、JPEG/MP4或真实帧验收。
