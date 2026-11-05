import SwiftUI

struct ProfileDetailView: View {
    @EnvironmentObject var store: Store
    let profile: Profile

    @State private var backupScope: Scope = .both
    @State private var newKind: ProfileKind
    @State private var confirmType = false
    @State private var confirmAuth = false
    @State private var editingScope: Scope?

    init(profile: Profile) {
        self.profile = profile
        _newKind = State(initialValue: profile.kind)
    }

    private var installDir: URL { store.client.installDir }
    private var profileBackups: [BackupInfo] { store.backups.filter { $0.profile == profile.name } }

    var body: some View {
        Page(title: profile.name, subtitle: profile.kind.title + (profile.readOnly ? " · pouze pro čtení" : ""), symbol: profile.kind.symbol, tint: Brand.color(for: profile.kind)) {
            HStack(spacing: 10) {
                if profile.kind.hasCLI {
                    Button { store.launchCLI(profile.name) } label: {
                        Label("Spustit CLI v Terminálu", systemImage: "terminal")
                    }
                    .buttonStyle(.borderedProminent)
                }
                if profile.kind.hasGUI {
                    Button { Task { await store.launchGUI(profile.name) } } label: {
                        Label("Spustit Claude Desktop", systemImage: "macwindow")
                    }
                    .buttonStyle(.borderedProminent)
                }
                Spacer()
                Menu { ProfileQuickActions(profile: profile) } label: { Label("Další", systemImage: "ellipsis.circle") }
                    .fixedSize()
            }
            .controlSize(.large)

            Card(title: "Umístění dat", systemImage: "internaldrive") {
                PathRow(label: "CLI (CLAUDE_CONFIG_DIR)", path: profile.cliDir)
                PathRow(label: "Desktop (--user-data-dir)", path: profile.guiDir)
                ForEach(profile.disabledRoots.keys.sorted(), id: \.self) { k in
                    PathRow(label: "Vypnuto: \(k.uppercased())", path: profile.disabledRoots[k])
                }
            }

            Card(title: "Spouštěče", systemImage: "app.badge") {
                if profile.kind.hasCLI {
                    PathRow(label: "Příkaz v Terminálu",
                            path: installDir.appendingPathComponent("sbin/claude-\(profile.name)").path)
                }
                if profile.kind.hasGUI {
                    PathRow(label: "Aplikace pro Dock",
                            path: installDir.appendingPathComponent("Applications/Claude \(profile.name).app").path)
                }
                HStack {
                    Button("Vygenerovat / aktualizovat spouštěče") {
                        Task { await store.execute(["launchers", profile.name], label: "Generuji spouštěče…",
                                                   success: "Spouštěče profilu \(profile.name) jsou připravené.") }
                    }
                    Text("Bezpečně přepíše pouze spouštěče, které vytvořil tento správce.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }

            if profile.kind.hasCLI {
                Card(title: "Přihlášení a prostředí CLI", systemImage: "key") {
                    Toggle(isOn: Binding(get: { profile.inheritAuthEnv }, set: { _ in confirmAuth = true })) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Dědit autentizační proměnné z rodičovského shellu")
                            Text("Vypnuto (doporučeno): ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, CLAUDE_CODE_OAUTH_TOKEN, ANTHROPIC_BASE_URL a přepínače Bedrock/Vertex/Foundry se před spuštěním odstraní, aby nepřebily přihlášený účet profilu.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .toggleStyle(.switch)
                }
            }

            Card(title: "Nastavení", systemImage: "slider.horizontal.3") {
                Text("Úpravy probíhají ve stagingu: před uložením se vytvoří ověřená záloha a neplatný JSON se nikdy nezapíše.")
                    .font(.callout).foregroundStyle(.secondary)
                HStack {
                    if profile.kind.hasCLI {
                        Button { editingScope = .cli } label: { Label("Upravit settings.json (CLI)", systemImage: "doc.text") }
                    }
                    if profile.kind.hasGUI {
                        Button { editingScope = .gui } label: {
                            Label("Upravit claude_desktop_config.json", systemImage: "doc.text")
                        }
                    }
                }
            }

            Card(title: "Zálohy profilu", systemImage: "externaldrive.badge.timemachine") {
                HStack {
                    Picker("Rozsah", selection: $backupScope) {
                        ForEach(Scope.allCases) { s in
                            Text(s.title).tag(s)
                        }
                    }
                    .pickerStyle(.segmented).frame(width: 260)
                    Button("Zálohovat nyní") {
                        Task {
                            if let r = await store.execute(["backup", profile.name, "--scope", backupScope.rawValue],
                                                           label: "Zálohuji a ověřuji…",
                                                           success: "Záloha vytvořena a ověřena (SHA-256).") {
                                _ = r
                                await store.refresh()
                            }
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(backupScope == .cli && !profile.kind.hasCLI || backupScope == .gui && !profile.kind.hasGUI)
                }
                if profileBackups.isEmpty {
                    Text("Tento profil zatím nemá žádnou zálohu.").foregroundStyle(.secondary)
                } else {
                    ForEach(profileBackups.prefix(5)) { b in
                        HStack {
                            Image(systemName: b.isImport ? "square.and.arrow.down" : "clock")
                            Text(b.created.map { $0.formatted(date: .abbreviated, time: .standard) } ?? b.name)
                            Text(b.scopes.joined(separator: " + ").uppercased()).font(.caption).foregroundStyle(.secondary)
                            Spacer()
                            Text("\(b.entries) položek").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Button("Všechny zálohy…") { store.selection = .backups }.buttonStyle(.link)
                }
            }

            Card(title: "Projekty", systemImage: "folder") {
                if profile.projects.isEmpty {
                    Text("Žádné evidované projekty.").foregroundStyle(.secondary)
                }
                ForEach(profile.projects, id: \.self) { PathRow(label: "Projekt", path: $0) }
                HStack {
                    Button("Přidat existující projekt…") {
                        if let p = choosePath(directories: true) {
                            Task { await store.execute(["project-add", profile.name, p], label: "Přidávám projekt…",
                                                       success: "Projekt zaevidován."); await store.refresh() }
                        }
                    }
                    Button("Kopírovat projekt…") { store.selection = .projects }
                }
            }

            Card(title: "Typ profilu", systemImage: "arrow.triangle.swap") {
                HStack {
                    Picker("Nový typ", selection: $newKind) {
                        ForEach(ProfileKind.allCases) { Text($0.title).tag($0) }
                    }
                    .frame(width: 300)
                    Button("Změnit typ…") { confirmType = true }
                        .disabled(newKind == profile.kind)
                }
                Text("Před změnou se zazálohují aktivní kořeny. Data vypnuté části se nemažou a při opětovném zapnutí se použijí původní cesty.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .confirmationDialog("Změnit typ profilu \(profile.name) na „\(newKind.title)“?", isPresented: $confirmType) {
            Button("Zazálohovat a změnit typ") {
                Task {
                    await store.execute(["set-type", profile.name, newKind.rawValue, "--yes"],
                                        label: "Zálohuji a měním typ…", success: "Typ profilu změněn.")
                    await store.execute(["launchers", profile.name], label: "Generuji spouštěče…")
                    await store.refresh()
                }
            }
        } message: {
            Text("Všechny Claude procesy musí být ukončené. Staré spouštěče vypnuté části zůstanou na disku, ale jejich spuštění bude odmítnuto.")
        }
        .confirmationDialog(profile.inheritAuthEnv ? "Vrátit oddělení účtů?" : "Povolit dědění autentizačních proměnných?",
                            isPresented: $confirmAuth) {
            Button(profile.inheritAuthEnv ? "Oddělit (clean)" : "Povolit dědění (inherit)") {
                Task {
                    await store.execute(["auth-env", profile.name, profile.inheritAuthEnv ? "clean" : "inherit"],
                                        label: "Ukládám…", success: "Nastavení prostředí uloženo.")
                    await store.refresh()
                }
            }
        } message: {
            Text(profile.inheritAuthEnv
                 ? "Proměnné jako ANTHROPIC_API_KEY se budou před spuštěním CLI opět odstraňovat."
                 : "API klíče a provider proměnné z vašeho shellu pak mohou přebít přihlášený účet tohoto profilu. Klíč se do manager.json neukládá.")
        }
        .sheet(item: $editingScope) { scope in
            SettingsEditorSheet(profile: profile, scope: scope)
        }
    }
}

struct SettingsEditorSheet: View {
    @EnvironmentObject var store: Store
    @Environment(\.dismiss) private var dismiss
    let profile: Profile
    let scope: Scope

    @State private var text = ""
    @State private var original = ""
    @State private var saving = false

    private var file: URL? { store.settingsFile(for: profile, scope: scope) }

    private var validation: String? {
        guard let data = text.data(using: .utf8) else { return "Neplatné kódování" }
        do {
            let obj = try JSONSerialization.jsonObject(with: data)
            return obj is [String: Any] ? nil : "Nejvyšší úroveň musí být JSON objekt { … }"
        } catch {
            return "Neplatný JSON: " + ((error as NSError).userInfo["NSDebugDescription"] as? String ?? error.localizedDescription)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading) {
                    Text(file?.lastPathComponent ?? "settings").font(.title2.weight(.semibold))
                    Text("Profil \(profile.name) · \(file?.path.tildePath ?? "")").foregroundStyle(.secondary).font(.callout)
                }
                Spacer()
                Button("Formátovat") {
                    if let d = text.data(using: .utf8), let o = try? JSONSerialization.jsonObject(with: d) {
                        text = prettyJSON(o)
                    }
                }
                .disabled(validation != nil)
            }
            TextEditor(text: $text)
                .font(.system(.body, design: .monospaced))
                .autocorrectionDisabled()
                .frame(minHeight: 380)
                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.primary.opacity(0.15)))
            HStack {
                if let v = validation {
                    Label(v, systemImage: "xmark.octagon").foregroundStyle(.red).lineLimit(2)
                } else {
                    Label("Platný JSON", systemImage: "checkmark.circle").foregroundStyle(.green)
                }
                Spacer()
                Button("Zrušit", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Zazálohovat a uložit") {
                    saving = true
                    Task {
                        let ok = await store.saveSettings(profile: profile.name, scope: scope, text: text)
                        saving = false
                        if ok { dismiss() }
                    }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut("s")
                .disabled(validation != nil || text == original || saving)
            }
            Text("Uložení vyžaduje ukončené Claude procesy. Pokud se soubor mezitím změní jiným programem, uložení se odmítne.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(20)
        .frame(width: 720, height: 560)
        .onAppear {
            if let file, let data = try? String(contentsOf: file, encoding: .utf8) {
                text = data
            } else {
                text = "{\n}\n"
            }
            original = text
        }
    }
}

