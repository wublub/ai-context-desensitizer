# AI Context Desensitizer

一个面向日常 AI 对话场景的轻量级桌面脱敏工具。发送给 AI 之前先做脱敏，收到 AI 回复后一键还原，复制结果可直接粘贴到 Word 并保留格式。

## 功能特点

- **文本脱敏与还原**
  - 将原文中的敏感内容替换为占位符 `[名称]`
  - 基于映射将 AI 返回内容一键还原回原始文本
- **Word 友好复制**
  - Windows 下同时写入纯文本与 HTML 剪贴板格式
  - 标题、列表、粗体、斜体、表格、水平线、引用块、复选框列表等 Markdown 格式可直接保留到 Word
- **左侧关键词列表**
  - 双击直接改名
  - `Delete` 键删除选中条目
  - 点选可联动标黄对应位置
- **快捷键**
  - `Ctrl+C`：在原文窗口中对选中文字命名；在脱敏后/还原后窗口中复制结果
  - `Ctrl+F`：按名称定位左侧条目，可直接修改或删除
  - 快捷键可在设置中自定义

> 注意：请确保你拥有处理相关数据的权限，并遵守当地法律法规与合规要求。

## 快速开始

### Windows

1. 从 [Releases](https://github.com/wublub/ai-context-desensitizer/releases) 下载 `ai-context-desensitizer-windows.exe`
2. 双击运行

### macOS

1. 下载 `ai-context-desensitizer-macos`
2. 给执行权限并运行：

```bash
chmod +x ai-context-desensitizer-macos
./ai-context-desensitizer-macos
```

如果提示被系统拦截：系统设置 → 隐私与安全 → 允许打开

### Linux

1. 下载 `ai-context-desensitizer-linux`
2. 给执行权限并运行：

```bash
chmod +x ai-context-desensitizer-linux
./ai-context-desensitizer-linux
```

## 使用流程

### 发送前（脱敏）

1. 在"原文"中粘贴内容
2. 用鼠标选中敏感词，按 `Ctrl+C` 为其命名
3. 程序自动生成占位符并更新脱敏结果
4. 在"脱敏后"按 `Ctrl+C` 或点击"复制"，粘贴给 AI 或 Word

### 收到后（还原）

1. 在"AI返回"中粘贴 AI 回复
2. 程序根据已有映射自动还原
3. 在"还原后"按 `Ctrl+C` 或点击"复制"即可

### 修改或删除已有名称

1. 按 `Ctrl+F` 输入名称
2. 自动定位到对应条目
3. 直接修改名称，或按 `Delete` 删除

## 版本更新

### v0.1.3

- 新增 Markdown 水平分隔线（`---`）转换支持
- 新增引用块（`>`）转换支持
- 新增复选框列表（`- [ ]` / `- [x]`）转换支持
- 修复 Claude 等模型返回的 Markdown 复制到 Word 后格式丢失的问题
- 关闭打包时的 console 窗口（不再弹出黑框）
- 清理无用代码和文件

### v0.1.2

- 新增 `Ctrl+F`，可按名称快速定位并直接修改/删除条目
- 调整 `Ctrl+C` 分区行为，发送前原文支持"选中文字即命名"
- 改进 Markdown 到 Word 的复制体验
- 增强 Markdown 表格复制效果
- 支持左侧列表双击直接改名

## 仓库

GitHub: https://github.com/wublub/ai-context-desensitizer
