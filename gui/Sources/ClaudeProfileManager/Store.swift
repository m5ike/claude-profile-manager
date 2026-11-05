import AppKit
import Foundation
import SwiftUI

enum SidebarItem: Hashable {
    case overview
    case profile(String)
    case backups
    case migration
    case projects
    case environment
    case activity
    case tool(String)
}

struct Banner: Identifiable, Equatable {
    let id = UUID()
    let text: String
    let isError: Bool
}

@MainActor
final class Store: ObservableObject {
    @Published var config = ManagerConfig.empty
    @Published var doctor: DoctorReport?
    @Published var backups: [BackupInfo] = []
    @Published var tools: [ToolInfo] = []
    @Published var toolBackups: [ToolBackupInfo] = []
    @Published var log: [LogEntry] = []
    @Published var busyLabel: String?
    @Published var banner: Banner?
    @Published var errorAlert: String?
    @Published var selection: SidebarItem? = .overview
    @Published var showNewProfile = false
    @Published var showRegister = false
    @Published var pendingTransaction = false
    @Published var pendingUpdate = false

    @Published var pythonPath: String {
        didSet { UserDefaults.standard.set(pythonPath, forKey: "pythonPath") }
    }
    @Published var scriptPath: String {
        didSet { UserDefaults.standard.set(scriptPath, forKey: "scriptPath") }
    }

    init() {
        let defaults = UserDefaults.standard
        pythonPath = defaults.string(forKey: "pythonPath") ?? ManagerClient.detectPython()
        scriptPath = defaults.string(forKey: "scriptPath") ?? ManagerClient.detectScript() ?? ""
    }

    var client: ManagerClient { ManagerClient(python: pythonPath, script: scriptPath) }

    var isConfigured: Bool {
        !scriptPath.isEmpty && FileManager.default.fileExists(atPath: scriptPath)
            && FileManager.default.isExecutableFile(atPath: pythonPath)
    }

    var isBusy: Bool { busyLabel != nil }

    func profile(_ name: String) -> Profile? { config.profiles.first { $0.name == name } }

    // MARK: - Command execution

    /// Runs one backend command, records it in the activity log and surfaces errors.
    @discardableResult
    func execute(_ args: [String], label: String, environment: [String: String] = [:],
                 success: String? = nil, quiet: Bool = false) async -> CommandResult? {
        guard isConfigured else {
            errorAlert = "Správce není nastaven. Otevřete Nastavení (⌘,) a vyberte claude-manager.py."
            return nil
        }
        if !quiet { busyLabel = label }
        defer { if !quiet { busyLabel = nil } }
        let result = await client.run(args, environment: environment)
        log.insert(LogEntry(arguments: args, status: result.status,
                            output: result.stdout, error: result.stderr), at: 0)
        if log.count > 300 { log.removeLast(log.count - 300) }
        if result.status != 0 {
            if !quiet { errorAlert = result.errorMessage }
            return nil
        }
        if let success { show(success) }
        return result
    }

