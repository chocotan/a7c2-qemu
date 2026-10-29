# 原CCF API诊断client

只使用正常export的OF node／clock接口，不构造内部device/clk对象、不硬调用Image地址，不触碰PCI、PHY或DMA。目标consumer为派生板的`/sony-test-ccf-consumer`，其七个clock-names／ID对应原controller0。

每项实际核lookup、原rate、初始硬件状态、prepare／enable、`__clk_is_enabled=1`，随后disable／unprepare并核硬件状态回0；clock和node references通过正常put释放。两项NULL-parent gate的预期rate API值为0，不宣称其物理频率0 Hz。返回0或一句PASS都不替代外部SCU真实寄存器序列／状态核验。

主机七个控制情形含node缺失、ERR_PTR、rate错、prepare／enable失败和“返回0但硬件状态未变”，ASan／UBSan已通过，refs／prepared计数检查清零。普通module ABI检查通过：5512B，SHA256：

```text
057c296ae2064d5f15900d7a0d8136869f74fe078592a779462050d4b6b5976a
```

原接口export及有限参数语义由`../verifiers/verify_ccf_client_api.py`另行核。后续trial-db4bp47v已实际执行client，七个原API lookup／rate／prepare-enable／硬件状态／disable、七组实际SCU SET/CLEAR、最终bank读回和CPU退出经main独立`verify_native_ccf.py`通过，见`../native-ccf-validation.json`。这是有限CCF组件验收，不是PLL电气校准、SoC host／PHY或DMA验收，Host fixture本身仍不作原kernel证据。
