# 8420接收器：request conditioner与endpoint6边界

已闭合同一original0提交路径选择endpoint1b并到达`venc_req_conditioner`的静态绑定。其已证直接分支仍只把同一24字节descriptor转发到endpoint6，没有pixel writer或DMA配置证据；因此不实现猜测的像素producer。

本次为公开Imola2只读静态原指令/配置/入口核对，无MCU/系统VM、网络、硬件或private/full。12窗口3960B及完整原件身份见[source-pins.json](source-pins.json)。它是3234/381冻结代码轮之后的独立源调查，沿用[original0到8420](../imola-original0-vbb-request/README.md)而不回填旧运行。

## 发送endpoint来自实际构造

8007c24c的GOP/VBB factory在8007c270调用8008ff18(7)，返回配置M的五个u16为`{7,8,1b,2,4}`。8007c304..30c把同一个M交8007a4f4；该函数读取M+4和M+0并调用8012f21c，构造器实际保存`u16[C+2]=1b`、`u16[C+0]=7`。

原提交80131f20取C+2调用8000cc28，所以所选endpoint为1b。lookup显式计算`80ae3500+(index<<6)`，此处得到80ae3bc0；这是固件内部地址，不作为host pointer。C+0的7传入sender a3/header字段，和recipient使用的body byte0不同，不能混用。

## 接收worker绑定同一endpoint

静态任务记录80244084的七word为`{1a,0,0,800ae928,8,1000,80253e78}`。首word不是据此已知的队列号；入口才给出可靠绑定：800ae928→800ae850→80090120创建R=`{1b,6,9,1a}`（四u16），conditioner构造800aca80保存R。

worker800ae738读取u16[R+0]，经8000cc28取得endpoint1b，用801aadac(endpoint,-1)取消息。800ae7e8比较8420，800ae7f4调用800ace90。原路径字符串是`src/ipsx/release/spu/all/ctrl/video/enc/common/venc_req_conditioner.cxx`。这里只证明静态任务绑定，没有观察当前capture实际启动该任务。

## Handler只证明描述符处理

800acec4..cec8要求u16[message+6]==18h，800acf10令body=message+8。认证的是24字节body；sender的0x80参数仍不能当作帧长。

800acf90..cfb8读取body.byte0并测试conditioner[4+body0]。值为1时进入800ad7a4..7ac，调用800adefc(conditioner,body,u16[message+2])。此函数保留原body，在800adfa4..fac读取u16[R+2]=6，再以同一8420和同一body指针调用801aa768（800adfc8，延迟槽800adfcc把指针放stack+14）。nested handle随之保留，没有逐像素读写。

另一分支复制body字段到临时记录与1c字节cache item，保留body+14引用。缓存寻址800ad22c在MTLO/MFLO间含未解释word0043001c，附近另有70000026；不能默认为`base+channel*b8`或把这些操作变NOP，也不宣称已能执行整个cache分支。直接模式的实际运行值尚未观察。

## 第一未闭合消费点

endpoint6的selected8420 consumer还没有绑定。不能只凭`vbb_drv`字符串就指定8006d480。需要它首次解开same-body nested handle并实际使用original0 pair的动作，才能判定地址是input/output/in-place，以及source pointer、byte count、row pitch、packing、bit depth与硬件job寄存器。

E1（factory和C+2 store）→F1（选定endpoint）；E2（task入口、R配置与receive）→F2（真实recipient）；E3（same-body转发/cache复制）→F3（该层仍非像素生产）。后续调查聚焦终端consumer的实际数据动作，不用完成通知、更多地址复制或队列计数代替。`actual_origin_pixels_consumed=false`、gap63、`capture_verified=false`。
