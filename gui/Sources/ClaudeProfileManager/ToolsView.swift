import AppKit
import SwiftUI

/// Profiles for one of the other AI coding CLIs (Codex, Gemini, Copilot, opencode).
struct ToolView: View {
    @EnvironmentObject var store: Store
    let tool: ToolInfo

    @State private var binary = ""
    @State private var showNew = false
    @State private var showRegister = false
    @State private var restoreTarget: ToolBackupInfo?
    @State private var unregisterTarget: ToolProfile?
    @State private var authTarget: ToolProfile?
    @State private var migration: MigrationRequest?
    @State private var showImport = false
    @State private var exportResult: String?

    private var backups: [ToolBackupInfo] { store.toolBackups.filter { $0.tool == tool.id } }

    var body: some View {
        Page(title: tool.title, subtitle: "Oddělené profily se samostatnou konfigurací, historií a přihlášením.", symbol: tool.symbol, tint: Brand.color(forTool: tool.id)) {
            HStack {
                Button { showNew = true } label: { Label("Nový profil", systemImage: "plus") }
                    .buttonStyle(.borderedProminent)
                if tool.canRegister {
                    Button { showRegister = true } label: {
                        Label("Zaregistrovat existující", systemImage: "tray.and.arrow.down")
                    }
                }
                Button { migration = MigrationRequest(source: nil) } label: {
                    Label("Migrace…", systemImage: "arrow.left.arrow.right")
                }
                .disabled(tool.profiles.isEmpty)
                Spacer()
                Link(destination: tool.docsURL) { Label("Dokumentace výrobce", systemImage: "book") }
            }

            Card(title: "Jak funguje oddělení", systemImage: "square.split.2x2", tint: Brand.color(forTool: tool.id)) {
                Text(tool.isolationNote).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                Text("Ve výchozím stavu se před spuštěním odstraní: " + tool.authEnv.joined(separator: ", "))
                    .font(.caption).foregroundStyle(.secondary)
            }

            Card(title: "Spustitelný soubor", systemImage: "terminal", tint: Brand.color(forTool: tool.id)) {
                if let b = tool.binary {
                    Label("Používá se: \(b.tildePath)", systemImage: "checkmark.circle").foregroundStyle(.green)
                } else {
                    Label("\(tool.title) nebyl nalezen. Instalace: \(tool.installHint)",
                          systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                }
                HStack {
                    TextField("", text: $binary, prompt: Text("/opt/homebrew/bin/\(tool.id)"))
                        .font(.system(.body, design: .monospaced))
                    Button("Vybrat…") { if let p = choosePath(directories: false) { binary = p } }
                    Button("Uložit") {
                        Task {
                            await store.execute(["tool-set-binary", tool.id, binary], label: "Ověřuji…",
                                                success: "Cesta k \(tool.title) uložena.")
                            await store.refresh()
                        }
                    }
                    .disabled(binary.isEmpty || binary == tool.configuredBinary)
                }
                Text("Bez nastavení se použije \(tool.id) nalezený v PATH aplikace.").font(.caption).foregroundStyle(.secondary)
            }

            if tool.profiles.isEmpty {
                Card {
                    Text("Zatím žádný profil. Vytvořte například „osobni“ a „pracovni“ a v každém se přihlaste jiným účtem.")
                        .foregroundStyle(.secondary)
                }
            }
            ForEach(tool.profiles) { p in profileCard(p) }

            Card(title: "Zálohy a přenos", systemImage: "externaldrive.fill", tint: Brand.color(forTool: tool.id)) {
                HStack {
                    Text("Exportovaný archiv přenesete na jiný Mac, tam ho importujte a použijte „Migrovat…“.")
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button { showImport = true } label: { Label("Importovat archiv…", systemImage: "square.and.arrow.down") }
                }
                if let exportResult { ResultView(title: "Export dokončen", text: exportResult) }
                if backups.isEmpty {
                    Text("Žádné zálohy profilů \(tool.title).").foregroundStyle(.secondary)
                }
                ForEach(backups) { b in
                    HStack {
                        Image(systemName: "clock")
                        Text(b.created.map { $0.formatted(date: .abbreviated, time: .standard) } ?? b.path.lastPathComponent)
                        Text(b.profile + (b.isImport ? " (import)" : "")).foregroundStyle(.secondary)
                        Spacer()
                        Text("\(b.entries) položek").font(.caption).foregroundStyle(.secondary)
                        Button("Ověřit") {
                            Task { await store.execute(["tool-verify", b.path.path], label: "Ověřuji…",
                                                       success: "Záloha je kompletní a neporušená.") }
                        }
                        Button("Obnovit…") { restoreTarget = b }
                            .disabled(!tool.profiles.contains { $0.name == b.profile && $0.root == b.root })
                            .help("Přesná obnova jen do původního profilu a cesty; jinak použijte Migrovat…")
                        Button("Migrovat…") { migration = MigrationRequest(source: b.path.path) }
                        Button("Export…") { export(b) }
                        Button { store.reveal(b.path.path) } label: { Image(systemName: "folder") }
                    }
                    .controlSize(.small)
                }
            }
        }
        .onAppear {
            if Snapshotter.openToolMigration, tool.profiles.count > 1 {
                Snapshotter.openToolMigration = false
                migration = MigrationRequest(source: nil)
            }
            binary = tool.configuredBinary
            if Snapshotter.directory != nil { binary = binary.tildePath }
        }
        .sheet(isPresented: $showNew) { ToolProfileSheet(tool: tool, register: false) }
        .sheet(isPresented: $showRegister) { ToolProfileSheet(tool: tool, register: true) }
        .sheet(item: $migration) { ToolMigrationSheet(tool: tool, backupSource: $0.source) }
        .sheet(isPresented: $showImport) { ToolImportSheet() }
        .confirmationDialog("Obnovit zálohu?", isPresented: Binding(get: { restoreTarget != nil },
                                                                     set: { if !$0 { restoreTarget = nil } }),
                            presenting: restoreTarget) { b in
            Button("Zazálohovat aktuální stav a obnovit", role: .destructive) {
                Task {
                    await store.execute(["tool-restore", tool.id, b.profile, b.path.path, "--yes"],
                                        label: "Obnovuji…", success: "Profil obnoven.")
                    await store.refresh()
                }
            }
        } message: { b in
            Text("Profil \(b.profile) se vrátí do stavu ze zálohy. Před obnovou se vytvoří záloha aktuálního stavu. \(tool.title) nesmí běžet.")
        }
        .confirmationDialog("Odebrat profil z registru?", isPresented: Binding(get: { unregisterTarget != nil },
                                                                              set: { if !$0 { unregisterTarget = nil } }),
                            presenting: unregisterTarget) { p in
            Button("Odebrat (data ponechat)") {
                Task {
                    await store.execute(["tool-unregister", tool.id, p.name, "--yes"], label: "Ukládám…",
                                        success: "Profil odebrán, data zůstala v \(p.root.tildePath).")
                    await store.refresh()
                }
            }
        } message: { p in
            Text("Adresář \(p.root.tildePath) se nesmaže. Spouštěč \(tool.id)-\(p.name) přestane fungovat.")
        }
        .confirmationDialog("Změnit dědění proměnných?", isPresented: Binding(get: { authTarget != nil },
                                                                             set: { if !$0 { authTarget = nil } }),
                            presenting: authTarget) { p in
            Button(p.inheritAuthEnv ? "Oddělit (clean)" : "Povolit dědění (inherit)") {
                Task {
                    await store.execute(["tool-auth-env", tool.id, p.name, p.inheritAuthEnv ? "clean" : "inherit"],
                                        label: "Ukládám…", success: "Nastavení uloženo.")
                    await store.refresh()
                }
            }
        } message: { p in
            Text(p.inheritAuthEnv
                 ? "Proměnné \(tool.authEnv.joined(separator: ", ")) se budou opět odstraňovat."
                 : "Klíče a tokeny z vašeho shellu pak mohou přebít účet přihlášený v profilu \(p.name).")
        }
    }

    private func export(_ b: ToolBackupInfo) {
        guard let out = chooseSavePath(defaultName: "\(tool.id)-\(b.profile)-transfer.tar.gz") else { return }
        Task {
            if await store.execute(["tool-export", b.path.path, out], label: "Exportuji…",
                                   success: "Archiv vytvořen.") != nil {
                let sha = (try? String(contentsOfFile: out + ".sha256", encoding: .utf8))?
                    .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                exportResult = out.tildePath + "\n\nSHA-256 (předejte jiným důvěryhodným kanálem):\n" + sha
            }
        }
    }

    @ViewBuilder private func profileCard(_ p: ToolProfile) -> some View {
        Card(title: p.name, systemImage: tool.symbol, tint: Brand.color(forTool: tool.id)) {
            PathRow(label: p.registered ? "Kořen (registrovaný)" : "Kořen profilu", path: p.root)
            PathRow(label: "Spouštěč", path: p.launcher)
            VStack(alignment: .leading, spacing: 2) {
                ForEach(p.env.keys.sorted(), id: \.self) { k in
                    Text("\(k)=\(p.env[k]!.tildePath)").font(.system(.caption, design: .monospaced))
                        .foregroundStyle(.secondary).textSelection(.enabled)
                        .lineLimit(1).truncationMode(.middle)
                }
            }
            Toggle(isOn: Binding(get: { p.inheritAuthEnv }, set: { _ in authTarget = p })) {
                Text("Dědit autentizační proměnné z rodičovského shellu")
            }
            .toggleStyle(.switch)
            HStack {
                Button { store.launchTool(tool.id, p.name) } label: {
                    Label("Spustit v Terminálu", systemImage: "terminal")
                }
                .buttonStyle(.borderedProminent)
                .disabled(tool.binary == nil)
                Button(p.launcher == nil ? "Vytvořit spouštěč" : "Obnovit spouštěč") {
                    Task {
                        await store.execute(["tool-launchers", tool.id, p.name], label: "Vytvářím spouštěč…",
                                            success: "Příkaz \(tool.id)-\(p.name) je připraven.")
                        await store.refresh()
                    }
                }
                Button("Zálohovat") {
                    Task {
                        await store.execute(["tool-backup", tool.id, p.name], label: "Zálohuji…",
                                            success: "Záloha vytvořena a ověřena.")
                        await store.refresh()
                    }
                }
                Spacer()
                Button { store.reveal(p.root) } label: { Image(systemName: "folder") }.help("Zobrazit ve Finderu")
                Button(role: .destructive) { unregisterTarget = p } label: { Image(systemName: "minus.circle") }
                    .help("Odebrat z registru (data zůstanou)")
            }
        }
    }
}

struct ToolProfileSheet: View {
    @EnvironmentObject var store: Store
    @Environment(\.dismiss) private var dismiss
    let tool: ToolInfo
    let register: Bool

