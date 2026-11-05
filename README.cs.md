# Claude Profile Manager pro macOS

Samostatný správce profilů pro Claude Code CLI a Claude Desktop, verze 1.3.0. Přímé spuštění `claude-manager.py` otevře textovou administraci v terminálu; symlinky `claude-NAME` místo menu spustí skutečné Claude CLI s odpovídajícím `CLAUDE_CONFIG_DIR` a všemi původními argumenty.

Balíček nic sám neinstaluje do tvého Macu. Instalace vyžaduje macOS, Python 3.9+ a existující Claude CLI/Claude.app; vlastní správce používá pouze standardní knihovnu Pythonu a pro práci s GUI Git registry také systémový `git`.

## Bezpečnostní model a hranice

- **Žádné neohlášené přepisování:** výchozí migrace je dry-run a výchozí konflikt znamená chybu. Zápis potřebuje `--apply --yes`; editor nastavení potřebuje `--yes`.
- **Zálohy:** před zápisem migrace, obnovy i editace nastavení se vytváří a ověřuje záloha cíle. Kopie se kontrolují SHA-256 po jednotlivých souborech; zápis probíhá přes staging a journal.
- **Konzistentní zastavená data:** před datovými operacemi ukonči všechny CLI, Desktop a Code v editorech. Správce odmítá rozpoznané aktivní procesy a používá zámky; nedokáže však zabránit spuštění nezávislého procesu mimo wrapper nebo změnám jinými programy.
- **Přihlášení:** běžná migrace nekopíruje CLI `.credentials.json`, účtový `.claude.json`, GUI cookies, OAuth databáze ani Keychain. CLI credential soubor lze kopírovat jen explicitním `--credentials`; tím nesmíš předpokládat přenos celého macOS přihlášení.
- **Citlivé zálohy:** plná záloha naopak obsahuje i souborová přihlášení a historii. Má privátní nadřazený adresář, export soubor `600`, ale není šifrovaná; používej FileVault/šifrovaný disk a bezpečný přenos.
- **Souborová, ne systémová záloha:** kontrolují se datové soubory a symlinky. Keychain, macOS resource forks, ACL a veškerá rozšířená metadata nejsou garantovaně přenesená; nenahrazuje to Time Machine ani systémový snapshot.
- **Důvěra:** skills, pluginy, hooks a MCP mohou při pozdějším použití spouštět kód. Správce je sám nespouští, ale kopíruj je pouze z důvěryhodného zdroje a při přesunu mezi osobním a pracovním účtem respektuj oprávnění k datům.
- **Prostor na disku:** staging, automatické zálohy a staré transakční adresáře mohou vyžadovat několik násobků velikosti dat. Staré `.cm-old-*` se automaticky nemažou.

## Grafická aplikace pro macOS

Kromě textové administrace je k dispozici nativní okenní aplikace **Claude Profile Manager.app** (SwiftUI, macOS 13+), která nabízí všechny funkce správce – profily, spouštění, zálohy, migrace, projekty a diagnostiku – se stejnými pojistkami jako příkazová řádka. Sestavíš ji příkazem `gui/build-app.sh`; podrobnosti jsou v [gui/README.md](gui/README.md) a v uživatelské příručce [docs/Napoveda.pdf](docs/Napoveda.pdf).

## Další AI nástroje (od verze 1.2.0)

Stejným způsobem lze oddělovat profily dalších AI asistentů pro programování. Správce nastaví pro spuštěný proces zdokumentovanou proměnnou daného nástroje a ve výchozím stavu odstraní proměnné s klíči a tokeny, které by přebily účet přihlášený v profilu.

| Nástroj | Proměnné | Poznámka |
| --- | --- | --- |
| OpenAI Codex CLI | `CODEX_HOME` | Nový profil dostane `cli_auth_credentials_store = "file"`, přihlášení zůstává v `auth.json` profilu. |
| Google Gemini CLI | `GEMINI_CLI_HOME` (uvnitř `.gemini`) | Přihlášení Google účtem může být ve sdílené klíčence; API klíče jsou oddělené. |
| GitHub Copilot CLI | `COPILOT_HOME`, `COPILOT_CACHE_HOME` | Token je v klíčence podle účtu; v každém profilu použij `/login`. `GH_TOKEN` apod. se odstraňují. |
| opencode | `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, `XDG_CACHE_HOME` | Ověřeno `opencode debug paths`; XDG zdědí i podprocesy. |

```bash
"$CM" tool-create codex pracovni --yes
"$CM" tool-register copilot vychozi --dir "$HOME/.copilot" --yes
"$CM" tool-launchers codex pracovni      # vytvoří příkaz codex-pracovni
codex-pracovni                           # nebo: "$CM" tool-run codex pracovni
"$CM" tool-backup codex pracovni
"$CM" tool-list

