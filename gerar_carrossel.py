#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_carrossel.py
Gera um carrossel (post) para o app Instagram-Resumos a partir de um PDF,
usando IA para sintetizar cards de estudo + 1 questão comentada.

Saída: um objeto JS pronto pra colar no array `const posts = [ ... ]` do index.html
(e também um .json com o mesmo conteúdo).

------------------------------------------------------------------
INSTALAÇÃO (uma vez):
    pip install pypdf anthropic
    # (alternativa OpenAI) pip install pypdf openai

CHAVE DE API (uma vez, no terminal):
    Anthropic:  export ANTHROPIC_API_KEY="sua-chave"      (Windows: set ANTHROPIC_API_KEY=...)
    OpenAI:     export OPENAI_API_KEY="sua-chave"

USO:
    python gerar_carrossel.py artigo.pdf
    python gerar_carrossel.py artigo.pdf --cards 12 --provider anthropic
    python gerar_carrossel.py livro.pdf --pages 46-64 --titulo "Inércia"
    python gerar_carrossel.py artigo.pdf --provider openai --model gpt-4o-mini
    python gerar_carrossel.py artigo.pdf --model claude-opus-5

COMO USAR A SAÍDA:
    1) Abra o index.html no editor.
    2) Ache a linha `const posts=[`.
    3) Cole o objeto gerado (arquivo .js) como um novo item do array (separe com vírgula).
    4) Salve e faça o commit no GitHub.
------------------------------------------------------------------
"""

import argparse, json, os, re, sys, random

# paleta igual à do app (cor do avatar do post)
CORES = ["#0a84ff", "#ff375f", "#30d158", "#ff9f0a", "#5e5ce6", "#bf5af2", "#64d2ff"]

# ---------- Instrução para a IA ----------
SYSTEM = (
    "Você é um professor que cria material de estudo em formato de flashcards, "
    "em português do Brasil, a partir de um texto acadêmico. "
    "Seja fiel ao texto: NÃO invente fatos, dados, leis, autores ou citações. "
    "Use linguagem clara e direta. Cada card deve caber em uma tela de celular."
)

def prompt_usuario(titulo, texto, n_cards):
    return f"""A partir do texto abaixo (título: "{titulo}"), gere um carrossel de estudo.

Responda SOMENTE com um JSON válido (sem comentários, sem markdown), neste formato:

{{
  "titulo": "título curto do carrossel",
  "handle": "usuario_sem_espacos_minusculo",
  "legenda": "1 frase de legenda do post, com a referência do autor se houver",
  "cards": [
    {{
      "kicker": "rótulo curto (ex.: 'Definição', 'Mito 1', 'Conceito')",
      "frente": "título do card, no máximo 6 palavras",
      "corpo": "explicação em 1-2 frases (máx ~200 caracteres). Envolva 1 termo-chave em <mark>...</mark>",
      "fonte": "autor/ano ou lei/artigo de onde saiu"
    }}
  ],
  "questao": {{
    "enunciado": "pergunta de múltipla escolha sobre o conteúdo",
    "alternativas": ["texto A", "texto B", "texto C", "texto D"],
    "correta": 0,
    "explicacao": "por que a correta está certa (cite artigo/autor). Use <b>...</b> no ponto-chave."
  }}
}}

Regras:
- Gere exatamente {n_cards} cards (fora a questão).
- "corpo" curto: precisa caber na tela. Use no máximo um <mark>.
- "correta" é o índice (0 a 3) da alternativa certa.
- Nada de texto fora do JSON.

TEXTO:
\"\"\"{texto}\"\"\"
"""

# ---------- Extração de PDF ----------
def extrair_texto(caminho, paginas=None):
    """Extrai texto do PDF. `paginas` = (inicio, fim), 1-indexado e inclusivo."""
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("Falta a biblioteca pypdf. Rode:  pip install pypdf")
    reader = PdfReader(caminho)
    if paginas:
        ini, fim = paginas
        total = len(reader.pages)
        if ini < 1 or fim > total or ini > fim:
            sys.exit("Faixa de paginas invalida: %d-%d (o PDF tem %d paginas)." % (ini, fim, total))
        alvo = reader.pages[ini - 1:fim]
    else:
        alvo = reader.pages
    partes = []
    for pg in alvo:
        t = pg.extract_text() or ""
        partes.append(t)
    texto = "\n".join(partes)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    if len(texto) < 200:
        sys.exit("Quase nenhum texto extraído. O PDF pode ser digitalizado (imagem) e precisar de OCR.")
    return texto

# ---------- Chamadas de IA ----------
def chamar_anthropic(system, user, model):
    try:
        import anthropic
    except ImportError:
        sys.exit("Falta a biblioteca anthropic. Rode:  pip install anthropic")
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("Defina a variável ANTHROPIC_API_KEY com sua chave.")
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

def chamar_openai(system, user, model):
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("Falta a biblioteca openai. Rode:  pip install openai")
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("Defina a variável OPENAI_API_KEY com sua chave.")
    client = OpenAI()
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=0.3,
    )
    return resp.choices[0].message.content

# ---------- Utilidades ----------
def so_json(txt):
    """Extrai o primeiro bloco JSON da resposta da IA."""
    txt = txt.strip()
    txt = re.sub(r"^```(json)?", "", txt).strip()
    txt = re.sub(r"```$", "", txt).strip()
    i, j = txt.find("{"), txt.rfind("}")
    if i == -1 or j == -1:
        sys.exit("A IA não devolveu JSON. Resposta:\n" + txt[:500])
    return json.loads(txt[i:j+1])

def js_str(s):
    """String segura para JS (aspas duplas)."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip() + '"'

