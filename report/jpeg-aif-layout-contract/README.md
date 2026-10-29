# JPEG AIF输入：地址来源字段与byte lane边界

本次在同一原encoder调用中闭合了P+50/P+54到L+68..6a、再到B+1200的字段映射，仍没有正证据命名输入字节顺序。首个未解释边界是ASIC如何把B+800所指内存的各byte lane解释为Y/Cb/Cr。不能据此选择YUYV、UYVY、NV12或plane布局，native START继续NEED_DATA。

范围限公开ALLLANG原件只读静态分析；无系统VM、网络、真机、物理SD或private/full数据。没有改变native-jpeg配置或成功判据。

## 同一encode路径

K均为av-cam.bin raw offset；原KVA为ffffffc001000000+K。

```text
K2acba8  K2aab4c清零整个L，1d8字节
K2acc18  K2aa3e8(P,P+28,L+90,3,0,0,0,q)，q=((u32[P+50]|1)==3)
K2acc4c  K2aaaf0(P+50,L+68,L+90)
K2af76c  K2a52fc(B,0,L+68)
K2af694  K2af780(B,u8[L+2],L+70,L+90)，本路径L+2=0
K2accd0  K2af620(unit,1) -> K2a5404(B) -> START
```

2aaaf0在u32[P+50]==2时置L+68=1、L+6a=u8[P+54]，还通过2aeed4把由P+54构造的地址覆到L+90。其他值只写L+68=0。由于L先被整个清零，条件P+50=0路径得到三个字节0/0/0。这是该条件路径的明确本地写，不是实际VM输入或packing默认值。

2a52fc以32位MMIO RMW保留其他位：

```c
B1200 = (old & ~0x000f1800u)
      | ((L68 != 0) << 11)
      | ((L69 != 0) << 12)
      | ((L6a & 15) << 16);
```

L68非零且L69为零时，还在另一寄存器块base+16*L6a置bit0。这支持地址来源/端口选择关系，不提供byte lane定义。

完整2a5404执行B1008=old|10、B1200=old|2000、B1280=(old&~6)|3。10/2000/3只是保留位为零时的结果；函数自身为RMW。没有已匹配的原enum把这些位定义为分量排列。

## 地址与未闭合语义

2af780用L+90构造遍历记录，2a4650在本调用channel=0时写B+800，高地址经2a510c(B,0,…)写B+1218。另一分支写B+840，但本路径传零，不能把另一分支视为第二plane。选定提交没有独立、具名的Y/Cb/Cr分量地址。

实际名称锚点包括`src/dgi_jpeg_common_make_rsl.c`、`dgi_jpeg_common_make_rsl_image`、`dgi_jpeg_common_check_ip_image_param`、`dgi_jpeg_common_check_invalid_ip_trans`。限定的AIF/LIRO符号及六种lane名字面查询没有给出可绑定定义；这不是其他代码不存在定义的证明，也没有重做先前RC/GRM/SA调查。

[source-pins.json](source-pins.json)保存9窗口共1972字节与完整原件身份。E1（caller及L清零）→F1（条件输入字段）；E2（完整helper和RMW）→F2（原MMIO字段对应）；E3（channel0地址写）→F3（单输入基址，但byte-lane语义未证）。原件身份、原始窗口及关键指令静态核对通过，不作为实际帧消费证据。

`pixel_layout_known=false`、`guest_pixel_consumed=false`、`capture_verified=false`保持。地址、422采样、2*Canvas stride和matrix系数都不能单独补上顺序定义。
