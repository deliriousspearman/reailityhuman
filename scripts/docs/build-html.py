#!/usr/bin/env python3
"""Renders the guides in docs/ (developer-guide.md, admin-guide.md) as themed, self-contained HTML in
docs/html/, in the panel's Hardline Classic look (frontend/src/lib/styles/tokens.css and app.css).

The markdown is the source: edit it, then run this from anywhere and commit both.

    python3 scripts/docs/build-html.py

Needs Python's markdown and pymdown-extensions packages (pip install markdown pymdown-extensions, or
apt install python3-markdown python3-pymdownx). Lists nest with 4-space indents, as Python-Markdown
requires (GitLab renders them the same).
"""

import html
import re
import sys
from pathlib import Path

try:
    import markdown
    import pymdownx  # noqa: F401  (superfences: code blocks inside lists)
except ImportError:
    sys.exit("build-html.py needs Python's markdown and pymdown-extensions: pip install markdown pymdown-extensions")

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
OUT = DOCS / "html"
GUIDES = {"developer-guide": "Developer guide", "admin-guide": "Admin guide"}

# Colours and shape: the panel's tokens (frontend/src/lib/styles/tokens.css). Keep in step with it.
CSS = r"""
:root {
  --display: 'Chakra Petch', var(--font);
  --font: 'Figtree Variable', 'Figtree', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  --mono: 'JetBrains Mono Variable', 'JetBrains Mono', ui-monospace, 'SFMono-Regular', Menlo, Consolas, 'DejaVu Sans Mono', monospace;
  --white: #ffffff; --gray-1: #e4e9f4; --gray-2: #a4b1cd; --gray-3: #8494b5; --gray-4: #52627f;
  --gray-5: #2c3a52; --gray-6: #1a2332; --black: #111927;
  --accent-low: #2a3d12; --accent: #9fef00; --accent-high: #c5f467;
  --bg-nav: #1a2332; --bg-sidebar: #141d2b; --bg-code: #202c3f; --panel: #1a2332; --panel-2: #202c3f;
  --lime: #9fef00; --on-lime: #0e1a02; --lime-text: #9fef00; --medium: #ffaf00; --hard: #ff3e3e;
  --header: 4rem; --sidebar: 17rem;
  color-scheme: dark;
}
:root[data-theme='light'] {
  --white: #0f1726; --gray-1: #1a2332; --gray-2: #34435c; --gray-3: #56657f; --gray-4: #8c99b0;
  --gray-5: #d3dae6; --gray-6: #e9edf4; --black: #f4f6fa;
  --accent-low: #e8f8c8; --accent: #5b8c00; --accent-high: #3d6200;
  --bg-nav: #ffffff; --bg-sidebar: #ffffff; --bg-code: #e9edf4; --panel: #ffffff; --panel-2: #f1f4f9;
  --lime-text: #3d6200; --medium: #b86e00; --hard: #d12a2a;
  color-scheme: light;
}
*, *::before, *::after { box-sizing: border-box; }
html { scroll-padding-top: calc(var(--header) + 1rem); -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--black); color: var(--gray-2); font: 1rem/1.65 var(--font); }
a { color: var(--lime-text); }
a:hover { color: var(--accent-high); }
:focus-visible { outline: 2px solid var(--accent-high); outline-offset: 2px; }

/* Header */
.top { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 1rem;
  height: var(--header); padding: 0 1.25rem; background: var(--bg-nav); border-bottom: 2px solid var(--gray-5); }
.brand { display: flex; align-items: center; gap: .6rem; color: var(--white); text-decoration: none;
  font: 700 1.15rem var(--display); letter-spacing: .02em; }
.brand-mark { display: grid; place-items: center; width: 2rem; height: 2rem; background: var(--lime);
  color: var(--on-lime); font: 700 .95rem var(--mono); }
.crumb { color: var(--gray-3); font: 600 .85rem var(--mono); text-transform: uppercase; letter-spacing: .08em; }
.top-links { margin-left: auto; display: flex; align-items: center; gap: .75rem; }
.top-links a { color: var(--gray-2); text-decoration: none; font: 700 .9rem var(--display); }
.top-links a:hover, .top-links a[aria-current] { color: var(--lime-text); }
select { padding: .3rem .5rem; border: 1px solid var(--gray-4); border-radius: 0; background: var(--panel);
  color: var(--white); font: 600 .8rem var(--mono); }
.menu-btn { display: none; padding: .3rem .6rem; border: 1px solid var(--gray-4); background: transparent;
  color: var(--white); font: 700 .85rem var(--display); cursor: pointer; }

/* Layout */
.layout { display: grid; grid-template-columns: var(--sidebar) minmax(0, 1fr); }
.toc { position: sticky; top: var(--header); align-self: start; height: calc(100vh - var(--header));
  overflow-y: auto; padding: 1.5rem 1rem 2rem; background: var(--bg-sidebar); border-right: 2px solid var(--gray-5); }
.toc-title { margin: 0 0 .75rem; color: var(--gray-3); font: 700 .75rem var(--mono); text-transform: uppercase; letter-spacing: .1em; }
.toc ul { list-style: none; margin: 0; padding: 0; }
.toc li a { display: block; padding: .3rem .6rem; border-left: 3px solid transparent; color: var(--gray-2);
  text-decoration: none; font-size: .9rem; line-height: 1.35; }
.toc li a:hover { color: var(--white); background: var(--panel-2); }
.toc li a.active { border-left-color: var(--lime); color: var(--lime-text); background: var(--panel-2); }
.toc ul ul a { padding-left: 1.4rem; font-size: .84rem; color: var(--gray-3); }
main { min-width: 0; padding: 2.5rem clamp(1.25rem, 4vw, 3.5rem) 5rem; }
.content { max-width: 52rem; }

/* Text */
h1, h2, h3, h4 { font-family: var(--display); font-weight: 700; line-height: 1.2; color: var(--white); }
h1 { margin: 0 0 1rem; font-size: clamp(1.9rem, 1.4rem + 1.8vw, 2.5rem); }
h2 { margin: 3rem 0 1rem; padding: .35rem 0 .35rem .8rem; border-left: 3px solid var(--lime); font-size: 1.45rem; }
h3 { margin: 2rem 0 .75rem; font-size: 1.15rem; }
h4 { margin: 1.5rem 0 .5rem; font-size: 1rem; }
.headerlink { margin-left: .4rem; color: var(--gray-4); text-decoration: none; opacity: 0; }
h2:hover .headerlink, h3:hover .headerlink { opacity: 1; }
p, ul, ol { margin: 0 0 1rem; }
li { margin: .25rem 0; }
li > ul, li > ol { margin: .25rem 0 0; }
strong { color: var(--gray-1); }
hr { border: 0; border-top: 2px solid var(--gray-5); margin: 2rem 0; }
code { padding: .1rem .35rem; background: var(--bg-code); color: var(--gray-1); font: .86em var(--mono); }
a code { color: inherit; }

/* Code blocks: the panel's terminal window */
.term { margin: 0 0 1.25rem; border: 2px solid #2c3a52; background: #0d1420; }
.term-bar { display: flex; align-items: center; gap: .4rem; padding: .45rem .75rem; background: #1a2332;
  border-bottom: 1px solid #2c3a52; }
.term-bar i { width: .65rem; height: .65rem; border-radius: 50%; }
.term-bar i:nth-child(1) { background: #ff3e3e; } .term-bar i:nth-child(2) { background: #ffaf00; }
.term-bar i:nth-child(3) { background: #9fef00; }
.term-bar span { margin-left: auto; color: #8494b5; font: 600 .7rem var(--mono); text-transform: uppercase; letter-spacing: .08em; }
.term pre { margin: 0; padding: 1rem 1.1rem; overflow-x: auto; color: #a4b1cd; font: .85rem/1.55 var(--mono); }
.term pre code { padding: 0; background: none; color: inherit; font: inherit; }

/* Tables */
.table-wrap { margin: 0 0 1.5rem; overflow-x: auto; border: 2px solid var(--gray-5); background: var(--panel); }
table { width: 100%; border-collapse: collapse; font-size: .92rem; }
th { padding: .6rem .8rem; text-align: left; white-space: nowrap; color: var(--gray-3); background: var(--panel-2);
  font: 700 .72rem var(--mono); text-transform: uppercase; letter-spacing: .06em; border-bottom: 2px solid var(--gray-5); }
td { padding: .6rem .8rem; vertical-align: top; border-top: 1px solid var(--gray-5); }
tr:first-child td { border-top: 0; }

/* Callouts: the panel's banners */
blockquote { margin: 0 0 1.25rem; padding: .85rem 1.1rem; border: 1px solid var(--gray-4);
  border-left-width: 4px; background: var(--panel); }
blockquote p:last-child { margin: 0; }
blockquote.note { border-color: var(--accent); background: linear-gradient(90deg, var(--accent-low), transparent 70%); }
blockquote.warn { border-color: var(--medium); background: linear-gradient(90deg, color-mix(in srgb, var(--medium) 16%, transparent), transparent 70%); }
blockquote.note strong:first-child { color: var(--lime-text); }
blockquote.warn strong:first-child { color: var(--medium); }

.foot { margin-top: 4rem; padding-top: 1rem; border-top: 2px solid var(--gray-5); color: var(--gray-3); font-size: .85rem; }

@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .menu-btn { display: inline-block; }
  .crumb { display: none; }
  .toc { position: fixed; top: var(--header); left: 0; z-index: 9; width: min(85vw, 20rem); transform: translateX(-105%);
    transition: transform .2s; }
  body.toc-open .toc { transform: none; box-shadow: 4px 0 0 var(--lime); }
}
@media (max-width: 560px) {
  .top { gap: .6rem; padding: 0 .75rem; }
  .brand-name, .top-links a:not([aria-current]) { display: none; }
}
@media print {
  .top, .toc { display: none; }
  .layout { display: block; }
}
"""

