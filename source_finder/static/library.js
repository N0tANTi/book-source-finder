'use strict';
let activeBookId = '';
let indexBookId = '';
let shelfPoll = null;

function showShelf() {
  ++state.searchVersion; ++state.detailVersion;
  document.body.classList.remove('reading-mode', 'book-open');
  $('#expand-reader').textContent = '专注阅读';
  $('#shelf').hidden = false;
  $('.search-section').hidden = true;
  $('#results-section').hidden = true;
  $('#empty').hidden = true;
  $('#error').hidden = true;
  activeBookId = '';
  loadLibrary().catch(showError);
}

function renderShelf() {
  const books = state.library.books;
  const filter = $('#shelf-filter').value.trim().toLocaleLowerCase();
  const grid = $('#book-grid'); grid.replaceChildren();
  $('#shelf-empty').hidden = books.length > 0;
  const configured = state.library.model?.configured;
  const banner = $('#model-banner'); banner.replaceChildren();
  banner.append(element('span', configured ? '模型已配置 · 可为新导入的书籍建立语义索引' : '原文和译文已就位后，可连接模型建立语义索引'));
  const settings = element('button', configured ? '查看模型设置' : '连接 Cloudflare', 'small-button');
  settings.type = 'button'; settings.addEventListener('click', openSettings); banner.append(settings);
  for (const [i, book] of books.entries()) {
    if (filter && !book.title.toLocaleLowerCase().includes(filter)) continue;
    const card = element('article', undefined, `book-card book-color-${i % 4}`);
    const cover = element('button', undefined, 'book-cover'); cover.type = 'button';
    cover.setAttribute('aria-label', `打开 ${book.title}`);
    cover.append(element('span', book.language + ' / 中文', 'cover-language'), element('strong', book.title, 'cover-title'), element('span', book.kind === 'files' ? '原文 · 译文' : '已有页码配对', 'cover-bottom'));
    cover.addEventListener('click', () => openBook(book).catch(showError));
    const content = element('div', undefined, 'book-info'); content.append(element('h2', book.title));
    if (book.kind === 'files') {
      for (const role of ['source', 'translation']) {
        const file = book.files.find(f => f.role === role);
        content.append(element('p', `${role === 'source' ? '原文' : '译文'} · ${file ? file.name : '尚未添加'}`, 'book-file'));
      }
      const status = book.index_ready ? '语义索引已就绪' : book.job?.status === 'running'
        ? `正在建立索引 · ${book.job.done} / ${book.job.total}`
        : book.job?.status === 'paused' ? `索引已暂停 · ${book.indexed_units} / ${book.total_units}` : '文字已提取 · 等待语义索引';
      content.append(element('p', status, 'book-status'));
      if (book.job?.status === 'paused') content.append(element('p', book.job.error, 'quiet'));
    } else content.append(element('p', `${book.chapters.length} 章 · ${book.paragraph_count} 段中文 · ${book.verified_count} 处已核对`, 'book-status'));
    const actions = element('div', undefined, 'book-actions');
    const open = element('button', '打开阅读', 'small-button'); open.type = 'button'; open.addEventListener('click', () => openBook(book).catch(showError)); actions.append(open);
    if (book.kind === 'files' && !book.index_ready) {
      const index = element('button', book.job?.status === 'running' ? '正在处理…' : book.indexed_units ? '继续建索引' : '建立语义索引', 'small-button');
      index.type = 'button'; index.disabled = book.job?.status === 'running';
      index.addEventListener('click', () => openIndex(book)); actions.append(index);
    }
    content.append(actions); card.append(cover, content); grid.append(card);
  }
  if (books.length && !grid.children.length) grid.append(element('p', '没有找到这个书名。', 'quiet'));
  const running = books.some(b => b.job?.status === 'running');
  clearTimeout(shelfPoll);
  if (running) shelfPoll = setTimeout(() => loadLibrary().catch(showError), 2500);
}

