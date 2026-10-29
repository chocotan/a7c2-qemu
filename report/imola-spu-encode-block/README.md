# AVC实际2c00命令块：分配、模板与请求指针

AVC命令块的分配/模板准备已有实际对象绑定：它是11264字节配置块，经handle映射后由相同AVC builder填充，随后进入command20传输。源像素布局与ES目的/容量仍不足，不能启用codec。`MemLD_Y/MemLD_C`仅证明LD设备内存字段名称，不当作拍摄输入plane。

本次为公开Imola2只读源调查，没有执行MCU/系统VM、网络、设备或private/full。12个RAM0窗口3844B及完整原件身份见[source-pins.json](source-pins.json)。主会话独立按bank和摘要读回；后续字段调查独立进行，不回填此前完整回归收据。

## 实际AVC对象链

```text
8011007c安装vptr80240974
  +10 =801556a8，公共job分配/准备
  +38 =80110a08，AVC准备
  +40 =80110f3c，AVC后续frame处理

801556a8:
  H=8005ef3c(7,2c00)
  B=CPU_mapping(u32[H])
  input=CPU_mapping(u32[frame的+10 handle])
  vtable+38(this,B,input,frame_flag)
    ->80110a08
    ->80160ad0(this+fa24,B,input,u32[this+7ea0])
```

H是内存管理handle，不能与B混用。所选mapper将低于1e000000的值加80000000；另一个合法窗口加c0000000。它不同于8016b6cc转换函数，不能统一套用一种地址公式。

80160a00初次清C+4的2c00字节并存u32[C]=C+4；后续参数操作可能选择修改后的模板。80160c74实际从u32[C]取得当前模板，四个u32一组复制完整2c00到B，含分支延迟槽的第四store；之后80160e54做每图更新。因此分配或初次清零不能证明当前B仍全零。

## 已知字段与单位边界

下表记录各选定store阶段的来源；它不代表proxy后最终提交块的全部字段已经解码。

| B偏移 | 宽度 | 正向来源/实际写入 | 边界 |
|---|---|---|---|
| 9c0 | u32 | 80163d78：argument1+1；AVC配置取u16[P+16] | count-like，像素或macroblock单位未证 |
| 9c4 | u32 | 同setter：argument2+1，取u16[P+18] | 同上 |
| 14 | masked u32 | low10=arg1&3ff，bits10..18来自arg2的条件转换 | 其余位保留，不把它解释为完整width |
| 9c8 bits0..3 | masked u32 | 公共准备取frame.byte0&f | 语义未命名 |
| 9c8 bit21 | masked u32 | input.byte4c4&1 | 同一input来源已证，语义未命名 |
| b54/b64 | u32 | 初始模板8005e3f4(MemLD_Y)+u32[be000064] | named LD-Y值，不是已证源image plane |
| b5c/b6c | u32 | 对MemLD_C执行同型操作 | 不证明Cb/Cr次序或packing |
| b58/b68、b60/b70 | u32 | 8005e47c(handle)/8005e504(handle) | 关联商值，stride/capacity单位未证 |

原assert802334b0要求`MemLD_Y/MemLD_C`同时有或同时无。名字没有给出实际拍摄YC字节布局。

## 提交前转换仍要保留

proxy800867f8→80085448在B上调用：

```text
80082978(this,B+b44,(u32[B+b88]>>10)&f)
80082d0c(this,B+1340,(u32[B+b88]>>6)&f,u32[B+b8c])
80082ee8(this,B+1340,(u32[B+b88]>>10)&f)
```

第一函数从B+b44的u32索引4..b处理四对值，也就是b54..b70。首值等于1时跳过该对；模式0/1/9保持，2右移1，3取`high32(u64(x)*aaaaaaab)&fffffffe`，4/5/d取`((x/3)*4+1ff)&fffffe00`，6/7/f左移1。按源u32语义处理。未证明这些值的物理字节地址单位，不能将LD字段一律交给host当像素pointer。

## 请求指针与未闭合调度边

801565a8从frame+2c的command handle形成CPU mapping，放在descriptor+10；801c61b4 serializer保留该字段。driver8407处理80174be4将descriptor交scheduler虚槽+8。FIFO实现8016bb78分配独立28字节req，80176710将descriptor+10复制到req+18；构造安装vptr80242e1c，slot10=80176a4c，因此已知cache/sync/command20使用此复制字段。运行时scheduler具体vptr安装尚未完成，不把数字相同当成已观察的异步指针传输。

## 下一个源图像候选

80117884和80118088都写`D+1340=u32[S+470]`、`D+1348=u32[S+474]`；第一函数复制到1344/134c，第二函数改取S+488/+48c。1350..135c来自virtual getter。它们各有不同方法表中的指针，尚未把参数D绑定到同一AVC B，也未证明S字段是source页/plane。不能因偏移类似就采用该布局或给这些word冠以YC/ES名称。

E1（构造/vtable/job allocation）→F1（AVC准备身份）；E2（整块模板copy与store）→F2（字节来源和阶段）；E3（descriptor/req复制）→F3（pointer transport的静态边及缺失selector）。下一步先闭合D→B、S字段与实际页/plane，再核stride、格式、bit depth和ES容量。`actual_ES_byte_writer_closed=false`、gap63、`capture_verified=false`。
