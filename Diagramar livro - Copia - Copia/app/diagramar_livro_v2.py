#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagramar_livro_v2.py - Extrai todo o texto de qualquer PDF com OCR e refaz do zero
em uma diagramação editorial limpa (A4, corpo 16/22 pt com capitulares, fólhas alternadas
no rodapé), identificando automaticamente títulos, capítulos, subtítulos, citações e notas,
mantendo a chamada da nota após a palavra correta, movendo todas as notas para o final de
cada capítulo e gerando Sumário automático.

Instalação:
    pip install pymupdf reportlab python-docx pyphen

Uso:
    python diagramar_livro_v2.py livro.pdf [pasta_saida] [opções]

    --capa ARQUIVO          imagem (JPG/PNG) usada como primeira página do PDF
    --capa-ajuste AJUSTE    "preencher" (corta, cobre a página toda - padrão) ou "conter"
    --folha-de-rosto        mantém a folha de rosto tipográfica depois da capa enviada
"""
import os
import re
import sys
import html
import unicodedata
from collections import Counter

import pymupdf as fitz  # PyMuPDF

# Sumário detector (ML + heurística)
try:
    from sumario_detector import SumarioDetector
    SUMARIO_DETECTOR_DISPONIVEL = True
except ImportError:
    SUMARIO_DETECTOR_DISPONIVEL = False

# EPUB generation (optional dependency)
try:
    from ebooklib import epub
    from ebooklib.utils import parse_html_string
    EPUB_DISPONIVEL = True
except ImportError:
    EPUB_DISPONIVEL = False


# ============================================================================
# MOTOR DE EXTRAÇÃO (embutido: este arquivo funciona sozinho)
# ============================================================================
# Marcadores internos de formatação
ABRE_IT, FECHA_IT = "\x01", "\x02"
ABRE_NE, FECHA_NE = "\x05", "\x06"
MARCA_I, MARCA_F = "\x03", "\x04"  # Sobrescrito de chamada de nota

ZONA_CAB = 0.10
ZONA_ROD = 0.91
LIM_NOTA = 0.92
PRESERVAR_ITALICO = True

SUPERSCRIPT_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
SUPERSCRIPT_CHARS = set("⁰¹²³⁴⁵⁶⁷⁸⁹")

PROTEGIDOS = {"pré", "pós", "pró", "recém", "além", "aquém", "vice"}

CORRECOES = [
    (r"ﬁ", "fi"), (r"ﬂ", "fl"), (r"ﬀ", "ff"), (r"ﬃ", "ffi"), (r"ﬄ", "ffl"),
    (r"\bÊ(?=\s+[a-záéíóúâêôãõç])", "É"),
    (r"\bÃ(?=\s+[a-záéíóúâêôãõç])", "À"),
    (r"\s+([,.;:!?])", r"\1"),
    (r"[ \t]{2,}", " "),
]

NUM_PAG_RE = re.compile(r"^[\W_]*(\d{1,4}|[ivxlcdm]{1,7})[\W_]*$", re.I)
CARIMBO_RE = re.compile(
    r"(naps2|imagem\s+digitalizada|camscanner|instituto\s+cultural|instituto\s+goethe|biblioteca\s+|av\.\s+graça\s+aranha)",
    re.I
)
SUB_RE = re.compile(
    r"^(?:(?:\d{1,2}(?:\.\d{1,2}){0,3}|[IVXLC]{1,6}|[a-zA-Z])[\.\)]\s+)"
    r"[A-ZÁÉÍÓÚÂÊÔÃÕÇÜÑ\"'“”«\d]"
)
# Reconhece (1), 1., 1 , [1], (*), *, ¹ etc. e também falhas de OCR como "+. Autor" ou ": . Autor"
NOTA_INICIO_RE = re.compile(
    r"^\s*(?:"
    r"\(\s*(\d{1,3}|\*+)\s*\)"
    r"|\[(\d{1,3}|\*+)\]"
    r"|(\d{1,3})\s*[\.\)\-–—]\s+"
    r"|(\d{1,3})\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇÜÑ\"'“”«\(\[])"
    r"|(\*+)\s+"
    r"|([⁰¹²³⁴⁵⁶⁷⁸⁹]{1,3})\s*"
    r")"
)
NOTA_OCR_QUEBRADA_RE = re.compile(
    r"^\s*([+:;\-~•·'\"]?\s*\d{0,2}[\.,])\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇÜÑ][a-zA-ZÀ-ÿ\.\s]{2,})"
)


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def sem_marcas(t):
    return re.sub(r"[\x01-\x06]", "", t)


def percentil(v, p):
    if not v:
        return 0.0
    v = sorted(v)
    return v[min(len(v) - 1, max(0, int(len(v) * p)))]


def mediana_ponderada(pares):
    if not pares:
        return 10.0
    pares = sorted(pares)
    total = sum(w for _, w in pares)
    acc = 0
    for v, w in pares:
        acc += w
        if acc >= total / 2:
            return v
    return pares[-1][0]


def normaliza_sup_ocr(txt_sup):
    """Converte chamadas como '¹o', '¹"', '¹¹' em números limpos."""
    s = txt_sup.translate(SUPERSCRIPT_MAP)
    s = s.replace("o", "0").replace("O", "0").replace("l", "1").replace("I", "1")
    if s in ("*", "(*)", "**"):
        return "*"
    m = re.match(r"^(\d{1,3})$", s)
    return m.group(1) if m else s


def extrai_linhas_pagina(page, corpo_estimado=None):
    """Extrai linhas preservando itálico, negrito e chamadas de nota em sobrescrito."""
    d = page.get_text("dict", sort=True, clip=page.rect)
    out = []

    # Primeiro calcula o tamanho médio da página se corpo_estimado não foi dado
    tamanhos = []
    for b in d.get("blocks", []):
        if b.get("type") == 0:
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    if s["text"].strip():
                        tamanhos.append((round(s["size"], 1), len(s["text"].strip())))
    ref_size = corpo_estimado or mediana_ponderada(tamanhos)

    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            spans = [s for s in l.get("spans", []) if s["text"]]
            utos = [s for s in spans if s["text"].strip()]
            if not utos:
                continue

            maior = max(utos, key=lambda s: len(s["text"].strip()))
            line_size = maior["size"]
            line_y0, line_y1 = l["bbox"][1], l["bbox"][3]
            line_h = max(1.0, line_y1 - line_y0)

            partes, raw_parts = [], []
            for idx, s in enumerate(spans):
                t = s["text"]
                raw_parts.append(t)
                t_strip = t.strip()
                if not t_strip:
                    partes.append(t)
                    continue

                f = s["font"].lower()
                flags = s["flags"]
                is_sup_flag = bool(flags & 1)
                # Detecta itálico: flag (2) OU nome da fonte contendo variantes de itálico/oblíquo
                italic_keywords = ("italic", "oblique", "slant", "cursive", "kursiv", "kurs", "ital", "it ")
                is_ital = PRESERVAR_ITALICO and bool((flags & 2) or any(kw in f for kw in italic_keywords))
                is_bold = bool((flags & 16) or "bold" in f or "black" in f)

                # Verifica se o span é uma chamada de nota em sobrescrito (menor e mais alto na linha)
                sy0, sy1 = s["bbox"][1], s["bbox"][3]
                elevado = (sy1 < line_y1 - line_h * 0.15) and (s["size"] < line_size * 0.88)
                so_sup_unicode = any(c in SUPERSCRIPT_CHARS for c in t_strip) and len(t_strip) <= 4
                candidato_num = bool(re.match(r"^[\(\[]?(\d{1,3}|\*+|[⁰¹²³⁴⁵⁶⁷⁸⁹]{1,3}[oO\"']?)[\)\]]?$", t_strip))

                if idx > 0 and candidato_num and (is_sup_flag or elevado or so_sup_unicode):
                    num_limpo = normaliza_sup_ocr(t_strip.strip("()[]"))
                    partes.append(MARCA_I + num_limpo + MARCA_F)
                    continue

                # Converte caracteres Unicode sobrescritos colados dentro de um span normal (ex: "dela.¹", "anterior¹o")
                def _sub_sup_unicode(m):
                    prefixo = m.group(1)
                    sup_part = normaliza_sup_ocr(m.group(2))
                    return prefixo + MARCA_I + sup_part + MARCA_F

                t_proc = re.sub(
                    r"([A-Za-zÀ-ÿ\.,;:!\?\)”\"’])([⁰¹²³⁴⁵⁶⁷⁸⁹]{1,3}[oO]?)",
                    _sub_sup_unicode,
                    t
                )

                if is_ital:
                    t_proc = ABRE_IT + t_proc + FECHA_IT
                if is_bold and line_size > ref_size * 1.05:
                    t_proc = ABRE_NE + t_proc + FECHA_NE
                partes.append(t_proc)

            x0, y0, x1, y1 = l["bbox"]
            raw = "".join(raw_parts).strip()
            txt = "".join(partes).strip()

            # Trata hifens suaves (\u00ad) e caractere de substituição \ufffd () no fim da linha
            txt = re.sub(r"(\u00ad|\ufffd)(?=" + FECHA_IT + r"?" + FECHA_NE + r"?$)", "-", txt)
            txt = txt.replace("\u00ad", "")
            raw = re.sub(r"\ufffd$", "-", raw)

            if not raw:
                continue
            _tk = raw.split()
            if len(_tk) >= 4 and all(len(w) == 1 for w in _tk):   # título com letras espaçadas
                raw = "".join(_tk)
                txt = "".join(sem_marcas(txt).split())
            out.append({
                "t": txt, "raw": raw, "norm": norm(raw),
                "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "size": line_size, "bold": any((s["flags"] & 16) or "bold" in s["font"].lower() for s in utos)
            })
    return out


def detecta_cabecalhos_rodapes_repetidos(paginas):
    """Detecta cabeçalhos no topo e títulos correntes no rodapé em qualquer livro."""
    cont_cab = Counter()
    cont_rod = Counter()
    for pg in paginas:
        H = pg["H"]
        for i, l in enumerate(pg["linhas"]):
            k = re.sub(r"\b(\d{1,4}|[ivxlcdm]{1,6})\b", "", l["norm"]).strip()
            if len(k) < 3 or len(l["raw"]) > 95:
                continue
            if l["y0"] < H * ZONA_CAB or i == 0:
                cont_cab[k] += 1
            if l["y1"] > H * ZONA_ROD or i == len(pg["linhas"]) - 1:
                cont_rod[k] += 1

    limite = max(3, int(len(paginas) * 0.025))
    rep_cab = {k for k, v in cont_cab.items() if v >= limite}
    rep_rod = {k for k, v in cont_rod.items() if v >= limite}
    return rep_cab, rep_rod


def eh_lixo(l, idx_linha, total_linhas, H, rep_cab, rep_rod, tam_med=0.0):
    raw = l["raw"].strip()
    if not raw:
        return True
    # Ruído de OCR de 1 caractere não alfanumérico nas bordas
    if len(raw) <= 2 and not any(c.isalnum() for c in raw):
        return True

    no_topo = (l["y0"] < H * ZONA_CAB) or (idx_linha == 0 and l["y0"] < H * 0.14)
    na_base = (l["y1"] > H * ZONA_ROD) or (idx_linha == total_linhas - 1 and l["y1"] > H * 0.86)

    # Linha maior que o corpo da pagina: titulo de capitulo ou numero de
    # capitulo.  Cabeçalho corrente e numero de folha nunca sao maiores que o
    # texto, por isso essas linhas nao podem ser descartadas como ruido.
    grande = bool(tam_med) and l["size"] > tam_med * 1.15

    if not grande:
        if (no_topo or na_base) and CARIMBO_RE.search(raw):
            return True

        if (no_topo or na_base) and NUM_PAG_RE.match(raw):
            return True

    k = re.sub(r"\b(\d{1,4}|[ivxlcdm]{1,6})\b", "", l["norm"]).strip()
    if not grande and no_topo and k in rep_cab and len(raw) <= 95:
        return True
    if not grande and na_base and k in rep_rod and len(raw) <= 95:
        return True

    # Rodapé corrente com número na ponta (ex: "10 PEDRO DA SILVA MOREIRA" ou "INTRODUÇÃO 39")
    if na_base and len(raw) <= 65 and not raw.endswith("."):
        letras = [c for c in raw if c.isalpha()]
        if letras and all(c.isupper() for c in letras):
            if re.match(r"^(\d{1,4}\s+.+|.+\s+\d{1,4})$", raw):
                return True
    return False


def _eh_capitular(l, corpo):
    """Linha que é apenas a letra capitular de um parágrafo (drop cap)."""
    raw = (l["raw"] or "").strip()
    return (len(raw) == 1 and raw.isalpha() and l["size"] >= corpo * 1.3)


def une_capitulares(linhas, corpo):
    """Une letras capitulares (Drop Caps) isoladas, como 'F' + 'riedrich' -> 'Friedrich'."""
    if len(linhas) < 2:
        return linhas
    out = []
    i = 0
    while i < len(linhas):
        atual = linhas[i]
        raw = atual["raw"].strip()
        if (len(raw) == 1 and raw.isalpha() and raw.isupper() and i + 1 < len(linhas)):
            prox = linhas[i + 1]
            prox_raw = prox["raw"].lstrip()
            # Se a próxima linha começa com minúscula (ex: "riedrich") ou está na mesma faixa vertical
            mesma_faixa = abs(atual["y0"] - prox["y0"]) < corpo * 3.5
            comeca_minuscula = prox_raw[:1].islower()
            if mesma_faixa and (comeca_minuscula or atual["size"] > corpo * 1.3):
                sep = "" if comeca_minuscula else " "
                prox = dict(prox)
                prox["raw"] = raw + sep + prox["raw"].lstrip()
                prox["t"] = raw + sep + prox["t"].lstrip()
                prox["norm"] = norm(prox["raw"])
                prox["x0"] = min(atual["x0"], prox["x0"])
                i += 1
                out.append(prox)
                i += 1
                continue
        out.append(atual)
        i += 1
    return out


def margens(linhas, corpo):
    cl = [l for l in linhas if l["size"] >= corpo * LIM_NOTA]
    if len(cl) < 4:
        return None
    return percentil([l["x0"] for l in cl], 0.15), percentil([l["x1"] for l in cl], 0.85)


def extrai_num_nota_inicio(raw, ultimo_num=None):
    """Extrai o identificador inicial de uma nota de rodapé/fim, recuperando falhas de OCR."""
    m = NOTA_INICIO_RE.match(raw)
    if m:
        for g in m.groups():
            if g:
                return normaliza_sup_ocr(g)
    if ultimo_num is not None and str(ultimo_num).isdigit():
        m_ocr = NOTA_OCR_QUEBRADA_RE.match(raw)
        if m_ocr:
            return str(int(ultimo_num) + 1)
    return None


def separa_corpo_e_notas_pagina(pg, corpo, glob, em_bloco_notas_fim=False):
    """
    Separa com precisão linhas do corpo, citações recuadas e notas de rodapé da página.
    Não confunde citações recuadas no meio da página com notas de rodapé.
    Preserva recuo original de citações longas.
    """
    linhas = une_capitulares(pg["linhas"], corpo)
    W, H = pg["W"], pg["H"]
    esq, dire = margens(linhas, corpo) or glob

    # Calcula recuo médio do corpo para detectar citações com recuo preservado
    linhas_corpo = [l for l in linhas if l["size"] >= corpo * LIM_NOTA]
    recuo_corpo_medio = base.percentil([l["x0"] for l in linhas_corpo], 0.5) if linhas_corpo else esq

    for l in linhas:
        raw = l["raw"].strip()
        l["pequena"] = l["size"] < corpo * LIM_NOTA
        l["indent"] = l["x0"] > esq + W * 0.025
        # Threshold aumentado: 0.10 (era 0.065) para evitar falsos positivos
        # Citação real tem recuo substancial e consistente
        l["recuo_g"] = l["x0"] > esq + W * 0.10
        # Detecta citações longas: recuo maior que o corpo + 10% da largura útil
        l["recuo_citacao"] = l["x0"] > recuo_corpo_medio + W * 0.10
        l["curto"] = l["x1"] < dire - W * 0.12
        l["centrado"] = (l["x0"] > esq + W * 0.10) and (l["x1"] < dire - W * 0.10)
        l["tipo"] = "corpo"
        l["nivel"] = 2

        letras = [c for c in raw if c.isalpha()]
        grande = l["size"] >= corpo * 1.12
        caixa_alta = len(letras) >= 3 and all(c.isupper() for c in letras) and len(raw) <= 110
        num_cap_isolado = bool( re.match(r"^(\d{1,2}|[IVXLC]{1,5})$", raw) ) and (grande or l["centrado"])
        sub = (bool(SUB_RE.match(raw)) and len(raw) <= 95 and (l["curto"] or l["bold"] or grande)
               and not raw.endswith((".", ";", ",")))

        if not l["pequena"] and (grande or caixa_alta or num_cap_isolado or sub):
            l["tipo"] = "h"
            l["nivel"] = 1 if (grande or caixa_alta or num_cap_isolado) else 2

    if em_bloco_notas_fim:
        # Se estamos dentro de uma seção explícita "NOTAS", linhas normais/pequenas pertencem às notas
        # até que apareça um título de capítulo (h de nível 1 grande/caixa alta no topo)
        corpo_l, notas_l = [], []
        saiu_notas = False
        for idx, l in enumerate(linhas):
            if not saiu_notas and l["tipo"] == "h" and l["nivel"] == 1 and idx < 4 and l["norm"] != "notas":
                saiu_notas = True
            if saiu_notas:
                corpo_l.append(l)
            else:
                notas_l.append(l)
        return corpo_l, notas_l, saiu_notas

    # Verifica se nesta página começa uma seção explícita "NOTAS"
    for idx, l in enumerate(linhas):
        if l["norm"] == "notas" and (l["tipo"] == "h" or l["curto"]):
            return linhas[:idx], linhas[idx + 1:], True

    # Deteção geométrica de zona de notas de rodapé no fundo da página:
    # As notas de rodapé ficam na parte inferior da página e todas as linhas abaixo do início
    # do rodapé têm fonte menor (ou começam com marcador de nota).
    idx_rodape = None
    n = len(linhas)
    for idx in range(n):
        l = linhas[idx]
        if l["y0"] < H * 0.35:
            continue
        resto = linhas[idx:]
        # Para ser rodapé de página, pelo menos 80% das linhas restantes até o fim da página devem ser pequenas
        if all(r["pequena"] for r in resto):
            tem_inicio_nota = any(extrai_num_nota_inicio(r["raw"]) is not None for r in resto[:3])
            salto_y = (idx > 0) and ((l["y0"] - linhas[idx - 1]["y1"]) > corpo * 0.6)
            if tem_inicio_nota or (salto_y and l["y0"] > H * 0.55 and not l["recuo_g"]):
                idx_rodape = idx
                break

    if idx_rodape is not None:
        return linhas[:idx_rodape], linhas[idx_rodape:], False
    return linhas, [], False


def junta(a, b):
    """Junta duas strings preservando marcadores de itálico/negrito/sobrescrito.
    Não insere espaço se a junção seria dentro de uma formatação (ex: FECHA_IT seguido de ABRE_IT)."""
    a2 = a.rstrip(FECHA_IT + FECHA_NE)
    tail = a[len(a2):]
    
    # Check b for opening markers BEFORE stripping
    b_starts_with_abre_it = b.startswith(ABRE_IT)
    b_starts_with_abre_ne = b.startswith(ABRE_NE)
    b_clean = b.lstrip(ABRE_IT + ABRE_NE)

    # Trata palavra quebrada com hífen ou com caractere  no meio/fim
    if a2.endswith("-") or a2.endswith("�"):
        if b_clean[:1].islower():
            m = re.search(r"([A-Za-zÀ-ÿ]+)[-�]$", sem_marcas(a2))
            pref = m.group(1).lower() if m else ""
            if pref in PROTEGIDOS and a2.endswith("-"):
                return a + b
            return a2[:-1] + tail + b

    # Preserva formatação inline: não insere espaço entre FECHA_IT e ABRE_IT
    # ou entre FECHA_NE e ABRE_NE (continuidade de itálico/negrito)
    if tail and b_clean:
        if (tail == FECHA_IT and b_starts_with_abre_it) or            (tail == FECHA_NE and b_starts_with_abre_ne) or            (tail == FECHA_IT + FECHA_NE and (b_starts_with_abre_it or b_starts_with_abre_ne)) or            (tail == FECHA_NE + FECHA_IT and (b_starts_with_abre_it or b_starts_with_abre_ne)):
            return a + b

    return a + " " + b


def limpa(t):
    t = re.sub(r"[\x00\x07-\x08\x0b-\x1f]", "", t)
    # Remove  entre duas letras minúsculas (hífen de quebra de linha mal decodificado pelo OCR)
    t = re.sub(r"(?<=[a-zà-ÿ])\ufffd\s*(?=[a-zà-ÿ])", "", t)
    t = t.replace("\ufffd", "")
    for pat, rep in CORRECOES:
        t = re.sub(pat, rep, t)
    t = re.sub(FECHA_IT + r"(\s*)" + ABRE_IT, r"\1", t)
    t = re.sub(FECHA_NE + r"(\s*)" + ABRE_NE, r"\1", t)
    return t.strip()


def fim_de_frase(t):
    """True se o texto termina uma frase (. ? ! …), ignorando aspas, parênteses e chamadas de nota."""
    t = re.sub(r"\x03[^\x04]*\x04", "", t)
    t = sem_marcas(t).rstrip()
    return bool(re.search(r"[.?!…][\"”»’')\]]*\d{0,2}$", t))


def monta_corpo(linhas, corpo):
    pars, atual, prev = [], None, None
    for l in linhas:
        if l["tipo"] == "h":
            salto_y = (prev is not None) and ((l["y0"] - prev["y1"]) > corpo * 1.8)
            if atual and atual["tipo"] == "h" and not salto_y and abs(l["size"] - prev["size"]) < 2.5:
                atual["t"] = junta(atual["t"], l["t"])
                atual["nivel"] = min(atual["nivel"], l["nivel"])
            else:
                atual = {"tipo": "h", "t": l["t"], "nivel": l["nivel"]}
                pars.append(atual)
            prev = l
            continue

        # Linha de corpo ou citação recuada
        # Heurística: citação real tem TODAS as linhas com recuo consistente (recuo_g)
        # Não só a primeira linha. Verifica se as próximas linhas também têm recuo_g.
        # Usa recuo_citacao para preservar formatação original de citações longas
        eh_cit = l["recuo_g"] or l.get("recuo_citacao", False)
        # Se for candidato a citação (recuo_g), verifica consistência nas próximas linhas
        if eh_cit:
            # Olha para frente: próximas 3-5 linhas também devem ter recuo_g ou serem pequenas/indentadas
            # Se a maioria NÃO tiver recuo, provavelmente é só recuo de parágrafo normal
            prox_com_recuo = 0
            prox_total = 0
            for prox in linhas[linhas.index(l):min(len(linhas), linhas.index(l)+5)]:
                if prox is l:
                    continue
                prox_total += 1
                if prox["recuo_g"] or prox.get("recuo_citacao", False) or (prox["pequena"] and prox["indent"]):
                    prox_com_recuo += 1
                elif prox["tipo"] == "h" or not prox["raw"].strip():
                    break  # título ou linha vazia = fim do bloco
            # Exige pelo menos 60% das próximas linhas com recuo para ser citação
            if prox_total > 0 and prox_com_recuo / prox_total < 0.6:
                eh_cit = False
        # Fallback original: pequena + indent
        elif l["pequena"] and l["indent"]:
            eh_cit = True
        novo = (atual is None) or (atual["tipo"] != "corpo") or (atual.get("cit", False) != eh_cit)
        if atual is not None and atual["tipo"] == "corpo":
            fim = fim_de_frase(atual["t"])
            minus = l["t"].lstrip(ABRE_IT + ABRE_NE)[:1].islower()
            termina_hifen = atual["t"].rstrip(FECHA_IT + FECHA_NE).endswith(("-", "\ufffd"))
            if minus or termina_hifen or not fim:
                novo = False      # continuação óbvia: frase não terminou ou a linha começa em minúscula
            elif not novo and prev is not None:
                salto_grande = (l["y0"] - prev["y1"]) > corpo * 1.45
                if salto_grande or prev["curto"] or (l["indent"] and not eh_cit):
                    novo = True

        if novo:
            atual = {"tipo": "corpo", "t": l["t"], "cit": eh_cit}
            pars.append(atual)
        else:
            atual["t"] = junta(atual["t"], l["t"])
        prev = l
    return pars


def monta_notas(linhas):
    """Agrupa linhas de notas (qualquer formato: (1), 1., 1 , *, etc.) em notas completas."""
    notas = []
    ultimo_num = None
    for l in linhas:
        raw = l["raw"].strip()
        if norm(raw) == "notas" and len(raw) <= 10:
            continue
        num = extrai_num_nota_inicio(raw, ultimo_num)
        # Também inicia nova nota se a linha tem recuo de parágrafo de nota ou a anterior terminou curta
        if num is not None or not notas:
            if num is not None:
                ultimo_num = num
                # Normaliza o prefixo caso o OCR tenha quebrado (ex: "+. Gustav Hugo" -> "14. Gustav Hugo")
                if NOTA_INICIO_RE.match(raw) is None and NOTA_OCR_QUEBRADA_RE.match(raw):
                    l_t = re.sub(r"^\s*[+:;\-~•·'\"]?\s*\d{0,2}[\.,]\s*", f"{num}. ", l["t"])
                else:
                    l_t = l["t"]
            else:
                l_t = l["t"]
            notas.append({"num": num, "t": l_t})
        else:
            notas[-1]["t"] = junta(notas[-1]["t"], l["t"])
    return notas


def vincula_chamadas_no_corpo(pars, notas):
    """
    Garante que todas as notas da seção/página tenham sua chamada em sobrescrito (MARCA_I...MARCA_F)
    posicionada exatamente depois da palavra correspondente no corpo.
    """
    validos = [n["num"] for n in notas if n.get("num")]
    if not validos:
        return

    # Verifica quais números já estão marcados por detecção de span em sobrescrito
    ja_marcados = set()
    for p in pars:
        for m in re.finditer(re.escape(MARCA_I) + r"([^\x04]+)" + re.escape(MARCA_F), p["t"]):
            ja_marcados.add(m.group(1))

    faltantes = [n for n in validos if n not in ja_marcados]
    if not faltantes:
        return

    # Procura números colados à palavra ou após pontuação no texto (ex: "oral,2", "Möser16", "ruptura. 10")
    alt = "|".join(re.escape(x) for x in sorted(set(faltantes), key=len, reverse=True))
    rx = re.compile(
        rf"(?<=[A-Za-zÀ-ÿ\.,;:!\?\)”\"’»])(\s?)({alt})(?=[\s,.;:!\?\)”\"’»]|$)"
    )

    for p in pars:
        if p["tipo"] != "corpo":
            continue

        def _sub(m):
            esp, num = m.group(1), m.group(2)
            # com espaço antes do número, só vale se vier depois de pontuação (evita 'os 2 tomos')
            if esp and m.string[m.start() - 1:m.start()].isalpha():
                return m.group(0)
            antes = m.string[max(0, m.start() - 18):m.start()]
            # Ignora números que fazem parte de páginas, capítulos, anos, artigos, parágrafos ou volumes
            if re.search(r"\b(pp?|cap|vol|ed|ano|art|arts|sec|seç|n|no|nº|t|v|l|c)\.\s*$", antes, re.I):
                return m.group(0)
            if re.search(r"(Apêndice|Anexo|Parte| Livro|Tomo|Capítulo|Secção|Seção|§|§§)\s*$", antes, re.I):
                return m.group(0)
            return MARCA_I + num + MARCA_F

        p["t"] = rx.sub(_sub, p["t"])


CORRIGIR_OCR = True  # corrige palavras raras que diferem de uma palavra frequente do livro por erro típico de OCR


def _sem_acento(w):
    return "".join(c for c in unicodedata.normalize("NFD", w) if unicodedata.category(c) != "Mn")


def acha_correcoes_ocr(textos):
    """Usa o vocabulário do próprio livro: uma palavra que aparece 1 vez e difere de uma palavra
    frequente (6+ vezes) só por uma confusão típica de OCR (c/e, i/l, h/b, t/l) ou só pela falta
    de acento é trocada pela frequente. Retorna {errada: certa}."""
    if not CORRIGIR_OCR:
        return {}
    pares = {("c", "e"), ("e", "c"), ("i", "l"), ("l", "i"), ("h", "b"), ("b", "h"), ("t", "l"), ("l", "t")}
    cont = Counter()
    for t in textos:
        cont.update(re.findall(r"[A-Za-zÀ-ÿ]{5,}", sem_marcas(t)))
    por_tam = {}
    for w, c in cont.items():
        if c >= 6 and w.islower():
            por_tam.setdefault(len(w), []).append(w)
    troca = {}
    for w, c in cont.items():
        if c != 1 or not w.islower():
            continue
        for f in por_tam.get(len(w), []):
            dif = [(x, y) for x, y in zip(w, f) if x != y]
            if (len(dif) == 1 and dif[0] in pares) or (w == _sem_acento(f) and w != f):
                troca[w] = f
                break
    return troca


def aplica_correcoes_ocr(t, troca):
    if not troca:
        return t
    rx = re.compile(r"(?<![A-Za-zÀ-ÿ])(" + "|".join(map(re.escape, troca)) + r")(?![A-Za-zÀ-ÿ])")
    return rx.sub(lambda m: troca[m.group(1)], t)


def xml_seguro(t):
    return re.sub(r"[\x00\x07\x08\x0b\x0c\x0e-\x1f]", "", t)


def tokens_docx(par, t, tam=None):
    from docx.shared import Pt
    it = ne = sup = False
    for s in re.split(r"([\x01-\x06])", xml_seguro(t)):
        if s == ABRE_IT:
            it = True
        elif s == FECHA_IT:
            it = False
        elif s == ABRE_NE:
            ne = True
        elif s == FECHA_NE:
            ne = False
        elif s == MARCA_I:
            sup = True
        elif s == MARCA_F:
            sup = False
        elif s:
            r = par.add_run(s)
            r.italic = it
            r.bold = ne
            r.font.superscript = sup
            if tam:
                r.font.size = Pt(tam)



base = sys.modules[__name__]  # as funções do motor estão neste mesmo arquivo

# ----------------------------------------------------------------------------
# CONFIGURAÇÃO OPCIONAL (Se deixado None/vazio, o script detecta tudo sozinho)
# ----------------------------------------------------------------------------
TITULO_LIVRO = None
AUTOR = None
SUBTITULO = ""
HIFENIZAR_PDF = True

# Palavras-chave de seções pré-textuais e pós-textuais universais
SECOES_ESPECIAIS_RE = re.compile(
    r"^(nota\s+introdutoria|nota\s+do\s+editor|nota\s+editorial|apresentacao|presentacion|"
    r"palavras\s+preliminares|palabras\s+preliminares|prefacio.*|prologo|introducao|"
    r"introduccion|conclusao|posfacio|apendice.*|anexo.*|referencias|bibliografia)$",
    re.I
)

# Divisores de "Parte" (maiores que capítulo) - variações multilíngues
PARTE_RE = re.compile(
    r"^(parte|part|book|livro|volume|tom[ao])\s*[:\-–—]?\s*"
    r"([IVXLC]{1,7}|\d{1,3}|(primeir[ao]|segund[ao]|terceir[ao]|quart[ao]|quint[ao]|sext[ao]|s[eé]tim[ao]|oitav[ao]|n[oa]v[ao]|d[eé]cim[ao]))",
    re.I
)
SUMARIO_TITULO_RE = re.compile(r"^(sumario|indice|conteudo|tabla\s+de\s+contenidos|table\s+of\s+contents|contents)"
                               r"(\s+(geral|analitico|resumido|do\s+livro|da\s+obra))?$", re.I)
LINHA_SUMARIO_RE = re.compile(
    r"^\s*(?:(\d{1,2}(?:\.\d{1,2}){0,3}|[IVXLC]{1,5})[\.\s\-–—]+)?(.+?)\s*[\.…\s\|]{2,}\s*(\d{1,4})\s*$"
)


def detecta_folha_de_rosto(paginas, corpo):
    """
    Reconoce uma folha de rosto tipográfica nas primeiras páginas: poucas linhas,
    curtas e centralizadas (título, autor, tradução). Devolve
    (índices das páginas, título, autor, subtítulo) ou None.

    Assim o livro não sai com a folha de rosto original repetida no meio do texto,
    e o título/autor são aproveitados em vez de inventados.
    """
    for pi, pg in enumerate(paginas[:4]):
        linhas = [l for l in pg["linhas"] if base.sem_marcas(l["raw"]).strip()]
        if not (2 <= len(linhas) <= 12):
            continue
        W, H = pg["W"], pg["H"]
        if max((l["x1"] - l["x0"]) / W for l in linhas) > 0.72:
            continue
        if sum(1 for l in linhas if l["x0"] > W * 0.12) < max(2, len(linhas) - 1):
            continue
        ys = sorted(l["y0"] for l in linhas)
        if (ys[-1] - ys[0]) > H * 0.55:
            continue
        if sum(1 for l in linhas if l["raw"].strip().endswith(".")) > 1:
            continue
        if max(l["size"] for l in linhas) < corpo * 1.2:
            continue

        maior = max(l["size"] for l in linhas)
        limiar = max(corpo * 1.25, maior * 0.85)
        tit_linhas = [l for l in linhas if l["size"] >= limiar]
        outras = [l for l in linhas if l["size"] < limiar]
        if not tit_linhas:
            continue
        titulo = " ".join(l["raw"].strip() for l in tit_linhas)
        resto = [l["raw"].strip() for l in outras]
        autor = subtitulo = ""
        if resto:
            m = re.match(r"^(?:POR|DE|BY)\s*[:\-–—]?\s*(.+)$", resto[0], re.I)
            if m:
                autor = m.group(1).strip(" ,;:-")
                resto = resto[1:]
            elif len(resto) == 2:
                letras = [c for c in resto[0] if c.isalpha()]
                if letras and all(c.isupper() for c in letras) and 1 <= len(resto[0].split()) <= 4:
                    autor = resto[0]
                    resto = resto[1:]
        subtitulo = " ".join(resto[:2]).strip(" ,;:-")
        return [pi], titulo, autor, subtitulo
    return None


# Palavras-chave para detectar ficha catalográfica (páginas técnicas de biblioteca)
FICHA_CATALOGRAFICA_RE = re.compile(
    r"(cataloga|catalogação|catalogr|ficha\s+catalo|"
    r"cip\b|isbn\s*\d|issn\s*\d|"
    r"cdu\s*\d|cutter\s*\d|classifica[cç][aã]o|"
    r"dados\s+internacionais|dados\s+de\s+cataloga|"
    r"biblioteca\s+nacional|biblioteca\s+do\s+congresso|"
    r"serviço\s+de\s+cataloga|preparada\s+pelo|elaborada\s+pelo|"
    r"direitos\s+reservados|proibida\s+a\s+reprodu[cç][aã]o|"
    r"impresso\s+no\s+brasil|impress[ãa]o\s+\d{4}|"
    r"edição\s+conforme|acordo\s+ortogr[áa]fico)",
    re.I
)


def detecta_ficha_catalografica(paginas):
    """
    Detecta páginas de ficha catalográfica nas primeiras 8 páginas.
    Retorna conjunto de índices de páginas a remover.
    """
    indices_ficha = set()

    for idx, pg in enumerate(paginas[:8]):
        texto_pg = "\n".join(l["raw"] for l in pg["linhas"])
        linhas_validas = [l for l in pg["linhas"] if l["raw"].strip()]

        # Critérios para ficha catalográfica:
        # 1. Tem palavras-chave de ficha
        tem_palavras_chave = bool(FICHA_CATALOGRAFICA_RE.search(texto_pg))

        # 2. Layout denso: muitas linhas, texto alinhado à esquerda, pouca variação de fonte
        n_linhas = len(linhas_validas)
        if n_linhas < 8:
            continue

        # 3. Verifica se tem padrão "Sobrenome, Nome" (autor na ficha)
        tem_autor_ficha = bool(re.search(r"[A-ZÀ-Ý][a-zà-ÿ]+,\s+[A-ZÀ-Ý][a-zA-ZÀ-ÿ\s]{3,}", texto_pg))

        # 4. Não é sumário/índice (já detectado separadamente)
        pags_sumario, _, _ = detecta_paginas_sumario_original(paginas)
        if idx in pags_sumario:
            continue

        # 5. Não é folha de rosto (já detectada separadamente)
        # Folha de rosto tem poucas linhas (2-12), ficha tem muitas

        if tem_palavras_chave and (tem_autor_ficha or n_linhas >= 15):
            indices_ficha.add(idx)

    return indices_ficha


def infere_metadados(doc, paginas):
    """Infere Título e Autor automaticamente dos metadados ou das primeiras páginas."""
    titulo = TITULO_LIVRO
    autor = AUTOR

    meta = doc.metadata or {}
    if not titulo and meta.get("title") and len(meta["title"].strip()) > 3:
        titulo = meta["title"].strip()
    if not autor and meta.get("author") and len(meta["author"].strip()) > 3:
        autor = meta["author"].strip()

    # Inspeciona as primeiras 6 páginas (capa / folha de rosto / ficha catalográfica)
    linhas_iniciais = []
    for pg in paginas[:6]:
        for l in pg["linhas"]:
            raw = l["raw"].strip()
            if len(raw) >= 4 and not re.search(r"(isbn|copyright|direitos|impressão|ed\.|edição|\d{4})", raw, re.I):
                linhas_iniciais.append(l)

    if not titulo and linhas_iniciais:
        maior_l = max(linhas_iniciais, key=lambda x: x["size"])
        # Junta linhas vizinhas de mesmo tamanho na mesma página (títulos de múltiplas linhas)
        for pg in paginas[:6]:
            if maior_l in pg["linhas"]:
                mesmo_tam = [
                    x["raw"].strip() for x in pg["linhas"]
                    if abs(x["size"] - maior_l["size"]) < 1.5 and len(x["raw"].strip()) > 2
                ]
                titulo = " ".join(mesmo_tam[:3])
                break

    if not autor and linhas_iniciais:
        # Procura padrão de ficha catalográfica "Sobrenome, Nome" nas primeiras páginas
        pags_toc, _, _ = detecta_paginas_sumario_original(paginas)
        for idx_pg, pg in enumerate(paginas[:8]):
            texto_pg = "\n".join(l["raw"] for l in pg["linhas"])
            if idx_pg in pags_toc or not re.search(r"(cip\b|cataloga|isbn|ficha\s+catalogr)", texto_pg, re.I):
                continue
            m_ficha = re.search(r"([A-ZÀ-Ý][a-zà-ÿ]+,\s+[A-ZÀ-Ý][a-zA-ZÀ-ÿ\s]{3,40}?)(?:,\s*\d{4}|\n)", texto_pg)
            if m_ficha:
                partes = [p.strip() for p in m_ficha.group(1).split(",", 1)]
                autor = f"{partes[1]} {partes[0]}" if len(partes) == 2 else partes[0]
                break

    if not titulo:
        titulo = os.path.splitext(os.path.basename(doc.name))[0].replace("_", " ").upper()
    if not autor:
        autor = "Autor"

    return titulo.upper(), autor, SUBTITULO


def detecta_paginas_sumario_original(paginas):
    """Identifica páginas que pertencem ao Sumário/Índice original do PDF e extrai entradas.
    Diferencia entre sumário analítico (detalhado, com subcapítulos) e sumário resumido (apenas capítulos)."""
    pags_sumario = set()
    entradas_toc = []
    entradas_subcapitulos = []

    for idx, pg in enumerate(paginas):
        linhas = pg["linhas"]
        if not linhas:
            continue
        textos_norm = [l["norm"] for l in linhas]
        # a palavra "Sumário/Índice" vale em qualquer ponto da metade superior da página (ou nas últimas linhas)
        tem_titulo_sumario = any(
            SUMARIO_TITULO_RE.match(l["norm"]) for l in linhas if l["y0"] < pg["H"] * 0.5
        ) or any(SUMARIO_TITULO_RE.match(t) for t in textos_norm[-3:])
        linhas_com_num_dir = sum(
            1 for l in linhas if re.search(r"(\.{2,}|\|)\s*\d{1,4}\s*$|^\d{1,3}$|\S\s{1,}\d{1,4}$", l["raw"].strip())
        )

        # Detecta se é sumário analítico (tem entradas com numeração hierárquica: 1.1, 1.2, 2.1.3, etc.)
        tem_subcapitulos = any(
            re.match(r"^\s*\d+(\.\d+)+\s+", l["raw"].strip()) for l in linhas
        )

        if tem_titulo_sumario or (idx in pags_sumario) or (idx < 20 and linhas_com_num_dir >= 6):
            if tem_titulo_sumario or (idx - 1 in pags_sumario and linhas_com_num_dir >= 3):
                pags_sumario.add(idx)
                for l in linhas:
                    raw = l["raw"].strip()
                    if SUMARIO_TITULO_RE.match(l["norm"]):
                        continue
                    # Remove pontuação pontilhada e números de página à direita
                    limpo = re.sub(r"[\.…\|]+\s*\d{1,4}\s*$", "", raw).strip()
                    limpo = re.sub(r"\s+\d{1,4}\s*$", "", limpo).strip()
                    if len(limpo) >= 3 and not limpo.isdigit():
                        # Classifica: capítulo principal (1., 2., CAPÍTULO 1) ou subcapítulo (1.1, 2.3.1)
                        if re.match(r"^(\d+|[IVXLC]+)(\.|$)", limpo) or limpo.upper().startswith("CAPÍTULO") or limpo.upper().startswith("CHAPTER"):
                            entradas_toc.append((base.norm(limpo), limpo))
                        elif tem_subcapitulos:
                            entradas_subcapitulos.append((base.norm(limpo), limpo))
                        else:
                            entradas_toc.append((base.norm(limpo), limpo))

    return pags_sumario, entradas_toc, entradas_subcapitulos


def verifica_inicio_capitulo_na_pagina(pg, corpo):
    """
    Verifica se a página inicia um capítulo ou seção principal.
    Retorna o título completo do capítulo e quantas linhas do topo compõem esse título,
    ou (None, 0) se a página for continuação normal.
    """
    linhas = pg["linhas"]
    if not linhas:
        return None, 0

    H = pg["H"]
    # capitular (letra grande e isolada no alto) nao abre capitulo: em livros
    # diagramados ela vem como propria linha e o texto continua na mesma pagina.
    # Mas guardamos ONDE ela apareceu: a linha que vem logo depois de uma capitular
    # e o INÍCIO DO CORPO do texto (muitas vezes em versalete/caixa-alta por estilo
    # tipográfico), nunca uma continuação do título - então a fronteira não pode
    # ser atravessada ao juntar linhas no título (ver `capitular_antes` abaixo).
    topo = []
    capitular_antes = []
    teve_capitular = False
    for l in linhas[:6]:
        if l["y0"] >= H * 0.48:
            continue
        if _eh_capitular(l, corpo):
            teve_capitular = True
            continue
        topo.append(l)
        capitular_antes.append(teve_capitular)
        teve_capitular = False
    if not topo:
        return None, 0

    l0 = topo[0]
    raw0 = l0["raw"].strip()
    norm0 = l0["norm"]

    def estende(partes_tit, usadas, cond_fn, maximo=4):
        """Acrescenta a `partes_tit` as linhas seguintes do topo que passam em
        `cond_fn`, mas para assim que uma capitular tiver aparecido antes da
        próxima linha (= começo do parágrafo do corpo, não do título)."""
        for pos in range(usadas, min(len(topo), maximo)):
            if capitular_antes[pos]:
                break
            ok, texto = cond_fn(topo[pos])
            if not ok:
                break
            partes_tit.append(texto)
            usadas += 1
        return partes_tit, usadas

    # Ignora página com apenas algarismo romano isolado de "Parte I / II / III" se não houver texto,
    # ou trata-a como divisor de Parte
    if len(linhas) == 1 and re.match(r"^[IVX]{1,4}$", raw0):
        return f"Parte {raw0}", 1

    # Caso 1: Seção especial conhecida (Introdução, Apresentação, Nota do Editor, Prefácio, Apêndice...)
    if SECOES_ESPECIAIS_RE.match(norm0) and len(raw0) <= 70:
        # Verifica se a linha seguinte também faz parte do título (ex: "PREFÁCIO DA / SEGUNDA EDIÇÃO / (1828)")
        # IMPORTANTE: Não capturar o início do texto do capítulo - apenas linhas que são
        # claramente continuação do título: edição, ano, subtítulo curto em caixa alta
        def cond1(l_next):
            r_next = l_next["raw"].strip()
            # Continuação de título: edição, ano entre parênteses, ou subtítulo em maiúsculas
            ok = (len(r_next) <= 75 and not r_next.endswith(".")
                  and (re.match(r"^\(\d{4}\)$", r_next)  # (1828)
                      or re.match(r"^(SEGUNDA|TERCEIRA|QUARTA|PRIMEIRA|2A|3A|4A)\s+EDI[CÇ][AÃ]O$", r_next, re.I)  # edições
                      or (r_next.isupper() and len(r_next.split()) <= 6)  # subtítulo curto em caixa alta
                      or l_next["size"] >= corpo * 1.15))  # fonte claramente maior
            return ok, r_next
        partes_tit, usadas = estende([raw0], 1, cond1)
        return " - ".join(partes_tit) if len(partes_tit) > 1 else partes_tit[0], usadas

    # Caso 1b: "CAPÍTULO 3", "CAP. III" ou "PARTE II" com o título na linha seguinte
    m_cap = re.match(r"^(capitulos?|caps?\.?|parte|part|chapter)\s+([IVXLC]{1,7}|\d{1,3})$",
                     norm0)
    if m_cap and len(topo) >= 2:
        def cond1b(l_next):
            r_next = l_next["raw"].strip()
            ok = (len(r_next) <= 85 and not r_next.endswith(".")
                  and (l_next["size"] >= corpo * 1.05 or r_next.isupper()))
            return ok, r_next
        partes_tit, usadas = estende([raw0], 1, cond1b)
        return " - ".join(partes_tit), usadas

    # Caso 1c: Divisor de "Parte" (ex: "PARTE I: TÍTULO", "BOOK 1", "VOLUME 2 - NOME")
    m_parte = PARTE_RE.match(norm0)
    if m_parte and len(topo) >= 2:
        # Captura o número/nome da parte + título na linha seguinte
        parte_prefixo = raw0
        def cond_parte(l_next):
            r_next = l_next["raw"].strip()
            ok = (len(r_next) <= 100 and not r_next.endswith(".")
                  and (l_next["size"] >= corpo * 1.0 or r_next.isupper()))
            return ok, r_next
        partes_tit, usadas = estende([parte_prefixo], 1, cond_parte)
        return " - ".join(partes_tit), usadas

    # Caso 1d: Página divisória só com "PARTE I" (sem título na mesma página)
    if re.match(r"^(parte|part|book|livro|volume|tom[ao])\s+([IVXLC]{1,7}|\d{1,3}|primeir[ao]|segund[ao]|terceir[ao]|quart[ao]|quint[ao])$", norm0, re.I) and len(linhas) <= 3:
        return raw0.upper(), 1

    # Caso 4: título grande e isolado no alto da pagina (ex: "O EMPREGO E A CONFIANÇA"),
    # sem numero, quando a pagina tem texto bastante para ser abertura de capitulo
    if (len(raw0) <= 90 and not raw0.endswith((".", ",", ";", ":"))
            and l0["size"] >= corpo * 1.4
            and sum(len(l["raw"]) for l in linhas[1:]) > 400):
        return raw0, 1

    # Caso 2: Número de capítulo isolado na linha 1 (ex: "1", "2", "12") e título logo abaixo
    if re.match(r"^\d{1,2}$", raw0) and len(topo) >= 2:
        partes_tit = [raw0 + "."]
        usadas = 1
        tam_tit = None
        for pos in range(1, min(len(topo), 4)):
            if capitular_antes[pos]:
                break
            l_next = topo[pos]
            r_next = l_next["raw"].strip()
            letras = [c for c in r_next if c.isalpha()]
            eh_titulo = (
                l_next["size"] >= corpo * 1.08
                or (letras and all(c.isupper() for c in letras))
                or (l_next["x1"] < pg["W"] * 0.82 and not r_next.endswith("."))
            )
            if eh_titulo and tam_tit is not None and abs(l_next["size"] - tam_tit) > 1.5:
                eh_titulo = False  # subtítulo de seção em corpo menor: não faz parte do título
            if eh_titulo and len(r_next) <= 85:
                if tam_tit is None:
                    tam_tit = l_next["size"]
                partes_tit.append(r_next)
                usadas += 1
            else:
                break
        if usadas >= 2:
            return " ".join(partes_tit), usadas

    # Caso 3: Capítulo numerado na mesma linha em destaque (ex: "1. FILOSOFIA DE LA POIESIS" ou "2. ESTUDIO PRELIMINAR...")
    m_num = re.match(r"^(\d{1,2})\.\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇÜÑ\"“].+)$", raw0)
    if m_num:
        letras = [c for c in raw0 if c.isalpha()]
        tudo_maiusculo = letras and all(c.isupper() for c in letras)
        fonte_grande = l0["size"] >= corpo * 1.12
        if tudo_maiusculo or fonte_grande:
            def cond3(l_next):
                r_next = l_next["raw"].strip()
                letras_n = [c for c in r_next if c.isalpha()]
                ok = bool(letras_n) and all(c.isupper() for c in letras_n) and len(r_next) <= 85
                return ok, r_next
            partes_tit, usadas = estende([raw0], 1, cond3, maximo=3)
            return " ".join(partes_tit), usadas

    return None, 0


def segmenta_em_capitulos(paginas, corpo, glob):
    """Divide qualquer livro em capítulos preservando textos iniciais e finais."""
    pags_sumario, _, _ = detecta_paginas_sumario_original(paginas)

    inicios = []
    for idx, pg in enumerate(paginas):
        if idx in pags_sumario or not pg["linhas"]:
            continue
        titulo_cap, linhas_usadas = verifica_inicio_capitulo_na_pagina(pg, corpo)
        if titulo_cap:
            inicios.append((idx, titulo_cap, linhas_usadas))

    if not inicios:
        return [{"titulo": "Texto Integral", "pags_indices": [i for i in range(len(paginas)) if i not in pags_sumario], "linhas_titulo_p0": 0}]

    capitulos = []
    # Preserva páginas pré-textuais anteriores ao primeiro capítulo se tiverem conteúdo substantivo
    primeiro_idx = inicios[0][0]
    pags_pre = [
        i for i in range(0, primeiro_idx)
        if i not in pags_sumario and sum(len(l["raw"]) for l in paginas[i]["linhas"]) > 250
    ]
    if pags_pre:
        capitulos.append({
            "titulo": "Preliminares",
            "pags_indices": pags_pre,
            "linhas_titulo_p0": 0
        })

    for j, (ini_idx, tit, l_usadas) in enumerate(inicios):
        fim_idx = inicios[j + 1][0] if j + 1 < len(inicios) else len(paginas)
        pags_cap = [i for i in range(ini_idx, fim_idx) if i not in pags_sumario and paginas[i]["linhas"]]
        # Se for apenas uma folha divisória de "Parte I" (1 linha), junta o título ao capítulo seguinte
        if len(pags_cap) == 1 and len(paginas[pags_cap[0]]["linhas"]) <= 2 and j + 1 < len(inicios):
            inicios[j + 1] = (inicios[j + 1][0], f"{tit} — {inicios[j + 1][1]}", inicios[j + 1][2])
            continue
        capitulos.append({
            "titulo": base.limpa(tit),
            "pags_indices": pags_cap,
            "linhas_titulo_p0": l_usadas
        })

    return capitulos


def processa_capitulos(paginas, corpo, glob):
    estrutura_caps = segmenta_em_capitulos(paginas, corpo, glob)
    caps_finais = []

    # Detecta o sumário/índice original do livro
    _, entradas_toc = detecta_paginas_sumario_original(paginas)

    for cap in estrutura_caps:
        pags_idx = cap["pags_indices"]
        if not pags_idx:
            continue

        corpo_cap_linhas = []
        notas_cap_todas = []
        em_bloco_notas_fim = False
        acum_notas_fim = []
        pars_acumulados = []

        for pos, pi in enumerate(pags_idx):
            pg = dict(paginas[pi])
            # Na primeira página do capítulo, remove as linhas que já formaram o título do capítulo
            if pos == 0 and cap["linhas_titulo_p0"] > 0:
                pg["linhas"] = pg["linhas"][cap["linhas_titulo_p0"]:]
            if not pg["linhas"]:
                continue

            corpo_l, notas_l, mudou = base.separa_corpo_e_notas_pagina(
                pg, corpo, glob, em_bloco_notas_fim
            )
            if not em_bloco_notas_fim and mudou:
                em_bloco_notas_fim = True
            elif em_bloco_notas_fim and mudou:
                em_bloco_notas_fim = False

            if corpo_l:
                pars_pg = base.monta_corpo(corpo_l, corpo)
                for p in pars_pg:
                    p["t"] = base.limpa(p["t"])
                pars_pg = [p for p in pars_pg if base.sem_marcas(p["t"]).strip()]

                # Se a página tem notas de rodapé próprias, vincula na página e adiciona à lista do capítulo
                if notas_l and not em_bloco_notas_fim:
                    notas_pg = base.monta_notas(notas_l)
                    for n in notas_pg:
                        n["t"] = base.limpa(n["t"])
                    base.vincula_chamadas_no_corpo(pars_pg, notas_pg)
                    notas_cap_todas.extend(
                        n["t"] for n in notas_pg if base.sem_marcas(n["t"]).strip()
                    )

                # parágrafo que atravessa a virada de página: junta em vez de abrir outro
                if pars_acumulados and pars_pg:
                    ant, prox = pars_acumulados[-1], pars_pg[0]
                    if (ant["tipo"] == "corpo" and prox["tipo"] == "corpo"
                            and not base.fim_de_frase(ant["t"])
                            and base.sem_marcas(prox["t"]).lstrip()[:1].islower()):
                        ant["t"] = base.junta(ant["t"], prox["t"])
                        pars_pg = pars_pg[1:]
                pars_acumulados.extend(pars_pg)

            if notas_l and em_bloco_notas_fim:
                acum_notas_fim.extend(notas_l)

        if acum_notas_fim:
            notas_fim = base.monta_notas(acum_notas_fim)
            for n in notas_fim:
                n["t"] = base.limpa(n["t"])
            base.vincula_chamadas_no_corpo(pars_acumulados, notas_fim)
            notas_cap_todas.extend(
                n["t"] for n in notas_fim if base.sem_marcas(n["t"]).strip()
            )

        caps_finais.append({
            "titulo": cap["titulo"],
            "pars": pars_acumulados,
            "notas": notas_cap_todas,
            "pags": (paginas[pags_idx[0]]["n"], paginas[pags_idx[-1]]["n"])
        })

    # Anexa as entradas do TOC original aos capítulos para uso no sumário
    for c in caps_finais:
        c["_toc_original"] = entradas_toc

    return caps_finais


# ----------------------------------------------------------------------------
# GERADORES DE SAÍDA (TXT, DOCX COM SUMÁRIO E PDF COM SUMÁRIO PAGINADO)
# ----------------------------------------------------------------------------
def gera_txt(caps, caminho):
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("SUMÁRIO\n" + "=" * 70 + "\n")
        for i, cap in enumerate(caps, 1):
            tit_cap = base.sem_marcas(cap['titulo'])
            f.write((tit_cap if re.match(r'\d', tit_cap) else f'{i}. {tit_cap}') + '\n')
            for p in cap["pars"]:
                if p["tipo"] == "h":
                    f.write(f"   - {base.sem_marcas(p['t'])}\n")
        f.write("\n\n")

        for cap in caps:
            f.write("=" * 70 + "\n" + base.sem_marcas(cap["titulo"]) + "\n" + "=" * 70 + "\n\n")
            for p in cap["pars"]:
                t = p["t"].replace(base.MARCA_I, "^").replace(base.MARCA_F, "")
                t = base.sem_marcas(t)
                if p["tipo"] == "h":
                    f.write("\n## " + t + "\n\n")
                else:
                    f.write(t + "\n\n")
            if cap["notas"]:
                f.write("\n--- NOTAS DO CAPÍTULO ---\n\n")
                for n in cap["notas"]:
                    t_n = n.replace(base.MARCA_I, "^").replace(base.MARCA_F, "")
                    f.write(base.sem_marcas(t_n) + "\n")
            f.write("\n\n")


def adiciona_campo_toc_word(par):
    """Insere o campo nativo TOC do Word para atualização automática de páginas."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = par.add_run()
    fldChar1 = OxmlElement("w:fldChar")
    fldChar1.set(qn("w:fldCharType"), "begin")
    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = 'TOC \\o "1-3" \\h \\z \\u'
    fldChar2 = OxmlElement("w:fldChar")
    fldChar2.set(qn("w:fldCharType"), "separate")
    fldChar3 = OxmlElement("w:fldChar")
    fldChar3.set(qn("w:fldCharType"), "end")

    r_elem = run._r
    r_elem.append(fldChar1)
    r_elem.append(instrText)
    r_elem.append(fldChar2)
    r_elem.append(fldChar3)