async function openBook(book) {
  ++state.searchVersion;
  const opening = ++state.detailVersion;
  activeBookId = book.id;
  $('#shelf').hidden = true; $('.search-section').hidden = false; $('#empty').hidden = true;
  document.body.classList.remove('reading-mode');
  document.body.classList.add('book-open');
  $('#expand-reader').textContent = '专注阅读';
  $('#search-title').textContent = book.title;
  $('#active-book-note').textContent = book.kind === 'files'
    ? book.index_ready ? '智能搜索 · 语义查询使用 Cloudflare' : '尚未建立语义索引 · 可查找译文和分别阅读'
    : '已保存页码对应关系';
  $('#book').value = book.id; chapters(); $('#chapter').value = '';
  $('#query').value = ''; $('#search-mode').value = 'auto';
  updateSearchMode(book);
  $('#results-section').hidden = false; $('#error').hidden = true;
  $('#results-title').textContent = '对照阅读'; $('#result-count').textContent = '';
  state.results = []; displayResults();
  $('#search-button').disabled = false; $('#search-button').textContent = '搜索';
  $('#reader-options').open = false;
  const data = await api(`/api/open-book?${new URLSearchParams({ book: book.id })}`);
  if (opening !== state.detailVersion || activeBookId !== book.id) return;
  await selectResult(data.id);
}

function updateSearchMode(book) {
  $('#search-mode').querySelector('option[value="semantic"]').disabled = !book?.index_ready;
  if (!book?.index_ready && $('#search-mode').value === 'semantic') $('#search-mode').value = 'auto';
  $('#query-disclosure').hidden = $('#search-mode').value === 'text' || !book?.index_ready;
  $('#query').placeholder = book?.index_ready ? '搜一句话、一个词，或描述大意' : '搜索中文原句或词语';
}

async function openSettings() {
  const settings = await api('/api/settings');
  $('#account-id').value = settings.account_id || ''; $('#api-token').value = '';
  $('#settings-status').textContent = settings.configured ? '已有配置；测试连接后可以建立书籍索引。' : '尚未配置模型。';
  $('#credential-storage').textContent = settings.storage === 'environment' ? '当前使用本机环境变量中的凭据。' : navigator.platform.includes('Win') ? 'Token 使用 Windows 当前用户凭据加密保存在本机；不会返回给页面。' : 'Token 仅在本次服务运行期间保留；重启后需重新填写。';
  $('#settings-error').hidden = true; $('#settings-dialog').showModal();
}

function openIndex(book) {
  if (!state.library.model?.configured) { openSettings().catch(showError); return; }
  indexBookId = book.id;
  $('#index-book-name').textContent = `${book.title} · ${book.total_units} 个文字片段，已完成 ${book.indexed_units} 个。`;
  $('#index-error').hidden = true; $('#index-dialog').showModal();
}

function dialogError(id, error) { $(id).textContent = error.message; $(id).hidden = false; }

async function selectSource(id, source) {
  const version = ++state.detailVersion;
  const data = await api(`/api/file-detail?${new URLSearchParams({ id, source })}`);
  if (version === state.detailVersion) renderFileReader(data);
}

