#!/usr/bin/env python3
"""Ponto de entrada da aplicação."""

from app.main import create_app

if __name__ == "__main__":
    app = create_app()
    print("\n🏠  Comparador de Imóveis — BH")
    print("   Acesse: http://localhost:5000\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
