# screensaverspecial

Windows kassza kijelzővédő / special screensaver alkalmazás.

## Mire való?

A program csak a kiválasztott kasszaprogram ablakát figyeli. Ha annak képe a beállított ideig nem változik, teljes képernyőn megjelenít egy kiválasztott képet a kiválasztott monitoron. Ha a kasszaprogram képe megváltozik, a kép automatikusan eltűnik.

Ez azért hasznos, mert a másik monitoron futó mozgó böngészős reklám nem zavarja meg a működést.

## Telepítés

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Indítás

```bat
python screensaver_special.py
```

## Beállítható a felületen

- kasszaprogram ablak kiválasztása
- ablakcím részlete, például `Juta`, `Micra`, `Jota`
- kijelzővédő kép kiválasztása
- cél monitor kiválasztása
- tétlenségi idő
- ellenőrzési gyakoriság
- változásérzékenység
- automatikus monitorozás indításkor

## Javasolt kasszás beállítás

- Ellenőrzés gyakorisága: `0.25`
- Tétlenségi idő: `60`
- Változásérzékenység: `3.0`
- Változás után látható idő: `2.0`
