# 实例配置存储组件

宿主存储组件已实现并通过48项测试；它尚未接通原固件配置提交、导出恢复或
GTK重初始化。当前相机默认重启会从seed重建配置的行为尚未改变，不能把
本组件测试通过当作跨VM配置验收完成。

## 实现范围

代码为runtime/analysis/setting_store.py，测试为test_setting_store.py。
控制器必须选择跨UI进程稳定的实例目录，而不是某次run目录，并提供真实
固件身份、已一致导出的Backup字节和独立取得的guest SHA256。

- commit接收显式bytes或精确长度的普通文件fd，要求2390264B和SHA256
  匹配；fd用pread从0读取，不改变调用者offset。摘要只证明传输字节身份，
  不证明guest事务一致性，也不认证调用者提供的固件摘要。
- load对新空实例返回None；已存在代文件但缺失current.json、缺失/损坏
  数据、固件不匹配均报错，不静默退回默认seed。
- 每次写新代并保留旧代。payload、记录和待发布指针写入后读回核对，
  fsync后原子替换唯一current指针。flock串行、generation CAS拒绝旧提交。
- 路径逐组件dirfd/O_NOFOLLOW检查；实例0700，文件0600，所有权和
  单硬链接普通文件约束；空间不可判断或不足则拒绝。
- reset要求字面confirmed=True及控制器离线租约factory，租约覆盖
  当前实例停止、安全租约结束并排除启动/导入/导出后才可发布reset代。
  存储层只能验证接口，不能替控制器证明VM已停止。它不删除历史证据、
  SD、外部源或其他实例；发布逻辑重置状态，不执行磁盘安全擦除。

最终目录fsync若在指针替换后失败，返回PublicationUncertain：新指针可能
已经可见，不能宣称旧代仍保留为current，也不能盲目重试。控制器须重新
load核对并报告未确定的持久性。真实断电恢复仍需文件系统级验证。

## 同题独立实现与修正

两位执行代理独立实现相同要求，不互读结果。main分别复跑原测试，A为
45passed/0.66s，B为45passed/0.81s。main另行复现A丢失已提交指针后返回
None的问题，以及B记录被破坏仍可发布后返回成功的问题。

选择B的普通fd约束和缺失指针拒绝方案后，main补元数据/指针发布前读回，
以及租约context吞掉reset异常时的失败保护。新增三项故障回归，原候选均
保留未改；选择基于实际行为和证据，不基于模型投票或测试数量相同。

## 复现与证据

在runtime/analysis目录执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider --color=no -q test_setting_store.py
```

main结果：48passed，0.83s，退出0；git diff --check通过。
测试仅使用临时合成数据，覆盖跨进程加载/锁/CAS、软链接/权限/硬链接/FIFO、
损坏/缺失/摘要失败、空间与发布故障、确认/离线租约/异常吞掉、SD和外部
文件保持不变。没有创建或销毁真实用户相机实例。

setting_store.py为13204B，SHA256
71b6e5d9521865c24ba03be091e38c304b778205d7a5488384c0540dedd37f4d；
test_setting_store.py为17779B，SHA256
d12fba598547938ae823961b86dc408e88dab6f2d96dd7901f88e221727bead0。

下一验收须由原固件改菜单参数，经已核原提交接口保存，正常停止后重建VM，
再关闭重开UI，以原API和原LCD双读确认；UI销毁重初始化还需范围确认、
稳定实例生命周期锁及默认保留SD的实际接线。上述链路当前仍未完成。
