"""
GHOST - Visão sob demanda: "o que é isso na minha mão?", "o que você está vendo?"

Só olha quando você pede (a IA chama a ferramenta olhar_camera):
1. Tira UMA foto da câmera (nada é salvo em disco).
2. Envia ao Gemini (visão) para descrever o objeto, em até 2 frases.
3. Se o Gemini falhar, usa um detector LOCAL (MediaPipe, 80 tipos de objetos comuns).
Não identifica pessoas.
"""
import os
import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

import camera
import gestos_lib as gl

# tentados em ordem: se um estiver sobrecarregado (503), passa para o próximo
MODELOS_GEMINI = ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"]
URL_DETECTOR = ("https://storage.googleapis.com/mediapipe-models/object_detector/"
                "efficientdet_lite0/float16/latest/efficientdet_lite0.tflite")
CONFIANCA_LOCAL = 0.5

PROMPT = ("Você é a visão de um assistente de voz. O usuário perguntou: \"{pergunta}\". "
          "Olhe a foto da webcam e responda em português do Brasil, em no máximo 2 frases curtas, "
          "dizendo qual é o objeto (o que ele está segurando ou mostrando, se houver) e um detalhe útil "
          "(cor, marca visível, estado). Se não der para ver bem, diga o que dá para ver e peça para aproximar. "
          "Não identifique nem descreva pessoas.")

# nomes do detector local (em inglês) -> português
NOMES = {"mouse": "mouse", "keyboard": "teclado", "cell phone": "celular", "laptop": "notebook", "tv": "monitor",
         "remote": "controle remoto", "cup": "copo", "bottle": "garrafa", "book": "livro", "scissors": "tesoura",
         "person": "pessoa", "chair": "cadeira", "clock": "relógio", "backpack": "mochila", "handbag": "bolsa",
         "spoon": "colher", "fork": "garfo", "knife": "faca", "banana": "banana", "apple": "maçã",
         "orange": "laranja", "toothbrush": "escova de dentes", "wine glass": "taça", "bowl": "tigela",
         "umbrella": "guarda-chuva", "teddy bear": "urso de pelúcia", "vase": "vaso", "potted plant": "planta"}

_detector = None
_gemini = None


def capturar_quadro():
    """Uma foto da câmera compartilhada (liga a câmera só pelo tempo da foto, se estiver desligada)."""
    camera.iniciar("visao")
    try:
        ultimo, frame = 0, None
        fim = time.time() + 4
        for _ in range(6):  # descarta os primeiros quadros (exposição ainda ajustando)
            ultimo, f = camera.ler(ultimo, timeout=1.5)
            if f is not None:
                frame = f
            if time.time() > fim:
                break
        return None if frame is None else frame.copy()
    finally:
        camera.parar("visao")


def _detector_local():
    global _detector
    if _detector is None:
        opcoes = vision.ObjectDetectorOptions(
            base_options=mp_python.BaseOptions(model_asset_path=gl.garantir_modelo("efficientdet_lite0.tflite", URL_DETECTOR)),
            max_results=5, score_threshold=CONFIANCA_LOCAL)
        _detector = vision.ObjectDetector.create_from_options(opcoes)
    return _detector


def detectar_local(frame):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    res = _detector_local().detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    vistos = []
    for d in res.detections:
        c = d.categories[0]
        if c.category_name != "person":
            vistos.append(f"{NOMES.get(c.category_name, c.category_name)} ({c.score:.0%})")
    return vistos


def descrever_gemini(frame, pergunta):
    global _gemini
    from google import genai
    from google.genai import types
    if _gemini is None:
        _gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"), http_options={"timeout": 30000, "retry_options": {"attempts": 1}})
    ok, jpg = cv2.imencode(".jpg", cv2.resize(frame, (640, 480)), [cv2.IMWRITE_JPEG_QUALITY, 85])
    ultimo_erro = None
    for modelo in MODELOS_GEMINI:
        try:
            r = _gemini.models.generate_content(
                model=modelo,
                contents=[types.Part.from_bytes(data=jpg.tobytes(), mime_type="image/jpeg"),
                          PROMPT.format(pergunta=pergunta)],
                config={"temperature": 0.2, "max_output_tokens": 4096})
            if (r.text or "").strip():
                return r.text.strip()
        except Exception as e:
            ultimo_erro = e
            print(f"\n[VISÃO]: {modelo} indisponível ({str(e)[:60]}). Tentando o próximo...")
    raise RuntimeError(ultimo_erro or "sem resposta")


def olhar(pergunta="o que é isso?"):
    """Retorna a resposta em texto para o Ghost falar."""
    frame = capturar_quadro()
    if frame is None:
        return "Senhor, não consegui acessar a câmera agora."
    try:
        texto = descrever_gemini(frame, pergunta)
        if texto:
            return texto
    except Exception as e:
        print(f"\n[VISÃO]: Gemini indisponível ({e}). Usando o detector local.")
    vistos = detectar_local(frame)
    if vistos:
        return "Pelo que vejo: " + ", ".join(vistos) + "."
    return "Senhor, não reconheci o objeto. Tente aproximá-lo da câmera, com boa luz."
