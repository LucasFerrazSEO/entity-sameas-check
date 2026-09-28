**English** · [Português (Brasil)](README.pt-BR.md)

# entity-sameas-check

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) ![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)

`entity-sameas-check` is a free, open source command-line tool that audits
the `sameAs` of the Organization and Person entities declared in a page's
JSON-LD. It checks whether each profile URL still answers, flags duplicated,
`http` and tracking-parameter URLs, cross-checks Wikidata items through the
public Wikidata API and compares `name`, `url` and `@id` across pages.

The tool prints its report in Brazilian Portuguese.

## Contents

- [Background](#background)
- [What it checks](#what-it-checks)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [FAQ](#faq)
- [Limitations](#limitations)
- [Methodology](#methodology)
- [Contributing](#contributing)
- [Author](#author)
- [License](#license)

## Background

`sameAs` is how a site tells search engines and AI systems which external
profiles describe the same entity: the LinkedIn page, the Wikidata item,
the YouTube channel. The list is usually written once and then forgotten.
Profiles get renamed, accounts get closed, Wikidata items get merged or
deleted, and the JSON-LD keeps pointing at them. The same company can also
end up published under two different `@id` values on two pages, which
splits the entity instead of consolidating it. `entity-sameas-check` makes
that drift visible.

## What it checks

1. **Entity discovery.** Reads every `application/ld+json` block, including
   `@graph` and arrays, and finds Organization nodes (Organization,
   LocalBusiness, ProfessionalService, Corporation and common subtypes) and
   Person nodes. Nodes without `@id` (review authors, cited publishers) are
   skipped by default; `--todos` includes them.
2. **sameAs hygiene.** Duplicated URLs (scheme and trailing slash ignored),
   `http` instead of `https`, tracking parameters (`utm_*`, `fbclid`,
   `gclid`, `igshid` and others) and malformed URLs.
3. **Does each profile answer?** HEAD request with a GET fallback,
   following redirects. Result: OK, redirects (with the final URL),
   **not verifiable by bot** (999, 401, 403 or a persistent 429, typical of
   LinkedIn, Instagram, Facebook and X), 4xx, 5xx, timeout or no
   connection. "Not verifiable" is a request for a manual check, not an
   error.
4. **Wikidata cross-check.** For `wikidata.org/wiki/Q...` URLs, queries
   `wbgetentities` and reports whether the item exists, was deleted or was
   redirected (merged); whether the pt/en label (or an alias) matches the
   node's `name` after normalization; whether P856 (official website)
   points to the site's domain; and which other `sameAs` profiles the item
   lists (partial reciprocity through a small domain to property map: X
   P2002, Facebook P2013, LinkedIn company P4264, LinkedIn person P6634,
   Instagram P2003, YouTube P2397 and P11245, GitHub P2037).
5. **Consistency across pages.** With several URLs: the same `@id` with a
   different `name` or `url`, and the same `name` published under
   different `@id` values.

## Requirements

Python 3.9 or newer and the `requests` library (see `requirements.txt`).

## Installation

```bash
git clone https://github.com/LucasFerrazSEO/entity-sameas-check.git
cd entity-sameas-check
pip install -r requirements.txt
```

## Usage

**1. Audit a live page.**

```bash
python entity_sameas_check.py https://example.com/
```

**2. Compare several pages** (for example the company site and the
founder's personal site).

```bash
python entity_sameas_check.py --urls https://lucasferrazseo.com/ https://lucasferraz.com/
```

A real output from that command, run on 2026-09-28 and shortened with
"..." (most OK lines removed):

```
=== entity-sameas-check ===
  página   https://lucasferrazseo.com/: 1 bloco(s) JSON-LD, 21 nó(s) de entidade
  página   https://lucasferraz.com/: 1 bloco(s) JSON-LD, 7 nó(s) de entidade

[Organization] Lucas Ferraz SEO
  @id: https://lucasferrazseo.com/#organization
  url: https://lucasferrazseo.com/
  páginas: 2 | sameAs: 11
  INFO     https://www.crunchbase.com/organization/lucas-ferraz-seo  [não verificável por bot: HTTP 403: acesso negado ao robô; conferir no navegador]
  OK       https://www.linkedin.com/company/lucasferrazseo/  [OK: HTTP 200]
  ...

[Person] Lucas Ferraz
  @id: https://lucasferraz.com/#person
  url: https://lucasferraz.com/
  páginas: 1 | sameAs: 15
  OK       https://orcid.org/0009-0004-1265-7226  [OK: HTTP 200]
  INFO     https://www.linkedin.com/in/lucasferrazseo/  [não verificável por bot: HTTP 999: o site recusa robôs; conferir no navegador]
  INFO     https://deezer.com/show/1001118021  [redireciona: 301 -> https://www.deezer.com/br/show/1001118021 (considerar usar a URL final)]
  ...

Consistência entre páginas:
  ATENÇÃO  Organization "lucas ferraz seo" publicado com 2 @id diferentes: https://lucasferrazseo.com/#organization, https://lucasferrazseo.com/#psLucasFerraz
  ATENÇÃO  Person "lucas ferraz" publicado com 2 @id diferentes: https://lucasferraz.com/#person, https://lucasferrazseo.com/autor-lucas-ferraz/#personLucasFerraz

18 nó(s) sem @id omitido(s) (autor de avaliação, veículo citado e afins); use --todos para auditar também esses nós.

Resumo: 9 entidade(s) auditada(s) | ATENÇÃO 2 | FAIL 0 | 34 requisição(ões)
```

The two ATENÇÃO (warning) lines are real findings on the author's own
sites: the same company and the same person published under two `@id`
values each.

**3. Audit a local HTML file without network access.** The `examples/`
folder has a fictitious page with planted problems.

```bash
python entity_sameas_check.py examples/exemplo-entidade.html --offline
```

```
[Organization/ProfessionalService] Exemplo Consultoria
  @id: https://example.com/#organization
  url: https://example.com/
  páginas: 1 | sameAs: 4
  OK       https://www.linkedin.com/company/exemplo-consultoria/  [estrutura OK]
  ATENÇÃO  http://www.instagram.com/exemploconsultoria/  [usa http em vez de https]
  ATENÇÃO  https://www.facebook.com/exemploconsultoria?utm_source=site  [parâmetro de rastreio: utm_source]
  OK       https://www.linkedin.com/company/exemplo-consultoria  [estrutura OK]
  ATENÇÃO  sameAs duplicado (2x): https://www.linkedin.com/company/exemplo-consultoria/

[Person] Maria Exemplo / Maria E. Exemplo
  @id: https://example.com/#pessoa
  páginas: 1 | sameAs: 2
  OK       https://github.com/maria-exemplo  [estrutura OK]
  FAIL     example.com/maria  [URL malformada ou sem esquema http(s)]
  ATENÇÃO  mesmo @id com name diferente: "Maria Exemplo" em 1 página(s); "Maria E. Exemplo" em 1 página(s)

Resumo: 2 entidade(s) auditada(s) | ATENÇÃO 4 | FAIL 1 | 0 requisição(ões)
```

**4. What a missing Wikidata item looks like.** A real run against a
`sameAs` that points to a Wikidata item that does not exist (the same
output appears when an item has been deleted):

```
  FAIL     https://www.wikidata.org/wiki/Q999999999  [Wikidata (ver abaixo)]
  FAIL     Wikidata Q999999999: item não existe (apagado ou id errado); remover do sameAs
```

And against a healthy item, with partial reciprocity:

```
  OK       Wikidata Q95: rótulo bate com o name (mul: Google / en: Google)
  OK       Wikidata Q95: P856 aponta para about.google
  INFO     Wikidata Q95: lista 3 de 4 perfil(is) do sameAs; ausentes: LinkedIn (empresa) (P4264)
```

**5. Options.**

```bash
python entity_sameas_check.py https://example.com/ --json relatorio.json   # full report in JSON
python entity_sameas_check.py https://example.com/ --strict   # exit code 1 on ATENÇÃO or FAIL
python entity_sameas_check.py https://example.com/ --todos    # also audit nodes without @id
python entity_sameas_check.py https://example.com/ --sem-wikidata   # skip the Wikidata API
python entity_sameas_check.py https://example.com/ --delay 2 --timeout 20 --max-urls 30
```

The tool identifies itself with the User-Agent
`entity-sameas-check/1.0 (+https://github.com/LucasFerrazSEO/entity-sameas-check)`,
waits `--delay` seconds between requests (default 1.0), retries a 429 once
after waiting and checks at most `--max-urls` profile URLs per run
(default 50).

## FAQ

**Is entity-sameas-check free?**
Yes. It is open source under the MIT license, with no sign-up and no usage
limit.

**Why does LinkedIn show up as "não verificável por bot"?**
LinkedIn answers automated requests with status 999, and several social
networks answer with 403. The profile may be perfectly fine. The tool
reports it as a manual check instead of a false error.

**Do I need a Wikidata account or API key?**
No. The tool reads the public `wbgetentities` endpoint, which needs no key.
It sends an identifiable User-Agent, as Wikimedia asks of automated
clients.

**Does a clean report mean I will get a Knowledge Panel or be cited by AI?**
No, and no tool can promise that. The report shows whether your entity
data is consistent and reachable. What search engines and AI systems do
with it is up to them.

**Does it read JSON-LD added by JavaScript?**
No. It reads the HTML as served. If your schema is injected in the browser,
save the rendered DOM as a file and pass the file.

## Limitations

The tool does not execute JavaScript. Profile status depends on how each
network treats automated requests, so a 200 on a login wall is still
reported as OK. Wikidata reciprocity covers only the properties in the
internal map, and identifier formats vary (a YouTube handle is not a
channel ID). Name matching is a normalized exact comparison, so a legal
name against a trade name will be flagged for review. Treat the result as
a checklist, not a verdict.

## Methodology

The tool comes from the routine maintenance of the Organization and Person
entities of [lucasferrazseo.com](https://lucasferrazseo.com) and
[lucasferraz.com](https://lucasferraz.com), including a real case of a
deleted Wikidata item that kept being listed in `sameAs` without anyone
noticing. It is generalized here for public use, with no site-specific or
CMS-specific rules.

## Contributing

Bug reports and suggestions are welcome through [GitHub Issues](https://github.com/LucasFerrazSEO/entity-sameas-check/issues).

## Author

[Lucas Ferraz](https://lucasferraz.com) is an SEO, website development and Generative Engine Optimization specialist and the founder of [Lucas Ferraz SEO](https://lucasferrazseo.com).

## License

MIT. See [LICENSE](LICENSE).
