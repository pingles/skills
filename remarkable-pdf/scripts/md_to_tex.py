#!/usr/bin/env python3
"""Convert a Markdown document to a LaTeX source file ready to compile with
the remarkable-preamble.tex preamble.

Usage:
  md_to_tex.py INPUT.md OUTPUT.tex
      --title "My Briefing"
      [--author "Name"]
      [--date "April 2026"]
      [--header-left "Series Name"]   # running-header left text
      [--header-right "Ep. 1"]         # running-header right text
      [--sources SOURCES.md]           # optional bullet list of sources
      [--no-references]                # skip the References section entirely
      [--preamble PATH]                # override preamble path (default: ../assets/)

Markdown features supported:
  - Headings (# / ## / ### map to \section* / \subsection* / \subsubsection*)
  - Bold **...**, italic *...*, code `...`, links [text](url)
  - Bulleted lists (- or *)
  - Pipe tables (first row = header, second = separator)
  - Horizontal rule ---
  - Plain paragraphs separated by blank lines

Citation pattern:
  If --sources is provided, the file should contain a bulleted list of
  sources, one per line, with the source's short title wrapped in *italics*.
  Example:
      - Author, *State of Enterprise AI 2025* (Dec 2025) — https://example.com/paper.pdf
      - Company, *Some Other Report* (2026) — https://example.com/other

  The script extracts the italicized titles, then inserts a \\footnote{...}
  at the first italicized mention of each title in the body. All sources are
  also listed in a References section at the end of the document.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# LaTeX escaping & inline-markdown handling
# ---------------------------------------------------------------------------

def latex_escape(text: str) -> str:
    out = text.replace("\\", r"\textbackslash{}")
    out = out.replace("&", r"\&")
    out = out.replace("%", r"\%")
    out = out.replace("$", r"\$")
    out = out.replace("#", r"\#")
    out = out.replace("_", r"\_")
    out = out.replace("{", r"\{")
    out = out.replace("}", r"\}")
    out = out.replace("~", r"\textasciitilde{}")
    out = out.replace("^", r"\textasciicircum{}")
    return out


def inline_markdown_to_latex(text: str) -> str:
    """Handle **bold**, *italic*, `code`, [link](url). Escape everything else."""
    parts = []
    pattern = re.compile(
        r"(\*\*[^*\n]+\*\*)"                # bold
        r"|(\*[^*\n]+\*)"                   # italic
        r"|(`[^`\n]+`)"                     # code
        r"|(\[[^\]\n]+\]\([^)\n]+\))"       # link
    )
    last = 0
    for m in pattern.finditer(text):
        start, end = m.span()
        if start > last:
            parts.append(latex_escape(text[last:start]))
        bold, ital, code, link = m.groups()
        if bold is not None:
            parts.append(r"\textbf{" + latex_escape(bold[2:-2]) + r"}")
        elif ital is not None:
            parts.append(r"\textit{" + latex_escape(ital[1:-1]) + r"}")
        elif code is not None:
            parts.append(r"\texttt{" + latex_escape(code[1:-1]) + r"}")
        elif link is not None:
            m2 = re.match(r"\[([^\]]+)\]\(([^)]+)\)", link)
            label = latex_escape(m2.group(1))
            url = m2.group(2)
            url_safe = url.replace("%", r"\%").replace("#", r"\#").replace("_", r"\_")
            parts.append(r"\href{" + url_safe + r"}{" + label + r"}")
        last = end
    if last < len(text):
        parts.append(latex_escape(text[last:]))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def convert_table(block_lines: list[str]) -> str:
    rows = []
    for ln in block_lines:
        if re.match(r"^\s*\|?\s*[-:| ]+\s*\|?\s*$", ln):
            continue
        ln = ln.strip()
        if ln.startswith("|"):
            ln = ln[1:]
        if ln.endswith("|"):
            ln = ln[:-1]
        rows.append([c.strip() for c in ln.split("|")])
    if not rows:
        return ""
    ncols = len(rows[0])
    colspec = "@{}" + "X" * ncols + "@{}"
    out = [
        r"\begin{table}[!htbp]",
        r"\centering\footnotesize",
        r"\begin{tabularx}{\linewidth}{" + colspec + "}",
        r"\toprule",
    ]
    header = rows[0]
    out.append(" & ".join(r"\textbf{" + inline_markdown_to_latex(h) + "}" for h in header) + r" \\")
    out.append(r"\midrule")
    for r in rows[1:]:
        while len(r) < ncols:
            r.append("")
        out.append(" & ".join(inline_markdown_to_latex(c) for c in r[:ncols]) + r" \\")
    out.append(r"\bottomrule")
    out.append(r"\end{tabularx}")
    out.append(r"\end{table}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Markdown → LaTeX body conversion
# ---------------------------------------------------------------------------

def md_to_body(md_text: str) -> str:
    """Convert Markdown to a LaTeX body (no preamble, no \\begin{document})."""
    lines = md_text.splitlines()
    out: list[str] = []
    i = 0
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append(r"\end{itemize}")
            in_list = False

    while i < len(lines):
        stripped = lines[i].rstrip()

        # Pipe-table detection
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(
            r"^\s*\|?\s*[-:| ]+\s*\|?\s*$", lines[i + 1]
        ):
            close_list()
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(convert_table(block))
            out.append("")
            continue

        # Horizontal rule
        if stripped == "---":
            close_list()
            out.append(r"\medskip\noindent\hrulefill")
            out.append("")
            i += 1
            continue

        # Heading
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            close_list()
            level = len(m.group(1))
            title = m.group(2).strip()
            if level == 1:
                out.append(r"\section*{" + inline_markdown_to_latex(title) + r"}")
            elif level == 2:
                out.append(r"\subsection*{" + inline_markdown_to_latex(title) + r"}")
            elif level == 3:
                out.append(r"\subsubsection*{" + inline_markdown_to_latex(title) + r"}")
            else:
                out.append(r"\paragraph{" + inline_markdown_to_latex(title) + r"}")
            out.append("")
            i += 1
            continue

        # Bullet
        if re.match(r"^\s*[-*]\s+", stripped):
            if not in_list:
                out.append(r"\begin{itemize}")
                in_list = True
            bullet_text = re.sub(r"^\s*[-*]\s+", "", stripped)
            out.append(r"  \item " + inline_markdown_to_latex(bullet_text))
            i += 1
            continue

        # Blank line
        if stripped == "":
            close_list()
            out.append("")
            i += 1
            continue

        # Regular paragraph
        close_list()
        out.append(inline_markdown_to_latex(stripped))
        i += 1

    close_list()
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Sources & citation injection
# ---------------------------------------------------------------------------

URL_RE = re.compile(r"(https?://[^\s)\]]+)")


def render_source_entry(src: str) -> str:
    """Render a source line, wrapping URLs in \\url{} for clean breaking."""
    out = []
    last = 0
    for m in URL_RE.finditer(src):
        if m.start() > last:
            out.append(inline_markdown_to_latex(src[last:m.start()]))
        url = m.group(1).rstrip(".,;)")
        out.append(r"\url{" + url + r"}")
        last = m.end() - (len(m.group(1)) - len(url))
    if last < len(src):
        out.append(inline_markdown_to_latex(src[last:]))
    return "".join(out)


def parse_sources(sources_path: Path) -> list[str]:
    """Extract bullet-listed source lines from a markdown file."""
    text = sources_path.read_text()
    return [ln.strip()[2:] for ln in text.splitlines() if ln.strip().startswith("- ")]


def extract_title(src_line: str) -> str | None:
    """Pull out the first italicized *title* from a source bullet."""
    m = re.search(r"\*([^*]+)\*", src_line)
    return m.group(1).strip() if m else None


def _title_variants(title: str) -> list[str]:
    """Return plausible short forms the body might use."""
    t = title.strip()
    variants = {t}
    for article in ("The ", "A ", "An "):
        if t.lower().startswith(article.lower()):
            variants.add(t[len(article):])
    for v in list(variants):
        for suffix in (" Report", " Guide", " (2025)", " (2024)", " (2026)"):
            if v.endswith(suffix):
                variants.add(v[: -len(suffix)])
    # combos
    for v in list(variants):
        for article in ("The ", "A ", "An "):
            if v.lower().startswith(article.lower()):
                rem = v[len(article):]
                for suffix in (" Report", " Guide"):
                    if rem.endswith(suffix):
                        variants.add(rem[: -len(suffix)])
    return sorted(variants, key=len, reverse=True)


def inject_footnotes(body: str, sources: list[str]) -> str:
    """Attach a \\footnote{...} to the first mention of each source in the body.

    Tries several forms (italicized, quoted, plain) so short forms still match.
    """
    for idx, src in enumerate(sources, start=1):
        title = extract_title(src)
        if not title:
            continue
        payload = render_source_entry(src)
        payload_safe = payload.replace("\\", r"\\")
        replacement = r"\1\\footnote{[" + str(idx) + r"] " + payload_safe + r"}"
        matched = False
        variants = _title_variants(title)
        # Tier 1: italics
        for variant in variants:
            pattern = re.compile(r"(\\textit\{" + re.escape(variant) + r"\})")
            body, n = pattern.subn(replacement, body, count=1)
            if n > 0:
                matched = True
                break
        if matched:
            continue
        # Tier 2: quoted forms
        for variant in variants:
            esc = re.escape(variant)
            pattern = re.compile(r"(``" + esc + r"''|\"" + esc + r"\")")
            body, n = pattern.subn(replacement, body, count=1)
            if n > 0:
                matched = True
                break
        if matched:
            continue
        # Tier 3: bare word-boundary match (only for titles long enough to be distinctive)
        for variant in variants:
            if len(variant) < 15:
                continue
            pattern = re.compile(r"(\b" + re.escape(variant) + r"\b)")
            body, n = pattern.subn(replacement, body, count=1)
            if n > 0:
                break
    return body


def build_references_section(sources: list[str]) -> str:
    refs = [
        r"\clearpage",
        r"\section*{References}",
        r"\footnotesize",
        r"\sloppy",
        "",
        r"\begin{enumerate}[label={[\arabic*]},leftmargin=1.6em,itemsep=0.5em]",
    ]
    for src in sources:
        refs.append(r"  \item " + render_source_entry(src))
    refs.append(r"\end{enumerate}")
    return "\n".join(refs)


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------

def build_document(
    md_text: str,
    *,
    title: str,
    author: str,
    date: str,
    header_left: str,
    header_right: str,
    sources: list[str],
    include_references: bool,
    preamble_relpath: str,
) -> str:
    body = md_to_body(md_text)
    if sources:
        body = inject_footnotes(body, sources)
    if sources and include_references:
        body = body + "\n\n" + build_references_section(sources)

    def esc_arg(s: str) -> str:
        return latex_escape(s)

    header = [
        r"% Auto-generated by md_to_tex.py",
        r"\input{" + preamble_relpath + "}",
        r"\newcommand{\briefingtitle}{" + esc_arg(header_left) + "}",
        r"\newcommand{\transcriptnum}{" + esc_arg(header_right) + "}",
        r"\title{" + esc_arg(title) + "}",
        r"\author{" + esc_arg(author) + "}",
        r"\date{" + esc_arg(date) + "}",
        r"\begin{document}",
        r"\maketitle",
        r"\thispagestyle{plain}",
        "",
    ]
    footer = ["", r"\end{document}", ""]
    return "\n".join(header) + body + "\n" + "\n".join(footer)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=Path, help="Input markdown file")
    parser.add_argument("output", type=Path, help="Output LaTeX file")
    parser.add_argument("--title", required=True)
    parser.add_argument("--author", default="")
    parser.add_argument("--date", default="")
    parser.add_argument("--header-left", default="", help="Running-header left text")
    parser.add_argument("--header-right", default="", help="Running-header right text")
    parser.add_argument("--sources", type=Path, help="Markdown file with a bulleted list of sources")
    parser.add_argument(
        "--no-references", action="store_true",
        help="Don't append a References section even if --sources is given "
             "(footnotes will still be injected)",
    )
    parser.add_argument(
        "--preamble", default="remarkable-preamble.tex",
        help="Path (relative to the output dir) to remarkable-preamble.tex. "
             "Default assumes it sits alongside the output file.",
    )
    args = parser.parse_args(argv)

    md_text = args.input.read_text()
    sources = parse_sources(args.sources) if args.sources else []

    doc = build_document(
        md_text,
        title=args.title,
        author=args.author,
        date=args.date,
        header_left=args.header_left or args.title,
        header_right=args.header_right,
        sources=sources,
        include_references=not args.no_references,
        preamble_relpath=args.preamble,
    )
    args.output.write_text(doc)
    print(f"wrote {args.output} ({len(doc)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
