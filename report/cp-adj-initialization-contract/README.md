# ADJ group9注册与M/C初值边界

`b22f1e`只登记指针表及项目数量，不读取、复制或初始化M/C。它后面的`a48dea`只清零u8[1b18336]，没有覆盖紧邻的M=1b18337或C=1b18359。因此当前第四启动状态字节的M/C输入仍未知，不能从这两个函数导出默认零。

范围为公开ALLLANG CP原件的只读静态核对；没有运行VM、访问真机/物理SD/private/full或网络，也没有改变数据owner或3003回复准入。完整第四字节算法及ADJ读写路径沿用[现有合同](../cp-start-state-data/README.md)。

## 实际函数方向

`a48f02`首先调用40c25c完成LIF属性初始化，消费若干独立配置字段，随后在a48f7a调用`b22f1e(9,19ee17c,100)`，再在a48f7e调用a48dea并返回。这里100为十六进制项目数。

完整b22f1e相当于：

```c
for (unsigned off = 0; off != 0x84; off += 12) {
    if (*(uint16_t *)(0x110f7a4 + off) == group) {
        *(uint32_t *)(0x110f7a8 + off) = pointer_table;
        *(uint32_t *)(0x110f7ac + off) = item_count;
    }
}
```

关键原指令b22f3a是`strd r1,r2,[r3,#4]`。它把注册元数据写入文件背书的group记录，不解引用表中的各个项目。该函数没有helper调用、值域校验、缺省载入或pointee清零。原group9记录VA110f810为`090000000000000000000000`：group ID及初始空注册字段，不含M/C默认值。

接下来的完整a48dea只有materialize 1b18336、mov零、**strb**、return。写宽度是一个字节；不能因为M只差一个地址就扩成半字或整字清零。

## 第一处尚缺的值输入

已有ADJ路径以key0a、selector0、index80/b2选到M/C指针。opff在b24d5e把请求payload写入pointee；另一分支b24d8a从pointee读值、b24d96复制到reply。这是当前值的读写方向，未提供默认来源。C另有M=2时第四getter的条件写回。

E1（完整注册函数与编译group表）支持F1（登记地址和数量、没有初始化项目）；E2（注册后的完整尾调用）支持F2（只清邻接字节）。这不是全程序不存在writer的结论：早期/后续生产者、原启动历史及M/C实际运行值仍未闭合。global clear仅证明其自身返回边界，不证明构造后或3003时刻的值。

[source-pins.json](source-pins.json)保存4个原窗口、216字节。主会话已独立读回所有摘要，核完整helper及STRB宽度；没有新增回归代码。`M_known=false`、`C_known=false`、`capture_verified=false`保持。
