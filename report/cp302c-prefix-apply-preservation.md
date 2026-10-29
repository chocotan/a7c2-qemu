# type5 common APPLY 的 current 保持边界

公共 apply 路径的同步字段已闭合，但整条前缀仍不能授权 current0。原件为公开 CP `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`，CPVA文件偏移为 CPVA−`0x108000`。

已核实：

```text
996fec:  u8[1b16058] = 1
996f7c:  return u8[1b16058]
3a5e1c:  if r8==0 && getter==1: call 9d30ee; call 996f34(0xa)
9d30ee:  u8[1b163d4] = 1
996f34:  u32[18b8a84] = 0xa
```

`0x18b8a84` 是局部状态域，中央 current 是 `0x1a52ad4`；不能将 `0xa` 当成中央 mode 或 commit。

延迟工作入口和flag读取的方向为：

```text
98ec9c → 9cf8c6
  9cfca4 → 9d3136   (读取双flag条件，不是调度producer)
  条件分支 → 9d09a8 / 9d1ff4 / a4abc0 / a4a3f2
```

原 `98ec9c` 的输入r1非零时可进入工作；为零时，`98ecee` 读取 `165d2c1`，该值为零才在 `98ecf2` 跳过 `9cf8c6`。跳过这一个callee并不代表整个入口无副作用：它在此前已更新局部计数/字段并调用其它工作，不能将其包装为generic no-op。

双flag的准确合同是：`9d30ee` 设置 `A=u8[1b163d4]=1`；`9d30fc` 同时清A和 `B=u8[1b163d5]`；`9d3120` 执行 `B=A`；`9d3136` 返回 `A & (B==0)`，非零分支仍须caller精确比较结果为1。真实caller `9cfca4` 在工作中读取该谓词，`9cfe6a` 才调用snapshot复制。因此不能把APPLY设置A解释为直接排队、复制已经发生或中央状态已推进。

release状态写入的是 `u8[u32[10ff418]+17c]`（原件 `10ff418` 指向 `18b8fd8`），另有 `165d2c1`、bank+4c 等独立门控。这些地址和字段都不能从中央 current、CP cold mode3、BB 状态或图连接结果推导。

后续源复核已明确setter实参：`9d09a8` 用r1作新byte，完整r1等于ff才取旧byte+1；r0只参与诊断，r2=1另清两个局部flag。存在 `1b16270==7` 时写release byte=ff的条件reset，但没有证据把它当开机构造器。即使APPLY双flag谓词不成立，`9cfdbc/9cfdf2` 的其它guard也可选择 `9d09a8(0x0d,5,1)`；该guard由 `3b0b9c→9df0e2` 的四个实际输入产生。写5之后仍可能在同一工作中改写7，不能直接认定handler5已执行。完整原字节、实参表达式与边界检查见[LIF合同的首次release状态章节](cp-apply-lif-command-consumer/README.md)。

一条未闭合的异步路径是：

```text
9cf8c6 → a4abc0 → a5d7ca → a5c700
→ a5c366(command byte 0x1c)
→ 3e9584 / 3e9585 callback object
```

15 B队列槽包含1 B bookkeeping和14 B命令记录；只有命令首字节由 `a5c700` 明确设为 `0x1c`，其余13 B不能补零。后续已查到 `405eec(3)` 实际调用 `3e9584`、逐项经 `a91e54` 复制输出。原件metadata中 `1c` 的长度为1：在该表绑定和support有效时，13 B未知尾部不会进入此命令的输出。因此“未知尾部必然阻塞消费”不成立，仍需保留未知原字节，不能宣称原值为零。见[实际LIF consumer与验证器](cp-apply-lif-command-consumer/README.md)。另一条 `a4a3f2→a4a430` 写44 B队列，后续消费者也未闭合。

因此即使目前没有直接发现该链生产 event0/event2，也不能在未知启动工作项和异步消费者的条件下宣布它保持 current。原 current0 命令表允许 `3000/3003/3006/300e/3020/3007/301e/302a/303c/303d/3047`，所以“任何未知 command 会被 current0 拒绝”也不成立。

延迟 flag 的实际异步边已定位：`9cf8c6→a4abc0→a5d7ca→a5c700→a5c366`。后者在专用队列中写入首字节 `0x1c`、复制14 B输入、更新 `1b187e6` 唤醒 flag 和队列游标；剩余13 B不能补零。消费者 `3e9584→a5c422` 将队列项放入工作列表 `1716a40/1716a48`。异步对象 `19f2d8c` 的 callback 槽为 `+0xc=3e9585`，`a918ca(object,3)` 把它存到 `1a03d18[3]`；原 `405eec(3)` 在 `406094` 真正调用该槽，`4060ae..4060d4` 逐项核support并调用 `a91e54`。输出由 `a910a8(2)→a9366c→a48382→a478c4` 组装通讯帧并以记录索引提交原环队列。现已进一步闭合 `a47962/a47c2a` 出队及staging复制/record退休，再到 `406ae0→a9368c→3e1a94` 的UART1/DMA1寄存器提交，以及IRQ/两次timer/event3清busy。命令1c的一字节body产生9 B协议长度、16 B实际DMA跨度，额外7 B padding仍未知；DMA callback还忽略错误位，event3不证明无错误发送。runtime support、实际设备接收和中央状态因果仍未验证；完整复核见[源合同与验证器](cp-apply-lif-command-consumer/README.md)。

另一条 `a4a3f2→a4a430` 会生成44 B替换队列记录并更新 `19ee70c/710/714`，实际消费者同样未闭合。`9d09a8` 写入的是独立 release bank `u8[u32[10ff418]+17c]`，不是中央 current；release index 6/7 也不能命名为中央 state6/7。

结论：

```text
common_apply_preserves_current = unknown
whitelist_apply_commands = none
original_config_consumed = false
302c_native_verified = false
capture_verified = false
```

调查没有启动 VM、修改生产代码或使用 private/full-system 数据。