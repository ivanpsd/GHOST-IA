"""
GHOST - Tela de cadastro de Gestos e Ações.

Abra por voz ("Ghost, abrir cadastro de gestos") — o Ghost libera a câmera
enquanto esta tela estiver aberta — ou rode direto: pythonw cadastro_gestos.py

Aba AÇÕES: o que pode ser feito.
  - Sistema (mover mouse, clique, rolar...), Tecla/atalho, Comando de voz do Ghost
  - Macro gravada: clique em "Gravar ação", faça no PC o que quiser e pressione F10.
Aba GESTOS: os movimentos da mão. Cada gesto aponta para uma ação.
  - Nativos: já vêm prontos (troque a ação ou desative).
  - Gravados: você grava a pose da sua mão.
Tudo é salvo em gestos_cadastro.json e o Ghost aplica na hora.
"""
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import cv2
import pyautogui

import gestos_lib as gl
import macros

INDICE_CAMERA = 0
SEGUNDOS_PREPARO = 3
SEGUNDOS_GRAVACAO = 2.5
MAX_AMOSTRAS = 30


# -------------------------------------------------------------
# CÂMERA (gravação de gesto e teste)
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

def testar(janela_pai, cad):
    """Mostra ao vivo qual gesto está sendo reconhecido e a ação ligada (não executa nada)."""
    cap = abrir_camera(janela_pai)
    if cap is None:
        return
    detector = gl.criar_detector_maos()
    gestos = cad["gestos"]
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
                a = gl.acao_por_id(cad, g.get("acao_id")) if g else None
                acao = ("-> " + a["nome"]) if a else ""
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
# ESCOLHA DE AÇÃO (usada no editor de gesto)
# -------------------------------------------------------------
def rotulo_acao(a):
    return f"{a['nome']}  —  {gl.TIPOS_ACAO.get(a['tipo'], a['tipo'])}"


