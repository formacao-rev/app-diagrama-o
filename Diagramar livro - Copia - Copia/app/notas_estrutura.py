#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notas_estrutura.py - Reconhece e classifica estrutura de notas

Classes de notas:
- RODAPE: notas de rodapé da página (chamada no texto, nota no rodapé)
- FIM_CAPITULO: notas agrupadas no final do capítulo
- BIBLIOGRAFIA: referências bibliográficas formatadas
- NOTA_EDITOR: notas do editor/tradutor (N.E., N.T.)
- OUTRAS: notas não classificadas
"""

import re
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional

class TipoNota(Enum):
    RODAPE = "rodapé"
    FIM_CAPITULO = "fim_capítulo"
    BIBLIOGRAFIA = "bibliografia"
    NOTA_EDITOR = "nota_editor"
    OUTRAS = "outras"

@dataclass
class NotaClassificada:
    texto: str
    tipo: TipoNota
    numero: Optional[str] = None
    autor_ano: Optional[str] = None  # Para bibliografia: "Silva 2020"
    confianca: float = 0.0

# Regex patterns para classificação
PATTERNS = {
    TipoNota.BIBLIOGRAFIA: [
        # "Autor, A. (2020). Título. Editora."
        r'^[A-ZÀ-Ý][a-zà-ÿ]+,\s+[A-ZÀ-Ý]\.\s*\(\d{4}\)\.',
        # "AUTOR, A. Ano. Título. Local: Editora."
        r'^[A-ZÀ-Ý][A-ZÀ-Ý\s]+,\s+[A-ZÀ-Ý]\.\s*\d{4}\.',
        # ISBN, DOI
        r'(ISBN|DOI)\s*[\d\-]+',
        # "Disponível em: http..."
        r'[Dd]ispon[ií]vel\s+(em|na|no)\s+[:\s]*https?://',
        # Múltiplas páginas de referência
        r'\b(p\.\s*\d+|pp\.\s*\d+\-\d+)',
    ],
    TipoNota.NOTA_EDITOR: [
        r'^(N\.?\s*[EET]\.?|N\.?\s*[TD]\.?|Nota\s+do\s+[Ee]ditor|Nota\s+do\s+[Tt]radutor)[\s:\-]',
        r'^\[?\s*(N\.?E\.?|N\.?T\.?)\s*\]?',
    ],
    TipoNota.FIM_CAPITULO: [
        # Notas sequenciais no final: "1. Texto", "2. Texto"
        r'^\d{1,3}[\.\)]\s+',
        # Título "NOTAS" ou "NOTAS DO CAPÍTULO"
        r'^(NOTAS|NOTAS\s+DO\s+CAP[IÍ]TULO|NOTES|ENDNOTES)\s*$',
    ],
    TipoNota.RODAPE: [
        # Marcadores de rodapé na página: (1), ¹, [1], *
        r'^[\\(\[]?(\d{1,3}|\*+)[\\)\]]?\s+',
        r'^[⁰¹²³⁴⁵⁶⁷⁸⁹]{1,3}\s*',
    ]
}

def compila_patterns():
    """Compila regex patterns para uso eficiente."""
    return {tipo: [re.compile(p, re.I | re.MULTILINE) for p in patterns]
            for tipo, patterns in PATTERNS.items()}

PATTERNS_COMPILADOS = compila_patterns()

def detecta_tipo_nota(texto: str, contexto: dict = None) -> tuple:
    """
    Detecta o tipo de uma nota baseado no texto e contexto.

    Args:
        texto: Texto da nota
        contexto: Dict opcional com:
            - 'posicao_pagina': 'topo', 'meio', 'rodape', 'fim_pagina'
            - 'sequencia_notas': int (número de notas vistas em sequência)
            - 'tem_chamada_texto': bool (se há chamada no corpo do texto)
            - 'pagina_fim_capitulo': bool

    Returns:
        (TipoNota, confiança 0-1)
    """
    texto_limpo = texto.strip()
    if not texto_limpo:
        return TipoNota.OUTRAS, 0.0

    scores = {}

    # Verifica patterns de cada tipo
    for tipo, patterns in PATTERNS_COMPILADOS.items():
        score = 0
        for pattern in patterns:
            if pattern.search(texto_limpo):
                score += 1
        if score > 0:
            scores[tipo] = score / len(patterns)

    # Boost contextual
    if contexto:
        pos = contexto.get('posicao_pagina')
        seq = contexto.get('sequencia_notas', 0)
        fim_cap = contexto.get('pagina_fim_capitulo', False)
        tem_chamada = contexto.get('tem_chamada_texto', False)

        # Notas de rodapé aparecem no rodapé da página
        if pos == 'rodape':
            scores[TipoNota.RODAPE] = scores.get(TipoNota.RODAPE, 0) + 0.5

        # Sequência longa no fim = fim de capítulo
        if fim_cap and seq > 3:
            scores[TipoNota.FIM_CAPITULO] = scores.get(TipoNota.FIM_CAPITULO, 0) + 0.4

        # Tem chamada no texto = provavelmente rodapé
        if tem_chamada:
            scores[TipoNota.RODAPE] = scores.get(TipoNota.RODAPE, 0) + 0.3

    # Default se nada detectou
    if not scores:
        return TipoNota.OUTRAS, 0.1

    # Retorna o de maior score
    melhor = max(scores, key=scores.get)
    return melhor, min(scores[melhor], 1.0)

def classifica_bloco_notas(linhas_notas: List[dict], pagina_info: dict = None) -> List[NotaClassificada]:
    """
    Classifica um bloco de linhas que formam notas.

    Args:
        linhas_notas: Lista de dicts com 'raw', 't' (texto com marcadores)
        pagina_info: Info da página (opcional)

    Returns:
        Lista de NotaClassificada
    """
    resultados = []

    # Junta linhas que formam uma nota completa
    notas_agrupadas = agrupa_linhas_em_notas(linhas_notas)

    for i, (texto_completo, linhas_da_nota) in enumerate(notas_agrupadas):
        # Contexto
        ctx = {
            'sequencia_notas': len(notas_agrupadas),
            'pagina_fim_capitulo': pagina_info.get('fim_capitulo', False) if pagina_info else False,
            'posicao_pagina': pagina_info.get('posicao', 'meio') if pagina_info else 'meio',
        }

        tipo, conf = detecta_tipo_nota(texto_completo, ctx)

        # Extrai número se houver
        num_match = re.match(r'^[\\(\[]?(\d{1,3})[\\)\]]?[\.\s]', texto_completo.strip())
        numero = num_match.group(1) if num_match else None

        # Para bibliografia, tenta extrair autor/ano
        autor_ano = None
        if tipo == TipoNota.BIBLIOGRAFIA:
            autor_ano = extrai_autor_ano(texto_completo)

        resultados.append(NotaClassificada(
            texto=texto_completo,
            tipo=tipo,
            numero=numero,
            autor_ano=autor_ano,
            confianca=conf
        ))

    return resultados

def agrupa_linhas_em_notas(linhas: List[dict]) -> List[tuple]:
    """
    Agrupa linhas consecutivas em notas completas.
    Retorna lista de (texto_completo, [linhas_da_nota]).
    """
    if not linhas:
        return []

    grupos = []
    atual_texto = []
    atual_linhas = []

    for l in linhas:
        raw = l.get('raw', '').strip()
        if not raw:
            continue

        # Verifica se inicia nova nota
        is_nova = False
        raw_limpo = raw.strip()

        # Padrões de início de nota
        if re.match(r'^[\\(\[]?\d{1,3}[\\)\]]?[\.\s]', raw_limpo):
            is_nova = True
        elif re.match(r'^[⁰¹²³⁴⁵⁶⁷⁸⁹]{1,3}\s*', raw_limpo):
            is_nova = True
        elif re.match(r'^\*+\s+', raw_limpo):
            is_nova = True
        elif len(atual_texto) == 0:
            is_nova = True

        if is_nova and atual_texto:
            grupos.append((" ".join(atual_texto), atual_linhas))
            atual_texto = []
            atual_linhas = []

        atual_texto.append(raw_limpo)
        atual_linhas.append(l)

    if atual_texto:
        grupos.append((" ".join(atual_texto), atual_linhas))

    return grupos

def extrai_autor_ano(texto: str) -> Optional[str]:
    """Extrai 'Autor Ano' de referências bibliográficas."""
    # "Silva, J. (2020). Título..."
    m = re.search(r'^([A-ZÀ-Ý][a-zà-ÿ]+(?:,\s*[A-Z]\.)?)\s*\(\s*(\d{4})\s*\)', texto)
    if m:
        return f"{m.group(1)} {m.group(2)}"

    # "SILVA, J. 2020. Título..."
    m = re.search(r'^([A-ZÀ-Ý][A-ZÀ-Ý\s]+),\s*([A-Z]\.)\s*(\d{4})\.', texto)
    if m:
        return f"{m.group(1)}, {m.group(2)} {m.group(3)}"

    return None

def separa_notas_por_tipo(notas: List[NotaClassificada]) -> dict:
    """Agrupa notas por tipo para processamento diferenciado."""
    from collections import defaultdict
    agrupadas = defaultdict(list)
    for n in notas:
        agrupadas[n.tipo].append(n)
    return dict(agrupadas)


# Integração com diagramar_livro_v2
def processa_notas_capitulo(cap_data: dict) -> dict:
    """
    Processa as notas de um capítulo já estruturado,
    separando por tipo para tratamento diferenciado.

    Args:
        cap_data: dict com 'pars', 'notas', 'titulo', etc.

    Returns:
        cap_data atualizado com 'notas_por_tipo'
    """
    # Converte notas brutas para formato de linhas
    linhas_notas = []
    for nota in cap_data.get('notas', []):
        # Assume que nota já é string limpa
        linhas_notas.append({'raw': nota, 't': nota})

    notas_classificadas = classifica_bloco_notas(linhas_notas, {'fim_capitulo': True})
    por_tipo = separa_notas_por_tipo(notas_classificadas)

    cap_data['notas_por_tipo'] = por_tipo
    cap_data['notas_classificadas'] = notas_classificadas

    return cap_data


if __name__ == "__main__":
    # Testes rápidos
    testes = [
        ("1. Silva, J. (2020). Capital. Editora.", {'fim_capitulo': True}),
        ("(1) Nota de rodapé aqui.", {'posicao_pagina': 'rodape'}),
        ("NOTAS DO CAPÍTULO", {'fim_capitulo': True}),
        ("[N.E.] Nota do editor.", {}),
        ("2. Segunda nota do capítulo.", {'fim_capitulo': True, 'sequencia_notas': 2}),
    ]

    for texto, ctx in testes:
        tipo, conf = detecta_tipo_nota(texto, ctx)
        print(f"'{texto[:50]}...' -> {tipo.value} (conf: {conf:.2f})")