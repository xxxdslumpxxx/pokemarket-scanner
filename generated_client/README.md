# Client generato da `reverse-api-engineer`

Quando esegui:
```powershell
.\.venv\Scripts\python.exe scripts\capture_cardmarket.py
```
`reverse-api-engineer` aprirà un browser su `https://www.cardmarket.com/en/Pokemon`, catturerà il traffico HAR durante la tua navigazione e genererà un client Python.

Per collegarlo automaticamente alla webapp **PokéMarket Scanner**, assicurati che il file `generated_client/cardmarket_client.py` esponga una funzione:

```python
def search_card(name: str, card_number: str | None = None, set_name: str | None = None) -> dict:
    return {
        "url": "https://www.cardmarket.com/en/Pokemon/Products/Singles/...",
        "listings": [
            {
                "seller": "NomeVenditore",
                "country": "IT",
                "condition": "NM",
                "language": "Italian",
                "is_foil": False,
                "price": 12.50,
            }
        ],
    }
```

Appena questo file è presente, il backend lo rileva in automatico e calcola **Più basso**, **Valore Medio** e **Più alto** direttamente dalle inserzioni live di Cardmarket!
