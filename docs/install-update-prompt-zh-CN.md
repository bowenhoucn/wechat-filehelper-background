# 发给 Codex 的安装／更新提示词（v0.3.0）

复制下面整段发给其他 Codex，即可要求其安装或更新，并保留已有发送记录。本段只授权安装与只读检查；实际发送时再指定文件。

```text
请安装或更新 GitHub 仓库 https://github.com/bowenhoucn/wechat-filehelper-background 中的 skills/wechat-filehelper-background，固定版本为 v0.3.0，使用 skill-installer 完成。若已安装，先备份旧 skill；完整保留 %LOCALAPPDATA%\CodexWeChatFileHelper 中的发送账本、回执及快照，禁止清空或重建空账本来绕过历史记录。安装后完整读取 SKILL.md，运行 bootstrap 和只读 doctor，确认运行时完整、微信核心指纹受支持；本次仅安装更新，不发送测试文件。以后我明确指定本地文件并要求发送时，直接纯后台发送到当前本人微信的 filehelper，不再重复询问发送许可；不得操作窗口、模拟按键、使用剪贴板，也不得改走 ClawBot 或网页渠道。所有线程及安装共用原账本，按账号与文件内容 SHA256 去重；已有提交或结果待核实记录时禁止自动重发，改名也不能绕过。保留每次原生回包及发送回执，准确区分“原生提交成功”和“已独立确认收到”。只有我明确要求重发同一内容时，才记录原因后再次发送。
```

## 安装完成后的发送示例

将路径替换为实际文件路径，再把下面这句话发给 Codex：

```text
使用 $wechat-filehelper-background，把 C:\交付\分析结果.pdf 后台发到我的微信文件传输助手，保留发送回执，不操作窗口，不重复发送。
```

## 使用范围

- 需要 Windows x64、Python 3.10+（含 pip）及已登录的桌面微信。v0.3.0 支持 4.1.15.56、4.2.0.53 的指定核心指纹，其他指纹不会自动放行。
- 去重依赖本 Windows 用户的共享账本。换电脑时应先迁移可信历史记录；不能把新机器的空账本视为旧文件从未发送。
- 新版 skill 安装后在下一轮对话使用。原生提交成功不代表已独立确认服务器上传完成或手机端收件。

详细说明见 [SKILL.md](../skills/wechat-filehelper-background/SKILL.md)；固定版本下载见 [v0.3.0 发布页](https://github.com/bowenhoucn/wechat-filehelper-background/releases/tag/v0.3.0)。
