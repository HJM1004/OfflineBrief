#!/usr/bin/env python3
"""content/ 内の直近日付フォルダのMarkdownからオフラインPWAサイトを public/ に生成する。

依存パッケージなし(Python標準ライブラリのみ)。

コンテンツ形式(content/YYYY-MM-DD/*.md):

    ---
    genre: 総合・国際
    slug: general
    order: 1
    ---

    > このジャンルの今日の概況(複数行可)

    ## 記事の見出し
    - source: NHK
    - url: https://example.com/article
    - date: 2026-07-05

    要約や本文(Markdown)。

    **解説**
    解説本文...

slug が essays のファイルは「知的探究」タブになり、各セクションがエッセイとして表示される。

サイトには content/ 内の全日付フォルダ(MAX_DAYS_IN_BUILDで上限を設けた場合はその範囲)が
同梱され、ヘッダーの日付セレクタで切り替えて閲覧できる。
"""
import html
import json
import re
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
CONTENT = ROOT / "content"

# サイトに直接組み込む過去日数の上限。None なら content/ 内の全日付を含める(既定)。
# ページサイズ・読み込み時間が気になってきたら整数(例: 30)に変更して直近N日分に絞れる。
# その場合、上限を超える古い日付はビューアーの「mdファイルを読み込む」機能で個別に読み込める。
MAX_DAYS_IN_BUILD = None


def esc(s):
    return html.escape(str(s or ""))