# Migrace mezi profily stejného nástroje (nejprve zkouška, pak --apply --yes):
"$CM" tool-migrate codex osobni pracovni --components settings,history
"$CM" tool-migrate codex osobni pracovni --components settings,history --apply --yes

# Přenos na jiný Mac:
"$CM" tool-export "$INSTALL_DIR/tool-backups/ZALOHA" "$HOME/codex-transfer.tar.gz"
"$CM" tool-import "$HOME/codex-transfer.tar.gz" --sha256 "DOPLN_64_ZNAKU_SHA256"
"$CM" tool-migrate-backup "$INSTALL_DIR/tool-backups/import-XXXX" pracovni --apply --yes
```

Migrace kopíruje nastavení a volitelně historii; přihlašovací soubory a uložená oprávnění jen s `--credentials`, logy a cache nikdy.

Zálohy těchto profilů se ukládají do `INSTALL_DIR/tool-backups`, cache do `INSTALL_DIR/cache`. Podrobnosti a zdroje jsou v kapitole 5 příručky [docs/Napoveda.pdf](docs/Napoveda.pdf) a v [CHANGELOG.md](CHANGELOG.md).

## Instalace

Rozbal ZIP, otevři Terminál v rozbalené složce a spusť níže uvedené příkazy. Instalátor odmítne existující instalační adresář a neupravuje data Claude, přihlášení, shell ani `/Applications`.

```bash
chmod +x install.sh claude-manager.py
./install.sh "$HOME/.local/share/claude-profile-manager"

CM="$HOME/.local/share/claude-profile-manager/claude-manager.py"
"$CM"
```

`INSTALL_DIR` je adresář obsahující řídicí `claude-manager.py`, nikoli aktuální pracovní adresář. Po instalaci neměň jeho umístění, pokud už jsi vytvořil launchery; GUI aplikace obsahují absolutní cestu k řídicímu skriptu a Pythonu a je potřeba je po přestěhování znovu vygenerovat.

Alternativně můžeš používat správce přímo z rozbalené složky. Pak se tato složka stane `INSTALL_DIR`, proto ji nenechávej v dočasném adresáři.

## Aktualizace existující instalace

Rozbal NOVÝ balíček jinam než do existující instalace, ukonči Claude procesy a v nové rozbalené složce spusť aktualizátor. Použij stejný `INSTALL_DIR` jako doposud; instalátor `install.sh` existující instalaci záměrně nepřepisuje.

```bash
bash ./update.sh "$HOME/.local/share/claude-profile-manager" --yes
```

Aktualizátor ověří SHA-256 zdrojových souborů, získá zámky, zazálohuje nahrazované skripty, existující launchery, shellové konfigurace a registr profilů do `INSTALL_DIR/update-backups/…`. Poté atomicky nahrazuje jednotlivé soubory a přegeneruje launchery pouze pro aktivní typy profilů; profilové adresáře, historii a přihlášení nekopíruje ani nepřepisuje.

Opraví vlastní označené PATH bloky v `~/.profile` a `~/.zshrc`; existující `.zprofile`, `.zshenv`, `.bash_profile`, `.bashrc` a `.bash_login` zkontroluje také. Respektuje i explicitní `ZDOTDIR`, odstraňuje duplicitní celé bloky pro tuto instalaci a ostatní uživatelský obsah zachová; nové okno terminálu načte změny.

Neoznačené ruční exporty PATH nemaže. Pokud znáš předchozí umístění instalace, můžeš explicitně povolit odstranění jeho označených bloků; to nepřesouvá data ze starého adresáře.

```bash
bash ./update.sh "$HOME/.local/share/claude-profile-manager" --yes \
  --old-root "$HOME/stare-umisteni/claude-profile-manager"
