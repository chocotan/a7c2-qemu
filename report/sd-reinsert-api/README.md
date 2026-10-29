# 原 Fsys 重插后 API 存储诊断

这里的 C 文件是已执行诊断的唯一权威源码；不包含固件、卡镜像或用户配置。它是研究用显式 opt-in preload，不进入正常模拟器启动，也不是相机拍摄实现。

只在原 AP 的 Read 成功返回、真实拔出/重插达到 generation3、原库只有一个挂载卷后，调用同进程原 Fsys API。文件名要求用户态提供8位大写hex，先拒绝可读的已存在文件，再创建4096B诊断数据，依次执行Write、Flush、Close、Open、Read、Close，并比对完整内容；不调用Mount、Unmount、设置presence/ready或修改Backup。原触发Read的buffer、返回值和errno保持；失败不伪报DONE0。

为了让宿主独立核实际保存内容，诊断文件有意留在虚拟卡根目录，明确记录`left_behind`。数据以“not a photo or video”文本开头，不能将它冒作原固件照片/视频。

## 已执行结果

`run-atvy5ajv` 在原简中首设/真实GTK拔出和重插后执行：

* 新文件 `B:/C883B25C.BIN`；Open/Flush/两次Close均0，Write/Read均4096。
* 写入、读回及导出卡独立FAT解析的FNV均 `3c37c5fe978fc608`。
* 全4096B逐字节相同，文件SHA `4371dae3d0f92258599da5639f174e2836f6fdc0c93629e7e3a49c8f923c7bc2`。
* 整卡SHA `e7b612a108f3d2ba07a3d1ed45090217dde6164a416650e533d9bd62eafd34fa`，独立fsck0，12files/4734of65399clusters，原owner resumed。
* 实际选用镜像中的诊断库SHA `617a33fbe06c141732bcb10604f4454a13c27c623ec29b3b3cf7544969c7f72b`，file-media观察库SHA `ec0c6fe5e66221d72e48c4a4f67eca62676d132a8bee95365c94c4b4ec7d27e3`。

宿主ASan/UBSan已执行正常及10种拒绝/错误场景，原Read保持不变；派生GTK驱动语法和等待真实DONE0再保存也通过。这里只验原API存储能力。重插后原程序自然读取整个DATABASE.BIN/XML另有`run-h7tn8rmu`证据；本次新文件属于显式诊断，`natural_camera_reinsert_write_verified`与`capture_verified`继续false。

## 离线复核已有运行

从成果根目录执行（本机运行目录不随源码发布）：

```bash
python3 report/sd-reinsert-api/verify.py runtime/analysis/menu-runs/run-atvy5ajv
```

要求该runtime已按官方ALLLANG路线准备，包含项目既有`vendor/fwtool` FAT读取模块以及`fsck.fat`。复核程序只读日志、卡镜像与manifest，不连接VM或写相机；验证结果写该run的`sd-reinsert-api-review.json`。原始总体false proof不改写。
