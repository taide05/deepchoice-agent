"""Markdown -> PDF rendering for report export (xhtml2pdf, Windows/Docker-safe).

CJK rendering is best-effort: candidate system fonts are probe-loaded with
reportlab and registered via xhtml2pdf's DEFAULT_FONT (the @font-face path
breaks on Windows drive-letter URLs and temp-file locking). If none load,
the PDF falls back to helvetica and CJK glyphs degrade — the Markdown
export is the canonical format.
"""
from pathlib import Path

FONT_CANDIDATES = [
    # Plain TTFs first; .ttc needs reportlab's subfontIndex and must be
    # TrueType-outlined (NotoSansCJK is CFF-based — reportlab cannot open it)
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    # Linux / Docker (fonts-wqy-zenhei: TrueType-outlined TTC)
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
]

FAMILY = "DeepChoiceCJK"

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body {{ font-family: {font_family}; font-size: 10pt; color: #1a1a1a; line-height: 1.5; }}
    h1 {{ font-size: 16pt; border-bottom: 1px solid #ccc; padding-bottom: 4pt; }}
    h2 {{ font-size: 13pt; margin-top: 14pt; }}
    h3 {{ font-size: 11pt; margin-top: 10pt; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 8.5pt; margin: 8pt 0; }}
    th, td {{ border: 1px solid #ccc; padding: 4pt 6pt; text-align: left; }}
    th {{ background: #f0e8ff; }}
    blockquote {{ border-left: 3px solid #7c3aed; padding-left: 8pt; color: #555; margin-left: 0; }}
    code, pre {{ font-family: monospace; font-size: 8pt; background: #f5f5f5; }}
    sup a {{ text-decoration: none; color: #7c3aed; font-size: 7pt; }}
</style>
</head>
<body>{body}</body>
</html>"""

_registered: bool = False


def _register_cjk_font() -> str:
    """Probe candidates, register the first loadable one with xhtml2pdf. Returns family name."""
    global _registered
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from xhtml2pdf.default import DEFAULT_FONT

    if not _registered:
        for path in FONT_CANDIDATES:
            try:
                TTFont(FAMILY, str(path), subfontIndex=0)
            except Exception:
                continue
            try:
                pdfmetrics.getFont(FAMILY)
            except KeyError:
                pdfmetrics.registerFont(TTFont(FAMILY, str(path), subfontIndex=0))
            DEFAULT_FONT[FAMILY] = {
                "normal": str(path),
                "bold": str(path),
                "italic": str(path),
                "bolditalic": str(path),
            }
            _registered = True
            break
    return FAMILY if _registered else "helvetica"


def render_pdf(md: str) -> bytes:
    import markdown
    from xhtml2pdf import pisa

    font_family = _register_cjk_font()
    body = markdown.markdown(md, extensions=["tables"])
    html = HTML_TEMPLATE.format(font_family=font_family, body=body)

    from io import BytesIO

    buffer = BytesIO()
    status = pisa.CreatePDF(html, dest=buffer, encoding="utf-8")
    if status.err:
        raise RuntimeError(f"PDF generation failed: {status.err}")
    return buffer.getvalue()