```

Neúplný označený blok nebo symlink shellové konfigurace se automaticky neřeší, aby se nesmazal obsah či dotfile symlink. Pro aktualizaci pouze kódu bez zásahu do shellu použij `--skip-shell`; opravu takové konfigurace proveď až po kontrole ručně.

```bash
bash ./update.sh "$HOME/.local/share/claude-profile-manager" --yes --skip-shell
```

Při běžné chybě se aktualizace pokusí vrátit původní skripty a shellové soubory a novější kopie odloží do zálohy. Po výpadku nebo tvrdém ukončení, kdy zůstane `update-transaction.json`, aplikace profilové launchery v nové verzi zablokuje a obnovu spustíš ze stejného čistého nového balíčku; nepokračuj slepým mazáním journalu.

```bash
bash ./update.sh "$HOME/.local/share/claude-profile-manager" --recover --yes
```

Aktualizátor se nespouští s `sudo`, neprovádí systémové změny a nemění samotný Claude binary ani Claude.app. Staré registry verze 1.0 bez položky `kind` zůstávají platné a automaticky znamenají kombinované profily.

## Typy profilů

Profil může mít pouze CLI, pouze GUI, nebo obě konfigurace. Volbu lze provést v administračním menu při vytvoření/registraci, případně pomocí `--type`; pokud volbu vynecháš, zůstává kvůli kompatibilitě `both`.

```bash
CM="$HOME/.local/share/claude-profile-manager/claude-manager.py"
"$CM" create terminal --type cli --yes
"$CM" create desktop --type gui --yes
"$CM" create komplet --type both --yes
"$CM" launchers terminal
"$CM" launchers desktop
```

- **CLI-only:** vznikne jen CLI datový adresář a symlink; žádný GUI profil ani `.app`. Běžné spuštění CLI nevolá kontrolu procesů a může běžet současně s jinými CLI i Desktopem.
- **GUI-only:** vznikne jen GUI datový adresář a `.app`; žádný CLI datový adresář či symlink a není vyžadovaná instalace CLI binary. Launcher odstraní zděděný `CLAUDE_CONFIG_DIR`, místo aby GUI omylem navázal na jiný CLI profil.
- **Both:** vzniknou oba datové kořeny a oba launchery. U GUI nadále platí omezení interního prostředí Code popsaná níže.

Rozsah operace `both` znamená všechny povolené části daného profilu: pro CLI-only pouze CLI. Explicitní požadavek na chybějící část skončí srozumitelnou chybou; při migraci profilů s různými typy zvol společný `--scope cli` nebo `--scope gui`.

Existující profil lze přepnout na jiný typ, aniž by se smazala vypnutá data. Před změnou vznikne záloha aktivních kořenů, vypnuté cesty se uloží do `disabled_roots` a při opětovném zapnutí se použijí původní cesty.

```bash
"$CM" set-type komplet cli --yes
"$CM" set-type komplet both --yes
```

Dříve vytvořené launchery vypnuté části zůstávají na disku, ale jejich spuštění nová verze odmítne bez vytvoření profilu. Aktualizátor přegeneruje jen launchery aktivních částí; staré vypnuté ikony můžeš po ověření odstranit ručně.

## První nastavení

Nejprve zjisti skutečné umístění Claude CLI a nastav je jako absolutní cestu. Nesmí to být symlink na tohoto správce; kontrola brání rekurzi wrapperu.

```bash
command -v claude

CM="$HOME/.local/share/claude-profile-manager/claude-manager.py"
"$CM" set-binary "/absolutni/cesta/ke/skutecnemu/claude"
"$CM" create osobni --yes
"$CM" create pracovni --yes
"$CM" launchers osobni
"$CM" launchers pracovni
"$CM" path
"$CM" path --write --yes
"$CM" doctor
```

`path` nejprve vypíše stav. S `--write --yes` zálohuje existující rc soubor a přidá idempotentní blok do `~/.zshrc` pro Zsh, jinak do `~/.profile`; ostatní obsah zachová. Otevři nové okno terminálu, aby se změna projevila.

Stav PATH se kontroluje a vypisuje také při generování launcherů. Samotné generování shell rc bez svolení neupravuje; potřebný zápis potvrď v administraci nebo přes `path --write --yes`.

Vytvoří se tato struktura; registry a privátní zálohy mají záměrně společný chráněný nadřazený adresář:

```text
INSTALL_DIR/
├── claude-manager.py
├── manager.json
├── sbin/
│   ├── claude-osobni  -> ../claude-manager.py
│   └── claude-pracovni -> ../claude-manager.py
├── data/
│   ├── claude-osobni/
│   └── claude-pracovni/
├── Applications/
│   ├── Claude osobni.app/
│   └── Claude pracovni.app/
├── backups/
├── locks/
├── receipts/
└── shell-backups/

