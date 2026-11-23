# 新附件组件的来源与许可

`filehelper_42053.cpp` 派生自 Prometheus-first/helper 的固定提交 `bdbe97d4e3213fb6c85dee2339aba326d03612b4`，只抽取普通附件构造、账号核对、原生调度和资源清理部分。原非商业许可完整保存在同目录 `LICENSE.helper`；根仓库 MIT 许可不替代它。

本目录新组件不使用 MinHook、聊天接收或多媒体转码。原 helper 的完整第三方声明及其依赖许可在 `../assets/helper-bdbe97d4-runtime.zip` 内原样保留，适用于旧版归档中的对应组件。

4.2.0.53 基础位置参考 dsh-world 提交 `3ed75924f8e9914c37911699e0bf0c13629a4c79` 的公开映射，随后对本机精确核心做静态核对和普通附件运行验收；未复制该项目桥接实现。完整来源见 `../references/candidate-4.2.0.53.json`。

新 DLL 使用 Microsoft C++ 静态运行库构建。仓库不包含 Microsoft 编译器/SDK、微信客户端 DLL、用户账号或文件。
