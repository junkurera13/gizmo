from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


ROOT = Path(r"D:\GIZMO\gizmo-main")
SOURCE = Path(r"C:\Users\mevan\Downloads\Project Final Report (individual submission).pdf")
OUT_DIR = ROOT / "output" / "pdf"
TMP_DIR = ROOT / "tmp" / "pdfs"
OUTPUT = OUT_DIR / "Mevan_Perera_Personal_Robotics_Project.pdf"
REPLACEMENTS = TMP_DIR / "replacement_pages.pdf"
HEADER_OVERLAY = TMP_DIR / "personal_header_overlay.pdf"

NAVY = HexColor("#09265D")
RED = HexColor("#E2232E")
INK = HexColor("#172033")
MUTED = HexColor("#657084")
PALE = HexColor("#F3F5F8")
RULE = HexColor("#D8DDE7")


def wrap_text(text, font_name, font_size, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if stringWidth(trial, font_name, font_size) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_footer(c, page_number):
    w, _ = A4
    c.setStrokeColor(RULE)
    c.setLineWidth(0.6)
    c.line(52, 39, w - 52, 39)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(INK)
    c.drawString(52, 24, str(page_number))
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    c.drawString(66, 24, "|  Page")


def draw_cover(c):
    w, h = A4
    c.setFillColor(NAVY)
    c.rect(0, 0, w, h, fill=1, stroke=0)

    c.setFillColor(RED)
    c.rect(0, h - 18, w, 18, fill=1, stroke=0)
    c.rect(0, 0, 16, h, fill=1, stroke=0)

    # Subtle engineering-grid motif.
    c.saveState()
    c.setStrokeColor(HexColor("#173A78"))
    c.setLineWidth(0.35)
    for x in range(36, int(w), 28):
        c.line(x, 0, x, h)
    for y in range(28, int(h), 28):
        c.line(0, y, w, y)
    c.restoreState()

    left = 62
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(left, h - 70, "PERSONAL ENGINEERING PROJECT")
    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#C7D1E7"))
    c.drawString(left, h - 88, "MECHATRONICS  /  ROBOTICS  /  EMBEDDED CONTROL")

    c.setFillColor(RED)
    c.roundRect(left, h - 164, 142, 24, 12, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(left + 71, h - 155, "PROJECT CASE STUDY")

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 34)
    c.drawString(left, h - 235, "AUTONOMOUS BALL")
    c.drawString(left, h - 276, "COLLECTION ROBOT")
    c.setFillColor(HexColor("#C7D1E7"))
    c.setFont("Helvetica", 15)
    c.drawString(left, h - 307, "Design, control and prototype development")

    c.setStrokeColor(RED)
    c.setLineWidth(3)
    c.line(left, h - 338, left + 76, h - 338)

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(left, h - 382, "PERSONAL MECHATRONICS PROJECT")
    c.setFont("Helvetica", 11)
    c.setFillColor(HexColor("#C7D1E7"))
    subtitle = "Autonomous ball collection, seesaw traversal and delivery system"
    c.drawString(left, h - 405, subtitle)

    info_y = 205
    c.setFillColor(HexColor("#0E316F"))
    c.roundRect(left, info_y, w - left - 46, 150, 8, fill=1, stroke=0)
    c.setFillColor(HexColor("#91A4C9"))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(left + 22, info_y + 116, "CREATED BY")
    c.drawString(left + 22, info_y + 67, "PROJECT FOCUS")
    c.drawString(left + 22, info_y + 21, "COMPLETED")

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(left + 22, info_y + 92, "Mevan Shandika Perera")
    c.setFont("Helvetica", 13)
    c.drawString(left + 22, info_y + 45, "Arduino control, actuation and prototyping")
    c.drawString(left + 22, info_y - 1, "13 June 2025")
    c.showPage()


def draw_executive_summary(c):
    w, h = A4
    c.setFillColor(white)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(0, h - 142, w, 142, fill=1, stroke=0)
    c.setFillColor(RED)
    c.rect(0, h - 16, w, 16, fill=1, stroke=0)

    c.setFillColor(HexColor("#C7D1E7"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(52, h - 48, "PROJECT OVERVIEW")
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(52, h - 86, "Executive Summary")
    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#C7D1E7"))
    c.drawString(52, h - 111, "Autonomous collection, transport and delivery prototype")

    opening = (
        "This project explores a compact autonomous robot designed to collect three balls of different sizes, "
        "transport them securely across a pivoting seesaw, and release them at a destination. The prototype "
        "combines a four-wheel drive platform, two servo-actuated retaining arms, and an Arduino Uno running "
        "a calibrated time-based control sequence."
    )
    y = h - 180
    c.setFillColor(INK)
    c.setFont("Helvetica", 10.5)
    for line in wrap_text(opening, "Helvetica", 10.5, w - 104):
        c.drawString(52, y, line)
        y -= 16

    highlights = [
        ("CONTROL", "Arduino Uno", "Sequential motor and servo commands using calibrated timing."),
        ("MOBILITY", "Four-wheel drive", "Four 12 V geared DC motors provide movement and seesaw traversal."),
        ("HANDLING", "Dual servo arms", "Custom grooves and servo arms secure three different ball sizes."),
    ]
    y -= 22
    card_w = (w - 124) / 3
    for i, (label, title, body) in enumerate(highlights):
        x = 52 + i * (card_w + 10)
        c.setFillColor(PALE)
        c.roundRect(x, y - 156, card_w, 156, 8, fill=1, stroke=0)
        c.setFillColor(RED)
        c.rect(x, y - 6, card_w, 6, fill=1, stroke=0)
        c.setFillColor(MUTED)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(x + 14, y - 29, label)
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x + 14, y - 52, title)
        c.setFillColor(INK)
        c.setFont("Helvetica", 8.7)
        by = y - 75
        for line in wrap_text(body, "Helvetica", 8.7, card_w - 28):
            c.drawString(x + 14, by, line)
            by -= 13

    y -= 194
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(52, y, "Development outcome")
    c.setFillColor(RED)
    c.rect(52, y - 12, 42, 3, fill=1, stroke=0)
    outcome = (
        "Testing demonstrated successful collection, controlled navigation, and stable seesaw crossing. "
        "The table-tennis ball was released successfully; the heavier tennis and racquet balls required more "
        "release momentum. The result validated the core mechanical and control architecture while identifying "
        "clear opportunities for sensing, voltage regulation, and an assisted release mechanism."
    )
    ty = y - 38
    c.setFillColor(INK)
    c.setFont("Helvetica", 10.2)
    for line in wrap_text(outcome, "Helvetica", 10.2, w - 104):
        c.drawString(52, ty, line)
        ty -= 16

    c.setFillColor(HexColor("#E9EDF4"))
    c.roundRect(52, 88, w - 104, 82, 8, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(68, 145, "KEY DESIGN DECISION")
    decision = (
        "Separate power supplies were used for the drive motors and servo system to reduce voltage drop "
        "and improve repeatability during combined operation."
    )
    c.setFillColor(INK)
    c.setFont("Helvetica", 9.5)
    dy = 124
    for line in wrap_text(decision, "Helvetica", 9.5, w - 136):
        c.drawString(68, dy, line)
        dy -= 14

    draw_footer(c, 2)
    c.showPage()


def draw_contents(c):
    w, h = A4
    c.setFillColor(white)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColor(RED)
    c.rect(0, h - 14, w, 14, fill=1, stroke=0)

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(52, h - 82, "Contents")
    c.setFillColor(RED)
    c.rect(52, h - 100, 54, 4, fill=1, stroke=0)

    rows = [
        ("1", "Introduction", "4", False),
        ("2", "Initial Design", "5", False),
        ("2.1", "Initial timelines", "6", True),
        ("3", "Final Design", "7", False),
        ("3.1", "Mechanical structure, mechanisms and motions", "7", True),
        ("3.2", "Sensors and actuators", "8", True),
        ("3.3", "Microcontroller programming", "9", True),
        ("3.4", "Simulation or prototyping/fabrication", "10", True),
        ("4", "Cost", "12", False),
        ("5", "Results and Discussion", "13", False),
        ("6", "System Overview", "14", False),
        ("7", "Conclusion and Further Developments", "15", False),
        ("", "References", "16", False),
        ("A", "Appendix A: Technical Specifications", "17", False),
        ("B", "Appendix B: Source Code", "20", False),
    ]

    y = h - 138
    for number, title, page, nested in rows:
        if not nested:
            c.setFillColor(PALE)
            c.roundRect(48, y - 17, w - 96, 30, 5, fill=1, stroke=0)
        x_num = 68 if nested else 58
        x_title = 112 if nested else 92
        c.setFont("Helvetica-Bold" if not nested else "Helvetica", 10.2)
        c.setFillColor(NAVY if not nested else INK)
        if number:
            c.drawString(x_num, y - 5, number)
        c.drawString(x_title, y - 5, title)
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(RED if not nested else MUTED)
        c.drawRightString(w - 62, y - 5, page)
        y -= 37 if not nested else 28

    draw_footer(c, 3)
    c.showPage()


def draw_system_overview(c):
    w, h = A4
    c.setFillColor(white)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(0, h - 110, w, 110, fill=1, stroke=0)
    c.setFillColor(RED)
    c.rect(0, h - 18, w, 18, fill=1, stroke=0)

    c.setFillColor(HexColor("#C7D1E7"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(52, h - 44, "SECTION 6")
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 25)
    c.drawString(52, h - 78, "System Overview")
    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#C7D1E7"))
    c.drawRightString(w - 52, h - 44, "Architecture and operating sequence")

    intro = (
        "The prototype uses a deliberately simple architecture: timed Arduino control, differential drive, "
        "servo-assisted ball retention, and isolated power for the drive and handling systems."
    )
    c.setFillColor(INK)
    c.setFont("Helvetica", 11)
    y = h - 145
    for line in wrap_text(intro, "Helvetica", 11, w - 104):
        c.drawString(52, y, line)
        y -= 17

    cards = [
        (
            "01",
            "CONTROL",
            "An Arduino Uno executes one calibrated sequence of forward, reverse, turning, pickup, crossing, and release actions. The loop remains empty after completion.",
        ),
        (
            "02",
            "DRIVE",
            "Four 12 V geared DC motors use differential steering. Reversing wheel polarity enables forward motion, reverse motion, and pivot turns.",
        ),
        (
            "03",
            "BALL HANDLING",
            "Two servo-driven arms retain the balls against dedicated chassis grooves during movement. Servo detachment releases the payload at the destination.",
        ),
        (
            "04",
            "POWER",
            "A 12 V Ni-MH pack supplies the drive motors, while a separate 8 x AA holder powers the servos. Isolation reduces voltage drop during combined operation.",
        ),
    ]

    y -= 22
    card_h = 102
    for num, heading, body in cards:
        c.setFillColor(PALE)
        c.roundRect(52, y - card_h, w - 104, card_h, 8, fill=1, stroke=0)
        c.setFillColor(RED)
        c.roundRect(66, y - 36, 38, 24, 12, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(85, y - 28, num)

        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(118, y - 27, heading)
        c.setFillColor(INK)
        c.setFont("Helvetica", 9.6)
        line_y = y - 48
        for line in wrap_text(body, "Helvetica", 9.6, w - 190):
            c.drawString(118, line_y, line)
            line_y -= 14
        y -= card_h + 14

    c.setFillColor(NAVY)
    c.roundRect(52, 72, w - 104, 68, 8, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(68, 116, "OPERATING SEQUENCE")
    summary = (
        "Approach grid  >  secure balls  >  reverse and turn  >  cross seesaw  >  align with destination  >  release payload"
    )
    c.setFont("Helvetica", 9.6)
    sy = 96
    for line in wrap_text(summary, "Helvetica", 9.6, w - 136):
        c.drawString(68, sy, line)
        sy -= 14

    draw_footer(c, 14)
    c.showPage()


def create_header_overlay():
    c = canvas.Canvas(str(HEADER_OVERLAY), pagesize=A4)
    w, h = A4
    c.setFillColor(white)
    c.rect(0, h - 42, w, 42, fill=1, stroke=0)
    c.setFillColor(RED)
    c.rect(0, h - 10, w, 10, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(52, h - 29, "AUTONOMOUS BALL COLLECTION ROBOT")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.5)
    c.drawRightString(w - 52, h - 29, "PERSONAL MECHATRONICS PROJECT")
    c.showPage()
    c.save()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(REPLACEMENTS), pagesize=A4)
    c.setTitle("Autonomous Ball Collection Robot - Personal Project")
    c.setAuthor("Mevan Shandika Perera")
    draw_cover(c)
    draw_executive_summary(c)
    draw_contents(c)
    draw_system_overview(c)
    c.save()
    create_header_overlay()

    source = PdfReader(str(SOURCE))
    replacement = PdfReader(str(REPLACEMENTS))
    if len(source.pages) != 20 or len(replacement.pages) != 4:
        raise RuntimeError("Unexpected page count")

    writer = PdfWriter()
    replace_map = {
        0: replacement.pages[0],
        1: replacement.pages[1],
        2: replacement.pages[2],
        13: replacement.pages[3],
    }
    header = PdfReader(str(HEADER_OVERLAY)).pages[0]
    for idx, page in enumerate(source.pages):
        if idx in replace_map:
            final_page = replace_map[idx]
        else:
            final_page = page
            final_page.merge_page(header, over=True)
        writer.add_page(final_page)
    writer.add_metadata(
        {
            "/Title": "Autonomous Ball Collection Robot - Personal Project",
            "/Author": "Mevan Shandika Perera",
            "/Subject": "Personal mechatronics and robotics project",
        }
    )
    with OUTPUT.open("wb") as stream:
        writer.write(stream)

    check = PdfReader(str(OUTPUT))
    if len(check.pages) != 20:
        raise RuntimeError("Final PDF does not contain 20 pages")
    print(OUTPUT)


if __name__ == "__main__":
    main()