    @State private var name = ""
    @State private var dir = ""
    @State private var launcher = true
    @State private var working = false

    private var exists: Bool { tool.profiles.contains { $0.name == name } }
    private var suggestion: String? {
        switch tool.id {
        case "codex": return NSHomeDirectory() + "/.codex"
        case "copilot": return NSHomeDirectory() + "/.copilot"
        case "grok": return NSHomeDirectory() + "/.grok"
        default: return nil
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 4) {
                Text(register ? "Zaregistrovat existující data – \(tool.title)" : "Nový profil – \(tool.title)")
                    .font(.title2.weight(.semibold))
                Text(register ? "Převezme existující adresář bez kopírování a beze změny obsahu."
                              : "Vytvoří prázdný oddělený profil. Přihlásíte se při prvním spuštění.")
                    .foregroundStyle(.secondary)
            }
            .padding([.horizontal, .top], 20)
            Form {
                TextField("Název", text: $name, prompt: Text("např. pracovni"))
                if !name.isEmpty && !isValidProfileName(name) {
                    Text("1–32 malých písmen ASCII, číslic, _ a -; začíná písmenem.").font(.caption).foregroundStyle(.red)
                } else if exists {
                    Text("Profil s tímto názvem už existuje.").font(.caption).foregroundStyle(.red)
                }
                DirectoryField(label: register ? "Existující adresář" : "Adresář (volitelné)", path: $dir,
                               placeholder: register ? (suggestion?.tildePath ?? "adresář obsahující .gemini")
                                                     : "INSTALL_DIR/tools/\(tool.id)/NAZEV",
                               suggestion: register ? suggestion : nil)
                if register && tool.id == "gemini" {
                    Text("Zadejte adresář, který obsahuje složku .gemini (GEMINI_CLI_HOME). Domovský adresář ~ registrovat nelze.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Toggle("Vytvořit spouštěč \(tool.id)-\(name.isEmpty ? "NAZEV" : name)", isOn: $launcher)
            }
            .formStyle(.grouped)
            HStack {
                Spacer()
                Button("Zrušit", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button(register ? "Zaregistrovat" : "Vytvořit") {
                    working = true
                    Task {
                        var args = [register ? "tool-register" : "tool-create", tool.id, name]
                        if !dir.isEmpty { args += ["--dir", (dir as NSString).expandingTildeInPath] }
                        let ok = await store.execute(args + ["--yes"], label: "Ukládám profil…",
                                                     success: "Profil \(name) připraven.") != nil
                        if ok && launcher {
                            await store.execute(["tool-launchers", tool.id, name], label: "Vytvářím spouštěč…")
                        }
                        await store.refresh()
                        working = false
                        if ok { dismiss() }
                    }
                }
                .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                .disabled(!isValidProfileName(name) || exists || working || (register && dir.isEmpty))
            }
            .padding(20)
        }
        .frame(width: 560)
    }
}


struct MigrationRequest: Identifiable {
    let id = UUID()
    let source: String?   // backup path, or nil for a profile source
}

/// Copy settings/history between profiles of one tool, always via a dry-run first.
struct ToolMigrationSheet: View {
    @EnvironmentObject var store: Store
    @Environment(\.dismiss) private var dismiss
    let tool: ToolInfo
    let backupSource: String?

    @State private var source = ""
    @State private var target = ""
    @State private var settings = true
    @State private var history = false
    @State private var credentials = false
    @State private var conflict: ConflictPolicy = .error
    @State private var dryRunOK: [String]?
    @State private var result: (title: String, text: String, error: Bool)?

    private var args: [String] {
        var a = backupSource != nil ? ["tool-migrate-backup", backupSource!, target]
                                    : ["tool-migrate", tool.id, source, target]
        a += ["--components", [settings ? "settings" : nil, history ? "history" : nil]
                .compactMap { $0 }.joined(separator: ","), "--conflict", conflict.rawValue]
        if credentials { a.append("--credentials") }
        return a
    }
    private var valid: Bool {
        !target.isEmpty && (settings || history) && (backupSource != nil || (!source.isEmpty && source != target))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Migrace – \(tool.title)", systemImage: "arrow.left.arrow.right").font(.title2.weight(.semibold))
            StepsView(current: dryRunOK == args ? 2 : 1)
            Form {
                if let b = backupSource {
                    LabeledContent("Zdroj (záloha)", value: (b as NSString).lastPathComponent)
                } else {
                    Picker("Zdrojový profil", selection: $source) {
                        Text("Vyberte…").tag("")
                        ForEach(tool.profiles) { Text($0.name).tag($0.name) }
                    }
                }
                Picker("Cílový profil", selection: $target) {
                    Text("Vyberte…").tag("")
                    ForEach(tool.profiles) { Text($0.name).tag($0.name) }
                }
                Toggle("Nastavení (konfigurace, instrukce, skills, agenti, MCP, rozšíření)", isOn: $settings)
                Toggle("Historie (sezení, databáze, stav)", isOn: $history)
                Toggle("Také přihlašovací údaje a uložená oprávnění (--credentials)", isOn: $credentials)
                if credentials {
                    Text("Zkopírují se soubory s tokeny/klíči. Klíčenka macOS se nepřenáší. Používejte jen mezi vlastními účty.")
                        .font(.caption).foregroundStyle(.orange)
                }
                Picker("Při konfliktu", selection: $conflict) {
                    ForEach(ConflictPolicy.allCases) { Text($0.title).tag($0) }
                }
            }
            .formStyle(.grouped)
            Text("Logy, dočasné soubory a cache se nekopírují nikdy. U Codexu si cíl vždy ponechá vlastní cli_auth_credentials_store.")
                .font(.caption).foregroundStyle(.secondary)
            if let result { ResultView(title: result.title, text: result.text, isError: result.error) }
            HStack {
                Spacer()
                Button("Zavřít", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button("1. Zkouška nanečisto") { Task { await run(apply: false) } }
                    .disabled(!valid || store.isBusy)
                Button("2. Provést migraci") { Task { await run(apply: true) } }
                    .buttonStyle(.borderedProminent)
                    .disabled(dryRunOK != args || store.isBusy)
            }
        }
        .padding(22).frame(width: 640)
        .onAppear {
            if Snapshotter.directory != nil, backupSource == nil, tool.profiles.count > 1 {
                source = tool.profiles[0].name; target = tool.profiles[1].name; history = true
            }
        }
    }

    private func run(apply: Bool) async {
        let a = args
        if let r = await store.execute(apply ? a + ["--apply", "--yes"] : a,
                                       label: apply ? "Migruji…" : "Kontroluji…",
                                       success: apply ? "Migrace dokončena (cíl zazálohován)." : "Zkouška proběhla bez chyb.") {
            dryRunOK = apply ? nil : a
            result = (apply ? "Migrace provedena" : "Výsledek zkoušky – nic nebylo změněno", prettyJSON(r.json), false)
            if apply { await store.refresh() }
        } else {
            dryRunOK = nil
            result = ("Operace odmítnuta", store.log.first?.error ?? "", true)
        }
    }
}

struct ToolImportSheet: View {
    @EnvironmentObject var store: Store
    @Environment(\.dismiss) private var dismiss
    @State private var archive = ""
    @State private var sha = ""
    @State private var output: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Import zálohy nástroje", systemImage: "square.and.arrow.down").font(.title2.weight(.semibold))
            Text("Ověří kontrolní součet a bezpečně rozbalí archiv do INSTALL_DIR/tool-backups. Žádný profil se nemění; data pak přenesete tlačítkem Migrovat… u importované zálohy.")
                .foregroundStyle(.secondary)
            Form {
                LabeledContent("Archiv .tar.gz") {
                    HStack {
                        TextField("", text: $archive)
                        Button("Vybrat…") { if let p = choosePath(directories: false) { archive = p } }
                    }
                }
                LabeledContent("Důvěryhodný SHA-256") {
                    HStack {
                        TextField("", text: $sha).font(.system(.body, design: .monospaced))
                        Button("Ze souboru .sha256") {
                            if let s = try? String(contentsOfFile: archive + ".sha256", encoding: .utf8) {
                                sha = String(s.prefix(64)).lowercased()
                            }
                        }
                        .disabled(archive.isEmpty)
                    }
                }
            }
            .formStyle(.grouped)
            if let output { ResultView(title: "Import dokončen", text: output) }
            HStack {
                Spacer()
                Button(output == nil ? "Zrušit" : "Zavřít", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Importovat") {
                    Task {
                        if let r = await store.execute(["tool-import", archive, "--sha256", sha],
                                                       label: "Ověřuji a rozbaluji…", success: "Archiv importován.") {
                            output = prettyJSON(r.json)
                            await store.refresh()
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(archive.isEmpty || sha.range(of: "^[0-9a-f]{64}$", options: .regularExpression) == nil || output != nil)
            }
        }
        .padding(22).frame(width: 620)
    }
}
