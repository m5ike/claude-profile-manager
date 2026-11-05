# Historie verzí

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
