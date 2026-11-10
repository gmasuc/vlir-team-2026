"""
Convierte uno o más informes Markdown en un solo PDF con las figuras incrustadas (no dependen de archivos externos).

Proceso: Markdown -> HTML (tablas, código) con cada imagen local convertida a base64 -> PDF con Microsoft Edge sin
ventana (--headless --print-to-pdf). El primer archivo va en A4 vertical; los siguientes (anexos), en A4 horizontal,
porque sus tablas son anchas.

Uso:  py analisis/informe/md_a_pdf.py salida.pdf informe.md [anexo.md ...]
      p. ej.  py analisis/informe/md_a_pdf.py informe_tecnico_simulacion.pdf informe_tecnico_simulacion.md anexo_A_catalogo_corridas.md
      (rutas relativas a analisis/informe/)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import base64
import re
import subprocess
import sys
from pathlib import Path

import markdown

AQUI = Path(__file__).resolve().parent
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

CSS = """
@page { size: A4; margin: 18mm 16mm; }
@page anexo { size: A4 landscape; margin: 12mm 12mm; }
body { font-family: "Segoe UI", Calibri, Arial, sans-serif; font-size: 10pt; line-height: 1.4; color: #1a1a1a; }
h1 { font-size: 17pt; color: #12355b; margin: 0 0 8pt; }
h2 { font-size: 13pt; color: #12355b; border-bottom: 1px solid #c8d3df; padding-bottom: 2pt; margin-top: 16pt;
     break-after: avoid; }
h3 { font-size: 11pt; color: #12355b; margin-top: 12pt; break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 8.5pt; break-inside: auto; }
th, td { border: 1px solid #c8d3df; padding: 3pt 5pt; vertical-align: top; text-align: left; }
th { background: #e8eef5; }
tr { break-inside: avoid; }
code { font-family: Consolas, monospace; font-size: 8.3pt; background: #f2f4f7; padding: 0 2pt; word-break: break-all; }
pre { background: #f2f4f7; padding: 6pt; font-size: 7.8pt; white-space: pre-wrap; word-break: break-all; }
pre code { background: none; padding: 0; }
img { max-width: 100%; max-height: 120mm; display: block; margin: 6pt auto 2pt; }
p img + em, em { color: #444; }
hr { border: 0; border-top: 1px solid #dde3ea; margin: 12pt 0; }
a { color: #1f5f99; text-decoration: none; }
.anexo { page: anexo; break-before: page; }
.anexo table { font-size: 7.3pt; }
.anexo td:nth-child(2) code { word-break: break-all; }
"""


def html_de(md_path):
    texto = md_path.read_text(encoding="utf-8")

    def incrustar(m):
        alt, ruta = m.group(1), m.group(2)
        f = (md_path.parent / ruta).resolve()
        if not f.exists():
            print(f"  falta la figura: {ruta}")
            return m.group(0)
        tipo = "png" if f.suffix.lower() == ".png" else "jpeg"
        return f"![{alt}](data:image/{tipo};base64,{base64.b64encode(f.read_bytes()).decode()})"

    texto = re.sub(r"!\[([^\]]*)\]\(([^)]+\.(?:png|jpg|jpeg))\)", incrustar, texto)
    # Python-Markdown exige una línea en blanco antes de una lista (GitHub no): se agrega
    lineas, previa = [], ""
    lista = re.compile(r"\s*([-*]|\d+\.)\s")
    for ln in texto.split("\n"):
        if lista.match(ln) and previa.strip() and not lista.match(previa) and not previa.lstrip().startswith("|"):
            lineas.append("")
        lineas.append(ln)
        previa = ln
    texto = "\n".join(lineas)
    # enlaces entre los informes del mismo PDF -> enlaces internos
    texto = re.sub(r"\]\((anexo_[^)#]+\.md)\)", lambda m: f"](#{Path(m.group(1)).stem})", texto)
    return markdown.markdown(texto, extensions=["tables", "fenced_code", "sane_lists", "nl2br"])


salida, archivos = AQUI / sys.argv[1], [AQUI / a for a in sys.argv[2:]]
salida.unlink(missing_ok=True)
partes = []
for i, f in enumerate(archivos):
    clase = "" if i == 0 else ' class="anexo"'
    partes.append(f'<section id="{f.stem}"{clase}>{html_de(f)}</section>')
html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{archivos[0].stem}</title>'
        f"<style>{CSS}</style></head><body>{''.join(partes)}</body></html>")
tmp = salida.with_suffix(".html")
tmp.write_text(html, encoding="utf-8")
import tempfile
perfil = tempfile.mkdtemp(prefix="edge_pdf_")             # perfil aparte: no choca con un Edge abierto
r = subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={perfil}",
                    "--virtual-time-budget=10000", f"--print-to-pdf={salida}", tmp.as_uri()],
                   capture_output=True, text=True, timeout=300)
import time                                                 # Edge puede volver antes de terminar de escribir el PDF
for _ in range(240):
    if salida.exists() and salida.stat().st_size > 0:
        time.sleep(2)
        break
    time.sleep(0.5)
tmp.unlink()
print(f"PDF: {salida} ({salida.stat().st_size / 1e6:.1f} MB)" if salida.exists() else f"falló Edge: {r.stderr[-500:]}")
