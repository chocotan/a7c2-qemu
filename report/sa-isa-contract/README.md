# SA条目解析与ISA边界

公开原件已经足够确定一个SA条目的头校验、索引和payload相对指针规则。仍不能据此确定指令ISA、Y/Cb/Cr lane或原RC/JPEG同一缓冲的解释。native JPEG START保持NEED_DATA，`native_pixel_layout_known=false`、`guest_pixel_consumed=false`、`capture_verified=false`。

本次只读本地公开ALLLANG与定向GPL源码，不运行VM、不连接网络/真机/物理SD，不读取private/full工件。没有增加SA执行器、像素转换或ready事件。

## 原驱动实际读取

K地址均为av-cam.bin的raw offset；原KVA为`ffffffc001000000 + K`。

- K304ac0查询最多16条、stride18的registry record。record+2非零才参与匹配；比较record+1与第二个u8键、record+0与第一个u8键。第一键ff接受任意第一键。
- K304c44以w2=0调用该查询，返回u64[record+10]头指针；缺失返回NULL。
- K2fe644..2fe748检查完整magic **91130aaa** 并解析条目。早先K2ec794/K2ed188的aaa只是MMIO测试填充值，不是本合同的loader证据。
- K304e0c..304e2c的真实调用者以当前unit、request+3的u8和request+6的u8索引调用解析器。这里没有执行payload的指令语义。

令H为查询返回的头基址，原解析器检查：

```text
H非NULL
LE32(H+00) == 91130aaa
u8(H+04) == 7
u8(H+08) <= 1
n=u8(H+0e)，1<=n<=63
LE16(H+06) >= 20 + 30*n             （这里20、30为十六进制）
i=u8(w2)，要求i<n
D=H+20+30*i
可选输出*x3 = H+LE32(D+08)
```

头错误返回0d，索引越界返回0c，成功返回0。该函数没有给出payload总文件范围或指令长度；安全文件解析不能把这个指针规则当作完整的bounds证明。

若提供x4输出，函数先置u8[x4]=1，然后根据u8[D+0c]低四位选择性复制：bit0复制D+10到x4+04，bit1复制D+14到x4+0c，bit2复制D+18到x4+08，bit3复制D+1c到x4+10，均为u32。未选字段保持旧值，不能补零或将其命名为plane、stride、lane。

## 已知条目的实际读回

[此前YC边界](../yc-cpu-consumer-boundary/README.md)固定的SA包中，H位于raw8800：magic字节`aa0a1391`，type7，头长50，H+08=0，n=1。D位于8820；D+08的`00010000`给出相对offset100，因此原解析规则指向**raw8900**。D+0c=0，没有任何可选metadata复制。

原payload窗口8900..9d00共5120字节的长度来自已经固定的条目身份边界；上述函数自身不提供该长度。`SP`、magic、`NV12CONV0x02`标签及payload首字b039003d均不能单独命名架构。没有已验证的首条opcode、load/store或lane示例；本次GPL定向检索没有取得decoder正证据，也不证明ISA不存在公开定义。

[source-pins.json](source-pins.json)归档4个驱动窗口和2个包窗口，共7240字节，含完整解析函数。E1（registry读取）→F1（头指针来源）；E2（完整parser）→F2（头/索引/条件metadata合同）；E3（包头与payload）→F3（实际相对指针匹配）。实际路径止于payload地址与metadata，尚未跨过指令执行或像素lane边界。
