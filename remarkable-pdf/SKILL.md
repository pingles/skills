---
name: remarkable-pdf
description: Produce a LaTeX-typeset PDF sized and styled for comfortable reading on a Remarkable Pro Move e-ink tablet (4.00" × 7.11" portrait, 16:9), with inline page-bottom footnotes plus a consolidated References section. Use whenever the user wants a briefing, memo, research summary, paper, or any prose document formatted specifically for a Remarkable or similar narrow e-ink reader — especially if they mention "Remarkable", "Pro Move", "e-ink", "narrow PDF", "reader-friendly PDF", "a PDF I can annotate on my tablet", or describe a device around 4 inches wide. Also trigger when converting an existing briefing or markdown doc into an e-reader-friendly PDF, even if the user doesn't name the device explicitly. Do NOT trigger for standard letter/A4 PDFs, slide decks, or Word documents — those are served better by other skills.
---

# Remarkable Pro Move PDF

This skill produces PDFs sized and typeset for the Remarkable Pro Move (and similar narrow 16:9 portrait e-ink readers around 4 inches wide). It bundles a tested LaTeX preamble, a minimal markdown-to-LaTeX converter, and a citation pattern that pairs page-bottom footnotes with a consolidated end-of-document References section.

## When to reach for this

Use this skill when the goal is a **PDF for reading on a narrow e-ink device**. The preamble is tuned for the Move's 4-inch-wide screen specifically, but works well for any similarly proportioned reader. If the target device is different (letter paper, A4, large-format tablet), a standard LaTeX setup is better — this one sacrifices column width for device-native rendering.

A useful signal: the user cares that the document will be read on a tablet, not printed. They may want to annotate with a stylus, bookmark sections, or read on a commute. If those concerns are absent, reach for a different skill.

## The shape of the output

Each project produces, at minimum:

- a `.tex` source file
- a compiled `.pdf`
- the shared preamble (copied in as `remarkable-preamble.tex`)

The PDF page is 288 × 511.92 pt (exactly 4.00 × 7.11 inches). Body type is TeX Gyre Pagella (a Palatino-like Latin-script serif) at 10pt with 1.14 leading — chosen for comfortable reading on e-ink at device-native resolution, where crisp x-height and generous counters matter more than tight setting. Headings use TeX Gyre Adventor as a sans companion.

## Workflow

1. **Set up the working directory.** Copy `assets/remarkable-preamble.tex` to the project folder. This is the one file the skill really insists on — it encodes every typographic and geometric decision and the document just needs to `\input` it.

2. **The default preamble includes a 0.75in right margin for handwritten annotations.** This is the right default for e-ink readers where stylus notes are common. See *Annotation margin* below if you need to adjust (narrower for max text density, wider for more writing space).

3. **Author the body.** Two sensible paths:
   - **Write LaTeX directly.** Use `assets/example-body.tex` as a starter. This is the right choice when the user wants fine typographic control or already works in LaTeX.
   - **Start from markdown.** Run `scripts/md_to_tex.py <input.md> <output.tex>` to convert a markdown file. This handles headings, lists, tables, bold/italic/code, and links, and drops the preamble + title block around the body. This is the right choice for most briefing-style docs.

4. **Inject citations** if the document has sources. See *Citations* below for the footnote-plus-References pattern the script supports.

5. **Compile.** `pdflatex -interaction=nonstopmode <name>.tex` twice (second pass resolves page numbers and any cross-references). Check the log for `Overfull` boxes — the preamble is tuned to minimize these, but stubborn long URLs or unbreakable code spans can still overflow. See *Narrow-column typesetting* for remedies.

6. **Verify** with `pdfinfo`: page size should read `288 x 511.92 pts`. If it reads anything else, the preamble wasn't picked up.

## Page geometry

Defined in the preamble's `geometry` block:

```
paperwidth  = 4.00in
paperheight = 7.11in
top         = 0.40in
bottom      = 0.45in
left        = 0.35in
right       = 0.75in    (default — annotation margin for stylus notes)
```

The 16:9 ratio approximates the Move's display. The default 0.75in right margin reserves space for handwritten annotations — a good balance between text density and writing room. The asymmetric top/bottom leaves room for the running header on every page after the first.

## Font stack

TeX Gyre Pagella for body copy, TeX Gyre Adventor for headings and UI furniture (page numbers, running heads, table column headers). Pagella is Palatino-family; Adventor is URW Gothic-family. They're free, ship with TeX Live, and are well-hinted for the sizes we use.

Keep body text at 10pt. E-ink renders around ~225 dpi on the Move; below 10pt, strokes start to look thin. 11pt is readable too but costs you roughly one line per page.

If the user asks for a different face, the usual substitutions work: `\usepackage{tgtermes}` for Times-like, `\usepackage{libertine}` for Libertine, `\usepackage{mathpazo}` if Pagella isn't available. Keep the same geometry and leading.

## Citations

The pattern is **footnote at first mention + consolidated References list at the end**. This gives the reader immediate context without flipping pages, and a clean bibliography they can scan or copy from.

The footnote marker is a superscript number in sans-serif. The References section starts on a fresh page (`\clearpage`) and uses a numbered list with URL-safe breaking (`\url{...}`).

