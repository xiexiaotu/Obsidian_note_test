import sys, io, os
sys.stderr = io.StringIO()
from pypdf import PdfReader

path = r"H:\Note_Test\Obsidian_note_test\[野火EmbedFire]《STM32 HAL库开发实战指南——基于野火霸天虎开发板》.pdf"
outdir = r"C:\Users\0.0\AppData\Local\Temp\iic_pdf"
os.makedirs(outdir, exist_ok=True)
r = PdfReader(path)

def dump(a, b, name):
    buf = []
    for i in range(a, b):
        try:
            t = r.pages[i].extract_text() or ""
        except Exception as e:
            t = f"<<extract failed: {e}>>"
        buf.append(f"\n========== PDF_PAGE_INDEX {i} ==========\n{t}")
    p = os.path.join(outdir, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write("".join(buf))
    print("WROTE", p, os.path.getsize(p))

dump(378, 440, "ch23_i2c_eeprom.txt")
dump(1265, 1300, "ch44_mpu6050.txt")