def md_to_html(text: str) -> str:
    """最小限のMarkdown変換(見出し・強調・箇条書き・リンク・段落)。"""
    out, in_list = [], False

    def inline(s):
        s = esc(s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
        return s

    for raw in (text or "").split("\n"):
        stripped = raw.strip()
        if stripped.startswith(("- ", "・")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(stripped.lstrip('-・ '))}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if stripped.startswith("### "):
            out.append(f"<h4>{inline(stripped[4:])}</h4>")
        elif stripped.startswith("## "):
            out.append(f"<h3>{inline(stripped[3:])}</h3>")
        elif stripped.startswith("# "):
            out.append(f"<h3>{inline(stripped[2:])}</h3>")
        elif stripped:
            out.append(f"<p>{inline(stripped)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def parse_front_matter(text: str):
    meta, body = {}, text
    m = re.match(r"\s*---\s*\n([\s\S]*?)\n---\s*\n", text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = text[m.end():]
    return meta, body


BLOCK_START = re.compile(r"^---[ \t]*\r?\n(?=genre\s*:)", re.MULTILINE)


def split_genre_blocks(text: str):
    """1ファイルに複数ジャンルのfrontmatterブロックが連結されていても分割する。
    各ブロックは行頭の `---` の直後に `genre:` が続く箇所を開始点とみなす。
    見つからなければファイル全体を1ブロックとして扱う(後方互換)。"""
    starts = [m.start() for m in BLOCK_START.finditer(text)]
    if not starts:
        return [text]
    starts.append(len(text))
    return [text[starts[i]:starts[i + 1]] for i in range(len(starts) - 1)]


def parse_block(text: str, fallback_name: str):
    """1ジャンル分のブロック(frontmatter+本文)を解析する。概況(blockquote)と
    「## 」区切りのセクションに分解する。"""
    meta, body = parse_front_matter(text)

    overview_lines = []
    rest_lines = []
    seen_section = False
    for line in body.split("\n"):
        if line.startswith("## "):
            seen_section = True
        if not seen_section and line.strip().startswith(">"):
            overview_lines.append(line.strip().lstrip("> ").strip())
        else:
            rest_lines.append(line)

    sections = []
    current = None
    for line in rest_lines:
        if line.startswith("## "):
            current = {"title": line[3:].strip(), "meta": {}, "body_lines": [], "in_head": True}
            sections.append(current)
            continue
        if current is None:
            continue
        s = line.strip()
        mm = re.match(r"-\s*(source|url|date|from)\s*:\s*(.+)", s)
        if current["in_head"] and (mm or not s):
            if mm:
                current["meta"][mm.group(1)] = mm.group(2).strip()
            continue
        current["in_head"] = False
        current["body_lines"].append(line)

    return {
        "genre": meta.get("genre", fallback_name),
        "slug": meta.get("slug", re.sub(r"\W+", "", fallback_name) or "sec"),
        "order": int(meta.get("order", 99)),
        "overview": " ".join(l for l in overview_lines if l),
        "sections": [{"title": s["title"], "meta": s["meta"],
                      "body": "\n".join(s["body_lines"]).strip()} for s in sections],
    }


def parse_file(path: Path):
    """1ファイルに複数ジャンルが連結されていてもよい。ジャンルごとの辞書のリストを返す。"""
    text = path.read_text(encoding="utf-8")
    blocks = split_genre_blocks(text)
    return [parse_block(b, f"{path.stem}_{i}" if i else path.stem)
            for i, b in enumerate(blocks)]


def day_option_label(day: str) -> str:
    y, m, d = day.split("-")
    return f"{y}年{int(m)}月{int(d)}日"


CSS = """
:root{--bg:#faf8f4;--card:#ffffff;--ink:#1e2430;--sub:#5c6470;--accent:#0f4c81;--accent2:#b3541e;--line:#e5e0d8;--tag:#eef3f8}
@media(prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d2129;--ink:#e8e6e1;--sub:#9aa2ad;--accent:#7fb3e0;--accent2:#e0956a;--line:#2c313a;--tag:#242b35}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Hiragino Sans","Yu Gothic",'Noto Sans JP',sans-serif;line-height:1.9;-webkit-text-size-adjust:100%}
header{background:var(--accent);color:#fff;padding:20px 16px 14px}
header h1{margin:0;font-size:1.25rem;letter-spacing:.06em}
header .date{font-size:.8rem;opacity:.85;margin-top:2px}
nav{position:sticky;top:0;background:var(--card);border-bottom:1px solid var(--line);display:flex;overflow-x:auto;z-index:10}
nav a{flex:0 0 auto;padding:11px 14px;text-decoration:none;color:var(--sub);font-size:.85rem;font-weight:600;border-bottom:3px solid transparent;white-space:nowrap}
nav a.active{color:var(--accent);border-bottom-color:var(--accent)}
main{max-width:720px;margin:0 auto;padding:16px}
section{display:none}section.active{display:block}
.overview{background:var(--tag);border-left:4px solid var(--accent);padding:12px 14px;border-radius:0 8px 8px 0;font-size:.92rem;margin:14px 0 20px}
article{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 18px 14px;margin-bottom:16px}
article h2{font-size:1.05rem;margin:0 0 8px;line-height:1.6}
article h3{font-size:.95rem;color:var(--accent2);margin:16px 0 4px}
article p,article ul{font-size:.92rem;margin:8px 0}
.meta{font-size:.75rem;color:var(--sub);margin-bottom:10px}
.srclink{font-size:.75rem;color:var(--sub);word-break:break-all;border-top:1px dashed var(--line);margin-top:12px;padding-top:8px}
.essay{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px 20px;margin-bottom:20px}
.essay h2{font-size:1.15rem;color:var(--accent);margin:0 0 4px}
.essay .from{font-size:.78rem;color:var(--sub);margin-bottom:14px}
.essay h3{font-size:1rem;color:var(--accent2);margin:22px 0 6px}
.essay p{font-size:.95rem}
.essay .label{display:inline-block;font-size:.7rem;font-weight:700;color:var(--accent2);letter-spacing:.1em;margin-bottom:6px}
footer{text-align:center;color:var(--sub);font-size:.75rem;padding:24px 16px 40px}
.offline-badge{display:none;background:var(--accent2);color:#fff;text-align:center;font-size:.75rem;padding:4px}
body.offline .offline-badge{display:block}
header{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}
header .headtext{flex:1 1 auto;min-width:0}
.day-select{flex:0 0 auto;background:rgba(255,255,255,.15);color:#fff;border:1px solid rgba(255,255,255,.5);border-radius:8px;padding:8px 10px;font-size:.78rem;font-weight:600}
.day-select option{color:#1e2430}
.load-btn{flex:0 0 auto;background:rgba(255,255,255,.15);color:#fff;border:1px solid rgba(255,255,255,.5);border-radius:8px;padding:8px 12px;font-size:.78rem;font-weight:600;cursor:pointer;white-space:nowrap}
.load-btn:active{background:rgba(255,255,255,.3)}
.loaded-tag{display:inline-block;font-size:.7rem;color:var(--accent2);border:1px solid var(--accent2);border-radius:4px;padding:1px 6px;margin-left:8px;vertical-align:middle}
"""

JS = r"""
function show(slug){
  document.querySelectorAll('section').forEach(s=>s.classList.toggle('active',s.id===slug));
  document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',a.dataset.slug===slug));
  try{localStorage.setItem('tab',slug)}catch(e){}
  window.scrollTo(0,0);
}
function bindNav(){
  document.querySelectorAll('nav a').forEach(a=>{
    a.onclick = (e)=>{e.preventDefault();show(a.dataset.slug)};
  });
}
function showDay(day, preferredSlug){
  if(!day) return;
  document.querySelectorAll('nav a').forEach(a=>{
    a.style.display = (a.dataset.day===day) ? '' : 'none';
  });
  try{localStorage.setItem('activeDay',day)}catch(e){}
  const sel = document.getElementById('daySelect');
  if(sel && sel.value!==day) sel.value = day;
  let slug = preferredSlug;
  const candidate = slug && document.querySelector('nav a[data-slug="'+slug+'"][data-day="'+day+'"]');
  if(!candidate){
    const first = document.querySelector('nav a[data-day="'+day+'"]');
    slug = first ? first.dataset.slug : null;
  }
  if(slug) show(slug);
}
function bindDaySelect(){
  const sel = document.getElementById('daySelect');
  if(sel) sel.addEventListener('change', ()=>showDay(sel.value));
}
bindNav();
bindDaySelect();
let initDay='';try{initDay=localStorage.getItem('activeDay')||''}catch(e){}
if(!document.querySelector('nav a[data-day="'+initDay+'"]')){
  const firstOpt = document.querySelector('#daySelect option');
  initDay = firstOpt ? firstOpt.value : '';
}
let initTab='';try{initTab=localStorage.getItem('tab')||''}catch(e){}
showDay(initDay, initTab);
function updateNet(){document.body.classList.toggle('offline',!navigator.onLine)}
window.addEventListener('online',updateNet);window.addEventListener('offline',updateNet);updateNet();
if('serviceWorker' in navigator){navigator.serviceWorker.register('./sw.js')}

function esc(s){
  return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function inline(s){
  s = esc(s);
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2">$1</a>');
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
  return s;
}
function mdToHtml(text){
  const out = []; let inList = false;
  const lines = (text||'').split('\n');
  for(const raw of lines){
    const stripped = raw.trim();
    if(stripped.startsWith('- ') || stripped.startsWith('・')){
      if(!inList){ out.push('<ul>'); inList = true; }
      out.push('<li>'+inline(stripped.replace(/^[-・]\s*/,''))+'</li>');
      continue;
    }
    if(inList){ out.push('</ul>'); inList = false; }
    if(stripped.startsWith('### ')) out.push('<h4>'+inline(stripped.slice(4))+'</h4>');
    else if(stripped.startsWith('## ')) out.push('<h3>'+inline(stripped.slice(3))+'</h3>');
    else if(stripped.startsWith('# ')) out.push('<h3>'+inline(stripped.slice(2))+'</h3>');
    else if(stripped) out.push('<p>'+inline(stripped)+'</p>');
  }
  if(inList) out.push('</ul>');
  return out.join('\n');
}
function parseFrontMatter(text){
  const meta = {};
  const m = text.match(/^\s*---\s*\n([\s\S]*?)\n---\s*\n/);
  let body = text;
  if(m){
    for(const line of m[1].split('\n')){
      const idx = line.indexOf(':');
      if(idx>=0){ meta[line.slice(0,idx).trim()] = line.slice(idx+1).trim(); }
    }
    body = text.slice(m[0].length);
  }
  return {meta, body};
}
function parseMdText(text, fallbackName){
  const fm = parseFrontMatter(text);
  const meta = fm.meta, body = fm.body;
  const overviewLines = []; const restLines = [];
  let seenSection = false;
  for(const line of body.split('\n')){
    if(line.startsWith('## ')) seenSection = true;
    if(!seenSection && line.trim().startsWith('>')) overviewLines.push(line.trim().replace(/^>\s*/,''));
    else restLines.push(line);
  }
  const sections = [];
  let current = null;
  for(const line of restLines){
    if(line.startsWith('## ')){
      current = {title: line.slice(3).trim(), meta:{}, bodyLines: [], inHead:true};
      sections.push(current);
      continue;
    }
    if(!current) continue;
    const s = line.trim();
    const mm = s.match(/^-\s*(source|url|date|from)\s*:\s*(.+)$/);
    if(current.inHead && (mm || !s)){
      if(mm) current.meta[mm[1]] = mm[2].trim();
      continue;
    }
    current.inHead = false;
    current.bodyLines.push(line);
  }
  return {
    genre: meta.genre || fallbackName,
    slug: meta.slug || (fallbackName||'sec').replace(/\W+/g,'') || 'sec',
    order: parseInt(meta.order || '50', 10),
    overview: overviewLines.filter(Boolean).join(' '),
    sections: sections.map(s=>({title:s.title, meta:s.meta, body:s.bodyLines.join('\n').trim()}))
  };
}
function genreSectionHtml(g){
  const cards = g.sections.map(s=>{
    const metaBits = [s.meta.source||'', s.meta.date||''].filter(Boolean);
    const metaLine = metaBits.join(' / ');
    const url = s.meta.url||'';
    const srclink = url ? '<div class="srclink">出典: <a href="'+esc(url)+'">'+esc(url)+'</a>(オンライン時のみ)</div>' : '';
    return '<article><h2>'+esc(s.title)+'</h2><div class="meta">'+esc(metaLine)+'</div>'+mdToHtml(s.body)+srclink+'</article>';
  }).join('');
  const ov = g.overview ? '<div class="overview"><strong>今日の概況</strong><br>'+esc(g.overview)+'</div>' : '';
  return '<section id="'+esc(g.slug)+'">'+ov+cards+'</section>';
}
function essaysSectionHtml(g){
  const blocks = g.sections.map(s=>{
    const frm = s.meta.from||'';
    const frmHtml = frm ? '<div class="from">きっかけ: '+esc(frm)+'</div>' : '';
    return '<div class="essay"><span class="label">知的探究</span><h2>'+esc(s.title)+'</h2>'+frmHtml+mdToHtml(s.body)+'</div>';
  }).join('');
  return '<section id="'+esc(g.slug)+'">'+blocks+'</section>';
}
function insertNavTab(g, dayGroupKey){
  const nav = document.querySelector('nav');
  let a = nav.querySelector('a[data-slug="'+g.slug+'"]');
  if(!a){
    a = document.createElement('a');
    a.href = '#';
    nav.appendChild(a);
  }
  a.dataset.slug = g.slug;
  a.dataset.order = g.order;
  a.dataset.day = dayGroupKey;
  a.innerHTML = esc(g.genre) + '<span class="loaded-tag">読込</span>';
  const tabs = Array.from(nav.querySelectorAll('a'));
  tabs.sort((x,y)=>(parseInt(x.dataset.order||'50',10) - parseInt(y.dataset.order||'50',10)));
  tabs.forEach(t=>nav.appendChild(t));
  bindNav();
}
function splitGenreBlocks(text){
  const re = /^---[ \t]*\r?\n(?=genre\s*:)/mg;
  let m; const starts = [];
  while((m = re.exec(text))){ starts.push(m.index); }
  if(starts.length === 0) return [text];
  starts.push(text.length);
  const blocks = [];
  for(let i=0;i<starts.length-1;i++) blocks.push(text.slice(starts[i], starts[i+1]));
  return blocks;
}
function dayKeyFromName(name){
  const m = (name||'').match(/(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : '';
}
function dayOptionLabel(dayKey){
  if(!dayKey) return '読み込んだファイル';
  const parts = dayKey.split('-');
  return parts[0]+'年'+parseInt(parts[1],10)+'月'+parseInt(parts[2],10)+'日';
}
function ensureDayOption(dayKey){
  const key = dayKey || '__loaded__';
  const sel = document.getElementById('daySelect');
  if(sel && !sel.querySelector('option[value="'+key+'"]')){
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = dayOptionLabel(dayKey);
    sel.insertBefore(opt, sel.firstChild);
  }
  return key;
}
function namespaceSlug(g, dayGroupKey){
  const isEssays = (g.slug === 'essays');
  g.slug = g.slug + '__' + dayGroupKey;
  return isEssays;
}
function renderOneBlock(block, fallbackName, dayKey){
  const g = parseMdText(block, fallbackName);
  const dayGroupKey = dayKey || '__loaded__';
  const isEssays = namespaceSlug(g, dayGroupKey);
  const html = isEssays ? essaysSectionHtml(g) : genreSectionHtml(g);
  const old = document.getElementById(g.slug);
  if(old) old.remove();
  document.querySelector('main').insertAdjacentHTML('beforeend', html);
  ensureDayOption(dayKey);
  insertNavTab(g, dayGroupKey);
  try{
    localStorage.setItem('offlinebrief_loaded_'+g.slug, JSON.stringify({dayKey: dayKey||'', block}));
    const idxRaw = localStorage.getItem('offlinebrief_loaded_index');
    const idx = idxRaw ? JSON.parse(idxRaw) : [];
    if(!idx.includes(g.slug)) idx.push(g.slug);
    localStorage.setItem('offlinebrief_loaded_index', JSON.stringify(idx));
  }catch(e){}
  return {slug: g.slug, day: dayGroupKey};
}
function renderLoadedFile(text, filenameFallback){
  const dayKey = dayKeyFromName(filenameFallback);
  const blocks = splitGenreBlocks(text);
  let first = null;
  blocks.forEach((block, i)=>{
    const res = renderOneBlock(block, i ? filenameFallback+'_'+i : filenameFallback, dayKey);
    if(first===null) first = res;
  });
  if(first) showDay(first.day, first.slug);
}
function restoreLoadedFiles(){
  try{
    const idxRaw = localStorage.getItem('offlinebrief_loaded_index');
    if(!idxRaw) return;
    const idx = JSON.parse(idxRaw);
    for(const key of idx){
      const raw = localStorage.getItem('offlinebrief_loaded_'+key);
      if(!raw) continue;
      let dayKey = '', block = raw;
      try{
        const parsed = JSON.parse(raw);
        if(parsed && typeof parsed==='object' && 'block' in parsed){ dayKey = parsed.dayKey||''; block = parsed.block; }
      }catch(e){}
      const g = parseMdText(block, key);
      const dayGroupKey = dayKey || '__loaded__';
      const isEssays = namespaceSlug(g, dayGroupKey);
      const html = isEssays ? essaysSectionHtml(g) : genreSectionHtml(g);
      const old = document.getElementById(g.slug);
      if(old) old.remove();
      document.querySelector('main').insertAdjacentHTML('beforeend', html);
      ensureDayOption(dayKey);
      insertNavTab(g, dayGroupKey);
    }
  }catch(e){}
}
restoreLoadedFiles();
const loadBtn = document.getElementById('loadMdBtn');
const fileInput = document.getElementById('mdFileInput');
if(loadBtn && fileInput){
  loadBtn.addEventListener('click', ()=>fileInput.click());
  fileInput.addEventListener('change', (e)=>{
    const files = Array.from(e.target.files||[]);
    files.forEach(f=>{
      const reader = new FileReader();
      reader.onload = ()=>renderLoadedFile(String(reader.result), f.name.replace(/\.md$/,''));
      reader.readAsText(f, 'utf-8');
    });
    fileInput.value = '';
  });
}
"""


def genre_section_html(g):
    cards = []
    for s in g["sections"]:
        meta_bits = [s["meta"].get("source", ""), s["meta"].get("date", "")]
        meta_line = " / ".join(b for b in meta_bits if b)
        url = s["meta"].get("url", "")
        srclink = (f'<div class="srclink">出典: <a href="{esc(url)}">{esc(url)}</a>(オンライン時のみ)</div>'
                   if url else "")
        cards.append(f"""
<article>
 <h2>{esc(s['title'])}</h2>
 <div class="meta">{esc(meta_line)}</div>
 {md_to_html(s['body'])}
 {srclink}
</article>""")
    ov = (f'<div class="overview"><strong>今日の概況</strong><br>{esc(g["overview"])}</div>'
          if g["overview"] else "")
    return f'<section id="{esc(g["slug"])}">{ov}{"".join(cards)}</section>'


def essays_section_html(g):
    blocks = []
    for s in g["sections"]:
        frm = s["meta"].get("from", "")
        frm_html = f'<div class="from">きっかけ: {esc(frm)}</div>' if frm else ""
        blocks.append(f"""
<div class="essay">
 <span class="label">知的探究</span>
 <h2>{esc(s['title'])}</h2>
 {frm_html}
 {md_to_html(s['body'])}
</div>""")
    return f'<section id="{esc(g["slug"])}">{"".join(blocks)}</section>'


def main():
    date_dirs = sorted([d for d in CONTENT.iterdir() if d.is_dir()
                        and re.match(r"\d{4}-\d{2}-\d{2}$", d.name)])
    if not date_dirs:
        raise SystemExit("[error] content/YYYY-MM-DD/ フォルダがありません")

    # 新しい日付順(降順)に並べ、MAX_DAYS_IN_BUILDが設定されていればその日数分だけに絞る
    # (Noneなら [:None] は全件を意味するのでスライスはそのまま全日付を返す)
    build_dirs = list(reversed(date_dirs))[:MAX_DAYS_IN_BUILD]

    day_options = []
    nav, sections = [], []
    latest_name = None

    for day_dir in build_dirs:
        day = day_dir.name
        parsed = []
        for p in sorted(day_dir.glob("*.md")):
            parsed.extend(parse_file(p))
        parsed.sort(key=lambda g: g["order"])
        if not parsed:
            continue

        if latest_name is None:
            latest_name = day
        day_options.append(f'<option value="{day}">{esc(day_option_label(day))}</option>')

        for g in parsed:
            day_slug = f'{g["slug"]}__{day}'
            nav.append(
                f'<a href="#" data-slug="{esc(day_slug)}" data-order="{g["order"]}" '
                f'data-day="{day}">{esc(g["genre"])}</a>'
            )
            g_for_html = dict(g, slug=day_slug)
            sections.append(essays_section_html(g_for_html) if g["slug"] == "essays"
                            else genre_section_html(g_for_html))

    if latest_name is None:
        raise SystemExit("[error] content/YYYY-MM-DD/ 配下に有効な .md がありません")

    print(f"[build] {latest_name} を最新として、直近{len(day_options)}日分を同梱")

    version = str(int(time.time()))
    date_label = day_option_label(latest_name)

    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>機内ブリーフ {esc(date_label)}</title>
<meta name="theme-color" content="#0f4c81">
<link rel="manifest" href="./manifest.webmanifest">
<link rel="apple-touch-icon" href="./icon-192.png">
<style>{CSS}</style>
</head>
<body>
<div class="offline-badge">オフライン閲覧中(キャッシュ済み)</div>
<header>
<div class="headtext"><h1>✈ 機内ブリーフ</h1><div class="date">{esc(date_label)}版</div></div>
<select id="daySelect" class="day-select">{''.join(day_options)}</select>
<button id="loadMdBtn" class="load-btn" type="button">📄 mdファイルを読み込む(複数日OK)</button>
<input id="mdFileInput" type="file" accept=".md,text/markdown" multiple style="display:none">
</header>
<nav>{''.join(nav)}</nav>
<main>{''.join(sections)}</main>
<footer>OfflineBrief — Claudeが調査・執筆した解説を含みます。誤りを含む可能性があるため重要な判断には出典をご確認ください。<br>build {version}</footer>
<script>{JS}</script>
</body>
</html>"""

    if PUBLIC.exists():
        shutil.rmtree(PUBLIC, ignore_errors=True)
    PUBLIC.mkdir(exist_ok=True)
    (PUBLIC / "index.html").write_text(page, encoding="utf-8")

    (PUBLIC / "manifest.webmanifest").write_text(json.dumps({
        "name": "機内ブリーフ", "short_name": "機内ブリーフ",
        "start_url": "./", "display": "standalone",
        "background_color": "#faf8f4", "theme_color": "#0f4c81",
        "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }, ensure_ascii=False), encoding="utf-8")

    sw = """const CACHE='brief-VERSION';
const ASSETS=['./','./index.html','./manifest.webmanifest','./icon-192.png','./icon-512.png'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting()))});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
self.addEventListener('fetch',e=>{
 e.respondWith(
  fetch(e.request).then(r=>{
   if(e.request.method==='GET'&&r.ok&&new URL(e.request.url).origin===location.origin){
    const cp=r.clone();caches.open(CACHE).then(c=>c.put(e.request,cp));}
   return r;
  }).catch(()=>caches.match(e.request,{ignoreSearch:true}).then(m=>m||caches.match('./index.html')))
 );
});""".replace("VERSION", version)
    (PUBLIC / "sw.js").write_text(sw, encoding="utf-8")

    for icon in ("icon-192.png", "icon-512.png"):
        src = ROOT / "assets" / icon
        if src.exists():
            shutil.copy(src, PUBLIC / icon)

    print(f"[done] -> {PUBLIC}/index.html (build {version})")


if __name__ == "__main__":
    main()
