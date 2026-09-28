[English](README.md) · **Português (Brasil)**

# entity-sameas-check

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) ![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)

`entity-sameas-check` é uma ferramenta gratuita, de código aberto e de
linha de comando, que audita o `sameAs` das entidades Organization e Person
declaradas no JSON-LD de uma página. Ela confere se cada URL de perfil
ainda responde, aponta URL duplicada, com `http` ou com parâmetro de
rastreio, cruza os itens do Wikidata pela API pública do Wikidata e compara
`name`, `url` e `@id` entre páginas.

## Sumário

- [Contexto](#contexto)
- [O que a ferramenta verifica](#o-que-a-ferramenta-verifica)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Uso](#uso)
- [Perguntas frequentes](#perguntas-frequentes)
- [Limitações](#limitações)
- [Método e origem](#método-e-origem)
- [Como contribuir](#como-contribuir)
- [Autor](#autor)
- [Licença](#licença)

## Contexto

O `sameAs` é o jeito de um site dizer aos buscadores e às IAs quais perfis
externos descrevem a mesma entidade: a página do LinkedIn, o item do
Wikidata, o canal do YouTube. A lista costuma ser escrita uma vez e depois
esquecida. Perfis mudam de nome, contas são fechadas, itens do Wikidata são
fundidos ou apagados, e o JSON-LD continua apontando para eles. A mesma
empresa também pode acabar publicada com dois `@id` diferentes em duas
páginas, o que divide a entidade em vez de consolidá-la.
`entity-sameas-check` deixa essa deriva visível.

## O que a ferramenta verifica

1. **Descoberta das entidades.** Lê todos os blocos `application/ld+json`,
   inclusive `@graph` e arrays, e encontra os nós de organização
   (Organization, LocalBusiness, ProfessionalService, Corporation e
   subtipos comuns) e de pessoa (Person). Nós sem `@id` (autor de
   avaliação, veículo citado) ficam fora do relatório padrão; `--todos`
   inclui esses nós.
2. **Higiene do sameAs.** URL duplicada (esquema e barra final ignorados),
   `http` em vez de `https`, parâmetro de rastreio (`utm_*`, `fbclid`,
   `gclid`, `igshid` e outros) e URL malformada.
3. **Cada perfil responde?** Requisição HEAD com GET de reserva, seguindo
   redirecionamento. Resultado: OK, redireciona (com a URL final), **não
   verificável por bot** (999, 401, 403 ou 429 persistente, típico de
   LinkedIn, Instagram, Facebook e X), 4xx, 5xx, timeout ou sem conexão.
   "Não verificável" é pedido de conferência manual, não erro.
4. **Cruzamento com o Wikidata.** Para URLs `wikidata.org/wiki/Q...`,
   consulta o `wbgetentities` e informa se o item existe, foi apagado ou
   foi redirecionado (fundido); se o rótulo pt/en (ou um apelido) bate com
   o `name` do nó depois de normalizado; se a P856 (site oficial) aponta
   para o domínio do site; e quais outros perfis do `sameAs` o item lista
   (reciprocidade parcial por um mapa pequeno domínio para propriedade: X
   P2002, Facebook P2013, LinkedIn empresa P4264, LinkedIn pessoa P6634,
   Instagram P2003, YouTube P2397 e P11245, GitHub P2037).
5. **Consistência entre páginas.** Com várias URLs: o mesmo `@id` com
   `name` ou `url` diferente, e o mesmo `name` publicado com `@id`
   diferentes.

## Requisitos

Python 3.9 ou mais recente e a biblioteca `requests` (ver
`requirements.txt`).

## Instalação

```bash
git clone https://github.com/LucasFerrazSEO/entity-sameas-check.git
cd entity-sameas-check
pip install -r requirements.txt
```

## Uso

**1. Audite uma página no ar.**

```bash
python entity_sameas_check.py https://example.com/
```

**2. Compare várias páginas** (por exemplo, o site da empresa e o site
pessoal do fundador).

```bash
python entity_sameas_check.py --urls https://lucasferrazseo.com/ https://lucasferraz.com/
```

Saída real desse comando, rodado em 2026-09-28 e encurtada com "..." (a
maior parte das linhas OK foi removida):

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

As duas linhas de ATENÇÃO são achados reais nos próprios sites do autor: a
mesma empresa e a mesma pessoa publicadas com dois `@id` cada uma.

**3. Audite um arquivo HTML local sem acessar a rede.** A pasta
`examples/` tem uma página fictícia com problemas plantados.

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

**4. Como aparece um item do Wikidata inexistente.** Execução real contra
um `sameAs` que aponta para um item do Wikidata que não existe (a mesma
saída aparece quando o item foi apagado):

```
  FAIL     https://www.wikidata.org/wiki/Q999999999  [Wikidata (ver abaixo)]
  FAIL     Wikidata Q999999999: item não existe (apagado ou id errado); remover do sameAs
```

E contra um item saudável, com reciprocidade parcial:

```
  OK       Wikidata Q95: rótulo bate com o name (mul: Google / en: Google)
  OK       Wikidata Q95: P856 aponta para about.google
  INFO     Wikidata Q95: lista 3 de 4 perfil(is) do sameAs; ausentes: LinkedIn (empresa) (P4264)
```

**5. Opções.**

```bash
python entity_sameas_check.py https://example.com/ --json relatorio.json   # relatório completo em JSON
python entity_sameas_check.py https://example.com/ --strict   # código de saída 1 se houver ATENÇÃO ou FAIL
python entity_sameas_check.py https://example.com/ --todos    # audita também os nós sem @id
python entity_sameas_check.py https://example.com/ --sem-wikidata   # não consulta a API do Wikidata
python entity_sameas_check.py https://example.com/ --delay 2 --timeout 20 --max-urls 30
```

A ferramenta se identifica com o User-Agent
`entity-sameas-check/1.0 (+https://github.com/LucasFerrazSEO/entity-sameas-check)`,
espera `--delay` segundos entre requisições (padrão 1.0), tenta de novo uma
vez depois de um 429 e confere no máximo `--max-urls` URLs de perfil por
execução (padrão 50).

## Perguntas frequentes

**entity-sameas-check é realmente grátis?**
Sim, código aberto sob licença MIT, sem cadastro, sem limite de uso.

**Por que o LinkedIn aparece como "não verificável por bot"?**
O LinkedIn responde a requisições automáticas com o status 999, e várias
redes sociais respondem com 403. O perfil pode estar perfeito. A
ferramenta registra o caso como conferência manual, em vez de acusar um
erro falso.

**Preciso de conta ou chave de API do Wikidata?**
Não. A ferramenta lê o endpoint público `wbgetentities`, que não pede
chave. Ela envia um User-Agent identificável, como a Wikimedia pede aos
clientes automáticos.

**Relatório limpo garante Painel de Conhecimento ou citação por IA?**
Não, e nenhuma ferramenta garante isso. O relatório mostra se os dados da
entidade estão consistentes e acessíveis. O que buscadores e IAs fazem com
eles é decisão deles.

**A ferramenta lê JSON-LD inserido por JavaScript?**
Não. Ela lê o HTML como o servidor entrega. Se o seu schema é inserido no
navegador, salve o DOM renderizado em arquivo e passe o arquivo.

## Limitações

A ferramenta não executa JavaScript. O status dos perfis depende de como
cada rede trata requisições automáticas, então um 200 em uma tela de login
ainda sai como OK. A reciprocidade no Wikidata cobre só as propriedades do
mapa interno, e os formatos de identificador variam (um handle do YouTube
não é o ID do canal). A comparação de nome é exata depois de normalizada,
então razão social contra nome fantasia vai aparecer para revisão. Trate o
resultado como lista de conferência, não como veredito.

## Método e origem

A ferramenta nasceu da manutenção de rotina das entidades Organization e
Person de [lucasferrazseo.com](https://lucasferrazseo.com) e
[lucasferraz.com](https://lucasferraz.com), inclusive de um caso real de
item do Wikidata apagado que continuava listado no `sameAs` sem ninguém
perceber. Foi generalizada aqui para uso público, sem nenhuma regra
específica de site ou CMS.

## Como contribuir

Relatos de erro e sugestões são bem-vindos pelas [Issues do GitHub](https://github.com/LucasFerrazSEO/entity-sameas-check/issues).

## Autor

[Lucas Ferraz](https://lucasferraz.com) é especialista em SEO, criação de sites e Generative Engine Optimization e fundador da [Lucas Ferraz SEO](https://lucasferrazseo.com).

## Licença

MIT. Veja o arquivo [LICENSE](LICENSE).
