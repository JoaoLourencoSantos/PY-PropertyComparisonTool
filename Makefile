# ── Comparador de Imóveis — Makefile (Linux/WSL) ──────────────────────────
VENV   = venv
PIP    = pip
PYTHON = python3

.PHONY: help venv install playwright seed run clean reset

help:
	@echo ""
	@echo "  Comparador de Imoveis — comandos disponíveis:"
	@echo "  ------------------------------------------------"
	@echo "  make venv        Cria o ambiente virtual Python"
	@echo "  make install     Instala as dependências no venv"
	@echo "  make playwright  Baixa o Chromium para o Playwright"
	@echo "  make seed        Importa os links de imóveis no banco"
	@echo "  make run         Sobe o servidor em http://localhost:5000"
	@echo "  make clean       Remove o banco imoveis.db"
	@echo "  make reset       Remove venv + banco (recomeço total)"
	@echo ""

## 1. Cria o ambiente virtual
venv:
	python3 -m venv $(VENV)
	@echo "[OK] venv criado — rode: make install"

## 2. Instala dependências
install: venv
	$(PIP) install --upgrade pip
	$(PIP) install --ignore-installed -r requirements.txt
	@echo "[OK] Dependências instaladas — rode: make playwright"

## 3. Baixa o Chromium (necessário para o scraper)
playwright:
	$(PYTHON) -m playwright install chromium
	@echo "[OK] Chromium instalado — rode: make seed && make run"

## 4. Importa os links no banco
seed:
	$(PYTHON) seed_links.py

## 5. Sobe o servidor
run:
	$(PYTHON) run.py

## 6. Remove o banco
clean:
	rm -f imoveis.db
	@echo "[OK] Banco removido."

## 7. Reset completo
reset: clean
	rm -rf $(VENV)
	@echo "[OK] venv removido. Rode: make install"
