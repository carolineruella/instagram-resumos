#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Confere os carrosséis de carrosseis/*.json antes de colar no index.html."""
import glob, io, json, re, sys

CAMPOS_POST = ("user","av","avc","disp","time","likes","comments","cap","slides")
problemas = 0
# com --corrigir, ajusta o "N cards" da capa para o numero real em vez de reclamar
CORRIGIR = "--corrigir" in sys.argv

def erro(arq, msg):
    global problemas
    problemas += 1
    print("  ✗ %s: %s" % (arq, msg))

for arq in sorted(glob.glob("carrosseis/cap*.json")):
    d = json.load(io.open(arq, encoding="utf-8"))
    nome = arq.split("/")[-1]

    for c in CAMPOS_POST:
        if c not in d:
            erro(nome, "falta o campo '%s'" % c)

    slides = d.get("slides", [])
    if not slides or not slides[0].get("cover"):
        erro(nome, "primeiro slide nao e a capa")
    questoes = [s for s in slides if s.get("q")]
    cards = [s for s in slides if not s.get("cover") and not s.get("q")]

    if len(questoes) != 1:
        erro(nome, "tem %d questoes (esperado 1)" % len(questoes))

    # a capa precisa anunciar o numero real de cards
    n = slides[0].get("n", "")
    m = re.search(r"(\d+)\s*cards", n)
    if not m:
        erro(nome, "capa sem 'N cards' em n=%r" % n)
    elif int(m.group(1)) != len(cards):
        if CORRIGIR:
            slides[0]["n"] = re.sub(r"\d+\s*cards", "%d cards" % len(cards), n)
            io.open(arq, "w", encoding="utf-8", newline="\n").write(
                json.dumps(d, ensure_ascii=False, indent=2) + "\n")
            print("  ~ %s: capa corrigida para %d cards" % (nome, len(cards)))
        else:
            erro(nome, "capa diz %s cards, mas ha %d" % (m.group(1), len(cards)))

    for i, c in enumerate(cards, 1):
        for campo in ("k","h","p","src"):
            if not c.get(campo):
                erro(nome, "card %d sem '%s'" % (i, campo))
        p = c.get("p", "")
        nm = p.count("<mark>")
        if nm != 1 or p.count("</mark>") != nm:
            erro(nome, "card %d tem %d <mark> (esperado 1, bem fechado)" % (i, nm))
        if len(p) > 230:
            erro(nome, "card %d com corpo de %d chars (limite 230)" % (i, len(p)))
        if len(c.get("h","").split()) > 6:
            erro(nome, "card %d: frente com mais de 6 palavras" % i)

    for q in questoes:
        opts = q.get("opts", [])
        if len(opts) < 3:
            erro(nome, "questao com %d alternativas" % len(opts))
        if not all(isinstance(o, list) and len(o) == 2 for o in opts):
            erro(nome, "alternativa fora do formato [letra, texto]")
        cor = q.get("correct")
        if not isinstance(cor, int) or not (0 <= cor < len(opts)):
            erro(nome, "'correct'=%r fora da faixa 0..%d" % (cor, len(opts)-1))
        if not q.get("explain"):
            erro(nome, "questao sem 'explain'")
        if "<b>" not in q.get("explain",""):
            erro(nome, "explicacao sem <b> no ponto-chave")

    print("  %s  %2d cards + questao  (%s)" % (nome, len(cards), d.get("disp","?")))

print()
if problemas:
    print("%d problema(s) encontrado(s)." % problemas)
    sys.exit(1)
print("Tudo certo.")
