# ── Comparador de Imóveis — Makefile (Linux/WSL) ──────────────────────────
VENV   = venv
PIP    = pip
PYTHON = python3

.PHONY: help venv install playwright seed run run-turso clean reset

help:
	@echo ""
	@echo "  Comparador de Imoveis — comandos disponíveis:"
	@echo "  ------------------------------------------------"
	@echo "  make venv        Cria o ambiente virtual Python"
	@echo "  make install     Instala as dependências no venv"
	@echo "  make playwright  Baixa o Chromium para o Playwright"
	@echo "  make seed        Importa os links de imóveis no banco"
	@echo "  make run         Sobe o servidor local (SQLite)"
	@echo "  make run-turso   Sobe o servidor local apontando para o Turso"
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

## 5. Sobe o servidor (SQLite local)
run:
	$(PYTHON) run.py

## 5b. Sobe o servidor apontando para o Turso (produção)
run-turso:
	TURSO_URL="libsql://propertycomparisontool-joaolourencosantos.aws-us-east-1.turso.io" \
	TURSO_TOKEN="eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3Nzc1NjQ4NTksImlkIjoiMDE5ZGRlZjktMDEwMS03YmFmLWJmNGItMjRhZWU0YWQyMWQ4IiwicmlkIjoiYWJhODVhMjEtMDkxYi00ZTUyLTg4ZTUtNGM3NDY3NDg0ZGQ2In0.dy1Mc7g35v5c982mj80O_Xn6EpwIV_N18cyFqxK7ujr2sgP6xfB4S9oD5IAfmNAl2meZah5DzLF-8IPCnLx3Cw" \
	$(PYTHON) run.py

## 6. Remove o banco
clean:
	rm -f imoveis.db
	@echo "[OK] Banco removido."

## 7. Reset completo
reset: clean
	rm -rf $(VENV)
	@echo "[OK] venv removido. Rode: make install"
