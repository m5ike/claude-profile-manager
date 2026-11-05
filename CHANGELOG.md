# Historie verzí

## 1.4.0 – 2026-11-05

### Přidáno
- **xAI Grok Build CLI** (`grok`) jako pátý podporovaný nástroj: `tool-create/register/run/launchers/
  backup/restore/migrate/export/import grok …`, spouštěče `grok-NAZEV`, sekce v grafické aplikaci.
- Profil přes `GROK_HOME`; mimo původní `~/.grok` navíc `GROK_DISABLE_AUTOUPDATER=1`, aby si profily
  nestahovaly vlastní kopie programu. Ve výchozím stavu se odstraní `XAI_API_KEY`, `GROK_AUTH_*`,
  `GROK_OIDC_*`, `GROK_DEPLOYMENT_KEY` a `GROK_XAI_API_BASE_URL`.
- Hledání programu nejprve v `~/.grok/bin/grok` (oficiální instalátor), protože `brew install grok`
  je nesouvisející nástroj.
- Třídy migrace pro Grok (přihlášení `auth.json`, `agent_id`, `trusted_folders.toml`, `hooks-paths`;
  historie `sessions`, `memory*`; instalace programu a cache se nekopírují). Soubory `*.lock` jsou
  u všech nástrojů dočasné.
- End-to-end test se skutečným `grok` (spouští se, pokud je nainstalovaný).

### Ověřeno
- docs.x.ai/build/settings/reference a uživatelská příručka xai-org/grok-build (GROK_HOME, auth.json,
  proměnné prostředí); grok 1.0.70: nový `GROK_HOME` je odhlášený a původní `~/.grok/auth.json` zůstává beze změny.

## 1.3.0 – 2026-11-05

### Přidáno
- `tool-migrate` a `tool-migrate-backup`: kopírování nastavení a historie mezi profily Codex / Gemini /
  Copilot / opencode, nebo z importované zálohy. Výchozí je zkouška ve stagingu; `--apply --yes` zazálohuje
  cíl a zapíše transakčně. Přihlášení a uložená oprávnění jen s `--credentials`, logy a cache nikdy.
  Codex si v cíli ponechá vlastní `cli_auth_credentials_store`.
- `tool-export` / `tool-import`: přenosné archivy záloh nástrojů s kontrolním součtem SHA-256
  (stejné zabezpečení rozbalování jako u záloh Claude).
- Grafická aplikace: dialog Migrace, export a import záloh nástrojů.
- `gui/make-release.sh`: balíček vydání (skripty, aplikace, nápověda, kontrolní součty).

### Změněno
- Export/import archivů přepracován na sdílené pomocné funkce pro zálohy Claude i nástrojů.
- `.gitignore` ignoruje `.DS_Store` a `/dist/`.

## 1.2.0 – 2026-11-05

### Přidáno
- **Profily dalších AI CLI** – OpenAI Codex CLI, Google Gemini CLI, GitHub Copilot CLI a opencode.
  Nové příkazy `tool-list`, `tool-create`, `tool-register`, `tool-unregister`, `tool-set-binary`,
  `tool-auth-env`, `tool-launchers`, `tool-run`, `tool-backup`, `tool-verify`, `tool-restore`
  a spouštěče `codex-NAZEV`, `gemini-NAZEV`, `copilot-NAZEV`, `opencode-NAZEV`.
- Ověřené zálohy a transakční obnova profilů dalších nástrojů (`INSTALL_DIR/tool-backups`), kontrola běžících procesů.
- Kontrola překryvu kořenů mezi profily Claude a dalších nástrojů; recovery zahrnuje i jejich kořeny.
- Položka 18 v textové administraci.
- **Grafická aplikace pro macOS** (`gui/`, SwiftUI) včetně sekce „Další AI nástroje“, zobrazení verze aplikace
  i správce, upozornění na rozdílné verze a panelu O aplikaci.
- Uživatelská příručka `docs/Napoveda.pdf` (zdroj `docs/napoveda/`).

### Ověřeno proti dokumentaci (listopad 2026)
- Codex: `CODEX_HOME`, `cli_auth_credentials_store` (`file`/`keyring`/`auto`/`ephemeral`), `CODEX_API_KEY` – developers.openai.com/codex.
- Gemini CLI: `GEMINI_CLI_HOME` (vytváří `.gemini`), autentizační proměnné – geminicli.com/docs.
- Copilot CLI: `COPILOT_HOME`, `COPILOT_CACHE_HOME`, pořadí `COPILOT_GITHUB_TOKEN` > `GH_TOKEN` > `GITHUB_TOKEN` > klíčenka – docs.github.com.
- opencode: XDG adresáře config/data/state/cache – opencode.ai/docs; navíc ověřeno `opencode debug paths` (opencode 2.2.5).

## 1.1.0
- Typy profilů CLI / Desktop / obojí, aktualizátor `update.sh` s obnovou, editor nastavení.

## 1.0.0
- První verze: kombinované profily Claude CLI a Desktop, zálohy, migrace, kopírování projektů.