# -------------------------------------------------------------
# EDITOR DE GESTO: nome, ação ligada, tempo de segurar, ativo
# -------------------------------------------------------------
class EditorGesto(tk.Toplevel):
    def __init__(self, pai, cad, gesto, novo=False):
        super().__init__(pai)
        self.title("Novo gesto" if novo else f"Gesto: {gesto['nome']}")
        self.resizable(False, False)
        self.transient(pai); self.grab_set()
        self.resultado = None
        self.acoes = cad["acoes"]

        frm = ttk.Frame(self, padding=12); frm.pack(fill="both")
        ttk.Label(frm, text="Nome do gesto:").grid(row=0, column=0, sticky="w", pady=4)
        self.nome = tk.StringVar(value=gesto.get("nome", ""))
        e = ttk.Entry(frm, textvariable=self.nome, width=45)
        e.grid(row=0, column=1, columnspan=2, sticky="we")
        if gesto.get("tipo") == "nativo":
            e.state(["disabled"])

        ttk.Label(frm, text="Faz a ação:").grid(row=1, column=0, sticky="w", pady=4)
        self.rotulos = [rotulo_acao(a) for a in self.acoes]
        atual = gl.acao_por_id(cad, gesto.get("acao_id")) or gl.acao_por_id(cad, "nada")
        self.acao = tk.StringVar(value=rotulo_acao(atual))
        ttk.Combobox(frm, textvariable=self.acao, values=self.rotulos, state="readonly", width=50)\
            .grid(row=1, column=1, columnspan=2, sticky="we")
        ttk.Label(frm, text="Para criar uma ação nova, use a aba Ações.", foreground="#666")\
            .grid(row=2, column=1, columnspan=2, sticky="w")

        ttk.Label(frm, text="Segurar por (s):").grid(row=3, column=0, sticky="w", pady=4)
        self.segurar = tk.DoubleVar(value=gesto.get("segurar", 0.8))
        ttk.Spinbox(frm, from_=0, to=5, increment=0.1, textvariable=self.segurar, width=6)\
            .grid(row=3, column=1, sticky="w")
        ttk.Label(frm, text="0 = dispara na hora", foreground="#666").grid(row=3, column=2, sticky="w")

        self.ativo = tk.BooleanVar(value=gesto.get("ativo", True))
        ttk.Checkbutton(frm, text="Ativo", variable=self.ativo).grid(row=4, column=1, sticky="w", pady=4)

        bts = ttk.Frame(frm); bts.grid(row=5, column=0, columnspan=3, pady=(10, 0), sticky="e")
        ttk.Button(bts, text="Cancelar", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(bts, text="OK", command=self._ok).pack(side="right")
        self.wait_window(self)

    def _ok(self):
        if not self.nome.get().strip():
            messagebox.showwarning("Nome", "Dê um nome ao gesto.", parent=self); return
        acao = self.acoes[self.rotulos.index(self.acao.get())]
        self.resultado = {"nome": self.nome.get().strip(), "acao_id": acao["id"],
                          "segurar": round(float(self.segurar.get()), 2), "ativo": bool(self.ativo.get())}
        self.destroy()


# -------------------------------------------------------------
# EDITOR DE AÇÃO (tecla ou comando de voz; macros são gravadas)
# -------------------------------------------------------------
class EditorAcao(tk.Toplevel):
    def __init__(self, pai, acao=None):
        super().__init__(pai)
        self.title("Nova ação" if acao is None else f"Ação: {acao['nome']}")
        self.resizable(False, False)
        self.transient(pai); self.grab_set()
        self.resultado = None
        acao = acao or {"nome": "", "tipo": "tecla", "valor": ""}
        self.eh_macro = acao["tipo"] == "macro"

        frm = ttk.Frame(self, padding=12); frm.pack(fill="both")
        ttk.Label(frm, text="Nome da ação:").grid(row=0, column=0, sticky="w", pady=4)
        self.nome = tk.StringVar(value=acao["nome"])
        ttk.Entry(frm, textvariable=self.nome, width=45).grid(row=0, column=1, sticky="we")

        if self.eh_macro:
            ttk.Label(frm, text="Ritmo:").grid(row=1, column=0, sticky="w", pady=4)
            self.ritmo = tk.StringVar(value=acao.get("ritmo", "original"))
            rf = ttk.Frame(frm); rf.grid(row=1, column=1, sticky="w")
            ttk.Radiobutton(rf, text="Tempo original", value="original", variable=self.ritmo).pack(side="left")
            ttk.Radiobutton(rf, text="Rápido", value="rapido", variable=self.ritmo).pack(side="left", padx=8)
            ttk.Label(frm, text="Para mudar os passos, use \"Regravar macro\".", foreground="#666")\
                .grid(row=2, column=1, sticky="w")
        else:
            ttk.Label(frm, text="Tipo:").grid(row=1, column=0, sticky="w", pady=4)
            self.tipo = tk.StringVar(value=acao["tipo"])
            tf = ttk.Frame(frm); tf.grid(row=1, column=1, sticky="w")
            ttk.Radiobutton(tf, text="Tecla/atalho", value="tecla", variable=self.tipo,
                            command=self._dica).pack(side="left")
            ttk.Radiobutton(tf, text="Comando de voz", value="comando", variable=self.tipo,
                            command=self._dica).pack(side="left", padx=8)
            ttk.Label(frm, text="Valor:").grid(row=2, column=0, sticky="w", pady=4)
            self.valor = tk.StringVar(value=acao.get("valor", ""))
            ttk.Entry(frm, textvariable=self.valor, width=45).grid(row=2, column=1, sticky="we")
            self.lbl = ttk.Label(frm, foreground="#666"); self.lbl.grid(row=3, column=1, sticky="w")
            self._dica()

        bts = ttk.Frame(frm); bts.grid(row=4, column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(bts, text="Cancelar", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(bts, text="OK", command=self._ok).pack(side="right")
        self.wait_window(self)

    def _dica(self):
        self.lbl.config(text="Ex.: enter, ctrl+c, ctrl+shift+t, alt+tab, win+d, f5" if self.tipo.get() == "tecla"
                        else "Uma frase que você diria ao Ghost. Ex.: abrir calculadora")

    def _ok(self):
        nome = self.nome.get().strip()
        if not nome:
            messagebox.showwarning("Nome", "Dê um nome à ação.", parent=self); return
        if self.eh_macro:
            self.resultado = {"nome": nome, "ritmo": self.ritmo.get()}
        else:
            tipo, valor = self.tipo.get(), self.valor.get().strip()
            if not valor:
                messagebox.showwarning("Valor", "Preencha o valor da ação.", parent=self); return
            if tipo == "tecla":
                valor = valor.lower().replace(" ", "")
                invalidas = [t for t in valor.split("+") if t not in pyautogui.KEYBOARD_KEYS]
                if invalidas:
                    messagebox.showwarning("Tecla", f"Tecla(s) não reconhecida(s): {', '.join(invalidas)}",
                                           parent=self); return
            self.resultado = {"nome": nome, "tipo": tipo, "valor": valor}
        self.destroy()


# -------------------------------------------------------------
# JANELA PRINCIPAL: abas Gestos e Ações
# -------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GHOST - Cadastro de Gestos e Ações")
        self.geometry("980x520")
        self.cad = gl.carregar_cadastro()

        abas = ttk.Notebook(self); abas.pack(fill="both", expand=True, padx=8, pady=8)

        # ---- aba GESTOS
        fg = ttk.Frame(abas); abas.add(fg, text="  Gestos  ")
        topo = ttk.Frame(fg, padding=6); topo.pack(fill="x")
        for txt, cmd in [("Novo gesto (gravar)", self.novo_gesto), ("Regravar", self.regravar),
                         ("Editar / trocar ação", self.editar_gesto), ("Ativar/Desativar", self.alternar),
                         ("Excluir", self.excluir_gesto), ("Testar reconhecimento", self.testar),
                         ("Restaurar nativos", self.restaurar)]:
            ttk.Button(topo, text=txt, command=cmd).pack(side="left", padx=3)
        cols = ("nome", "tipo", "acao", "segurar", "ativo")
        self.tg = ttk.Treeview(fg, columns=cols, show="headings", selectmode="browse")
        for c, t, w in [("nome", "Gesto", 330), ("tipo", "Tipo", 80), ("acao", "Ação", 340),
                        ("segurar", "Segurar (s)", 90), ("ativo", "Ativo", 60)]:
            self.tg.heading(c, text=t); self.tg.column(c, width=w, anchor="w")
        self.tg.pack(fill="both", expand=True)
        self.tg.bind("<Double-1>", lambda _: self.editar_gesto())

        # ---- aba AÇÕES
        fa = ttk.Frame(abas); abas.add(fa, text="  Ações  ")
        topo = ttk.Frame(fa, padding=6); topo.pack(fill="x")
        for txt, cmd in [("Gravar ação (macro)", self.gravar_macro), ("Nova tecla/comando", self.nova_acao),
                         ("Regravar macro", self.regravar_macro), ("Editar", self.editar_acao),
                         ("Executar para testar", self.testar_acao), ("Excluir", self.excluir_acao)]:
            ttk.Button(topo, text=txt, command=cmd).pack(side="left", padx=3)
        cols = ("nome", "tipo", "detalhe", "usada")
        self.ta = ttk.Treeview(fa, columns=cols, show="headings", selectmode="browse")
        for c, t, w in [("nome", "Ação", 280), ("tipo", "Tipo", 120), ("detalhe", "Detalhe", 330),
                        ("usada", "Usada pelos gestos", 220)]:
            self.ta.heading(c, text=t); self.ta.column(c, width=w, anchor="w")
        self.ta.pack(fill="both", expand=True)
        self.ta.bind("<Double-1>", lambda _: self.editar_acao())

        rodape = ttk.Frame(self, padding=(8, 0, 8, 8)); rodape.pack(fill="x")
        ttk.Label(rodape, foreground="#555", text="Cada gesto aponta para uma ação. Gestos gravados têm "
                  "prioridade sobre os nativos. Tudo é salvo na hora e o Ghost aplica sozinho.").pack(side="left")
        ttk.Button(rodape, text="Fechar", command=self.destroy).pack(side="right")
        self.atualizar()

    # ---------- utilidades
    def atualizar(self):
        self.tg.delete(*self.tg.get_children())
        for g in self.cad["gestos"]:
            a = gl.acao_por_id(self.cad, g.get("acao_id"))
            self.tg.insert("", "end", iid=g["id"], values=(
                g["nome"], "Nativo" if g.get("tipo") == "nativo" else "Gravado",
                a["nome"] if a else "(ação excluída)", g.get("segurar", 0), "Sim" if g.get("ativo", True) else "Não"))
        self.ta.delete(*self.ta.get_children())
        for a in self.cad["acoes"]:
            usada = ", ".join(g["nome"] for g in self.cad["gestos"] if g.get("acao_id") == a["id"])
            self.ta.insert("", "end", iid=a["id"], values=(
                a["nome"], gl.TIPOS_ACAO.get(a["tipo"], a["tipo"]), gl.descrever_acao(a), usada or "—"))

    def salvar(self):
        gl.salvar_cadastro(self.cad)
        self.atualizar()

    def _sel(self, tv, lista, msg):
        sel = tv.selection()
        if not sel:
            messagebox.showinfo("Cadastro", msg, parent=self); return None
        return next(x for x in lista if x["id"] == sel[0])

    def gesto_sel(self):
        return self._sel(self.tg, self.cad["gestos"], "Selecione um gesto na lista.")

    def acao_sel(self):
        return self._sel(self.ta, self.cad["acoes"], "Selecione uma ação na lista.")

    # ---------- GESTOS
    def _confirmar_conflitos(self, amostras, ignorar_id=None):
        avisos = conflitos(amostras, self.cad["gestos"], ignorar_id)
        pose = pose_nativa_das_amostras(amostras)
        if pose in ("mover", "pinca", "pinca_medio", "rolar"):
            avisos.append(f"- parece com a pose nativa \"{gl.POSES_NATIVAS[pose]}\", usada pelo mouse. "
                          "Como o gravado tem prioridade, o mouse deixaria de funcionar com essa pose.")
        if avisos:
            return messagebox.askyesno("Gesto parecido", "Atenção:\n" + "\n".join(avisos) +
                                       "\n\nSalvar mesmo assim?", parent=self)
        return True

    def novo_gesto(self):
        nome = simpledialog.askstring("Novo gesto", "Nome do gesto (ex.: Paz e amor):", parent=self)
        if not nome:
            return
        messagebox.showinfo("Gravação", f"Vai abrir a câmera. Faça o gesto \"{nome}\" após a contagem e segure "
                            f"por {SEGUNDOS_GRAVACAO:.0f} s.\nDica: mexa levemente a mão durante a gravação "
                            "para o Ghost aprender pequenas variações.", parent=self)
        amostras = gravar_amostras(self)
        if not amostras or not self._confirmar_conflitos(amostras):
            return
        ed = EditorGesto(self, self.cad, {"nome": nome, "tipo": "gravado", "acao_id": "nada", "segurar": 0.8},
                         novo=True)
        if ed.resultado:
            g = gl.novo_gravado(ed.resultado["nome"], ed.resultado["acao_id"], ed.resultado["segurar"], amostras)
            g["ativo"] = ed.resultado["ativo"]
            self.cad["gestos"].append(g)
            self.salvar()

    def regravar(self):
        g = self.gesto_sel()
        if not g:
            return
        if g.get("tipo") == "nativo":
            messagebox.showinfo("Regravar", "Gestos nativos não são gravados; troque a ação deles ou "
                                "desative-os e grave um gesto seu.", parent=self); return
        amostras = gravar_amostras(self)
        if not amostras or not self._confirmar_conflitos(amostras, g["id"]):
            return
        novo = gl.novo_gravado(g["nome"], g["acao_id"], g.get("segurar", 0.8), amostras)
        g["amostras"], g["limiar"] = novo["amostras"], novo["limiar"]
        self.salvar()

    def editar_gesto(self):
        g = self.gesto_sel()
        if g:
            ed = EditorGesto(self, self.cad, g)
            if ed.resultado:
                g.update(ed.resultado); self.salvar()

    def alternar(self):
        g = self.gesto_sel()
        if g:
            g["ativo"] = not g.get("ativo", True); self.salvar()

    def excluir_gesto(self):
        g = self.gesto_sel()
        if not g:
            return
        if g.get("tipo") == "nativo":
            messagebox.showinfo("Excluir", "Gestos nativos não podem ser excluídos, só desativados.", parent=self)
            return
        if messagebox.askyesno("Excluir", f"Excluir o gesto \"{g['nome']}\"?", parent=self):
            self.cad["gestos"].remove(g); self.salvar()

    def testar(self):
        testar(self, self.cad)

    def restaurar(self):
        if messagebox.askyesno("Restaurar", "Voltar os gestos NATIVOS ao padrão? Gestos gravados e ações são "
                               "mantidos.", parent=self):
            self.cad = gl.restaurar_nativos(self.cad); self.salvar()

    # ---------- AÇÕES
    def _gravar_passos(self):
        if not messagebox.askokcancel(
                "Gravar ação", "Esta janela vai minimizar e a gravação começa em 3 segundos.\n\n"
                "Faça no computador o que a ação deve repetir (teclas, cliques, rolagem).\n"
                "Pressione F10 para TERMINAR a gravação.", parent=self):
            return None
        self.iconify(); self.update()
        time.sleep(3)
        passos = macros.Gravador().gravar()
        self.deiconify(); self.lift(); self.focus_force()
        if not passos:
            messagebox.showwarning("Gravar ação", "Nada foi gravado.", parent=self); return None
        return passos

    def gravar_macro(self):
        nome = simpledialog.askstring("Gravar ação", "Nome da ação (ex.: Abrir relatório de produção):", parent=self)
        if not nome:
            return
        passos = self._gravar_passos()
        if not passos:
            return
        rapido = messagebox.askyesno("Ritmo", f"Gravado: {macros.resumo(passos)}.\n\nRepetir no modo RÁPIDO?\n"
                                     "(Não = mantém o tempo original entre os passos, mais seguro para "
                                     "programas que demoram a abrir.)", parent=self)
        self.cad["acoes"].append(gl.nova_acao(nome, "macro", passos=passos, ritmo="rapido" if rapido else "original"))
        self.salvar()
        messagebox.showinfo("Ação criada", f"Ação \"{nome}\" criada. Para usar, vá na aba Gestos, escolha um "
                            "gesto e troque a ação dele.", parent=self)

    def regravar_macro(self):
        a = self.acao_sel()
        if not a:
            return
        if a["tipo"] != "macro":
            messagebox.showinfo("Regravar", "Só ações do tipo macro são gravadas.", parent=self); return
        passos = self._gravar_passos()
        if passos:
            a["passos"] = passos; self.salvar()

    def nova_acao(self):
        ed = EditorAcao(self)
        if ed.resultado:
            r = ed.resultado
            self.cad["acoes"].append(gl.nova_acao(r["nome"], r["tipo"], r["valor"])); self.salvar()

    def editar_acao(self):
        a = self.acao_sel()
        if not a:
            return
        if a["tipo"] == "sistema":
            messagebox.showinfo("Editar", "Ações do sistema não são editáveis.", parent=self); return
        ed = EditorAcao(self, a)
        if ed.resultado:
            a.update(ed.resultado); self.salvar()

    def testar_acao(self):
        a = self.acao_sel()
        if not a:
            return
        if a["tipo"] not in ("macro", "tecla"):
            messagebox.showinfo("Testar", "Só dá para testar aqui macros e teclas. Comandos de voz e ações do "
                                "sistema são testados com o Ghost ligado.", parent=self); return
        if not messagebox.askokcancel("Testar", "A janela vai minimizar e a ação será executada em 3 segundos.",
                                      parent=self):
            return
        self.iconify(); self.update(); time.sleep(3)
        if a["tipo"] == "macro":
            macros.executar(a.get("passos", []), a.get("ritmo", "original"))
        else:
            pyautogui.hotkey(*a["valor"].split("+"))
        self.deiconify(); self.lift()

    def excluir_acao(self):
        a = self.acao_sel()
        if not a:
            return
        if a["tipo"] == "sistema":
            messagebox.showinfo("Excluir", "Ações do sistema não podem ser excluídas.", parent=self); return
        usados = [g for g in self.cad["gestos"] if g.get("acao_id") == a["id"]]
        aviso = (f"\n\nOs gestos {', '.join(g['nome'] for g in usados)} ficarão sem ação." if usados else "")
        if messagebox.askyesno("Excluir", f"Excluir a ação \"{a['nome']}\"?{aviso}", parent=self):
            for g in usados:
                g["acao_id"] = "nada"
            self.cad["acoes"].remove(a); self.salvar()


if __name__ == "__main__":
    App().mainloop()
