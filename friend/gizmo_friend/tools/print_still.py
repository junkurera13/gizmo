from __future__ import annotations

import math


PALETTE_PAPER = "#e7dcc8"
PALETTE_INK = "#1c1814"
PALETTE_OCHRE = "#c45c26"
PALETTE_MOSS = "#3d4a32"


def render_still(subject: str, size: int = 240) -> str:
    """240×240 print-look SVG. Not photoreal. Never a kid's face."""
    key = subject.strip().lower() or "thing"
    if "pinecone" in key or "pine cone" in key:
        inner = _pinecone()
    elif "rock" in key or "stone" in key:
        inner = _rock()
    elif "leaf" in key:
        inner = _leaf()
    else:
        inner = _stamp(subject)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">
  <rect width="{size}" height="{size}" fill="{PALETTE_PAPER}"/>
  <rect x="10" y="10" width="220" height="220" fill="none" stroke="{PALETTE_INK}" stroke-width="3"/>
  {inner}
</svg>
'''


def _pinecone() -> str:
    scales = []
    for row, y in enumerate(range(70, 175, 14)):
        cols = 5 - (row % 2)
        x0 = 120 - cols * 11
        for i in range(cols):
            x = x0 + i * 22
            scales.append(
                f'<ellipse cx="{x}" cy="{y}" rx="11" ry="8" fill="{PALETTE_OCHRE}" '
                f'stroke="{PALETTE_INK}" stroke-width="2"/>'
            )
    return f'''
  <line x1="120" y1="48" x2="120" y2="70" stroke="{PALETTE_INK}" stroke-width="3"/>
  <polygon points="120,42 112,58 128,58" fill="{PALETTE_MOSS}" stroke="{PALETTE_INK}" stroke-width="2"/>
  {"".join(scales)}
  <ellipse cx="120" cy="182" rx="16" ry="8" fill="{PALETTE_INK}"/>
'''


def _rock() -> str:
    return f'''
  <polygon points="70,150 90,90 150,70 190,120 170,180 80,185" fill="{PALETTE_OCHRE}" stroke="{PALETTE_INK}" stroke-width="3"/>
  <line x1="100" y1="120" x2="150" y2="140" stroke="{PALETTE_INK}" stroke-width="2"/>
'''


def _leaf() -> str:
    return f'''
  <ellipse cx="120" cy="125" rx="50" ry="80" fill="{PALETTE_MOSS}" stroke="{PALETTE_INK}" stroke-width="3"/>
  <line x1="120" y1="50" x2="120" y2="200" stroke="{PALETTE_INK}" stroke-width="2"/>
'''


def _stamp(subject: str) -> str:
    label = _xml(subject.strip()[:18] or "thing")
    wedges = []
    for i in range(7):
        ang = i * (2 * math.pi / 7) - math.pi / 2
        x = 120 + int(48 * math.cos(ang))
        y = 110 + int(48 * math.sin(ang))
        wedges.append(
            f'<circle cx="{x}" cy="{y}" r="10" fill="{PALETTE_OCHRE}" stroke="{PALETTE_INK}" stroke-width="2"/>'
        )
    return f'''
  <circle cx="120" cy="110" r="28" fill="{PALETTE_INK}"/>
  {"".join(wedges)}
  <text x="120" y="210" text-anchor="middle" font-family="Georgia, serif" font-size="16" fill="{PALETTE_INK}">{label}</text>
'''


def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
