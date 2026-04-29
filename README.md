# 🏠 Comparador de Imóveis — Belo Horizonte

Aplicação web para comparar imóveis à venda em BH com ranking inteligente baseado em múltiplos critérios.

## Funcionalidades

- **Adicionar imóveis por link** — ZAP Imóveis, VivaReal, OLX ou qualquer site
- **Scraping automático** — extrai preço, área, quartos, banheiros, endereço e foto
- **Distâncias calculadas automaticamente** (sem chave de API):
  - 🚗 Distância e tempo de carro até a Praça Sete de Setembro (centro de BH)
  - 🚌 Estimativa de tempo de ônibus até o centro
  - 🛒 Supermercado mais próximo (via OpenStreetMap)
- **Ranking ponderado** — score de 0 a 100 com pesos configuráveis
- **Banco SQLite** — todos os dados persistidos localmente
- **Interface responsiva** — funciona em desktop e mobile

## Critérios de Ranking

| Critério | Peso padrão | Lógica |
|---|---|---|
| Preço | 30 | Menor = melhor |
| Área (m²) | 20 | Maior = melhor |
| Quartos | 15 | Mais = melhor |
| Banheiros | 10 | Mais = melhor |
| Dist. Supermercado | 10 | Mais perto = melhor |
| Dist. Centro (carro) | 7 | Mais perto = melhor |
| Dist. Centro (ônibus) | 8 | Mais perto = melhor |

Os pesos são ajustáveis pela interface (botão ⚙️).

## Instalação

```bash
# 1. Crie um ambiente virtual
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Execute
python run.py
```

Acesse **http://localhost:5000**

## Estrutura

```
├── app/
│   ├── main.py        # Factory Flask
│   ├── routes.py      # Rotas API + página
│   ├── database.py    # SQLite (CRUD)
│   ├── scraper.py     # Scraping de links
│   ├── distances.py   # OSRM + Overpass API
│   └── ranking.py     # Cálculo de scores
├── templates/
│   └── index.html     # Frontend
├── static/
│   ├── style.css
│   └── app.js
├── run.py
└── requirements.txt
```

## APIs utilizadas (todas gratuitas, sem chave)

- **OSRM** — roteamento de carro/a pé
- **Overpass API** — busca de supermercados no OpenStreetMap
- **Nominatim** — geocodificação de endereços

## Observações

- O scraping depende da estrutura HTML dos sites. Se um site mudar seu layout, pode ser necessário atualizar o scraper.
- Sites com proteção anti-bot (Cloudflare, etc.) podem bloquear o scraping. Nesse caso, use o botão "Reprocessar" ou adicione os dados manualmente.
- O tempo de ônibus é uma estimativa baseada na distância de carro dividida por 20 km/h + 10 min de espera.
