
你可以把“Features/Usage”里那句“optional”删除，等你把真实功能确定后再补。

---

## D：把产物名/构建名也统一成英文（建议）
你展示名用 `AI Context Desensitizer` 没问题，但**产物名建议用无空格**：  
`ai-context-desensitizer`

如果你的 GitHub Actions 里用 PyInstaller，通常改这三类字段：

1) `pyinstaller --name ai-context-desensitizer ...`
2) artifact 名 `name: ai-context-desensitizer`
3) release 上传的文件名/路径里不要中文和空格

把你的 `.github/workflows/build.yml` 贴出来（尤其是打包那段），我帮你逐行改成统一命名。

---

## 最后：提交 README
```powershell
git add README.md
git commit -m "Update README (CN/EN)"
git push
