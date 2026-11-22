# 实现、兼容性和故障处理

## 固定依赖

- 原生实现：[Prometheus-first/helper](https://github.com/Prometheus-first/helper)。固定提交 `bdbe97d4e3213fb6c85dee2339aba326d03612b4`。
- 核心调用：`native/run_selftest.py` 中 `run("--dispatch", target="filehelper", file_path=..., account=..., bridge_path=TEXT_DLL)`。附件探测加 `file_probe=True`，不发送消息。
- 上游二进制：`native/build_text/text_bridge.dll`。SHA256 `20b5ba37ac00b1b26a9ac13b82ae80e48f59cf61eb486dff947840c70923c936`。
- 本 skill 实测允许的微信核心：4.1.15.56，204305968 字节，SHA256 `e0428a7b691853de496532523c2c09aa095f90941c37c9f4cfb3f137f3c66556`。上游列出的其他版本不自动构成本 skill 已验证范围。
- 运行时路径：`%LOCALAPPDATA%\CodexWeChatFileHelper\runtime\<固定提交>`。`runtime-lock.json` 校验上游 Python 源码、配置、组件和许可文件；`requirements.lock` 固定 `pefile` wheel 哈希。每次加载前验证所需文件。
- Git 与 pip 子进程均隐藏、无交互启动，不运行上游完整机器人服务、Web 面板或监听服务。

上游是非商业许可，允许个人学习、研究、测试及非商业自用，不自动授权商业产品或营利服务。准确条款以 [固定提交 LICENSE](https://github.com/Prometheus-first/helper/blob/bdbe97d4e3213fb6c85dee2339aba326d03612b4/LICENSE) 为准。此仓库只提供独立封装，bootstrap 从上游取得原组件并保留其 LICENSE 和 THIRD_PARTY_NOTICES。封装的 MIT 许可不覆盖上游组件。

## 结论分层

1. 本地文件一致：SHA256、大小、发送快照一致，原始文件发送途中改变不影响已冻结快照。
2. 原生提交成功：接收方、附件类型、路径、字节数、返回码、完成标记及卸载均匹配。
3. 服务器上传完成或用户已收到：需要独立证据。当前无通用后台服务器收件查询实现，因此第二层不能自动提升为第三层。

原生接口返回后可能仍有异步网络发送；不因未知网络状态而盲目重试。微信升级、账号切换、组件未卸载、超时都保持真实状态和旧证据。

## 去重和崩溃恢复

- 以当前账号标识的 SHA256 + 文件内容 SHA256 去重，接收方固定 `filehelper`。路径、文件名、线程 ID 都不改变去重键。
- 一把操作系统文件锁串行化本 Windows 用户下的操作，进程退出后由 OS 释放。不要删除锁文件解锁。
- SQLite `synchronous=FULL` 在发送前写入 `dispatch_started`；JSON 提供易读回执。保存回包前崩溃仍保留阻止重发的状态。
- 探测失败且尚未调用发送可修复后再试；进入发送调用后的一切不确定结果都要求先核实。
- 明确重发保存原因及上一回执 ID。当前不做自动网络重试，不提供删除账本来“解除阻塞”的命令。
- 快照、原生回包和账本留在本机，不自动上传 GitHub。数据目录跟随 Windows 用户，不跟随项目或 skill 安装目录。另一台电脑不具备本机历史。

## 导入此前一次性发送的记录

适用于已有 `filehelper_native_receipt.json` 及带 `account_sha256` 的 `filehelper_native_attempt.json`。脚本核对两者一致后只登记，不发送：

```powershell
python "<skill>/scripts/send_file.py" import-receipt --receipt "C:\历史\filehelper_native_receipt.json" --attempt "C:\历史\filehelper_native_attempt.json"
```

不为新安装自动扫描私人目录，也不把历史文档带进 GitHub。没有可信旧回执时，不能伪造导入证据。

## 验证范围

2026-11-21 的原先同一原生入口已完成一次真实 28 页 PDF 提交：395292 字节，原生返回成功，附件副本哈希一致，组件卸载成功；未独立验证服务器最终收件。此信息只证明特定版本和该次附件提交。

通用封装的自动化测试使用替身适配器，不会真实向微信发测试文件；测试包含跨路径同内容去重、账号隔离、明确重发、调用异常、进程骤停、并发锁、哈希拒绝、快照不可写、探测失败，以及本地回执保留。只读 `doctor` 验证真实环境兼容，不能替代通用封装的真实发送验收。

## 命令退出码

- `0`：提交成功、重复被阻止，或只读/导入命令成功。仍须检查 `status`，不能只看退出码。
- `1`：前置条件失败（无可用账号、版本/运行时不匹配、锁被占用、文件无效等）。未提交新的附件。
- `2`：已记录的探测失败或结果待核实。读取 `status` 判断是否允许修复后重新尝试。

当脚本没有输出而调用仍在运行时，保留进程并等待工具会话完成。不要因模型一次工具等待超时而启动第二个发送进程；账本虽会拦截重复，但无法替代保留原生回调资源。
