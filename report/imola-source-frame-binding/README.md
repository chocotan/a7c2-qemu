# 派生AVC：original0地址到同一编码块

在已识别的派生AVC控制器中，actual original0 Y/C地址已静态绑定到同一2c00编码命令块B。尚未观察实际capture选择该子类，也未证明谁写入这些缓冲区、stride、plane extent、tiling、packing或bit depth。因此不能将它们作为已知NV12或其他格式交给codec。

范围：公开Imola2只读静态指令/虚表与原字符串核对，无MCU/系统VM、网络、硬件或private/full。12个新RAM0窗口8892B和完整身份见[source-pins.json](source-pins.json)，独立于此前3234/381冻结代码轮，不倒算成该轮运行证据。

## 同一B的完整条件链

```text
801556a8已分配B，调用controller+34(controller,B,descriptor)
 ->派生vptr80240918+34=801122d0
 ->manager vptr80241074+08=8011b82c
 ->helper vptr80240b8c+08=80116dd0
 ->helper +10=80117884(helper,S,B)
 ->80085448消费B+1340，交80082d0c/80082ee8
```

80111830先调用AVC构造8011007c，再安装派生vptr80240918，保留+10公共分配、+38 AVC准备、+40后续AVC处理，新增+34回调。它在controller+18ff0构造helper，manager+10保存该helper。公共调度80155b9c..ac把原B传a1；801122d0保留B并将u32[*descriptor+10]按既有mapper转换为S；manager在s4/s3保留B/S，8011b8a0..b8调用helper+08；helper在80116ef8..f00调用+10，延迟槽a2=B。由此闭合D就是同一B。

**基类vptr80240974的+34仍是no-op。** 本合同属于派生路径，不能据此认定当前原生capture一定走此链。

## 原图像字段与句柄

下表均是consumer normalization之前的u32：

| B字段 | writer输入 | 已证含义 |
|---|---|---|
| 1340、1344 | u32[S+470] | original0.Y_core0_addr，重复两项 |
| 1348、134c | u32[S+474] | original0.C_core0_addr，重复两项 |
| 1350、1354 | Q.vtable+18两次 | 所选Q子类的handle-derived地址 |
| 1358、135c | Q.vtable+1c两次 | 同上，不是已证stride |

实际普通指令包括80117958的`lw v0,470(s6)`、80117960的`sw v0,1340(s7)`，以及80117988延迟槽的`sw v1,c(s2)`；s2=B+1340。

801324d4映射同型输入handle到S，按BadImolaAddr哨兵1检查S+470/+474。原字符串80230070/8023002c明确为：

```text
( epict->mem_area.image.original0.Y_core0_addr != BadImolaAddr )
( epict->mem_area.image.original0.C_core0_addr != BadImolaAddr )
```

其80132d5c/801329b4普通store从handle得到：

```text
u32[S+470] = u32[u32[S+478]] + u32[be000064]
u32[S+474] = u32[u32[S+47c]] + u32[be000064]
```

另一路复制通道esram_addr记录的地址word。两种方式都只产生地址，不证明相应像素已被写入。

## 额外四个字段是地址getter

对Q.vptr=80240e3c，初始化构造该reference-control子类，经8011077c→800b099c把helper+4重绑定到选中的对象。它的+18/+1c/+20/+24分别为801d0db0/df8/e40/e88；每个方法通过virtual+90取记录，再取记录+4/+8/+c/+10的handle，返回`*handle+u32[be000064]`，null handle返回1。不能将B1350..135c解释为pitch；选中记录的完整picture角色仍未闭合。

已知consumer随后对original地址四项做`G_mode(x-u32[B+b8c])`，对getter字段使用另一个mode转换；最终提交的word不是无需解释的host字节pointer。转换算法与frame memory的单位/格式须一起确认。

E1（派生构造/manager/helper）→F1（同一B）；E2（普通store与original0断言）→F2（源地址字段）；E3（reference subtype/getter）→F3（排除把该分支地址当stride）。当前第一像素边界是original0缓冲区实际producer及其row/plane/packing/bit-depth合同。`source_pixel_format_closed=false`、gap63、`capture_verified=false`。
