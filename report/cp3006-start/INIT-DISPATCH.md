# BACKUP_INIT真实调用者与初始化表

原初始化表的消费者已静态闭合；启动前04000000的字节来源仍未闭合。主会话完整读独立报告`scratch/cp-init-dispatcher/REPORT.md`，另按SHA核原件、表记录、标签和ARM指令。`verify_init_dispatch.py`仅只读复核这些事实，不执行初始化。

## 表格式与调用

原ARM路径为634780→6347e8→634844。6347e8包装器传入表EB55C4、计数LE32(EB56DC)=14和标签数组EB56E0。记录固定20B：

```text
u32 flags, u32 argument, u32 function_pointer, u32 mode_mask, u32 id_mask
```

6349b8..c4计算table+20*index；634d74以LDMIB取记录+4/+8到r0/r1，634d78以BLX r1执行。函数指针可为ARM偶数地址或Thumb奇数地址，不能只扫Thumb BL来找全部调用者。

BACKUP_INIT是索引7：记录起EB5650，函数指针字段EB5658=55DCA5，实参0；掩码FFFFFFFE/1。此前把EB5658直接当记录起点、把其后负数当priority或依赖长度的猜测不成立。

## 标签是平行数组，不是依赖链

14项按索引尝试：TOPPERS_KERNEL、USER_TSK_INIT1、PCIDMA_INIT、OSAL_UIPC_INIT、SNDCMD_INIT、PCIEIF_INIT、OSAL_UTIMER_INIT、BACKUP_INIT、OSAL_ULOGIO_INIT、SENSER_SLAVE_INIT、KBD_INIT、UDATE_INIT、USER_TSK_DRV_INIT、USER_TSK_INIT2。

邻近EB5548是另一张退出表，计数和五个标签占据表间区域；此前的“变长记录”现象来自跨表读取。不能从邻近字符串列表推断依赖关系。

每项受mode_mask与`1<<运行模式`、id_mask与`1<<(读出ID-1)`约束。**实际模式/ID未观测，不与model_mode=3或CPU编号直接等同。** 调用者对记录顺序的遍历，也不证明其内部异步任务在下一项前已经完成。

## 下一边

PCIEIF_INIT索引5回调56A921，位于BACKUP_INIT前；main只读其Thumb主体发现向其他chip触发的日志与调用，尚未沿所有callee核BKP数据搬运，因此不据此声称04000000已准备好。

source-reader中的primary-only规则不变；第二BK4存在、AP的type1取址规则、此初始化顺序是三个不同事实，尚不能拼成已执行的CP配置加载证明。不给3006补成功回包或shadow值。

```bash
# 从本成果根目录，只读复核
python3 -B report/cp3006-start/verify_init_dispatch.py
```
