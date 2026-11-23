# 微信文件传输助手后台发送 — Codex Skill

将用户指定的本地文件自动提交到已登录微信的“文件传输助手”，不激活窗口、不点击、不模拟键盘、不使用 ClawBot。保留回执，并通过本机共享账本防止多个 Codex 线程重复发送。

**v0.3.0：微信 4.2.0.53 后台附件适配已通过真实验证。**新文件组件已编译并随包提供，完成不发送探测、一次 758 字节新 PDF 的原生提交及安全卸载；重复调用被共享账本拦截，旧文档未重发。回执由宿主读取并保存，避免依赖微信进程写外部回执路径。此结论不等于独立确认服务器上传或手机端收件。[脱敏验证证据](skills/wechat-filehelper-background/references/validation-4.2.0.53.json)

## 安装到 Codex

完整可复制版本见 **[发给 Codex 的安装／更新提示词（v0.3.0）](docs/install-update-prompt-zh-CN.md)**，包含保留发送记录、纯后台发送和防重复要求。

把以下文字发送给另一个 Codex：

> 请使用 skill-installer 从 https://github.com/bowenhoucn/wechat-filehelper-background 安装 `skills/wechat-filehelper-background`，版本 `v0.3.0`。若已安装，先备份旧 skill 文件夹，再安装新版；不要删除 `%LOCALAPPDATA%\CodexWeChatFileHelper` 的账本和回执。读取 SKILL.md 并运行 bootstrap，发送时我会提供文件路径。

或用 Codex 自带安装脚本：

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" --repo bowenhoucn/wechat-filehelper-background --path skills/wechat-filehelper-background --ref v0.3.0
```

安装后下一轮使用新版技能。下载 skill 需要访问 GitHub；之后的运行时安装完全离线，不再需要 Git 或访问 PyPI，也无需本机安装编译器。实际执行需要 Windows x64、Python 3.10+（含 pip）及已登录的桌面微信。支持 **4.1.15.56 和 4.2.0.53 的指定核心指纹**；版本号相同但指纹不同也会拒绝。v0.2.0 的离线依赖、缺文件修复和旧版通道保留，不误报未登录、不自动降级。

## 使用

在 Codex 中说：

> 使用 $wechat-filehelper-background，把 `C:\交付\分析结果.pdf` 后台发到我的微信文件传输助手，保留回执。

也可调用脚本：

```powershell
python "<skill>/scripts/bootstrap.py"
python "<skill>/scripts/send_file.py" send --file "C:\交付\分析结果.pdf"
python "<skill>/scripts/send_file.py" status
```

辅助进程必须隐藏启动；脚本不会操作微信界面。发送命令固定 `filehelper`，不会把用户任意联系人作为参数开放。

## 可靠性边界

- 不同线程/安装共用 `%LOCALAPPDATA%\CodexWeChatFileHelper`，以账号哈希和文件 SHA256 去重，改名仍能拦截。
- 发送前保存不可并发修改的快照与持久预登记；崩溃/超时后结果待核实，不盲目重发。
- 保存原生回包和 JSON 回执，记录组件是否卸载。旧结果不覆盖。
- `native_submission_accepted` 表示原生提交成功，**不代表独立核实服务器上传完成或用户下载**。本项目不承诺跨电脑或网络端严格恰好一次。
- 这是第三方原生组件方案，不是腾讯官方公开 API。组件临时加载到微信进程，版本不匹配会拒绝发送；不会更改微信安装、安全设置或读取无关聊天。

## 开发与测试

```powershell
python -m unittest discover -s tests -v
```

自动测试不连接微信，不发送测试文件。真实环境只读检查用 `send_file.py doctor`。冻结上游提交、校验清单和详细状态解释见 [SKILL.md](skills/wechat-filehelper-background/SKILL.md) 和 [operation.md](skills/wechat-filehelper-background/references/operation.md)。

## 许可与来源

本仓库独立封装采用 MIT 许可。原生上游 helper 固定提交 `bdbe97d4e3213fb6c85dee2339aba326d03612b4` 采用**非商业许可**；原仓库已返回 404，`assets` 中原样归档保留了完整许可和第三方声明，封装许可不替代上游许可。归档包含原生源码及二进制，详见 [第三方声明](skills/wechat-filehelper-background/assets/NOTICE.md)。仓库不包含用户文档、账号、发送记录、凭据或微信客户端 DLL。