~/Library/Application Support/
├── Claude-osobni/
└── Claude-pracovni/
```

## Běžné spouštění

CLI symlink neparsuje argumenty Claude a přebírá sezení přes `execve`. Stdin, stdout i stderr zůstávají přímo připojené k původním deskriptorům, takže fungují TTY, interaktivní zadávání, pipes, signály a návratový kód bez ztrát způsobených tee/thread wrapperem.

```bash
claude-osobni
claude-pracovni --resume
claude-pracovni --print "Zkontroluj projekt"
printf 'Shrň tento vstup\n' | claude-osobni --print

# Stejný launch bez symlinku:
"$CM" cli osobni --resume

# Nativní zacházení se stderr:
claude-osobni --print "Test" 2>"$HOME/claude-errors.log"
```

Správce zpracuje vlastní chyby spuštění přes stderr; diagnostiku samotného Claude nepřepisuje a nefiltruje. Ve výchozím stavu odstraní zděděné hlavní autentizační a provider přepínače prostředí, aby například `ANTHROPIC_API_KEY` potichu nepřebil zvolený přihlášený účet.

Chceš-li v konkrétním profilu záměrně používat klíče nebo cloudové provider proměnné z rodičovského shellu, zapni dědění explicitně. Klíč se neukládá do `manager.json`.

```bash
"$CM" auth-env pracovni inherit
# Návrat k oddělení účtů:
"$CM" auth-env pracovni clean
```

GUI spustíš dvojklikem na `INSTALL_DIR/Applications/Claude osobni.app` nebo příkazem níže. App bundle lze připnout do Docku či otevřít přes Finder; nevytváří druhou kopii Claude.app a nepřidává login item.

```bash
"$CM" gui osobni

# Jiná instalace aplikace:
"$CM" set-gui-app "$HOME/Applications/Claude.app"
```

GUI launcher kontroluje duplicitní hlavní proces se stejným `--user-data-dir`. Při jiné aktivní desktopové instanci konzervativně odmítne přepnutí, aby se nepromíchaly přihlašovací callbacky; pokud už daný GUI profil běží, vrátí úspěch bez dalšího `open`. Samostatné běžící CLI GUI launcher neblokuje; zámek kombinovaného profilu ale chrání kolidující spouštění přes tentýž profil.

CLI wrapper při běžném spuštění žádný seznam procesů nekontroluje a neblokuje se kvůli Desktopu. Kontrola procesů a exkluzivní profilové zámky zůstávají pro zálohování, obnovu, migraci, editaci nastavení, změnu typu a jiné zásahy do dat; sdílený runtime zámek brání spuštění během takového zásahu.

Používá tvar `/usr/bin/open -n -a /Applications/Claude.app --args --user-data-dir=...` a po `open` čeká na potvrzení hlavního procesu. Jinou cestu k aplikaci lze nastavit příkazem `set-gui-app`.

## Existující výchozí data a editor nastavení

Než cokoli migruješ, ukonči všechna Claude sezení. Výchozí profil můžeš zaregistrovat bez kopírování a bez změny obsahu; soubor `~/.claude.json` vedle standardního adresáře se zohledňuje při záloze, obnově a přenosu přenositelných MCP nastavení.

```bash
"$CM" register puvodni \
  --cli-dir "$HOME/.claude" \
  --gui-dir "$HOME/Library/Application Support/Claude" \
  --yes
