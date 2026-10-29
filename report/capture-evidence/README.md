# 只读运行证据检查器

检查原App32输入顺序、原LCD PNG摘要、虚拟SD导出与FAT16目录，识别有限
JPEG/MP4结构候选。**不验证真实相机拍摄**，capture_verified始终为false；
容器有结构不代表可解码，更不证明来自原capture/encoder/Fsys。

```sh
python3 check_evidence.py /absolute/path/to/owned-run \
  --expect 0xa7:1,0xa7:0 > /your/experiment/evidence.json
python3 -m pytest test_check_evidence.py -q
```

默认输出stdout；可选--output只允许在工具目录直接新建文件，不覆盖已有
文件、不写入被检查的run。工具不自动发现run；只处理用户明确提供的目录。
实际LCD必须为640×480 PNG，摘要为解码RGB字节的SHA256，需Pillow。
MODE/拨轮status支持完整u32。输入到达不证明功能、曝光或对焦完成。

磁盘仅支持固定128MiB、512B扇区的FAT16 superfloppy。检查导出摘要、已有
fsck记录、Flush/STOP/恢复序号与PID，目录解析拒绝越界、循环和交叉链。
LFN记录全部忽略，仅列经过检查的短文件名；大于16MiB单文件及不支持的
格式明确失败，未检查的容器不算有效媒体。它不重新执行fsck。

为避免摘要与目录解析读取不同时刻的字节，工具向私有TemporaryFile边复制
边hash，然后仅解析该副本；不声称源读取是原子快照。**临时目录需至少
129MiB可用空间**，若TMPDIR指向tmpfs会占用相应内存；可在启动Python前
将TMPDIR设置为实验磁盘目录。空间不足或临时文件创建失败返回结构化错误，
不丢弃其它检查结果。临时副本在退出context时关闭删除。

独立评审发现并复现了Pillow大图异常未捕获、摘要/解析TOCTOU、图片尺寸
缺失及合法JPEG填充误拒绝。修复后评审重跑23tests通过，独立70B超大PNG
复现也确认input失败而disk仍检查；另以真实check_disk验证副本一致性。
主会话已重跑run-hcrppdg6：22张图均640×480，输入/磁盘通过，DB/XML两文件，
媒体候选0，capturefalse。迁入本最终目录后新增临时空间/创建失败两项回归，
最终目录测试结果为**25 passed，0.14s**。迁移后再次实际只读检查run-hcrppdg6：
22张LCD摘要与640×480尺寸、原输入和磁盘检查通过，媒体候选0，capturefalse。
结果保存在研究目录的final-delivery-run-check.json，未回写原run。

单卡槽硬件事实与固件内部slot/RM编号必须区分：检查器只列FAT内容，既不
证明AP录像媒体实例已挂载，也不从“槽2”提示推断存在第二个物理卡槽。
