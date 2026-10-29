# CP4001 实施范围

- auth：用户授权本机公开 ALLLANG 派生源的最小 implementation；继续使用既有工作区，保留其它工作；不派发子代理。
- in_scope：`device-models/cp-parameter-state.c/h`、其专属 C 测试；新增 `device-models/functional-cp-zoom.c/h`、专属 C/Python 测试、本报告说明和 pins。
- out_of_scope：menu-observe、build、ABI、broker、其它组件；全仓回归、DSO/full build、VM、真机、真实 SD、私有 dump。
- network_profile：offline，本机 C 编译和测试；不请求外部服务。
- data：只复用 source 调查的公开 AP/CP pins；原 4063 wire、190slot/masks、未知 bytes、已有 parameter view 不被重建或扩充。
- acceptance：实际 12B packet 的四字段源语义、同进程 guarded owner、事务写入/读回、一次原 free 与成功 oneway 标记分离，错误保留原请求所有权或显式 sticky retained fault；始终 applied0/published0/generation0/capture0。