def padroniza_estilos_docx(d, fonte="Times New Roman"):
    """Todos os estilos (corpo e títulos) na mesma fonte e em preto: sem o Calibri azul padrão do Word."""
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn
    for nome, tam in (("Normal", 11), ("Title", 20), ("Heading 1", 15), ("Heading 2", 12), ("Heading 3", 11)):
        try:
            st = d.styles[nome]
        except KeyError:
            continue
        st.font.name = fonte
        st.font.color.rgb = RGBColor(0, 0, 0)
        if nome != "Normal":
            st.font.size = Pt(tam)
            st.font.bold = True
            st.font.italic = False
        rf = st.element.get_or_add_rPr().find(qn("w:rFonts"))
        if rf is not None:
            for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
                rf.attrib.pop(qn(a), None)
            for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
                rf.set(qn(a), fonte)


def gera_docx(caps, titulo_livro, autor, subtitulo, caminho):
    from docx import Document
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    d = Document()
    padroniza_estilos_docx(d)
    sec = d.sections[0]
    sec.page_width, sec.page_height = Cm(14), Cm(21)
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin = sec.bottom_margin = Cm(2.2)

    st = d.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(11)

    # Folha de rosto
    p_autor = d.add_paragraph(autor)
    p_autor.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_tit = d.add_heading(titulo_livro, 0)
    p_tit.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if subtitulo:
        p_sub = d.add_paragraph(subtitulo)
        p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER

    d.add_page_break()

    # Sumário Automático
    d.add_heading("Sumário", 1)
    p_toc_field = d.add_paragraph()
    # (lista estática abaixo; o campo TOC do Word duplicaria o sumário ao atualizar)

    # O sumário lista só os capítulos (nível 0), como no índice impresso original
    # do livro: subtítulos internos detectados automaticamente (p["tipo"] == "h")
    # ficam de fora daqui porque a detecção de títulos internos é sujeita a falsos
    # positivos (citações, verbetes de bibliografia etc.) e um sumário "detalhado"
    # feito com eles tende a sair mais poluído do que o índice que o livro já traz.
    for cap in caps:
        p_item = d.add_paragraph()
        p_item.paragraph_format.space_after = Pt(2)
        r = p_item.add_run(base.sem_marcas(cap["titulo"]))
        r.bold = True

    for cap in caps:
        d.add_page_break()
        d.add_heading(base.sem_marcas(cap["titulo"]), 1)
        for p in cap["pars"]:
            if p["tipo"] == "h":
                hd = d.add_heading("", 2 if p["nivel"] == 1 else 3)
                base.tokens_docx(hd, p["t"])
            elif p.get("cit"):
                par = d.add_paragraph()
                par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                par.paragraph_format.left_indent = Cm(0.9)
                par.paragraph_format.first_line_indent = Cm(0)
                base.tokens_docx(par, p["t"], 9.5)
            else:
                par = d.add_paragraph()
                par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                par.paragraph_format.first_line_indent = Cm(0.6)
                base.tokens_docx(par, p["t"], 11)
        if cap["notas"]:
            d.add_heading("Notas", 2)
            for n in cap["notas"]:
                par = d.add_paragraph()
                par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                par.paragraph_format.left_indent = Cm(0.6)
                par.paragraph_format.first_line_indent = Cm(-0.6)
                par.paragraph_format.space_after = Pt(2)
                base.tokens_docx(par, n, 9)

    d.save(caminho)


