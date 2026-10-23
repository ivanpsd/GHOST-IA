"""
GHOST - Palavra de ativação "Ghost" treinada na SUA voz (openWakeWord + classificador local, grátis).

Por que: o Vosk usa um modelo genérico em inglês e só decide no FIM da frase.
Este detector reconhece "Ghost" no instante em que você fala (≈0,25 s) e erra menos,
porque aprendeu com a sua voz e com o barulho do seu ambiente.

Como aprende:
1. "Ghost, treinar ativação": você diz "Ghost" 8 vezes depois do bipe, fala algo
   qualquer por 20 s e fica 5 s em silêncio. Pronto: ele treina em segundos.
2. Depois, sozinho: cada "Ghost" confirmado vira exemplo positivo; cada alarme falso
   e cada frase sem "Ghost" vira negativo. A cada 15 exemplos novos, retreina.
Seus exemplos e o modelo ficam em dados/palavra/ (é a sua voz: fora do Git); os exemplos
gerais baixados ficam em modelos/palavra/. "Ghost, esquecer treino da ativação" apaga o que
é seu e volta para o Vosk.

Desempenho: os exemplos ficam em memória e são gravados em segundo plano (antes cada exemplo
relia e regravava dezenas de MB dentro da thread do microfone). Só um treino roda por vez, e o
retreino automático acontece no máximo a cada RETREINO_MIN_INTERVALO segundos.
"""
import os
import threading
import time

import numpy as np

from ghost.nucleo import caminhos

PASTA = caminhos.dado("palavra")
ARQ_POS, ARQ_NEG = os.path.join(PASTA, "positivos.npy"), os.path.join(PASTA, "negativos.npy")
ARQ_MODELO = os.path.join(PASTA, "classificador.joblib")
ARQ_GERAIS = caminhos.modelo("palavra", "negativos_gerais.npy")   # ~11 h de fala/ruído variados, 176 MB
URL_GERAIS = "https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/validation_set_features.npy"
N_GERAIS = 15000
TAXA = 16000
JANELA = 2 * TAXA               # 2 s de áudio por exemplo
QUADROS = 16                    # 16 vetores de 80 ms = 1,28 s analisados
LIMIAR_PADRAO = 0.85
LIMIAR_MINIMO = 0.85            # abaixo disso disparava com conversa comum (visto no uso real: 0,5 era baixo demais)
MAX_EXEMPLOS = 600
RETREINAR_A_CADA = 15
RETREINO_MIN_INTERVALO = 3600   # retreino automático: no máximo 1 por hora (cada treino leva ~1 min de CPU)
MIN_POS, MIN_NEG = 8, 40
SALVAR_APOS_S = 5               # exemplos novos são gravados em disco em lote, alguns segundos depois

versao = 0                      # muda a cada treino (o detector se recarrega)
LIMIAR = LIMIAR_PADRAO
_trava = threading.RLock()
_novos = 0
_modelo = None
_em_sessao = False              # treino guiado em andamento (não retreina sozinho no meio)
_treinando = threading.Lock()   # um treino por vez
_ultimo_treino = 0.0
_exemplos = None                # {"pos": [...], "neg": [...]} em memória
_salvar_timer = None


def _features_obj():
    import openwakeword
    from openwakeword.utils import AudioFeatures, download_models
    pasta_modelos = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
    mel, emb = os.path.join(pasta_modelos, "melspectrogram.onnx"), os.path.join(pasta_modelos, "embedding_model.onnx")
    if not (os.path.exists(mel) and os.path.exists(emb)):
        download_models(model_names=["__nenhum__"])
    return AudioFeatures(melspec_model_path=mel, embedding_model_path=emb, inference_framework="onnx")


def _carregar_modelo():
    global _modelo, LIMIAR
    import joblib
    if os.path.exists(ARQ_MODELO):
        d = joblib.load(ARQ_MODELO)
        _modelo, LIMIAR = d["clf"], max(d.get("limiar", LIMIAR_PADRAO), LIMIAR_MINIMO)
    return _modelo


def pronto():
    with _trava:
        try:
            return (_modelo or _carregar_modelo()) is not None
        except Exception as e:
            print(f"\n[PALAVRA]: modelo treinado inválido ({e}).")
            return False


