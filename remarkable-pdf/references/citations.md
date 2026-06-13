# Citation pattern: worked examples and troubleshooting

The remarkable-pdf skill uses a two-layer citation pattern:

1. **Page-bottom footnotes** at the first mention of each source — so the reader sees the citation immediately without flipping pages.
2. **A consolidated References section** at the end — so the reader has a clean list they can scan or copy.

Both layers carry the same numbered identifier (`[1]`, `[2]`, …) so a reader can cross-match.

## Minimum working example (handwritten LaTeX)

```latex
\input{remarkable-preamble.tex}
\title{Example}\author{}\date{}
\newcommand{\briefingtitle}{Example}\newcommand{\transcriptnum}{}

\begin{document}\maketitle\thispagestyle{plain}

The OpenAI paper \textit{State of Enterprise AI 2025}\footnote{[1]~OpenAI,
\textit{State of Enterprise AI 2025} (Dec 2025) —
\url{https://cdn.openai.com/paper.pdf}} reported a 95\% failure rate in
enterprise AI pilots.

Elsewhere the report states ...\cite{1}

\clearpage
\section*{References}\footnotesize\sloppy

\begin{enumerate}[label={[\arabic*]},leftmargin=1.6em,itemsep=0.5em]
  \item OpenAI, \textit{State of Enterprise AI 2025} (Dec 2025) — \url{https://cdn.openai.com/paper.pdf}
\end{enumerate}

\end{document}
```

Three mechanics worth noticing:

- **Footnote on first mention only.** Repeat citations use `\cite{1}` (a small sans superscript, defined in the preamble) rather than repeating the full footnote.
- **Title is italicized in both places.** This is stylistic, but the `md_to_tex.py` script relies on italicization to auto-inject footnotes — see below.
- **URLs wrapped in `\url{...}`.** `xurl` breaks them cleanly across line ends. A plain `http://...` won't break and will overflow the narrow column.

## Using `scripts/md_to_tex.py`

If the body is written in markdown, `md_to_tex.py` will inject footnotes for you. Pass it a sources file as `--sources <path>`:

```markdown
# sources.md
- OpenAI, *State of Enterprise AI 2025* (Dec 2025) — https://cdn.openai.com/paper.pdf
- a16z, *Your Data Agents Need Context* (2026) — https://a16z.com/your-data-agents-need-context/
```

The script:

1. Extracts each bulleted source and pulls the italicized title.
2. Scans the body for the first mention of that title (trying italics first, then quotes, then a bare word-boundary match).
3. Attaches a `\footnote{[N] ...}` at that spot.
4. Appends a References section at the end with every source in order.

**Why the italics-first strategy?** In well-edited markdown, source titles are italicized (`*Title*`). The script's first pass looks for those exact forms in the body. When it finds them, there's no ambiguity about where the footnote should go.

## Title-matching troubleshooting

The most common failure mode is "the script doesn't inject my footnote, even though the body clearly mentions the source." Typical causes:

**The body uses a shorter form than the sources file.** E.g., sources file says `*The State of Enterprise AI 2025 Report*` but the body just says `State of Enterprise AI 2025`. The script tries common variants automatically (drop leading *The*, drop trailing *Report*/*Guide*) but can't catch every edit. Fix: either make the body match, or shorten the title in the sources file.

**The title is in quotes, not italics.** E.g., `"State of Enterprise AI 2025"`. The script catches this in its second-pass tier, so it should still work — but if you've got straight-quote-vs-smart-quote mismatches, it may miss. Look at the generated `.tex` to confirm whether `\footnote{...}` appeared next to the expected phrase.

**The title is too short.** The script's third-pass (bare word-boundary) match is deliberately restricted to titles 15+ characters long, to avoid false positives on common words. A title like `"Skills"` or `"Context"` won't match bare-word; wrap it in italics or quotes in the body, or extend the title in the sources file.

**The only mention is inside the References list itself.** This was a bug in an earlier draft of the script. The fix: pass the body separately from the references, and only inject footnotes into the body. If you're debugging this, confirm your `build_document` calls `inject_footnotes` *before* appending the References section.

## When to skip the References section

For very short documents with one or two sources, a footnote-only approach can be tidier. Pass `--no-references` to the script, or hand-author without the `\clearpage\section*{References}` block. The footnote alone carries the citation.

For long documents with many repeat mentions, the `\cite{N}` helper (defined in the preamble) renders as a small sans superscript — use it for second and subsequent mentions of a source that's already been footnoted.

## Footnote formatting

The preamble sets footnote text at 7.8pt with 9.2pt leading and flushes footnotes to the bottom of each page (`footmisc` with `[bottom,hang,flushmargin]`). This keeps the footnote column tidy at the foot of the page and prevents the common "footnote floats away from its mention" problem.

If footnotes visibly overcrowd a page, it usually means too many sources are cited close together. Either:

- Move some citations to `\cite{N}` short form (if they've been previously footnoted), or
- Accept the overflow — `footmisc` handles continuation across pages gracefully.
