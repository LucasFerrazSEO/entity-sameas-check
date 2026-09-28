#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
entity-sameas-check — auditoria do sameAs das entidades (Organization e Person)
declaradas em JSON-LD, com conferência cruzada no Wikidata.

O QUE FAZ
    Recebe uma ou mais URLs (ou arquivos HTML locais), extrai todos os blocos
    <script type="application/ld+json"> (inclusive @graph e arrays) e encontra
    os nós de organização (Organization, LocalBusiness, ProfessionalService,
    Corporation e subtipos comuns) e de pessoa (Person). Para cada nó:

    - lista o sameAs e aponta URL duplicada, http em vez de https, URL com
      parâmetro de rastreio (utm_, fbclid, gclid...) e URL malformada;
    - confere se cada URL do sameAs responde (HEAD, com GET de reserva; segue
      redirecionamento) e classifica: OK, redireciona, não verificável por bot
      (999/401/403/429 persistente, típico de LinkedIn, Instagram, Facebook e
      X), erro 4xx, erro 5xx, timeout, sem conexão;
    - para sameAs do Wikidata (wikidata.org/wiki/Q...), consulta a API pública
      (wbgetentities) e confere: se o item existe, foi apagado ou redirecionado;
      se o rótulo (pt/en) ou um apelido bate com o name do nó (normalizado);
      se a P856 (site oficial) aponta para o domínio do site; e quais outros
      perfis do sameAs o item lista nas propriedades de identificador externo
      (reciprocidade parcial, por um mapa pequeno domínio -> propriedade);
    - com várias URLs, confere a consistência entre páginas: o mesmo @id com
      name ou url diferente, e o mesmo name publicado com @id diferente.

MÉTODO
    Nasceu da manutenção da entidade (Organization e Person) de
    lucasferrazseo.com e lucasferraz.com, inclusive do caso real de um item de
    Wikidata apagado que continuava listado no sameAs sem ninguém perceber.
    Generalizado para uso público, sem regra específica de site ou CMS.

USO
    python entity_sameas_check.py https://example.com/
    python entity_sameas_check.py pagina.html
    python entity_sameas_check.py --urls https://example.com/ https://example.com/sobre/
    python entity_sameas_check.py https://example.com/ --json relatorio.json
    python entity_sameas_check.py pagina.html --offline      # só checagens estruturais
    python entity_sameas_check.py https://example.com/ --strict   # saída 1 se houver ATENÇÃO/FAIL

LIMITAÇÕES
    Não executa JavaScript: JSON-LD injetado no navegador não aparece. Perfis
    de rede social costumam bloquear robôs, então "não verificável" não é erro,
    é pedido de conferência manual. A reciprocidade no Wikidata é parcial:
    cobre só as propriedades do mapa interno. Nada aqui garante Painel de
    Conhecimento, posição no Google ou citação por IA.

Autor: Lucas Ferraz (lucasferraz.com). Dependência: requests (ver requirements.txt).
Licença: MIT.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from urllib.parse import parse_qsl, urlparse

try:
    import requests
