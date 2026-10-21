"""
GHOST - Tela de cadastro de gestos.

Abra por voz ("Ghost, abrir cadastro de gestos") — o Ghost libera a câmera
enquanto esta tela estiver aberta — ou rode direto: pythonw cadastro_gestos.py

- Gestos NATIVOS: já vêm prontos; você pode trocar a ação, o tempo de segurar ou desativar.
- Gestos GRAVADOS: você grava a pose da sua mão e escolhe a ação.
As alterações são salvas em gestos_cadastro.json e o Ghost aplica na hora.
"""
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import cv2
import pyautogui

import gestos_lib as gl

INDICE_CAMERA = 0
SEGUNDOS_PREPARO = 3
SEGUNDOS_GRAVACAO = 2.5
MAX_AMOSTRAS = 30

ROTULOS_ACOES = {v[0]: k for k, v in gl.ACOES.items()}


# -------------------------------------------------------------
# CÂMERA (gravação e teste)
# -------------------------------------------------------------
def abrir_camera(janela_pai):
    cap = cv2.VideoCapture(INDICE_CAMERA, cv2.CAP_DSHOW)
    if not cap.isOpened():
        messagebox.showerror(
            "Câmera ocupada",
            "Não consegui abrir a câmera.\n\nSe o Ghost estiver com os gestos ou a leitura facial ligados, "
            "feche esta tela e abra pelo comando de voz \"Ghost, abrir cadastro de gestos\" "
            "(ele libera a câmera automaticamente).",
            parent=janela_pai)
        return None
    return cap

