# doccheck

检查仓库内 Markdown 文档是否满足 `docs/AGENTS.md` 的约束。

## 运行

```bash
python tools/doccheck/check.py
```

在仓库任意位置执行都可以，脚本按自身位置定位仓库根。Python 3（CI 用 3.12），只用标准库。

## 配置

`budget.json` 按目录给出全篇、单个二级章节、单个段落的字数上限：`default` 适用于未单列的目录，其余键是仓库相对路径，取最长匹配。改上限时按 `docs/AGENTS.md` 第 5 节说明理由。

## 输出

- `::error file=…,line=…::`：字数超限、相对链接指向不存在的文件、指代无法在 HEAD 定位。有错误时退出码为 1。
- `::warning file=…,line=…::`：历史叙述、推导过程、跨文档重复的句子。不改变退出码。

GitHub Actions 在改动 Markdown 的 PR 上运行同一条命令。

## 限制

- 只检查 `.md` 文件。
- 代码块不计入词表检查与重复检查，仍计入字数。
- 中文引号包住的词不触发词表检查，供文档引用禁用词时使用。
