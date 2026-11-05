import Foundation

/// Profile type as stored in manager.json (`kind`). Missing kind means `both` (v1.0 compatibility).
enum ProfileKind: String, CaseIterable, Identifiable, Codable {
    case cli, gui, both
    var id: String { rawValue }

    var title: String {
        switch self {
        case .cli: return "Pouze CLI"
        case .gui: return "Pouze Desktop (GUI)"
        case .both: return "CLI + Desktop"
        }
    }

    var symbol: String {
        switch self {
        case .cli: return "terminal"
        case .gui: return "macwindow"
        case .both: return "square.split.2x1"
        }
    }

    var hasCLI: Bool { self != .gui }
    var hasGUI: Bool { self != .cli }
}

/// Data scope for backup / restore / migration.
enum Scope: String, CaseIterable, Identifiable {
    case cli, gui, both
    var id: String { rawValue }
    var title: String {
        switch self {
        case .cli: return "CLI"
        case .gui: return "Desktop"
        case .both: return "Obojí"
        }
    }
}

enum ConflictPolicy: String, CaseIterable, Identifiable {
    case error, keep, replace
    var id: String { rawValue }
    var title: String {
        switch self {
        case .error: return "Zastavit při konfliktu (bezpečné)"
        case .keep: return "Ponechat cílový soubor"
        case .replace: return "Nahradit zdrojem"
        }
    }
}

enum Component: String, CaseIterable, Identifiable {
    case settings, skills, plugins, history
    var id: String { rawValue }
    var title: String {
        switch self {
        case .settings: return "Nastavení (settings, CLAUDE.md, rules, agents, MCP)"
        case .skills: return "Skills a commands"
        case .plugins: return "Pluginy (instalace a registry)"
        case .history: return "Historie (projekty, sezení, todos, plány)"
        }
    }
}

struct Profile: Identifiable, Hashable {
    let name: String
    let kind: ProfileKind
    let cliDir: String?
    let guiDir: String?
    let projects: [String]
    let inheritAuthEnv: Bool
    let readOnly: Bool
    let disabledRoots: [String: String]
    var id: String { name }

    init(name: String, raw: [String: Any]) {
        self.name = name
        self.kind = ProfileKind(rawValue: raw["kind"] as? String ?? "both") ?? .both
        self.cliDir = raw["cli"] as? String
        self.guiDir = raw["gui"] as? String
        self.projects = raw["projects"] as? [String] ?? []
        self.inheritAuthEnv = raw["inherit_auth_env"] as? Bool ?? false
        self.readOnly = raw["read_only"] as? Bool ?? false
        self.disabledRoots = raw["disabled_roots"] as? [String: String] ?? [:]
    }
}

struct ManagerConfig {
    var binary: String
    var guiApp: String
    var profiles: [Profile]

    init(raw: [String: Any]) {
        binary = raw["binary"] as? String ?? ""
        guiApp = raw["gui_app"] as? String ?? "/Applications/Claude.app"
        let dict = raw["profiles"] as? [String: Any] ?? [:]
        profiles = dict.keys.sorted().map { Profile(name: $0, raw: dict[$0] as? [String: Any] ?? [:]) }
    }

    static let empty = ManagerConfig(raw: [:])
}

struct DoctorReport {
    var version: String
    var python: String
    var root: String
    var binary: String?
    var issues: [String]
    var pathFile: String?
    var pathManagedBlock: Bool?
    var pathInCurrent: Bool?
    var pathNotRequired: Bool

    init(raw: [String: Any]) {
        version = raw["version"] as? String ?? "?"
        python = raw["python"] as? String ?? "?"
        root = raw["root"] as? String ?? ""
        binary = raw["binary"] as? String
        issues = raw["issues"] as? [String] ?? []
        let path = raw["path"] as? [String: Any] ?? [:]
        pathNotRequired = path["not_required"] as? Bool ?? false
        pathFile = path["file"] as? String
        pathManagedBlock = path["managed_block"] as? Bool
        pathInCurrent = path["in_current_PATH"] as? Bool
    }
}

/// A backup or imported archive directory under INSTALL_DIR/backups, read straight from its manifest.
struct BackupInfo: Identifiable, Hashable {
    let path: URL
    let profile: String
    let created: Date?
    let complete: Bool
    let scopes: [String]
    let entries: Int
    var id: String { path.path }
    var name: String { path.lastPathComponent }
    var isImport: Bool { name.contains("import") }
}

/// One executed backend command, shown in the activity log.
struct LogEntry: Identifiable {
    let id = UUID()
    let date = Date()
    let arguments: [String]
    var status: Int32
    var output: String
    var error: String
    var succeeded: Bool { status == 0 }
    var commandLine: String {
        (["claude-manager.py"] + arguments).map { arg in
            arg.contains(" ") ? "'\(arg)'" : arg
        }.joined(separator: " ")
    }
}

extension String {
    /// Abbreviate home directory for display.
    var tildePath: String {
        // Match the Python backend, which resolves ~ from $HOME.
        // $HOME is what the Python backend uses; the account home covers paths outside it.
        for home in [ProcessInfo.processInfo.environment["HOME"], NSHomeDirectory()].compactMap({ $0 })
        where hasPrefix(home + "/") || self == home {
            return "~" + dropFirst(home.count)
        }
        return self
    }
}

let profileNamePattern = try! NSRegularExpression(pattern: "^[a-z][a-z0-9_-]{0,31}$")

func isValidProfileName(_ name: String) -> Bool {
    let range = NSRange(name.startIndex..., in: name)
    return profileNamePattern.firstMatch(in: name, range: range) != nil && !name.hasPrefix("gui-")
}

