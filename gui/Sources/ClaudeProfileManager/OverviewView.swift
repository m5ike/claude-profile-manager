import AppKit
import SwiftUI

struct OverviewView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        Page(title: "Přehled", subtitle: "Oddělené profily Claude Code, Claude Desktop, Codex, Gemini, Copilot a opencode na jednom Macu") {
            if store.pendingTransaction || store.pendingUpdate {
                Card(title: "Vyžaduje pozornost", systemImage: "exclamationmark.triangle.fill") {
                    Text(store.pendingTransaction
                         ? "Byla nalezena přerušená transakce. Zápisy a spouštěče jsou zablokovány, dokud neproběhne obnova."
                         : "Byla nalezena přerušená aktualizace. Spusťte z nového balíčku: update.sh INSTALL_DIR --recover --yes")
                    if store.pendingTransaction {
                        Button("Přejít k obnově…") { store.selection = .environment }
                            .buttonStyle(.borderedProminent)
                    }
                }
            }

            if let d = store.doctor, d.version != AppInfo.version, AppInfo.version != "vývojová" {
                Card(title: "Rozdílné verze", systemImage: "arrow.triangle.2.circlepath") {
                    Text("Aplikace má verzi \(AppInfo.version), ale claude-manager.py v INSTALL_DIR má verzi \(d.version). Aktualizujte instalaci příkazem update.sh, nebo sestavte aplikaci ze stejného balíčku.")
                        .foregroundStyle(.secondary)
                }
            }

            HStack(spacing: 14) {
                StatTile(value: "\(store.config.profiles.count)", label: "Profily Claude", symbol: "person.2")
                StatTile(value: "\(store.tools.reduce(0) { $0 + $1.profiles.count })", label: "Další CLI",
                         symbol: "square.stack.3d.up")
                StatTile(value: "\(store.backups.filter { !$0.isImport }.count)", label: "Zálohy",
                         symbol: "externaldrive")
                StatTile(value: store.doctor.map { $0.issues.isEmpty ? "OK" : "\($0.issues.count)" } ?? "…",
                         label: store.doctor?.issues.isEmpty ?? true ? "Diagnostika" : "Problémy",
                         symbol: "stethoscope",
                         tint: (store.doctor?.issues.isEmpty ?? true) ? .green : .orange)
                StatTile(value: store.doctor?.version ?? "…", label: "Verze správce", symbol: "shippingbox")
            }

            if let d = store.doctor, !d.issues.isEmpty {
                Card(title: "Zjištěné problémy", systemImage: "exclamationmark.bubble") {
                    ForEach(d.issues, id: \.self) { issue in
                        Label(issue, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                    }
                    Button("Otevřít diagnostiku") { store.selection = .environment }
                }
            }

            HStack {
                Text("Profily").font(.title2.weight(.semibold))
                Spacer()
                Button { store.showRegister = true } label: { Label("Zaregistrovat existující", systemImage: "tray.and.arrow.down") }
                Button { store.showNewProfile = true } label: { Label("Nový profil", systemImage: "plus") }
                    .buttonStyle(.borderedProminent)
            }

            if store.config.profiles.isEmpty {
                EmptyProfilesView()
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 270), spacing: 14)], spacing: 14) {
                    ForEach(store.config.profiles) { ProfileCard(profile: $0) }
                }
            }
        }
    }
}

struct StatTile: View {
    let value: String
    let label: String
    let symbol: String
    var tint: Color = .accentColor

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: symbol).font(.title2).foregroundStyle(tint).frame(width: 30)
            VStack(alignment: .leading, spacing: 2) {
                Text(value).font(.title2.weight(.semibold)).monospacedDigit()
                Text(label).font(.callout).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .frame(maxWidth: .infinity)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08)))
    }
}

struct ProfileCard: View {
    @EnvironmentObject var store: Store
    let profile: Profile

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: profile.kind.symbol)
                    .font(.title2).foregroundStyle(.tint)
                    .frame(width: 38, height: 38)
                    .background(Color.accentColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
                VStack(alignment: .leading) {
                    Text(profile.name).font(.headline)
                    Text(profile.kind.title).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Menu { ProfileQuickActions(profile: profile) } label: { Image(systemName: "ellipsis.circle") }
                    .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
            }
            VStack(alignment: .leading, spacing: 3) {
                if let c = profile.cliDir { Text("CLI: " + c.tildePath).lineLimit(1).truncationMode(.middle) }
                if let g = profile.guiDir { Text("GUI: " + g.tildePath).lineLimit(1).truncationMode(.middle) }
                Text("\(profile.projects.count) projektů · \(store.backups.filter { $0.profile == profile.name }.count) záloh")
            }
            .font(.caption).foregroundStyle(.secondary)
            HStack {
                if profile.kind.hasCLI {
                    Button { store.launchCLI(profile.name) } label: { Label("CLI", systemImage: "terminal") }
                }
                if profile.kind.hasGUI {
                    Button { Task { await store.launchGUI(profile.name) } } label: {
                        Label("Desktop", systemImage: "macwindow")
                    }
                }
                Spacer()
                Button("Detail") { store.selection = .profile(profile.name) }
                    .buttonStyle(.link)
            }
            .controlSize(.small)
        }
        .padding(14)
        .frame(minHeight: 168, alignment: .top)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08)))
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { store.selection = .profile(profile.name) }
    }
}

