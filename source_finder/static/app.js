'use strict';
const $ = (selector) => document.querySelector(selector);
const state = { library: null, results: [], current: null, searchVersion: 0, detailVersion: 0 };
let toastTimer;
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
async function api(path, body) {
  const response = await fetch(path, body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.library.csrf_token },
    body: JSON.stringify(body),
  } : undefined);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '操作失败，请重试。');
  return data;
}
function showError(error) { $('#error').textContent = error.message; $('#error').hidden = false; }
function toast(message) {
  $('#toast').textContent = message; $('#toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 3500);
}
function options(select, items, first) {
  const old = select.value;
  select.replaceChildren(new Option(first, ''), ...items.map(item => new Option(item.title, item.id)));
  if (items.some(item => item.id === old)) select.value = old;
}
function chapters() {
  const books = state.library.books.filter(b => !$('#book').value || b.id === $('#book').value);
  options($('#chapter'), books.flatMap(b => b.chapters), '全部章节');
}
async function loadLibrary() {
  state.library = await api('/api/library');
  const books = state.library.books;
  options($('#book'), books, '全部书籍'); chapters();
  const count = books.reduce((sum, b) => sum + b.paragraph_count, 0);
  const reviewed = books.reduce((sum, b) => sum + b.verified_count, 0);
  $('#library-status').textContent = books.length ? `${books.length} 本书 · ${count} 个译文片段 · ${reviewed} 处已核对` : '书库还没有书籍';
  renderShelf();
  if (activeBookId) {
    const active = books.find(b => b.id === activeBookId);
    $('#search-mode').options[1].disabled = !active?.index_ready;
  }
  $('#examples').replaceChildren();
  for (const example of state.library.examples) {
    const excerpt = example.text.slice(0, 48);
    const button = element('button', `${excerpt}${example.text.length > 48 ? '…' : ''}`, 'example');
    button.type = 'button';
    button.addEventListener('click', () => {
      $('#book').value = ''; chapters(); $('#chapter').value = '';
      $('#query').value = excerpt; $('#search-form').requestSubmit();
    });
    $('#examples').append(button);
  }
}
function highlight(text, query) {
  const node = element('p', undefined, 'passage');
  const q = query.trim();
  const offset = q ? text.indexOf(q) : -1;
  if (offset < 0) { node.textContent = text; return node; }
  node.append(document.createTextNode(text.slice(0, offset)), element('mark', text.slice(offset, offset + q.length)), document.createTextNode(text.slice(offset + q.length)));
  return node;
}
function displayResults() {
  const nav = $('#results'); nav.replaceChildren();
  for (const result of state.results) {
    const button = element('button', undefined, 'result');
    button.type = 'button'; button.dataset.id = result.id;
    button.append(element('div', result.book_title, 'book-name'), element('p', result.text.slice(0, 86) + (result.text.length > 86 ? '…' : ''), 'snippet'), element('div', result.kind === 'files' ? result.page_label : `第 ${result.page_label} 页 · ${result.verified ? '原文已核对' : '按页定位'}`, 'result-meta'));
    button.addEventListener('click', () => selectResult(result.id).catch(showError));
    nav.append(button);
  }
}
async function runSearch(event) {
  event?.preventDefault();
  const version = ++state.searchVersion;
  ++state.detailVersion;
  $('#error').hidden = true;
  $('#search-button').disabled = true; $('#search-button').textContent = '正在查找…';
  try {
    const params = new URLSearchParams({ q: $('#query').value, book: $('#book').value, chapter: $('#chapter').value });
    const data = $('#search-mode').value === 'semantic'
      ? await api('/api/semantic', { book_id: $('#book').value, chapter: $('#chapter').value, query: $('#query').value, consent: true })
      : await api(`/api/search?${params}`);
    if (version !== state.searchVersion) return;
    state.results = data.results;
    $('#empty').hidden = true; $('#results-section').hidden = false;
    const approximate = data.results[0]?.match === 'similar';
    $('#result-count').textContent = data.results.length ? `${data.results.length === 20 ? '最多显示 ' : ''}${data.results.length} 处${data.results[0]?.match === 'semantic' ? '语义候选，需核对' : approximate ? '文字近似，需确认' : '文字匹配'}` : '没有找到';
    displayResults();
    if (data.results.length) await selectResult(data.results[0].id);
    else $('#detail').replaceChildren(element('p', '没有找到这段译文。试试缩短到一句话、去掉注释，或选“全部书籍”。当前只搜索已导入的选译章节。', 'no-results'));
  } catch (error) { if (version === state.searchVersion) showError(error); }
  finally {
    if (version === state.searchVersion) { $('#search-button').disabled = false; $('#search-button').textContent = '查找原文 ↗'; }
  }
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast('已复制原文'); }
  catch { toast('浏览器未允许复制，可直接选中文字复制。'); }
}
function heading(text, action, callback) {
  const wrapper = element('div', undefined, 'column-heading');
  wrapper.append(element('h3', text));
  if (action) {
    const button = element('button', action, 'small-button');
    button.type = 'button'; button.addEventListener('click', callback); wrapper.append(button);
  }
  return wrapper;
}
async function selectResult(id) {
  const version = ++state.detailVersion;
  $('#detail').replaceChildren(element('p', '正在读取原文…', 'quiet'));
  const data = await api(`${id.startsWith('unit:') ? '/api/file-detail' : '/api/detail'}?${new URLSearchParams({ id })}`);
  if (version !== state.detailVersion) return;
  state.current = data;
  if (data.kind === 'files') { renderFileReader(data); return; }
  for (const button of document.querySelectorAll('.result')) {
    const active = button.dataset.id === id;
    button.classList.toggle('active', active); button.setAttribute('aria-current', active ? 'true' : 'false');
  }
  const panel = $('#detail'); panel.replaceChildren();
  const header = element('div', undefined, 'detail-header');
  header.append(element('span', data.book_title, 'quiet'), element('h2', data.chapter_title),
    element('span', data.alignment ? '段落原文已核对' : `按原书第 ${data.page_label} 页定位`, data.alignment ? 'badge' : 'badge page'));
  panel.append(header);
  const columns = element('div', undefined, 'columns');
  const chinese = element('section'); chinese.append(heading('中文译文 · 本章连续阅读'));
  chinese.append(element('p', '点击任一段中文，可定位右侧原文。两侧可以分别滚动阅读。', 'explanation'));
  const chineseReader = element('div', undefined, 'reader-window chinese-reader');
  chineseReader.setAttribute('aria-label', '中文连续阅读窗'); chineseReader.tabIndex = 0;
  for (const paragraph of data.reader_paragraphs) {
    const block = element('button', undefined, `reader-block${paragraph.id === id ? ' selected' : ''}`);
    block.type = 'button'; block.dataset.id = paragraph.id;
    block.setAttribute('aria-label', `定位这段原文：${paragraph.text.slice(0, 25)}`);
    if (paragraph.id === id) block.setAttribute('aria-current', 'true');
    block.append(element('span', `原书第 ${paragraph.page_label} 页`, 'page-label'), highlight(paragraph.text, $('#query').value));
    block.addEventListener('click', () => { if (paragraph.id !== state.current?.id) selectResult(paragraph.id).catch(showError); });
    chineseReader.append(block);
  }
  chinese.append(chineseReader);
  const source = element('section');
  const shownPages = data.alignment ? data.alignment.pages : data.reader_pages.filter(p => p.id === data.page_id);
  source.append(heading(data.language + '原文 · 本章连续阅读', data.alignment ? '复制对应原文' : '复制定位页', () => copyText(data.alignment?.quote || shownPages.map(p => p.text).join('\n\n'))));
  source.append(element('p', data.alignment ? '高亮显示已核对的原文片段，可以继续上下滚动查看上下文。' : '已跳到译稿页码对应的原文页。该段尚未逐段核对，句子可能延续到前后页。', 'explanation'));
  const pageContainer = element('div', undefined, 'reader-window original-reader');
  pageContainer.setAttribute('aria-label', '原文连续阅读窗'); pageContainer.tabIndex = 0;
  const joinedOriginal = data.reader_pages.map(p => p.text).join(' ');
  const quoteStart = data.alignment ? joinedOriginal.indexOf(data.alignment.quote) : -1;
  const quoteEnd = quoteStart + (data.alignment?.quote.length || 0);
  let pageOffset = 0;
  for (const page of data.reader_pages) {
    const start = quoteStart >= 0 ? Math.max(quoteStart - pageOffset, 0) : -1;
    const end = quoteStart >= 0 ? Math.min(quoteEnd - pageOffset, page.text.length) : -1;
    const activePage = data.alignment ? data.alignment.page_ids.includes(page.id) : page.id === data.page_id;
    pageContainer.append(sourcePage(page, activePage, start < end ? [start, end] : null));
    pageOffset += page.text.length + 1;
  }
  const raw = element('details', undefined, 'context'); raw.append(element('summary', '查看本页摘录的原始换行'));
  const currentPage = data.source_pages.find(p => p.id === data.page_id);
  raw.append(element('pre', currentPage.raw_text, 'raw-text'));
  source.append(pageContainer, raw);
  columns.append(chinese, source); panel.append(columns);
  const review = element('details', undefined, 'review');
  review.append(element('summary', data.alignment ? '修正 / 取消这段对应关系' : '核对并保存这段对应关系'));
  review.append(element('p', '在右侧阅读窗中选中对应英文或法文，点击“使用选中的原文”。确认它与左侧高亮的中文对应后保存。可以跨连续页选取。'));
  const selectionButton = element('button', '使用选中的原文', 'small-button'); selectionButton.type = 'button';
  const quote = element('textarea'); quote.id = 'alignment-quote'; quote.setAttribute('aria-label', '确认对应的原文'); quote.placeholder = '选中的原文会显示在这里，也可以从上面的原文页粘贴。';
  const selectedPageIds = new Set(data.alignment?.page_ids || [data.page_id]);
  const pageLabel = element('label', '原文所在页（跨页可多选）', 'selection-note');
  const pageSelect = element('select'); pageSelect.multiple = true; pageSelect.size = Math.min(4, data.source_pages.length);
  pageSelect.setAttribute('aria-label', '原文所在页');
  for (const page of data.reader_pages) { const option = new Option(`原书 ${page.label} 页 / PDF ${page.pdf_page} 页`, page.id); option.selected = selectedPageIds.has(page.id); pageSelect.append(option); }
  if (data.alignment) quote.value = data.alignment.quote;
  selectionButton.addEventListener('mousedown', event => event.preventDefault());
  selectionButton.addEventListener('click', () => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !pageContainer.contains(selection.anchorNode) || !pageContainer.contains(selection.focusNode)) {
      toast('请在右侧原文阅读窗中选取原文。'); return;
    }
    // Collect only source prose, excluding page labels between selected pages.
    const range = selection.getRangeAt(0);
    const pieces = [], ids = [];
    for (const p of pageContainer.querySelectorAll('.source-passage')) {
      if (!range.intersectsNode(p) || !p.firstChild) continue;
      const sub = document.createRange(); sub.selectNodeContents(p);
      if (p.contains(range.startContainer)) sub.setStart(range.startContainer, range.startOffset);
      if (p.contains(range.endContainer)) sub.setEnd(range.endContainer, range.endOffset);
      const piece = sub.toString().trim();
      if (piece) { pieces.push(piece); ids.push(p.dataset.pageId); }
    }
    quote.value = pieces.join(' ');
    for (const option of pageSelect.options) option.selected = ids.includes(option.value);
    toast('已放入选中的原文，请核对后保存。');
  });
  const actions = element('div', undefined, 'review-actions');
  const save = element('button', '确认对应并保存'); save.type = 'button';
  save.addEventListener('click', async () => {
    save.disabled = true; $('#error').hidden = true;
    try {
      await api('/api/align', { paragraph_id: id, page_ids: Array.from(pageSelect.selectedOptions, o => o.value), quote: quote.value });
      await selectResult(id); await loadLibrary(); toast('已保存这段对应关系');
      for (const r of state.results) if (r.id === id) r.verified = 1;
      displayResults(); document.querySelectorAll('.result').forEach(b => b.classList.toggle('active', b.dataset.id === id));
    } catch (error) { showError(error); }
    finally { save.disabled = false; }
  });
  actions.append(save);
  if (data.alignment) {
    const unconfirm = element('button', '取消确认', 'small-button'); unconfirm.type = 'button';
    unconfirm.addEventListener('click', async () => {
      try { await api('/api/unconfirm', { paragraph_id: id }); await selectResult(id); await loadLibrary();
        for (const r of state.results) if (r.id === id) r.verified = 0;
        displayResults(); document.querySelectorAll('.result').forEach(b => b.classList.toggle('active', b.dataset.id === id)); toast('已恢复为按页定位');
      } catch (error) { showError(error); }
    }); actions.append(unconfirm);
  }
  pageLabel.append(pageSelect); review.append(selectionButton, pageLabel, quote, actions); panel.append(review);
  positionReaders();
}
function positionReaders() {
  const chineseReader = document.querySelector('.chinese-reader');
  const pageContainer = document.querySelector('.original-reader');
  if (!chineseReader || !pageContainer) return;
  const chineseTarget = chineseReader.querySelector('.selected');
  if (chineseTarget) chineseReader.scrollTop = Math.max(0, chineseTarget.offsetTop - 24);
  const originalTarget = pageContainer.querySelector('mark') || pageContainer.querySelector('.current');
  if (originalTarget) {
    pageContainer.scrollTop = Math.max(0, originalTarget.getBoundingClientRect().top - pageContainer.getBoundingClientRect().top + pageContainer.scrollTop - 28);
  }
}
function sourcePage(page, current, selected) {
  const wrapper = element('div', undefined, `source-page${current ? ' current' : ''}`);
  wrapper.append(element('span', `原书 ${page.label} 页 · PDF ${page.pdf_page} 页`, 'page-label'));
  const passage = element('p', undefined, 'passage source-passage'); passage.dataset.pageId = page.id;
  if (selected) passage.append(document.createTextNode(page.text.slice(0, selected[0])), element('mark', page.text.slice(selected[0], selected[1])), document.createTextNode(page.text.slice(selected[1])));
  else passage.textContent = page.text;
  wrapper.append(passage); return wrapper;
}
$('#book').addEventListener('change', () => { chapters(); activeBookId = $('#book').value; });
$('#reader-layout').addEventListener('click', () => {
  const stacked = document.body.classList.toggle('stacked-readers');
  $('#reader-layout').textContent = stacked ? '改为左右' : '改为上下';
  $('#reader-layout').setAttribute('aria-pressed', String(stacked));
  positionReaders();
});
$('#expand-reader').addEventListener('click', () => {
  const expanded = document.body.classList.toggle('reading-mode');
  $('#expand-reader').textContent = expanded ? '返回查询' : '展开阅读';
  $('#expand-reader').setAttribute('aria-expanded', String(expanded));
  positionReaders();
  window.scrollTo({ top: 0, behavior: 'instant' });
});
$('#search-form').addEventListener('submit', runSearch);
$('#query').addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') $('#search-form').requestSubmit(); });
loadLibrary().catch(showError);
