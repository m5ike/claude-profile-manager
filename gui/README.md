# Claude Profile Manager – grafická aplikace pro macOS

Nativní okenní aplikace (SwiftUI, macOS 13+) nad `claude-manager.py` – profily Claude Code a Claude Desktop i dalších AI CLI (Codex, Gemini, Copilot, opencode). Verze aplikace se přebírá z `VERSION` v `claude-manager.py`. Veškerá logika – dry-run, zámky, kontrola procesů, ověřené zálohy, staging a journal – zůstává v Python backendu; aplikace jen sestavuje argumenty, spouští příkazy a zobrazuje jejich JSON výstup. Každý provedený příkaz je vidět v **Protokolu činností**.

Kompletní uživatelská příručka: [`docs/Napoveda.pdf`](../docs/Napoveda.pdf) (v aplikaci **Nápověda → ⌘?**).

## Sestavení

```bash
cd gui
./build-app.sh
open "build/Claude Profile Manager.app"
```

Vyžaduje Xcode nebo Command Line Tools (Swift 5.9+). Skript vytvoří ikonu, přibalí `docs/Napoveda.pdf` a aplikaci podepíše ad-hoc.

## Struktura

| Soubor | Účel |
| --- | --- |
| `ManagerClient.swift` | Spouštění `claude-manager.py`, čtení manifestů záloh |
| `Store.swift` | Stav aplikace, protokol, vysokoúrovňové akce |
| `ContentView.swift` | Okno, postranní panel, sdílené komponenty |
| `OverviewView.swift` | Přehled, uvítací obrazovka, nastavení aplikace |
| `ProfileDetailView.swift` | Detail profilu a editor nastavení |
| `BackupsView.swift` | Zálohy, obnova, export, import |
| `MigrationView.swift` | Migrace se zkouškou nanečisto |
| `ProjectsView.swift` | Evidence a kopírování projektů |
| `ToolsView.swift` | Profily Codex / Gemini / Copilot / opencode |
| `EnvironmentView.swift` | Claude binary, Claude.app, PATH, diagnostika, protokol |
| `Snapshot.swift` | Generování screenshotů pro dokumentaci |

## Poznámky k implementaci

- **CLI spuštění** otevírá Terminál (`.command` soubor), protože Claude CLI potřebuje skutečné TTY.
- **Editor nastavení** volá `edit-settings … --yes` s `EDITOR="/bin/cp <připravený soubor>"`. Backend tak dál dělá zálohu, staging, validaci JSON a transakci.
- **Migrace / kopie projektu**: tlačítko pro zápis je aktivní jen po úspěšném dry-runu se shodnými argumenty.

## Screenshoty pro dokumentaci

```bash
"build/Claude Profile Manager.app/Contents/MacOS/ClaudeProfileManager" \
  -scriptPath /cesta/k/claude-manager.py -snapshotDir /tmp/shots -snapshotAppearance light
../docs/napoveda/build-pdf.sh   # HTML → PDF (Google Chrome + Swift)
```

Snapshot režim vykreslí vlastní okno aplikace do PNG (nepotřebuje oprávnění Nahrávání obrazovky) a aplikaci ukončí. Doporučujeme ho spouštět nad testovací instalací, ne nad reálnými profily.