# Theme: the same localStorage key as the panel (labs-theme); "auto" follows the system.
HEAD_JS = r"""
(function () {
  var t = localStorage.getItem('labs-theme') || 'auto';
  if (t !== 'dark' && t !== 'light') t = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  document.documentElement.dataset.theme = t;
})();
"""

BODY_JS = r"""
(function () {
  var sel = document.getElementById('theme');
  var saved = localStorage.getItem('labs-theme');
  sel.value = saved === 'dark' || saved === 'light' ? saved : 'auto';
  sel.addEventListener('change', function () {
    localStorage.setItem('labs-theme', sel.value);
    var t = sel.value === 'auto' ? (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : sel.value;
    document.documentElement.dataset.theme = t;
  });
  document.getElementById('menu').addEventListener('click', function () { document.body.classList.toggle('toc-open'); });
  var links = Array.prototype.slice.call(document.querySelectorAll('.toc a'));
  links.forEach(function (a) { a.addEventListener('click', function () { document.body.classList.remove('toc-open'); }); });
  var heads = links.map(function (a) { return document.getElementById(decodeURIComponent(a.hash.slice(1))); });
  function spy() {
    var current = 0;
    heads.forEach(function (h, i) { if (h && h.getBoundingClientRect().top < 120) current = i; });
    links.forEach(function (a, i) { a.classList.toggle('active', i === current); });
  }
  addEventListener('scroll', spy, { passive: true });
  spy();
})();
"""

