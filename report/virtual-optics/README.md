# 内部虚拟镜头／场景成像原型

本组件输出实际可检验的**自定线性RGB888像素**，用于准备后续CMOS适配；尚未连接Sony固件，没有实现Sony/Bayer/YC格式、plane、lease、ACK、ready或相机拍摄。帧号与摘要独立存于metadata，不覆盖图像首行，也不写JPG/MP4。

## 复现

```bash
# 从本目录执行；需要host C编译器、libm和ASan/UBSan
TMPDIR=/var/tmp bash verify.sh
```

脚本以严格警告及ASan/UBSan编译到被忽略的`.build/`。任一断言、越界、未定义行为或泄漏诊断使验证失败。主会话已逐字读实现并独立复跑代理原交付，得到下列数值；移交后又补充空指针、奇数宽度/外侧哨兵，以及像素尺度/F数与模糊半径关系的独立边界测试。

```text
shutter=2.000000 aperture=0.253521;
gradients near 12.750/0.250 far 0.250/12.750
```

这表示未饱和区域快门加倍亮度约两倍，F4→F8亮度约四分之一；对焦距离1m→4m时，前景由清晰变模糊、背景相反。数值由测试消费实际像素计算，不以checksum变化代替光学效果。

## AArch64／原libc ABI验证

另有`verify_guest_abi.sh`，以项目已有guest helper的启动方式交叉编译同一测试，链接原libc/libm/loader 2.25，再用QEMU **user-mode**执行。主会话已实际得到相同亮度与梯度结果；它没有启动相机或Linux VM，也没有调用appFw/CP。

```bash
# 从本目录执行；QEMU_USER须指向自备的qemu-aarch64用户态模拟器
: "${QEMU_USER:?请指定qemu-aarch64工具路径}"
bash verify_guest_abi.sh ../../runtime/analysis/menu-root "$QEMU_USER"
```

该检查还需clang/lld、AArch64系统头、Python与pyelftools。脚本先校验三份原库的内容SHA，编译后核EM_AARCH64、只依赖libm/libc/loader且符号版本为GLIBC_2.17；不能只凭库文件名认ABI。主会话执行时经已有`idle_lock`持相机guest构建锁；同工作区使用也需串行化。此检查没有guest ASan运行时，内存安全检查由前一项host ASan/UBSan承担，不混为同一证明。

## 接口与所有权

`optics_render`接收镜头参数、width/height、字节stride、调用方buffer/容量、帧号及独立metadata/statistics。像素顺序固定R/G/B，每行仅写width×3字节，padding不变；帧摘要FNV-1a仅覆盖有效像素。

返回0才更新metadata与completed_frames；非法参数、容量/乘法溢出或计数溢出返回−1，目的像素、metadata和统计均不改。函数不分配内存，不建立固件消息或buffer lease。调用方负责有效且互不重叠的对象、buffer寿命以及共享对象的外部串行化。

## 明确的原型假设

- 固定35mm定焦，传感器宽度36mm；这些是原型设定，**不是已核A7C2电气或接口事实**。
- F4/F8/F16、对焦距离≥0.1m或正无限远、有限正快门/ISO。焦距不提供变焦功能。
- 左／右半图是1m和4m两层固定棋盘目标，以免目标纹理差异污染清晰度比较；没有遮挡与边缘散景。
- 焦距f以m计，场景／焦点屈光度Ds/Df（无限远Df=0），圈半径为 `f²×abs(Ds−Df)/(2N×(1−fDf))×width/0.036`，上限16像素。
- 使用可分离方框滤波及相邻整数半径插值，近似离焦；不是实测PSF，没有衍射、畸变、AF、噪声、滚动快门或色彩标定。
- 在线性亮度上乘 `shutter_s×ISO×64/N²`，clamp后量化到8bit。非常小的曝光会量化为黑，饱和区不再保持曝光比。

## 验收与未完成项

已测：快门/ISO和F数响应、双景深清晰度互换、重复输出、有效像素摘要、独立帧号、无限远、模糊上限、F16/饱和、非法/非有限参数零写入、尺寸溢出、padding、最小/奇数尺寸与边界。

尚缺原固件图像格式与像素发布/消费/归还合同；未将此图送入原图像驱动，也没有从该组件直接宣布CMOS、镜头或相机拍摄通过。后续接入须沿`imaging-pixel-contract/`的实际接口完成，不能把自定RGB888的枚举强套Sony元数据。

本目录为移交后的权威实现；`scratch/virtual-optics/`仅保留最初交付与历史验证，不来回维护第二份源码。
