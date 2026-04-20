"""
PreviewWorker — background thread that generates HTML for the preview panel.
Each renderer returns an HTML string; the worker emits it to the panel.
"""
from __future__ import annotations
import os
import base64
import zipfile
import re
import logging
import xml.etree.ElementTree as ET
from typing import Callable, Any

logger = logging.getLogger(__name__)

try:
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext, layout as _dxf_layout, svg as ezdxf_svg
    _HAS_EZDXF = True
except Exception as _e:
    logger.warning("ezdxf not available: %s", _e)
    _HAS_EZDXF = False


# ── helpers ───────────────────────────────────────────────────────────────────

def _html_escape(text: str) -> str:
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))


_preview_font_size: int = 13  # module-level，由 generate_preview 在執行前設定


def _base_html(body: str, extra_head: str = "", font_size: int | None = None) -> str:
    if font_size is None:
        font_size = _preview_font_size
    code_size = max(9, font_size - 1)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{extra_head}
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #1e1e2e; color: #cdd6f4;
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: {font_size}px; line-height: 1.5;
    overflow-x: hidden;
  }}
  .info-card {{
    padding: 20px; display: flex; flex-direction: column; gap: 8px;
  }}
  .info-card .label {{
    color: #89b4fa; font-weight: 600; font-size: 11px;
    text-transform: uppercase; letter-spacing: .05em;
  }}
  .info-card .value {{ color: #cdd6f4; word-break: break-all; }}
  .info-card hr {{ border: none; border-top: 1px solid #313244; margin: 6px 0; }}
  pre {{
    padding: 12px; margin: 0;
    white-space: pre-wrap; word-break: break-all;
    font-family: 'Cascadia Code','Consolas','Courier New', monospace;
    font-size: {code_size}px; line-height: 1.6;
    background: #1e1e2e; color: #cdd6f4;
  }}
  table {{
    width: 100%; border-collapse: collapse; font-size: 12px;
  }}
  thead th {{
    background: #313244; color: #89b4fa;
    padding: 6px 10px; text-align: left;
    border-bottom: 1px solid #45475a;
    position: sticky; top: 0;
  }}
  tbody tr:nth-child(even) {{ background: #181825; }}
  tbody td {{
    padding: 5px 10px; border-bottom: 1px solid #313244;
    white-space: nowrap; max-width: 300px;
    overflow: hidden; text-overflow: ellipsis;
  }}
  img.preview {{ max-width: 100%; max-height: 100vh; display: block; margin: auto; }}
  .err {{ padding: 20px; color: #f38ba8; }}
  .badge-row {{ display: flex; gap: 10px; flex-wrap: wrap; padding: 20px; }}
  .badge {{
    background: #313244; border-radius: 6px;
    padding: 10px 14px; display: flex; flex-direction: column; gap: 4px;
  }}
  .badge .bk {{ color: #89b4fa; font-size: 11px; text-transform: uppercase; }}
  .badge .bv {{ font-size: 18px; font-weight: 700; color: #a6e3a1; }}
  .badge .bu {{ font-size: 11px; color: #6c7086; }}
  .load-btn {{
    display: inline-block; margin: 20px;
    padding: 10px 22px; background: #89b4fa; color: #1e1e2e;
    border: none; border-radius: 6px; font-size: 13px; cursor: pointer;
    font-weight: 600;
  }}
  .load-btn:hover {{ background: #b4d0f7; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ── file-type maps ─────────────────────────────────────────────────────────────

TEXT_EXTS = {
    ".py", ".pyw", ".pyi",
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".html", ".htm", ".xml", ".xhtml", ".svg",
    ".css", ".scss", ".sass", ".less",
    ".json", ".jsonc", ".json5",
    ".toml", ".yaml", ".yml",
    ".md", ".markdown", ".rst", ".txt",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".java", ".go", ".rs",
    ".rb", ".php", ".lua", ".r", ".m", ".swift", ".kt",
    ".log", ".ini", ".cfg", ".conf", ".env",
    ".dockerfile", ".makefile", ".cmake",
    ".sql", ".graphql",
    ".csv",         # handled by table renderer if openpyxl present; fallback here
}

TABLE_EXTS = {".csv", ".xlsx", ".xls"}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp",
              ".gif", ".webp", ".ico", ".tiff", ".tif"}

PDF_EXTS = {".pdf", ".ai"}

STL_EXTS = {".stl", ".obj", ".ply"}

ARCHIVE_EXTS = {".zip", ".7z"}


# ── renderers ─────────────────────────────────────────────────────────────────

def render_unknown(path: str) -> str:
    stat = os.stat(path)
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1] or "(無副檔名)"
    body = f"""<div class="info-card">
  <div class="label">檔案名稱</div><div class="value">{_html_escape(name)}</div>
  <hr>
  <div class="label">類型</div><div class="value">{_html_escape(ext)}</div>
  <hr>
  <div class="label">大小</div><div class="value">{_fmt_size(stat.st_size)}</div>
  <hr>
  <div class="label">路徑</div><div class="value">{_html_escape(path)}</div>
  <hr>
  <div class="label">說明</div><div class="value" style="color:#6c7086">此格式無預覽支援</div>
</div>"""
    return _base_html(body)


def render_unsupported_office(path: str, ext: str) -> str:
    """Friendly message for old binary .doc / .ppt formats."""
    name = os.path.basename(path)
    body = f"""<div class="info-card" style="border-left: 4px solid #f38ba8;">
  <div class="label">檔案名稱</div><div class="value">{_html_escape(name)}</div>
  <hr>
  <div class="label">預覽限制</div>
  <div class="value" style="color:#f38ba8; font-weight:bold;">⚠️ 不支援舊版二進位格式 ({ext})</div>
  <div class="value" style="color:#6c7086; font-size:11px; margin-top:4px;">
    為了保持系統極速效能，目前僅支援 OpenXML 格式 (.docx, .pptx, .xlsx)。<br>
    請將檔案另存為新版格式後再行預覽。
  </div>
</div>"""
    return _base_html(body)


def render_cloud_placeholder(path: str) -> str:
    """Friendly message for offline cloud files to prevent auto-download."""
    name = os.path.basename(path)
    body = f"""<div class="info-card" style="border-left: 4px solid #3498db; text-align: center; padding: 40px 20px;">
  <div style="font-size: 48px; margin-bottom: 20px;">⛅</div>
  <div class="label" style="font-size: 16px; color: #cdd6f4; margin-bottom: 10px;">雲端檔案 (未下載)</div>
  <div class="value" style="color: #6c7086; font-size: 13px; line-height: 1.6;">
    檔案路徑: {_html_escape(name)}<br><br>
    此檔案目前僅存在於雲端。<br>
    為了節省流量與防止介面卡頓，系統已攔截自動下載。<br>
  </div>
  <div style="margin-top: 30px;">
    <a href="fspath:{_html_escape(os.path.abspath(path))}" 
       style="background: #3498db; color: white; padding: 10px 24px; border-radius: 20px; text-decoration: none; font-weight: bold; font-size: 13px; box-shadow: 0 4px 15px rgba(52,152,219,0.3);">
       ⬇️ 下載並預覽內容
    </a>
  </div>
  <div style="color: #585b70; font-size: 11px; margin-top: 15px;">或者直接雙擊檔案以使用系統預設程式開啟</div>
</div>"""
    return _base_html(body)


def render_office_docx(path: str, max_lines: int = 100) -> str:
    """Fast DOCX text extraction via OpenXML ZIP + XML parsing."""
    try:
        with zipfile.ZipFile(path, 'r') as docx:
            if 'word/document.xml' not in docx.namelist():
                return _base_html('<div class="err">無效的 Word 文件結構</div>')
            
            xml_content = docx.read('word/document.xml')
            tree = ET.fromstring(xml_content)
            
            # OpenXML Namespace
            W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            PARA = W_NS + 'p'
            TEXT = W_NS + 't'

            lines = []
            for p in tree.iter(PARA):
                # Join all text pieces in this paragraph
                t_parts = [node.text for node in p.iter(TEXT) if node.text]
                if t_parts:
                    lines.append("".join(t_parts))
                else:
                    lines.append("") # Empty paragraph (newline)
                
                if len(lines) >= max_lines:
                    lines.append("... (檔案過長，已截斷預覽) ...")
                    break
            
            content = "\n".join(lines)
            body = f"""
            <div style="background-color: #f3f2f1; padding: 25px; border-left: 5px solid #2b579a; min-height: 100vh;">
                <div style="background: white; padding: 40px; box-shadow: 0 4px 15px rgba(0,0,0,0.15); border-radius: 4px; color: #333;">
                    <h2 style="color: #2b579a; border-bottom: 1px solid #eee; padding-bottom: 10px; margin-bottom: 20px; font-size: 18px;">📄 文件內容預覽</h2>
                    <pre style="background: white; color: #333; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; line-height: 1.8; padding: 0;">{_html_escape(content)}</pre>
                </div>
            </div>
            """
            return _base_html(body)
    except Exception as e:
        return _base_html(f'<div class="err">無法解析 DOCX: {_html_escape(str(e))}</div>')


def render_office_pptx(path: str) -> str:
    """Extract text from PPTX slides with proper numerical sorting."""
    try:
        with zipfile.ZipFile(path, 'r') as pptx:
            names = pptx.namelist()
            # Find and sort slides numerically: slide1.xml, slide2.xml, slide10.xml
            slide_files = [n for n in names if re.match(r'ppt/slides/slide\d+\.xml', n)]
            if not slide_files:
                return _base_html('<div class="err">此簡報無任何投影片內容</div>')
            
            slide_files.sort(key=lambda x: int(re.search(r'slide(\d+)\.xml', x).group(1)))
            
            A_NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
            TEXT = A_NS + 't'
            
            slides_html = []
            for i, f in enumerate(slide_files):
                xml_data = pptx.read(f)
                tree = ET.fromstring(xml_data)
                texts = [node.text for node in tree.iter(TEXT) if node.text]
                
                if texts:
                    slide_content = _html_escape(" ".join(texts))
                    slides_html.append(f"""
                    <div style="margin-bottom: 20px; padding: 15px; border-bottom: 1px dashed #ccc;">
                        <div style="color: #666; font-size: 11px; margin-bottom: 5px;">Slide {i+1}</div>
                        <div style="font-size: 14px; line-height: 1.5; color: #222;">{slide_content}</div>
                    </div>
                    """)

            body = f"""
            <div style="background-color: #f3f2f1; padding: 25px; border-left: 5px solid #b7472a; min-height: 100vh;">
                <div style="background: white; padding: 30px; box-shadow: 0 4px 15px rgba(0,0,0,0.15); border-radius: 4px; color: #333;">
                    <h2 style="color: #b7472a; border-bottom: 1px solid #eee; padding-bottom: 10px; margin-bottom: 20px; font-size: 18px;">📊 投影片文字大綱</h2>
                    {''.join(slides_html)}
                </div>
            </div>
            """
            return _base_html(body)
    except Exception as e:
        return _base_html(f'<div class="err">無法解析 PPTX: {_html_escape(str(e))}</div>')


def render_text(path: str, max_lines: int = 1000) -> str:
    """Plain text / source code — plain <pre> for Phase 1; Highlight.js added in Phase 2a."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    lines.append(f"\n… (只顯示前 {max_lines} 行)")
                    break
                lines.append(line)
        content = _html_escape("".join(lines))
    except Exception as e:
        return _base_html(f'<div class="err">無法讀取: {_html_escape(str(e))}</div>')

    ext = os.path.splitext(path)[1].lower().lstrip(".")
    # Highlight.js language hint
    lang_map = {
        "py": "python", "pyw": "python", "pyi": "python",
        "js": "javascript", "mjs": "javascript", "ts": "typescript",
        "jsx": "javascript", "tsx": "typescript",
        "html": "html", "htm": "html", "xml": "xml", "svg": "xml",
        "css": "css", "scss": "scss", "json": "json", "jsonc": "json",
        "toml": "toml", "yaml": "yaml", "yml": "yaml",
        "md": "markdown", "sh": "bash", "bash": "bash",
        "ps1": "powershell", "bat": "bat",
        "c": "c", "cpp": "cpp", "h": "cpp", "hpp": "cpp",
        "cs": "csharp", "java": "java", "go": "go", "rs": "rust",
        "rb": "ruby", "php": "php", "lua": "lua", "r": "r",
        "sql": "sql", "log": "accesslog",
    }
    lang = lang_map.get(ext, "plaintext")

    # Highlight.js via CDN (graceful fallback if offline)
    hljs_head = """
<link rel="stylesheet"
  href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script>
  document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('pre code').forEach(function(el) {
      hljs.highlightElement(el);
    });
  });
</script>
"""
    body = f'<pre><code class="language-{lang}">{content}</code></pre>'
    return _base_html(body, extra_head=hljs_head)


def render_image(path: str) -> str:
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif",
                "bmp": "bmp", "webp": "webp", "ico": "x-icon",
                "tiff": "tiff", "tif": "tiff", "svg": "svg+xml"}.get(ext, "octet-stream")
        body = f'<img class="preview" src="data:image/{mime};base64,{data}" alt="">'
    except Exception as e:
        body = f'<div class="err">無法載入圖片: {_html_escape(str(e))}</div>'
    return _base_html(body)


def render_pdf(path: str, max_pages: int = 3, dpi_scale: float = 1.2) -> str:
    """
    極速 PDF 預覽：寬度優先、帶有實體紙張質感的 HTML 渲染。
    max_pages: 最多渲染頁數，由呼叫端傳入（預設 3）。
    dpi_scale: 縮放倍率，SD=1.2, HD=2.5。
    """
    try:
        import fitz  # PyMuPDF
        import base64
        import time
        import os
        
        start_time = time.time()
        abs_path = os.path.abspath(path)
        logger.debug(f"[PDF Start] Attempting to open: {abs_path}")

        if not os.path.exists(abs_path):
            logger.error(f"File does not exist: {abs_path}")
            return _base_html(f'<div class="err">檔案不存在: {path}</div>')

        doc = fitz.open(abs_path)
        total_pages = doc.page_count
        is_encrypted = doc.is_encrypted

        logger.debug(f"[PDF Info] Pages: {total_pages}, Encrypted: {is_encrypted}")
        
        if is_encrypted:
            doc.close()
            return _base_html('<div class="err">此檔案已加密或受保護，無法預覽。請按 Enter 開啟。</div>')

        if total_pages == 0:
            doc.close()
            return _base_html('<div class="err">此 PDF 無任何頁面內容。</div>')

        limit = min(max_pages, total_pages)
        file_size_str = _fmt_size(os.path.getsize(abs_path))
        
        html_parts = [
            "<style>",
            "  body { background-color: transparent !important; margin: 0; padding: 0; overflow-x: hidden; }",
            "  .pdf-info-badge { position: sticky; top: 10px; z-index: 100; margin: 0 auto; padding: 6px 16px; ",
            "                    background-color: rgba(30, 31, 41, 0.85); color: #cdd6f4; border-radius: 20px; ",
            "                    width: fit-content; font-size: 11px; box-shadow: 0 4px 15px rgba(0,0,0,0.4); ",
            "                    backdrop-filter: blur(5px); border: 1px solid rgba(255,255,255,0.1); text-align: center; ",
            "                    display: flex; align-items: center; gap: 10px; }",
            "  .open-btn { display: inline-block; padding: 3px 10px; background: rgba(88,166,255,0.25); ",
            "              color: #89b4fa; border-radius: 12px; text-decoration: none; font-size: 11px; ",
            "              border: 1px solid rgba(88,166,255,0.4); cursor: pointer; white-space: nowrap; }",
            "  .open-btn:hover { background: rgba(88,166,255,0.45); color: #ffffff; }",
            "  .page-adj { display:inline-block; padding:1px 7px; color:#89b4fa; text-decoration:none; font-size:15px; cursor:pointer; border-radius:8px; line-height:1; }",
            "  .page-adj:hover { background: rgba(88,166,255,0.3); }",
            "  .page-count { min-width:32px; text-align:center; display:inline-block; }",
            "  .pdf-page { width: 95%; max-width: 900px; height: auto; display: block; margin: 15px auto 20px auto; background-color: white; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4); border-radius: 2px; }",
            "</style>"
        ]

        # 2. 顯示檔案資訊橫幅 (置頂) + 頁數調整 + 開啟按鈕
        info_line = f"📄 {total_pages} 頁 | {file_size_str}"
        pdf_icon_svg = (
            '<svg width="14" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="margin-right:6px;">'
            '<path d="M4 4C4 2.89543 4.89543 2 6 2H14L20 8V20C20 21.1046 19.1046 22 18 22H6C4.89543 22 4 21.1046 4 20V4Z" fill="#E53935"/>'
            '<path d="M14 2V8H20L14 2Z" fill="#B71C1C"/>'
            '<text x="12" y="17" fill="white" font-size="7" font-family="Arial, sans-serif" font-weight="900" text-anchor="middle">PDF</text>'
            '</svg>'
        )
        pages_ctrl = (
            f'<a class="page-adj" href="app://pages-dec">‹</a>'
            f'<span class="page-count">{max_pages} 頁</span>'
            f'<a class="page-adj" href="app://pages-inc">›</a>'
        )
        open_btn = f'<a class="open-btn" href="app://open" style="display:inline-flex;align-items:center;">{pdf_icon_svg}開啟</a>'
        html_parts.append(f'<div style="width:100%; height:0; overflow:visible; position:relative; z-index:1000;"><div class="pdf-info-badge"><span>{info_line}</span>{pages_ctrl}{open_btn}</div></div>')

        # 3. 迴圈渲染頁面
        rendered_count = 0
        for i in range(limit):
            try:
                page = doc.load_page(i)
                mat = fitz.Matrix(dpi_scale, dpi_scale) 
                pix = page.get_pixmap(matrix=mat, alpha=False)
                quality = 90 if dpi_scale > 2.0 else 75
                img_data = pix.tobytes("jpeg", jpg_quality=quality)
                b64_str = base64.b64encode(img_data).decode("utf-8")
                html_parts.append(f'<img class="pdf-page" src="data:image/jpeg;base64,{b64_str}" alt="Page {i+1}">')
                rendered_count += 1
            except Exception as pe:
                logger.warning(f"Failed to render page {i}: {pe}")

        doc.close()
        final_html = _base_html("".join(html_parts))
        elapsed = time.time() - start_time
        logger.debug(f"[PDF End] Rendered {rendered_count} pages in {elapsed:.3f}s. HTML Size: {len(final_html)/1024:.1f} KB")

        return final_html

    except ImportError:
        logger.error("PyMuPDF (fitz) not found.")
        return _base_html('<div class="err">需要 PyMuPDF 套件以預覽 PDF</div>')
    except Exception as e:
        logger.exception(f"PDF Render Crash: {e}")
        return _base_html(f'<div class="err">PDF 預覽發生嚴重錯誤: {_html_escape(str(e))}</div>')

def render_table_csv(path: str, max_rows: int = 15) -> str:
    import csv
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f)
            rows = [row for i, row in enumerate(reader) if i <= max_rows]
    except Exception as e:
        logger.error(f"CSV Render Fail: {e}")
        return _base_html(f'<div class="err">無法讀取 CSV: {_html_escape(str(e))}</div>')

    if not rows:
        return _base_html('<div class="err">空白 CSV 檔</div>')

    header = rows[0]
    data = rows[1:max_rows + 1]
    th = "".join(f"<th>{_html_escape(str(c))}</th>" for c in header)
    body_rows = "".join(
        "<tr>" +
        "".join(f"<td>{_html_escape(str(c))}</td>" for c in row) + "</tr>"
        for row in data
    )
    total = sum(1 for _ in open(path, encoding="utf-8", errors="replace")) - 1
    note = f" <span style='color:#6c7086'>（共 {total} 行，顯示前 {min(max_rows, total)} 行）</span>" if total > max_rows else ""
    body = f"<p style='padding:8px 10px;color:#89b4fa;font-size:11px'>{_html_escape(os.path.basename(path))}{note}</p><table><thead><tr>{th}</tr></thead><tbody>{body_rows}</tbody></table>"
    return _base_html(body)


def render_table_xlsx(path: str, max_rows: int = 15) -> str:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i > max_rows:
                break
            rows.append(row)
        wb.close()
    except ImportError:
        return _base_html('<div class="err">需要 openpyxl 套件 (<code>pip install openpyxl</code>)</div>')
    except Exception as e:
        return _base_html(f'<div class="err">無法讀取 xlsx: {_html_escape(str(e))}</div>')

    if not rows:
        return _base_html('<div class="err">空白工作表</div>')

    header = rows[0]
    data = rows[1:max_rows + 1]
    th = "".join(
        f"<th>{_html_escape(str(c) if c is not None else '')}</th>" for c in header)
    body_rows = "".join(
        "<tr>" +
        "".join(
            f"<td>{_html_escape(str(c) if c is not None else '')}</td>" for c in row) + "</tr>"
        for row in data
    )
    body = f"<table><thead><tr>{th}</tr></thead><tbody>{body_rows}</tbody></table>"
    return _base_html(body)


def render_archive(path: str, max_items: int = 200) -> str:
    """Fast archive listing via zipfile (native) or py7zr (if present)."""
    import datetime
    try:
        file_list = []
        total_files = 0
        ext = os.path.splitext(path)[1].lower()

        if ext == '.zip':
            with zipfile.ZipFile(path, 'r') as zf:
                infos = zf.infolist()
                total_files = len(infos)
                for info in infos[:max_items]:
                    file_list.append({
                        "name": info.filename,
                        "size": info.file_size,
                        "is_dir": info.is_dir()
                    })
        elif ext == '.7z':
            try:
                import py7zr
                with py7zr.SevenZipFile(path, 'r') as szf:
                    infos = szf.list()
                    total_files = len(infos)
                    for info in infos[:max_items]:
                        file_list.append({
                            "name": info.filename,
                            "size": info.uncompressed,
                            "is_dir": info.is_directory
                        })
            except ImportError:
                return _base_html('<div class="err">需要 <code>py7zr</code> 套件以預覽 7z 檔<br><small>請執行 pip install py7zr</small></div>')
        else:
            return render_unknown(path)

        # 組合 HTML UI
        filename = os.path.basename(path)
        badge_note = f" (前 {max_items} 個項目)" if total_files > max_items else ""
        
        rows = []
        for item in file_list:
            icon = "📁" if item['is_dir'] else "📄"
            color = "#89b4fa" if item['is_dir'] else "#cdd6f4"
            size_str = _fmt_size(item['size']) if item['size'] > 0 else "-"
            rows.append(f"""
            <tr>
                <td style="color: {color};">{icon} {_html_escape(item['name'])}</td>
                <td style="text-align: right; color: #a6e3a1;">{size_str}</td>
            </tr>
            """)

        body = f"""
        <div class="info-card" style="padding-bottom: 5px;">
            <div class="label">📦 壓縮檔內容</div>
            <div class="value" style="font-size: 16px; font-weight: bold;">{_html_escape(filename)}</div>
            <div class="value" style="font-size: 11px; color: #6c7086;">共 {total_files} 個項目{badge_note}</div>
        </div>
        <div style="padding: 0 10px 20px;">
            <table>
                <thead>
                    <tr>
                        <th style="padding-left: 10px;">名稱</th>
                        <th style="text-align: right; padding-right: 10px;">原始大小</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
            {f'<div style="text-align:center; padding:15px; color:#585b70; font-size:11px; font-style:italic;">... 還有 {total_files - max_items} 個項目未顯示 ...</div>' if total_files > max_items else ""}
        </div>
        """
        return _base_html(body)

    except Exception as e:
        return _base_html(f'<div class="err">無法預覽壓縮檔: {_html_escape(str(e))}</div>')


def render_stl(path: str) -> str:
    """Render STL/OBJ/PLY with trimesh metadata (no PyVista thumbnail)."""
    # ── Phase A: trimesh metadata ─────────────────────────────────────────────
    meta_html = ""
    try:
        import trimesh
        mesh = trimesh.load(path, force="mesh")
        n_faces = len(mesh.faces) if hasattr(mesh, "faces") else 0
        n_verts = len(mesh.vertices) if hasattr(mesh, "vertices") else 0
        is_closed = mesh.is_watertight if hasattr(
            mesh, "is_watertight") else False
        bb = mesh.bounding_box.extents
        vol = abs(float(mesh.volume))
        meta_html = f"""<div class="badge-row">
  <div class="badge">
    <span class="bk">長 (X)</span>
    <span class="bv">{bb[0]:.3f}</span>
    <span class="bu">mm</span>
  </div>
  <div class="badge">
    <span class="bk">寬 (Y)</span>
    <span class="bv">{bb[1]:.3f}</span>
    <span class="bu">mm</span>
  </div>
  <div class="badge">
    <span class="bk">高 (Z)</span>
    <span class="bv">{bb[2]:.3f}</span>
    <span class="bu">mm</span>
  </div>
  <div class="badge">
    <span class="bk">體積</span>
    <span class="bv">{vol:.2f}</span>
    <span class="bu">mm³</span>
  </div>
</div>
<div class="info-card">
  <div class="label">面數</div><div class="value">{n_faces:,}</div>
  <hr>
  <div class="label">頂點數</div><div class="value">{n_verts:,}</div>
  <hr>
  <div class="label">封閉實體</div><div class="value">{'是' if is_closed else '否'}</div>
</div>"""
    except ImportError:
        meta_html = '<div class="err">需要 trimesh 套件 (<code>pip install trimesh</code>)</div>'
    except Exception as e:
        meta_html = f'<div class="err">無法解析幾何資料: {_html_escape(str(e))}</div>'

    # ── Phase C: assemble ─────────────────────────────────────────────────────
    return _base_html(meta_html)


# ── DXF renderer ──────────────────────────────────────────────────────────────

def render_dxf(path: str) -> str:
    if not _HAS_EZDXF:
        return _base_html(
            '<div class="info-card">'
            '<span class="label">⚠️ 尚未安裝 ezdxf 模組</span>'
            '<span class="value">請執行：<code>pip install ezdxf</code> 以啟用 DXF 預覽</span>'
            '</div>'
        )
    try:
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()
        backend = ezdxf_svg.SVGBackend()
        Frontend(RenderContext(doc), backend).draw_layout(msp)
        svg_str = backend.get_string(_dxf_layout.Page(0, 0))
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<style>'
            'body{background:#1e1e2e;margin:0;display:flex;justify-content:center;align-items:center;min-height:100vh;}'
            '.c{background:white;padding:10px;border-radius:4px;width:95vw;height:95vh;'
            'display:flex;justify-content:center;align-items:center;box-sizing:border-box;}'
            'svg{max-width:100%;max-height:100%;object-fit:contain;}'
            '</style></head>'
            f'<body><div class="c">{svg_str}</div></body></html>'
        )
    except ezdxf.DXFStructureError:
        return _base_html('<div class="info-card"><span class="label" style="color:#ff5555">❌ DXF 解析失敗：檔案結構損毀或格式不支援</span></div>')
    except Exception as e:
        logger.warning("render_dxf failed: %s", e)
        return render_unknown(path)


# ── main dispatcher ────────────────────────────────────────────────────────────

def generate_preview(path: str, pdf_max_pages: int = 3, font_size: int = 13, pdf_dpi: float = 1.2) -> tuple[str, str]:
    """
    Dispatch to the correct renderer.
    Always returns (html, "").
    pdf_max_pages: passed through to render_pdf, avoiding disk I/O inside worker.
    font_size: sets module-level _preview_font_size so all renderers use it.
    pdf_dpi: PDF 渲染縮放倍率。
    """
    global _preview_font_size
    _preview_font_size = font_size
    if not os.path.isfile(path):
        return _base_html('<div class="err">非檔案或路徑不存在</div>'), ""

    # 1. Cloud Check: Prevent blocking hydrate on UI/Worker threads
    try:
        from core.file_ops import FileOps
        if FileOps.is_offline_cloud_file(path):
            return render_cloud_placeholder(path), ""
    except ImportError:
        pass

    ext = os.path.splitext(path)[1].lower()

    if ext in IMAGE_EXTS:
        html = render_image(path)
    elif ext in PDF_EXTS:
        html = render_pdf(path, max_pages=pdf_max_pages, dpi_scale=pdf_dpi)
    elif ext in ARCHIVE_EXTS:
        html = render_archive(path)
    elif ext in STL_EXTS:
        html = render_stl(path)
    elif ext == ".dxf":
        html = render_dxf(path)
    elif ext in {".xlsx", ".xls"}:
        html = render_table_xlsx(path)
    elif ext == ".docx":
        html = render_office_docx(path)
    elif ext == ".pptx":
        html = render_office_pptx(path)
    elif ext in {".doc", ".ppt"}:
        html = render_unsupported_office(path, ext)
    elif ext in {".csv"}:
        html = render_table_csv(path)
    elif ext in TEXT_EXTS:
        html = render_text(path)
    else:
        # UTF-8 sniff
        try:
            with open(path, "rb") as f:
                f.read(512).decode("utf-8")
            html = render_text(path)
        except Exception:
            html = render_unknown(path)

    return html, ""


def generate_html(path: str) -> str:
    """Backwards-compatible wrapper — returns html only (no base_dir)."""
    html, _ = generate_preview(path)
    return html
