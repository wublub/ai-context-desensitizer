# AI Context Desensitizer

A lightweight tool for desensitizing sensitive information in text data and documents.  
一个轻量级的文本脱敏工具，用于对数据或文字资料中的敏感信息进行脱敏处理。

---

## Features / 功能特点

- Desensitize sensitive data in text (e.g., names, phone numbers, ID numbers, addresses, emails).  
  对文本中的敏感信息进行脱敏（如姓名、手机号、证件号、地址、邮箱等）。
- Keep the original context readable while masking sensitive parts.  
  在尽量不破坏上下文可读性的前提下进行遮罩/替换。
- Easy to extend rules / patterns.  
  脱敏规则可扩展、可按需增加匹配模式。
- Supports batch processing (optional, depending on your implementation).  
  支持批量处理（如项目实现包含该能力）。

> Note: Please ensure you have the right to process the data and comply with local laws and regulations.  
> 注意：请确保你拥有处理相关数据的权限，并遵守当地法律法规与合规要求。

---

## Installation / 安装

### 1) Create venv (recommended) / 创建虚拟环境（推荐）
```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