PAGE = """<!DOCTYPE html>
<html lang="en-GB" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Codex Labs</title>
<script>{head_js}</script>
<style>{css}</style>
</head>
<body>
<header class="top">
  <button class="menu-btn" id="menu" type="button" aria-label="Contents">Contents</button>
  <a class="brand" href="#top"><span class="brand-mark">CL</span><span class="brand-name">Codex Labs</span></a>
  <span class="crumb">{title}</span>
  <nav class="top-links" aria-label="Guides">
    {guide_links}
    <select id="theme" aria-label="Theme">
      <option value="auto">Auto</option><option value="dark">Dark</option><option value="light">Light</option>
    </select>
  </nav>
</header>
<div class="layout">
  <nav class="toc" aria-label="On this page">
    <p class="toc-title">On this page</p>
    {toc}
  </nav>
  <main id="top">
    <article class="content">
{body}
      <p class="foot">Generated from <code>docs/{name}.md</code> by <code>scripts/docs/build-html.py</code>. Edit the markdown, not this file.</p>
    </article>
  </main>
</div>
<script>{body_js}</script>
</body>
</html>
"""


def fix_link(href: str) -> str:
    """Links are written relative to docs/; the HTML lives one folder down, in docs/html/."""
    if re.match(r"^([a-z]+:|#|/)", href):
        return href
    path, _, frag = href.partition("#")
    stem = path[:-3] if path.endswith(".md") else None
    if stem in GUIDES:
        path = f"{stem}.html"
    else:
        path = f"../{path}"
    return path + (f"#{frag}" if frag else "")


