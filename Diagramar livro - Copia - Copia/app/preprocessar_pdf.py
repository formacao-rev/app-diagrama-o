#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preprocessar_pdf.py - Adiciona OCR a PDFs escaneados antes do diagramamento

Uso: python preprocessar_pdf.py entrada.pdf saida_com_ocr.pdf
"""

import sys
import os
import re

try:
    import pymupdf as fitz
    import pytesseract
    from PIL import Image
    import io
    OCR_DISPONIVEL = True
except ImportError as e:
    OCR_DISPONIVEL = False
    print(f"⚠️ OCR indisponível: {e}")


def pdf_tem_texto(pdf_path):
    """Verifica se o PDF já tem camada de texto OCR."""
    doc = fitz.open(pdf_path)
    for page in doc:
        text = page.get_text().strip()
        if len(text) > 50:  # Página com texto significativo
            doc.close()
            return True
    doc.close()
    return False


def adiciona_ocr(pdf_entrada, pdf_saida, dpi=300):
    """Adiciona OCR a cada página do PDF."""
    if not OCR_DISPONIVEL:
        print("❌ pytesseract não disponível. Instale: pip install pytesseract pillow")
        return False

    print(f"🔄 Adicionando OCR a: {pdf_entrada}")
    print(f"   DPI: {dpi}")

    doc_orig = fitz.open(pdf_entrada)
    doc_saida = fitz.open()

    for i, page in enumerate(doc_orig):
        # Render page to image
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes('png')))

        # OCR the image with optimized config for scanned PDFs
        print(f"   Processando página {i+1}/{len(doc_orig)}...")
        # Use LSTM OCR engine (OEM=1) and assume uniform block of text (PSM=6)
        text = pytesseract.image_to_string(img, lang='por', config='--oem 1 --psm 6')

        if not text.strip():
            print(f"   ⚠️ Página {i+1} não contém texto reconhecível")

        # Create new page
        new_page = doc_saida.new_page(width=page.rect.width, height=page.rect.height)

        # Insert the original image on the page
        new_page.insert_image(
            (0, 0, page.rect.width, page.rect.height),
            pixmap=pix
        )

        # Insert text as a semi-transparent text layer for searching/selecting
        # This allows the text to be searchable while showing it overlayed
        if text.strip():
            # Place text at top-left with small font
            new_page.insert_text(
                (5, 15),
                text.strip(),
                fontsize=2,  # Very small font - text is invisible but searchable
                render_mode=3,  # Invisible/text-under-image mode
                fill=0  # Black color (won't be visible due to render_mode)
            )

    doc_saida.save(pdf_saida, garbage=3, deflate=True)
    doc_orig.close()
    doc_saida.close()

    print(f"✅ OCR concluído: {pdf_saida}")
    return True


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        print("\nUso: python preprocessar_pdf.py entrada.pdf saida.pdf")
        return

    entrada = sys.argv[1]
    saida = sys.argv[2]

    if not os.path.exists(entrada):
        print(f"❌ Arquivo não encontrado: {entrada}")
        return

    # Check if PDF already has text
    if pdf_tem_texto(entrada):
        print("✅ PDF já tem OCR - nenhuma conversão necessária")
        if entrada != saida:
            import shutil
            shutil.copy(entrada, saida)
            print(f"✅ Cópia criada: {saida}")
        return

    # Add OCR
    adiciona_ocr(entrada, saida)


if __name__ == "__main__":
    main()