"$CM" backup puvodni --scope both
```

Při registraci pouze CLI vynech GUI cestu a přidej `--type cli`; pro GUI-only analogicky `--type gui`. Žádná nepoužitá část se při registraci nedovytváří.

Používej pouze jednu registraci pro každou skutečnou cestu. Překrývající se kořeny profilů, root symlinky nebo systémové/nadřazené adresáře správce odmítá, místo aby jejich obsah začal přepisovat.

Nastavení lze změnit v administraci nebo bezpečně přes `$EDITOR`. Editor pracuje ve stagingu; neplatný JSON nebo neúspěšné ukončení editoru se nepromítne do skutečného profilu.

```bash
EDITOR=nano "$CM" edit-settings osobni --scope cli --yes
EDITOR=nano "$CM" edit-settings osobni --scope gui --yes
```

## Migrace mezi profily

Rozsah `cli`, `gui` nebo `both` určuje, které lokální datové stromy se mění. Neznamená převod CLI do GUI či naopak; GUI záznamy se nepokoušíme vymýšlet ze samotného CLI transcriptu.

Nejprve spusť dry-run. Ten připraví a ověří staging, ale nepřepne kořeny profilů; může potřebovat značný prostor a při kopírování je vidět pouze dočasný skrytý adresář.

```bash
"$CM" migrate puvodni osobni \
  --scope cli \
  --components settings,skills,plugins,history

# Teprve po kontrole výsledku:
"$CM" migrate puvodni osobni \
  --scope cli \
  --components settings,skills,plugins,history \
  --apply --yes
```

Při rozdílných cílových souborech výchozí `--conflict error` celou operaci zastaví. `keep` zachová cílový konflikt a `replace` ho nahradí zdrojem; jde o explicitní volbu, nikoli odhad podle času změny.

```bash
"$CM" migrate osobni pracovni --scope cli \
  --components skills,plugins --conflict replace

"$CM" migrate osobni pracovni --scope cli \
  --components skills,plugins --conflict replace --apply --yes
```

CLI složky `skills`, `plugins`, instrukce, agents, rules a historie se přenášejí podle zvolené komponenty. Osobní `.claude.json` se nepřenáší celý; pro `settings` se přenášejí pouze jeho `mcpServers`, aby se nepřekopíroval účet nebo projektová důvěra.

Komponenta `skills` zahrnuje i legacy `commands`. Zapnutí pluginů v `enabledPlugins` je součást `settings.json`, proto pro plný přenos aktivace zvol současně `plugins,settings`; samotné `plugins` přenese instalace a registry, ne přepínače aktivace.

Pluginové registry a JSON/JSONL cesty se přepisují pouze při přesné shodě nebo cestovém prefixu. Shellové příkazy, neprůhledné databáze a náhodné podřetězce se nepřepisují; plugin s externím linkem vyžaduje zvláštní kontrolu a samotné zkopírování není zárukou jeho funkčnosti.

Pro divergentní JSONL historie správce záměrně nedělá automatický řádkový merge. `replace` může zahodit cílovou větev v aktivním profilu, ale její předchozí stav bude v automatické záloze; pro současnou práci používej rozdílná sezení.

## GUI historie a rozdělaná práce

Před migrací GUI historie spusť cílový GUI profil, přihlas se jeho účtem, otevři Code alespoň jednou a znovu vše ukonči. Správce vyžaduje jednoznačný lokální `claude-code-sessions/<account>/<org>` index a kontroluje identitu souborů `local_*.json`; neznámý či víceznačný stav odmítne.

```bash
"$CM" migrate puvodni osobni \
  --scope both \
  --components settings,skills,plugins,history \
  --workspaces

# Až po kontrole:
"$CM" migrate puvodni osobni \
  --scope both \
  --components settings,skills,plugins,history \
  --workspaces --apply --yes
