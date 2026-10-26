"""
GHOST - Trava contra a IA "em loop" na fala.

Já aconteceu: o modelo devolveu a mesma pergunta 6 vezes com reticências no meio e o Ghost falou tudo.
Para cada resposta, o filtro deixa passar no máximo `max_frases`, descarta frases repetidas ou quase iguais
e só uma pergunta.
"""
import difflib
import re
import unicodedata


def _normalizar(texto):
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()


class FiltroFala:
    def __init__(self, max_frases=8, parecido=0.8):
        self.max_frases, self.parecido = max_frases, parecido
        self.ditas, self.perguntou = [], False

    def aceitar(self, frase):
        """Frase limpa para falar, ou None para pular."""
        frase = re.sub(r"(?:\.\s*){2,}|…+", ". ", frase or "").strip()
        frase = re.sub(r"([?!])[\s.]+$", r"\1", frase)          # "senhor?....." -> "senhor?"
        chave = _normalizar(frase)
        if not chave or len(self.ditas) >= self.max_frases:
            return None
        if any(chave == d or difflib.SequenceMatcher(None, chave, d).ratio() > self.parecido for d in self.ditas):
            return None
        if "?" in frase:
            if self.perguntou:
                return None
            self.perguntou = True
        self.ditas.append(chave)
        return frase