# ---------------------------------------------------------------------------
# GERAÇÃO EPUB
# ---------------------------------------------------------------------------
def gera_epub(caps, titulo_livro, autor, subtitulo, caminho, capa=None):
    """Gera EPUB a partir da estrutura de capítulos."""
    if not EPUB_DISPONIVEL:
        print("⚠️  ebooklib não instalado: pip install ebooklib")
        return False

    book = epub.EpubBook()

    # Metadados
    book.set_identifier(f"diagramar-livro-{titulo_livro.lower().replace(' ', '-')}")
    book.set_title(titulo_livro)
    book.set_language('pt')
    book.add_author(autor)
    if subtitulo:
        book.add_metadata('DC', 'subtitle', subtitulo)

    # Capa
    if capa and os.path.exists(capa):
        with open(capa, 'rb') as img:
            book.set_cover("cover.jpg", img.read())

    # Estilo CSS
    style = '''
    @namespace epub "http://www.idpf.org/2007/ops";
    body { font-family: Georgia, serif; line-height: 1.6; margin: 1em; text-align: justify; }
    h1 { text-align: center; font-size: 1.8em; margin-top: 2em; margin-bottom: 1em; page-break-before: always; }
    h2 { font-size: 1.3em; margin-top: 1.5em; margin-bottom: 0.5em; }
    h3 { font-size: 1.1em; margin-top: 1em; margin-bottom: 0.5em; font-style: italic; }
    p { text-indent: 1.5em; margin: 0.5em 0; }
    p.first { text-indent: 0; }
    .citation { margin-left: 2em; margin-right: 1em; font-size: 0.9em; font-style: italic; }
    .note { font-size: 0.85em; margin-left: 1em; text-indent: -1em; margin-bottom: 0.3em; }
    .epigraph { font-style: italic; text-align: right; margin: 1em 2em; }
    .toc-title { text-align: center; font-size: 1.5em; margin: 2em 0 1em; }
    '''
    nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=style)
    book.add_item(nav_css)

    # Sumário (NCX + Nav)
    book.toc = []
    spine = ['nav']

    # Folha de rosto
    title_page = epub.EpubHtml(title='Folha de Rosto', file_name='titlepage.xhtml', lang='pt')
    title_content = f'''
    <html><body>
    <div style="text-align: center; margin-top: 30%;">
        <h1>{html.escape(titulo_livro)}</h1>
    '''
    if subtitulo:
        title_content += f'<h2>{html.escape(subtitulo)}</h2>'
    title_content += f'''
        <p style="margin-top: 3em;">{html.escape(autor)}</p>
    </div>
    </body></html>
    '''
    title_page.content = title_content
    book.add_item(title_page)
    spine.append(title_page)

    # Sumário HTML
    toc_page = epub.EpubHtml(title='Sumário', file_name='toc.xhtml', lang='pt')
    toc_content = '<html><body><h1 class="toc-title">Sumário</h1><ul>'
    for i, cap in enumerate(caps, 1):
        toc_content += f'<li><a href="cap_{i:03d}.xhtml">{html.escape(cap["titulo"])}</a></li>'
    toc_content += '</ul></body></html>'
    toc_page.content = toc_content
    book.add_item(toc_page)
    spine.append(toc_page)
    book.toc.append(epub.Link('toc.xhtml', 'Sumário', 'toc'))

    # Capítulos
    for i, cap in enumerate(caps, 1):
        chapter = epub.EpubHtml(title=cap['titulo'], file_name=f'cap_{i:03d}.xhtml', lang='pt')

        content = f'<html><body><h1>{html.escape(cap["titulo"])}</h1>'

        for p in cap["pars"]:
            t = p["t"].replace(base.MARCA_I, "<sup>").replace(base.MARCA_F, "</sup>")
            t = base.sem_marcas(t)
            t = t.replace('\x01', '<i>').replace('\x02', '</i>').replace('\x05', '<b>').replace('\x06', '</b>')

            if p["tipo"] == "h":
                level = 2 if p["nivel"] == 1 else 3
                content += f'<h{level}>{html.escape(t)}</h{level}>'
            elif p.get("cit"):
                content += f'<p class="citation">{html.escape(t)}</p>'
            else:
                content += f'<p>{html.escape(t)}</p>'

        if cap["notas"]:
            content += '<h2>Notas</h2>'
            for n in cap["notas"]:
                t = n.replace(base.MARCA_I, "<sup>").replace(base.MARCA_F, "</sup>")
                t = base.sem_marcas(t)
                t = t.replace('\x01', '<i>').replace('\x02', '</i>').replace('\x05', '<b>').replace('\x06', '</b>')
                content += f'<p class="note">{html.escape(t)}</p>'

        content += '</body></html>'
        chapter.content = content
        book.add_item(chapter)
        spine.append(chapter)
        book.toc.append(epub.Link(f'cap_{i:03d}.xhtml', cap['titulo'], f'cap{i}'))

    # NCX e Nav obrigatórios
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Spine ordem de leitura
    book.spine = spine

    # Salva
    epub.write_epub(caminho, book, {})
    return True


