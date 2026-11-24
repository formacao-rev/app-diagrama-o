#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dividir_paginas.py - Divide PDFs escaneados com duas páginas por folha (spread/xerox)
e coloca todas as páginas em ordem sequencial, preservando e limpando o OCR de cada metade.

Instalação:
    pip install pymupdf numpy

Uso:
    python dividir_paginas.py entrada.pdf [saida.pdf]
"""
import os
import re
import sys
import numpy as np
import pymupdf as fitz

DPI = 150
FAIXA_BUSCA = (0.35, 0.65)   # Janela central (35% a 65% da largura) para procurar a dobra
PROPORCAO_SPREAD = 1.08      # Largura/Altura acima disto (ou página paisagem) indica folha dupla
MARGEM_BORDA_Y = 0.08        # Ignora 8% do topo e da base (bordas pretas de xerox)
MARGEM_BORDA_X = 0.04        # Ignora 4% das bordas laterais


def acha_calha_ocr(page, x_min, x_max):
    """Procura a divisória central usando os blocos de texto do OCR para nunca cortar palavras."""
    blocos = page.get_text("blocks")
    Larg = page.rect.width
    H = page.rect.height
    caixas = []
    for b in blocos:
        if len(b) >= 7 and b[6] != 0:
            continue
        x0, y0, x1, y1, txt = b[:5]
        if not txt or not txt.strip():
            continue
        # Ignora ruído extremo nas bordas do scan
        if (x1 - x0) < Larg * 0.01 or y1 < H * 0.03 or y0 > H * 0.97:
            continue
        # Ignora blocos que atravessam a página inteira (marcas d'água ou linhas de falha)
        if (x1 - x0) > Larg * 0.75:
            continue
        caixas.append((x0, x1))

    if len(caixas) < 4:
        return None

    meio = page.rect.x0 + Larg * 0.5
    esq = [x1 for x0, x1 in caixas if (x0 + x1) / 2 < meio and x1 <= x_max]
    dir_ = [x0 for x0, x1 in caixas if (x0 + x1) / 2 >= meio and x0 >= x_min]

    if esq and dir_:
        limite_esq = np.percentile(esq, 95)
        limite_dir = np.percentile(dir_, 5)
        if limite_esq < limite_dir:
            return float((limite_esq + limite_dir) / 2.0)
    return None


def acha_calha_imagem(page, x_min, x_max):
    """Localiza a calha central mesmo quando há linha preta ou sombra escura na dobra do xerox."""
    pix = page.get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]

    # Recorta topo e base para ignorar bordas pretas horizontais de xerox
    y0 = int(pix.height * MARGEM_BORDA_Y)
    y1 = int(pix.height * (1.0 - MARGEM_BORDA_Y))
    miolo = arr[y0:y1, :] if y1 > y0 else arr

    a = int(pix.width * FAIXA_BUSCA[0])
    b = int(pix.width * FAIXA_BUSCA[1])
    if b <= a:
        return page.rect.x0 + page.rect.width * 0.5

    # 1. Densidade de tinta escura e variância vertical (texto tem alta variância; margem branca ou sombra uniforme tem baixa variância)
    tinta = (miolo < 160).mean(axis=0)
    transicoes = np.abs(np.diff(miolo.astype(np.int16), axis=0)).mean(axis=0)

    # Normaliza curvas (np.ptp(x) funciona no NumPy 1 e 2; o método x.ptp() foi removido no NumPy 2)
    tinta_norm = (tinta - tinta.min()) / (np.ptp(tinta) + 1e-6)
    trans_norm = (transicoes - transicoes.min()) / (np.ptp(transicoes) + 1e-6)

    # Suavização
    janela = max(5, int(pix.width * 0.012) | 1)
    kernel = np.ones(janela) / janela
    tinta_suave = np.convolve(tinta_norm, kernel, mode="same")
    trans_suave = np.convolve(trans_norm, kernel, mode="same")

    # Penaliza afastamento excessivo do centro geométrico (50%)
    eixo_x = np.arange(pix.width)
    centro_px = pix.width * 0.5
    penalidade_centro = ((eixo_x - centro_px) / (pix.width * 0.25)) ** 2 * 0.15

    # Na calha real (mesmo com sombra na dobra), há pouca transição de letras (trans_suave baixo)
    # ou uma linha estreita escura cercada por duas margens brancas (vales de tinta + trans_suave).
    janela_larga = max(15, int(pix.width * 0.04) | 1)
    vizinhanca_tinta = np.convolve(tinta_suave, np.ones(janela_larga) / janela_larga, mode="same")

    custo = 0.55 * trans_suave + 0.30 * vizinhanca_tinta + 0.15 * tinta_suave + penalidade_centro
    x_best = a + int(np.argmin(custo[a:b]))

    return float(page.rect.x0 + x_best * page.rect.width / pix.width)


def acha_calha(page):
    r = page.rect
    x_min = r.x0 + r.width * FAIXA_BUSCA[0]
    x_max = r.x0 + r.width * FAIXA_BUSCA[1]

    xg_ocr = acha_calha_ocr(page, x_min, x_max)
    xg_img = acha_calha_imagem(page, x_min, x_max)

    if xg_ocr is not None:
        # Se o OCR encontrou um corredor limpo entre as duas colunas de páginas, prioriza-o
        if abs(xg_ocr - xg_img) <= r.width * 0.06:
            return 0.65 * xg_ocr + 0.35 * xg_img
        return xg_ocr
    return xg_img


def limpa_ocr_fora_do_clip(page, lado_mantido):
    """Remove fisicamente o texto OCR que ficou fora da página dividida."""
    r = page.rect
    # Verifica blocos fora do retângulo visível e aplica redaction apenas no texto
    blocos = page.get_text("blocks")
    removidos = 0
    for b in blocos:
        bx0, by0, bx1, by1 = b[:4]
        cx = (bx0 + bx1) / 2.0
        if cx < r.x0 or cx > r.x1:
            page.add_redact_annot(fitz.Rect(bx0, by0, bx1, by1))
            removidos += 1
    if removidos:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)


def acha_sombra(page, xg):
    """Procura a faixa escura da dobra (sombra de xerox) perto do corte; devolve (x_ini, x_fim) ou None."""
    pix = page.get_pixmap(dpi=100, colorspace=fitz.csGRAY)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
    y0, y1 = int(pix.height * 0.1), int(pix.height * 0.9)
    escuro = (arr[y0:y1] < 110).mean(axis=0) > 0.6
    esc = pix.width / page.rect.width
    c = int(round((xg - page.rect.x0) * esc))
    raio = int(pix.width * 0.08)
    cols = [i for i in range(max(0, c - raio), min(pix.width, c + raio + 1)) if escuro[i]]
    if not cols or (cols[-1] - cols[0]) > pix.width * 0.12:
        return None
    x_ini = page.rect.x0 + cols[0] / esc
    x_fim = page.rect.x0 + (cols[-1] + 1) / esc
    r = page.rect
    if x_ini < r.x0 + r.width * 0.3 or x_fim > r.x0 + r.width * 0.7:
        return None
    return x_ini, x_fim


def eh_pagina_dupla(page):
    r = page.rect
    if r.width > r.height * PROPORCAO_SPREAD:
        return True
    return False


def divide(entrada, saida):
    src = fitz.open(entrada)
    out = fitz.open()
    divididas = 0

    for page in src:
        # Normaliza eventual rotação embutida no PDF antes de medir largura/altura
        if page.rotation in (90, 180, 270):
            page.remove_rotation()

        r = page.rect
        if not eh_pagina_dupla(page):
            out.insert_pdf(src, from_page=page.number, to_page=page.number)
            continue

        xg = acha_calha(page)
        divididas += 1
        sombra = acha_sombra(page, xg)  # tira a faixa escura da dobra dos dois lados
        xe, xd = sombra if sombra else (xg, xg)

        clips = [
            ("esq", fitz.Rect(r.x0, r.y0, xe, r.y1)),
            ("dir", fitz.Rect(xd, r.y0, r.x1, r.y1)),
        ]
        for lado, clip in clips:
            # Insere uma cópia independente da página e ajusta seu CropBox/MediaBox para a metade exata
            out.insert_pdf(src, from_page=page.number, to_page=page.number)
            nova = out[-1]
            nova.set_cropbox(clip)
            nova.set_mediabox(clip)
            limpa_ocr_fora_do_clip(nova, lado)

    out.save(saida, garbage=4, deflate=True)
    print(f"Concluído: {len(src)} página(s) de entrada -> {len(out)} página(s) de saída "
          f"({divididas} folha(s) dupla(s) dividida(s) em ordem).")
    print(f"Arquivo salvo em: {saida}")


def nome_do_livro(caminho):
    """Nome do livro a partir do arquivo (tira .pdf/.txt/.docx repetidos e caracteres proibidos no Windows)."""
    n = os.path.basename(caminho)
    while True:
        base, ext = os.path.splitext(n)
        if base and ext.lower() in (".pdf", ".txt", ".docx"):
            n = base
        else:
            break
    return re.sub(r'[<>:"/\\|?*]+', " ", n).strip(" .") or "livro"


def pasta_unica(nome):
    """Devolve 'nome', ou 'nome (2)', 'nome (3)'... se já existir: nunca escreve por cima de uma saída anterior."""
    p, i = nome, 2
    while os.path.exists(p):
        p = f"{nome} ({i})"
        i += 1
    return p


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    entrada = sys.argv[1]
    if len(sys.argv) > 2:
        saida = sys.argv[2]
    else:
        pasta = pasta_unica(nome_do_livro(entrada))
        os.makedirs(pasta, exist_ok=True)
        saida = os.path.join(pasta, nome_do_livro(entrada) + "_dividido.pdf")
    divide(entrada, saida)