function renderFileReader(data) {
  state.current = data;
  const id = data.id;
  for (const button of document.querySelectorAll('.result')) button.classList.toggle('active', button.dataset.id === id);
  const panel = $('#detail'); panel.replaceChildren();
  const header = element('div', undefined, 'detail-header');
  header.append(element('span', data.book_title, 'quiet'), element('h2', data.translation_location),
    element('span', data.verified ? '对应已人工确认' : data.candidate ? '原文候选 · 待核对' : '双文本阅读 · 尚未匹配', data.verified ? 'badge' : 'badge page'));
  panel.append(header);
  header.hidden = true;
  let candidateLabel = null;
  if (data.candidates.length) {
    const label = element('label', '原文候选', 'candidate-label');
    const choices = element('select'); choices.setAttribute('aria-label', '选择原文候选');
    for (const candidate of data.candidates) choices.append(new Option(`${candidate.location} · ${candidate.text.slice(0, 48)}…`, candidate.id));
    if (!data.candidates.some(c => c.id === data.source_id)) choices.append(new Option(data.source_location + (data.verified ? ' · 已确认' : ' · 手动位置'), data.source_id));
    choices.value = data.source_id;
    choices.addEventListener('change', async () => {
      try { await selectSource(id, choices.value); }
      catch (error) { showError(error); }
    }); label.append(choices); candidateLabel = label;
  }
  const columns = element('div', undefined, 'columns');
  const chinese = element('section'); chinese.append(heading('中文译文'), element('p', data.candidate ? '点击中文片段，在右侧查看原文候选。两侧均可独立滚动。' : '可查找、点击中文片段，并上下滚动查看上下文。两侧尚未自动对齐。', 'explanation'));
  const book = state.library.books.find(b => b.id === data.book_id);
  const translationSection = element('select'); translationSection.setAttribute('aria-label', '阅读章节');
  for (const chapter of book.chapters) {
    const option = new Option(chapter.title, chapter.id); option.selected = chapter.id === data.section; translationSection.append(option);
  }
  translationSection.addEventListener('change', async () => {
    try {
      $('#query').value = ''; $('#chapter').value = '';
      state.results = []; displayResults();
      const first = await api(`/api/open-book?${new URLSearchParams({ book: data.book_id, chapter: translationSection.value })}`);
      await selectResult(first.id);
    } catch (error) { showError(error); }
  });
  const chapterNavigation = element('label', undefined, 'translation-location');
  chapterNavigation.append(translationSection); chinese.append(chapterNavigation);
  const translated = element('div', undefined, 'reader-window chinese-reader'); translated.tabIndex = 0; translated.setAttribute('aria-label', '中文连续阅读窗');
  for (const [position, unit] of data.translation_units.entries()) {
    // Section titles already appear in navigation; retain all raw units in SQLite.
    if (unit.text.trim() === data.translation_location.trim()) continue;
    if (position === 0 && /^[\w.-]+\.xhtml$/i.test(unit.text.trim())) continue;
    const block = element('button', undefined, `reader-block${unit.id === id ? ' selected' : ''}`); block.type = 'button';
    block.append(element('span', unit.location, 'page-label'), highlight(unit.text, $('#query').value));
    block.addEventListener('click', () => { if (unit.id !== state.current.id) selectResult(unit.id).catch(showError); }); translated.append(block);
  }
  chinese.append(translated);
  const original = element('section');
  const selectedSource = data.source_units.find(u => u.id === data.source_id);
  original.append(heading(data.language === '原文' ? '原文' : `${data.language}原文`),
    element('p', data.verified ? '当前对应关系已由你确认。' : data.candidate ? '高亮为模型检索的候选或你选择的片段，需结合上下文核对。' : '原文与译文已提取。尚未建立索引，当前原文位置不代表对应关系。', 'explanation'));
  const paneState = element('span', data.verified ? '已核对' : data.candidate ? '模型候选' : '尚未匹配', 'pane-state');
  paneState.title = data.verified ? '对应关系已由你确认' : data.candidate ? '模型检索结果，需要结合上下文核对' : '当前原文位置不代表对应关系';
  original.querySelector('.column-heading').append(paneState);
  const sourceLocation = element('label', '原文位置', 'source-location-label');
  const sourceSections = element('select'); sourceSections.setAttribute('aria-label', '选择原文位置');
  for (const section of data.source_sections) {
    const option = new Option(section.section.replace(/^\d+:/, ''), section.id);
    option.selected = section.section === data.source_section; sourceSections.append(option);
  }
  sourceSections.addEventListener('change', async () => {
    try {
      await selectSource(id, sourceSections.value);
    } catch (error) { showError(error); }
  });
  sourceLocation.append(sourceSections);
  if (candidateLabel) original.append(candidateLabel);
  else original.append(sourceLocation);
  const source = element('div', undefined, 'reader-window original-reader'); source.tabIndex = 0; source.setAttribute('aria-label', '原文连续阅读窗');
  for (const unit of data.source_units) {
    const block = element('div', undefined, `source-page${unit.id === data.source_id ? ' current' : ''}`);
    const p = element('p', undefined, 'passage source-passage');
    if (unit.id === data.source_id && data.candidate) p.append(element('mark', unit.text)); else p.textContent = unit.text;
    block.append(element('span', unit.location, 'page-label'), p); source.append(block);
  }
  original.append(source); columns.append(chinese, original); panel.append(columns);
  const browsing = element('details', undefined, 'source-browse'); browsing.append(element('summary', '更多'));
  const browsingPanel = element('div', undefined, 'source-browse-panel');
  if (candidateLabel) browsingPanel.append(sourceLocation);
  const copy = element('button', '复制当前原文', 'small-button'); copy.type = 'button';
  copy.addEventListener('click', () => copyText(selectedSource.text)); browsingPanel.append(copy);
  browsing.append(browsingPanel); original.querySelector('.column-heading').append(browsing);
  if (data.candidate) {
    const actions = element('div', undefined, 'file-review-actions');
    const confirm = element('button', data.verified ? '取消人工确认' : '确认这两个片段对应', 'small-button'); confirm.type = 'button';
    confirm.addEventListener('click', async () => {
      try { await api('/api/confirm-file', { translation_id: id, source_id: data.source_id, cancel: data.verified });
        await selectResult(id); await loadLibrary(); toast(data.verified ? '已取消确认' : '对应关系已保存');
      } catch (error) { showError(error); }
    }); actions.append(confirm); panel.append(actions);
  }
  positionReaders();
}

