#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
perfis_diagramacao.py - Perfis de diagramação para diferentes tipos de publicação

Cada perfil define: margens, fontes, espaçamento, capitulares, fólhas, sumário, etc.
Formatos suportados: YAML, JSON, dict Python.
"""

import os
import json
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from pathlib import Path

# YAML opcional (para arquivos .yaml)
try:
    import yaml
    YAML_DISPONIVEL = True
except ImportError:
    YAML_DISPONIVEL = False

# =============================================================================
# DEFINIÇÃO DO PERFIL
# =============================================================================

@dataclass
class Margens:
    """Margens da página em centímetros."""
    superior: float = 2.5
    inferior: float = 2.0
    esquerda: float = 2.0
    direita: float = 1.8

@dataclass
class FonteConfig:
    """Configuração de fonte."""
    familia: str = "Times New Roman"
    corpo_pt: float = 11.0
    entrelinha: float = 1.5
    tracking_maiusculas: float = 0.075  # 7.5% do tamanho

@dataclass
class CapituloConfig:
    """Configuração de abertura de capítulo."""
    comeca_pagina_impar: bool = True      # Recto (página direita)
    folha_cega_antes: bool = False        # Página em branco antes
    letra_capitular: bool = True          # Drop cap
    capitular_linhas: int = 2
    capitular_tamanho: float = 3.5        # Múltiplo do corpo
    espaco_apos_titulo: float = 1.5       # em unidades de entrelinha
    numeracao: str = "arabica"            # arabica, romana, nenhuma
    prefixo: str = ""                     # Ex: "CAPÍTULO "

@dataclass
class SumarioConfig:
    """Configuração do sumário."""
    inclui_subcapitulos: bool = True
    max_nivel: int = 3
    usa_pontos_lideres: bool = True
    numeracao_progressiva: bool = True
    titulo: str = "Sumário"
    alinhamento_titulo: str = "centro"    # centro, esquerda

@dataclass
class NotasConfig:
    """Configuração de notas."""
    tipo: str = "fim_capitulo"            # rodape, fim_capitulo, fim_livro
    numeracao_por_capitulo: bool = True
    formato_chamada: str = "sobrescrito"  # sobrescrito, parentese, colchete
    separador_notas: str = "espaco"       # espaco, linha, nenhum

@dataclass
class FolhasConfig:
    """Configuração de fólhas (numeração de páginas)."""
    estilo: str = "alternado"             # alternado, centralizado, externo
    fonte_tamanho: float = 10.0
    incluir_total: bool = False           # "página X de Y"
    inicio_numeracao: int = 1             # Onde começa a contagem

@dataclass
class CapaConfig:
    """Configuração de capa."""
    usa_capa_personalizada: bool = False
    mantem_folha_rosto: bool = True
    ajuste_imagem: str = "preencher"      # preencher, conter

@dataclass
class PerfilDiagramacao:
    """Perfil completo de diagramação."""
    nome: str
    descricao: str
    tamanho_pagina: str = "A4"            # A4, A5, 16x23, 14x21, personalizado
    largura_cm: Optional[float] = None    # Se personalizado
    altura_cm: Optional[float] = None

    margens: Margens = field(default_factory=Margens)
    fonte_corpo: FonteConfig = field(default_factory=FonteConfig)
    fonte_titulos: FonteConfig = field(default_factory=lambda: FonteConfig(
        familia="Times New Roman", corpo_pt=14, entrelinha=1.3
    ))
    capitulo: CapituloConfig = field(default_factory=CapituloConfig)
    sumario: SumarioConfig = field(default_factory=SumarioConfig)
    notas: NotasConfig = field(default_factory=NotasConfig)
    folhas: FolhasConfig = field(default_factory=FolhasConfig)
    capa: CapaConfig = field(default_factory=CapaConfig)

    # Configurações avançadas
    hifenizacao: bool = True
    hifenizacao_idioma: str = "pt_BR"
    controle_viuva_orfas: bool = True
    grid_baseline: bool = False           # Alinha tudo à grade de leading
    small_caps_reais: bool = False        # Usa OpenType smcp se disponível

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_yaml(self) -> str:
        if not YAML_DISPONIVEL:
            raise RuntimeError("PyYAML não instalado. Use .json ou instale: pip install pyyaml")
        return yaml.dump(self.to_dict(), allow_unicode=True, sort_keys=False)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def salva(self, caminho: str):
        """Salva perfil em YAML ou JSON."""
        path = Path(caminho)
        if path.suffix.lower() in ('.yaml', '.yml'):
            if not YAML_DISPONIVEL:
                raise RuntimeError("PyYAML não instalado. Use .json ou instale: pip install pyyaml")
            path.write_text(self.to_yaml(), encoding='utf-8')
        elif path.suffix.lower() == '.json':
            path.write_text(self.to_json(), encoding='utf-8')
        else:
            if YAML_DISPONIVEL:
                path.write_text(self.to_yaml(), encoding='utf-8')
            else:
                path.write_text(self.to_json(), encoding='utf-8')

    @classmethod
    def carrega(cls, caminho: str) -> 'PerfilDiagramacao':
        """Carrega perfil de YAML ou JSON."""
        path = Path(caminho)
        texto = path.read_text(encoding='utf-8')

        if path.suffix.lower() in ('.yaml', '.yml'):
            if not YAML_DISPONIVEL:
                raise RuntimeError("PyYAML não instalado. Use .json ou instale: pip install pyyaml")
            data = yaml.safe_load(texto)
        elif path.suffix.lower() == '.json':
            data = json.loads(texto)
        else:
            if YAML_DISPONIVEL:
                data = yaml.safe_load(texto)
            else:
                data = json.loads(texto)

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PerfilDiagramacao':
        """Cria perfil a partir de dict (aninhado)."""
        # Converte dicts aninhados para dataclasses
        def converte(d, classe):
            if isinstance(d, dict):
                return classe(**{k: converte(v, type(v)) if isinstance(v, dict) else v
                                for k, v in d.items()})
            return d

        perfil = cls(
            nome=data.get('nome', 'Personalizado'),
            descricao=data.get('descricao', ''),
            tamanho_pagina=data.get('tamanho_pagina', 'A4'),
            largura_cm=data.get('largura_cm'),
            altura_cm=data.get('altura_cm'),
        )

        if 'margens' in data:
            perfil.margens = Margens(**data['margens'])
        if 'fonte_corpo' in data:
            perfil.fonte_corpo = FonteConfig(**data['fonte_corpo'])
        if 'fonte_titulos' in data:
            perfil.fonte_titulos = FonteConfig(**data['fonte_titulos'])
        if 'capitulo' in data:
            perfil.capitulo = CapituloConfig(**data['capitulo'])
        if 'sumario' in data:
            perfil.sumario = SumarioConfig(**data['sumario'])
        if 'notas' in data:
            perfil.notas = NotasConfig(**data['notas'])
        if 'folhas' in data:
            perfil.folhas = FolhasConfig(**data['folhas'])
        if 'capa' in data:
            perfil.capa = CapaConfig(**data['capa'])

        # Campos simples
        for campo in ['hifenizacao', 'hifenizacao_idioma', 'controle_viuva_orfas',
                      'grid_baseline', 'small_caps_reais']:
            if campo in data:
                setattr(perfil, campo, data[campo])

        return perfil

    def aplica_no_diagramar_livro(self) -> Dict[str, Any]:
        """
        Converte perfil para argumentos do diagramar_livro_v2.py.
        Retorna dict com parâmetros que o módulo principal entende.
        """
        # Converte cm para pontos (1 cm = 28.3465 pt)
        cm2pt = 28.3465

        return {
            # Página
            'page_width': (self.largura_cm or 21.0) * cm2pt,
            'page_height': (self.altura_cm or 29.7) * cm2pt,
            'margin_left': self.margens.esquerda * cm2pt,
            'margin_right': self.margens.direita * cm2pt,
            'margin_top': self.margens.superior * cm2pt,
            'margin_bottom': self.margens.inferior * cm2pt,

            # Fonte
            'font_family': self.fonte_corpo.familia,
            'font_size': self.fonte_corpo.corpo_pt,
            'leading': self.fonte_corpo.corpo_pt * self.fonte_corpo.entrelinha,
            'font_bold': self.fonte_corpo.familia.replace('Regular', 'Bold').replace('Roman', 'Bold'),
            'font_italic': self.fonte_corpo.familia.replace('Regular', 'Italic').replace('Roman', 'Italic'),

            # Capítulo
            'chapter_start_odd': self.capitulo.comeca_pagina_impar,
            'chapter_blank_before': self.capitulo.folha_cega_antes,
            'drop_cap': self.capitulo.letra_capitular,
            'drop_cap_lines': self.capitulo.capitular_linhas,
            'drop_cap_scale': self.capitulo.capitular_tamanho,
            'chapter_numbering': self.capitulo.numeracao,
            'chapter_prefix': self.capitulo.prefixo,

            # Sumário
            'toc_include_subsections': self.sumario.inclui_subcapitulos,
            'toc_max_level': self.sumario.max_nivel,
            'toc_leader_dots': self.sumario.usa_pontos_lideres,
            'toc_progressive_numbering': self.sumario.numeracao_progressiva,
            'toc_title': self.sumario.titulo,

            # Notas
            'notes_type': self.notas.tipo,
            'notes_restart_per_chapter': self.notas.numeracao_por_capitulo,
            'notes_call_format': self.notas.formato_chamada,

            # Fólhas
            'folio_style': self.folhas.estilo,
            'folio_font_size': self.folhas.fonte_tamanho,
            'folio_include_total': self.folhas.incluir_total,

            # Hifenização
            'hyphenate': self.hifenizacao,
            'hyphenation_lang': self.hifenizacao_idioma,

            # Capa
            'cover_image': None,  # Definido em runtime
            'cover_fit': self.capa.ajuste_imagem,
            'keep_half_title': self.capa.mantem_folha_rosto,
        }


# =============================================================================
# PERFIS PREDEFINIDOS
# =============================================================================

def cria_perfil_abnt() -> PerfilDiagramacao:
    """Perfil ABNT NBR 14724 (Teses/Dissertações)."""
    return PerfilDiagramacao(
        nome="ABNT NBR 14724",
        descricao="Teses e Dissertações (norma brasileira)",
        tamanho_pagina="A4",
        margens=Margens(superior=3.0, inferior=2.0, esquerda=3.0, direita=2.0),
        fonte_corpo=FonteConfig(familia="Times New Roman", corpo_pt=12, entrelinha=1.5),
        capitulo=CapituloConfig(
            comeca_pagina_impar=True,
            folha_cega_antes=True,
            letra_capitular=False,
            numeracao="arabica",
            prefixo="CAPÍTULO "
        ),
        sumario=SumarioConfig(
            inclui_subcapitulos=True,
            max_nivel=3,
            titulo="SUMÁRIO",
            alinhamento_titulo="centro"
        ),
        notas=NotasConfig(
            tipo="fim_capitulo",
            numeracao_por_capitulo=True
        ),
        folhas=FolhasConfig(
            estilo="centralizado",
            fonte_tamanho=10,
            incluir_total=False
        ),
        capa=CapaConfig(
            usa_capa_personalizada=False,
            mantem_folha_rosto=True
        ),
        hifenizacao=True,
        hifenizacao_idioma="pt_BR"
    )


def cria_perfil_livro_comercial() -> PerfilDiagramacao:
    """Perfil Livro Comercial (16x23 cm ou 14x21 cm)."""
    return PerfilDiagramacao(
        nome="Livro Comercial",
        descricao="Livros de não-ficção, romances, ensaios (formato 16x23 ou 14x21)",
        tamanho_pagina="16x23",
        largura_cm=16.0,
        altura_cm=23.0,
        margens=Margens(superior=2.5, inferior=2.0, esquerda=2.0, direita=1.8),
        fonte_corpo=FonteConfig(
            familia="Garamond", corpo_pt=11, entrelinha=1.4
        ),
        fonte_titulos=FonteConfig(
            familia="Garamond", corpo_pt=13, entrelinha=1.3
        ),
        capitulo=CapituloConfig(
            comeca_pagina_impar=True,
            folha_cega_antes=False,
            letra_capitular=True,
            capitular_linhas=2,
            numeracao="arabica"
        ),
        sumario=SumarioConfig(
            inclui_subcapitulos=False,
            max_nivel=1,
            titulo="Sumário",
            alinhamento_titulo="centro"
        ),
        notas=NotasConfig(
            tipo="fim_capitulo",
            numeracao_por_capitulo=True
        ),
        folhas=FolhasConfig(
            estilo="alternado",
            fonte_tamanho=9.5
        ),
        capa=CapaConfig(
            usa_capa_personalizada=True,
            mantem_folha_rosto=True,
            ajuste_imagem="preencher"
        ),
        hifenizacao=True,
        hifenizacao_idioma="pt_BR",
        small_caps_reais=True
    )


def cria_perfil_tese() -> PerfilDiagramacao:
    """Perfil Tese/Dissertação (formato A4, mais formal)."""
    return PerfilDiagramacao(
        nome="Tese/Dissertação",
        descricao="Teses acadêmicas formato A4 (pode usar ABNT ou norma da universidade)",
        tamanho_pagina="A4",
        margens=Margens(superior=3.0, inferior=2.5, esquerda=3.5, direita=2.5),
        fonte_corpo=FonteConfig(familia="Times New Roman", corpo_pt=12, entrelinha=1.5),
        capitulo=CapituloConfig(
            comeca_pagina_impar=True,
            folha_cega_antes=True,
            letra_capitular=False,
            numeracao="arabica",
            prefixo="CAPÍTULO "
        ),
        sumario=SumarioConfig(
            inclui_subcapitulos=True,
            max_nivel=3,
            titulo="SUMÁRIO",
            alinhamento_titulo="centro"
        ),
        notas=NotasConfig(
            tipo="rodape",
            numeracao_por_capitulo=True
        ),
        folhas=FolhasConfig(
            estilo="centralizado",
            fonte_tamanho=10
        ),
        capa=CapaConfig(
            mantem_folha_rosto=True
        ),
        hifenizacao=True
    )


def cria_perfil_artigo_cientifico() -> PerfilDiagramacao:
    """Perfil Artigo Científico (duas colunas, formato revista)."""
    return PerfilDiagramacao(
        nome="Artigo Científico",
        descricao="Artigos para periódicos (duas colunas, A4)",
        tamanho_pagina="A4",
        margens=Margens(superior=2.5, inferior=2.0, esquerda=2.0, direita=2.0),
        fonte_corpo=FonteConfig(
            familia="Times New Roman", corpo_pt=10, entrelinha=1.2
        ),
        capitulo=CapituloConfig(
            comeca_pagina_impar=False,
            folha_cega_antes=False,
            letra_capitular=False,
            numeracao="nenhuma"
        ),
        sumario=SumarioConfig(
            inclui_subcapitulos=False,
            max_nivel=1,
            titulo="Sumário"
        ),
        notas=NotasConfig(
            tipo="rodape",
            numeracao_por_capitulo=False
        ),
        folhas=FolhasConfig(
            estilo="centralizado",
            fonte_tamanho=9
        ),
        # Duas colunas seria configuração especial no layout engine
        hifenizacao=True,
        hifenizacao_idioma="en_US"  # Artigos em inglês
    )


def cria_perfil_livro_bolso() -> PerfilDiagramacao:
    """Perfil Livro de Bolso (pocket book)."""
    return PerfilDiagramacao(
        nome="Livro de Bolso",
        descricao="Pocket books (11x18 cm aprox), papel offset, custo reduzido",
        tamanho_pagina="11x18",
        largura_cm=11.0,
        altura_cm=18.0,
        margens=Margens(superior=1.8, inferior=1.5, esquerda=1.5, direita=1.3),
        fonte_corpo=FonteConfig(
            familia="Times New Roman", corpo_pt=9.5, entrelinha=1.3
        ),
        capitulo=CapituloConfig(
            comeca_pagina_impar=False,
            folha_cega_antes=False,
            letra_capitular=False,
            numeracao="arabica"
        ),
        sumario=SumarioConfig(
            inclui_subcapitulos=False,
            max_nivel=1,
            titulo="Sumário"
        ),
        notas=NotasConfig(
            tipo="fim_livro",
            numeracao_por_capitulo=False
        ),
        folhas=FolhasConfig(
            estilo="centralizado",
            fonte_tamanho=8
        ),
        hifenizacao=True
    )


# =============================================================================
# REGISTRO E GERENCIAMENTO
# =============================================================================

PERFIS_PREDEFINIDOS = {
    'abnt': cria_perfil_abnt,
    'livro_comercial': cria_perfil_livro_comercial,
    'tese': cria_perfil_tese,
    'artigo': cria_perfil_artigo_cientifico,
    'bolso': cria_perfil_livro_bolso,
}

def lista_perfis() -> Dict[str, str]:
    """Retorna dict {id: descrição} dos perfis disponíveis."""
    return {
        'abnt': 'ABNT NBR 14724 (Teses/Dissertações)',
        'livro_comercial': 'Livro Comercial (16x23 / 14x21)',
        'tese': 'Tese/Dissertação (A4 formal)',
        'artigo': 'Artigo Científico (duas colunas)',
        'bolso': 'Livro de Bolso (11x18 cm)',
    }

def get_perfil(perfil_id: str) -> PerfilDiagramacao:
    """Retorna instância do perfil pelo ID."""
    if perfil_id in PERFIS_PREDEFINIDOS:
        return PERFIS_PREDEFINIDOS[perfil_id]()
    raise ValueError(f"Perfil desconhecido: {perfil_id}")

def salva_perfil_padrao(pasta: str = "perfis"):
    """Salva todos os perfis predefinidos em arquivos YAML."""
    path = Path(pasta)
    path.mkdir(exist_ok=True)

    for pid, factory in PERFIS_PREDEFINIDOS.items():
        perfil = factory()
        arquivo = path / f"{pid}.yaml"
        perfil.salva(str(arquivo))
        print(f"  ✅ {arquivo}")

    print(f"\n✅ {len(PERFIS_PREDEFINIDOS)} perfis salvos em {pasta}/")


# =============================================================================
# INTEGRAÇÃO COM diagramar_livro_v2
# =============================================================================

def aplica_perfil_no_args(perfil: Optional[PerfilDiagramacao], args_dict: Dict) -> Dict:
    """
    Mescla configurações do perfil com argumentos CLI/GUI.

    IMPORTANTE: Se perfil is None, NÃO aplica nada — usa os defaults hardcoded
    do diagramar_livro_v2.py (corpo 16/22pt, capitulares, Vera Humana, etc.)

    Argumentos explícitos (GUI/CLI) têm prioridade sobre o perfil.
    """
    if perfil is None:
        # SEM PERFIL = usa defaults originais hardcoded
        return {k: v for k, v in args_dict.items() if v is not None}

    perfil_args = perfil.aplica_no_diagramar_livro()

    # Mescla: perfil como base, args_dict sobrescreve
    resultado = {**perfil_args, **args_dict}

    # Remove None values
    return {k: v for k, v in resultado.items() if v is not None}


# =============================================================================
# CLI PARA TESTE
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Perfis de Diagramação")
        print("Uso:")
        print("  python perfis_diagramacao.py lista          - Lista perfis")
        print("  python perfis_diagramacao.py mostra <id>    - Mostra perfil")
        print("  python perfis_diagramacao.py salva [pasta]  - Salva todos em pasta")
        print("  python perfis_diagramacao.py exporta <id> <arquivo> - Exporta perfil")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "lista":
        print("\n📋 Perfis disponíveis:")
        for pid, desc in lista_perfis().items():
            print(f"  {pid:20} - {desc}")

    elif cmd == "mostra":
        if len(sys.argv) < 3:
            print("❌ Informe o ID do perfil")
            sys.exit(1)
        perfil = get_perfil(sys.argv[2])
        print(perfil.to_yaml())

    elif cmd == "salva":
        pasta = sys.argv[2] if len(sys.argv) > 2 else "perfis"
        salva_perfil_padrao(pasta)

    elif cmd == "exporta":
        if len(sys.argv) < 4:
            print("❌ Uso: exporta <id> <arquivo.yaml>")
            sys.exit(1)
        perfil = get_perfil(sys.argv[2])
        perfil.salva(sys.argv[3])
        print(f"✅ Exportado para {sys.argv[3]}")