# ---------------- detector em tempo real ----------------
def _resumo(x):
    """(N, 16, 96) -> média, máximo e final da janela. Testado: generaliza bem melhor que usar os 1536 números crus."""
    x = np.asarray(x, dtype=np.float32)
    return np.concatenate([x.mean(1), x.max(1), x[:, -4:].mean(1)], 1)


def _features_fluxo(f, clips):
    """Features calculadas do MESMO jeito que o detector em tempo real (em blocos de 0,25 s).
    Calcular em lote (embed_clips) dava números diferentes e o modelo errava ao vivo."""
    f.reset()
    saida = []
    for clip in clips:
        f(np.zeros(TAXA, np.int16))                # separa do clipe anterior
        for i in range(0, len(clip), 4000):
            f(np.asarray(clip[i:i + 4000], np.int16))
        saida.append(f.get_features(QUADROS)[0])
    return np.stack(saida)


def _inicios_de_fala(neg):
    """Cada frase "não Ghost" também é mostrada COMEÇANDO depois de um silêncio (de 0,25 s em 0,25 s de fala).
    Sem isso o detector aprendia "silêncio + começo de fala = Ghost" e disparava sempre que alguém falava."""
    saida = []
    for n in neg:
        n = np.asarray(n, np.int16)
        saida.append(n)
        x = np.concatenate([np.zeros(JANELA, np.int16), n])
        for seg in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75):
            fim = JANELA + int(seg * TAXA)
            saida.append(x[fim - JANELA:fim])
    return saida


def _negativos_gerais():
    """Janelas de fala/ruído de milhares de pessoas: ensinam o que NÃO é "Ghost"."""
    if not os.path.exists(ARQ_GERAIS):
        import shutil
        import urllib.request
        os.makedirs(os.path.dirname(ARQ_GERAIS), exist_ok=True)
        print("\n[PALAVRA]: baixando exemplos gerais de 'não é Ghost' (176 MB, só uma vez)...")
        tmp = ARQ_GERAIS + ".tmp"
        try:
            with urllib.request.urlopen(URL_GERAIS, timeout=60) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            os.replace(tmp, ARQ_GERAIS)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    a = np.load(ARQ_GERAIS, mmap_mode="r")
    ini = np.random.default_rng(0).integers(0, len(a) - QUADROS, N_GERAIS)
    return np.stack([a[i:i + QUADROS] for i in ini])


class Detector:
    def __init__(self):
        self.versao = versao
        self.f = _features_obj()
        self.clf = _modelo or _carregar_modelo()

    def processar(self, dados):
        """dados: bytes int16 16 kHz. Devolve a probabilidade de ter sido dito "Ghost" agora."""
        self.f(np.frombuffer(dados, dtype=np.int16))
        x = self.f.get_features(QUADROS)
        if x.shape[1] < QUADROS:
            return 0.0
        return float(self.clf.predict_proba(_resumo(x))[0, 1])


# ---------------- exemplos ----------------
def _ler(arq):
    try:
        return list(np.load(arq))
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"\n[PALAVRA]: {os.path.basename(arq)} ilegível ({e}); começando vazio.")
        return []


def _carregar_exemplos():
    global _exemplos
    if _exemplos is None:
        _exemplos = {"pos": _ler(ARQ_POS), "neg": _ler(ARQ_NEG)}
    return _exemplos


def _salvar_exemplos():
    with _trava:
        ex = _carregar_exemplos()
        copia = {k: list(v) for k, v in ex.items()}
    os.makedirs(PASTA, exist_ok=True)
    for chave, arq in (("pos", ARQ_POS), ("neg", ARQ_NEG)):
        if copia[chave]:
            tmp = arq + ".tmp.npy"
            np.save(tmp, np.stack(copia[chave]))
            os.replace(tmp, arq)


def _agendar_salvamento():
    global _salvar_timer
    if _salvar_timer is None or not _salvar_timer.is_alive():
        def _rodar():
            try:
                _salvar_exemplos()
            except Exception as e:
                print(f"\n[PALAVRA]: não consegui gravar os exemplos ({e}).")
        _salvar_timer = threading.Timer(SALVAR_APOS_S, _rodar)
        _salvar_timer.daemon = True
        _salvar_timer.start()


