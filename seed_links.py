"""
Importa a lista de links de imóveis direto no banco SQLite.
Uso: python seed_links.py   (ou: make seed)
"""

import sys
import os

# Garante que o módulo app é encontrado
sys.path.insert(0, os.path.dirname(__file__))

from app.database import init_db, get_connection

LINKS = [
    # ── Primeiro de Maio ──────────────────────────────────────────────────
    "https://www.zapimoveis.com.br/imovel/venda-apartamento-1-quarto-com-cozinha-primeiro-de-maio-belo-horizonte-mg-52m2-id-2763777115/",
    # ── São Gabriel ───────────────────────────────────────────────────────
    "https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-com-armario-embutido-sao-gabriel-belo-horizonte-mg-42m2-id-2880573181/",
    "https://www.vivareal.com.br/imovel/apartamento-3-quartos-sao-gabriel-bairros-belo-horizonte-com-garagem-64m2-venda-RS200000-id-2871376618/",
    "https://www.vivareal.com.br/imovel/apartamento-2-quartos-sao-gabriel-bairros-belo-horizonte-com-garagem-50m2-venda-RS205000-id-2879592717/",
    "https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-sao-gabriel-belo-horizonte-mg-64m2-id-2846160613/",
    "https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-com-salao-de-festas-sao-gabriel-belo-horizonte-mg-53m2-id-2866110194/",
    "https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-com-area-de-servico-sao-gabriel-belo-horizonte-mg-50m2-id-2878097314/",
    "https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-sao-gabriel-belo-horizonte-mg-44m2-id-2788596618/",
    "https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-com-interfone-sao-gabriel-belo-horizonte-mg-49m2-id-2879595402/",
    # ── Paquetá ───────────────────────────────────────────────────────────
    "https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-paqueta-belo-horizonte-mg-49m2-id-2870521873/",
    # ── Santa Amélia ──────────────────────────────────────────────────────
    "https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-com-interfone-santa-amelia-belo-horizonte-mg-57m2-id-2876327218/",
    # ── São Lucas ─────────────────────────────────────────────────────────
    "https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-sao-lucas-belo-horizonte-mg-60m2-id-2883240060/",
    "https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-com-armario-de-cozinha-sao-lucas-belo-horizonte-mg-62m2-id-2883153721/",
    # ── Dom Silvério ──────────────────────────────────────────────────────
    "https://www.vivareal.com.br/imovel/apartamento-2-quartos-sao-gabriel-bairros-belo-horizonte-com-garagem-55m2-venda-RS200000-id-2872026807/",
    # ── Dom Bosco ─────────────────────────────────────────────────────────
    "https://www.vivareal.com.br/imovel/casa-2-quartos-dom-bosco-bairros-belo-horizonte-com-garagem-180m2-venda-RS250000-id-2860055965/",
    # ── Manacás ───────────────────────────────────────────────────────────
    "https://www.vivareal.com.br/imovel/apartamento-2-quartos-manacas-bairros-belo-horizonte-com-garagem-66m2-venda-RS200000-id-2860493667/",
    # ── São Cristóvão ─────────────────────────────────────────────────────
    "https://www.vivareal.com.br/imovel/apartamento-2-quartos-sao-cristovao-bairros-belo-horizonte-com-garagem-68m2-venda-RS210000-id-2867313666/",
    "https://www.vivareal.com.br/imovel/apartamento-2-quartos-sao-cristovao-bairros-belo-horizonte-com-garagem-75m2-venda-RS219700-id-2866594353/",
    # ── Carlos Prates ─────────────────────────────────────────────────────
    "https://www.vivareal.com.br/imovel/apartamento-2-quartos-carlos-prates-bairros-belo-horizonte-com-garagem-54m2-venda-RS230000-id-2880918374/",
    "https://www.vivareal.com.br/imovel/apartamento-2-quartos-carlos-prates-bairros-belo-horizonte-55m2-venda-RS230000-id-2726625640/",
    # ── Jardim Montanhês / Caiçaras ───────────────────────────────────────
    "https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-com-ambientes-integrados-caicaras-belo-horizonte-mg-55m2-id-2827970913/",
    "https://www.vivareal.com.br/imovel/apartamento-2-quartos-jardim-montanhes-bairros-belo-horizonte-com-garagem-55m2-venda-RS245000-id-2829401917/",
    "https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-com-janelas-de-aluminio-caicaras-belo-horizonte-mg-55m2-id-2830126719/",
    # ── Floramar ──────────────────────────────────────────────────────────
    "https://www.vivareal.com.br/imovel/casa-2-quartos-floramar-bairros-belo-horizonte-com-garagem-145m2-venda-RS250000-id-2882325920/",
    # ── Planalto ──────────────────────────────────────────────────────────
    "https://www.vivareal.com.br/imovel/casa-2-quartos-planalto-bairros-belo-horizonte-85m2-venda-RS250000-id-2808179595/",
    # ── Prado ─────────────────────────────────────────────────────────────
    "https://www.vivareal.com.br/imovel/apartamento-3-quartos-prado-bairros-belo-horizonte-68m2-venda-RS240000-id-2864961440/",
]


def seed():
    init_db()
    conn = get_connection()
    inseridos = 0
    ignorados = 0

    for url in LINKS:
        url = url.strip()
        if not url:
            continue
        try:
            conn.execute(
                """INSERT OR IGNORE INTO imoveis (url, status) VALUES (?, 'pendente')""",
                (url,),
            )
            if conn.total_changes > inseridos + ignorados:
                inseridos += 1
            else:
                ignorados += 1
        except Exception as e:
            print(f"  ✗ Erro ao inserir {url[:60]}...: {e}")

    conn.commit()
    conn.close()

    total = len(LINKS)
    print(f"\n✅  Seed concluído!")
    print(f"   Total de links : {total}")
    print(f"   Inseridos      : {inseridos}")
    print(f"   Já existiam    : {ignorados}")
    print(f"\n   Agora rode 'make run' e acesse http://localhost:5000")
    print(f"   Os imóveis serão processados automaticamente ao abrir a página.\n")


if __name__ == "__main__":
    seed()
