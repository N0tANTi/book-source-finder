# 对照书库 / Book Source Finder

首页是本地书库。每本书放入一份原文和一份中文译文，选择书籍后搜索、阅读。支持 EPUB 原文 + EPUB 译文、PDF 原文 + EPUB 译文，以及 Markdown/TXT。双阅读窗支持独立滚动、候选定位和左右/上下排列。

书籍文件、文字、对应关系和向量索引保存在本机。原句查找不需要账号；可选的 Cloudflare Workers AI 用于语义索引和按意思查询，启用时相关文字会发送给 Cloudflare。公开仓库只保存工具代码、说明和合成测试数据。

## 启动

Python 3.10+。首次在本目录安装（`pypdf` 用于 PDF 文字提取）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

然后运行：

```powershell
.\.venv\Scripts\python.exe -m source_finder serve
```

打开 <http://127.0.0.1:8765>。Windows 也可双击 `start.cmd`。终端按 Ctrl+C 停止；占用端口时可用 `serve --port 8766`。

数据库默认为 `data/library.sqlite3`。如果是独立下载本工具，书库初始为空，需要先导入；如果工具位于现有 `book_ocr` 工作目录的子目录，首次运行启动脚本会尝试导入该工作目录中已有的配对摘录。

## 使用

1. 点击“添加书籍”，填写可选书名，分别选择或拖入原文与译文。每份文件最多 80 MB，解压 EPUB 总量最多 200 MB。两份文件都提取成功才加入书库；重复文件对会复用现有书籍。
2. 点击书籍打开双阅读窗，输入中文句子或词语进行本地文字查找。没有模型索引时，原文从起始位置展示，并明确标为“尚未匹配”。
3. 在“模型设置”中配置 Cloudflare，点击“测试连接”。回到书库，为新导入的书籍建立语义索引。操作前会说明发送哪些文字及额度消耗。
4. 索引完成后，点击中文片段即可从本地向量索引寻找原文候选；也可以选择“按意思查找”。原句匹配优先。模型候选始终标为待核对，可切换多个候选并人工确认。
5. 点击“展开阅读”扩大阅读窗，切换左右/上下排列。EPUB 按提取到的正文节展示；PDF 按最多 12 页的阅读范围保留 PDF 页号，不虚构原书章节或印刷页码。中文无搜索文字时选择章节可以跳转阅读位置。

导入在本机完成，不自动联网 OCR，也不绕过电子书加密。扫描 PDF 缺少文字时会提示先 OCR；混合扫描/文字 PDF 的图片页不在文本检索范围内。双栏 PDF 的提取顺序和原排版可能不同，引用前仍需核对原书。

已有的页码配对资料也保留在书库，继续使用旧的原文页/人工核对关系；它们不会自动变成新文件索引。需要模型检索时请通过“添加书籍”放入相应的原文、译文文件。

## Cloudflare 设置

- 注册或登录 Cloudflare，进入 Workers AI → Use REST API → Create a Workers AI API Token，复制 Account ID 和 Token。使用官方预填模板：[官方步骤](https://developers.cloudflare.com/workers-ai/get-started/rest-api/)。不需要给本工具注册域名或部署到 Cloudflare。
- 在本地“模型设置”中填写，Token 不需要发送到聊天或提交到仓库。Windows 使用当前用户 DPAPI 加密保存在忽略目录 `data/cloudflare.protected.json`；其他系统仅保存在服务会话内。页面和设置 API 不会返回 Token。也可设置 `CLOUDFLARE_ACCOUNT_ID`、`CLOUDFLARE_API_TOKEN` 环境变量。
- 当前模型为 `@cf/baai/bge-m3`，通过 Cloudflare 的 OpenAI 兼容 embeddings 接口调用。不生成或改写原文，只查找文件内的候选片段。
- 为一本书建索引会发送其提取的原文和译文；按意思查询会发送查询文字。完成的片段向量保存在本机，后续点击译文使用已有向量，不再联网。查询向量缓存最多 500 条，不保存查询原文。
- 一次仅处理一本书，分批写入，单轮最多处理 200 万字符；达到上限、额度受限或重启后可继续，不重算已保存的片段。模型向量跨语言相似度不等于准确翻译对应，确认前需检查上下文。
- 尚未提供真实凭据的安装仅能验证本地流程；“已配置”也不等于连接成功，应使用测试连接按钮验证账号权限与实际可用性。

“文字近似”只表示部分字词相同，候选结果需要确认。目前不支持按大意进行语义搜索。

## 导入自己的书

网页直接导入的 EPUB、PDF、Markdown、TXT 无需手动添加页码。下面是兼容旧资料的命令行页码配对格式，适合已有可靠页码标记的 UTF-8 文本。

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
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check source_finder/static/app.js
node --check source_finder/static/library.js
```

Node 只用于开发时检查 JavaScript 语法，不是运行依赖。请在安装依赖的虚拟环境运行测试。测试使用合成 EPUB/PDF 和模拟向量，涵盖文件上传、提取、中文查询、跨语言候选流程、凭据保护、重复导入、索引恢复和原有页码匹配。模拟模型通过不代表真实 Cloudflare 账号联调通过。

服务只绑定 `127.0.0.1`，限定 Host 和写请求来源，不提供外部资源加载、遥测或任意文件浏览。当前是个人本地工具，不适合直接改成公网服务。

项目现状见 [CURRENT_STATE.md](CURRENT_STATE.md)，后续计划见 [ROADMAP.md](ROADMAP.md)。