// MARK: - Other AI coding CLIs

struct ToolProfile: Identifiable, Hashable {
    let tool: String
    let name: String
    let root: String
    let inheritAuthEnv: Bool
    let registered: Bool
    let launcher: String?
    let env: [String: String]
    var id: String { tool + "/" + name }
}

struct ToolInfo: Identifiable, Hashable {
    let id: String          // codex, gemini, copilot, opencode
    let title: String
    let binary: String?
    let binaryError: String?
    let configuredBinary: String
    let canRegister: Bool
    let authEnv: [String]
    let profiles: [ToolProfile]

    init(id: String, raw: [String: Any]) {
        self.id = id
        title = raw["title"] as? String ?? id
        binary = raw["binary"] as? String
        binaryError = raw["binary_error"] as? String
        configuredBinary = raw["configured_binary"] as? String ?? ""
        canRegister = raw["can_register"] as? Bool ?? false
        authEnv = raw["auth_env"] as? [String] ?? []
        let dict = raw["profiles"] as? [String: Any] ?? [:]
        profiles = dict.keys.sorted().map { n in
            let p = dict[n] as? [String: Any] ?? [:]
            return ToolProfile(tool: id, name: n, root: p["root"] as? String ?? "",
                               inheritAuthEnv: p["inherit_auth_env"] as? Bool ?? false,
                               registered: p["registered"] as? Bool ?? false,
                               launcher: p["launcher"] as? String,
                               env: p["env"] as? [String: String] ?? [:])
        }
    }

    /// Fixed sidebar order; also used before the backend answers.
    static let order = ["codex", "gemini", "copilot", "opencode", "grok"]

    /// Short label for compact tiles.
    var shortName: String {
        switch id {
        case "codex": return "Codex"
        case "gemini": return "Gemini"
        case "copilot": return "Copilot"
        case "grok": return "Grok Build"
        default: return title
        }
    }

    var vendor: String {
        switch id {
        case "codex": return "OpenAI"
        case "gemini": return "Google"
        case "copilot": return "GitHub"
        case "grok": return "xAI"
        default: return "open source"
        }
    }

    var symbol: String {
        switch id {
        case "codex": return "chevron.left.forwardslash.chevron.right"
        case "gemini": return "sparkles"
        case "copilot": return "airplane"
        case "grok": return "bolt.horizontal"
        default: return "curlybraces.square"
        }
    }

    /// What the per-profile separation covers, verified against each vendor's documentation.
    var isolationNote: String {
        switch id {
        case "codex":
            return "CODEX_HOME ukazuje do kořene profilu (config.toml, auth.json, historie, sezení). Nový profil dostane cli_auth_credentials_store = \"file\", takže přihlášení zůstává v jeho auth.json místo sdílené klíčenky."
        case "gemini":
            return "GEMINI_CLI_HOME = kořen profilu; Gemini CLI v něm používá složku .gemini (settings.json, historie, .env). Přihlášení Google účtem může Gemini CLI ukládat do systémové klíčenky – oddělení účtů přes OAuth proto není zaručené, API klíče oddělené jsou."
        case "copilot":
            return "COPILOT_HOME nahrazuje celé ~/.copilot (settings, config.json, session-state, MCP, skills). Cache jde přes COPILOT_CACHE_HOME mimo profil. OAuth token je v klíčence (služba copilot-cli) podle účtu; v každém profilu se přihlaste /login vlastním účtem."
        case "grok":
            return "GROK_HOME ukazuje do kořene profilu (config.toml, auth.json, sessions, memory, skills, plugins, logy). Přihlášení je v auth.json profilu – nový profil je odhlášený (ověřeno s grok 1.0.70). Mimo původní ~/.grok se nastaví GROK_DISABLE_AUTOUPDATER=1; aktualizujte grok v původní instalaci příkazem grok update."
        default:
            return "XDG_CONFIG_HOME, XDG_DATA_HOME, XDG_STATE_HOME a XDG_CACHE_HOME ukazují do profilu (opencode.json, auth.json, opencode.db, logy). Ověřeno příkazem opencode debug paths. Tyto proměnné zdědí i nástroje, které opencode spustí (git, gh…)."
        }
    }

    var docsURL: URL {
        switch id {
        case "codex": return URL(string: "https://developers.openai.com/codex/config-advanced")!
        case "gemini": return URL(string: "https://geminicli.com/docs/cli/enterprise")!
        case "copilot": return URL(string: "https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference")!
        case "grok": return URL(string: "https://docs.x.ai/build/settings/reference")!
        default: return URL(string: "https://opencode.ai/docs/troubleshooting/")!
        }
    }

    var installHint: String {
        switch id {
        case "codex": return "npm install -g @openai/codex   nebo   brew install --cask codex"
        case "gemini": return "npm install -g @google/gemini-cli   nebo   brew install gemini-cli"
        case "copilot": return "npm install -g @github/copilot   nebo   brew install copilot-cli"
        case "grok": return "oficiální instalátor z docs.x.ai, nebo brew install --cask grok-build (pozor: brew install grok je jiný nástroj)"
        default: return "brew install opencode   nebo   npm install -g opencode-ai"
        }
    }
}

/// A backup under INSTALL_DIR/tool-backups.
struct ToolBackupInfo: Identifiable, Hashable {
    let path: URL
    let tool: String
    let profile: String
    let created: Date?
    let entries: Int
    let root: String
    var id: String { path.path }
    var isImport: Bool { path.lastPathComponent.hasPrefix("import-") }
}

enum AppInfo {
    static var version: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "vývojová"
    }
}
