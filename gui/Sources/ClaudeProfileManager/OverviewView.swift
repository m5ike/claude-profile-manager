import AppKit
import SwiftUI

struct OverviewView: View {
    @EnvironmentObject var store: Store

    private var toolProfiles: Int { store.tools.reduce(0) { $0 + $1.profiles.count } }

    var body: some View {
        Page(title: "", subtitle: nil) {
            HeroHeader(claudeProfiles: store.config.profiles.count, toolProfiles: toolProfiles,
                       backups: store.backups.filter { !$0.isImport }.count + store.toolBackups.count,
                       healthy: store.doctor?.issues.isEmpty ?? true)

            if store.pendingTransaction || store.pendingUpdate {
                Card(title: "Vyžaduje pozornost", systemImage: "exclamationmark.triangle.fill", tint: .orange) {
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
                Card(title: "Rozdílné verze", systemImage: "arrow.triangle.2.circlepath", tint: .orange) {
                    Text("Aplikace má verzi \(AppInfo.version), ale claude-manager.py v INSTALL_DIR má verzi \(d.version). Aktualizujte instalaci příkazem update.sh, nebo sestavte aplikaci ze stejného balíčku.")
                        .foregroundStyle(.secondary)
                }
            }
            if let d = store.doctor, !d.issues.isEmpty {
                Card(title: "Zjištěné problémy", systemImage: "stethoscope", tint: .orange) {
                    ForEach(d.issues, id: \.self) { issue in
                        Label(issue, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                    }
                    Button("Otevřít diagnostiku") { store.selection = .environment }
                }
            }

            SectionTitle(title: "Profily Claude", detail: "Claude Code CLI a Claude Desktop") {
                Button { store.showRegister = true } label: { Label("Zaregistrovat existující", systemImage: "tray.and.arrow.down") }
                Button { store.showNewProfile = true } label: { Label("Nový profil", systemImage: "plus") }
                    .buttonStyle(.borderedProminent)
            }
            if store.config.profiles.isEmpty {
                EmptyProfilesView()
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 280), spacing: 16)], spacing: 16) {
                    ForEach(store.config.profiles) { ProfileCard(profile: $0) }
                }
            }

            SectionTitle(title: "Další AI nástroje", detail: "Codex, Gemini, Copilot, opencode a Grok") { EmptyView() }
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12), count: 5), spacing: 12) {
                ForEach(store.tools) { ToolSummaryCard(tool: $0) }
            }
        }
    }
}

/// Gradient banner with the logo and the key numbers.
struct HeroHeader: View {
    let claudeProfiles: Int
    let toolProfiles: Int
    let backups: Int
    let healthy: Bool

    var body: some View {
        HStack(alignment: .center, spacing: 22) {
            LogoView(size: 96)
                .shadow(color: .black.opacity(0.25), radius: 10, y: 4)
            VStack(alignment: .leading, spacing: 8) {
                Text("Claude Profile Manager")
                    .font(.system(size: 26, weight: .bold, design: .rounded))
                Text("Oddělené účty, konfigurace a historie pro Claude Code, Claude Desktop a další AI nástroje na jednom Macu.")
                    .font(.callout).opacity(0.88)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 8) {
                    HeroStat(value: "\(claudeProfiles)", label: "Claude")
                    HeroStat(value: "\(toolProfiles)", label: "další CLI")
                    HeroStat(value: "\(backups)", label: "záloh")
                    HeroStat(value: healthy ? "OK" : "!", label: "diagnostika")
                    HeroStat(value: AppInfo.version, label: "verze")
                }
                .padding(.top, 4)
            }
            Spacer(minLength: 0)
        }
        .foregroundStyle(.white)
        .padding(24)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            ZStack(alignment: .topTrailing) {
                Brand.heroGradient
                Circle().fill(.white.opacity(0.08)).frame(width: 260, height: 260).offset(x: 90, y: -120)
                Circle().fill(.white.opacity(0.06)).frame(width: 160, height: 160).offset(x: -40, y: 110)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: Brand.accent.opacity(0.25), radius: 14, y: 6)
    }
}

struct HeroStat: View {
    let value: String
    let label: String
    var body: some View {
        HStack(spacing: 5) {
            Text(value).font(.callout.weight(.bold)).monospacedDigit()
            Text(label).font(.caption).opacity(0.8)
        }
        .padding(.horizontal, 10).padding(.vertical, 5)
        .background(.white.opacity(0.16), in: Capsule())
    }
}

struct SectionTitle<Actions: View>: View {
    let title: String
    var detail: String?
    @ViewBuilder var actions: Actions
    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title).font(.title2.weight(.bold))
            if let detail { Text(detail).foregroundStyle(.secondary) }
            Spacer()
            actions
        }
        .padding(.top, 6)
    }
}

/// Clickable tile per AI tool on the overview.
struct ToolSummaryCard: View {
    @EnvironmentObject var store: Store
    let tool: ToolInfo

    private var count: String {
        switch tool.profiles.count {
        case 0: return "Bez profilů"
        case 1: return "1 profil"
        case 2...4: return "\(tool.profiles.count) profily"
        default: return "\(tool.profiles.count) profilů"
        }
    }

    var body: some View {
        Button { store.selection = .tool(tool.id) } label: {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    BadgeIcon(symbol: tool.symbol, color: Brand.color(forTool: tool.id), size: 34)
                    Spacer()
                    Image(systemName: tool.binary == nil ? "exclamationmark.circle" : "checkmark.circle.fill")
                        .foregroundStyle(tool.binary == nil ? .orange : .green)
                        .help(tool.binary == nil ? "Program nebyl nalezen" : "Program nalezen")
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(tool.shortName).font(.headline).foregroundStyle(.primary).lineLimit(1)
                    Text(tool.vendor).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Pill(text: count, color: tool.profiles.isEmpty ? .secondary : Brand.color(forTool: tool.id))
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(nsColor: .controlBackgroundColor),
                        in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.primary.opacity(0.07)))
            .shadow(color: .black.opacity(0.05), radius: 8, y: 2)
            .contentShape(Rectangle())
            .help(tool.title)
        }
        .buttonStyle(.plain)
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
                BadgeIcon(symbol: profile.kind.symbol, color: Brand.color(for: profile.kind), size: 40)
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
        .padding(16)
        .frame(minHeight: 168, alignment: .top)
        .background(Color(nsColor: .controlBackgroundColor),
                    in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.primary.opacity(0.07)))
        .shadow(color: .black.opacity(0.05), radius: 8, y: 2)
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
            LogoView(size: 110)
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
