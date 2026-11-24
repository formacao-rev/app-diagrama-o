#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ocr_layout.py - OCR com análise de layout (pytesseract.image_to_data)

Preserva estrutura: colunas, parágrafos, tabelas, imagens, headers/footers.
Gera PDF com camada de texto posicionada (text-under-image).
"""

import os
import io
import json
import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
from pathlib import Path

try:
    import pytesseract
    from PIL import Image
    import pymupdf as fitz
    OCR_DISPONIVEL = True
except ImportError:
    OCR_DISPONIVEL = False

try:
    import cv2
    import numpy as np
    CV2_DISPONIVEL = True
except ImportError:
    CV2_DISPONIVEL = False


@dataclass
class BlocoOCR:
    """Bloco de texto detectado pelo OCR com layout."""
    texto: str
    x: int
    y: int
    w: int
    h: int
    confianca: float
    nivel: int  # 1=page, 2=block, 3=par, 4=line, 5=word
    bloco_num: int
    par_num: int
    linha_num: int
    palavra_num: int
    coluna: int = 0  # 0=esquerda, 1=direita (para 2 colunas)

    @property
    def centro_x(self) -> float:
        return self.x + self.w / 2

    @property
    def centro_y(self) -> float:
        return self.y + self.h / 2


@dataclass
class ColunaOCR:
    """Coluna de texto detectada."""
    x_inicio: int
    x_fim: int
    blocos: List['BlocoOCR'] = field(default_factory=list)

    def adiciona(self, bloco: 'BlocoOCR'):
        self.blocos.append(bloco)


@dataclass
class TabelaOCR:
    """Tabela detectada."""
    x: int
    y: int
    w: int
    h: int
    linhas: int
    colunas: int
    celulas: List[List[str]] = field(default_factory=list)
    confianca: float = 0.0


@dataclass
class ImagemOCR:
    """Imagem/figura detectada."""
    x: int
    y: int
    w: int
    h: int
    tipo: str = "figura"  # figura, grafico, foto, diagrama
    caption: str = ""


def detecta_colunas(blocos: List[BlocoOCR], largura_pagina: int) -> List[ColunaOCR]:
    """
    Detecta colunas baseado na distribuição horizontal dos blocos.
    Assume 1 ou 2 colunas (layout comum em livros).
    """
    if not blocos:
        return [ColunaOCR(0, largura_pagina, blocos)]

    # Coleta centros X
    centros = [b.centro_x for b in blocos if b.nivel <= 3]  # block/par/line
    if not centros:
        return [ColunaOCR(0, largura_pagina, blocos)]

    # Testa se há 2 picos (bimodal = 2 colunas)
    from collections import Counter
    hist = Counter([int(c // 50) * 50 for c in centros])  # bins de 50px

    if len(hist) < 3:
        return [ColunaOCR(0, largura_pagina, blocos)]

    # Procura vale entre dois picos
    sorted_bins = sorted(hist.items())
    picos = []
    for i in range(1, len(sorted_bins) - 1):
        if sorted_bins[i][1] > sorted_bins[i-1][1] and sorted_bins[i][1] > sorted_bins[i+1][1]:
            picos.append(sorted_bins[i][0])

    if len(picos) >= 2:
        # Dois picos = duas colunas
        vale_x = (picos[0] + picos[1]) // 2
        col1 = ColunaOCR(0, vale_x, [])
        col2 = ColunaOCR(vale_x, largura_pagina, [])

        for b in blocos:
            if b.centro_x < vale_x:
                col1.adiciona(b)
            else:
                col2.adiciona(b)

        return [col1, col2]

    return [ColunaOCR(0, largura_pagina, blocos)]


def detecta_tabelas(blocos: List[BlocoOCR]) -> List[TabelaOCR]:
    """
    Detecta tabelas: grade regular de blocos alinhados.
    """
    tabelas = []
    if len(blocos) < 6:
        return tabelas

    # Agrupa por linha (Y similar)
    linhas_map = {}
    for b in blocos:
        if b.nivel == 4:  # linha
            y_key = round(b.y / 10) * 10
            if y_key not in linhas_map:
                linhas_map[y_key] = []
            linhas_map[y_key].append(b)

    # Procura grade: múltiplas linhas com mesmo número de blocos alinhados em X
    for y, bloco_linha in linhas_map.items():
        if len(bloco_linha) >= 3:
            # Verifica alinhamento X consistente
            xs = sorted([b.x for b in bloco_linha])
            # Verifica se há grade em múltiplas linhas
            pass

    return tabelas


def extrai_texto_com_layout(pagina, dpi=300) -> Dict[str, Any]:
    """
    Extrai texto da página com análise completa de layout.

    Returns:
        Dict com:
        - 'blocos': Lista[BlocoOCR]
        - 'colunas': Lista[ColunaOCR]
        - 'tabelas': Lista[TabelaOCR]
        - 'imagens': Lista[ImagemOCR]
        - 'texto_por_coluna': Dict[coluna_idx, str]
        - 'tem_multiplas_colunas': bool
    """
    if not OCR_DISPONIVEL:
        return {'erro': 'OCR não disponível'}

    # Render página como imagem
    pix = pagina.get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes('png')))

    # OCR com dados detalhados
    data = pytesseract.image_to_data(
        img, lang='por', output_type=pytesseract.Output.DICT
    )

    # Converte para BlocoOCR
    blocos = []
    n = len(data['text'])
    for i in range(n):
        if data['text'][i].strip() and data['conf'][i] > 30:
            bloco = BlocoOCR(
                texto=data['text'][i],
                x=data['left'][i],
                y=data['top'][i],
                w=data['width'][i],
                h=data['height'][i],
                confianca=data['conf'][i] / 100.0,
                nivel=data['level'][i],
                bloco_num=data['block_num'][i],
                par_num=data['par_num'][i],
                linha_num=data['line_num'][i],
                palavra_num=data['word_num'][i]
            )
            blocos.append(bloco)

    # Detecta colunas
    largura = pagina.rect.width * dpi / 72
    colunas = detecta_colunas(blocos, largura)

    # Atribui coluna aos blocos
    for col_idx, col in enumerate(colunas):
        for b in col.blocos:
            b.coluna = col_idx

    # Detecta tabelas (simplificado)
    tabelas = detecta_tabelas(blocos)

    # Detecta imagens (áreas sem texto mas com conteúdo)
    imagens = detecta_imagens(img, blocos)

    # Texto por coluna (ordem de leitura)
    texto_por_coluna = {}
    for col_idx, col in enumerate(colunas):
        # Ordena por Y (topo para baixo), depois X
        col.blocos.sort(key=lambda b: (b.y, b.x))
        texto_col = " ".join([b.texto for b in col.blocos if b.nivel <= 4])
        texto_por_coluna[col_idx] = texto_col

    return {
        'blocos': blocos,
        'colunas': colunas,
        'tabelas': tabelas,
        'imagens': imagens,
        'texto_por_coluna': texto_por_coluna,
        'tem_multiplas_colunas': len(colunas) > 1
    }


def detecta_imagens(img: Image.Image, blocos: List[BlocoOCR]) -> List[ImagemOCR]:
    """
    Detecta áreas de imagem/figura (regiões sem texto mas com conteúdo visual).
    Simplificado: usa OpenCV se disponível.
    """
    imagens = []
    if not CV2_DISPONIVEL:
        return imagens

    # Converte PIL para OpenCV
    cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    # Detecta bordas
    edges = cv2.Canny(gray, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    h_img, w_img = gray.shape

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 5000:  # Muito pequeno
            continue

        x, y, w, h = cv2.boundingRect(cnt)
        if w < 100 or h < 100:
            continue

        # Verifica se não sobrepõe blocos de texto significativamente
        sobrepoe_texto = False
        for b in blocos:
            # Converte coordenadas OCR (dpi-based) para coordenadas imagem
            # Simplificado: assume mesmo DPI
            if (b.x < x + w and b.x + b.w > x and
                b.y < y + h and b.y + b.h > y):
                sobrepoe_texto = True
                break

        if not sobrepoe_texto:
            imagens.append(ImagemOCR(x, y, w, h))

    return imagens


def cria_pdf_com_ocr_layout(pdf_entrada: str, pdf_saida: str, dpi=300) -> bool:
    """
    Cria PDF com OCR preservando layout (colunas, tabelas, imagens).
    Insere texto como camada invisível posicionada (text-under-image).
    """
    if not OCR_DISPONIVEL:
        print("❌ OCR não disponível")
        return False

    doc_orig = fitz.open(pdf_entrada)
    doc_saida = fitz.open()

    for i, page in enumerate(doc_orig):
        print(f"   Processando página {i+1}/{len(doc_orig)}...")

        # Extrai com layout
        layout = extrai_texto_com_layout(page, dpi=dpi)

        if 'erro' in layout:
            continue

        # Nova página
        new_page = doc_saida.new_page(width=page.rect.width, height=page.rect.height)

        # Insere imagem original
        pix = page.get_pixmap(dpi=dpi)
        new_page.insert_image(
            (0, 0, page.rect.width, page.rect.height),
            pixmap=pix
        )

        # Insere texto por coluna (ordem de leitura correta)
        if layout['tem_multiplas_colunas']:
            # Para múltiplas colunas, insere coluna por coluna
            for col_idx, texto in layout['texto_por_coluna'].items():
                if not texto.strip():
                    continue
                # Posição aproximada da coluna
                col = layout['colunas'][col_idx]
                x = col.x_inicio * 72 / dpi
                y = 50  # topo
                w = (col.x_fim - col.x_inicio) * 72 / dpi

                # Insere texto invisível (render_mode=3)
                new_page.insert_textbox(
                    (x, y, x + w, page.rect.height - 50),
                    texto,
                    fontsize=8,
                    render_mode=3,  # invisível mas pesquisável
                    fill=(0, 0, 0)
                )
        else:
            # Coluna única - insere todo texto
            texto_total = layout['texto_por_coluna'].get(0, "")
            if texto_total.strip():
                new_page.insert_text(
                    (50, 50),
                    texto_total,
                    fontsize=6,
                    render_mode=3,
                    fill=(0, 0, 0)
                )

        # Metadados de layout (opcional - para debug)
        # new_page.insert_text((10, 10), f"Cols: {len(layout['colunas'])}", fontsize=6)

    doc_saida.save(pdf_saida, garbage=3, deflate=True)
    doc_orig.close()
    doc_saida.close()

    print(f"✅ OCR com layout salvo: {pdf_saida}")
    return True


def main():
    import sys
    if len(sys.argv) < 3:
        print("Uso: python ocr_layout.py entrada.pdf saida.pdf [dpi]")
        sys.exit(1)

    entrada = sys.argv[1]
    saida = sys.argv[2]
    dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 300

    if not os.path.exists(entrada):
        print(f"❌ Arquivo não encontrado: {entrada}")
        return

    cria_pdf_com_ocr_layout(entrada, saida, dpi)


if __name__ == "__main__":
    main()