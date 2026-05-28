import os
import tempfile
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_registered = False

def _register():
    global _registered
    if _registered:
        return
    # Все возможные пути к DejaVu на разных системах
    reg_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    bold_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    reg  = next((p for p in reg_paths  if os.path.exists(p)), None)
    bold = next((p for p in bold_paths if os.path.exists(p)), None)

    if not reg:
        # Последний шанс — найти через find
        import subprocess
        result = subprocess.run(['find', '/usr/share/fonts', '-name', 'DejaVuSans.ttf'],
                                capture_output=True, text=True)
        found = result.stdout.strip().split('\n')
        reg = found[0] if found and found[0] else None

    if not reg:
        raise RuntimeError("DejaVu font not found. Run: apt-get install fonts-dejavu-core")

    print(f"[PDF] Регистрирую шрифт: {reg}")
    pdfmetrics.registerFont(TTFont("DV",   reg))
    pdfmetrics.registerFont(TTFont("DV-B", bold or reg))
    _registered = True


def generate_pdf_report(title: str, name: str, content: str, filename: str) -> str:
    _register()

    PURPLE = colors.HexColor("#5b21b6")
    LILAC  = colors.HexColor("#ede9fe")
    GOLD   = colors.HexColor("#c9a96e")
    DARK   = colors.HexColor("#1e1033")
    GRAY   = colors.HexColor("#6b7280")

    st_title = ParagraphStyle("tt", fontSize=22, textColor=PURPLE, alignment=TA_CENTER, fontName="DV-B", spaceAfter=6)
    st_sub   = ParagraphStyle("ss", fontSize=13, textColor=GOLD,   alignment=TA_CENTER, fontName="DV",   spaceAfter=4)
    st_meta  = ParagraphStyle("mm", fontSize=10, textColor=GRAY,   alignment=TA_CENTER, fontName="DV",   spaceAfter=2)
    st_head  = ParagraphStyle("hh", fontSize=14, textColor=PURPLE, fontName="DV-B", spaceBefore=14, spaceAfter=6)
    st_body  = ParagraphStyle("bb", fontSize=11, textColor=DARK,   fontName="DV",   leading=17, spaceAfter=8, alignment=TA_LEFT)
    st_foot  = ParagraphStyle("ff", fontSize=9,  textColor=GRAY,   fontName="DV",   alignment=TA_CENTER)

    doc = SimpleDocTemplate(filename, pagesize=A4,
                            rightMargin=2.5*cm, leftMargin=2.5*cm,
                            topMargin=2.5*cm, bottomMargin=2.5*cm)
    story = [
        Spacer(1, 0.5*cm),
        Paragraph("СЕЛЕНА", st_title),
        Paragraph("Психолог . Нумеролог . Астролог", st_sub),
        HRFlowable(width="100%", thickness=1, color=GOLD, spaceAfter=10),
        Paragraph(title, st_head),
        Paragraph(f"Составлено для: {name}", st_body),
        Paragraph(f"Дата: {datetime.now().strftime('%d.%m.%Y')}", st_meta),
        Spacer(1, 0.4*cm),
        HRFlowable(width="100%", thickness=0.5, color=LILAC, spaceAfter=14),
    ]

    for p in content.split("\n"):
        p = p.strip()
        if not p:
            story.append(Spacer(1, 0.2*cm))
        elif p.startswith("#") or (p.startswith("**") and p.endswith("**")) or (p.isupper() and len(p) < 60):
            story.append(Paragraph(p.lstrip("#").strip("*").strip(), st_head))
        else:
            story.append(Paragraph(p.replace("**","").replace("*","").replace("_",""), st_body))

    story += [
        Spacer(1, 1*cm),
        HRFlowable(width="100%", thickness=0.5, color=GOLD, spaceAfter=8),
        Paragraph("Отчёт создан персонально · Нумерология · Астрология · Психология", st_foot),
    ]
    doc.build(story)
    print(f"[PDF] Создан: {filename}")
    return filename