struct EmptyProfilesView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 10) {
                Text("Začněte prvním profilem").font(.headline)
                Text("1. V části Prostředí nastavte cestu ke skutečnému Claude CLI.\n2. Zaregistrujte stávající data (~/.claude a ~/Library/Application Support/Claude), ať je můžete zálohovat.\n3. Vytvořte nové profily, např. „osobni“ a „pracovni“, a vygenerujte jejich spouštěče.")
                    .foregroundStyle(.secondary)
                HStack {
                    Button("Nastavit prostředí") { store.selection = .environment }
                    Button("Zaregistrovat existující data") { store.showRegister = true }
                    Button("Nový profil") { store.showNewProfile = true }.buttonStyle(.borderedProminent)
                }
            }
        }
    }
}

/// Shown when claude-manager.py or Python cannot be found.
struct SetupView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        VStack(spacing: 18) {
            Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 96, height: 96)
            Text("Vítejte v Claude Profile Manageru").font(.largeTitle.weight(.semibold))
            Text("Aplikace je grafickým rozhraním pro skript claude-manager.py. Vyberte jeho instalaci (INSTALL_DIR), ve které jsou uložené registry profilů, spouštěče a zálohy.")
                .multilineTextAlignment(.center).foregroundStyle(.secondary).frame(maxWidth: 520)
            ManagerLocationForm().frame(maxWidth: 560)
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct ManagerLocationForm: View {
    @EnvironmentObject var store: Store

    var body: some View {
        Form {
            LabeledContent("claude-manager.py") {
                HStack {
                    TextField("", text: $store.scriptPath, prompt: Text("~/.local/share/claude-profile-manager/claude-manager.py"))
                    Button("Vybrat…") {
                        if let p = choosePath(directories: false, types: ["py"]) {
                            if ManagerClient.isManagerScript(p) { store.scriptPath = p }
                            else { store.errorAlert = "Vybraný soubor není claude-manager.py." }
                        }
                    }
                }
            }
            LabeledContent("Python 3.9+") {
                HStack {
                    TextField("", text: $store.pythonPath)
                    Button("Vybrat…") { if let p = choosePath(directories: false) { store.pythonPath = p } }
                }
            }
            HStack {
                StatusDot(ok: store.isConfigured)
                Text(store.isConfigured ? "Instalace nalezena: \(store.client.installDir.path.tildePath)"
                                        : "Soubor nebo Python nebyl nalezen.")
                    .foregroundStyle(.secondary)
                Spacer()
                Button("Najít automaticky") {
                    store.pythonPath = ManagerClient.detectPython()
                    if let s = ManagerClient.detectScript() { store.scriptPath = s }
                }
                Button("Použít") { Task { await store.refresh() } }
                    .buttonStyle(.borderedProminent).disabled(!store.isConfigured)
            }
        }
        .formStyle(.grouped)
    }
}

struct PreferencesView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ManagerLocationForm()
            Text("Aplikace sama nic neinstaluje. Všechny operace provádí claude-manager.py se stejnými pojistkami jako v Terminálu: dry-run, ověřené zálohy, zámky a journal.")
                .font(.callout).foregroundStyle(.secondary).padding([.horizontal, .bottom], 20)
        }
    }
}

@MainActor
func choosePath(directories: Bool, types: [String] = [], message: String? = nil,
                startAt: String? = nil) -> String? {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = directories
    panel.canChooseFiles = !directories
    panel.allowsMultipleSelection = false
    panel.treatsFilePackagesAsDirectories = types.isEmpty && !directories
    panel.showsHiddenFiles = true
    if let message { panel.message = message }
    if let startAt { panel.directoryURL = URL(fileURLWithPath: startAt) }
    if !types.isEmpty {
        panel.allowedContentTypes = types.compactMap { .init(filenameExtension: $0) }
    }
    return panel.runModal() == .OK ? panel.url?.path : nil
}

@MainActor
func chooseSavePath(defaultName: String) -> String? {
    let panel = NSSavePanel()
    panel.nameFieldStringValue = defaultName
    panel.canCreateDirectories = true
    return panel.runModal() == .OK ? panel.url?.path : nil
}