def toc_html(tokens: list) -> str:
    """The sidebar: h2s, with their h3s nested (h1 and deeper levels left out)."""
    def items(ts, depth):
        out = []
        for t in ts:
            if t["level"] == 1:
                out.extend(items(t["children"], depth))
                continue
            kids = items(t["children"], depth + 1) if depth < 1 else []
            sub = f"<ul>{''.join(kids)}</ul>" if kids else ""
            out.append(f'<li><a href="#{t["id"]}">{t["name"]}</a>{sub}</li>')
        return out
    return f"<ul>{''.join(items(tokens, 0))}</ul>"


def postprocess(body: str) -> str:
    body = re.sub(r'href="([^"]+)"', lambda m: f'href="{html.escape(fix_link(html.unescape(m.group(1))))}"', body)

    # Fenced code in the terminal frame, labelled with its language.
    def term(m):
        lang = m.group(1) or ""
        label = {"sh": "shell", "text": "", "yaml": "yaml", "ts": "typescript"}.get(lang, lang)
        return (f'<div class="term"><div class="term-bar"><i></i><i></i><i></i><span>{label}</span></div>'
                f'<pre><code>{m.group(2)}</code></pre></div>')
    body = re.sub(r'<pre class="highlight"><code(?: class="language-([\w-]+)")?>(.*?)</code></pre>', term, body, flags=re.S)

    body = re.sub(r"<table>", '<div class="table-wrap"><table>', body)
    body = re.sub(r"</table>", "</table></div>", body)

    # > **Note:** / > **Warning:** become the panel's banners.
    def callout(m):
        kind = "warn" if m.group(1).startswith("Warning") else "note"
        return f'<blockquote class="{kind}">\n<p><strong>{m.group(1)}</strong>'
    return re.sub(r"<blockquote>\s*<p><strong>(Note:|Warning:)</strong>", callout, body)


def build(name: str, title: str) -> Path:
    md = markdown.Markdown(
        extensions=["toc", "tables", "pymdownx.highlight", "pymdownx.superfences", "attr_list", "sane_lists"],
        extension_configs={"toc": {"permalink": "#", "toc_depth": "2-3"}, "pymdownx.highlight": {"use_pygments": False}})
    body = postprocess(md.convert((DOCS / f"{name}.md").read_text(encoding="utf-8")))
    current = ' aria-current="page"'
    links = " ".join(f'<a href="{n}.html"{current if n == name else ""}>{t}</a>' for n, t in GUIDES.items())
    page = PAGE.format(title=html.escape(title), name=name, css=CSS, head_js=HEAD_JS, body_js=BODY_JS,
                       guide_links=links, toc=toc_html(md.toc_tokens), body=body)
    out = OUT / f"{name}.html"
    out.write_text(page, encoding="utf-8")
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, title in GUIDES.items():
        print(build(name, title).relative_to(ROOT))


if __name__ == "__main__":
    main()
