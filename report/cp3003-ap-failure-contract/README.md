# AP3003：发送失败致命，未找到合法推进的错误回包

当前证据没有一条可用的原AP降级路径能在缺失3003状态时合法推进UI。立即`osal_snd_msg`非零是致命断言；收到非F000状态虽被这个局部调用者忽略，但本轮未找到可据以生成这种CP3003错误回包的source producer。因此不新增错误注入profile、不用错误容忍掩盖未完成START，也不强写EE/current/ready。

本次仅公开ALLLANG AP/CP只读静态ELF、原字节和调用边核对，无执行固件/VM、网络、设备或private/full。两原件完整身份、8窗口2294B及映射在[source-pins.json](source-pins.json)，独立于3249/381冻结轮，不回填旧运行。最后真实run-nzx01uc3仍3003/EE0，无JPEG/MP4。

## 原调用边

```text
338ea5c BL34cb808
34cb830 BL3546040
3546068 MOV w0,#3003
35460a4 BL35358b8
```

这些原指令独立于saved stack候选解释。请求type0、24B、source80020002、destination90030001，wire为000003302700008000000000000000000000000000000000。

## 即时send错误没有降级

35358b8经3599b68分配/复制request。该wrapper的ELF imports/relocations为osal_valloc_msg_wait、osal_set_msg_src与memcpy。3535a64调用osal_snd_msg PLT，3535a68检查返回；非零进入assert logging，usleep100000微秒，再由3535af4调用35aa4b4。

35aa4b4在35aa4d8调用imported __assert_fail：expression=false，file=lib_assert.cpp，line=2eh/46，function字符串为`void lib::assert::notify_model_system_error()`。之前的assert标记infra_wrapper_imaging_ipsx_sp_pp_branch.cpp第c25h/3109行。只有send0分支到达reply waiting；这里没有转换成普通RPC错误或NoLens默认值并返回。

原request已经分配，非零send分支在fatal前没有osal_free_msg。拒绝handler仍须维持caller-owned语义，不能把返回负值当作所有权转移，也不能声称已经完成reply/free。

现有strict集成在数据不可用时由menu-observe的provider返回-ENODATA；cp-state-publication将其作为handled=1/result传出，原osal_snd_msg wrapper直接返回该result。按原AP代码，这会assert，不是“解除等待后降级”。该静态结论不是新VM执行结果；最后旧run早于strict owner。

## 收到错误状态是另一回事

send成功并收到reply后，generic helper复制完整16字节并free回复。35460a8将`reply.u32[8] != f000`写入caller_result，随后在mutex下清byte91166ec。34cb808不检查result；其338ea60调用者也不重读FP+50结果，随后写原`EV CamReady`日志并return。

所以“已被该helper接受的非F000回包不会使此caller退出”是局部条件事实。它不证明CP应发这种包，不证明真实硬件已ready，也不是代理可以编造状态码/尾部data的授权。

## CP3003是START，不是可省略getter

CP decoder在4b6118把3003映射event2；已有START合同中的慢路径为b21898→b21702→4b28d8(3003,1)。完成builder b224a8/b224ae固定type1、cmd3003、statusF000，并带四个真实cache/getter字节，不从failure参数接收status。本轮看到的START guard内部负结果未建立替代CP3003 error packet。

即时AP函数也没有NoLens或release-without-lens setting测试。没有证明该正常camera功能能替代START失败；不改backup字节或设置ready。

## 符号与映射限制

appFw.so长99960744B，SHA2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b。950条dynsym中唯一named defined symbol是Application_System_Init，没有symtab；内部C++名字来自编译器assert字符串，不能称作恢复的导出。该generic名字为`infra_wrapper_imaging::detail::execute_infra_cmd_i(...)`；OSAL与__assert_fail imports则由真实GOT/PLT relocation验证。

列出的AP窗口都在PT_LOAD1（offset=VA=0，filesz51a6cff），所以本表VA=file offset；PT_LOAD2 offset51a7718、VA51b7718，不能统一减同一基址。CP独立使用VA-108000。

E1（原send/error/assert）→F1（立即失败fatal）；E2（reply-copy/result/caller）→F2（局部容忍不等于合法producer）；E3（CP event2/固定completion）→F3（START缺数据仍不能绕过）。原生UI、EE与capture未验收，保持data0/4、capture=false。下一步需真正闭合输入/START工作，不制造success或unsupported reply来利用caller忽略结果。