document.addEventListener('DOMContentLoaded', () => {
  $('#home-button').addEventListener('click', showShelf);
  $('#back-to-shelf').addEventListener('click', showShelf);
  $('#settings-button').addEventListener('click', () => openSettings().catch(showError));
  for (const button of document.querySelectorAll('.close-dialog')) button.addEventListener('click', () => button.closest('dialog').close());
  for (const id of ['#add-book-button', '#first-book-button']) $(id).addEventListener('click', () => {
    $('#import-error').hidden = true; $('#import-status').textContent = ''; $('#import-dialog').showModal();
  });
  $('#shelf-filter').addEventListener('input', renderShelf);
  $('#search-mode').addEventListener('change', () => updateSearchMode(state.library.books.find(b => b.id === activeBookId)));
  $('#chapter').addEventListener('change', async () => {
    if (!activeBookId || $('#query').value.trim()) return;
    try {
      const data = await api(`/api/open-book?${new URLSearchParams({book:activeBookId,chapter:$('#chapter').value})}`);
      await selectResult(data.id);
    } catch (error) { showError(error); }
  });
  for (const role of ['source', 'translation']) {
    const input = $(`#${role}-file`), drop = $(`#${role}-drop`);
    const update = () => { $(`#${role}-filename`).textContent = input.files[0]?.name || '点击选择，或把文件拖到这里'; };
    input.addEventListener('change', update);
    drop.addEventListener('dragover', event => { event.preventDefault(); drop.classList.add('dragging'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('dragging'));
    drop.addEventListener('drop', event => {
      event.preventDefault(); drop.classList.remove('dragging');
      if (event.dataTransfer.files.length !== 1) { toast('每个位置放入一份文件即可。'); return; }
      input.files = event.dataTransfer.files; update();
    });
  }
  $('#import-form').addEventListener('submit', async event => {
    event.preventDefault(); $('#import-error').hidden = true;
    const source = $('#source-file').files[0], translation = $('#translation-file').files[0];
    if (!source || !translation) return;
    if (source.size > 80 * 1024 * 1024 || translation.size > 80 * 1024 * 1024) { dialogError('#import-error', new Error('每份文件最多 80 MB。')); return; }
    $('#import-submit').disabled = true; $('#import-status').textContent = '正在本机提取文字和章节，请稍候…';
    try {
      const form = new FormData($('#import-form'));
      const response = await fetch('/api/import', { method: 'POST', headers: { 'X-CSRF-Token': state.library.csrf_token }, body: form });
      const result = await response.json(); if (!response.ok) throw new Error(result.error || '导入失败。');
      await loadLibrary(); $('#import-dialog').close(); $('#import-form').reset();
      $('#source-filename').textContent = $('#translation-filename').textContent = '点击选择，或把文件拖到这里';
      toast('已加入书库，接下来可建立语义索引。');
      showShelf();
    } catch (error) { dialogError('#import-error', error); $('#import-status').textContent = ''; }
    finally { $('#import-submit').disabled = false; }
  });
  $('#settings-form').addEventListener('submit', async event => {
    event.preventDefault(); $('#settings-error').hidden = true; $('#settings-save').disabled = true;
    try {
      await api('/api/settings', { account_id: $('#account-id').value.trim(), token: $('#api-token').value });
      $('#api-token').value = ''; $('#settings-status').textContent = '已保存。可以点击“测试连接”检查模型。'; await loadLibrary();
    } catch (error) { dialogError('#settings-error', error); }
    finally { $('#settings-save').disabled = false; }
  });
  $('#test-model').addEventListener('click', async () => {
    $('#settings-error').hidden = true; $('#test-model').disabled = true; $('#settings-status').textContent = '正在测试连接（仅发送测试文字）…';
    try { const data = await api('/api/model-test', {}); $('#settings-status').textContent = data.message; }
    catch (error) { dialogError('#settings-error', error); $('#settings-status').textContent = ''; }
    finally { $('#test-model').disabled = false; }
  });
  $('#index-confirm').addEventListener('click', async () => {
    $('#index-error').hidden = true; $('#index-confirm').disabled = true;
    try { await api('/api/index', { book_id: indexBookId, consent: true }); $('#index-dialog').close(); await loadLibrary(); toast('已开始建立语义索引，可在书库查看进度。'); }
    catch (error) { dialogError('#index-error', error); }
    finally { $('#index-confirm').disabled = false; }
  });
});
