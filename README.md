# 原文查找 / Book Source Finder

粘贴中文译文，查找原文出处。左右两个阅读窗显示本章的完整译文与原文，可以独立滚动、点击中文重新定位，也可切换上下排列。

所有查询、书籍和对应关系保存在本机。Python 3.10+，运行不需要额外依赖、账号或 API key。公开仓库只保存工具代码、说明和合成测试数据。

## 启动

在本目录运行：

```powershell
python -m source_finder serve
```

打开 <http://127.0.0.1:8765>。Windows 也可双击 `start.cmd`。终端按 Ctrl+C 停止；占用端口时可用 `serve --port 8766`。

数据库默认为 `data/library.sqlite3`。如果是独立下载本工具，书库初始为空，需要先导入；如果工具位于现有 `book_ocr` 工作目录的子目录，首次运行启动脚本会尝试导入该工作目录中已有的配对摘录。

## 使用

1. 粘贴中文中的一句或一段，选择书籍、章节，点击“查找原文”（也支持 Ctrl+Enter）。
2. 点击结果，左侧定位中文，右侧定位原文。点击“展开阅读”扩大两个阅读窗；“改为上下”切换排列。
3. 两侧各自滚动查看本章上下文。点击另一段中文，右侧重新定位。
4. “段落原文已核对”会高亮对应原文；“按页定位”显示译稿页码对应的原文页，不能视为已经确认的逐段对应。原文可能跨页。
5. 展开“核对并保存这段对应关系”，在右侧阅读窗选取原文，使用选中内容并保存；也可粘贴原文并选择连续页。取消确认会恢复按页定位。

“文字近似”只表示部分字词相同，候选结果需要确认。目前不支持按大意进行语义搜索。

## 导入自己的书

第一版支持 UTF-8 的 Markdown 译稿和 TXT/Markdown 原文。两份文件需要有可靠页码；工具不会按段落数量猜测跨语言对应关系。扫描 PDF 需先提取或 OCR；EPUB 需先提取文本并建立位置记录，当前不直接导入。

原文格式（以下为合成示例）：

```text
--- PDF page 8; printed page 1 ---
Rain falls across the quiet garden.

--- PDF page 9; printed page 2 ---
The morning brings a clear sky.
```

译文格式：

```markdown
# 第一章

<!-- 原书第1页 -->

雨落在安静的花园里。

<!-- 原书第2页 -->

清晨带来了晴朗的天空。
```

在被 Git 忽略的 `local/` 中放入配对文件与 `book.json`：

```json
{
  "id": "my-book",
  "title": "我的书",
  "language": "英文",
  "chapters": [
    {
      "id": "chapter-1",
      "title": "第一章",
      "source": "original.txt",
      "translation": "translation.md",
      "page_headers": ["A BOOK"]
    }
  ]
}
```

路径相对于 JSON 文件。`page_headers` 可选，仅去掉每页前四行中与配置完全相同的页眉；原始摘录另行保留。原文页尾与页码相同的独立行也会从阅读副本移除。不会修复断词、改写原文或纠正 OCR。

```powershell
python -m source_finder import-book local/book.json
```

原文前言标注 `printed page front matter` 时，需要在章节配置提供 `front_matter_start`（如 17 对应 xvii）。其他页码按标签直接匹配。

导入现有配对摘录：

```powershell
python -m source_finder import-workspace --root ..
```

此适配器只处理 `work/on_flirtation/source` 和 `work/de_lintime/source` 的 manifest 与 `output/` 中对应的逐章译稿。只导入已有选译章节，不宣称覆盖全书；不修改原文件。

重新导入相同文件保留已确认关系；原文、译文或解析配置改变会清除该章旧确认，避免沿用过期映射。导入前先导出确认记录。一本书的全部文件验证通过才写入；配置中移除章节会从索引中移除该章。

## 本地数据与恢复

```powershell
python -m source_finder export-alignments data/backups/2026-10-21/alignments.json
python -m source_finder restore-alignments data/backups/2026-10-21/alignments.json
```

恢复需要先导入相同版本的原文、译文和解析配置，哈希不一致会拒绝恢复。仅有这个 JSON 不能恢复整本书，应另行保管原始文件与导入配置。

不要把个人书籍、配置、导出的对应关系、数据库或截图加入公开仓库。GitHub 仅恢复代码。备份与本地运行的操作见 [运行说明](docs/runbooks/local-library.md)。

## 开发与验证

```powershell
python -m unittest discover -s tests -v
node --check source_finder/static/app.js
```

Node 只用于开发时检查 JavaScript 语法，不是运行依赖。测试使用合成文本，涵盖页码核对、中文查询、跨段查询、连续阅读数据、跨页原文确认、过期确认清除和本地 HTTP 接口。

服务只绑定 `127.0.0.1`，限定 Host 和写请求来源，不提供外部资源加载、遥测或任意文件浏览。当前是个人本地工具，不适合直接改成公网服务。

项目现状见 [CURRENT_STATE.md](CURRENT_STATE.md)，后续计划见 [ROADMAP.md](ROADMAP.md)。
