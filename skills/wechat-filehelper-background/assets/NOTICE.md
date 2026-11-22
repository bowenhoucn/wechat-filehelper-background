# 第三方运行时归档

`helper-bdbe97d4-runtime.zip` 是 Prometheus-first/helper 的原样 Git archive，提交 `bdbe97d4e3213fb6c85dee2339aba326d03612b4`，包含 native、wxbot_framework、LICENSE、THIRD_PARTY_NOTICES.md。文件未修改，保留了原许可证与第三方声明；其中源码、原生组件适用 **helper 非商业许可**，不适用本封装的 MIT 许可。请在使用前阅读压缩包根目录 LICENSE。

原仓库在 2026-11-22 返回 404。为恢复可重复安装，使用此前保存并校验过的原始 Git 提交生成这份归档，不从不明二进制镜像取代。压缩包 SHA256 和其中运行时文件的 SHA256 均保存在 references/runtime-lock.json；只要不同就拒绝安装/加载。提供归档不代表增加了对新版微信的兼容支持。

`pefile-2023.2.7-py3-none-any.whl` 原样取自 PyPI，许可为 MIT，版权声明保留于 wheel 内。精确 wheel 哈希见 requirements.lock 和 runtime-lock.json。

当前归档含旧版接口源码和组件。4.2.0.53 的普通附件适配尚不能因这些文件齐全而被视为通过。
