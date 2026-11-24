#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
editor_sumario_gui.py - Editor Visual do Sumário (Drag-and-Drop)

Componente tkinter para reordenar, renomear, adicionar/remover capítulos
antes de gerar o livro diagramado.
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path
import sys

# Adiciona o diretório do app ao path
sys.path.insert(0, str(Path(__file__).parent))

from diagramar_livro_v2 import preview_sumario


@dataclass
class ItemSumario:
    """Item do sumário (capítulo ou seção)."""
    id: str
    titulo: str
    nivel: int = 0              # 0 = capítulo, 1 = seção, 2 = subseção
    pagina_pdf: Optional[int] = None
    pai_id: Optional[str] = None
    filhos: List['ItemSumario'] = field(default_factory=list)
    expandido: bool = True

    def __post_init__(self):
        if self.filhos is None:
            self.filhos = []


class EditorSumario(ttk.Frame):
    """
    Editor visual do sumário com drag-and-drop.
    """

    def __init__(self, parent, on_change: Callable = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.on_change = on_change
        self.itens: List[ItemSumario] = []
        self.item_selecionado: Optional[str] = None
        self._drag_data = {"item": None, "y": 0}

        self._build_ui()

    def _build_ui(self):
        """Constrói a interface."""
        self.configure(padding=10)

        # Toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 10))

        ttk.Label(toolbar, text="Editor do Sumário", font=("Segoe UI", 11, "bold")).pack(side="left")

        ttk.Button(toolbar, text="➕ Capítulo", command=self._adiciona_capitulo).pack(side="left", padx=5)
        ttk.Button(toolbar, text="➕ Seção", command=self._adiciona_secao).pack(side="left", padx=5)
        ttk.Button(toolbar, text="🗑️ Remover", command=self._remove_item).pack(side="left", padx=5)
        ttk.Button(toolbar, text="📂 Expandir Tudo", command=self._expandir_tudo).pack(side="right", padx=5)
        ttk.Button(toolbar, text="📁 Colapsar Tudo", command=self._colapsar_tudo).pack(side="right", padx=5)

        # Treeview com drag-and-drop
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True)

        # Scrollbars
        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal")

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("pagina", "nivel"),
            show="tree headings",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            selectmode="browse"
        )

        vsb.config(command=self.tree.yview)
        hsb.config(command=self.tree.xview)

        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.tree.pack(fill="both", expand=True)

        # Configura colunas
        self.tree.heading("#0", text="Título", anchor="w")
        self.tree.heading("pagina", text="Página PDF", anchor="center")
        self.tree.heading("nivel", text="Nível", anchor="center")

        self.tree.column("#0", width=400, minwidth=200)
        self.tree.column("pagina", width=80, minwidth=60, anchor="center")
        self.tree.column("nivel", width=60, minwidth=50, anchor="center")

        # Tags para níveis
        self.tree.tag_configure("nivel0", font=("Segoe UI", 10, "bold"))
        self.tree.tag_configure("nivel1", font=("Segoe UI", 10))
        self.tree.tag_configure("nivel2", font=("Segoe UI", 9, "italic"))
        self.tree.tag_configure("arrastando", background="#cce5ff")

        # Drag-and-drop bindings
        self.tree.bind("<ButtonPress-1>", self._on_drag_start)
        self.tree.bind("<B1-Motion>", self._on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_drop)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Delete>", lambda e: self._remove_item())
        self.tree.bind("<F2>", lambda e: self._edita_titulo())
        self.tree.bind("<Return>", lambda e: self._edita_titulo())

        # Context menu
        self._build_context_menu()

        # Status bar
        self.status_var = tk.StringVar(value="Pronto")
        status = ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w")
        status.pack(fill="x", pady=(10, 0))

    def _build_context_menu(self):
        """Cria menu de contexto (botão direito)."""
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="✏️ Renomear (F2)", command=self._edita_titulo)
        self.context_menu.add_command(label="➕ Adicionar Seção", command=self._adiciona_secao)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="⬆️ Mover para Cima", command=lambda: self._move_item(-1))
        self.context_menu.add_command(label="⬇️ Mover para Baixo", command=lambda: self._move_item(1))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📁 Promover (↑ nível)", command=lambda: self._promove_item(-1))
        self.context_menu.add_command(label="📂 Rebaixar (↓ nível)", command=lambda: self._promove_item(1))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🗑️ Excluir (Del)", command=self._remove_item)

        self.tree.bind("<Button-3>", self._show_context_menu)

    def _show_context_menu(self, event):
        """Mostra menu de contexto."""
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    # ==================== OPERAÇÕES DE DADOS ====================

    def carrega_do_preview(self, pdf_path: str):
        """Carrega sumário detectado automaticamente."""
        try:
            preview = preview_sumario(pdf_path)
            self.limpa()

            for cap in preview.get("capitulos", []):
                self._adiciona_item_hierarquico(
                    titulo=cap["titulo"],
                    nivel=0,
                    pagina=cap.get("paginas_pdf", "").split("–")[0] if cap.get("paginas_pdf") else None
                )

            self.status_var.set(f"Carregado: {len(self.itens)} capítulos detectados")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao carregar preview:\n{e}")

    def carrega_estrutura(self, caps: List[Dict]):
        """Carrega estrutura de capítulos processada."""
        self.limpa()
        for cap in caps:
            item = self._adiciona_item_hierarquico(
                titulo=cap["titulo"],
                nivel=0,
                pagina=cap.get("pags", [None, None])[0]
            )
            # Adiciona subcapítulos se houver
            for sub in cap.get("subcapitulos", []):
                self._adiciona_filho(item.id, sub["titulo"], 1, sub.get("pagina"))

    def limpa(self):
        """Limpa todos os itens."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.itens.clear()
        self.item_selecionado = None

    def obtem_estrutura(self) -> List[Dict]:
        """Retorna estrutura atual como lista de dicts."""
        resultado = []
        for item_id in self.tree.get_children(""):
            resultado.append(self._item_para_dict(item_id))
        return resultado

    def _item_para_dict(self, item_id: str) -> Dict:
        """Converte item da tree para dict."""
        item = self.tree.item(item_id)
        titulo = item["text"]
        valores = item["values"]
        pagina = valores[0] if valores else None
        nivel = valores[1] if len(valores) > 1 else 0

        filhos = []
        for child_id in self.tree.get_children(item_id):
            filhos.append(self._item_para_dict(child_id))

        return {
            "id": item_id,
            "titulo": titulo,
            "nivel": nivel,
            "pagina": pagina,
            "filhos": filhos
        }

    # ==================== DRAG-AND-DROP ====================

    def _on_drag_start(self, event):
        """Inicia drag."""
        item = self.tree.identify_row(event.y)
        if not item:
            return

        # Não permite arrastar se for filho de item colapsado
        parent = self.tree.parent(item)
        if parent and not self.tree.item(parent, "open"):
            return

        self._drag_data["item"] = item
        self._drag_data["y"] = event.y
        self.tree.item(item, tags=("arrastando",))

    def _on_drag_motion(self, event):
        """Durante drag - mostra indicador visual."""
        if not self._drag_data["item"]:
            return

        target = self.tree.identify_row(event.y)
        if target and target != self._drag_data["item"]:
            # Remove indicador anterior
            for item in self.tree.get_children(""):
                self._remove_drop_indicator(item)

            # Adiciona indicador no target
            self._add_drop_indicator(target, event.y)

    def _on_drag_drop(self, event):
        """Finaliza drag - move item."""
        if not self._drag_data["item"]:
            return

        source = self._drag_data["item"]
        target = self.tree.identify_row(event.y)

        # Limpa indicadores
        for item in self.tree.get_children(""):
            self._remove_drop_indicator(item)

        self.tree.item(source, tags=())

        if target and target != source:
            self._move_item_para(source, target, event.y)

        self._drag_data = {"item": None, "y": 0}
        self._notifica_mudanca()

    def _add_drop_indicator(self, target, y):
        """Adiciona indicador visual de drop."""
        bbox = self.tree.bbox(target, column="#0")
        if bbox:
            x, ty, w, h = bbox
            # Cria linha indicadora
            self.tree.item(target, tags=("drop-target",))
            self.tree.tag_configure("drop-target", background="#e8f4fd")

    def _remove_drop_indicator(self, item):
        """Remove indicador de drop."""
        tags = list(self.tree.item(item, "tags"))
        if "drop-target" in tags:
            tags.remove("drop-target")
            self.tree.item(item, tags=tags)

    def _move_item_para(self, source, target, y):
        """Move item source para posição relativa a target."""
        source_parent = self.tree.parent(source)
        target_parent = self.tree.parent(target)

        # Obtém índices
        source_idx = self.tree.index(source)
        target_idx = self.tree.index(target)

        # Determina posição relativa (antes ou depois)
        bbox = self.tree.bbox(target, column="#0")
        if bbox:
            _, ty, _, th = bbox
            drop_after = (event.y - ty) > th / 2 if 'event' in locals() else source_idx < target_idx
        else:
            drop_after = source_idx < target_idx

        new_idx = target_idx + (1 if drop_after else 0)

        # Move na tree
        self.tree.move(source, target_parent, new_idx)

        # Se moveu para dentro de outro item (rebaixou)
        if target_parent != source_parent:
            # Verifica se target está expandido
            if not self.tree.item(target, "open"):
                self.tree.item(target, open=True)

    # ==================== OPERAÇÕES DE ITENS ====================

    def _adiciona_capitulo(self):
        """Adiciona novo capítulo no final."""
        titulo = self._prompt_titulo("Novo Capítulo")
        if titulo:
            self._adiciona_item_hierarquico(titulo, nivel=0)
            self._notifica_mudanca()

    def _adiciona_secao(self):
        """Adiciona seção como filho do item selecionado."""
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione um capítulo pai primeiro")
            return

        parent = sel[0]
        parent_nivel = int(self.tree.item(parent, "values")[1]) if self.tree.item(parent, "values") else 0

        if parent_nivel >= 2:
            messagebox.showwarning("Aviso", "Máximo 3 níveis (capítulo > seção > subseção)")
            return

        titulo = self._prompt_titulo("Nova Seção")
        if titulo:
            self._adiciona_filho(parent, titulo, parent_nivel + 1)
            # Expande pai
            self.tree.item(parent, open=True)
            self._notifica_mudanca()

    def _adiciona_item_hierarquico(self, titulo: str, nivel: int, pagina: str = None) -> str:
        """Adiciona item no nível raiz."""
        tags = (f"nivel{nivel}",)
        item_id = self.tree.insert("", "end", text=titulo, values=(pagina or "", nivel), tags=tags)
        return item_id

    def _adiciona_filho(self, parent: str, titulo: str, nivel: int, pagina: str = None) -> str:
        """Adiciona item como filho de parent."""
        tags = (f"nivel{nivel}",)
        item_id = self.tree.insert(parent, "end", text=titulo, values=(pagina or "", nivel), tags=tags)
        return item_id

    def _remove_item(self):
        """Remove item selecionado (e filhos)."""
        sel = self.tree.selection()
        if not sel:
            return

        if messagebox.askyesno("Confirmar", "Remover item selecionado e todos os seus filhos?"):
            for item in sel:
                self.tree.delete(item)
            self._notifica_mudanca()

    def _edita_titulo(self, event=None):
        """Edita título do item selecionado (inline)."""
        sel = self.tree.selection()
        if not sel:
            return

        item = sel[0]
        titulo_atual = self.tree.item(item, "text")

        # Cria entry temporário
        bbox = self.tree.bbox(item, column="#0")
        if not bbox:
            return

        x, y, w, h = bbox
        entry = ttk.Entry(self.tree)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, titulo_atual)
        entry.select_range(0, tk.END)
        entry.focus()

        def salva(e=None):
            novo = entry.get().strip()
            if novo and novo != titulo_atual:
                self.tree.item(item, text=novo)
                self._notifica_mudanca()
            entry.destroy()

        def cancela(e=None):
            entry.destroy()

        entry.bind("<Return>", salva)
        entry.bind("<Escape>", cancela)
        entry.bind("<FocusOut>", salva)

    def _move_item(self, direcao: int):
        """Move item para cima (-1) ou baixo (1)."""
        sel = self.tree.selection()
        if not sel:
            return

        item = sel[0]
        parent = self.tree.parent(item)
        idx = self.tree.index(item)
        siblings = self.tree.get_children(parent)

        if 0 <= idx + direcao < len(siblings):
            self.tree.move(item, parent, idx + direcao)
            self._notifica_mudanca()

    def _promove_item(self, delta: int):
        """Promove (delta=-1) ou rebaixa (delta=1) nível do item."""
        sel = self.tree.selection()
        if not sel:
            return

        item = sel[0]
        parent = self.tree.parent(item)
        nivel_atual = int(self.tree.item(item, "values")[1]) if self.tree.item(item, "values") else 0
        novo_nivel = nivel_atual + delta

        if novo_nivel < 0 or novo_nivel > 2:
            return

        # Se promovendo (subindo nível), move para pai do pai
        if delta == -1 and parent:
            avo = self.tree.parent(parent)
            idx = self.tree.index(item)
            self.tree.move(item, avo, self.tree.index(parent) + 1)

        # Se rebaixando (descendo nível), move para irmão anterior como pai
        elif delta == 1 and parent:
            siblings = self.tree.get_children(parent)
            idx = self.tree.index(item)
            if idx > 0:
                novo_pai = siblings[idx - 1]
                if self.tree.item(novo_pai, "values")[1] < 2:  # só se não for nível 2
                    self.tree.move(item, novo_pai, "end")
                    self.tree.item(novo_pai, open=True)

        # Atualiza tag de nível
        novo_nivel = max(0, min(2, nivel_atual + delta))
        self.tree.item(item, tags=(f"nivel{novo_nivel}",))
        self.tree.item(item, values=(self.tree.item(item, "values")[0], novo_nivel))

        # Atualiza filhos recursivamente
        self._atualiza_nivel_filhos(item, novo_nivel + 1)
        self._notifica_mudanca()

    def _atualiza_nivel_filhos(self, item: str, novo_nivel: int):
        """Atualiza nível dos filhos recursivamente."""
        if novo_nivel > 2:
            return
        for child in self.tree.get_children(item):
            self.tree.item(child, tags=(f"nivel{novo_nivel}",))
            vals = list(self.tree.item(child, "values"))
            if len(vals) > 1:
                vals[1] = novo_nivel
                self.tree.item(child, values=vals)
            self._atualiza_nivel_filhos(child, novo_nivel + 1)

    # ==================== UTILITÁRIOS ====================

    def _prompt_titulo(self, label: str) -> Optional[str]:
        """Dialog simples para título."""
        dialog = tk.Toplevel(self)
        dialog.title(label)
        dialog.geometry("400x120")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(dialog, text=f"{label}:").pack(pady=(15, 5))
        entry = ttk.Entry(dialog, width=50)
        entry.pack(pady=5, padx=20)
        entry.focus()

        resultado = {"valor": None}

        def ok():
            resultado["valor"] = entry.get().strip()
            dialog.destroy()

        def cancel():
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=15)
        ttk.Button(btn_frame, text="OK", command=ok).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancelar", command=cancel).pack(side="left", padx=5)

        entry.bind("<Return>", lambda e: ok())
        entry.bind("<Escape>", lambda e: cancel())

        dialog.wait_window()
        return resultado["valor"] if resultado["valor"] else None

    def _expandir_tudo(self):
        for item in self.tree.get_children(""):
            self._expande_recursivo(item)

    def _colapsar_tudo(self):
        for item in self.tree.get_children(""):
            self.tree.item(item, open=False)

    def _expande_recursivo(self, item: str):
        self.tree.item(item, open=True)
        for child in self.tree.get_children(item):
            self._expande_recursivo(child)

    def _on_select(self, event):
        sel = self.tree.selection()
        self.item_selecionado = sel[0] if sel else None
        if self.item_selecionado:
            titulo = self.tree.item(self.item_selecionado, "text")
            self.status_var.set(f"Selecionado: {titulo}")

    def _on_double_click(self, event):
        self._edita_titulo()

    def _notifica_mudanca(self):
        if self.on_change:
            self.on_change(self.obtem_estrutura())

    # ==================== API PÚBLICA ====================

    def obtem_estrutura_plana(self) -> List[Dict]:
        """Retorna lista plana de itens (para processamento)."""
        return self.obtem_estrutura()

    def define_estrutura(self, estrutura: List[Dict]):
        """Define estrutura completa (substitui atual)."""
        self.limpa()
        for item in estrutura:
            self._cria_item_recursivo(item, "")

    def _cria_item_recursivo(self, item_data: Dict, parent: str):
        item_id = self.tree.insert(
            parent, "end",
            text=item_data.get("titulo", ""),
            values=(item_data.get("pagina", ""), item_data.get("nivel", 0)),
            tags=(f"nivel{item_data.get('nivel', 0)}",)
        )
        for filho in item_data.get("filhos", []):
            self._cria_item_recursivo(filho, item_id)


# ==================== DEMO / TESTE ====================

if __name__ == "__main__":
    root = tk.Tk()
    root.title("Editor de Sumário - Demo")
    root.geometry("700x600")

    def on_change(estrutura):
        print(f"📝 Mudança: {len(estrutura)} capítulos raiz")
        for cap in estrutura:
            print(f"  - {cap['titulo']} (p. {cap.get('pagina', '?')})")

    editor = EditorSumario(root, on_change=on_change)
    editor.pack(fill="both", expand=True, padx=10, pady=10)

    # Dados de exemplo
    exemplo = [
        {"titulo": "Introdução", "nivel": 0, "pagina": "1"},
        {"titulo": "Capítulo 1: Fundamentos", "nivel": 0, "pagina": "15",
         "filhos": [
             {"titulo": "1.1 Conceitos Básicos", "nivel": 1, "pagina": "16"},
             {"titulo": "1.2 Histórico", "nivel": 1, "pagina": "22"},
         ]},
        {"titulo": "Capítulo 2: Avançado", "nivel": 0, "pagina": "45"},
        {"titulo": "Conclusão", "nivel": 0, "pagina": "89"},
    ]

    editor.define_estrutura(exemplo)

    # Botão para testar exportação
    ttk.Button(root, text="📤 Exportar Estrutura",
               command=lambda: print(editor.obtem_estrutura())).pack(pady=10)

    root.mainloop()