def _ajustar(pcm):
    a = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16) if isinstance(pcm, (bytes, bytearray)) else np.asarray(pcm, np.int16)
    if len(a) >= JANELA:
        return a[-JANELA:].copy()
    return np.concatenate([np.zeros(JANELA - len(a), np.int16), a])


def recortar_palavra(pcm):
    """Do áudio de "Ghost, ..." devolve 2 s terminando logo depois da 1ª palavra."""
    a = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32)
    q = 320                                                     # 20 ms
    n = len(a) // q
    if n < 5:
        return _ajustar(pcm)
    energia = np.sqrt(np.mean(a[: n * q].reshape(n, q) ** 2, axis=1))
    limiar = max(np.percentile(energia, 20) * 3, 300)
    voz = np.where(energia > limiar)[0]
    if not voz.size:
        return _ajustar(pcm)
    fim = voz[0]
    silencio = 0
    for i in range(voz[0], min(n, voz[0] + 45)):                # no máximo 0,9 s de palavra
        if energia[i] > limiar:
            fim, silencio = i, 0
        else:
            silencio += 1
            if silencio >= 8:                                   # 160 ms de pausa: acabou a palavra
                break
    corte = min(len(a), (fim + 1) * q + int(0.2 * TAXA))
    return _ajustar(a[:corte].astype(np.int16))


def registrar(pcm, positivo, recortar=True):
    """Guarda um exemplo (positivo = era você dizendo "Ghost"). Rápido: só mexe na memória."""
    global _novos
    clip = recortar_palavra(pcm) if (positivo and recortar) else _ajustar(pcm)
    with _trava:
        ex = _carregar_exemplos()
        lista = ex["pos" if positivo else "neg"]
        lista.append(clip)
        del lista[:-MAX_EXEMPLOS]
        _novos += 1
        retreinar = (not _em_sessao and _novos >= RETREINAR_A_CADA and len(ex["pos"]) >= MIN_POS
                     and time.time() - _ultimo_treino > RETREINO_MIN_INTERVALO and not _treinando.locked())
        if retreinar:
            _novos = 0
    _agendar_salvamento()
    if retreinar:
        threading.Thread(target=treinar, daemon=True).start()


def quantidade():
    with _trava:
        ex = _carregar_exemplos()
        return len(ex["pos"]), len(ex["neg"])


# ---------------- treino ----------------
def _aumentar(pos, neg, rng):
    """Variações dos positivos: volume, deslocamento e ruído de fundo do seu ambiente."""
    saida = []
    for p in pos:
        saida.append(p)
        for _ in range(5):
            x = p.astype(np.float32) * rng.uniform(0.5, 1.6)
            x = np.roll(x, -int(rng.uniform(0, 0.25) * TAXA))
            if len(neg):
                x += neg[rng.integers(len(neg))].astype(np.float32) * rng.uniform(0.0, 0.4)
            saida.append(np.clip(x, -32768, 32767).astype(np.int16))
    return saida


def treinar():
    """Treina o classificador com os exemplos guardados. Devolve uma frase com o resultado."""
    if not _treinando.acquire(blocking=False):
        return "Já estou treinando, senhor. Um instante."
    try:
        return _treinar()
    finally:
        _treinando.release()


