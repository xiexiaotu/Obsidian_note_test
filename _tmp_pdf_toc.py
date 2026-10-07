import sys, re, io
sys.stderr = io.StringIO()
from pypdf import PdfReader

path = r"H:\Note_Test\Obsidian_note_test\[野火EmbedFire]《STM32 HAL库开发实战指南——基于野火霸天虎开发板》.pdf"
r = PdfReader(path)

out = []
def walk(items, depth=0):
    for it in items:
        if isinstance(it, list):
            walk(it, depth + 1)
        else:
            try:
                t = it.title
                p = r.get_destination_page_number(it)
            except Exception:
                continue
            out.append((depth, p, t))

walk(r.outline)
print("OUTLINE_ENTRIES:", len(out))
for d, p, t in out:
    if re.search(r"I2C|IIC|I²C|EEPROM|24C|MPU|触摸|OLED|通信|通讯", t, re.I):
        print(f"{'  '*d}[p{p}] {t}")
