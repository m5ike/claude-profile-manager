# Claude Profile Manager 1.1.0: testovací protokol

Aktualizace přidává profily CLI-only / GUI-only / both, neblokující běžný CLI launch a zálohovaný aktualizátor se shell PATH opravou. Kontroly probíhají pouze v izolovaném cloudovém sandboxu, nikoli na uživatelově Macu.

## Rozsah testů

Testovací sada zahrnuje původní CLI, zálohovací a migrační scénáře a novou sadu `tests/test_update.py`. Všechny fixture profily i jejich konverzace a účty jsou umělé; skutečný Claude binary a skutečný macOS Desktop se nespouští.

- **Původní funkce:** předání argumentů, stdin/stdout/stderr a návratového kódu přes symlink/exec; skutečné TTY; zámek přes exec; integrita záloh; konflikty; mapování cest; archivové útoky; bezpečné projektové kopie; GUI metadata a worktree registry; recovery po chybách zápisu.
- **Samostatné typy:** CLI-only nevytvoří GUI kořen nebo `.app`; GUI-only nevytvoří CLI kořen či symlink a nevyžaduje CLI binary ani shell rc pro generování launcheru.
- **Rozsahy:** backup/restore/migrate/import pro jednostranné profily, jasná chyba pro vypnutý typ, explicitní společný scope při migraci různých typů.
- **Procesy:** běžný CLI launch nevolá procesový scanner ani při aktivním Desktopu; datová operace ho stále volá. Metadata launcherů neblokuje samotný runtime profilový zámek; GUI-only ignoruje nezávislé CLI.
- **Kompatibilita:** registry bez `kind` zůstávají kombinované; přepnutí typu uchová vypnuté adresáře i obsah a umí je znovu zapnout.
- **Aktualizátor:** ověří kandidáta před spuštěním kódu, odmítne změněný payload, zachová profilová data a přesný registr, regeneruje vlastněné launchery s cestou na instalovaný řídicí skript.
- **Shell konfigurace:** idempotentně opraví duplicitní/stará ohraničená PATH nastavení, zachová ostatní obsah, řeší explicitní old-root, odmítne neúplný blok a symlinky; podporuje `--skip-shell`.
- **Návrat aktualizace:** simulované selhání regenerace launcherů vrátí původní skripty a rc soubory; interrupted-update journal blokuje nové launchery; recovery vrátí rozpracovanou aktualizaci, ale nevrací už potvrzený commit.

## Opakování testů

Kompletní sadu spouští skript níže dvakrát po sobě, poté ověří Python a Bash syntaxi. Každý průchod obsahuje 109 testů; finální výsledek je uveden v přiloženém `test-output.txt`.

```bash
bash ./run-tests.sh
```

Samostatně se kontroluje syntaxe všech Bash bloků českého návodu. Balíček obsahuje SHA-256 manifest, takže lze zkontrolovat také identitu zabalených souborů; kontrolní součet sám o sobě nenahrazuje důvěryhodný původ či digitální podpis.

## Upgrade původního vydání

Proběhl také samostatný smoke test ze skutečného původního ZIPu 1.0.0: starý instalátor vytvořil instalaci v cestě s mezerami, původní skript vytvořil kombinovaný profil a launchery a nový aktualizátor ji převedl na 1.1.0. SHA-256 registru před a po aktualizaci zůstal shodný.

V aktualizované instalaci se následně vytvořily samostatné CLI a GUI profily. Ověřila se absence nepovolených druhých kořenů i úspěšné opakované spuštění aktualizátoru; šlo opět o souborový test v sandboxu, ne o spuštění skutečné aplikace na Macu.

## Hranice ověření

macOS LaunchServices, Finder, Keychain a skutečné účtové přihlášení nebyly v sandboxu dostupné. GUI scénáře jsou testy s mocky a datovými fixtures; před ostrým nasazením je potřeba izolovaný pilot na konkrétní verzi macOS a Claude Desktop.

Nejde o audit třetí stranou ani garanci nulové ztráty při libovolném výpadku nebo souběhu procesů mimo wrapper. Aktualizátor používá svůj vlastní journal a zálohy souborů, nikoli systémový snapshot; při nejasném stavu odmítá pokračovat a vyžaduje recovery.