**How to cite in the body:**

Wrap the source's short title in `\textit{...}` on first mention. Example:

```
The OpenAI paper \textit{State of Enterprise AI 2025} reported that 95%% of
enterprise AI pilots deliver no measurable P&L impact.
```

**If you're using `scripts/md_to_tex.py`**, the script will scan primary sources from a markdown file you pass via `--sources <file>` and auto-inject a `\footnote{...}` at the first italicized match of each title. See the script's `--help` for details.

**If you're handwriting LaTeX**, drop a `\footnote{...}` directly at the first mention and list all sources in the `references` environment at the end. The preamble defines a helper `\cite{N}` that renders as a small superscript sans reference marker — use it for repeat citations within the body if you'd rather not repeat the full footnote.

See `references/citations.md` for worked examples and troubleshooting (common issue: the short-title form in the body doesn't match the full title in the References entry; the script has variant matching built in, but handwritten docs need manual care).

## Narrow-column typesetting

Four-inch columns are unforgiving. The preamble includes several tuning knobs; the ones worth knowing:

- **`\emergencystretch=3.5em`** — lets TeX stretch inter-word space up to 3.5em on a line it otherwise couldn't break cleanly, trading a slightly loose line for zero overfull boxes. The default (0pt) is too strict here.
- **`\tolerance=2000`** and **`\hyphenpenalty=50`** — make TeX more willing to break mid-word and to accept slightly-underfull lines. Raise `tolerance` further (up to 9999) if you still see overfulls.
- **`xurl` package** — aggressive URL line-breaking. Without it, a single long URL will blow the column width and TeX will shrug.
- **`microtype`** — font expansion and protrusion. Subtle but measurable reduction in ragged right edges.

If a compile still produces overfull boxes after all this, the usual culprits are: a `\texttt{...}` span without spaces (use `\seqsplit` or add zero-width breaks), a URL that `xurl` can't crack (break it manually), or a long compound word that won't hyphenate (add `\-` hints or `\linebreak[2]`).

## Tables

Use `tabularx` with `X` columns sized to `\linewidth`, and `booktabs` rules (`\toprule`, `\midrule`, `\bottomrule`). Set table text to `\footnotesize` (≈8.5pt) — the preamble defines this. Avoid vertical rules entirely; they're wrong for booktabs and look noisy at narrow widths.

```latex
\begin{table}[!htbp]
\centering\footnotesize
\begin{tabularx}{\linewidth}{@{}XX@{}}
\toprule
\textbf{Col A} & \textbf{Col B} \\
\midrule
cell 1 & cell 2 \\
\bottomrule
\end{tabularx}
\end{table}
```

Three columns is usually the practical limit at 4" wide. Four columns becomes cramped unless cells are very short.

## Annotation margin

The default right margin is **0.75in**, which reserves space for handwritten stylus annotations. This is the right default for e-ink readers where annotation is a primary use case — it gives a text column of ~2.90in, balancing readability with writing room.

To adjust, open `remarkable-preamble.tex` and change the `right` value:

- `right=0.35in` — maximum text density, no annotation space (~3.30in column)
- `right=0.75in` — **default**, moderate annotation margin (~2.90in column, ~10% more pages)
- `right=1.00in` — wide annotation column (~2.65in column, ~25% more pages)

If the user explicitly says they don't need annotation space, use 0.35in. Otherwise stick with the 0.75in default.

## Title block

The preamble defines a clean title block that prints on the first page only (the header on subsequent pages uses `\briefingtitle` and `\transcriptnum` macros you can redefine per document). Set them up like:

```latex
\input{remarkable-preamble.tex}
\newcommand{\briefingtitle}{My Briefing}
\newcommand{\transcriptnum}{1}
\title{My Briefing Title}
\author{Author Name}
\date{April 2026}
\begin{document}
\maketitle
\thispagestyle{plain}

... body ...

\end{document}
```

If the running header doesn't make sense for the document (e.g., a single-topic paper with no series), delete the `\fancyhead` lines in the preamble or override with `\pagestyle{plain}`.

## Common pitfalls

- **Underscore in `\texttt{filename_here}`** — LaTeX reads `_` as a math subscript. Escape it: `filename\_here`. The conversion script handles this; handwritten docs need the escape.
- **Running header showing a URL** — the preamble renders the title in the header; if the title contains a URL or special characters, escape them or pass a simplified string via `\briefingtitle`.
- **Blank References page** — caused by `\clearpage` followed by an empty `enumerate`. Either guard with a check that there are sources, or skip the section entirely when there aren't any.
- **First compile shows `??` for page references** — normal; re-run `pdflatex` once more.

## What's in this skill

```
remarkable-pdf/
├── SKILL.md                          (this file)
├── assets/
│   ├── remarkable-preamble.tex       (the LaTeX preamble — primary artifact)
│   └── example-body.tex              (a minimal starter document)
├── scripts/
│   └── md_to_tex.py                  (markdown → LaTeX converter with citation injection)
└── references/
    └── citations.md                  (detailed citation-pattern worked examples)
```

Read `references/citations.md` if the document has more than a handful of sources or if the automatic citation injection isn't finding them — the reference file has debugging advice.
