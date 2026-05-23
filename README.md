# screensaverspecial

Windows kassza kijelzővédő / special screensaver alkalmazás.

## Mire való?

A program csak a kiválasztott kasszaprogram ablakát figyeli. Ha annak képe a beállított ideig nem változik, teljes képernyőn megjelenít egy kiválasztott képet a kiválasztott monitoron. Ha a kasszaprogram képe megváltozik, a kép automatikusan eltűnik.

Ez azért hasznos, mert a másik monitoron futó mozgó böngészős reklám nem zavarja meg a működést.

## Telepítés fejlesztői módban

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Indítás fejlesztői módban

```bat
python screensaver_special.py
```

## EXE készítése Windows alatt

A repóban van egy egyszerű build script:

```bat
build_exe.bat
```

Ez létrehozza a virtuális környezetet, telepíti a függőségeket, majd elkészíti az EXE fájlt.

Az elkészült fájl helye:

```text
dist\ScreenSaverSpecial.exe
```

## EXE készítése GitHub Actions-szel

A repó tartalmaz egy workflow-t is:

```text
.github/workflows/build-windows-exe.yml
```

GitHubon az **Actions** fülön a **Build Windows EXE** workflow manuálisan is indítható a **Run workflow** gombbal. A kész EXE az artifactok között jelenik meg `ScreenSaverSpecial-windows-exe` néven.

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