# ---------------------------------------------------------------------------
# PREVIEW DO SUMÁRIO (para GUI)
# ---------------------------------------------------------------------------
def preview_sumario(pdf_path, dpi=150):
    """Gera preview do sumário detectado sem processar o livro todo.
    Retorna dict com estrutura detectada para exibição na GUI."""
    doc = fitz.open(pdf_path)
    paginas = [
        {"n": i, "W": p.rect.width, "H": p.rect.height, "linhas": base.extrai_linhas_pagina(p)}
        for i, p in enumerate(doc, 1)
    ]
    doc.close()

    rep_cab, rep_rod = base.detecta_cabecalhos_rodapes_repetidos(paginas)

    for pg in paginas:
        antes = len(pg["linhas"])
        tams = sorted(l["size"] for l in pg["linhas"] if l["raw"].strip())
        med = tams[len(tams) // 2] if tams else 0.0
        pg["linhas"] = [
            l for idx, l in enumerate(pg["linhas"])
            if not base.eh_lixo(l, idx, antes, pg["H"], rep_cab, rep_rod, med)
        ]

    pares = [(round(l["size"], 1), len(l["raw"])) for pg in paginas for l in pg["linhas"]]
    if not pares:
        return {"error": "Nenhum texto encontrado"}

    corpo = base.mediana_ponderada(pares)
    ms = [m for m in (base.margens(pg["linhas"], corpo) for pg in paginas) if m]
    glob = (base.percentil([m[0] for m in ms], 0.5), base.percentil([m[1] for m in ms], 0.5)) if ms else (0, paginas[0]["W"])

    # Detecta folha de rosto
    rosto = base.detecta_folha_de_rosto(paginas, corpo)
    if rosto:
        idx_rosto, _, _, _ = rosto
        paginas = [pg for i, pg in enumerate(paginas) if i not in set(idx_rosto)]

    # Detecta ficha catalográfica
    indices_ficha = base.detecta_ficha_catalografica(paginas)
    if indices_ficha:
        paginas = [pg for i, pg in enumerate(paginas) if i not in indices_ficha]

    # Segmenta em capítulos
    caps = base.segmenta_em_capitulos(paginas, corpo, glob)

    # Tenta extrair TOC original
    _, entradas_toc = base.detecta_paginas_sumario_original(paginas)

    resultado = {
        "capitulos": [],
        "tem_toc_original": len(entradas_toc) > 0,
        "toc_original": [{"titulo": raw, "norm": norm} for norm, raw in entradas_toc],
        "total_paginas": len(paginas),
        "corpo_pt": round(corpo, 1)
    }

    for cap in caps:
        resultado["capitulos"].append({
            "titulo": cap["titulo"],
            "paginas_pdf": f"{cap['pags'][0]}–{cap['pags'][1]}",
            "num_paginas": cap['pags'][1] - cap['pags'][0] + 1
        })

    return resultado


# ---------------------------------------------------------------------------
# Fontes do livro: procura Vera Humana/Marcellus e cai para serifas genericas
# ---------------------------------------------------------------------------
FONTES_CORPO = [
    ("Verah__.ttf", "Verahb_.ttf", "Verahi_.ttf", "Verahbi.ttf"),
    ("VeraHumana95-Regular.ttf", "VeraHumana95-Bold.ttf",
     "VeraHumana95-Italic.ttf", "VeraHumana95-BoldItalic.ttf"),
    ("LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf",
     "LiberationSerif-Italic.ttf", "LiberationSerif-BoldItalic.ttf"),
    ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    ("Times New Roman.ttf", "Times New Roman Bold.ttf",
     "Times New Roman Italic.ttf", "Times New Roman Bold Italic.ttf"),
]
FONTES_DISPLAY = ["Marcellus-Regular.ttf", "MarcellusSC-Regular.ttf",
                  "marcellus-regular.ttf", "Marcellus-Regular.otf"]

# ---------------------------------------------------------------------------
# Geometria da pagina (A4) e escala tipografica - medidas do modelo de referencia
# ---------------------------------------------------------------------------
PAG_L, PAG_A = 595.28, 841.89            # A4 retrato
M_ESQ, M_DIR = 56.7, 52.38               # margens laterais
M_TOPO, M_BAIXO = 74.03, 85.86           # margens superior e inferior (caixa de 30 linhas)
LARG_TEXTO = PAG_L - M_ESQ - M_DIR       # 486,2 pt de largura de coluna
CORPO_PT, ENTR_LEAD = 16.0, 22.0         # corpo do texto e entrelinha
RECUO_1A = 21.3                          # recuo de primeira linha
ESP_ENTRE_PAR = 22.0                     # espaco entre paragrafos (uma linha em branco)
# Letra capitular: tamanho, linhas invadidas e respiro (2 mm) entre a caixa de
# avanco da letra e o texto ao lado.
CAP_PT, CAP_LINHAS, CAP_FOLGA = 46.1, 2, 5.669
FOLHA_Y, FOLHA_X = 25.86, 532.6          # baseline do rodape e fim do numero
TRACK_MAIUSC = 0.075                     # tracking das maiusculas (titulo/creditos)
CENTRO_TITULO = 0.4726                   # centro vertical do bloco do titulo (de baixo)
CIT_PT, CIT_LEAD = 13.0, 18.0            # citacoes
NOTA_PT, NOTA_LEAD = 11.0, 15.0          # notas no fim do capitulo


def _pastas_fontes():
    pastas = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        pastas.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    aqui = os.path.dirname(os.path.abspath(__file__))
    pastas += [os.path.join(aqui, "fontes"), aqui,
               "C:/Windows/Fonts", "/usr/share/fonts/truetype/liberation",
               "/usr/share/fonts", "/System/Library/Fonts/Supplemental",
               "/Library/Fonts"]
    return pastas


def _acha_fonte(nomes):
    for pasta in _pastas_fontes():
        for n in nomes:
            p = os.path.join(pasta, n)
            if os.path.exists(p):
                return p
    return None


_TAG_RE = re.compile(r"<[^>]*>")


def _sem_tags(t):
    return _TAG_RE.sub("", t)


def _caixa_glifo(caractere, caminho_fonte, _cache={}):
    """(lsb, largura da tinta, altura) de um glifo, em fracao do em (fontTools)."""
    chave = (caminho_fonte, caractere)
    if chave in _cache:
        return _cache[chave]
    resultado = None
    try:
        from fontTools.ttLib import TTFont as _FT
        from fontTools.pens.boundsPen import BoundsPen
        ft = _FT(caminho_fonte, lazy=True, fontNumber=0)
        gs = ft.getGlyphSet()
        cmap = ft.getBestCmap()
        upem = ft["head"].unitsPerEm
        nome = cmap.get(ord(caractere))
        if nome:
            bp = BoundsPen(gs)
            gs[nome].draw(bp)
            if bp.bounds:
                x0, _y0, x1, _y1 = bp.bounds
                resultado = (x0 / upem, (x1 - x0) / upem)
    except Exception:
        resultado = None
    _cache[chave] = resultado
    return resultado


_ENTIDADES = (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
              ("&quot;", '"'), ("&apos;", "'"), ("&#39;", "'"))
_RE_TAG = re.compile(r"</?([a-zA-Z]+)[^>]*>")


def _sem_entidades(t):
    for a, b in _ENTIDADES:
        if a in t:
            t = t.replace(a, b)
    return t


def _sem_tags(t):
    return _RE_TAG.sub("", t or "")


def _tokeniza(texto):
    """Texto -> lista de palavras; cada palavra = [(trecho, estilo), ...] com
    estilo em ('', 'b', 'i').  Preserva a marcacao inline (<b>, <i>, <bi>)."""
    palavras, atual, estilo, i, n = [], [], "", 0, len(texto)
    while i < n:
        if texto[i].isspace():
            if atual:
                palavras.append(atual)
                atual = []
            i += 1
            continue
        m = _RE_TAG.match(texto, i)
        if m:
            tag = m.group(1).lower()
            fecha = texto[i + 1] == "/"
            if tag in ("b", "strong"):
                estilo = "" if fecha else "b"
            elif tag in ("i", "em", "italic"):
                estilo = "" if fecha else "i"
            elif tag in ("bi", "ib") and not fecha:
                estilo = "i"
            i = m.end()
            continue
        j = i
        while j < n and not texto[j].isspace() and not _RE_TAG.match(texto, j):
            j += 1
        trecho = _sem_entidades(texto[i:j])
        if trecho:
            if atual and atual[-1][1] == estilo:
                atual[-1] = (atual[-1][0] + trecho, estilo)
            else:
                atual.append((trecho, estilo))
        i = j
    if atual:
        palavras.append(atual)
    return [p for p in palavras if any(t for t, _ in p)]


def _larg_palavra(pal, fontes, tamanho):
    from reportlab.pdfbase import pdfmetrics
    return sum(pdfmetrics.stringWidth(t, fontes.get(e, fontes[""]), tamanho)
               for t, e in pal if t)


def _pontos_hifen(hif, t):
    """Indices em `t` onde a palavra pode ser hifenizada (pyphen)."""
    try:
        marcado = hif.inserted(t)
    except Exception:
        return []
    pts, vistas = [], 0
    for k, c in enumerate(marcado):
        if c == chr(0xAD):
            vistas += 1
            pts.append(k - vistas)
    return [p for p in pts if 1 < p < len(t) - 1]


# Folga de quebra: a linha pode "inchar" essa fracao da largura util antes de
# rejeitar a proxima palavra (o espaco e comprimido na justificacao).  Medido
# no livro de referencia: ~8pt em 486pt de medida (1,65%).
_FOLGA_QUEBRA = 0.0165


def _quebra_linhas(palavras, fontes, tamanho, largura, indent_1a=0.0,
                   indent_esq=0.0, hifen=None):
    """Quebra em linhas com a regra do livro de referencia: o espaco que sobra
    no fim da linha NAO entra na conta da largura, e a linha pode passar da
    medida em ate _FOLGA_QUEBRA dela (comprimindo os espacos).  Devolve uma
    lista de (palavras, largura_natural, x, largura_disponivel)."""
    from reportlab.pdfbase import pdfmetrics
    espaco = pdfmetrics.stringWidth(" ", fontes[""], tamanho)
    linhas = []
    i, n = 0, len(palavras)
    primeira = True
    while i < n:
        rec = indent_1a if primeira else 0.0
        disp = largura - indent_esq - rec
        # limite de quebra: a medida mais a folga de compressao
        limite = disp * (1.0 + _FOLGA_QUEBRA)
        x = indent_esq + rec
        linha, larg = [], 0.0
        while i < n:
            pal = palavras[i]
            w = _larg_palavra(pal, fontes, tamanho)
            if not linha:
                linha.append(pal)
                larg = w
                i += 1
                continue
            if larg + espaco + w <= limite:
                linha.append(pal)
                larg += espaco + w
                i += 1
                continue
            if hifen is not None and len(pal) == 1:
                txt, est = pal[0]
                fonte = fontes.get(est, fontes[""])
                for p in reversed(_pontos_hifen(hifen, txt)):
                    wp = (pdfmetrics.stringWidth(txt[:p], fonte, tamanho)
                          + pdfmetrics.stringWidth("-", fonte, tamanho))
                    if larg + espaco + wp <= limite:
                        linha.append([(txt[:p] + "-", est)])
                        palavras[i] = [(txt[p:], est)]
                        larg += espaco + wp
                        break
                else:
                    break
                break
            break
        linhas.append((linha, larg, x, disp))
        primeira = False
    return linhas


def _parte_inicial(texto, fonte, tamanho, largura, n_linhas, folga=0.985):
    """Separa as `n_linhas` primeiras linhas (na largura reduzida) do resto."""
    tokens = texto.split()
    if len(tokens) <= 2:
        return None, None
    from reportlab.pdfbase import pdfmetrics
    espaco = pdfmetrics.stringWidth(" ", fonte, tamanho)
    usados, linhas = [], 0
    while linhas < n_linhas and tokens:
        linha, larg = [], 0.0
        while tokens:
            w = pdfmetrics.stringWidth(_sem_tags(tokens[0]), fonte, tamanho)
            if not linha:
                if w > largura * folga:
                    return None, None
                linha.append(tokens.pop(0))
                larg = w
            elif larg + espaco + w <= largura * folga:
                linha.append(tokens.pop(0))
                larg += espaco + w
            else:
                break
        usados.extend(linha)
        linhas += 1
    if linhas < n_linhas or not tokens:
        return None, None
    return " ".join(usados), " ".join(tokens)


def _separa_letra(texto):
    """'Atualmente...' -> ('A', 'tualmente...'); (None, texto) se nao der."""
    m = re.match(r"^(?:\s|<[^>]*>|[\"'“”‘’«»(\[{])*", texto)
    pos = len(m.group(0))
    if pos >= len(texto) or not texto[pos].isalpha():
        return None, texto
    prefixo = re.sub(r"</[^>]*>", "", texto[:pos])
    return texto[pos].upper(), prefixo + texto[pos + 1:]


def _separa_letra_pals(pals):
    """Igual a _separa_letra, mas sobre palavras ja tokenizadas."""
    if not pals:
        return None, pals
    prim = [list(t) for t in pals[0]]
    if not prim or not prim[0][0]:
        return None, pals
    txt, est = prim[0]
    if not txt[:1].isalpha():
        return None, pals
    letra = txt[0].upper()
    if len(txt) > 1:
        prim[0][1] = txt[1:]
    else:
        prim.pop(0)
    return letra, [prim] + pals[1:]


ITALICO_SINTETICO = False     # True quando a fonte do corpo nao tem arquivo de italico
INCLINACAO_ITALICO = 0.2126   # tan(12 graus): inclinacao do italico sintetico


def registra_fontes():
    """Registra as fontes do livro; devolve (corpo, negrito, italico, display)."""
    global ITALICO_SINTETICO
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for conj in FONTES_CORPO:
        regular = _acha_fonte([conj[0]])
        negrito = _acha_fonte([conj[1]])
        if not (regular and negrito):
            continue
        italico = _acha_fonte([conj[2]])
        ITALICO_SINTETICO = italico is None
        if ITALICO_SINTETICO:
            print(f"AVISO: italico de '{conj[0]}' nao encontrado; "
                  "usando italico sintetico (fonte inclinada).")
            italico = regular
        negrito_it = _acha_fonte([conj[3]]) or negrito
        try:
            pdfmetrics.registerFont(TTFont("Livro", regular))
            pdfmetrics.registerFont(TTFont("Livro-B", negrito))
            pdfmetrics.registerFont(TTFont("Livro-I", italico))
            pdfmetrics.registerFont(TTFont("Livro-BI", negrito_it))
            pdfmetrics.registerFontFamily("Livro", normal="Livro", bold="Livro-B",
                                          italic="Livro-I", boldItalic="Livro-BI")
        except Exception:
            continue
        display = _acha_fonte(FONTES_DISPLAY)
        if display:
            try:
                pdfmetrics.registerFont(TTFont("Livro-D", display))
                return "Livro", "Livro-B", "Livro-I", "Livro-D", regular, negrito
            except Exception:
                pass
        return "Livro", "Livro-B", "Livro-I", "Livro", regular, negrito
    return ("Times-Roman", "Times-Bold", "Times-Italic", "Times-Roman", None, None)


def rl(t):
    """Converte marcadores internos de itálico e sobrescrito para tags XML do ReportLab."""
    t = t.replace(base.ABRE_NE, "").replace(base.FECHA_NE, "")
    t = html.escape(t, quote=False)
    out = []
    it_aberto = False
    sup_aberto = False
    for ch in t:
        if ch == base.ABRE_IT:
            if not it_aberto:
                out.append("<i>")
                it_aberto = True
        elif ch == base.FECHA_IT:
            if it_aberto:
                out.append("</i>")
                it_aberto = False
        elif ch == base.MARCA_I:
            if not sup_aberto:
                out.append("<super>")
                sup_aberto = True
        elif ch == base.MARCA_F:
            if sup_aberto:
                out.append("</super>")
                sup_aberto = False
        else:
            out.append(ch)
    if sup_aberto:
        out.append("</super>")
    if it_aberto:
        out.append("</i>")
    return "".join(out)


# ---------------------------------------------------------------------------
# RENDERIZADOR PDF - layout editorial A4 no modelo do livro de referencia
# ---------------------------------------------------------------------------
def _desloc_1a_linha(fonte, tamanho):
    """Distancia do topo da caixa do paragrafo ate a primeira baseline."""
    from reportlab.pdfbase import pdfmetrics
    try:
        from reportlab.rl_config import paraFontSizeHeightOffset
    except Exception:
        paraFontSizeHeightOffset = 1
    if paraFontSizeHeightOffset:
        return float(tamanho)
    return pdfmetrics.getAscent(fonte) / 1000.0 * float(tamanho)


def _quebra_maiusculas(texto, fonte, tamanho, tracking, largura):
    """Quebra um titulo em maiusculas (com tracking) em linhas de no maximo `largura`."""
    from reportlab.pdfbase import pdfmetrics
    palavras = base.sem_marcas(texto or "").upper().split()
    linhas, atual = [], []
    while palavras:
        cand = " ".join(atual + [palavras[0]])
        w = pdfmetrics.stringWidth(cand, fonte, tamanho) + tracking * max(0, len(cand) - 1)
        if not atual or w <= largura:
            atual.append(palavras.pop(0))
        else:
            linhas.append(" ".join(atual))
            atual = []
    if atual:
        linhas.append(" ".join(atual))
    return linhas


def _tamanho_imagem(caminho):
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            return im.size
    except Exception:
        pass
    try:
        from reportlab.lib.utils import ImageReader
        w, h = ImageReader(caminho).getSize()
        return (w, h)
    except Exception:
        return None


class LivroPDF:
    """Diagrama o livro pagina a pagina: A4, capitulares, folhas recto/verso."""

    def __init__(self, caminho, titulo, autor, subtitulo, editora=None, ano=None):
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_LEFT
        from reportlab.lib.colors import black

        self.titulo = (titulo or "").strip()
        self.autor = (autor or "").strip()
        self.subtitulo = (subtitulo or "").strip()
        self.editora = (editora or "").strip()
        self.ano = (ano or "").strip()
        self.f, self.fb, self.fi, self.fd, self.arq_corpo, self.arq_negrito = registra_fontes()

        self.c = rl_canvas.Canvas(caminho, pagesize=(PAG_L, PAG_A), pageCompression=1)
        self.c.setTitle(self.titulo or "Livro")
        self.c.setAuthor(self.autor or "")
        self.c.setSubject(self.subtitulo or "")
        self.c.setCreator("Diagramar Livro")

        self.n_pag = 0
        self.folha = 0
        self.topo_y = PAG_A - M_TOPO
        self.base_y = M_BAIXO
        self.y = self.topo_y
        self.ultimo_bloco = False

        extra = {}
        self.hifen = None
        if HIFENIZAR_PDF:
            try:
                import pyphen
                self.hifen = pyphen.Pyphen(lang="pt_BR")
            except Exception:
                self.hifen = None
        comum = dict(fontName=self.f, fontSize=CORPO_PT, leading=ENTR_LEAD,
                     alignment=TA_JUSTIFY, firstLineIndent=RECUO_1A,
                     spaceAfter=ESP_ENTRE_PAR, allowWidows=0, allowOrphans=0,
                     textColor=black, **extra)
        self.est = {
            "corpo": ParagraphStyle("corpo", **comum),
            "cit": ParagraphStyle("cit", parent=ParagraphStyle("_b", **comum),
                                  fontSize=CIT_PT, leading=CIT_LEAD, leftIndent=33.7,
                                  firstLineIndent=0, spaceBefore=4,
                                  spaceAfter=ESP_ENTRE_PAR + 2, allowWidows=0, allowOrphans=0),
            "nota": ParagraphStyle("nota", parent=ParagraphStyle("_b2", **comum),
                                   fontSize=NOTA_PT, leading=NOTA_LEAD, leftIndent=13,
                                   firstLineIndent=-13, spaceAfter=3, allowWidows=0, allowOrphans=0),
        }

    # ---------------------------------------------------------------- paginas
    def _nova_pagina(self, com_folha=True, forcar=False):
        if self.n_pag or forcar:
            self.c.showPage()
        self.n_pag += 1
        if com_folha:
            self.folha += 1
            self._desenha_rodape()
        self.y = self.topo_y

    def _desenha_rodape(self):
        c = self.c
        impar = self.folha % 2 == 1
        texto, fonte = None, self.f
        if impar and self.titulo:
            texto, fonte = self.titulo, self.fd
        elif not impar and self.autor:
            texto, fonte = self.autor, self.f
        elif self.titulo:
            texto, fonte = self.titulo, self.fd
        elif self.autor:
            texto, fonte = self.autor, self.f
        if texto:
            texto = texto.upper()
            tamanho = 13.0
            while tamanho > 8 and self._larg(texto, fonte, tamanho) > PAG_L - M_ESQ - 90:
                tamanho -= 0.25
            c.setFont(fonte, tamanho)
            c.drawString(M_ESQ, FOLHA_Y, texto)
        c.setFont(self.f, 12)
        c.drawRightString(FOLHA_X, FOLHA_Y, str(self.folha))

    def _larg(self, texto, fonte, tamanho):
        from reportlab.pdfbase import pdfmetrics
        return pdfmetrics.stringWidth(texto, fonte, tamanho)

    def _no_topo(self):
        return abs(self.y - self.topo_y) < 0.05

    # ----------------------------------------------------------- texto solto
    def _desenha_maiusculas(self, texto, y_topo, largura, fonte, tamanho, leading,
                            centro=True, espaco_depois=0.0, centro_em=None):
        """Desenha titulo em maiusculas com tracking; devolve a altura consumida."""
        c = self.c
        tracking = TRACK_MAIUSC * tamanho
        linhas = _quebra_maiusculas(texto, fonte, tamanho, tracking, largura)
        desloc = _desloc_1a_linha(fonte, tamanho)
        cx = (M_ESQ + largura / 2.0) if centro_em is None else centro_em
        for i, ln in enumerate(linhas):
            yb = y_topo - desloc - i * leading
            c.setFont(fonte, tamanho)
            if centro:
                c.drawCentredString(cx, yb, ln, charSpace=tracking)
            else:
                c.drawString(M_ESQ, yb, ln, charSpace=tracking)
        altura = desloc + (len(linhas) - 1) * leading
        self.y = y_topo - altura - espaco_depois
        return altura

    # ------------------------------------------------------------ paragrafos
    def paragrafo(self, texto, est, capitular=False):
        if capitular or self._no_topo():
            if self._paragrafo_capitular(texto, est):
                return
        self._paragrafo(texto, est)

    def _fontes(self):
        return {"": self.f, "b": self.fb, "i": self.fi, "bi": self.fi}

    def _desenha_linha(self, linha, larg, x, disp, y_base, tamanho, justificar):
        """Desenha uma linha ja quebrada; justifica abrindo ou comprimindo os
        espacos para a linha encostar na medida (como no livro de referencia).
        Os espacos sao desenhados de verdade (Word Space do PDF), para o texto
        continuar selecionavel e pesquisavel."""
        from reportlab.pdfbase import pdfmetrics
        fontes = self._fontes()
        espaco = pdfmetrics.stringWidth(" ", fontes[""], tamanho)
        n_esp = max(0, len(linha) - 1)
        gap = espaco
        if n_esp and (justificar or larg > disp + 1e-6):
            # ajuste por espaco; comprimir e permitido (nunca abaixo de 55%)
            gap = espaco + (disp - larg) / float(n_esp)
            piso = espaco * 0.55
            if gap < piso:
                gap = piso
        cx = M_ESQ + x
        for k, pal in enumerate(linha):
            for t, e in pal:
                if not t:
                    continue
                f = fontes.get(e, fontes[""])
                if ITALICO_SINTETICO and e in ("i", "bi"):
                    # Sem arquivo de italico de verdade: inclina a fonte regular/negrito
                    # via matriz de texto, em vez de desenhar reto (que é o que estava
                    # fazendo o itálico "sumir" visualmente).
                    to = self.c.beginText()
                    to.setTextTransform(1, 0, INCLINACAO_ITALICO, 1, cx, y_base)
                    to.setFont(f, tamanho)
                    to.textOut(t)
                    self.c.drawText(to)
                else:
                    self.c.setFont(f, tamanho)
                    self.c.drawString(cx, y_base, t)
                cx += pdfmetrics.stringWidth(t, f, tamanho)
            if k < n_esp:
                # espaco real entre as palavras (o avanco vem do Tw abaixo)
                self.c.setFont(fontes[""], tamanho)
                self.c.drawString(cx, y_base, " ", wordSpace=gap - espaco)
                cx += gap

    def _paragrafo(self, texto, est, pals=None, cap=True, recuo_1a=None):
        from reportlab.lib.enums import TA_JUSTIFY
        if pals is None:
            pals = _tokeniza(texto or " ")
        # Paragralo de texto que comeca no topo de uma pagina leva capitular,
        # como no livro de referencia (so o estilo do corpo a leva).
        if cap and est is self.est.get("corpo") and self.y - self.base_y < ENTR_LEAD:
            self._nova_pagina()
            if self._paragrafo_capitular(None, est, pals=pals):
                return
        linhas = _quebra_linhas(pals, self._fontes(), est.fontSize, LARG_TEXTO,
                                indent_1a=(est.firstLineIndent if recuo_1a is None
                                           else recuo_1a),
                                indent_esq=est.leftIndent, hifen=self.hifen)
        if not linhas:
            return
        lead = est.leading
        desloc = _desloc_1a_linha(self.f, est.fontSize)
        justificar = (est.alignment == TA_JUSTIFY)
        k = 0
        total = len(linhas)
        while k < total:
            avail = self.y - self.base_y
            if avail < lead:
                self._nova_pagina()
                continue
            n_cabe = int((avail + 0.01) // lead)
            if n_cabe > total - k:
                n_cabe = total - k
            if n_cabe < 1:
                self._nova_pagina()
                continue
            yb = self.y - desloc
            for j in range(k, k + n_cabe):
                pal, larg, x, disp = linhas[j]
                self._desenha_linha(pal, larg, x, disp, yb, est.fontSize,
                                    justificar and j < total - 1)
                yb -= lead
            self.y -= n_cabe * lead
            k += n_cabe
            if k < total:
                self._nova_pagina()
        if self.y - self.base_y >= lead:
            self.y -= est.spaceAfter

    def _paragrafo_capitular(self, texto, est, pals=None):
        from reportlab.pdfbase import pdfmetrics
        if pals is None:
            letra, resto = _separa_letra(texto or "")
            if letra is None:
                return False
            pals = _tokeniza(resto)
        else:
            letra, pals = _separa_letra_pals(pals)
            if letra is None:
                return False
        # Recuo das linhas ao lado da capitular: a caixa de avanco da letra
        # (que comeca LSB antes da margem, para a tinta encostar nela) mais
        # 2 mm de respiro.  Medido no livro de referencia: casa com A, E, Q e U
        # a 0,01 pt.
        avanco = pdfmetrics.stringWidth(letra, self.fb, CAP_PT)
        caixa = _caixa_glifo(letra, self.arq_negrito) if self.arq_negrito else None
        lsb = caixa[0] * CAP_PT if caixa else 0.0
        indent = avanco + CAP_FOLGA - lsb
        fontes = self._fontes()
        linhas = _quebra_linhas(pals, fontes, CORPO_PT, LARG_TEXTO,
                                indent_1a=0.0, indent_esq=indent, hifen=self.hifen)
        if len(linhas) <= CAP_LINHAS:
            return False
        avail = self.y - self.base_y
        if CAP_LINHAS * ENTR_LEAD > avail:
            return False
        desloc = _desloc_1a_linha(self.f, CORPO_PT)
        yb = self.y - desloc
        for j in range(CAP_LINHAS):
            pal, larg, x, disp = linhas[j]
            self._desenha_linha(pal, larg, x, disp, yb, CORPO_PT, True)
            yb -= ENTR_LEAD
        # capitular: baseline na 2a linha, tinta encostada na margem esquerda
        base_linha2 = self.y - desloc - ENTR_LEAD * (CAP_LINHAS - 1)
        x_cap = M_ESQ - lsb
        self.c.setFillColor(est.textColor)
        self.c.setFont(self.fb, CAP_PT)
        self.c.drawString(x_cap, base_linha2, letra)
        self.y -= CAP_LINHAS * ENTR_LEAD
        resto_pals = [p for (lin, _, _, _) in linhas[CAP_LINHAS:] for p in lin]
        # o resto do paragrafo continua na largura toda, sem recuo de 1a linha
        self._paragrafo(None, est, pals=resto_pals, cap=False, recuo_1a=0.0)
        return True

    # -------------------------------------------------------------- blocos
    def _titulo_interno(self, texto, nivel):
        tamanho = 15.0 if nivel == 1 else 12.5
        leading = tamanho * 1.25
        antes = 8.0 if self._no_topo() else (26.0 if nivel == 1 else 18.0)
        self.y -= antes
        tracking = TRACK_MAIUSC * tamanho
        linhas = _quebra_maiusculas(texto, self.fb, tamanho, tracking, LARG_TEXTO)
        altura = _desloc_1a_linha(self.fb, tamanho) + (len(linhas) - 1) * leading
        depois = 12.0 if nivel == 1 else 8.0
        if self.y - self.base_y < altura + depois + 3 * ENTR_LEAD:
            self._nova_pagina()
            self.y = self.topo_y
        self._desenha_maiusculas(texto, self.y, LARG_TEXTO, self.fb, tamanho, leading,
                                 centro=(nivel == 1), espaco_depois=depois)

    def _abre_capitulo(self, texto):
        self.y -= 56.7
        self._desenha_maiusculas(texto, self.y, LARG_TEXTO, self.fb, 20.0, 26.0,
                                 centro=True, espaco_depois=20.0)

    def _notas(self, notas):
        if not notas:
            return
        self.y -= 24.0
        altura_tit = _desloc_1a_linha(self.fb, 12.5)
        if self.y - self.base_y < altura_tit + 8 + 3 * NOTA_LEAD:
            self._nova_pagina()
        self._desenha_maiusculas("Notas", self.y, LARG_TEXTO, self.fb, 12.5, 15.6,
                                 centro=False, espaco_depois=8.0)

    def _paragrafo_nota(self, nota):
        self._paragrafo(rl(nota), self.est["nota"])

    def _desenha_epigrafe(self, texto):
        """Desenha epígrafe (citação no início do capítulo) com estilo especial:
        itálico, alinhado à direita, recuado, com espaço antes/depois."""
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.styles import ParagraphStyle
        epigrafe_style = ParagraphStyle(
            "epigrafe", parent=self.est["corpo"],
            fontSize=CORPO_PT * 0.9, leading=ENTR_LEAD * 1.1,
            alignment=TA_RIGHT, leftIndent=LARG_TEXTO * 0.15,
            firstLineIndent=0, spaceBefore=12, spaceAfter=24,
            fontName=self.fi, textColor=self.est["corpo"].textColor
        )
        self.paragrafo(rl(texto), epigrafe_style)

    # --------------------------------------------------------- pagina 1
    def desenha_capa(self, capa, preencher=True):
        dim = _tamanho_imagem(capa)
        if not dim:
            return False
        c = self.c
        r_img = dim[0] / float(dim[1])
        r_pag = PAG_L / PAG_A
        if preencher:
            # cobre a pagina toda, cortando o excesso
            if r_img >= r_pag:
                dh, dw = PAG_A, PAG_A * r_img
            else:
                dw, dh = PAG_L, PAG_L / r_img
        else:
            # imagem inteira dentro da pagina, com margens iguais
            if r_img >= r_pag:
                dw, dh = PAG_L, PAG_L / r_img
            else:
                dh, dw = PAG_A, PAG_A * r_img
        x = (PAG_L - dw) / 2.0
        y = (PAG_A - dh) / 2.0
        c.saveState()
        if not preencher:
            # fundo branco nas margens que sobrarem (letterbox)
            c.setFillColorRGB(1, 1, 1)
            c.rect(0, 0, PAG_L, PAG_A, stroke=0, fill=1)
        trilha = c.beginPath()
        trilha.rect(0, 0, PAG_L, PAG_A)
        c.clipPath(trilha, stroke=0, fill=0)
        try:
            c.drawImage(capa, x, y, dw, dh, mask="auto")
        except Exception:
            c.restoreState()
            return False
        c.restoreState()
        return True

    def desenha_folha_de_rosto(self):
        c = self.c
        titulo = self.titulo or "Sem titulo"
        tamanho = 30.0
        while tamanho > 18:
            if len(_quebra_maiusculas(titulo, self.f, tamanho,
                                      TRACK_MAIUSC * tamanho, LARG_TEXTO)) <= 3:
                break
            tamanho -= 1.0
        linhas_t = _quebra_maiusculas(titulo, self.f, tamanho,
                                      TRACK_MAIUSC * tamanho, LARG_TEXTO)
        n_t = len(linhas_t)
        creditos = []
        if self.autor:
            creditos.append(self.autor.upper())
        if self.subtitulo:
            creditos.append(self.subtitulo.upper())
        # Editora e ano (se fornecidos)
        if self.editora:
            creditos.append(self.editora.upper())
        if self.ano:
            creditos.append(self.ano)
        t_cred, lead_cred = CORPO_PT, ENTR_LEAD
        gap_por = 60.0
        m = len(creditos)
        # altura de tinta do bloco (topo das maiusculas ate a base dos creditos)
        alt_tinta = 0.68 * tamanho + tamanho * (n_t - 1) + (gap_por if m else 0) \
            + lead_cred * (m - 1) + (0.25 * t_cred if m else 0)
        centro = PAG_A * CENTRO_TITULO
        # primeira baseline do titulo, para o bloco ficar centrado em `centro`
        base_1a = centro + alt_tinta / 2.0 - 0.68 * tamanho
        y_topo = base_1a + _desloc_1a_linha(self.f, tamanho)
        self._desenha_maiusculas(titulo, y_topo, LARG_TEXTO, self.f, tamanho,
                                 tamanho, centro=True, espaco_depois=0.0,
                                 centro_em=PAG_L / 2.0)
        if m:
            # self.y ficou na ultima baseline do titulo
            for i, cr in enumerate(creditos):
                yb = self.y - gap_por - i * lead_cred
                c.setFont(self.f, t_cred)
                c.drawCentredString(PAG_L / 2.0, yb, cr,
                                    charSpace=TRACK_MAIUSC * t_cred)
        self.y = self.base_y

    # ------------------------------------------------------------ sumario
    def _entradas(self, caps):
        # Sumário: usa o índice original do livro se disponível (entradas_toc),
        # senão cai para títulos de capítulos detectados automaticamente.
        # Isso evita falsos positivos (citações, verbetes) que poluíam o sumário.
        for cap in caps:
            toc_original = cap.get("_toc_original", [])
            if toc_original:
                # Usa as entradas do sumário original: (norm, raw)
                return [(0, base.sem_marcas(raw)) for _, raw in toc_original]
        # Fallback: apenas capítulos detectados
        return [(0, base.sem_marcas(cap["titulo"])) for cap in caps]

    def _desenha_sumario(self, caps, numeros):
        c = self.c
        self.y -= 56.7
        self._desenha_maiusculas("Sumario", self.y, LARG_TEXTO, self.fb, 18.0, 23.0,
                                 centro=True, espaco_depois=26.0)
        entradas = self._entradas(caps)
        for i, (nivel, texto) in enumerate(entradas):
            tamanho = 11.5 if nivel == 0 else (10.5 if nivel == 1 else 10.0)
            leading = tamanho * 1.5
            if self.y - self.base_y < leading:
                self._nova_pagina()
                self.y = self.topo_y
            self.y -= leading
            x = M_ESQ + (0 if nivel == 0 else (24.0 if nivel == 1 else 44.0))
            fonte = self.fb if nivel == 0 else self.f
            folha = (numeros or {}).get(i, "")
            yb = self.y
            # numero progressivo antes dos capitulos (nivel 0), como no modelo
            rotulo = texto
            if nivel == 0:
                n_cap = sum(1 for j in range(i) if entradas[j][0] == 0) + 1
                rotulo = f"{n_cap}. {texto}"
            c.setFont(fonte, tamanho)
            c.drawString(x, yb, rotulo.upper())
            w_txt = self._larg(rotulo.upper(), fonte, tamanho)
            x_fim = M_ESQ + LARG_TEXTO
            x_num = x_fim - self._larg(str(folha), fonte, tamanho)
            if x_num - (x + w_txt) > 14:
                w_pt = self._larg(".", fonte, tamanho)
                pts = "." * max(0, int((x_num - (x + w_txt) - 6) / w_pt))
                c.drawString(x + w_txt + 6, yb, pts)
            if folha != "":
                c.drawRightString(x_fim, yb, str(folha))
        self.y = self.base_y

    # ------------------------------------------------------------ render
    def renderiza(self, caps, capa=None, capa_preencher=True, folha_de_rosto=False,
                  numeros=None):
        paginas = {}
        cont = [0]

        def marca(nivel, texto):
            paginas[cont[0]] = self.folha
            cont[0] += 1

        # ------------------------------------------------------- paginas de abertura
        # capa (pagina cheia, sem rodape), folha de rosto e sumario.  A quebra
        # que fecha a ultima pagina de abertura e feita pelo laco dos capitulos
        # (que tambem poe o rodape da primeira folha); por isso cada bloco so
        # quebra pagina quando existe outro bloco depois dele.
        com_sumario = len(caps) >= 2
        tem_capa = bool(capa) and self.desenha_capa(capa, capa_preencher)
        if tem_capa:
            if folha_de_rosto or com_sumario:
                # fecha a pagina da capa antes de continuar
                self._nova_pagina(com_folha=False, forcar=True)
            if folha_de_rosto:
                self.desenha_folha_de_rosto()
            if not (folha_de_rosto or com_sumario):
                # a capa e a unica pagina de abertura: apenas conta a pagina,
                # para a quebra ficar com o laco dos capitulos
                self._nova_pagina(com_folha=False)
        else:
            self.desenha_folha_de_rosto()
            if com_sumario:
                self._nova_pagina(com_folha=False, forcar=True)
            else:
                self._nova_pagina(com_folha=False)

        if com_sumario:
            self._desenha_sumario(caps, numeros or {})

        for ci, cap in enumerate(caps):
            self._nova_pagina(com_folha=True)
            # Bookmark para o capítulo (outline PDF clicável)
            bookmark_name = f"cap_{ci}"
            self.c.bookmarkPage(bookmark_name)
            self.c.addOutlineEntry(cap["titulo"], bookmark_name, level=0, closed=False)
            marca(0, cap["titulo"])
            if com_sumario:
                self._abre_capitulo(cap["titulo"])
            primeira = True
            ult_cap = (ci == len(caps) - 1)
            pars = cap["pars"]
            for k, p in enumerate(pars):
                if p["tipo"] == "h":
                    # Detecta se é epígrafe (citação logo após título do capítulo)
                    is_epigrafe = (k < 3 and p.get("cit") and primeira)
                    if is_epigrafe:
                        # Renderiza epígrafe com estilo especial
                        self._desenha_epigrafe(p["t"])
                    else:
                        self._titulo_interno(p["t"], p["nivel"] if p["nivel"] in (1, 2) else 2)
                        # Bookmark para subseção
                        sub_bookmark = f"cap_{ci}_sub_{k}"
                        self.c.bookmarkPage(sub_bookmark)
                        self.c.addOutlineEntry(base.sem_marcas(p["t"]), sub_bookmark, level=1, closed=True)
                    # Não chama marca() aqui: o sumário (_entradas) só lista capítulos
                    # agora, então contar subtítulos internos aqui desalinharia os
                    # números de página de 'numeros' com o índice de 'entradas'.
                    primeira = True      # secao nova: o paragrafo seguinte leva capitular
                    continue
                est = self.est["cit"] if p.get("cit") else self.est["corpo"]
                self.ultimo_bloco = ult_cap and k == len(pars) - 1 and not cap["notas"]
                self.paragrafo(p["t"], est, capitular=(primeira and com_sumario))
                self.ultimo_bloco = False
                primeira = False
            notas = cap["notas"]
            for k, n in enumerate(notas):
                self.ultimo_bloco = ult_cap and k == len(notas) - 1
                self._paragrafo_nota(n)
                self.ultimo_bloco = False

        self.c.showPage()
        self.c.save()
        return paginas


def gera_pdf(caps, titulo_livro, autor, subtitulo, caminho,
             capa=None, capa_preencher=True, folha_de_rosto=False,
             editora=None, ano=None):
    """Gera o PDF diagramado. `capa` (imagem JPG/PNG) vira a primeira pagina."""
    paginas = {}
    converge = False
    for _ in range(3):
        livro = LivroPDF(caminho, titulo_livro, autor, subtitulo, editora=editora, ano=ano)
        novo = livro.renderiza(caps, capa, capa_preencher, folha_de_rosto, paginas)
        if novo == paginas:
            converge = True
            break
        paginas = novo
    if not converge:
        livro = LivroPDF(caminho, titulo_livro, autor, subtitulo, editora=editora, ano=ano)
        livro.renderiza(caps, capa, capa_preencher, folha_de_rosto, paginas)


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


def le_opcoes(args):
    """Le as opcoes de linha de comando (--capa, --capa-ajuste, --folha-de-rosto, --titulo, --autor, --editora, --ano, --input-txt)."""
    opc = {
        "capa": None, "capa_ajuste": "preencher", "folha_de_rosto": False,
        "titulo": None, "autor": None, "editora": None, "ano": None,
        "input_txt": None
    }
    resto, i = [], 0
    while i < len(args):
        a = args[i]
        if a == "--capa" and i + 1 < len(args):
            opc["capa"] = args[i + 1]
            i += 2
            continue
        if a.startswith("--capa="):
            opc["capa"] = a.split("=", 1)[1]
            i += 1
            continue
        if a.startswith("--capa-ajuste="):
            opc["capa_ajuste"] = a.split("=", 1)[1].strip().lower()
            i += 1
            continue
        if a == "--folha-de-rosto":
            opc["folha_de_rosto"] = True
            i += 1
            continue
        if a == "--sem-folha-de-rosto":
            opc["folha_de_rosto"] = False
            i += 1
            continue
        if a == "--titulo" and i + 1 < len(args):
            opc["titulo"] = args[i + 1]
            i += 2
            continue
        if a.startswith("--titulo="):
            opc["titulo"] = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--autor" and i + 1 < len(args):
            opc["autor"] = args[i + 1]
            i += 2
            continue
        if a.startswith("--autor="):
            opc["autor"] = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--editora" and i + 1 < len(args):
            opc["editora"] = args[i + 1]
            i += 2
            continue
        if a.startswith("--editora="):
            opc["editora"] = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--ano" and i + 1 < len(args):
            opc["ano"] = args[i + 1]
            i += 2
            continue
        if a.startswith("--ano="):
            opc["ano"] = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--input-txt" and i + 1 < len(args):
            opc["input_txt"] = args[i + 1]
            i += 2
            continue
        if a.startswith("--input-txt="):
            opc["input_txt"] = a.split("=", 1)[1]
            i += 1
            continue
        resto.append(a)
        i += 1
    if opc["capa"] and not os.path.isfile(opc["capa"]):
        print(f"Capa ignorada: arquivo não encontrado ({opc['capa']}).")
        opc["capa"] = None
    if opc["capa_ajuste"] not in ("preencher", "conter"):
        opc["capa_ajuste"] = "preencher"
    return resto, opc


def parse_txt_estruturado(caminho_txt):
    """Lê livro_corrigido.txt e reconstrói a estrutura de capítulos/parágrafos/notas.
    Formato esperado:
    SUMÁRIO
    =...

    =====
    Título do Capítulo
    =====

    ## Subtítulo
    Texto do parágrafo...

    --- NOTAS DO CAPÍTULO ---
    1. Nota...
    """
    with open(caminho_txt, 'r', encoding='utf-8') as f:
        conteudo = f.read()

    caps = []
    linhas = conteudo.split('\n')

    i = 0
    # Pula sumário até linha vazia dupla ou "====="
    while i < len(linhas):
        if linhas[i].strip() == '=' * 70:
            break
        i += 1

    while i < len(linhas):
        if linhas[i].strip() == '=' * 70:
            i += 1
            if i >= len(linhas):
                break
            # Título do capítulo
            titulo_cap = linhas[i].strip()
            i += 1
            if i < len(linhas) and linhas[i].strip() == '=' * 70:
                i += 1

            pars = []
            notas = []
            em_notas = False

            while i < len(linhas):
                linha = linhas[i]

                # Fim do capítulo - próximo "=====" ou fim do arquivo
                if linha.strip() == '=' * 70:
                    break

                if linha.strip() == '--- NOTAS DO CAPÍTULO ---':
                    em_notas = True
                    i += 1
                    continue

                if not em_notas:
                    if linha.startswith('## '):
                        pars.append({"tipo": "h", "t": linha[3:], "nivel": 2})
                    elif linha.startswith('   - '):
                        # Item do sumário interno, ignora
                        pass
                    elif linha.strip():
                        pars.append({"tipo": "corpo", "t": linha, "cit": False})
                else:
                    if linha.strip() and not linha.startswith('  ['):
                        notas.append(linha.strip())

                i += 1

            caps.append({
                "titulo": titulo_cap,
                "pars": pars,
                "notas": notas,
                "pags": (1, 1)  # placeholder
            })
        else:
            i += 1

    return caps


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    args, opc = le_opcoes(sys.argv[1:])
    if not args:
        print(__doc__)
        return
    entrada = args[0]
    pasta = args[1] if len(args) > 1 else pasta_unica(nome_do_livro(entrada))
    os.makedirs(pasta, exist_ok=True)

    # MODO 2: --input-txt (segunda passagem: texto já corrigido)
    if opc["input_txt"]:
        txt_path = Path(opc["input_txt"])
        if not txt_path.exists():
            print(f"Arquivo --input-txt não encontrado: {txt_path}")
            return

        print(f"📖  Lendo texto corrigido de: {txt_path}")
        caps = parse_txt_estruturado(str(txt_path))

        # Metadados: tenta inferir do PDF original se fornecido, senão usa CLI
        titulo_livro = opc["titulo"] or "Título Desconhecido"
        autor = opc["autor"] or "Autor Desconhecido"
        subtitulo = ""
        editora = opc["editora"]
        ano = opc["ano"]

        # Se entrada é PDF, tenta ler metadados dele
        if entrada.lower().endswith('.pdf'):
            try:
                doc = fitz.open(entrada)
                meta = doc.metadata or {}
                if not opc["titulo"] and meta.get("title"):
                    titulo_livro = meta["title"].strip()
                if not opc["autor"] and meta.get("author"):
                    autor = meta["author"].strip()
                doc.close()
            except Exception:
                pass

        gera_txt(caps, os.path.join(pasta, "livro_limpo.txt"))
        gera_docx(caps, titulo_livro, autor, subtitulo, os.path.join(pasta, "livro_editavel.docx"))

        gera_pdf(caps, titulo_livro, autor, subtitulo,
                 os.path.join(pasta, "livro_diagramado.pdf"),
                 capa=opc["capa"], capa_preencher=(opc["capa_ajuste"] == "preencher"),
                 folha_de_rosto=opc["folha_de_rosto"],
                 editora=editora, ano=ano)

        print(f"\n✅  PDF regenerado com correções aplicadas em: ./{pasta}/")
        return

    # MODO 1: Processamento normal (PDF -> extração -> correção OCR -> diagramação)
    doc = fitz.open(entrada)
    paginas = [
        {"n": i, "W": p.rect.width, "H": p.rect.height, "linhas": base.extrai_linhas_pagina(p)}
        for i, p in enumerate(doc, 1)
    ]

    rep_cab, rep_rod = base.detecta_cabecalhos_rodapes_repetidos(paginas)

    removidas = 0
    folhas_rosto = 0
    for pg in paginas:
        antes = len(pg["linhas"])
        tams = sorted(l["size"] for l in pg["linhas"] if l["raw"].strip())
        med = tams[len(tams) // 2] if tams else 0.0
        pg["linhas"] = [
            l for idx, l in enumerate(pg["linhas"])
            if not base.eh_lixo(l, idx, antes, pg["H"], rep_cab, rep_rod, med)
        ]
        removidas += antes - len(pg["linhas"])

    pares = [(round(l["size"], 1), len(l["raw"])) for pg in paginas for l in pg["linhas"]]
    if not pares:
        print("Nenhum texto encontrado: verifique se o PDF possui camada de OCR.")
        return
    corpo = base.mediana_ponderada(pares)
    ms = [m for m in (base.margens(pg["linhas"], corpo) for pg in paginas) if m]
    glob = (base.percentil([m[0] for m in ms], 0.5), base.percentil([m[1] for m in ms], 0.5)) if ms else (0, paginas[0]["W"])

    # Folha de rosto original: aproveita título/autor e não a reinjeta no corpo
    rosto = detecta_folha_de_rosto(paginas, corpo)
    if rosto:
        idx_rosto, titulo_rosto, autor_rosto, subtitulo_rosto = rosto
        tiradas = set(idx_rosto)
        paginas = [pg for i, pg in enumerate(paginas) if i not in tiradas]
        folhas_rosto += len(tiradas)
    else:
        titulo_rosto = autor_rosto = subtitulo_rosto = ""

    # Ficha catalográfica: remove páginas técnicas de biblioteca
    indices_ficha = detecta_ficha_catalografica(paginas)
    if indices_ficha:
        print(f"🗑️  Removendo ficha catalográfica: páginas {[i+1 for i in sorted(indices_ficha)]}")
        paginas = [pg for i, pg in enumerate(paginas) if i not in indices_ficha]

    # Detecta sumário com ML + heurística
    if SUMARIO_DETECTOR_DISPONIVEL:
        detector = SumarioDetector(confidence_threshold=0.7)
        pags_sumario, tipo_sumario, conf_sumario = detector.detecta(paginas)
        if pags_sumario:
            print(f"📑 Sumário detectado (ML): páginas {sorted([p+1 for p in pags_sumario])} | Tipo: {['resumido','analítico','remissivo'][tipo_sumario-1] if tipo_sumario > 0 else 'nenhum'} | Conf: {conf_sumario:.2f}")
    else:
        # Fallback heurístico
        pags_sumario, _ = detecta_paginas_sumario_original(paginas)

    titulo_livro, autor, subtitulo = infere_metadados(doc, paginas)
    if rosto:
        tp, mt = base.norm(titulo_rosto), base.norm(titulo_livro)
        if titulo_rosto and (not mt or mt not in tp):
            titulo_livro = titulo_rosto
        if autor_rosto and (not autor or autor == "Autor"
                            or base.norm(autor) not in base.norm(autor_rosto)):
            autor = autor_rosto
        if subtitulo_rosto and not subtitulo:
            subtitulo = subtitulo_rosto

    caps = processa_capitulos(paginas, corpo, glob)
    todos = [p["t"] for c in caps for p in c["pars"]] + [n for c in caps for n in c["notas"]]
    troca = base.acha_correcoes_ocr(todos)
    for c in caps:
        for p in c["pars"]:
            p["t"] = base.aplica_correcoes_ocr(p["t"], troca)
        c["notas"] = [base.aplica_correcoes_ocr(n, troca) for n in c["notas"]]
    with open(os.path.join(pasta, "correcoes_ocr.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(f"{a} -> {b}" for a, b in sorted(troca.items())) or "Nenhuma correção automática.")
    total_pars = sum(len(c["pars"]) for c in caps)
    total_notas = sum(len(c["notas"]) for c in caps)

    gera_txt(caps, os.path.join(pasta, "livro_limpo.txt"))
    gera_docx(caps, titulo_livro, autor, subtitulo, os.path.join(pasta, "livro_editavel.docx"))
    # CLI options override inferred metadata
    if opc["titulo"]:
        titulo_livro = opc["titulo"]
    if opc["autor"]:
        autor = opc["autor"]
    editora = opc["editora"]
    ano = opc["ano"]

    gera_pdf(caps, titulo_livro, autor, subtitulo,
             os.path.join(pasta, "livro_diagramado.pdf"),
             capa=opc["capa"], capa_preencher=(opc["capa_ajuste"] == "preencher"),
             folha_de_rosto=opc["folha_de_rosto"],
             editora=editora, ano=ano)

    rel = [
        f"Título detectado: {titulo_livro} | Autor: {autor}",
        f"Páginas lidas: {len(paginas)} | Fonte mediana do corpo: {corpo} pt",
        f"Cabeçalhos/rodapés removidos: {removidas}",
        f"Correções automáticas de OCR: {len(troca)} (veja correcoes_ocr.txt)",
        f"Capítulos estruturados: {len(caps)} | Parágrafos: {total_pars} | Notas: {total_notas}",
        "",
        "Sumário de Capítulos Detectados:"
    ]
    for c in caps:
        rel.append(
            f"  [PDF págs. {c['pags'][0]}-{c['pags'][1]}] {c['titulo']} "
            f"({len(c['pars'])} parágrafos, {len(c['notas'])} notas no fim do capítulo)"
        )

    with open(os.path.join(pasta, "relatorio.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(rel))

    print("\n".join(rel))
    print(f"\nConcluído! Arquivos gerados em: ./{pasta}/")


if __name__ == "__main__":
    main()