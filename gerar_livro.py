#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_livro.py
Gera um carrossel por capítulo de um livro em PDF, usando o índice (bookmarks)
do próprio PDF para descobrir os capítulos e suas páginas.

Reaproveita as funções do gerar_carrossel.py.

USO:
    python gerar_livro.py "material/Fisica Conceitual - Paul Hewitt.pdf" --ate 18
    python gerar_livro.py livro.pdf --de 5 --ate 8 --cards 8
    python gerar_livro.py livro.pdf --ate 18 --listar    (só mostra os capítulos)

É RETOMÁVEL: capítulos que já têm .json em carrosseis/ são pulados, então
reexecutar depois de uma falha não gasta chamadas de API de novo.

Saída em carrosseis/:
    cap01.json ... capNN.json   (um por capítulo)
    todos.js                    (todos os posts, pronto pra colar no index.html)
"""

import argparse, io, json, os, re, sys, time

import gerar_carrossel as gc

MODELO = "claude-opus-5"
SAIDA = "carrosseis"


# ---------- Descobrir capítulos pelo índice do PDF ----------
def listar_capitulos(caminho_pdf):
    """Devolve [(numero, titulo, pag_inicial, pag_final)] lendo os bookmarks."""
    from pypdf import PdfReader

    reader = PdfReader(caminho_pdf)
    total = len(reader.pages)

    # achata o índice em ordem de documento: [(pagina, titulo)]
    plano = []

    def caminhar(itens):
        for it in itens:
            if isinstance(it, list):
                caminhar(it)
            else:
                try:
                    plano.append((reader.get_destination_page_number(it) + 1, it.title))
                except Exception:
                    pass

    caminhar(reader.outline)
    plano.sort(key=lambda x: x[0])

    caps = []
    for i, (pag, titulo) in enumerate(plano):
        m = re.match(r"\s*Cap[íi]tulo\s+(\d+)\s*[-–—]\s*(.+)", titulo)
        if not m:
            continue
        # o capítulo termina uma página antes do próximo item do índice
        fim = total
        for pag_seg, _ in plano[i + 1:]:
            if pag_seg > pag:
                fim = pag_seg - 1
                break
        caps.append((int(m.group(1)), m.group(2).strip(), pag, fim))

    caps.sort(key=lambda c: c[0])
    return caps


# ---------- Chamada à IA (com retry e contagem de tokens) ----------
def gerar_um(client, titulo, texto, n_cards):
    """Devolve (dict_do_post, tokens_entrada, tokens_saida)."""
    user = gc.prompt_usuario(titulo, texto, n_cards)
    ultimo_erro = None

    for tentativa in range(1, 4):
        try:
            with client.messages.stream(
                model=MODELO,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=gc.SYSTEM,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                resp = stream.get_final_message()

            if resp.stop_reason == "max_tokens":
                raise ValueError("resposta truncada no limite de tokens")

            txt = "".join(b.text for b in resp.content if b.type == "text")
            dados = json.loads(_recortar_json(txt))
            return dados, resp.usage.input_tokens, resp.usage.output_tokens

        except Exception as e:
            # erros de credencial/pedido malformado nao melhoram com retry
            if type(e).__name__ in ("AuthenticationError", "PermissionDeniedError",
                                    "BadRequestError", "NotFoundError"):
                raise
            ultimo_erro = e
            if tentativa < 3:
                espera = 5 * tentativa
                print(f"     ! {type(e).__name__}: {e} — tentando de novo em {espera}s")
                time.sleep(espera)

    raise RuntimeError(f"falhou após 3 tentativas: {ultimo_erro}")


def _recortar_json(txt):
    """Igual ao so_json do gerar_carrossel, mas sem sys.exit — deixa o retry agir."""
    txt = txt.strip()
    txt = re.sub(r"^```(json)?", "", txt).strip()
    txt = re.sub(r"```$", "", txt).strip()
    i, j = txt.find("{"), txt.rfind("}")
    if i == -1 or j == -1:
        raise ValueError("a IA não devolveu JSON: " + txt[:200])
    return txt[i:j + 1]


# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(description="Gera um carrossel por capítulo de um livro PDF.")
    ap.add_argument("pdf")
    ap.add_argument("--de", type=int, default=1, help="primeiro capítulo (padrão 1)")
    ap.add_argument("--ate", type=int, required=False, help="último capítulo")
    ap.add_argument("--cards", type=int, default=10, help="cards por carrossel (padrão 10)")
    ap.add_argument("--max-chars", type=int, default=120000, help="limite de texto por capítulo")
    ap.add_argument("--listar", action="store_true", help="só listar os capítulos e sair")
    ap.add_argument("--refazer", action="store_true", help="regerar mesmo se o .json já existir")
    args = ap.parse_args()

    if not os.path.exists(args.pdf):
        sys.exit("Arquivo não encontrado: " + args.pdf)

    caps = listar_capitulos(args.pdf)
    if not caps:
        sys.exit("Não achei capítulos no índice do PDF.")

    if args.listar:
        for n, t, ini, fim in caps:
            print(f"  cap {n:2d}  p.{ini}-{fim}  ({fim - ini + 1} pág.)  {t}")
        print(f"\n{len(caps)} capítulos encontrados.")
        return

    ate = args.ate or len(caps)
    alvo = [c for c in caps if args.de <= c[0] <= ate]
    if not alvo:
        sys.exit(f"Nenhum capítulo entre {args.de} e {ate}.")

    os.makedirs(SAIDA, exist_ok=True)

    import anthropic
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("Defina ANTHROPIC_API_KEY.")
    client = anthropic.Anthropic()

    print(f"→ {len(alvo)} capítulos, {args.cards} cards cada, modelo {MODELO}\n")
    tot_in = tot_out = 0
    falhas = []

    for n, titulo, ini, fim in alvo:
        destino = os.path.join(SAIDA, f"cap{n:02d}.json")
        if os.path.exists(destino) and not args.refazer:
            print(f"  cap {n:2d}  {titulo[:45]:45s}  já existe, pulando")
            continue

        texto = gc.extrair_texto(args.pdf, (ini, fim))[: args.max_chars]
        print(f"  cap {n:2d}  {titulo[:45]:45s}  p.{ini}-{fim}  {len(texto)} chars", flush=True)

        try:
            dados, t_in, t_out = gerar_um(client, f"{titulo} (Hewitt, Física Conceitual)",
                                          texto, args.cards)
        except Exception as e:
            print(f"     ✗ FALHOU: {e}")
            falhas.append(n)
            continue

        post = gc.montar_post(dados, titulo)
        post["disp"] = f"Cap. {n} — {titulo}"
        with io.open(destino, "w", encoding="utf-8") as f:
            json.dump(post, f, ensure_ascii=False, indent=2)

        tot_in += t_in
        tot_out += t_out
        print(f"     ✓ {len(post['slides']) - 1} cards + questão   "
              f"({t_in} tok entrada, {t_out} saída)")

    # monta o .js final com tudo que existe no diretório
    postagens = []
    for n, titulo, ini, fim in caps:
        caminho = os.path.join(SAIDA, f"cap{n:02d}.json")
        if os.path.exists(caminho):
            postagens.append(json.load(io.open(caminho, encoding="utf-8")))

    js = ",\n".join(gc.post_para_js(p) for p in postagens)
    with io.open(os.path.join(SAIDA, "todos.js"), "w", encoding="utf-8") as f:
        f.write(js + ",\n")

    custo = tot_in / 1e6 * 5 + tot_out / 1e6 * 25
    print(f"\n✓ {len(postagens)} carrosséis em {SAIDA}/todos.js")
    print(f"  tokens desta rodada: {tot_in} entrada + {tot_out} saída  ≈ US$ {custo:.2f}")
    if falhas:
        print(f"  ✗ falharam: {falhas} — rode de novo para tentar só esses")


if __name__ == "__main__":
    main()
