# Native 本地模型源码

按用户要求，从同仓库的 full-system 成果中复制公开 C/头文件与必要验证工具。
此目录现在是 native 使用的本地副本：读取、修改、测试和编译均只操作这里，
不通过跨目录 include、实时读取或自动同步依赖原目录。

`UPSTREAM-COPY.json` 记录首次复制来源及原始副本摘要；后续 native 适配不改写该记录。
每次构建另生成 `observer-build-inputs.json` 和源码归档，记录实际编译版本。

只复制源码与测试工具，没有复制 root、setting、固件、镜像、运行日志或私有数据。
验证器的 libfdt 路径已改为 native 自己的公开工具目录。

在本目录可运行 `python3 test-pin-control-verifier.py`、
`python3 test-pin-format-verifier.py`、`python3 test-pin-connection-verifier.py`。
这些测试使用本地C producer构建fixture；旧连接回归中的私有run不可用时明确跳过，
不会从full目录补取运行数据。native真实内容验证另用`A7C2_NATIVE_PIN_RUN`指定实际运行目录。
首次迁移遗漏的`test-pin-control-verifier.py`已补复制，摘要亦记录在来源清单中。

`verify-vef-pin.py::verify_registry(..., native=True)`直接接受native运行元数据。
DrawInfo回归通过`A7C2_NATIVE_GET_RUN`指定已存在的DrawInfo运行，再执行
`python3 test-native-registry-verifier.py`。这些检查只证明Get内容和原waiter释放。
其它复制的full专用CLI尚未逐个适配，不应直接套用于native数据。

已有模型仍保留各自范围：配置缓存与 pin metadata 不代表连接、帧、传感器或拍摄成功。