    func show(_ text: String, error: Bool = false) {
        let b = Banner(text: text, isError: error)
        banner = b
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            if self.banner == b { self.banner = nil }
        }
    }

    func refresh() async {
        guard isConfigured else { return }
        let c = client
        pendingTransaction = c.hasPendingTransaction
        pendingUpdate = c.hasPendingUpdate
        if let r = await execute(["list"], label: "Načítám profily…", quiet: true),
           let raw = r.json as? [String: Any] {
            config = ManagerConfig(raw: raw)
        }
        if let r = await execute(["doctor"], label: "Diagnostika…", quiet: true),
           let raw = r.json as? [String: Any] {
            doctor = DoctorReport(raw: raw)
        }
        if let r = await execute(["tool-list"], label: "Načítám další nástroje…", quiet: true),
           let raw = r.json as? [String: Any] {
            tools = ToolInfo.order.compactMap { id in
                (raw[id] as? [String: Any]).map { ToolInfo(id: id, raw: $0) }
            }
        }
        backups = c.listBackups()
        toolBackups = c.listToolBackups()
        if case .profile(let name)? = selection, profile(name) == nil { selection = .overview }
    }

    // MARK: - High-level actions

    func createProfile(name: String, kind: ProfileKind, cliDir: String?, guiDir: String?,
                       register: Bool, makeLaunchers: Bool) async -> Bool {
        var args = [register ? "register" : "create", name, "--type", kind.rawValue]
        if let cliDir, !cliDir.isEmpty, kind.hasCLI { args += ["--cli-dir", cliDir] }
        if let guiDir, !guiDir.isEmpty, kind.hasGUI { args += ["--gui-dir", guiDir] }
        args.append("--yes")
        guard await execute(args, label: register ? "Registruji profil…" : "Vytvářím profil…") != nil
        else { return false }
        if makeLaunchers {
            await execute(["launchers", name], label: "Generuji spouštěče…")
        }
        await refresh()
        selection = .profile(name)
        show(register ? "Profil \(name) byl zaregistrován." : "Profil \(name) byl vytvořen.")
        return true
    }

    func tool(_ id: String) -> ToolInfo? { tools.first { $0.id == id } }

    func launchCLI(_ name: String) { openInTerminal(["cli", name], title: "claude-\(name)") }

    func launchTool(_ tool: String, _ name: String) {
        openInTerminal(["tool-run", tool, name], title: "\(tool)-\(name)")
    }

    func launchGUI(_ name: String) async {
        await execute(["gui", name], label: "Spouštím Claude Desktop…",
                      success: "Claude Desktop (\(name)) běží.")
    }

    /// Opens Terminal with a manager command. CLIs need a real TTY, so they cannot run inside the app.
    func openInTerminal(_ args: [String], title: String) {
        let fm = FileManager.default
        let dir = fm.temporaryDirectory.appendingPathComponent("ClaudeProfileManager", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true,
                                attributes: [.posixPermissions: 0o700])
        let file = dir.appendingPathComponent("\(title)-\(UUID().uuidString.prefix(8)).command")
        let script = """
        #!/bin/zsh
        rm -f -- \(shellQuote(file.path))
        clear
        exec \(shellQuote(pythonPath)) \(shellQuote(scriptPath)) \(args.map(shellQuote).joined(separator: " "))

        """
        do {
            try script.write(to: file, atomically: true, encoding: .utf8)
            try fm.setAttributes([.posixPermissions: 0o700], ofItemAtPath: file.path)
            let terminal = URL(fileURLWithPath: "/System/Applications/Utilities/Terminal.app")
            NSWorkspace.shared.open([file], withApplicationAt: terminal,
                                    configuration: NSWorkspace.OpenConfiguration())
            log.insert(LogEntry(arguments: args, status: 0,
                                output: "Otevřeno v aplikaci Terminál.", error: ""), at: 0)
        } catch {
            errorAlert = "Nelze otevřít Terminál: \(error.localizedDescription)"
        }
    }

    /// Commits edited settings through the backend's staged, validated, backed-up editor flow.
    /// The "editor" is `/bin/cp <prepared file>`, so the backend still does validation + transaction.
    func saveSettings(profile: String, scope: Scope, text: String) async -> Bool {
        guard let data = text.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data), obj is [String: Any] else {
            errorAlert = "Obsah není platný JSON objekt. Nic nebylo uloženo."
            return false
        }
        let fm = FileManager.default
        let dir = fm.temporaryDirectory.appendingPathComponent("ClaudeProfileManager", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true,
                                attributes: [.posixPermissions: 0o700])
        let file = dir.appendingPathComponent("settings-\(UUID().uuidString).json")
        defer { try? fm.removeItem(at: file) }
        do {
            try data.write(to: file, options: .atomic)
            try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        } catch {
            errorAlert = error.localizedDescription
            return false
        }
        let editor = "/bin/cp " + shellQuote(file.path)
        let ok = await execute(["edit-settings", profile, "--scope", scope.rawValue, "--yes"],
                               label: "Zálohuji a ukládám nastavení…",
                               environment: ["EDITOR": editor],
                               success: "Nastavení uloženo (záloha vytvořena).") != nil
        if ok { backups = client.listBackups() }
        return ok
    }

    func settingsFile(for profile: Profile, scope: Scope) -> URL? {
        switch scope {
        case .cli: return profile.cliDir.map { URL(fileURLWithPath: $0).appendingPathComponent("settings.json") }
        case .gui: return profile.guiDir.map {
            URL(fileURLWithPath: $0).appendingPathComponent("claude_desktop_config.json") }
        case .both: return nil
        }
    }

    func reveal(_ path: String) {
        let url = URL(fileURLWithPath: path)
        if FileManager.default.fileExists(atPath: path) {
            NSWorkspace.shared.activateFileViewerSelecting([url])
        } else {
            show("Cesta neexistuje: \(path.tildePath)", error: true)
        }
    }

    func openHelp() {
        if let url = Bundle.main.url(forResource: "Napoveda", withExtension: "pdf") {
            NSWorkspace.shared.open(url)
        } else {
            errorAlert = "Nápověda (Napoveda.pdf) není součástí této sestavy aplikace."
        }
    }
}

func shellQuote(_ s: String) -> String {
    "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'"
}

/// Parse "A=B" lines into --map arguments.
func mappingArguments(_ text: String) -> [String] {
    text.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }
        .filter { !$0.isEmpty }.flatMap { ["--map", $0] }
}

func prettyJSON(_ any: Any?) -> String {
    guard let any, JSONSerialization.isValidJSONObject(any),
          let data = try? JSONSerialization.data(withJSONObject: any,
                                                 options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
    else { return "" }
    return String(decoding: data, as: UTF8.self)
}
