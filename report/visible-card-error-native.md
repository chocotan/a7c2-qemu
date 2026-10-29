# 自然boot已产生原错误界面，拍摄主界面尚未恢复

`run-hobha2ig`通过DMM容量查询后，原UI离开boot future等待，实际显示存储卡错误。
MENU的按下/释放也由原App队列消费；当前没有进入菜单屏或拍摄主界面。
这不是强制切屏：本轮没有apply/sweep/工厂强切/ready或token写入。

![原固件显示存储卡错误](boot-card-error-visible.png)

图中文字为“メモリーカードが正しく読めません／メモリーカードを入れ直してください”，
即“无法正确读取存储卡，请重新插入存储卡”。图片从实际捕获原样复制，未叠字或替换界面。

## Evidence → Finding → Path

| Evidence | Finding | 下一步 |
|---|---|---|
| 原screen名称表/重定位：308→12d→322 | scr0039_boot→scr0099_0001→dlg_dbl021_base，非343 shooting或346 menu | 从错误生产者与真实媒体状态追查，不能按颜色数判主界面 |
| UI290栈1795708←179a470←1796ef4，原MENU ON/OFF接收记录 | 原UI已恢复消息循环，键已消费 | 菜单实际转屏仍需后续单独验收 |
| Common328栈…305eb88；原run305e9ec在此之前调用future完成 | 当前是sequence_boot的post-completion分支，不是旧UI bootfuture等待 | 原CameraBackground收尾依赖与媒体错误分别调查 |
| DMM同pointer/lease/free及AP属性读回00 00 60 09 | unit50b58配置查询和原模型值继续执行 | 不把容量150MiB当图像buffer allocation |
| StillCa330 initial_arrived0/slot states0/completion0=1 | 尚缺rep_boot退出时的初始snapshot；completion0到达也不独立证明挂载成功 | 不补假通知，不从错误页猜具体FAT故障 |

原screen名称通过`51f5250+id*8`的relocation addend在同原ELF解析，
没有继承旧vtable错位结论。Common收尾点处在原`sequence_boot::run`函数内，
305e9e4调用run_i、305e9ec完成原future，后面才走本轮305eb84→34d1748。
这里依据同run栈位置与原控制流判断经过completion调用，不冒称额外hook记录到了完整future生命周期。

后续纠正：scr0099的group311/31e是34项语言可用性列表，所选b1d不是SD故障predicate。
截图的存储错误显示在后续dlg_dbl021中，不能由语言页列表判断Fsys/RM原因。
无MENU同镜像对照仍显示逐像素相同的错误图像，只排除自动MENU是其必要触发条件。

## 图像与限制

截图640×480、RGBA非全零，已实际检查可读文字。PNG SHA256=
`ad66bc7d5e5f97ce73ea57a8e9ca1e46b77d94b852bea83349426948cb73924b`，
解码RGBA SHA256=`3496a870d47c6019bd6f4068d9d518a6bbaab6878555ef820c04b278055bddf6`。
metadata记录sequence458、pixel_source_seq2、bmp_format1；AP软件消费，实验RGBA4444。
`ack_delivery_proven=false`沿用原记录，不将可见截图外推为CP合成或物理屏ACK完成。

没有CMOS实时取景、原相机像素、硬件音频输出、拍照/录像或保存产物验收。
仍有10/11条Connect明确拒绝及其它未实现硬件路径。UI显示错误不等于拍摄主界面恢复。
原媒体错误来源正由独立只读调查核对，主会话继续处理post-boot Common依赖。
