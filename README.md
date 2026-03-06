# AI Context Desensitizer

一个面向日常 AI 对话场景的轻量级桌面脱敏工具。你可以在发送给 AI 之前先做脱敏，在收到 AI 回复后再一键还原，并尽量保持原文结构与阅读体验。

## Features / 功能特点

- 文本敏感信息脱敏与还原
  - 支持把原文中的敏感内容替换为占位符
  - 支持基于映射将 AI 返回内容还原回原始文本
- 左侧关键词列表可直接双击改名
  - 不再依赖单独的“改名”按钮
- 发送前 / 收到后结果区支持 Markdown 友好展示
  - 粘贴 Markdown 后会自动转换为更适合阅读与复制的格式
- 复制内容更适合粘贴到 Word
  - Windows 下会同时写入纯文本与 HTML 剪贴板格式
  - 标题、列表、粗体、斜体、链接、表格等常见 Markdown 结构可更好保留
- 快捷键更贴近日常操作
  - `Ctrl+C`
    - 在“发送前-原文”窗口中：对当前选中文字快速命名
    - 在“发送前-脱敏后”窗口中：直接复制结果
    - 在“收到后-还原后”窗口中：直接复制结果
  - `Ctrl+F`
    - 快速按名称定位左侧条目
    - 定位后可直接修改名称，或按 `Delete` 删除
- 支持高亮定位
  - 可仅高亮当前选中项
  - 也可切换为高亮全部匹配项

> Note: Please ensure you have the right to process the data and comply with local laws and regulations.
> 注意：请确保你拥有处理相关数据的权限，并遵守当地法律法规与合规要求。

---

## Quick Start / 快速开始

### Windows 怎么用

1. 下载 `ai-context-desensitizer-windows.exe`
2. 双击运行

### macOS 怎么用（常见会提示“无法打开/来自不明开发者”）

1. 下载 `ai-context-desensitizer-macos`
2. 第一次先给执行权限：

```bash
chmod +x ai-context-desensitizer-macos
```

3. 运行：

```bash
./ai-context-desensitizer-macos
```

如果提示被系统拦截：

- 系统设置 → 隐私与安全 → 允许打开

### Linux 怎么用

1. 下载 `ai-context-desensitizer-linux`
2. 给执行权限：

```bash
chmod +x ai-context-desensitizer-linux
```

3. 运行：

```bash
./ai-context-desensitizer-linux
```

---

## Common Workflow / 常见使用流程

### 发送前（脱敏）

1. 在“发送前-原文”中粘贴内容
2. 用鼠标选中敏感词
3. 按 `Ctrl+C`，为该选中文字命名
4. 程序会生成对应占位符并自动更新脱敏结果
5. 在“发送前-脱敏后”中按 `Ctrl+C` 或点击“复制”后，直接粘贴给 AI / Word

### 收到后（还原）

1. 在“收到后-AI返回”中粘贴 AI 回复
2. 程序会根据已有映射自动还原
3. 在“收到后-还原后”中按 `Ctrl+C` 或点击“复制”即可复制结果

### 修改或删除已有名称

1. 按 `Ctrl+F`
2. 输入左侧名称
3. 自动定位到对应条目
4. 直接修改名称，或按 `Delete` 删除

---

## Shortcut Keys / 快捷键

- `Ctrl+C`
  - 发送前-原文：命名当前选中文字
  - 发送前-脱敏后：复制结果
  - 收到后-还原后：复制结果
- `Ctrl+F`
  - 按名称快速定位左侧条目，便于修改或删除
- `Delete`
  - 删除当前选中的左侧条目
- 自定义快捷键
  - 可在设置中修改“命名快捷键”和“标黄全部快捷键”

---

## Release Notes / 版本更新

### v0.1.2

- 新增 `Ctrl+F`，可按名称快速定位并直接修改/删除条目
- 调整 `Ctrl+C` 分区行为，发送前原文支持“选中文字即命名”
- 改进 Markdown 到 Word 的复制体验
- 增强 Markdown 表格复制效果
- 支持左侧列表双击直接改名

---

## Repository / 仓库

GitHub: https://github.com/wublub/ai-context-desensitizer
