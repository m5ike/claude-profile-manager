# Historie verzí

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