def montar_post(d, titulo_arquivo):
    titulo = d.get("titulo") or titulo_arquivo
    handle = re.sub(r"[^a-z0-9]+", ".", (d.get("handle") or titulo).lower()).strip(".")[:26] or "meu.resumo"
    cor = random.choice(CORES)
    cards = d.get("cards", [])
    q = d.get("questao", {})

    slides = [{
        "cover": True, "tag": "Carrossel de estudo",
        "h2": titulo, "n": f"{len(cards)} cards + questão"
    }]
    for c in cards:
        slides.append({
            "k": c.get("kicker", "Card"),
            "h": c.get("frente", ""),
            "p": c.get("corpo", ""),
            "src": c.get("fonte", titulo),
        })
    if q.get("enunciado"):
        letras = ["A", "B", "C", "D", "E"]
        opts = [[letras[i], alt] for i, alt in enumerate(q.get("alternativas", []))]
        slides.append({
            "q": True, "k": "Questão de revisão",
            "h": q.get("enunciado", ""),
            "opts": opts,
            "correct": int(q.get("correta", 0)),
            "explain": q.get("explicacao", ""),
        })

    return {
        "user": handle, "av": "📄", "avc": cor, "disp": titulo,
        "time": "agora", "likes": 0, "comments": 0,
        "cap": d.get("legenda", "Carrossel gerado do PDF."),
        "slides": slides,
    }

def post_para_js(post):
    """Converte o dict do post no mesmo estilo de objeto JS usado no app."""
    def slide_js(s):
        if s.get("cover"):
            return ("      {cover:true,tag:%s,h2:%s,n:%s}"
                    % (js_str(s["tag"]), js_str(s["h2"]), js_str(s["n"])))
        if s.get("q"):
            opts = "[" + ",".join("[%s,%s]" % (js_str(o[0]), js_str(o[1])) for o in s["opts"]) + "]"
            return ("      {q:true,k:%s,h:%s,\n        opts:%s,correct:%d,\n        explain:%s}"
                    % (js_str(s["k"]), js_str(s["h"]), opts, s["correct"], js_str(s["explain"])))
        return ("      {k:%s,h:%s,p:%s,src:%s}"
                % (js_str(s["k"]), js_str(s["h"]), js_str(s["p"]), js_str(s["src"])))
    slides = ",\n".join(slide_js(s) for s in post["slides"])
    return (
        "  {\n"
        "    user:%s, av:%s, avc:%s, disp:%s,\n"
        "    time:%s, likes:%d, comments:%d,\n"
        "    cap:%s,\n"
        "    slides:[\n%s\n    ]\n"
        "  }"
        % (js_str(post["user"]), js_str(post["av"]), js_str(post["avc"]), js_str(post["disp"]),
           js_str(post["time"]), post["likes"], post["comments"], js_str(post["cap"]), slides)
    )

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(description="Gera um carrossel do app a partir de um PDF, com IA.")
    ap.add_argument("pdf", help="caminho do arquivo PDF")
    ap.add_argument("--cards", type=int, default=10, help="quantos cards gerar (padrão 10)")
    ap.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    ap.add_argument("--model", default=None, help="modelo (padrão: opus-5 / gpt-4o-mini)")
    ap.add_argument("--out", default=None, help="prefixo dos arquivos de saída")
    ap.add_argument("--max-chars", type=int, default=45000, help="limite de texto enviado à IA")
    ap.add_argument("--pages", default=None,
                    help="faixa de páginas do PDF, ex.: 46-64 (padrão: todas)")
    ap.add_argument("--titulo", default=None,
                    help="título do carrossel (padrão: nome do arquivo)")
    args = ap.parse_args()

    if not os.path.exists(args.pdf):
        sys.exit("Arquivo não encontrado: " + args.pdf)

    paginas = None
    if args.pages:
        m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", args.pages)
        if not m:
            sys.exit("--pages precisa ter o formato INICIO-FIM, ex.: 46-64")
        paginas = (int(m.group(1)), int(m.group(2)))

    titulo_arquivo = args.titulo or re.sub(
        r"[_-]+", " ", os.path.splitext(os.path.basename(args.pdf))[0]).strip()
    print("→ Lendo PDF…")
    texto = extrair_texto(args.pdf, paginas)[: args.max_chars]

    model = args.model or ("claude-opus-5" if args.provider == "anthropic" else "gpt-4o-mini")
    print(f"→ Gerando cards com {args.provider} ({model})…")
    user = prompt_usuario(titulo_arquivo, texto, args.cards)
    resp = (chamar_anthropic(SYSTEM, user, model) if args.provider == "anthropic"
            else chamar_openai(SYSTEM, user, model))

    dados = so_json(resp)
    post = montar_post(dados, titulo_arquivo)

    prefixo = args.out or re.sub(r"[^\w]+", "_", titulo_arquivo).strip("_") or "carrossel"
    with open(prefixo + ".json", "w", encoding="utf-8") as f:
        json.dump(post, f, ensure_ascii=False, indent=2)
    js = post_para_js(post)
    with open(prefixo + ".js", "w", encoding="utf-8") as f:
        f.write(js + ",\n")

    print("\n===== COLE ISTO no array `const posts=[` do index.html =====\n")
    print(js + ",")
    print(f"\n✓ Também salvo em: {prefixo}.js  e  {prefixo}.json")
    print(f"✓ {len(post['slides'])-1} cards + questão gerados.")

if __name__ == "__main__":
    main()
