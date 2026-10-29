# 跟踪实际dialog文本资源，避免把语言页当SD错误原因

目前可见图像仍是日文“无法正确读取存储卡”，但对应原dialog消息/producer尚未闭合。
group311/31e/b1c..b3d已经确认为语言DST列表，不能继续作为媒体故障predicate。
本记录只读原对象与文本参数，不改getter、dialog、boot模式、媒体状态或UI切屏。

## 原路径和动态栈

原appFw SHA256固定为`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`。
所有appFw地址为ELF VA。

`run-yquhg8jh`在无MENU条件下，真实screen322创建栈：

```text
1d56688 ← 1d5677c ← 1e4bb44 ← 1e773f8 ← 1e78c70
         ← 1e795ec ← 179a314 ← 1796ef4 ← 36ec1b0
```

这是UI消息派发后的构造栈，不直接包含更早enqueue的错误producer。
console SHA256=`42954657a1d3c948b223198d7bc531b9c08febac98aed15f32c985ee87306fbd`。
有界栈读取只使用`/proc/self/mem`，16层/256KiB窗口，拒绝无效/非单调/非对齐帧，保存errno。
host测试以真实proc读取fixture验证不写原帧、坏帧拒绝和errno恢复。

## Resource identity 的证据链

| Evidence | Finding | 只读采集 |
|---|---|---|
| factory T[322]=520a4d0，presenter factory1d56790→1d56758→1d5654c | 当前为dlt01_presenter通用dialog，非单独SD controller | 不从screen322名称诊断SD |
| 原1d56758将P放x19，再调用构造器；构造器保存old x19到FP+10 | 当前create调用的上级构造帧+10保存P | 只在首LR==1d56688且callerFP有界时读P |
| P.vptr59590b8、P+30=322、P+2ac8=getter | 可验证真实对象与getter身份 | /proc读取并核vptr/screen，然后记录getter/vtable/method，不调用或替换它 |
| 1ab8ca0尾跳getter.vptr[0](getter,&P.screen,out) | x1是screen字段地址，x2为输出，不是猜测的值参数ABI | 当前不装getter hook，保留原virtual调用 |
| 1ab8f8c调用后，1ab905c读selector，1ab9068写view-string.param+30 | 渲染器实际使用的32位文本资源值 | 在既有原drawFramebuffer返回后读P+28→array+38→param+30，要求array+30 kind2 |

主会话独立核原1d5654c/1d56758 prologue、1ab8ca0尾跳和1ab8f8c..9068 store，
确认不需要依赖observer编译器的寄存器保存偏移，也无需新增getter trampoline。
只有匹配的原dlt01对象会记录`RESOURCE_DIALOG_GETTER_CAPTURED`和`RESOURCE_DIALOG_VALUE`。
每个对象最多记录16个变化值；未匹配/不可读就不推断。
selector是UI资源键，不是Fsys错误码，需要继续跟实际getter实现和自然writer。

## 当前sequence对象与启动字段

同run只读manager group0 current得到O=`7f84170760`，vptr=B+`5b30e10`。
原64位RTTI链`*(vptr-8)→typeinfo→*(typeinfo+8)`独立解析为`N5model13sequence_bootE`，
因此可以将其字段与原run内定义交叉核对：O+68=0、O+74=0、O+80=1b。
前两项对应原日志ee_cap、boot_factor Attr，后一项枚举名仍未知。
这些观测只说明为什么执行post-completion特定分支，不能自动归为错误启动或SD故障。

本轮尚未含新的presenter/text参数采集；下一轮已在同无MENU启动条件下运行。
没有直接写原model或试不同boot_type以绕开错误。

## 实际文本getter与selector

`run-1_77s6pg`已成功采到原P=`7f55c80190`，getter在构造时=`7f4e10ced0`，
其vptr=B+59128c0，method=B+1882dc8。主会话独立RTTI解析为`caution::caution_module`，
不是先前静态候选screen_caution_resource_getter；thunk调整this-=8后进入1882c7c。
原view-string.param+30实际值为**0200a73b**，且实际RGBA摘要仍完全等于原错误页，
没有因只读采集改变画面。证据见`dialog-text-resource-native-proof.json`。

该getter读u16 active index（具体对象base+18，即接口getter+10），按58f03a8/index*a0选原记录。
它依据记录+50/+40的原predicate选+58/+48/+38的资源指针，复制其它原dialog参数。
当前u16 index尚未动态取得；不能仅从selector判断filesystem错误。

主会话扫描同原ELF的0200a73b literal及relative字段，原模块表中只有两个已匹配候选：

| 模块index | 记录ELF VA | 资源字段 | predicate+10 | 记录screen字段+2c |
|---|---|---|---|---|
| 233 | 5906388 | +48→377d000 | 187f89c（getter28789d0） | 321 |
| 262 | 59080e8 | +48→3781f48 | 187f8dc（getter28787f0） | 322 |

field+40分别18826d0/18826b8，均跳18758fc；不能把该资源投影条件直接当媒体故障predicate。
新的只读采集在构造时严格验证vptr/method后取实际u16 index，frame后只读最终text参数，
不再追读可能为临时对象的getter。另采两候选的原model输入：7e80dd0/7e80f50。
独立调查追187f8dc的实际自然writer，主会话负责实际index与字段采样；没有清模型错误位。

## 活动模块已动态消歧

`run-0xqk0apm`在构造时严格匹配真实getter vptr59128c0和method1882dc8，
实际读取u16 module_index=**262**（index_known1），显示selector仍0200a73b。
其原predicate getter28787f0的数据B+7e80dd0真实u32=**2**，次候选233不作为当前原因。
console SHA256=`a25d6960e21afa8f1f019638b41c67fa14e892c3b672d8d08add9cf987cf64a5`。
原UI模型没有被清零或改写，仍是同一原错误画面。

index262是caution_module内部活动index，不能直接当作对外caution ID、Fsys错误码或语言项b1d。
下一链是predicate187f8dc→真实model名称/自然writer→设备/配置输入。
对照脚本与新的原资源链验证器明确分开，尚未证明mount失败或boot record错误。

这条实际链已通过2测试/4种index、model、resource和method破坏负例，
正式`dialog-resource-chain-proof.json`保存actual_dialog_resource_chain_verified=true，
同时保留model_name_and_natural_writer_verified=false、filesystem_or_mount_error_proven=false。
项目同步及pytest244 passed/1 skipped/58 subtests passed再次通过；两组Cryptodome缺口照约定排除。
新增原appFw选定镜像身份及第五负例正在补跑，不能把前项结果宣称为已覆盖所有来源。

补充校验已通过：原appFw选定镜像必须匹配固定SHA且original_libraries_unchanged=true，
第五个身份篡改负例被拒绝，2测试通过。未改变已记录的module262/原model2/selector0200a73b；
该链仍不证明模型自然writer、mount故障或boot参数错误。

后续原metadata/writer静态调查已返回：ed1=media_mount_state_slot1，edd=media_error_slot1，
原262 predicate自身先检查2再检查1，仍有其他门控。验证器现同时要求两项只读采样，
2测试/六项篡改负例通过，更新的正式proof已归档；不把两个非原子快照称为原子谓词快照。
具体自然错误来源见`media-mount-source-static/CONFIG-QUERY.md`与首轮错误采集记录。