```

- **GUI účty:** u přenášených sezení se zdrojová remote-MCP a bridge oprávnění nepřebírají; zachovají se cílová nebo bezpečné výchozí hodnoty. GUI OAuth, cookies, routines a účtové preferences se při komponentové migraci nepřenášejí.
- **Scratch práce:** s `--workspaces` se přenášejí `scratch-workspaces` a případná legacy `scratch`; cesty se přemapují na cílový profil ještě před přepnutím dat.
- **Git worktrees:** podporovaný lokální registr má `schemaVersion: 2`. Správce kontroluje jméno, cestu, lease, existující Git checkout a konfliktní aktivní sezení; neprovádí `checkout`, `reset`, `clean`, úpravu `.git` pointerů ani `git worktree remove`.
- **Backing transcripts:** u sezení s `cliSessionId` se kontroluje odpovídající jednoznačný transcript v `~/.claude/projects`. Pokud chybí, migrace skončí chybou; nejprve přenes CLI historii do registrovaného výchozího profilu.
- **Starší schéma:** u záznamu bez `cliSessionId` se vrátí výslovné varování, že ověření backing transcriptu není možné. Takové sezení nelze označit za ověřeně obnovitelné bez testu v aplikaci.

Pokud GUI používá společné výchozí transcript úložiště, můžeš do něj přenést historii takto. Data na tomto místě mohou být viditelná i ostatním účtům Desktopu na stejném macOS uživateli, proto to nedělej pro projekty, které nesmějí být sdílené.

```bash
"$CM" migrate osobni puvodni --scope cli --components history
# Po kontrole konfliktů a obsahu:
"$CM" migrate osobni puvodni --scope cli --components history --apply --yes
```

Každé GUI sezení po přenosu skutečně otevři a ověř několik starších zpráv, poslední rozpracovaný stav, `cwd`, větev a aktivní účet. Přítomnost názvu v seznamu není důkazem funkčního pokračování.

## Kopírování projektů a přesun cest

`project-add` eviduje existující projekt, aniž by ho kopíroval. `project-copy` vytvoří nový adresář a ověří kopii včetně běžných untracked/dirty souborů a samostatného `.git` adresáře; existující cílový adresář nikdy nepřepíše.

```bash
"$CM" project-add osobni "$HOME/Developer/moje-aplikace"

"$CM" project-copy pracovni \
  "$HOME/Developer/moje-aplikace" \
  "$HOME/Developer/moje-aplikace-pracovni"

"$CM" project-copy pracovni \
  "$HOME/Developer/moje-aplikace" \
  "$HOME/Developer/moje-aplikace-pracovni" --apply --yes
```

Kopírování projektu s `.git` souborem, například linked worktree nebo submodule, je záměrně odmítnuto: slepé zkopírování by dál ukazovalo do původního repozitáře. Externí projektové symlinky a aktivní Git locky také vyžadují ruční řešení; projekt nesmí v průběhu kopie měnit editor, build ani server.

Odmítnuté jsou i vnořené `.git` pointery, explicitní `core.worktree`, registry dalších linked worktrees a externí Git object alternates. Absolutní projektové odkazy dovnitř zdrojového projektu se v nové kopii převedou na relativní, aby dál nesměřovaly na původní soubory.

Historii lze při migraci přesměrovat explicitním `--map`. Přepíšou se rozpoznané přesné cestové hodnoty a známé projektové adresáře odvozené ze zakódované cesty; běžný text, skripty a neprůhledné cache zůstanou beze změny.

```bash
"$CM" migrate osobni pracovni --scope cli --components history \
  --map "$HOME/Developer/moje-aplikace=$HOME/Developer/moje-aplikace-pracovni"

# Po kontrole přidej --apply --yes.
```

## Zálohy, přenos na jiný Mac a obnova

Příkaz backup vypíše přesnou cestu nového privátního adresáře. Níže uvedené `BACKUP`, `IMPORTED` a kontrolní součet doplň skutečnými hodnotami; nejde o předvyplněné existující cesty.

```bash
"$CM" backup osobni --scope both
BACKUP="/presna/cesta/z/vystupu/backup"
"$CM" verify "$BACKUP"
"$CM" export "$BACKUP" "$HOME/claude-osobni-transfer.tar.gz"
```

Export vytvoří vedle archivu také `.sha256` soubor. Absolutní linky dovnitř stejného datového stromu převede v exportu na relativní; externí symlinky odmítne, protože bez jejich cílů by přenos nebyl samostatný a bezpečný.

Přenes archiv bezpečnou cestou na druhý Mac a ověř hash z důvěryhodného kanálu. SHA-256 zjišťuje poškození, ale nepodepisuje autora archivu; archiv z neznámého zdroje nepoužívej.

```bash
"$CM" import "$HOME/claude-osobni-transfer.tar.gz" \
  --sha256 "DOPLN_64_ZNAKU_SHA256"

IMPORTED="/presna/cesta/z/vystupu/import"
"$CM" create novy --yes
"$CM" migrate-backup "$IMPORTED" novy --scope cli \
  --components settings,skills,plugins,history
"$CM" migrate-backup "$IMPORTED" novy --scope cli \
  --components settings,skills,plugins,history --apply --yes
