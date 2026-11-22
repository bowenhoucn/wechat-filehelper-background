---
name: wechat-filehelper-background
description: 在 Windows 上将用户指定的本地文件纯后台发送到本人微信文件传输助手，保存原生回执并跨 Codex 线程防重复发送。用于“发到微信文件助手”“后台给我发文件”等明确发送请求；不操作窗口，不发送给其他联系人。
---

# 微信文件助手后台发送

适用于 Windows x64、Python 3.10+、已登录的桌面微信。当前仅允许经过本方案实测的 **4.1.15.56 核心指纹**。使用固定版本的第三方原生组件，临时加载到微信进程，调用附件发送后卸载；它不是腾讯官方公开 API。上游采用非商业许可，见 [运行方式与限制](references/operation.md)。

## 执行

用户明确要求发送指定文件即构成发送授权，无需重复确认。文件不明确时先确定目标；仅制作文件、讨论方案或安装此 skill 不构成发送授权。接收方始终是当前唯一登录账号的 `filehelper`，不扩展到其他联系人。

以下 `<skill>` 指本 SKILL.md 所在目录。使用参数数组或正确的 shell 引号，不把文件路径拼接成可执行代码。

1. 首次使用运行 `python "<skill>/scripts/bootstrap.py"`，下载固定提交及带哈希的依赖。它不启动微信、不发送文件；后续正常发送无需反复安装。
2. 已登录微信且运行时已就绪时，直接执行：

   ```powershell
   python "<skill>/scripts/send_file.py" send --file "C:\交付\结果.pdf"
   ```

   多个指定文件逐个发送。不要并行启动，也不要因为耗时或暂时没有输出就终止、重试。首次安装排错可运行 `doctor`，该子命令只读检查，不注入组件、不发送。
3. 读取返回的 `status` 和 `receipt_path`，按真实结果回复。原始回包和回执在 `%LOCALAPPDATA%\CodexWeChatFileHelper\receipts`，SQLite 账本在同一数据根目录。**多个 skill 安装和多个 Codex 线程必须共用此目录**，不要改成项目私有账本。文件快照和发送前预登记会自动完成。

必须隐藏启动辅助进程。PowerShell `Start-Process` 加 `-WindowStyle Hidden`；Python 子进程使用 `CREATE_NO_WINDOW`，Node 使用 `windowsHide: true`、`shell: false`。不要激活、还原、点击微信窗口，不模拟按键，不通过剪贴板交付，也不回退 ClawBot 或网页文件助手。

## 回执判断与防重复

| 状态 | 含义与处理 |
|---|---|
| `native_submission_accepted` | 原生提交成功，组件已卸载。**不等于独立证实服务器上传完成或对方收到**。保留回执，不再发一次。 |
| `duplicate_blocked` | 同账号、同内容 SHA256 已有提交或待核实记录，本轮未发送。读取返回的旧回执。改文件名或换线程不能绕过。 |
| `needs_reconciliation` / `dispatch_started` / `preparing` | 结果可能不确定或进程中途结束，禁止自动重发、清账本或删占位。读取原生回包定位；如果没有可靠证据，明确结果待核实。 |
| `failed_before_dispatch` / `blocked_before_dispatch` | 没有进入发送调用；按具体原因局部修复。不要以“需要修复”为由操作微信窗口、关闭安全防护或盲改版本限制。 |
| `historical_submission_imported` | 已导入旧发送证据，防止同一文件再次自动发送；不新增上传完成结论。 |

查记录：`python "<skill>/scripts/send_file.py" status --id "<返回的id>"`。这只读本地账本，不是服务器收件查询。用户明确要求**重复发送相同内容**时，才可追加 `--resend-reason "用户明确要求再次发送：具体原因"`；该操作保留旧记录并新建关联回执。不要自行编造重发理由。

用户说“已收到”可在回复中据此确认，但不能把原生代码的 `completion_success` 当作用户收件证明。对于相同文件，默认保证本机账本范围内的不重复调用，不能声称网络端严格“恰好一次”。另一台电脑不共享此账本；跨机器发送先迁移必要历史或说明去重范围。

版本不匹配、未登录、多账号、已有其他原生组件时直接停止并说明具体限制。不得为完成发送擅自升级/降级微信、终止其进程、改安全设置、卸载别人的组件、读无关聊天或提取凭据。不要更改固定提交或删哈希限制来凑兼容。

旧一次性脚本的回执迁移、状态解释与已验证范围详见 [operation.md](references/operation.md)。