def _treinar():
    global _modelo, versao, LIMIAR, _ultimo_treino
    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    _ultimo_treino = time.time()
    with _trava:
        ex = _carregar_exemplos()
        pos, neg = list(ex["pos"]), list(ex["neg"])
        versao_inicio = versao
    if len(pos) < MIN_POS or len(neg) < MIN_NEG:
        return f"Ainda faltam exemplos: tenho {len(pos)} de {MIN_POS} da palavra e {len(neg)} de {MIN_NEG} de outros sons."
    rng = np.random.default_rng(7)
    pos_aum = _aumentar(pos, neg, rng)
    f = _features_obj()
    xp = _resumo(_features_fluxo(f, pos_aum))
    xn = _resumo(_features_fluxo(f, _inicios_de_fala(neg)))
    try:
        xg = _resumo(_negativos_gerais())
    except Exception as e:
        print(f"\n[PALAVRA]: sem os exemplos gerais ({e}); treinando só com os seus.")
        xg = np.zeros((0, xp.shape[1]), np.float32)
    x = np.vstack([xp, xn, xg]); y = np.r_[np.ones(len(xp)), np.zeros(len(xn) + len(xg))]
    clf = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, class_weight="balanced", max_iter=4000)).fit(x, y)
    # limiar: deixa passar no máximo 0,5% dos negativos (os seus + uma parte dos gerais)
    pn = np.sort(clf.predict_proba(np.vstack([xn, xg[:2000]]))[:, 1])
    limiar = float(max(LIMIAR_MINIMO, min(0.995, pn[int(len(pn) * 0.995)] + 0.02)))
    acerto = float((clf.predict_proba(xp[:: 6])[:, 1] >= limiar).mean())   # só os originais
    with _trava:
        if versao != versao_inicio:            # "esquecer" ou outro treino aconteceu no meio: descarta
            return "Treino descartado: os exemplos mudaram durante o treino."
        os.makedirs(PASTA, exist_ok=True)
        tmp = ARQ_MODELO + ".tmp"
        joblib.dump({"clf": clf, "limiar": limiar, "data": time.time()}, tmp)
        os.replace(tmp, ARQ_MODELO)
        _modelo, LIMIAR = clf, limiar
        versao += 1
    print(f"\n[PALAVRA]: treinado com {len(pos)} positivos e {len(neg)} negativos; "
          f"acerto {acerto:.0%}, limiar {limiar:.2f}.")
    return f"Treino concluído, senhor: reconheci {acerto:.0%} das vezes em que o senhor disse Ghost."


def esquecer():
    global _modelo, versao, _exemplos, _novos
    with _trava:
        if _salvar_timer is not None:
            _salvar_timer.cancel()
        for a in (ARQ_POS, ARQ_NEG, ARQ_MODELO):
            if os.path.exists(a):
                os.remove(a)
        _modelo, _exemplos, _novos = None, {"pos": [], "neg": []}, 0
        versao += 1


def _bipe():
    from ghost.voz import som
    t = np.arange(int(0.15 * 24000)) / 24000
    som.tocar((0.15 * np.sin(2 * np.pi * 880 * t)).astype(np.float32), 24000)


def treinar_interativo(falar):
    """Sessão guiada de ~1 minuto. Roda em segundo plano."""
    global _em_sessao, _novos
    from ghost.voz import ativacao

    def dizer(texto):
        """Fala e só volta quando a frase TERMINOU (esperar o início também: a voz demora a ser gerada,
        e sem isso a instrução tocava por cima da gravação e virava exemplo de treino)."""
        falar(texto)
        falando = ativacao._falando or (lambda: False)
        limite = time.time() + 8
        while not falando() and time.time() < limite:
            time.sleep(0.05)
        while falando():
            time.sleep(0.1)
        time.sleep(0.3)

    def gravar(seg):
        fim = time.time() + seg
        return ativacao.gravar_enquanto(lambda: time.time() < fim, maximo=seg + 1)

    if _treinando.locked():
        falar("Senhor, já há um treino em andamento.")
        return
    ativacao.pausar()
    _em_sessao = True
    try:
        dizer("Vou aprender como o senhor diz Ghost. Depois de cada bipe, diga apenas: Ghost. Serão oito vezes.")
        boas = 0
        for _ in range(8):
            _bipe()
            pcm = gravar(2.0)
            if ativacao._volume_fala(pcm) > 0:
                registrar(pcm, True)
                boas += 1
            time.sleep(0.3)
        dizer("Ótimo. Agora fale qualquer coisa, sem dizer Ghost, por vinte segundos. Pode ler algo em voz alta.")
        _bipe()
        fala = gravar(20.0)
        dizer("Agora fique em silêncio por cinco segundos.")
        silencio = gravar(5.0)
        for pcm, passo in ((fala, TAXA // 2), (silencio, TAXA)):
            a = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16)
            for ini in range(0, max(0, len(a) - JANELA), passo):
                registrar(a[ini:ini + JANELA].tobytes(), False)
        if boas < 5:
            dizer("Senhor, ouvi pouco a palavra. Fale mais perto do microfone e tente de novo.")
            return
        dizer("Treinando, um instante.")
        dizer(treinar())
    except Exception as e:
        print(f"\n[PALAVRA]: erro no treino ({e!r}).")
        falar("Senhor, deu erro no treino da ativação. Detalhes no log.")
    finally:
        _em_sessao, _novos = False, 0
        ativacao.retomar()