```

`import` pouze ověří a bezpečně rozbalí zálohu do správce, nic nepřepisuje v profilu. Odmítá path traversal, hardlinky, devices, externí symlinky a překročení extrakčních limitů; `migrate-backup` následně přenáší vybraná data, přemapuje původní kořeny a nechá cílové přihlášení beze změny.

Projektové zdrojové adresáře nejsou automatickou součástí profilové zálohy, pokud leží mimo profil. Přenes je samostatně před migrací historie a použij `--map /stara/cesta=/nova/cesta`; pro GUI nejprve inicializuj jeho účet/org index a doplň backing transcripts do výchozího úložiště.

Přesná obnova snapshotu je odlišná operace. Vyžaduje stejné původní kořenové cesty, obnovuje i souborová přihlašovací data a předem vytvoří zálohu aktuálního stavu; Keychain nezálohuje a platnost tokenů negarantuje.

```bash
"$CM" restore osobni "$BACKUP" --scope both --yes
```

## Přerušená transakce a úklid

Při zjištění `transaction.json` správce odmítne další zápisy i launchery. Po ukončení všech Claude procesů spusť recovery, které podle trvanlivého journalu dokončí evidenci potvrzeného commitu nebo vrátí původní kořeny; novější/staged data se při recovery záměrně nemažou.

```bash
"$CM" doctor
"$CM" recover
```

Přepnutí více kořenů není jedna atomická operace filesystému; journal a zálohy řeší návrat, nikoli nemožnost výpadku. Nemaž ručně `transaction.json`, `.cm-old-*`, `.cm-stage-*` nebo `.cm-recovered-*`, dokud nezkontroluješ receipts a ověřenou zálohu.

Automatický garbage collection zde není úmyslně. Po úspěšné kontrole sezení, projektů a záloh můžeš konkrétní staré adresáře odložit na šifrovaný disk nebo odstranit ručně; neodstraňuj je hromadným wildcard příkazem.

Odinstalace není automatická: nejprve exportuj ověřené zálohy, ukonči všechna sezení, odeber jen označený PATH blok ze shell rc a přesuň `INSTALL_DIR` do bezpečné archivní složky. GUI datové kořeny mohou být mimo něj a nemažou se spolu s instalací.

## Co není garantované

`CLAUDE_CONFIG_DIR` je dokumentovaný override pro CLI konfiguraci, projekty a pluginy, včetně umístění `.claude.json` při vlastním adresáři ([oficiální přehled adresáře](https://code.claude.com/docs/en/claude-directory)).

Desktopový `--user-data-dir` a interní GUI session/worktree soubory nejsou stabilní veřejné migrační API. Tvar profilu vychází z komunitně popsaného chování a zdrojového kódu správce profilů; aktualizace Claude může kompatibilitu změnit ([referenční projekt](https://github.com/erorplex/claude-desktop-profiles-macos)).

Nastavení `CLAUDE_CONFIG_DIR` v prostředí procesu `open` není záruka, že jej LaunchServices a interní Code proces Desktopu převezmou. Správce proto neslibuje úplnou izolaci lokální Code konfigurace uvnitř GUI; před ostrou prací ověř konkrétní verzi Desktopu a počítej s možným společným `~/.claude`.

GUI Customize skills/plugins a cloudová historie nejsou totožné s lokální CLI konfigurací; lokální filesystem migrace je mezi účty automaticky nezpřístupní ([oficiální Desktop dokumentace](https://code.claude.com/docs/en/desktop)).

Testy tohoto balíčku používají izolovaná data a mock pro macOS GUI. Nejde o plné ověření běhu skutečného Claude Desktop na konkrétním Macu a žádný test zde nečte tvé skutečné přihlášení nebo konverzace.

## Testy

Testovací sada pokrývá správu cest, konflikty, integritu záloh, archivové útoky, recovery po selhání rename, přesný přenos parametrů a proudů, TTY, zámek přetrvávající přes `exec`, GUI duplicate guard, portable plugin linky, worktree registry a editaci nastavení. Spustíš ji bez závislostí:

```bash
./run-tests.sh
# Nebo jednotlivě:
python3 -m unittest discover -s tests -v
python3 -m py_compile claude-manager.py update.py tests/test_manager.py tests/test_update.py
bash -n install.sh
bash -n update.sh
```

Kompletní sadu doporučuji spustit také na tvém macOS ještě před registrací reálných profilů. Následně proveď pilot s prázdným CLI a GUI profilem; žádná sada mock testů nezaručuje kompatibilitu všech budoucích verzí Claude.
