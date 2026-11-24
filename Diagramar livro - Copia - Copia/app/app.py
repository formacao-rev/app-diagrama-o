#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagramar Livro - Aplicação Moderna para Processamento de PDFs

Funcionalidades:
- Dividir páginas xerocadas (usar dividir_paginas.py)
- Rediagramar livros com OCR, sumário, capitulares, capa personalizada
- Arraste e solte arquivos PDF
- Gera executável standalone
"""

import sys
import re
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import subprocess
import threading
import queue
import os

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Initialize tkinterdnd2 for drag and drop
try:
    from tkinterdnd2 import DND_FILES
    import tkinterdnd2
    TkBase = tkinterdnd2.Tk
    HAS_DND = True
except ImportError:
    HAS_DND = False
    TkBase = tk.Tk

# Check OCR availability
try:
    import pytesseract
    from PIL import Image
    # Quick test that tesseract is actually working
    _ = pytesseract.get_tesseract_version()
    OCR_DISPONIVEL = True
except Exception:
    OCR_DISPONIVEL = False


# ============================================================================
# TEMA (escuro, com acento vermelho)
# ============================================================================
class Tema:
    bg = "#09090b"            # fundo da janela
    hero_topo = "#1d0a0f"     # brilho avermelhado no topo
    card = "#111114"          # cartões
    card2 = "#17171b"         # cartões secundários / segmentos
    campo = "#0c0c0f"         # campos, zona de soltar, log
    borda = "#26262c"
    borda_forte = "#52525b"
    # Texto
    texto = "#fafafa"
    texto2 = "#a1a1aa"
    texto3 = "#71717a"
    # Acentos
    acento = "#c1121f"        # botões
    acento_hover = "#e11d2e"
    acento_suave = "#1c1013"  # fundo do cartão selecionado
    primaria = "#fb7185"      # texto de destaque
    branco = "#f4f4f5"
    # Estados
    ok = "#4ade80"
    erro = "#f87171"
    aviso = "#fbbf24"

    familia = "Segoe UI"
    mono = "Consolas"


T = Tema


def fonte(tam=10, peso="normal"):
    return (T.familia, tam, peso)


def _mistura(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _pontos(x0, y0, x1, y1, r):
    """Pontos de um retângulo arredondado (use com smooth=True)."""
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
            x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


def _percorre(widget):
    yield widget
    for f in widget.winfo_children():
        yield from _percorre(f)


def _liga_clique(widget, comando, ignorar=()):
    for w in _percorre(widget):
        if isinstance(w, (Pilula, Toggle)) or w in ignorar:
            continue
        w.bind("<Button-1>", lambda e: comando(), add="+")
        try:
            w.configure(cursor="hand2")
        except tk.TclError:
            pass


def rot(parent, texto, tam=10, peso="normal", cor=None, **kw):
    """Label com o fundo do pai."""
    return tk.Label(parent, text=texto, bg=parent["bg"], fg=cor or T.texto,
                    font=fonte(tam, peso), **kw)


# ============================================================================
# WIDGETS PERSONALIZADOS
# ============================================================================
class Arredondado(tk.Canvas):
    """Cartão com cantos arredondados; o conteúdo vai em `.inner`."""

    def __init__(self, parent, fill=T.card, outline=T.borda, raio=16, pad=(18, 14),
                 dash=None, largura=1, preencher=False, autolargura=False):
        self._f, self._o = fill, outline
        self.autolargura = autolargura
        self.raio, self.padx, self.pady = raio, pad[0], pad[1]
        self.dash, self.larg, self.preencher = dash, largura, preencher
        # altura inicial > pad: o Tk só mapeia (e só avisa o tamanho de) janelas visíveis
        super().__init__(parent, width=10, height=2 * self.pady + 6, bg=parent["bg"],
                         highlightthickness=0, bd=0)
        self.inner = tk.Frame(self, bg=fill)
        self._win = self.create_window(self.padx, self.pady, window=self.inner, anchor="nw")
        self.bind("<Configure>", self._redesenha)
        self.inner.bind("<Configure>", self._ajusta)

    def _ajusta(self, _e=None):
        h = self.inner.winfo_reqheight() + 2 * self.pady
        if int(float(self.cget("height"))) != h:
            self.configure(height=h)
        if self.autolargura:
            w = self.inner.winfo_reqwidth() + 2 * self.padx
            if int(float(self.cget("width"))) != w:
                self.configure(width=w)

    def _redesenha(self, _e=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 6 or h < 6:
            return
        self.delete("fundo")
        r = min(self.raio, h // 2 - 1, w // 2 - 1)
        self.create_polygon(_pontos(1, 1, w - 1, h - 1, r), smooth=True, fill=self._f,
                            outline=self._o, width=self.larg, dash=self.dash, tags="fundo")
        self.tag_lower("fundo")
        opc = {"width": max(1, w - 2 * self.padx)}
        if self.preencher:
            opc["height"] = max(1, h - 2 * self.pady)
        self.itemconfigure(self._win, **opc)

    def estilizar(self, fill=None, outline=None, largura=None):
        antigo = self._f
        if fill is not None and fill != antigo:
            for w in _percorre(self.inner):
                try:
                    if w.cget("bg") == antigo:
                        w.configure(bg=fill)
                except tk.TclError:
                    pass
            self._f = fill
            self.inner.configure(bg=fill)
        if outline is not None:
            self._o = outline
        if largura is not None:
            self.larg = largura
        self._redesenha()


class Pilula(tk.Canvas):
    """Botão em pílula com hover."""

    ESTILOS = {
        "branco": (T.branco, "#ffffff", "#0a0a0a"),
        "acento": (T.acento, T.acento_hover, "#ffffff"),
        "suave": ("#1f1f24", "#2b2b32", "#e4e4e7"),
        "seg_off": (T.card2, "#222228", T.texto2),
        "seg_on": (T.branco, T.branco, "#0a0a0a"),
    }
    DESATIVADO = ("#1a1a1e", "#1a1a1e", "#52525b")

    def __init__(self, parent, texto, comando=None, estilo="suave", grande=False):
        self._cmd, self._estilo, self._ativo, self._hover = comando, estilo, True, False
        peso = "bold" if (grande or estilo in ("branco", "acento", "seg_on", "seg_off")) else "normal"
        self._fonte = tkfont.Font(font=fonte(11 if grande else 10, peso))
        px, py = (28, 12) if grande else (16, 7)
        w = self._fonte.measure(texto) + 2 * px
        h = self._fonte.metrics("linespace") + 2 * py
        super().__init__(parent, width=w, height=h, bg=parent["bg"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self._forma = self.create_polygon(_pontos(1, 1, w - 1, h - 1, h // 2), smooth=True)
        self._txt = self.create_text(w / 2, h / 2, text=texto, font=self._fonte)
        self._pinta()
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", self._clique)

    def _pinta(self):
        bg, bgh, fg = self.ESTILOS[self._estilo] if self._ativo else self.DESATIVADO
        self.itemconfigure(self._forma, fill=bgh if (self._hover and self._ativo) else bg,
                           outline=bgh if (self._hover and self._ativo) else bg)
        self.itemconfigure(self._txt, fill=fg)
        self.configure(cursor="hand2" if self._ativo else "arrow")

    def _set_hover(self, v):
        self._hover = v
        self._pinta()

    def _clique(self, _e):
        if self._ativo and self._cmd:
            self._cmd()

    def definir_estilo(self, estilo):
        self._estilo = estilo
        self._pinta()

    def ativar(self, ativo=True):
        self._ativo = ativo
        self._pinta()


class Toggle(tk.Canvas):
    """Interruptor ligado a uma BooleanVar."""

    def __init__(self, parent, var):
        super().__init__(parent, width=42, height=24, bg=parent["bg"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self.var = var
        var.trace_add("write", lambda *a: self._desenha())
        self.bind("<Button-1>", lambda e: var.set(not var.get()))
        self._desenha()

    def _desenha(self):
        self.delete("all")
        on = self.var.get()
        self.create_polygon(_pontos(1, 1, 41, 23, 11), smooth=True,
                            fill=T.acento if on else "#3f3f46", outline="")
        x = 21 if on else 3
        self.create_oval(x, 3, x + 18, 21, fill="white", outline="")


class Segmentado(Arredondado):
    """Grupo de pílulas onde só uma fica selecionada (abas / opções)."""

    def __init__(self, parent, var, opcoes, comando=None):
        super().__init__(parent, fill=T.card2, outline=T.borda, raio=22, pad=(4, 4),
                         autolargura=True)
        self.var, self.cmd, self.botoes = var, comando, {}
        for valor, texto in opcoes:
            b = Pilula(self.inner, texto, lambda v=valor: self.escolher(v), "seg_off")
            b.pack(side="left", padx=1)
            self.botoes[valor] = b
        self.atualiza()

    def escolher(self, valor):
        self.var.set(valor)
        self.atualiza()
        if self.cmd:
            self.cmd(valor)

    def atualiza(self):
        for v, b in self.botoes.items():
            b.definir_estilo("seg_on" if v == self.var.get() else "seg_off")

    def ativar(self, valor, ativo):
        self.botoes[valor].ativar(ativo)


class Hero(tk.Canvas):
    """Faixa do topo: brilho em degradê, selo, título e subtítulo centralizados."""

    def __init__(self, parent):
        super().__init__(parent, height=166, bg=T.bg, highlightthickness=0, bd=0)
        self.chips = []
        self.bind("<Configure>", self._desenha)

    def _desenha(self, _e=None):
        w, h = self.winfo_width(), int(self.cget("height"))
        if w < 50:
            return
        self.delete("all")
        for y in range(0, h, 2):
            self.create_rectangle(0, y, w, y + 2, outline="",
                                  fill=_mistura(T.hero_topo, T.bg, min(1, y / (h * 0.95))))
        # selo
        f = tkfont.Font(font=fonte(9, "bold"))
        txt = "D I A G R A M A R   L I V R O"
        tw = f.measure(txt)
        cx = w / 2
        self.create_polygon(_pontos(cx - tw / 2 - 18, 20, cx + tw / 2 + 18, 44, 12), smooth=True,
                            fill="#15151a", outline="#2e2e36")
        self.create_text(cx, 32, text=txt, fill=T.texto2, font=fonte(9, "bold"))
        # título
        self.create_text(cx, 82, text="Transforme PDFs em livros diagramados",
                         fill=T.texto, font=fonte(29, "bold"))
        self.create_text(cx, 112, anchor="n", justify="center", width=min(w - 120, 640),
                         fill=T.texto2, font=fonte(11),
                         text="Divida folhas xerocadas, faça OCR e gere um livro com sumário, "
                              "capitulares e capa, direto no seu computador.")
        # chips de status (canto superior direito)
        x = w - 26
        for texto, ok in reversed(self.chips):
            t = self.create_text(x, 18, text=texto, anchor="e", fill=T.texto3, font=fonte(9))
            x0 = self.bbox(t)[0]
            self.create_oval(x0 - 14, 14, x0 - 8, 20, fill=T.ok if ok else T.aviso, outline="")
            x = x0 - 30

    def define_chips(self, chips):
        self.chips = chips
        self._desenha()


# ---- ilustrações dos cartões de ferramenta --------------------------------
def _desenha_dividir(c, w, h):
    c.create_polygon(_pontos(0, 0, w, h, 12), smooth=True, fill=T.campo, outline="")
    cx, pw, ph = w / 2, 54, 62
    y0 = (h - ph) / 2
    for x0 in (cx - pw - 5, cx + 5):
        c.create_rectangle(x0, y0, x0 + pw, y0 + ph, fill="#e4e4e7", outline="")
        for k in range(5):
            c.create_rectangle(x0 + 8, y0 + 10 + k * 10, x0 + pw - (8 + (k % 2) * 10),
                               y0 + 13 + k * 10, fill="#a1a1aa", outline="")
    c.create_line(cx, y0 - 9, cx, y0 + ph + 9, fill=T.acento_hover, width=2, dash=(4, 3))


def _desenha_diagramar(c, w, h):
    c.create_polygon(_pontos(0, 0, w, h, 12), smooth=True, fill=T.campo, outline="")
    cx, pw, ph = w / 2, 58, 68
    y0 = (h - ph) / 2
    x0 = cx - pw / 2 + 8
    c.create_rectangle(x0 - 16, y0 + 5, x0 - 16 + pw, y0 + 5 + ph, fill="#52525b", outline="")
    c.create_rectangle(x0, y0, x0 + pw, y0 + ph, fill="#e4e4e7", outline="")
    c.create_polygon(x0 + pw - 14, y0, x0 + pw, y0, x0 + pw, y0 + 14, fill=T.acento, outline="")
    c.create_rectangle(x0 + 8, y0 + 9, x0 + 32, y0 + 14, fill="#3f3f46", outline="")
    c.create_rectangle(x0 + 8, y0 + 22, x0 + 22, y0 + 36, fill=T.acento, outline="")
    for k in range(2):
        c.create_rectangle(x0 + 26, y0 + 23 + k * 7, x0 + pw - 8, y0 + 26 + k * 7,
                           fill="#a1a1aa", outline="")
    for k in range(3):
        c.create_rectangle(x0 + 8, y0 + 42 + k * 7, x0 + pw - 8 - (k % 2) * 10,
                           y0 + 45 + k * 7, fill="#a1a1aa", outline="")


def _desenha_completo(c, w, h):
    """Ilustração do modo completo: setas encadeadas representando o pipeline."""
    c.create_polygon(_pontos(0, 0, w, h, 12), smooth=True, fill=T.campo, outline="")
    cx, cy = w / 2, h / 2

    # Quatro caixas representando as etapas
    box_w, box_h = 52, 38
    gap = 12
    total_w = 4 * box_w + 3 * gap
    x_start = cx - total_w / 2
    y0 = cy - box_h / 2

    etapas = [
        ("1. Dividir", "#52525b"),
        ("2. OCR", "#3f3f46"),
        ("3. Corrigir", "#3f3f46"),
        ("4. Diagramar", T.acento),
    ]

    for i, (label, color) in enumerate(etapas):
        x = x_start + i * (box_w + gap)
        # Caixa
        c.create_rectangle(x, y0, x + box_w, y0 + box_h, fill=color, outline="")
        # Texto
        c.create_text(x + box_w / 2, y0 + box_h / 2 - 4, text=label, fill="white", font=fonte(8, "bold"))
        # Seta entre caixas
        if i < 3:
            arrow_x = x + box_w
            c.create_line(arrow_x, cy, arrow_x + gap, cy, fill=T.texto3, width=2, arrow="last")
            # Seta triângulo
            c.create_polygon(arrow_x + gap - 4, cy - 4, arrow_x + gap, cy, arrow_x + gap - 4, cy + 4,
                           fill=T.texto3, outline="")


class ModernStyle(ttk.Style):
    """Estilo ttk para campos, spinbox, barra de progresso e scrollbar (tema escuro)."""

    def __init__(self):
        super().__init__()
        try:
            self.theme_use("clam")
        except Exception:
            pass
        # Mantidos por compatibilidade com o restante do código
        self.bg_color = T.bg
        self.primary = T.primaria
        self.text_primary = T.texto
        self.text_secondary = T.texto2
        self.success_color = T.ok
        self.border_color = T.borda
        self.font_family = T.familia
        self.font_mono = T.mono

        self.configure(".", background=T.card, foreground=T.texto, font=fonte(10))
        self.configure("TFrame", background=T.card)
        self.configure("TEntry", fieldbackground=T.campo, foreground=T.texto,
                       insertcolor=T.texto, bordercolor=T.borda, lightcolor=T.borda,
                       darkcolor=T.borda, padding=8)
        self.map("TEntry",
                 bordercolor=[("focus", T.acento_hover)],
                 lightcolor=[("focus", T.acento_hover)],
                 darkcolor=[("focus", T.acento_hover)],
                 fieldbackground=[("readonly", T.campo)],
                 foreground=[("readonly", T.texto2)])
        self.configure("TSpinbox", fieldbackground=T.campo, foreground=T.texto,
                       insertcolor=T.texto, bordercolor=T.borda, lightcolor=T.borda,
                       darkcolor=T.borda, background="#1f1f24", arrowcolor=T.texto2,
                       padding=6, arrowsize=13)
        self.map("TSpinbox", bordercolor=[("focus", T.acento_hover)],
                 arrowcolor=[("active", T.texto)])
        self.configure("TProgressbar", background=T.acento_hover, troughcolor=T.campo,
                       borderwidth=0, thickness=4, lightcolor=T.acento_hover,
                       darkcolor=T.acento_hover)
        self.configure("Vertical.TScrollbar", background="#2b2b32", troughcolor=T.campo,
                       bordercolor=T.campo, arrowcolor=T.campo, lightcolor="#2b2b32",
                       darkcolor="#2b2b32", relief="flat", arrowsize=0, gripcount=0)
        self.map("Vertical.TScrollbar", background=[("active", "#3f3f46")])


# ============================================================================
# JANELA PRINCIPAL
# ============================================================================
class PDFApp(TkBase):
    """Janela principal."""

    def __init__(self):
        super().__init__()
        self.style = ModernStyle()
        self._setup_window()
        self._setup_state()
        self._build_ui()
        self._setup_bindings()
        self._schedule_log_check()

    # ------------------------------------------------------------ janela/estado
    def _setup_window(self):
        self.title("Diagramar Livro")
        self.minsize(1000, 800)
        self.configure(bg=T.bg)
        w, h = 1120, 900
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(w, sw - 40), min(h, sh - 80)
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 20)}")
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

    def _setup_state(self):
        self.input_pdf: Path | None = None
        self.cover_path: Path | None = None
        self.output_base_folder = Path.cwd() / "output"
        self.output_base_folder.mkdir(exist_ok=True)
        self.log_queue = queue.Queue()
        self.processing_thread: threading.Thread | None = None
        self.last_output: Path | None = None
        self._cover_thumb = None
        self._tiles = {}
        self._paineis = {}

    def _setup_bindings(self):
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self._on_drop)
        self.bind("<Control-o>", lambda e: self._select_pdf())

    # ------------------------------------------------------------ construção
    def _build_ui(self):
        self.hero = Hero(self)
        self.hero.grid(row=0, column=0, sticky="ew")
        self.hero.define_chips([
            ("OCR pronto" if OCR_DISPONIVEL else "OCR indisponível", OCR_DISPONIVEL),
            ("Arrastar e soltar" if HAS_DND else "Sem arrastar e soltar", HAS_DND),
        ])

        corpo = tk.Frame(self, bg=T.bg)
        corpo.grid(row=1, column=0, sticky="nsew", padx=32, pady=(0, 22))
        corpo.grid_columnconfigure(0, weight=11, uniform="col")
        corpo.grid_columnconfigure(1, weight=9, uniform="col")
        corpo.grid_rowconfigure(2, weight=1)

        esq = tk.Frame(corpo, bg=T.bg)
        esq.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        esq.grid_columnconfigure(0, weight=1)
        self._build_input_card(esq)
        self._build_tool_card(esq)

        dir_ = Arredondado(corpo, fill=T.card, outline=T.borda, raio=18, pad=(20, 18))
        dir_.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        self._build_settings(dir_.inner)

        self._build_action_bar(corpo)
        self._build_log_section(corpo)
        self._on_tool_change()

    # ---- ARQUIVO ----
    def _titulo(self, parent, n, texto):
        linha = tk.Frame(parent, bg=parent["bg"])
        linha.pack(fill="x", pady=(0, 12))
        tk.Label(linha, text=str(n), bg=T.acento, fg="white", width=2, font=fonte(9, "bold")
                 ).pack(side="left", padx=(0, 10))
        rot(linha, texto, 11, "bold").pack(side="left")
        return linha

    def _build_input_card(self, parent):
        card = Arredondado(parent, fill=T.card, outline=T.borda, raio=18, pad=(20, 18))
        card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._titulo(card.inner, 1, "Arquivo PDF")

        # Zona tracejada de soltar
        self.drop_zone = Arredondado(card.inner, fill=T.campo, outline=T.borda_forte,
                                     dash=(6, 5), raio=16, pad=(20, 16))
        self.drop_zone.pack(fill="x")
        z = self.drop_zone.inner
        Pilula(z, "⬆  Escolher PDF", self._select_pdf, "branco", grande=True).pack(pady=(0, 10))
        rot(z, "Arraste e solte o PDF aqui" if HAS_DND else "Clique para escolher o PDF",
            10, "bold").pack()
        rot(z, "Escaneado ou digital  ·  Ctrl+O", 9, cor=T.texto3).pack(pady=(3, 0))
        self.drop_zone.bind("<Enter>", lambda e: self._drop_enter())
        self.drop_zone.bind("<Leave>", lambda e: self._drop_leave())
        if HAS_DND:
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind('<<Drop>>', self._on_drop)
            self.drop_zone.dnd_bind('<<DropEnter>>', lambda e: self._drop_enter())
            self.drop_zone.dnd_bind('<<DropLeave>>', lambda e: self._drop_leave())

        # Arquivo escolhido (aparece no lugar da zona)
        self.file_box = Arredondado(card.inner, fill=T.campo, outline=T.borda, raio=16,
                                    pad=(16, 14))
        f = self.file_box.inner
        f.grid_columnconfigure(1, weight=1)
        tk.Label(f, text="📄", bg=T.campo, fg=T.texto, font=(T.familia, 26)
                 ).grid(row=0, column=0, rowspan=2, padx=(0, 14))
        self.input_file_label = tk.Label(f, text="", bg=T.campo, fg=T.texto,
                                         font=fonte(11, "bold"), anchor="w")
        self.input_file_label.grid(row=0, column=1, sticky="sw")
        self.input_meta_label = tk.Label(f, text="", bg=T.campo, fg=T.texto2,
                                         font=fonte(9), anchor="w")
        self.input_meta_label.grid(row=1, column=1, sticky="nw")
        bt = tk.Frame(f, bg=T.campo)
        bt.grid(row=0, column=2, rowspan=2, padx=(10, 0))
        Pilula(bt, "Trocar", self._select_pdf, "suave").pack(side="left", padx=(0, 6))
        Pilula(bt, "Remover", self._clear_input, "suave").pack(side="left")

    def _drop_enter(self):
        self.drop_zone.estilizar(fill="#150c0f", outline=T.acento_hover)

    def _drop_leave(self):
        self.drop_zone.estilizar(fill=T.campo, outline=T.borda_forte)

    def _on_drop(self, event):
        self._drop_leave()
        try:
            paths = self.tk.splitlist(event.data)
            if paths and paths[0].lower().endswith('.pdf'):
                self._handle_dropped_file(paths[0])
            else:
                messagebox.showwarning("Formato inválido", "Por favor, arraste apenas arquivos PDF.")
        except Exception:
            pass

    def _handle_dropped_file(self, filepath):
        path = Path(filepath)
        if not path.exists():
            return
        self.input_pdf = path
        self.input_file_label.config(text=path.name)
        self.input_meta_label.config(text=self._descreve_pdf(path))
        self.drop_zone.pack_forget()
        self.file_box.pack(fill="x")
        self._log(f"✅ Arquivo selecionado: {path.name}", "success")
        self._atualiza_botao()

    def _descreve_pdf(self, path: Path) -> str:
        """Resumo curto: páginas · tamanho · escaneado ou com texto."""
        try:
            import pymupdf as fitz
            tam = path.stat().st_size / (1024 * 1024)
            with fitz.open(path) as doc:
                n = len(doc)
                tem_texto = any(len(doc[i].get_text().strip()) > 50 for i in range(min(n, 8)))
                larg, alt = doc[0].rect.width, doc[0].rect.height
            tipo = "com texto (OCR)" if tem_texto else "escaneado, sem texto"
            dupla = "  ·  parece folha dupla" if larg > alt * 1.08 else ""
            return f"{n} páginas  ·  {tam:.1f} MB  ·  {tipo}{dupla}"
        except Exception:
            return "Não foi possível ler os detalhes do PDF"

    def _select_pdf(self):
        filename = filedialog.askopenfilename(
            title="Selecione o PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if filename:
            self._handle_dropped_file(filename)

    def _clear_input(self):
        self.input_pdf = None
        self.file_box.pack_forget()
        self.drop_zone.pack(fill="x")
        self._atualiza_botao()

    # ---- FERRAMENTA ----
    def _build_tool_card(self, parent):
        card = Arredondado(parent, fill=T.card, outline=T.borda, raio=18, pad=(20, 18))
        card.grid(row=1, column=0, sticky="ew")
        self._titulo(card.inner, 2, "O que você quer fazer?")
        self.tool_var = tk.StringVar(value="diagram")
        linha = tk.Frame(card.inner, bg=T.card)
        linha.pack(fill="x")
        linha.grid_columnconfigure(0, weight=1, uniform="t")
        linha.grid_columnconfigure(1, weight=1, uniform="t")
        linha.grid_columnconfigure(2, weight=1, uniform="t")
        self._tile(linha, 0, "dividir", _desenha_dividir, "Dividir páginas",
                   "Separa folhas xerocadas (2 páginas por folha) em páginas individuais.")
        self._tile(linha, 1, "diagram", _desenha_diagramar, "Diagramar livro",
                   "OCR, sumário, capitulares e capa. Gera PDF, DOCX e TXT.")
        self._tile(linha, 2, "completo", _desenha_completo, "Processamento Completo",
                   "Divide páginas → OCR → Correção → Diagramção. Tudo automático.")

    def _tile(self, parent, col, valor, desenho, titulo, desc):
        t = Arredondado(parent, fill=T.card2, outline=T.borda, raio=16, pad=(14, 14))
        t.grid(row=0, column=col, sticky="nsew", padx=(0, 7) if col == 0 else (7, 0))
        ilus = tk.Canvas(t.inner, height=78, bg=T.card2, highlightthickness=0, bd=0)
        ilus.pack(fill="x")
        ilus.bind("<Configure>", lambda e, c=ilus, d=desenho: (c.delete("all"), d(c, e.width, e.height)))
        rot(t.inner, titulo, 11, "bold", anchor="w").pack(fill="x", pady=(12, 2))
        rot(t.inner, desc, 9, cor=T.texto2, anchor="w", justify="left", wraplength=190
            ).pack(fill="x")
        _liga_clique(t, lambda v=valor: self._set_tool(v))
        self._tiles[valor] = t

    def _set_tool(self, valor):
        self.tool_var.set(valor)
        self._on_tool_change()

    def _on_tool_change(self):
        atual = self.tool_var.get()
        for valor, t in self._tiles.items():
            if valor == atual:
                t.estilizar(fill=T.acento_suave, outline=T.acento_hover, largura=2)
            else:
                t.estilizar(fill=T.card2, outline=T.borda, largura=1)
        diag = atual == "diagram"
        self.abas.ativar("capa", diag)
        self.abas.ativar("meta", diag)
        if not diag and self.aba_var.get() != "opcoes":
            self.abas.escolher("opcoes")
        self._atualiza_opcoes()
        self._atualiza_botao()

    # ---- AJUSTES (abas em pílula) ----
    def _build_settings(self, parent):
        topo = tk.Frame(parent, bg=T.card)
        topo.pack(fill="x", pady=(0, 16))
        rot(topo, "Ajustes", 11, "bold").pack(side="left")
        self.aba_var = tk.StringVar(value="opcoes")
        self.abas = Segmentado(topo, self.aba_var,
                               [("opcoes", "Opções"), ("sumario", "Sumário"), ("perfil", "Perfil"), ("capa", "Capa"), ("meta", "Metadados")],
                               comando=self._mostra_painel)
        self.abas.pack(side="right")

        self.area = tk.Frame(parent, bg=T.card)
        self.area.pack(fill="both", expand=True)
        self._paineis = {k: tk.Frame(self.area, bg=T.card) for k in ("opcoes", "sumario", "perfil", "capa", "meta")}
        self._build_options_tab(self._paineis["opcoes"])
        self._build_sumario_tab(self._paineis["sumario"])
        self._build_perfil_tab(self._paineis["perfil"])
        self._build_cover_section(self._paineis["capa"])
        self._build_metadata_section(self._paineis["meta"])
        self._mostra_painel("opcoes")

    def _mostra_painel(self, nome):
        for k, p in self._paineis.items():
            if k == nome:
                p.pack(fill="both", expand=True)
            else:
                p.pack_forget()

    def _linha_toggle(self, parent, var, titulo, desc):
        l = tk.Frame(parent, bg=T.card)
        l.pack(fill="x", pady=(0, 4))
        Toggle(l, var).pack(side="left", anchor="n", padx=(0, 12), pady=2)
        col = tk.Frame(l, bg=T.card)
        col.pack(side="left", fill="x", expand=True)
        rot(col, titulo, 10, "bold", anchor="w").pack(fill="x")
        rot(col, desc, 9, cor=T.texto2, anchor="w", justify="left", wraplength=300).pack(fill="x")

    def _build_options_tab(self, parent):
        # Modo "diagramar"
        self.diagram_options = tk.Frame(parent, bg=T.card)
        rot(self.diagram_options, "Qualidade do OCR", 10, "bold", anchor="w").pack(fill="x")
        rot(self.diagram_options,
            "Só vale para PDFs escaneados. Mais DPI = mais precisão, porém mais lento.",
            9, cor=T.texto2, anchor="w", justify="left", wraplength=340).pack(fill="x", pady=(2, 10))
        linha = tk.Frame(self.diagram_options, bg=T.card)
        linha.pack(fill="x")
        self.dpi_var = tk.StringVar(value="300")
        ttk.Spinbox(linha, from_=150, to=600, increment=50, textvariable=self.dpi_var,
                    width=7, justify="center").pack(side="left")
        rot(linha, "  DPI  (padrão 300)", 9, cor=T.texto3).pack(side="left")
        tk.Frame(self.diagram_options, bg=T.borda, height=1).pack(fill="x", pady=18)
        self.correcao_var = tk.BooleanVar(value=True)
        self._linha_toggle(self.diagram_options, self.correcao_var,
                           "Correção ortográfica automática",
                           "Gera livro_corrigido.txt e um relatório com o que foi alterado.")

        # Modo "dividir"
        self.dividir_info = tk.Frame(parent, bg=T.card)
        rot(self.dividir_info, "Dividir páginas", 10, "bold", anchor="w").pack(fill="x")
        rot(self.dividir_info,
            "Detecta a dobra central de cada folha dupla e cria um PDF com as páginas em "
            "ordem sequencial, sem cortar palavras.\n\nNão há ajustes para esta ferramenta: "
            "escolha o PDF e inicie.",
            10, cor=T.texto2, anchor="w", justify="left", wraplength=340).pack(fill="x", pady=(6, 0))

    def _atualiza_opcoes(self):
        if self.tool_var.get() == "diagram":
            self.dividir_info.pack_forget()
            self.diagram_options.pack(fill="both", expand=True)
        else:
            self.diagram_options.pack_forget()
            self.dividir_info.pack(fill="both", expand=True)

    # ---- CAPA ----
    def _build_cover_section(self, parent):
        topo = tk.Frame(parent, bg=T.card)
        topo.pack(fill="x")
        self.cover_preview_label = tk.Label(
            topo, text="sem capa", bg=T.campo, fg=T.texto3, font=fonte(9),
            width=14, height=8, highlightbackground=T.borda, highlightthickness=1)
        self.cover_preview_label.pack(side="left", anchor="n")
        dir_ = tk.Frame(topo, bg=T.card)
        dir_.pack(side="left", fill="x", expand=True, padx=(16, 0), anchor="n")
        self.cover_status = rot(dir_, "Sem capa: será usada a folha de rosto tipográfica.", 9,
                                cor=T.texto2, anchor="w", justify="left", wraplength=210)
        self.cover_status.pack(fill="x", pady=(0, 10))
        Pilula(dir_, "Escolher imagem", self._select_cover, "branco").pack(anchor="w")
        Pilula(dir_, "Remover", self._clear_cover, "suave").pack(anchor="w", pady=(8, 0))

        rot(parent, "Ajuste da imagem", 10, "bold", anchor="w").pack(fill="x", pady=(18, 8))
        self.cover_fit_var = tk.StringVar(value="preencher")
        Segmentado(parent, self.cover_fit_var,
                   [("preencher", "Preencher a página"), ("conter", "Imagem inteira")]
                   ).pack(anchor="w")
        rot(parent, "Preencher pode cortar bordas; “Imagem inteira” deixa margens.", 9,
            cor=T.texto3, anchor="w").pack(fill="x", pady=(6, 14))
        self.cover_rosto_var = tk.BooleanVar(value=False)
        self._linha_toggle(parent, self.cover_rosto_var, "Manter a folha de rosto",
                           "Inclui a folha de rosto tipográfica depois da capa.")

    def _select_cover(self):
        filename = filedialog.askopenfilename(
            title="Selecione a imagem da capa",
            filetypes=[
                ("Imagens", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"),
                ("Todos os arquivos", "*.*"),
            ]
        )
        if filename:
            self._set_cover(Path(filename))

    def _set_cover(self, path: Path):
        path = Path(path)
        if not path.exists():
            messagebox.showwarning("Capa", f"Arquivo não encontrado:\n{path}")
            return
        self.cover_path = path
        self.cover_status.config(text=f"Capa: {path.name}", fg=T.primaria)
        self._log(f"🖼️ Capa selecionada: {path.name}")
        self._show_cover_preview(path)

    def _clear_cover(self):
        self.cover_path = None
        self.cover_status.config(text="Sem capa: será usada a folha de rosto tipográfica.",
                                 fg=T.texto2)
        self.cover_preview_label.config(image="", text="sem capa", width=14, height=8)
        self._cover_thumb = None

    def _show_cover_preview(self, path: Path):
        try:
            from PIL import Image, ImageTk
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((110, 140), Image.LANCZOS)
                self._cover_thumb = ImageTk.PhotoImage(im)
            self.cover_preview_label.config(image=self._cover_thumb, text="", width=0, height=0)
        except Exception as e:
            self.cover_preview_label.config(image="", text=f"Erro: {e}")
            self._cover_thumb = None

    # ---- METADADOS ----
    def _build_metadata_section(self, parent):
        self.titulo_var = tk.StringVar()
        self.autor_var = tk.StringVar()
        self.editora_var = tk.StringVar()
        self.ano_var = tk.StringVar()
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        rot(parent, "Deixe em branco para usar o que estiver no PDF.", 9, cor=T.texto2,
            anchor="w").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        # (rótulo, variável, linha, coluna, colunas ocupadas)
        campos = [("Título", self.titulo_var, 1, 0, 2), ("Autor", self.autor_var, 3, 0, 2),
                  ("Editora", self.editora_var, 5, 0, 1), ("Ano", self.ano_var, 5, 1, 1)]
        for rotulo, var, row, col, span in campos:
            dir_pad = (0, 8) if (col == 0 and span == 1) else ((8, 0) if col == 1 else (0, 0))
            rot(parent, rotulo, 9, "bold", anchor="w").grid(
                row=row, column=col, columnspan=span, sticky="w", pady=(10, 4))
            ttk.Entry(parent, textvariable=var).grid(
                row=row + 1, column=col, columnspan=span, sticky="ew", padx=dir_pad)

    # ---- BARRA DE AÇÃO ----
    def _build_action_bar(self, parent):
        barra = Arredondado(parent, fill=T.card, outline=T.borda, raio=18, pad=(18, 12))
        barra.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        b = barra.inner
        b.grid_columnconfigure(1, weight=1)
        rot(b, "Salvar em", 9, cor=T.texto3).grid(row=0, column=0, padx=(0, 10))
        self.output_path_var = tk.StringVar(value=str(self.output_base_folder))
        ttk.Entry(b, textvariable=self.output_path_var, state="readonly"
                  ).grid(row=0, column=1, sticky="ew")
        Pilula(b, "Alterar", self._select_output, "suave").grid(row=0, column=2, padx=(10, 6))
        Pilula(b, "Abrir pasta", self._open_output, "suave").grid(row=0, column=3, padx=(0, 14))
        self.exec_btn = Pilula(b, "▶  Iniciar", self._execute, "acento", grande=True)
        self.exec_btn.grid(row=0, column=4)

        self.status_label = tk.Label(b, text="", bg=T.card, fg=T.texto2, font=fonte(9), anchor="w")
        self.status_label.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(10, 0))
        self.progress = ttk.Progressbar(b, mode="indeterminate")
        self.progress.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        self.progress.grid_remove()
        self._atualiza_botao()

    def _atualiza_botao(self):
        if not hasattr(self, "exec_btn"):
            return
        rodando = bool(self.processing_thread and self.processing_thread.is_alive())
        self.exec_btn.ativar(bool(self.input_pdf) and not rodando)
        if rodando:
            return
        if not self.input_pdf:
            self.status_label.config(text="Selecione um PDF para começar.", fg=T.texto2)
        else:
            nome = "Dividir páginas" if self.tool_var.get() == "dividir" else "Diagramar livro"
            self.status_label.config(text=f"Pronto: {nome} — {self.input_pdf.name}", fg=T.texto2)

    def _select_output(self):
        folder = filedialog.askdirectory(
            title="Selecione a pasta base de saída",
            initialdir=str(self.output_base_folder)
        )
        if folder:
            self.output_base_folder = Path(folder)
            self.output_path_var.set(str(self.output_base_folder))

    def _open_output(self):
        alvo = self.last_output if self.last_output and self.last_output.exists() \
            else self.output_base_folder
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(alvo))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(alvo)])
            else:
                subprocess.Popen(["xdg-open", str(alvo)])
        except Exception as e:
            messagebox.showwarning("Abrir pasta", f"Não foi possível abrir:\n{alvo}\n\n{e}")

    # ---- LOG ----
    def _build_log_section(self, parent):
        caixa = Arredondado(parent, fill=T.campo, outline=T.borda, raio=18, pad=(18, 12),
                            preencher=True)
        caixa.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(14, 0))
        c = caixa.inner
        topo = tk.Frame(c, bg=T.campo)
        topo.pack(fill="x")
        rot(topo, "Progresso", 9, "bold", cor=T.texto2).pack(side="left")
        for texto, cmd in (("Copiar", self._copy_log), ("Limpar", self._clear_log)):
            l = tk.Label(topo, text=texto, bg=T.campo, fg=T.texto3, font=fonte(9), cursor="hand2")
            l.pack(side="right", padx=(12, 0))
            l.bind("<Button-1>", lambda e, f=cmd: f())
            l.bind("<Enter>", lambda e, w=l: w.configure(fg=T.texto))
            l.bind("<Leave>", lambda e, w=l: w.configure(fg=T.texto3))

        miolo = tk.Frame(c, bg=T.campo)
        miolo.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text = tk.Text(
            miolo, height=4, wrap="word", state="disabled", font=(T.mono, 9), bg=T.campo,
            fg="#d4d4d8", insertbackground="#d4d4d8", relief="flat", padx=0, pady=2,
            borderwidth=0, highlightthickness=0)
        v_scroll = ttk.Scrollbar(miolo, orient="vertical", command=self.log_text.yview)
        v_scroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.configure(yscrollcommand=v_scroll.set)

        self.log_text.tag_configure("info", foreground="#93c5fd")
        self.log_text.tag_configure("success", foreground="#86efac")
        self.log_text.tag_configure("error", foreground="#fca5a5")
        self.log_text.tag_configure("warning", foreground="#fcd34d")
        self.log_text.tag_configure("debug", foreground="#c084fc")

    def _copy_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.log_text.get("1.0", tk.END))
        self.status_label.config(text="Log copiado para a área de transferência.", fg=T.texto2)

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _log(self, message: str, level: str = "info"):
        """Add message to log with level-based color."""
        try:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, message + "\n", level)
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)
        except tk.TclError:
            pass

    def _schedule_log_check(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if isinstance(msg, tuple):
                    self._log(*msg)
                else:
                    self._log(msg)
        except queue.Empty:
            pass
        self.after(50, self._schedule_log_check)

    # ------------------------------------------------------------ EXECUÇÃO
    def _execute(self):
        if not self.input_pdf or not self.input_pdf.exists():
            messagebox.showwarning("Aviso", "Por favor, selecione um PDF válido.")
            return
        if self.processing_thread and self.processing_thread.is_alive():
            return

        self.exec_btn.ativar(False)
        self.progress.grid()
        self.progress.start(12)
        self.status_label.config(text="Processando… isso pode levar alguns minutos.", fg=T.primaria)
        self._clear_log()
        self._log("=" * 60)
        self._log("🚀  Iniciando processamento...", "info")

        self.processing_thread = threading.Thread(target=self._run_processing, daemon=True)
        self.processing_thread.start()

    def _run_processing(self):
        self._ok = True
        try:
            tool = self.tool_var.get()

            if tool == "dividir":
                self._run_dividir()
            elif tool == "completo":
                self._run_completo()
            else:
                self._run_diagram()

        except Exception as e:
            self._ok = False
            import traceback
            self.log_queue.put((f"\n❌  Erro inesperado: {e}", "error"))
            self.log_queue.put((traceback.format_exc(), "error"))
        finally:
            self.after(0, self._finish_processing)

    def _run_dividir(self):
        from dividir_paginas import divide

        # Create book-specific output folder
        book_folder = self._get_book_output_folder()
        book_folder.mkdir(parents=True, exist_ok=True)
        self.last_output = book_folder

        output_pdf = book_folder / (self.input_pdf.stem + "_dividido.pdf")

        self.log_queue.put(("🔄  Separando páginas xerocadas...", "info"))
        divide(str(self.input_pdf), str(output_pdf))

        self.log_queue.put((f"\n✅  Concluído! PDF salvo em:\n{output_pdf}", "success"))

    def _dpi(self) -> int:
        try:
            return max(150, min(600, int(self.dpi_var.get())))
        except (ValueError, tk.TclError):
            return 300

    def _run_completo(self):
        """Pipeline completo: Divide → OCR → Correção → Diagramar."""
        from dividir_paginas import divide
        from preprocessar_pdf import adiciona_ocr
        from diagramar_livro_v2 import main as diagram_main
        import sys
        import pymupdf as fitz

        self.log_queue.put(("🚀  Iniciando Processamento Completo (Dividir → OCR → Corrigir → Diagramar)", "info"))

        # ============================================================
        # ETAPA 1: DIVIDIR PÁGINAS DUPLAS
        # ============================================================
        self.log_queue.put(("\n📄  Etapa 1/4: Dividindo páginas xerocadas...", "info"))

        book_folder = self._get_book_output_folder()
        book_folder.mkdir(parents=True, exist_ok=True)
        self.last_output = book_folder

        pdf_dividido = book_folder / f"{self.input_pdf.stem}_dividido.pdf"

        try:
            divide(str(self.input_pdf), str(pdf_dividido))
            self.log_queue.put((f"✅  Páginas divididas: {pdf_dividido.name}", "success"))
        except Exception as e:
            self._ok = False
            self.log_queue.put((f"\n❌  Erro ao dividir páginas: {e}", "error"))
            import traceback
            self.log_queue.put((traceback.format_exc(), "error"))
            return

        # ============================================================
        # ETAPA 2: OCR (se necessário)
        # ============================================================
        self.log_queue.put(("\n🔍  Etapa 2/4: Verificando necessidade de OCR...", "info"))

        doc = fitz.open(str(pdf_dividido))
        has_text = any(page.get_text().strip() for page in doc)
        doc.close()

        pdf_para_processar = pdf_dividido

        if not has_text:
            self.log_queue.put((f"\n📄  PDF sem texto — adicionando OCR...", "warning"))
            if not OCR_DISPONIVEL:
                self._ok = False
                self.log_queue.put((f"\n⚠️  Tesseract não configurado!", "error"))
                self.log_queue.put(("   Instale: pip install pytesseract pillow", "error"))
                self.log_queue.put(("   E certifique-se que tesseract está no PATH", "error"))
                return

            from preprocessar_pdf import adiciona_ocr

            ocr_pdf = book_folder / f"{self.input_pdf.stem}_ocr.pdf"

            try:
                dpi = self._dpi()
                self.log_queue.put((f"⏳  Processando OCR a {dpi} DPI (pode demorar)...", "info"))
                adiciona_ocr(str(pdf_dividido), str(ocr_pdf), dpi=dpi)
                pdf_para_processar = ocr_pdf
                self.log_queue.put((f"✅  OCR concluído: {ocr_pdf.name}", "success"))
            except Exception as ocr_err:
                self._ok = False
                self.log_queue.put((f"\n⚠️  OCR falhou: {ocr_err}", "error"))
                self.log_queue.put(("   Processamento interrompido.", "error"))
                return
        else:
            self.log_queue.put(("✅  PDF já tem texto — pulando OCR", "success"))

        # ============================================================
        # ETAPA 3: DIAGRAMAR (Passagem 1)
        # ============================================================
        self.log_queue.put(("\n📖  Etapa 3/4: Diagramando livro (Passagem 1)...", "info"))

        base_argv = ["diagramar_livro_v2.py", str(pdf_para_processar), str(book_folder)]

        if self.cover_path:
            base_argv += ["--capa", str(self.cover_path),
                          f"--capa-ajuste={self.cover_fit_var.get()}"]
            if self.cover_rosto_var.get():
                base_argv.append("--folha-de-rosto")
            self.log_queue.put((f"🖼️  Capa aplicada ({self.cover_fit_var.get()})", "info"))

        if self.titulo_var.get().strip():
            base_argv += ["--titulo", self.titulo_var.get().strip()]
        if self.autor_var.get().strip():
            base_argv += ["--autor", self.autor_var.get().strip()]
        if self.editora_var.get().strip():
            base_argv += ["--editora", self.editora_var.get().strip()]
        if self.ano_var.get().strip():
            base_argv += ["--ano", self.ano_var.get().strip()]

        try:
            sys.argv = base_argv
            diagram_main()
            self.log_queue.put((f"\n✅  Passagem 1 concluída!", "success"))
        except Exception as e:
            self._ok = False
            self.log_queue.put((f"\n❌  Erro na passagem 1: {e}", "error"))
            import traceback
            self.log_queue.put((traceback.format_exc(), "error"))
            return
        finally:
            sys.argv = sys.argv[:1]

        # ============================================================
        # ETAPA 4: CORREÇÃO ORTOGRÁFICA + DIAGRAMAR (Passagem 2)
        # ============================================================
        if self.correcao_var.get():
            self.log_queue.put(("\n📝  Etapa 4/4: Correção ortográfica + Diagramar (Passagem 2)...", "info"))
            txt_corrigido = self._run_spelling_correction(book_folder)

            if txt_corrigido and txt_corrigido.exists():
                try:
                    argv_pass2 = base_argv + ["--input-txt", str(txt_corrigido)]
                    sys.argv = argv_pass2
                    diagram_main()
                    self.log_queue.put((f"\n✅  Passagem 2 concluída! PDF final com correções.", "success"))
                except Exception as e:
                    self._ok = False
                    self.log_queue.put((f"\n❌  Erro na passagem 2: {e}", "error"))
                    import traceback
                    self.log_queue.put((traceback.format_exc(), "error"))
                finally:
                    sys.argv = sys.argv[:1]
            else:
                self.log_queue.put(("⚠️  Correção não gerou arquivo, mantendo PDF da passagem 1", "warning"))
        else:
            self.log_queue.put(("\n⏭️  Correção desativada — pulando Passagem 2", "info"))

        self.log_queue.put((f"\n📁  Arquivos gerados em:\n{book_folder}", "success"))

    def _dpi(self) -> int:
        from diagramar_livro_v2 import main as diagram_main
        import sys
        import pymupdf as fitz

        # Determine if OCR is needed
        self.log_queue.put(("🔍  Verificando PDF...", "info"))
        doc = fitz.open(self.input_pdf)
        has_text = any(page.get_text().strip() for page in doc)
        doc.close()

        pdf_to_process = self.input_pdf

        if not has_text:
            self.log_queue.put((f"\n📄  PDF sem texto detectado — adicionando OCR...", "warning"))
            if not OCR_DISPONIVEL:
                self._ok = False
                self.log_queue.put((f"\n⚠️  Tesseract não configurado!", "error"))
                self.log_queue.put(("   Instale: pip install pytesseract pillow", "error"))
                self.log_queue.put(("   E certifique-se que tesseract está no PATH", "error"))
                return

            from preprocessar_pdf import adiciona_ocr

            # OCR goes to book folder
            book_folder = self._get_book_output_folder()
            book_folder.mkdir(parents=True, exist_ok=True)
            ocr_pdf = book_folder / f"{self.input_pdf.stem}_ocr.pdf"

            try:
                dpi = self._dpi()
                self.log_queue.put((f"⏳  Processando OCR a {dpi} DPI (pode demorar)...", "info"))
                adiciona_ocr(str(self.input_pdf), str(ocr_pdf), dpi=dpi)
                pdf_to_process = ocr_pdf
                self.log_queue.put((f"✅  OCR concluído: {ocr_pdf.name}", "success"))
            except Exception as ocr_err:
                self.log_queue.put((f"\n⚠️  OCR falhou: {ocr_err}", "error"))

        # Build base argv for diagramar_livro_v2
        book_folder = self._get_book_output_folder()
        book_folder.mkdir(parents=True, exist_ok=True)
        self.last_output = book_folder

        base_argv = ["diagramar_livro_v2.py", str(pdf_to_process), str(book_folder)]

        if self.cover_path:
            base_argv += ["--capa", str(self.cover_path),
                          f"--capa-ajuste={self.cover_fit_var.get()}"]
            if self.cover_rosto_var.get():
                base_argv.append("--folha-de-rosto")
            self.log_queue.put((f"🖼️  Capa aplicada ({self.cover_fit_var.get()})", "info"))

        # Metadata overrides
        if self.titulo_var.get().strip():
            base_argv += ["--titulo", self.titulo_var.get().strip()]
        if self.autor_var.get().strip():
            base_argv += ["--autor", self.autor_var.get().strip()]
        if self.editora_var.get().strip():
            base_argv += ["--editora", self.editora_var.get().strip()]
        if self.ano_var.get().strip():
            base_argv += ["--ano", self.ano_var.get().strip()]

        # ---- PASSAGEM 1: Processamento normal (gera livro_limpo.txt) ----
        try:
            self.log_queue.put(("\n📖  Passagem 1: Diagramando livro (extração)...", "info"))
            sys.argv = base_argv
            diagram_main()
            self.log_queue.put((f"\n✅  Passagem 1 concluída!", "success"))

        except Exception as e:
            self._ok = False
            self.log_queue.put((f"\n❌  Erro na passagem 1: {e}", "error"))
            import traceback
            self.log_queue.put((traceback.format_exc(), "error"))
            return
        finally:
            sys.argv = sys.argv[:1]  # restaura só o nome do script

        # ---- CORREÇÃO ORTOGRÁFICA (opcional) ----
        txt_corrigido = None
        if self.correcao_var.get():
            txt_corrigido = self._run_spelling_correction(book_folder)
            if not txt_corrigido:
                self.log_queue.put(("⚠️  Correção não gerou arquivo, mantendo PDF da passagem 1", "warning"))
                self.log_queue.put((f"\n📁  Arquivos gerados em:\n{book_folder}", "success"))
                return

        # ---- PASSAGEM 2: Regenerar PDF com texto corrigido ----
        if txt_corrigido and txt_corrigido.exists():
            try:
                self.log_queue.put(("\n🔄  Passagem 2: Regenerando PDF com correções aplicadas...", "info"))
                argv_pass2 = base_argv + ["--input-txt", str(txt_corrigido)]
                sys.argv = argv_pass2
                diagram_main()
                self.log_queue.put((f"\n✅  Passagem 2 concluída! PDF final com correções.", "success"))

            except Exception as e:
                self._ok = False
                self.log_queue.put((f"\n❌  Erro na passagem 2: {e}", "error"))
                import traceback
                self.log_queue.put((traceback.format_exc(), "error"))
            finally:
                sys.argv = sys.argv[:1]

        self.log_queue.put((f"\n📁  Arquivos gerados em:\n{book_folder}", "success"))

    def _get_book_output_folder(self) -> Path:
        """Get the book-specific output folder (output/BookName/)."""
        base_name = self._clean_filename(self.input_pdf.stem)
        return self.output_base_folder / base_name

    def _clean_filename(self, name: str) -> str:
        """Clean filename for use as folder name."""
        import re
        name = re.sub(r'[<>:"/\\|?*]+', " ", name)
        name = re.sub(r'\s+', " ", name)
        return name.strip(" .") or "livro"

    def _run_spelling_correction(self, book_folder: Path) -> Path | None:
        self.log_queue.put((f"\n📝  Aplicando correção ortográfica avançada...", "info"))
        try:
            from corrigidor_avancado import corrige_texto_avancado, gera_relatorio_avancado, inicializa_dicionarios

            # Inicializa dicionários com feedback loop da pasta do livro
            inicializa_dicionarios(pasta_livro=book_folder)

            txt_path = book_folder / "livro_limpo.txt"
            if not txt_path.exists():
                self.log_queue.put(("⚠️  Texto extraído não encontrado para correção", "warning"))
                return None

            with open(txt_path, 'r', encoding='utf-8') as f:
                linhas = f.readlines()

            correcoes_todas = []
            linhas_corrigidas = []
            capitulo_atual = "Preliminares"
            pagina_atual = None

            for linha in linhas:
                # Detect chapter headers
                if re.match(r'^\s*#\s+', linha) or re.match(r'^##\s+\d+\.\s+', linha):
                    capitulo_atual = linha.strip()
                    linhas_corrigidas.append(linha)
                    continue

                pagina_match = re.search(r'\[PDF pág\.\s+(\d+)\]', linha)
                if pagina_match:
                    pagina_atual = int(pagina_match.group(1))

                linha_limpa = re.sub(r'\[PDF pág\.\s*\d+\]\s+', '', linha)
                corrigida, altas, baixas = corrige_texto_avancado(
                    linha_limpa, pagina_atual, capitulo_atual
                )
                linhas_corrigidas.append(corrigida)
                correcoes_todas.extend(altas + baixas)

            txt_corrigido = book_folder / "livro_corrigido.txt"
            with open(txt_corrigido, 'w', encoding='utf-8') as f:
                f.writelines(linhas_corrigidas)

            relatorio = book_folder / "correcoes_ortografia.txt"
            gera_relatorio_avancado(correcoes_todas, str(relatorio))

            altas = len([c for c in correcoes_todas if c.get('confianca', 0) >= 0.7])
            baixas = len(correcoes_todas) - altas
            self.log_queue.put((f"✅  Correções: {altas} alta confiança + {baixas} para revisão", "success"))

            return txt_corrigido

        except ImportError:
            self.log_queue.put((f"⚠️  Corrigidor avançado não disponível", "warning"))
            return None
        except Exception as ce:
            self.log_queue.put((f"⚠️  Erro na correção: {ce}", "error"))
            return None

    def _finish_processing(self):
        self.progress.stop()
        self.progress.grid_remove()
        self.processing_thread = None
        if getattr(self, "_ok", True):
            self.status_label.config(text="✅ Concluído! Clique em “Abrir pasta” para ver os arquivos.",
                                     fg=T.ok)
        else:
            self.status_label.config(text="⚠️ Terminou com erros. Veja o log abaixo.", fg=T.erro)
        self._atualiza_botao_pos()

    def _atualiza_botao_pos(self):
        self.exec_btn.ativar(bool(self.input_pdf))


def main():
    os.environ["OMP_NUM_THREADS"] = "1"
    try:  # nitidez em telas de alta resolução no Windows
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = PDFApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()