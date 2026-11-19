"""
Helper CLI per usare `kalil0321/reverse-api-engineer` su Cardmarket.com.

Avvia la sessione interattiva di `reverse-api-engineer` installata nel `.venv`.
Scegli la modalità `manual` per aprire il browser su https://www.cardmarket.com/en/Pokemon,
cerca una carta Pokémon, apri la scheda prezzi/inserzioni, chiudi il browser e lascia che
`reverse-api-engineer` generi il client API.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
GENERATED_DIR = ROOT_DIR / "generated_client"


def _find_cli() -> str:
    venv_exe = Path(sys.executable).parent / "reverse-api-engineer.exe"
    if venv_exe.exists():
        return str(venv_exe)
    found = shutil.which("reverse-api-engineer")
    if found:
        return found
    raise FileNotFoundError(
        "Eseguibile `reverse-api-engineer` non trovato. "
        "Installa le dipendenze con: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
    )


def main() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    cli = _find_cli()

    print("=" * 68)
    print("  PokéMarket Scanner — Cattura Reverse-API per Cardmarket.com")
    print("=" * 68)
    print("1. Verrà avviata la sessione interattiva di `reverse-api-engineer`.")
    print("2. Scegli la modalità `manual` e vai su:")
    print("   https://www.cardmarket.com/en/Pokemon")
    print("3. Cerca una carta Pokémon e apri la sua scheda prezzi/inserzioni.")
    print("4. Chiudi il browser per generare il client API dal traffico HAR.")
    print("5. Esponi `search_card(name, card_number, set_name)` dentro:")
    print(f"   {GENERATED_DIR / 'cardmarket_client.py'}")
    print("   (Vedi generated_client/README.md per il formato atteso.)")
    print("=" * 68)
    print(f"\nAvvio: {cli}\n")

    subprocess.run([cli], cwd=str(ROOT_DIR), check=False)


if __name__ == "__main__":
    main()
