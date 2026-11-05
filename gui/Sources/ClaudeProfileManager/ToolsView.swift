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

    private var backups: [ToolBackupInfo] { store.toolBackups.filter { $0.tool == tool.id } }

    var body: some View {
        Page(title: tool.title, subtitle: "Oddělené profily se samostatnou konfigurací, historií a přihlášením.") {
            HStack {
                Button { showNew = true } label: { Label("Nový profil", systemImage: "plus") }
                    .buttonStyle(.borderedProminent)
                if tool.canRegister {
                    Button { showRegister = true } label: {
                        Label("Zaregistrovat existující", systemImage: "tray.and.arrow.down")
                    }
                }
                Spacer()
                Link(destination: tool.docsURL) { Label("Dokumentace výrobce", systemImage: "book") }
            }

            Card(title: "Jak funguje oddělení", systemImage: "square.split.2x2") {
                Text(tool.isolationNote).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                Text("Ve výchozím stavu se před spuštěním odstraní: " + tool.authEnv.joined(separator: ", "))
                    .font(.caption).foregroundStyle(.secondary)
            }

            Card(title: "Spustitelný soubor", systemImage: "terminal") {
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

            Card(title: "Zálohy", systemImage: "externaldrive.badge.timemachine") {
                if backups.isEmpty {
                    Text("Žádné zálohy profilů \(tool.title).").foregroundStyle(.secondary)
                }
                ForEach(backups) { b in
                    HStack {
                        Image(systemName: "clock")
                        Text(b.created.map { $0.formatted(date: .abbreviated, time: .standard) } ?? b.path.lastPathComponent)
                        Text(b.profile).foregroundStyle(.secondary)
                        Spacer()
                        Text("\(b.entries) položek").font(.caption).foregroundStyle(.secondary)
                        Button("Ověřit") {
                            Task { await store.execute(["tool-verify", b.path.path], label: "Ověřuji…",
                                                       success: "Záloha je kompletní a neporušená.") }
                        }
                        Button("Obnovit…") { restoreTarget = b }
                        Button { store.reveal(b.path.path) } label: { Image(systemName: "folder") }
                    }
                    .controlSize(.small)
                }
            }
        }
        .onAppear {
            binary = tool.configuredBinary
            if Snapshotter.directory != nil { binary = binary.tildePath }
        }
        .sheet(isPresented: $showNew) { ToolProfileSheet(tool: tool, register: false) }
        .sheet(isPresented: $showRegister) { ToolProfileSheet(tool: tool, register: true) }
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

    @ViewBuilder private func profileCard(_ p: ToolProfile) -> some View {
        Card(title: p.name, systemImage: tool.symbol) {
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
