#!/usr/bin/env python3
"""
Playwright-Powered Markdown & Mermaid Documentation Compiler
============================================================
Compiles Markdown documents (with embedded Mermaid.js vector diagrams and GitHub-flavored
alerts) into pixel-perfect, standalone HTML files and high-resolution vector A4 PDFs.

Usage:
------
  python3 scripts/generate_docs_pdf.py
"""

import os
import sys
import tempfile
from playwright.sync_api import sync_playwright

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');
    
    @page {{
      size: A4;
      margin: 18mm 16mm 18mm 16mm;
      @bottom-right {{
        content: counter(page);
        font-family: 'Inter', sans-serif;
        font-size: 8pt;
        color: #94a3b8;
      }}
    }}

    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      color: #0f172a;
      line-height: 1.6;
      font-size: 10pt;
      margin: 0;
      padding: 0;
      background: #ffffff;
    }}

    h1 {{
      font-size: 20pt;
      font-weight: 800;
      color: #0f172a;
      border-bottom: 2px solid #2563eb;
      padding-bottom: 6px;
      margin-top: 0;
      margin-bottom: 12px;
    }}

    h2 {{
      font-size: 14pt;
      font-weight: 700;
      color: #1e293b;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 4px;
      margin-top: 20px;
      margin-bottom: 8px;
    }}

    h3 {{
      font-size: 11pt;
      font-weight: 600;
      color: #334155;
      margin-top: 14px;
      margin-bottom: 6px;
    }}

    p, li {{
      color: #334155;
      margin-bottom: 6px;
    }}

    code {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 8.5pt;
      background: #f1f5f9;
      color: #0f172a;
      padding: 2px 5px;
      border-radius: 4px;
      border: 1px solid #e2e8f0;
    }}

    pre {{
      background: #0f172a;
      color: #f8fafc;
      padding: 10px 14px;
      border-radius: 8px;
      overflow-x: auto;
      font-size: 8.5pt;
      margin: 10px 0;
    }}

    pre code {{
      background: transparent;
      color: inherit;
      border: none;
      padding: 0;
    }}

    blockquote {{
      border-left: 4px solid #3b82f6;
      background: #eff6ff;
      margin: 10px 0;
      padding: 8px 14px;
      border-radius: 0 6px 6px 0;
      color: #1e40af;
      font-size: 9.5pt;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 12px 0;
      font-size: 8.5pt;
    }}

    th {{
      background: #f8fafc;
      color: #1e293b;
      font-weight: 600;
      text-align: left;
      padding: 7px 10px;
      border: 1px solid #cbd5e1;
    }}

    td {{
      padding: 6px 10px;
      border: 1px solid #e2e8f0;
      color: #334155;
    }}

    tr:nth-child(even) {{
      background: #f8fafc;
    }}

    .mermaid {{
      display: flex;
      justify-content: center;
      margin: 14px 0;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 12px;
    }}

    img {{
      max-width: 100% !important;
      max-height: 185mm !important;
      width: auto !important;
      height: auto !important;
      display: block;
      margin: 12px auto !important;
      object-fit: contain !important;
      border-radius: 8px;
      page-break-inside: avoid !important;
      break-inside: avoid !important;
    }}

    details {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 10px 14px;
      margin: 12px 0;
      page-break-inside: avoid !important;
      break-inside: avoid !important;
    }}

    summary {{
      font-weight: 600;
      color: #3b82f6;
      cursor: pointer;
      font-size: 9pt;
    }}

    .mermaid, blockquote, table, pre {{
      page-break-inside: avoid !important;
      break-inside: avoid !important;
    }}

    hr {{
      border: none;
      border-top: 1px solid #e2e8f0;
      margin: 18px 0;
    }}
  </style>
</head>
<body>
  <div id="content"></div>
  <script>
    const markdownText = {raw_markdown_json};
    
    // Configure marked
    marked.setOptions({{
      gfm: true,
      breaks: true
    }});

    // Parse markdown
    const htmlContent = marked.parse(markdownText);
    document.getElementById('content').innerHTML = htmlContent;

    // Convert code blocks with language-mermaid to div.mermaid
    document.querySelectorAll('pre code.language-mermaid').forEach((block) => {{
      const pre = block.parentElement;
      const mermaidDiv = document.createElement('div');
      mermaidDiv.className = 'mermaid';
      mermaidDiv.textContent = block.textContent;
      pre.parentElement.replaceChild(mermaidDiv, pre);
    }});

    mermaid.initialize({{ 
      startOnLoad: true,
      theme: 'default',
      securityLevel: 'loose',
      fontFamily: 'Inter, sans-serif'
    }});
  </script>
</body>
</html>
"""

def compile_markdown_to_html_and_pdf(md_path: str, html_path: str, pdf_path: str, title: str = "LumièreShop Documentation"):
    if not os.path.exists(md_path):
        print(f"Error: {md_path} does not exist.")
        return False

    with open(md_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    import json
    html = HTML_TEMPLATE.format(
        title=title,
        raw_markdown_json=json.dumps(md_content)
    )

    with open(html_path, "w", encoding="utf-8") as f_html:
        f_html.write(html)
    print(f"✅ Successfully compiled HTML: {html_path}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
            page = browser.new_page()
            page.goto(f"file://{os.path.abspath(html_path)}", wait_until="networkidle")
            page.wait_for_timeout(2500)  # Wait for Mermaid to fully render SVG diagrams
            page.pdf(
                path=pdf_path,
                format="A4",
                print_background=True,
                margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"}
            )
            browser.close()
            print(f"✅ Successfully compiled PDF:  {pdf_path} ({os.path.getsize(pdf_path):,} bytes)")
            return True
    except Exception as e:
        print(f"❌ Error compiling PDF {pdf_path}: {e}")
        return False

if __name__ == "__main__":
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs_dir = os.path.join(repo, "docs")

    # A path given on the command line is used AS GIVEN. Previously only the
    # basename survived and was re-joined to docs/, so asking for
    # export/internal_playbook/CMO_LIVE_DEMO_PLAYBOOK.md silently looked for
    # docs/CMO_LIVE_DEMO_PLAYBOOK.md, failed, and still printed success.
    if len(sys.argv) > 1:
        targets = [os.path.abspath(a) for a in sys.argv[1:] if a.endswith(".md")]
    else:
        targets = [os.path.join(docs_dir, f)
                   for f in os.listdir(docs_dir) if f.endswith(".md")]

    print("=" * 80)
    print(f"Compiling {len(targets)} Documentation Markdown Files to HTML and PDF...")
    print("=" * 80)

    ok = failed = 0
    for md_p in sorted(targets):
        out_dir = os.path.dirname(md_p)
        base_name = os.path.splitext(os.path.basename(md_p))[0]
        html_p = os.path.join(out_dir, f"{base_name}.html")
        pdf_p = os.path.join(out_dir, f"{base_name}.pdf")
        doc_title = base_name.replace("_", " ").title()

        print(f"\nProcessing: {md_p} -> {base_name}.html & {base_name}.pdf")
        if not os.path.exists(md_p):
            print(f"❌ Missing: {md_p}")
            failed += 1
            continue
        result = compile_markdown_to_html_and_pdf(
            md_p, html_p, pdf_p, title=f"LumièreShop — {doc_title}")
        if result is False:
            failed += 1
        else:
            ok += 1

    print("\n" + "=" * 80)
    if failed:
        print(f"⚠️  {ok} compiled, {failed} FAILED")
        sys.exit(1)
    print(f"🎉 {ok} Documentation HTML & PDF Files Compiled Successfully!")
    print("=" * 80)

