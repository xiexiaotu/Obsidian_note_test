import sys, re
from pypdf import PdfReader

path = r"H:\Note_Test\Obsidian_note_test\[野火EmbedFire]《STM32 HAL库开发实战指南——基于野火霸天虎开发板》.pdf"
r = PdfReader(path)
n = len(r.pages)
print("PAGES:", n)
hits = []
for i, p in enumerate(r.pages):
    try:
        t = p.extract_text() or ""
    except Exception as e:
        t = ""
    t2 = t.replace("\n", " ")
    if re.search(r"IIC|I2C|I²C", t2, re.I):
        hits.append(i)
print("HIT_PAGES:", len(hits))
# group into ranges
def ranges(xs):
    out = []
    for x in xs:
        if out and x == out[-1][1] + 1:
            out[-1][1] = x
        else:
            out.append([x, x])
    return out
print("RANGES:", ranges(hits))