except ImportError:  # pragma: no cover
    print("Falta a biblioteca requests. Rode: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(2)

NOME = "entity-sameas-check"
UA = f"{NOME}/1.0 (+https://github.com/LucasFerrazSEO/{NOME})"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

TIPOS_ORG = {
    "Organization", "LocalBusiness", "ProfessionalService", "Corporation", "NGO",
    "OnlineBusiness", "OnlineStore", "NewsMediaOrganization", "EducationalOrganization",
    "MedicalOrganization", "GovernmentOrganization", "SportsOrganization", "Airline",
    "Consortium", "PerformingGroup", "ResearchOrganization", "WorkersUnion", "Store",
    "Restaurant", "FoodEstablishment", "LegalService", "Attorney", "AccountingService",
    "FinancialService", "HomeAndConstructionBusiness", "AutomotiveBusiness",
    "HealthAndBeautyBusiness", "RealEstateAgent", "MedicalBusiness", "MedicalClinic",
    "Dentist", "Physician", "Hospital", "LodgingBusiness", "TravelAgency",
    "EmploymentAgency", "EntertainmentBusiness", "SportsActivityLocation",
}
TIPOS_PESSOA = {"Person", "Patient"}

PARAMS_RASTREIO = re.compile(
    r"^(utm_[a-z]+|fbclid|gclid|gbraid|wbraid|msclkid|dclid|igshid|igsh|mc_cid|mc_eid|"
    r"_hsenc|_hsmi|yclid|twclid|ttclid|li_fat_id|si|ref_src|ref)$",
    re.I,
)

# Domínios que costumam recusar robôs: 401/403/429/999 viram "não verificável".
BLOQUEIAM_BOT = (
    "linkedin.com", "instagram.com", "facebook.com", "fb.com", "x.com",
    "twitter.com", "tiktok.com", "threads.net", "pinterest.com", "medium.com",
)

# Mapa pequeno domínio -> propriedade de identificador externo no Wikidata.
PROP_NOMES = {
    "P2002": "X/Twitter", "P2013": "Facebook", "P4264": "LinkedIn (empresa)",
    "P6634": "LinkedIn (pessoa)", "P2003": "Instagram", "P2397": "YouTube (canal)",
    "P11245": "YouTube (handle)", "P2037": "GitHub", "P856": "site oficial",
}

ORDEM_NIVEL = {"OK": 0, "INFO": 1, "ATENÇÃO": 2, "FAIL": 3}


# --------------------------------------------------------------------------- rede
class Rede:
    """Sessão HTTP educada: User-Agent identificável, intervalo e 429 tratado."""

    def __init__(self, delay: float, timeout: float, offline: bool = False):
        self.delay = max(0.0, delay)
        self.timeout = timeout
        self.offline = offline
        self.sessao = requests.Session()
        self.sessao.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
        self._ultima = 0.0
        self.requisicoes = 0

    def _espera(self) -> None:
        falta = self.delay - (time.monotonic() - self._ultima)
        if falta > 0:
            time.sleep(falta)
        self._ultima = time.monotonic()

    def pede(self, metodo: str, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        for tentativa in range(2):
            self._espera()
            self.requisicoes += 1
            resp = self.sessao.request(metodo, url, **kw)
            if resp.status_code == 429 and tentativa == 0:
                espera = resp.headers.get("Retry-After", "")
                segundos = int(espera) if espera.isdigit() else 10
                time.sleep(min(max(segundos, 1), 30))
                continue
            return resp
        return resp


# ------------------------------------------------------------------- utilidades
def normaliza_nome(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^0-9a-z]+", " ", texto).split())


def host_base(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for prefixo in ("www.", "m.", "mobile."):
        if host.startswith(prefixo):
            host = host[len(prefixo):]
    return host


def mesmo_dominio(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def chave_url(url: str) -> str:
    """Forma comparável de uma URL (esquema e barra final ignorados)."""
    p = urlparse(url.strip())
    return f"{host_base(url)}{p.path.rstrip('/')}".casefold() + (f"?{p.query}" if p.query else "")


def como_lista(valor) -> list:
    if valor is None:
        return []
    return valor if isinstance(valor, list) else [valor]


def tipos_do_no(no: dict) -> list[str]:
    tipos = []
    for t in como_lista(no.get("@type")):
        if isinstance(t, str):
            tipos.append(t.rsplit("/", 1)[-1].rsplit(":", 1)[-1])
    return tipos


def texto_de(valor) -> str:
    if isinstance(valor, list):
        valor = valor[0] if valor else ""
    if isinstance(valor, dict):
        valor = valor.get("@value") or valor.get("@id") or ""
    return str(valor).strip() if valor else ""


def dominio_bloqueia(url: str) -> bool:
    return any(mesmo_dominio(host_base(url), d) for d in BLOQUEIAM_BOT)


# ------------------------------------------------------------- leitura JSON-LD
RE_SCRIPT = re.compile(
    r"<script\b[^>]*type\s*=\s*[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script>",
    re.I | re.S,
)


def extrai_blocos(html: str) -> tuple[list, list[str]]:
    blocos, erros = [], []
    for i, m in enumerate(RE_SCRIPT.finditer(html), 1):
        bruto = m.group(1).strip()
        bruto = re.sub(r"^\s*(<!--|<!\[CDATA\[)", "", bruto)
        bruto = re.sub(r"(-->|\]\]>)\s*$", "", bruto).strip()
        if not bruto:
            continue
        try:
            blocos.append(json.loads(bruto))
        except json.JSONDecodeError as exc:
            erros.append(f"bloco JSON-LD {i} inválido: {exc.msg} (linha {exc.lineno})")
    return blocos, erros


def percorre(valor, saida: list) -> None:
    if isinstance(valor, list):
        for item in valor:
            percorre(item, saida)
    elif isinstance(valor, dict):
        tipos = tipos_do_no(valor)
        if any(t in TIPOS_ORG or t in TIPOS_PESSOA for t in tipos):
            saida.append(valor)
        for chave, filho in valor.items():
            if chave != "@context":
                percorre(filho, saida)


def classe_do_no(tipos: list[str]) -> str:
    return "Person" if any(t in TIPOS_PESSOA for t in tipos) and not any(t in TIPOS_ORG for t in tipos) else "Organization"


def carrega_fonte(fonte: str, rede: Rede) -> tuple[str, str, str]:
    """Devolve (html, url_final, erro)."""
    if os.path.isfile(fonte):
        with open(fonte, encoding="utf-8", errors="replace") as fh:
            return fh.read(), "", ""
    if not fonte.lower().startswith(("http://", "https://")):
        return "", "", "não é arquivo existente nem URL http(s)"
    if rede.offline:
        return "", "", "modo --offline não busca URL"
    try:
        resp = rede.pede("GET", fonte, allow_redirects=True)
    except requests.RequestException as exc:
        return "", "", f"falha ao buscar: {exc.__class__.__name__}"
    if resp.status_code >= 400:
        return "", resp.url, f"HTTP {resp.status_code}"
    return resp.text, resp.url, ""


# ------------------------------------------------------------- checagem de URL
def checa_url(url: str, rede: Rede, cache: dict) -> dict:
    if url in cache:
        return cache[url]
    res = {"url": url, "status": None, "url_final": url, "classe": "", "nivel": "OK", "detalhe": ""}
    try:
        resp = rede.pede("HEAD", url, allow_redirects=True)
        if resp.status_code in (400, 403, 404, 405, 501) or resp.status_code >= 500:
            resp = rede.pede("GET", url, allow_redirects=True, stream=True)
            resp.close()
        res["status"] = resp.status_code
        res["url_final"] = resp.url
        primeiro = resp.history[0].status_code if resp.history else None
        cod = resp.status_code
        if cod == 999 or (cod in (401, 403, 429) and dominio_bloqueia(url)):
            res.update(classe="não verificável por bot", nivel="INFO",
                       detalhe=f"HTTP {cod}: o site recusa robôs; conferir no navegador")
        elif cod in (401, 403):
            res.update(classe="não verificável por bot", nivel="INFO",
                       detalhe=f"HTTP {cod}: acesso negado ao robô; conferir no navegador")
        elif cod == 429:
            res.update(classe="limite de requisições", nivel="INFO",
                       detalhe="HTTP 429 mesmo depois de esperar; conferir mais tarde")
        elif 200 <= cod < 300:
            if resp.history and chave_url(resp.url) != chave_url(url):
                res.update(classe="redireciona", nivel="INFO",
                           detalhe=f"{primeiro} -> {resp.url} (considerar usar a URL final)")
            else:
                res.update(classe="OK", nivel="OK", detalhe=f"HTTP {cod}")
        elif 300 <= cod < 400:
            res.update(classe="redireciona", nivel="ATENÇÃO", detalhe=f"HTTP {cod} sem destino final")
        elif 400 <= cod < 500:
            res.update(classe="erro 4xx", nivel="FAIL", detalhe=f"HTTP {cod}: perfil ausente ou removido")
        else:
            res.update(classe="erro 5xx", nivel="ATENÇÃO", detalhe=f"HTTP {cod}: erro do servidor, repetir depois")
    except requests.Timeout:
        res.update(classe="timeout", nivel="ATENÇÃO", detalhe=f"sem resposta em {rede.timeout:g} s")
    except requests.RequestException as exc:
        res.update(classe="sem conexão", nivel="FAIL", detalhe=exc.__class__.__name__)
    cache[url] = res
    return res


# ------------------------------------------------------------------ Wikidata
RE_QID = re.compile(r"wikidata\.org/(?:wiki|entity)/(Q\d+)", re.I)


def qid_de(url: str) -> str:
    m = RE_QID.search(url)
    return m.group(1).upper() if m else ""


def identificador_do_perfil(url: str) -> tuple[str, str]:
    """(propriedade, identificador) de um perfil pelo mapa domínio -> propriedade."""
    p = urlparse(url)
    host = host_base(url)
    seg = [s for s in p.path.split("/") if s]
    if not seg:
        return "", ""
    if mesmo_dominio(host, "twitter.com") or mesmo_dominio(host, "x.com"):
        return "P2002", seg[0].lstrip("@")
    if mesmo_dominio(host, "facebook.com"):
        if seg[0] == "profile.php":
            return "P2013", dict(parse_qsl(p.query)).get("id", "")
        return "P2013", seg[0]
    if mesmo_dominio(host, "linkedin.com") and len(seg) >= 2:
        if seg[0] == "company":
            return "P4264", seg[1]
        if seg[0] == "in":
            return "P6634", seg[1]
    if mesmo_dominio(host, "instagram.com"):
        return "P2003", seg[0]
    if mesmo_dominio(host, "youtube.com"):
        if seg[0] == "channel" and len(seg) >= 2:
            return "P2397", seg[1]
        if seg[0].startswith("@"):
            return "P11245", seg[0][1:]
    if mesmo_dominio(host, "github.com"):
        return "P2037", seg[0]
    return "", ""


def valores_claim(entidade: dict, prop: str) -> list[str]:
    valores = []
    for c in entidade.get("claims", {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, str):
            valores.append(v)
    return valores


def busca_wikidata(qids: list[str], rede: Rede) -> tuple[dict, str]:
    """Devolve ({qid_pedido: entidade ou {"missing": True}}, erro)."""
    saida: dict = {}
    for i in range(0, len(qids), 50):
        lote = qids[i:i + 50]
        try:
            resp = rede.pede("GET", WIKIDATA_API, params={
                "action": "wbgetentities", "ids": "|".join(lote), "format": "json",
                "props": "info|labels|aliases|claims", "languages": "pt|pt-br|en|mul",
            })
            dados = resp.json()
        except (requests.RequestException, ValueError) as exc:
            return saida, f"API do Wikidata indisponível ({exc.__class__.__name__})"
        if "error" in dados:
            # Um id inexistente derruba o lote inteiro: consulta um a um.
            if len(lote) > 1:
                for q in lote:
                    parcial, erro = busca_wikidata([q], rede)
                    saida.update(parcial)
                    if erro:
                        return saida, erro
                continue
            saida[lote[0]] = {"missing": True, "erro_api": dados["error"].get("info", "")}
            continue
        entidades = dados.get("entities", {})
        for q in lote:
            ent = entidades.get(q)
            if ent is None:
                for outra in entidades.values():
                    if outra.get("redirects", {}).get("from") == q:
                        ent = outra
                        break
            if ent is None:
                ent = {"missing": True}
            elif "missing" in ent:
                ent = {"missing": True}
            saida[q] = ent
    return saida, ""


def avalia_wikidata(qid: str, ent: dict, nomes: set[str], dominio_site: str, same_as: list[str]) -> list[tuple[str, str]]:
    achados: list[tuple[str, str]] = []
    if ent.get("missing"):
        achados.append(("FAIL", f"Wikidata {qid}: item não existe (apagado ou id errado); remover do sameAs"))
        return achados
    id_real = ent.get("id", qid)
    if id_real != qid:
        achados.append(("ATENÇÃO", f"Wikidata {qid}: redirecionado para {id_real} (item fundido); atualizar o sameAs"))
    rotulos = {lang: v.get("value", "") for lang, v in ent.get("labels", {}).items()}
    apelidos = [a.get("value", "") for lista in ent.get("aliases", {}).values() for a in lista]
    nomes_norm = {normaliza_nome(n) for n in nomes if n}
    rot_norm = {normaliza_nome(v) for v in rotulos.values() if v}
    ali_norm = {normaliza_nome(v) for v in apelidos if v}
    exibe = " / ".join(f"{k}: {v}" for k, v in rotulos.items()) or "sem rótulo pt/en"
    if not nomes_norm:
        achados.append(("INFO", f"Wikidata {id_real}: nó sem name para comparar ({exibe})"))
    elif nomes_norm & rot_norm:
        achados.append(("OK", f"Wikidata {id_real}: rótulo bate com o name ({exibe})"))
    elif nomes_norm & ali_norm:
        achados.append(("INFO", f"Wikidata {id_real}: name bate só com um apelido, não com o rótulo ({exibe})"))
    else:
        achados.append(("ATENÇÃO", f"Wikidata {id_real}: rótulo ({exibe}) não bate com o name do nó"))
    sites = valores_claim(ent, "P856")
    if not sites:
        achados.append(("ATENÇÃO", f"Wikidata {id_real}: sem P856 (site oficial)"))
    elif dominio_site and any(mesmo_dominio(host_base(s), dominio_site) for s in sites):
        achados.append(("OK", f"Wikidata {id_real}: P856 aponta para {dominio_site}"))
    elif dominio_site:
        achados.append(("ATENÇÃO", f"Wikidata {id_real}: P856 = {', '.join(sites)}, não é {dominio_site}"))
    # Reciprocidade parcial pelo mapa domínio -> propriedade.
    listados, faltam = [], []
    for u in same_as:
        prop, ident = identificador_do_perfil(u)
        if not prop or not ident:
            continue
        valores = {v.casefold() for v in valores_claim(ent, prop)}
        (listados if ident.casefold() in valores else faltam).append(f"{PROP_NOMES[prop]} ({prop})")
    if listados or faltam:
        total = len(listados) + len(faltam)
        msg = f"Wikidata {id_real}: lista {len(listados)} de {total} perfil(is) do sameAs"
        if faltam:
            msg += f"; ausentes: {', '.join(faltam)}"
        achados.append(("OK" if not faltam else "INFO", msg))
    return achados


# ------------------------------------------------------------------ principal
def audita(fontes: list[str], rede: Rede, max_urls: int, sem_wikidata: bool, todos: bool = False) -> dict:
    paginas, entidades = [], {}
    ordem: list[str] = []
    for fonte in fontes:
        html, url_final, erro = carrega_fonte(fonte, rede)
        pag = {"fonte": fonte, "url_final": url_final, "erro": erro, "blocos": 0, "erros_jsonld": [], "nos": 0}
        paginas.append(pag)
        if erro:
            continue
        blocos, erros = extrai_blocos(html)
        pag.update(blocos=len(blocos), erros_jsonld=erros)
        nos: list = []
        percorre(blocos, nos)
        pag["nos"] = len(nos)
        base_pagina = url_final or fonte
        for i, no in enumerate(nos):
            tipos = tipos_do_no(no)
            ident = texto_de(no.get("@id"))
            chave = ident or f"{base_pagina}#sem-id-{i}"
            ent = entidades.get(chave)
            if ent is None:
                ent = entidades[chave] = {
                    "id": ident, "tipos": [], "classe": classe_do_no(tipos), "paginas": [],
                    "nomes": {}, "urls": {}, "same_as": [], "ocorrencias_same_as": [],
                }
                ordem.append(chave)
            for t in tipos:
                if t not in ent["tipos"]:
                    ent["tipos"].append(t)
            if base_pagina not in ent["paginas"]:
                ent["paginas"].append(base_pagina)
            nome, url = texto_de(no.get("name")), texto_de(no.get("url"))
            if nome:
                ent["nomes"].setdefault(nome, [])
                if base_pagina not in ent["nomes"][nome]:
                    ent["nomes"][nome].append(base_pagina)
            if url:
                ent["urls"].setdefault(url, [])
                if base_pagina not in ent["urls"][url]:
                    ent["urls"][url].append(base_pagina)
            for alt in como_lista(no.get("alternateName")):
                if isinstance(alt, str):
                    ent.setdefault("apelidos", set()).add(alt)
            sa = [texto_de(s) for s in como_lista(no.get("sameAs")) if texto_de(s)]
            if sa:
                ent["ocorrencias_same_as"].append((base_pagina, sa))
            for s in sa:
                if s not in ent["same_as"]:
                    ent["same_as"].append(s)

    cache_http: dict = {}
    checadas = 0
    qids = sorted({qid_de(s) for c in ordem for s in entidades[c]["same_as"] if qid_de(s)})
    wd, erro_wd = ({}, "") if (sem_wikidata or rede.offline or not qids) else busca_wikidata(qids, rede)

    for chave in ordem:
        ent = entidades[chave]
        achados: list[tuple[str, str]] = []
        ent["secundario"] = not ent["id"] and not todos
        if ent["secundario"]:
            # Nó sem @id (autor de avaliação, veículo citado...): fora do relatório padrão.
            ent["itens_same_as"], ent["achados"] = [], []
            continue
        if not ent["id"]:
            achados.append(("INFO", "nó sem @id: outras páginas e o grafo não conseguem referenciar esta entidade"))
        if not ent["nomes"]:
            achados.append(("ATENÇÃO", "nó sem name"))
        if len(ent["nomes"]) > 1:
            detalhe = "; ".join(f'"{n}" em {len(p)} página(s)' for n, p in ent["nomes"].items())
            achados.append(("ATENÇÃO", f"mesmo @id com name diferente: {detalhe}"))
        if len({chave_url(u) for u in ent["urls"]}) > 1:
            achados.append(("ATENÇÃO", f"mesmo @id com url diferente: {', '.join(ent['urls'])}"))
        if not ent["same_as"]:
            achados.append(("INFO", "sem sameAs"))
        for pagina, lista in ent["ocorrencias_same_as"]:
            vistos: dict = {}
            for s in lista:
                vistos.setdefault(chave_url(s), []).append(s)
            for iguais in vistos.values():
                if len(iguais) > 1:
                    achados.append(("ATENÇÃO", f"sameAs duplicado ({len(iguais)}x): {iguais[0]}"))
        dominio_site = host_base(next(iter(ent["urls"]), "") or (ent["paginas"][0] if ent["paginas"] else ""))
        itens = []
        for s in ent["same_as"]:
            p = urlparse(s)
            item = {"url": s, "nivel": "OK", "detalhes": []}
            if p.scheme not in ("http", "https") or not p.netloc:
                item["nivel"] = "FAIL"
                item["detalhes"].append("URL malformada ou sem esquema http(s)")
                itens.append(item)
                continue
            if p.scheme == "http":
                item["nivel"] = "ATENÇÃO"
                item["detalhes"].append("usa http em vez de https")
            rastreio = [k for k, _ in parse_qsl(p.query, keep_blank_values=True) if PARAMS_RASTREIO.match(k)]
            if rastreio:
                item["nivel"] = "ATENÇÃO"
                item["detalhes"].append(f"parâmetro de rastreio: {', '.join(rastreio)}")
            qid = qid_de(s)
            if qid:
                item["wikidata"] = qid
                if qid in wd:
                    for nivel, msg in avalia_wikidata(qid, wd[qid], set(ent["nomes"]) | ent.get("apelidos", set()),
                                                      dominio_site, ent["same_as"]):
                        achados.append((nivel, msg))
                        if ORDEM_NIVEL[nivel] >= ORDEM_NIVEL["ATENÇÃO"]:
                            item["nivel"] = max(item["nivel"], nivel, key=ORDEM_NIVEL.get)
                elif erro_wd:
                    achados.append(("INFO", f"Wikidata {qid}: {erro_wd}"))
            elif not rede.offline and checadas < max_urls:
                checadas += s not in cache_http
                r = checa_url(s, rede, cache_http)
                item["http"] = r
                item["detalhes"].append(f"{r['classe']}: {r['detalhe']}")
                item["nivel"] = max(item["nivel"], r["nivel"], key=ORDEM_NIVEL.get)
            elif not rede.offline:
                item["detalhes"].append(f"não checada (limite --max-urls {max_urls})")
            itens.append(item)
        ent["itens_same_as"] = itens
        ent["achados"] = achados

    # Consistência entre páginas: mesmo name com @id diferente.
    cruzados = []
    por_nome: dict = {}
    for chave in ordem:
        ent = entidades[chave]
        if not ent["id"]:
            continue
        for n in ent["nomes"]:
            por_nome.setdefault((ent["classe"], normaliza_nome(n)), set()).add(ent["id"])
    for (classe, nome), ids in sorted(por_nome.items()):
        if len(ids) > 1 and nome:
            cruzados.append(("ATENÇÃO", f'{classe} "{nome}" publicado com {len(ids)} @id diferentes: {", ".join(sorted(ids))}'))

    return {"paginas": paginas, "entidades": [entidades[c] for c in ordem], "cruzados": cruzados,
            "requisicoes": rede.requisicoes}


def nivel_entidade(ent: dict) -> str:
    niveis = [n for n, _ in ent["achados"]] + [i["nivel"] for i in ent["itens_same_as"]]
    return max(niveis, key=ORDEM_NIVEL.get) if niveis else "OK"


def imprime(res: dict) -> tuple[int, int]:
    aten = fail = 0
    print(f"=== {NOME} ===")
    for pag in res["paginas"]:
        destino = f" -> {pag['url_final']}" if pag["url_final"] and pag["url_final"] != pag["fonte"] else ""
        if pag["erro"]:
            print(f"  FAIL     {pag['fonte']}{destino}: {pag['erro']}")
            fail += 1
            continue
        print(f"  página   {pag['fonte']}{destino}: {pag['blocos']} bloco(s) JSON-LD, {pag['nos']} nó(s) de entidade")
        for e in pag["erros_jsonld"]:
            print(f"  FAIL     {e}")
            fail += 1
    secundarios = [e for e in res["entidades"] if e.get("secundario")]
    for ent in res["entidades"]:
        if ent.get("secundario"):
            continue
        nome = " / ".join(ent["nomes"]) or "(sem name)"
        print(f"\n[{'/'.join(ent['tipos'])}] {nome}")
        print(f"  @id: {ent['id'] or '(sem @id)'}")
        if ent["urls"]:
            print(f"  url: {', '.join(ent['urls'])}")
        print(f"  páginas: {len(ent['paginas'])} | sameAs: {len(ent['same_as'])}")
        for item in ent["itens_same_as"]:
            det = "; ".join(item["detalhes"]) or ("Wikidata (ver abaixo)" if item.get("wikidata") else "estrutura OK")
            print(f"  {item['nivel']:<8} {item['url']}  [{det}]")
            if not item.get("wikidata"):  # achados do Wikidata já são contados abaixo
                aten += item["nivel"] == "ATENÇÃO"
                fail += item["nivel"] == "FAIL"
        for nivel, msg in ent["achados"]:
            print(f"  {nivel:<8} {msg}")
            aten += nivel == "ATENÇÃO"
            fail += nivel == "FAIL"
    if res["cruzados"]:
        print("\nConsistência entre páginas:")
        for nivel, msg in res["cruzados"]:
            print(f"  {nivel:<8} {msg}")
            aten += nivel == "ATENÇÃO"
    if secundarios:
        print(f"\n{len(secundarios)} nó(s) sem @id omitido(s) (autor de avaliação, veículo citado e afins); "
              "use --todos para auditar também esses nós.")
    total = len(res["entidades"]) - len(secundarios)
    print(f"\nResumo: {total} entidade(s) auditada(s) | ATENÇÃO {aten} | FAIL {fail} | {res['requisicoes']} requisição(ões)")
    print("(\"não verificável por bot\" pede conferência manual no navegador; não é erro.)")
    return aten, fail


def serializa(res: dict) -> dict:
    ents = []
    for e in res["entidades"]:
        if e.get("secundario"):
            continue
        ents.append({
            "id": e["id"], "tipos": e["tipos"], "classe": e["classe"], "nivel": nivel_entidade(e),
            "nomes": e["nomes"], "urls": e["urls"], "paginas": e["paginas"],
            "same_as": e["itens_same_as"],
            "achados": [{"nivel": n, "mensagem": m} for n, m in e["achados"]],
        })
    return {"ferramenta": NOME, "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "paginas": res["paginas"], "entidades": ents,
            "consistencia": [{"nivel": n, "mensagem": m} for n, m in res["cruzados"]],
            "requisicoes": res["requisicoes"]}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audita o sameAs das entidades Organization e Person em JSON-LD, com conferência no Wikidata.")
    ap.add_argument("fontes", nargs="*", help="URL(s) ou arquivo(s) HTML local(is)")
    ap.add_argument("--urls", nargs="+", default=[], help="várias URLs para conferir consistência entre páginas")
    ap.add_argument("--json", metavar="ARQUIVO", help="grava o relatório completo em JSON")
    ap.add_argument("--strict", action="store_true", help="código de saída 1 se houver ATENÇÃO ou FAIL")
    ap.add_argument("--offline", action="store_true", help="não acessa a rede (só arquivos locais e checagens estruturais)")
    ap.add_argument("--todos", action="store_true", help="audita também os nós sem @id (omitidos por padrão)")
    ap.add_argument("--sem-wikidata", action="store_true", help="não consulta a API do Wikidata")
    ap.add_argument("--delay", type=float, default=1.0, help="intervalo entre requisições em segundos (padrão 1.0)")
    ap.add_argument("--timeout", type=float, default=15.0, help="tempo limite por requisição em segundos (padrão 15)")
    ap.add_argument("--max-urls", type=int, default=50, help="máximo de URLs do sameAs checadas por HTTP (padrão 50)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    fontes = list(dict.fromkeys(args.fontes + args.urls))
    if not fontes:
        ap.error("informe ao menos uma URL ou arquivo HTML")
    rede = Rede(args.delay, args.timeout, args.offline)
    res = audita(fontes, rede, args.max_urls, args.sem_wikidata, args.todos)
    aten, fail = imprime(res)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(serializa(res), fh, ensure_ascii=False, indent=2, default=list)
        print(f"JSON gravado em {args.json}")
    if args.strict and (aten or fail):
        sys.exit(1)


if __name__ == "__main__":
    main()