def gravar_amostras(janela_pai):
    """Contagem regressiva + gravação. Retorna lista de vetores da mão ou None."""
    cap = abrir_camera(janela_pai)
    if cap is None:
        return None
    detector = gl.criar_detector_maos()
    amostras, t0 = [], time.monotonic()
    nome = "GHOST - Gravando gesto"
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            agora = time.monotonic() - t0
            p = gl.detectar(detector, frame, agora * 1000)
            if p is not None:
                gl.desenhar_mao(frame, p)
            if agora < SEGUNDOS_PREPARO:
                txt, cor = f"Prepare o gesto: {SEGUNDOS_PREPARO - int(agora)}", (0, 200, 255)
            elif agora < SEGUNDOS_PREPARO + SEGUNDOS_GRAVACAO:
                txt, cor = "GRAVANDO - segure o gesto", (0, 0, 255)
                if p is not None:
                    amostras.append(gl.vetor(p))
            else:
                break
            cv2.putText(frame, txt, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, cor, 2)
            cv2.imshow(nome, frame)
            if (cv2.waitKey(1) & 0xFF) == 27:  # Esc cancela
                return None
    finally:
        cap.release()
        cv2.destroyAllWindows(); cv2.waitKey(1)
    if len(amostras) < 10:
        messagebox.showwarning("Gravação", "A mão não foi vista o suficiente. Tente de novo, com a mão "
                               "inteira dentro da imagem e boa iluminação.", parent=janela_pai)
        return None
    passo = max(1, len(amostras) // MAX_AMOSTRAS)
    return amostras[::passo][:MAX_AMOSTRAS]

def testar(janela_pai, gestos):
    """Mostra ao vivo qual gesto está sendo reconhecido (não executa nada)."""
    cap = abrir_camera(janela_pai)
    if cap is None:
        return
    detector = gl.criar_detector_maos()
    gravados = [g for g in gestos if g.get("tipo") == "gravado" and g.get("ativo", True)]
    por_pose = {g["pose"]: g for g in gestos if g.get("tipo") == "nativo" and g.get("ativo", True)}
    nome, t0 = "GHOST - Teste (Esc para sair)", time.monotonic()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            p = gl.detectar(detector, frame, (time.monotonic() - t0) * 1000)
            txt, acao = "sem mao", ""
            if p is not None:
                gl.desenhar_mao(frame, p)
                g, dist = gl.reconhecer_gravado(gl.vetor(p), gravados)
                if g:
                    txt = f"{g['nome']} (gravado, {dist:.2f})"
                else:
                    pose = gl.classificar_nativa(p)
                    g = por_pose.get(pose)
                    txt = g["nome"] if g else pose
                acao = gl.descrever_acao(g["acao"]) if g else ""
            cv2.putText(frame, txt[:40], (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(frame, acao[:45], (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            cv2.imshow(nome, frame)
            if (cv2.waitKey(1) & 0xFF) == 27 or cv2.getWindowProperty(nome, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows(); cv2.waitKey(1)

def conflitos(amostras, gestos, ignorar_id=None):
    """Avisos se a pose gravada parece com outro gesto (o gravado tem prioridade sobre os nativos)."""
    avisos = []
    for g in gestos:
        if g.get("tipo") == "gravado" and g["id"] != ignorar_id and g.get("amostras"):
            dmin = min(gl.distancia(a, s) for a in amostras for s in g["amostras"][:10])
            if dmin <= max(g.get("limiar", 0.22), gl.calcular_limiar(amostras)):
                avisos.append(f"- parece com o gesto gravado \"{g['nome']}\"")
    return avisos


def pose_nativa_das_amostras(amostras):
    """Qual pose nativa a gravação lembra (para avisar conflito com o mouse)."""
    from collections import Counter
    from types import SimpleNamespace
    poses = [gl.classificar_nativa([SimpleNamespace(x=float(r[0]), y=float(r[1]), z=float(r[2])) for r in a])
             for a in amostras]
    return Counter(poses).most_common(1)[0][0] if poses else None

# -------------------------------------------------------------
# JANELA DE EDIÇÃO
# -------------------------------------------------------------
class Editor(tk.Toplevel):
    def __init__(self, pai, gesto, novo=False):
        super().__init__(pai)
        self.title("Novo gesto" if novo else f"Editar: {gesto['nome']}")
        self.resizable(False, False)
        self.transient(pai); self.grab_set()
        self.resultado = None
        self.gesto = gesto
        tipo, comp = gl.separar_acao(gesto.get("acao", "nada"))

        frm = ttk.Frame(self, padding=12); frm.pack(fill="both")
        ttk.Label(frm, text="Nome:").grid(row=0, column=0, sticky="w", pady=4)
        self.nome = tk.StringVar(value=gesto.get("nome", ""))
        e = ttk.Entry(frm, textvariable=self.nome, width=40)
        e.grid(row=0, column=1, columnspan=2, sticky="we")
        if gesto.get("tipo") == "nativo":
            e.state(["disabled"])

        ttk.Label(frm, text="Ação:").grid(row=1, column=0, sticky="w", pady=4)
        self.acao = tk.StringVar(value=gl.ACOES.get(tipo, gl.ACOES["nada"])[0])
        cb = ttk.Combobox(frm, textvariable=self.acao, values=[v[0] for v in gl.ACOES.values()],
                          state="readonly", width=45)
        cb.grid(row=1, column=1, columnspan=2, sticky="we")
        cb.bind("<<ComboboxSelected>>", lambda _: self._atualizar())

        self.lbl_comp = ttk.Label(frm, text="Complemento:")
        self.lbl_comp.grid(row=2, column=0, sticky="w", pady=4)
        self.comp = tk.StringVar(value=comp)
        self.ent_comp = ttk.Entry(frm, textvariable=self.comp, width=40)
        self.ent_comp.grid(row=2, column=1, columnspan=2, sticky="we")
        self.dica = ttk.Label(frm, text="", foreground="#666")
        self.dica.grid(row=3, column=1, columnspan=2, sticky="w")

        ttk.Label(frm, text="Segurar por (s):").grid(row=4, column=0, sticky="w", pady=4)
        self.segurar = tk.DoubleVar(value=gesto.get("segurar", 0.8))
        ttk.Spinbox(frm, from_=0, to=5, increment=0.1, textvariable=self.segurar, width=6)\
            .grid(row=4, column=1, sticky="w")
        ttk.Label(frm, text="0 = dispara na hora", foreground="#666").grid(row=4, column=2, sticky="w")

        self.ativo = tk.BooleanVar(value=gesto.get("ativo", True))
        ttk.Checkbutton(frm, text="Ativo", variable=self.ativo).grid(row=5, column=1, sticky="w", pady=4)

        bts = ttk.Frame(frm); bts.grid(row=6, column=0, columnspan=3, pady=(10, 0), sticky="e")
        ttk.Button(bts, text="Cancelar", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(bts, text="OK", command=self._ok).pack(side="right")
        self._atualizar()
        self.wait_window(self)

    def _atualizar(self):
        chave = ROTULOS_ACOES.get(self.acao.get(), "nada")
        if chave == "tecla":
            self.ent_comp.state(["!disabled"])
            self.dica.config(text="Ex.: enter, esc, ctrl+c, ctrl+shift+t, alt+tab, win+d, f5")
        elif chave == "comando":
            self.ent_comp.state(["!disabled"])
            self.dica.config(text="Uma frase que você diria ao Ghost. Ex.: abrir calculadora")
        else:
            self.ent_comp.state(["disabled"])
            self.dica.config(text="")

    def _ok(self):
        chave = ROTULOS_ACOES.get(self.acao.get(), "nada")
        comp = self.comp.get().strip().lower() if chave == "tecla" else self.comp.get().strip()
        if gl.ACOES[chave][1] and not comp:
            messagebox.showwarning("Ação", "Preencha o complemento da ação.", parent=self); return
        if chave == "tecla":
            invalidas = [t for t in comp.replace(" ", "").split("+") if t not in pyautogui.KEYBOARD_KEYS]
            if invalidas:
                messagebox.showwarning("Tecla", f"Tecla(s) não reconhecida(s): {', '.join(invalidas)}", parent=self)
                return
        if not self.nome.get().strip():
            messagebox.showwarning("Nome", "Dê um nome ao gesto.", parent=self); return
        self.resultado = {
            "nome": self.nome.get().strip(),
            "acao": f"{chave}:{comp}" if gl.ACOES[chave][1] else chave,
            "segurar": round(float(self.segurar.get()), 2),
            "ativo": bool(self.ativo.get()),
        }
        self.destroy()


# -------------------------------------------------------------
# JANELA PRINCIPAL
# -------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GHOST - Cadastro de Gestos")
        self.geometry("900x480")
        self.gestos = gl.carregar_cadastro()

        topo = ttk.Frame(self, padding=8); topo.pack(fill="x")
        for txt, cmd in [("Novo gesto (gravar)", self.novo), ("Regravar", self.regravar),
                         ("Editar", self.editar), ("Ativar/Desativar", self.alternar),
                         ("Excluir", self.excluir), ("Testar reconhecimento", self.testar),
                         ("Restaurar nativos", self.restaurar)]:
            ttk.Button(topo, text=txt, command=cmd).pack(side="left", padx=3)

        cols = ("nome", "tipo", "acao", "segurar", "ativo")
        self.tv = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        for c, t, w in [("nome", "Gesto", 330), ("tipo", "Tipo", 80), ("acao", "Ação", 300),
                        ("segurar", "Segurar (s)", 90), ("ativo", "Ativo", 60)]:
            self.tv.heading(c, text=t); self.tv.column(c, width=w, anchor="w")
        self.tv.pack(fill="both", expand=True, padx=8)
        self.tv.bind("<Double-1>", lambda _: self.editar())

        rodape = ttk.Frame(self, padding=8); rodape.pack(fill="x")
        ttk.Label(rodape, foreground="#555", text="Gestos gravados têm prioridade sobre os nativos. "
                  "Alterações são salvas na hora e o Ghost aplica sozinho.").pack(side="left")
        ttk.Button(rodape, text="Fechar", command=self.destroy).pack(side="right")
        self.atualizar_lista()

    def atualizar_lista(self):
        self.tv.delete(*self.tv.get_children())
        for g in self.gestos:
            self.tv.insert("", "end", iid=g["id"], values=(
                g["nome"], "Nativo" if g.get("tipo") == "nativo" else "Gravado",
                gl.descrever_acao(g.get("acao")), g.get("segurar", 0), "Sim" if g.get("ativo", True) else "Não"))

    def salvar(self):
        gl.salvar_cadastro(self.gestos)
        self.atualizar_lista()

    def selecionado(self):
        sel = self.tv.selection()
        if not sel:
            messagebox.showinfo("Cadastro", "Selecione um gesto na lista.", parent=self); return None
        return next(g for g in self.gestos if g["id"] == sel[0])

    def _confirmar_conflitos(self, amostras, ignorar_id=None):
        avisos = conflitos(amostras, self.gestos, ignorar_id)
        pose = pose_nativa_das_amostras(amostras)
        if pose in ("mover", "pinca", "pinca_medio", "rolar"):
            avisos.append(f"- parece com a pose nativa \"{gl.POSES_NATIVAS[pose]}\", usada pelo mouse. "
                          "Como o gravado tem prioridade, o mouse deixaria de funcionar com essa pose.")
        if avisos:
            return messagebox.askyesno("Gesto parecido", "Atenção:\n" + "\n".join(avisos) +
                                       "\n\nSalvar mesmo assim?", parent=self)
        return True

    def novo(self):
        nome = simpledialog.askstring("Novo gesto", "Nome do gesto (ex.: Paz e amor):", parent=self)
        if not nome:
            return
        messagebox.showinfo("Gravação", f"Vai abrir a câmera. Faça o gesto \"{nome}\" após a contagem "
                            f"e segure por {SEGUNDOS_GRAVACAO:.0f} s.\nDica: mexa levemente a mão durante "
                            "a gravação para o Ghost aprender pequenas variações.", parent=self)
        amostras = gravar_amostras(self)
        if not amostras or not self._confirmar_conflitos(amostras):
            return
        rascunho = {"nome": nome, "tipo": "gravado", "acao": "tecla:enter", "segurar": 0.8, "ativo": True}
        ed = Editor(self, rascunho, novo=True)
        if ed.resultado:
            g = gl.novo_gravado(ed.resultado["nome"], ed.resultado["acao"], ed.resultado["segurar"], amostras)
            g["ativo"] = ed.resultado["ativo"]
            self.gestos.append(g)
            self.salvar()

    def regravar(self):
        g = self.selecionado()
        if not g:
            return
        if g.get("tipo") == "nativo":
            messagebox.showinfo("Regravar", "Gestos nativos não são gravados; você pode mudar a ação deles "
                                "ou desativá-los e gravar um gesto seu.", parent=self); return
        amostras = gravar_amostras(self)
        if not amostras or not self._confirmar_conflitos(amostras, g["id"]):
            return
        novo = gl.novo_gravado(g["nome"], g["acao"], g.get("segurar", 0.8), amostras)
        g["amostras"], g["limiar"] = novo["amostras"], novo["limiar"]
        self.salvar()

    def editar(self):
        g = self.selecionado()
        if not g:
            return
        ed = Editor(self, g)
        if ed.resultado:
            g.update(ed.resultado)
            self.salvar()

    def alternar(self):
        g = self.selecionado()
        if g:
            g["ativo"] = not g.get("ativo", True)
            self.salvar()

    def excluir(self):
        g = self.selecionado()
        if not g:
            return
        if g.get("tipo") == "nativo":
            messagebox.showinfo("Excluir", "Gestos nativos não podem ser excluídos, só desativados.", parent=self)
            return
        if messagebox.askyesno("Excluir", f"Excluir o gesto \"{g['nome']}\"?", parent=self):
            self.gestos.remove(g)
            self.salvar()

    def testar(self):
        testar(self, self.gestos)

    def restaurar(self):
        if messagebox.askyesno("Restaurar", "Voltar os gestos NATIVOS ao padrão? Os gravados são mantidos.",
                               parent=self):
            self.gestos = gl.restaurar_nativos(self.gestos)
            self.salvar()


if __name__ == "__main__":
    App().mainloop()
