import SwiftUI

struct ContentView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        Group {
            if store.isConfigured {
                NavigationSplitView {
                    SidebarView()
                        .navigationSplitViewColumnWidth(min: 210, ideal: 240, max: 320)
                } detail: {
                    detail
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            } else {
                SetupView()
            }
        }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                if let label = store.busyLabel {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.small)
                        Text(label).font(.callout).foregroundStyle(.secondary)
                    }
                }
                Button { Task { await store.refresh() } } label: {
                    Label("Obnovit", systemImage: "arrow.clockwise")
                }
                .help("Znovu načíst profily, zálohy a diagnostiku (⌘R)")
                .disabled(store.isBusy || !store.isConfigured)
                Menu {
                    Button("Nový profil…") { store.showNewProfile = true }
                    Button("Zaregistrovat existující data…") { store.showRegister = true }
                } label: {
                    Label("Přidat profil", systemImage: "plus")
                } primaryAction: {
                    store.showNewProfile = true
                }
                .help("Vytvořit nový profil (⌘N)")
                .disabled(!store.isConfigured)
                Button { store.openHelp() } label: { Label("Nápověda", systemImage: "questionmark.circle") }
                    .help("Otevřít nápovědu v PDF")
            }
        }
        .overlay(alignment: .bottom) { BannerView() }
        .sheet(isPresented: $store.showNewProfile) { NewProfileSheet(register: false) }
        .sheet(isPresented: $store.showRegister) { NewProfileSheet(register: true) }
        .alert("Operaci nelze dokončit", isPresented: Binding(
            get: { store.errorAlert != nil }, set: { if !$0 { store.errorAlert = nil } })) {
            Button("Zobrazit protokol") { store.selection = .activity; store.errorAlert = nil }
            Button("OK", role: .cancel) { store.errorAlert = nil }
        } message: {
            Text(store.errorAlert ?? "")
        }
        .task {
            await store.refresh()
            await Snapshotter.run(store: store)
        }
    }

    @ViewBuilder private var detail: some View {
        switch store.selection ?? .overview {
        case .overview: OverviewView()
        case .profile(let name):
            if let p = store.profile(name) { ProfileDetailView(profile: p).id(name) }
            else { OverviewView() }
        case .backups: BackupsView()
        case .migration: MigrationView()
        case .projects: ProjectsView()
        case .environment: EnvironmentView()
        case .activity: ActivityView()
        case .tool(let id):
            if let t = store.tool(id) { ToolView(tool: t).id(id) } else { OverviewView() }
        }
    }
}

struct SidebarView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        List(selection: $store.selection) {
            Section("Správce") {
                Label("Přehled", systemImage: "square.grid.2x2").tag(SidebarItem.overview)
            }
            Section("Profily") {
                if store.config.profiles.isEmpty {
                    Text("Zatím žádné profily").foregroundStyle(.secondary).font(.callout)
                }
                ForEach(store.config.profiles) { p in
                    Label {
                        HStack {
                            Text(p.name)
                            Spacer()
                            Text(p.kind.rawValue.uppercased())
                                .font(.caption2.weight(.semibold))
                                .foregroundStyle(.secondary)
                        }
                    } icon: {
                        Image(systemName: p.kind.symbol)
                    }
                    .tag(SidebarItem.profile(p.name))
                    .contextMenu { ProfileQuickActions(profile: p) }
                }
            }
            Section("Další AI nástroje") {
                ForEach(store.tools) { t in
                    Label {
                        HStack {
                            Text(t.title)
                            Spacer()
                            if !t.profiles.isEmpty {
                                Text("\(t.profiles.count)").font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
                            }
                        }
                    } icon: { Image(systemName: t.symbol) }
                    .tag(SidebarItem.tool(t.id))
                }
            }
            Section("Nástroje") {
                Label("Zálohy a přenos", systemImage: "externaldrive.badge.timemachine").tag(SidebarItem.backups)
                Label("Migrace", systemImage: "arrow.left.arrow.right").tag(SidebarItem.migration)
                Label("Projekty", systemImage: "folder").tag(SidebarItem.projects)
                Label("Prostředí a diagnostika", systemImage: "stethoscope").tag(SidebarItem.environment)
                Label {
                    HStack {
                        Text("Protokol činností")
                        Spacer()
                        if store.log.contains(where: { !$0.succeeded }) {
                            Image(systemName: "exclamationmark.circle.fill").foregroundStyle(.orange)
                        }
                    }
                } icon: { Image(systemName: "list.bullet.rectangle") }
                .tag(SidebarItem.activity)
            }
        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .bottom) {
            VStack(alignment: .leading, spacing: 0) {
            if store.pendingTransaction || store.pendingUpdate {
                Button { store.selection = .environment } label: {
                    Label(store.pendingTransaction ? "Přerušená transakce" : "Přerušená aktualizace",
                          systemImage: "exclamationmark.triangle.fill")
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.borderless)
                .foregroundStyle(.orange)
                .padding(10)
            }
            Text("Aplikace \(AppInfo.version) · správce \(store.doctor?.version ?? "…")")
                .font(.caption2).foregroundStyle(.tertiary)
                .padding(.horizontal, 14).padding(.bottom, 8)
            }
        }
    }
}

/// Shared quick actions (context menu + overview cards).
struct ProfileQuickActions: View {
    @EnvironmentObject var store: Store
    let profile: Profile

    var body: some View {
        if profile.kind.hasCLI {
            Button("Spustit CLI v Terminálu") { store.launchCLI(profile.name) }
        }
        if profile.kind.hasGUI {
            Button("Spustit Claude Desktop") { Task { await store.launchGUI(profile.name) } }
        }
        Divider()
        Button("Zálohovat celý profil") {
            Task {
                if let r = await store.execute(["backup", profile.name, "--scope", "both"],
                                               label: "Zálohuji \(profile.name)…",
                                               success: "Záloha profilu \(profile.name) vytvořena a ověřena.") {
                    _ = r
                    await store.refresh()
                }
            }
        }
        Button("Vygenerovat spouštěče") {
            Task { await store.execute(["launchers", profile.name], label: "Generuji spouštěče…",
                                       success: "Spouštěče aktualizovány.") }
        }
        Divider()
        if let cli = profile.cliDir { Button("Zobrazit CLI data ve Finderu") { store.reveal(cli) } }
        if let gui = profile.guiDir { Button("Zobrazit Desktop data ve Finderu") { store.reveal(gui) } }
    }
}

struct BannerView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        if let b = store.banner {
            HStack(spacing: 8) {
                Image(systemName: b.isError ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
                    .foregroundStyle(b.isError ? .orange : .green)
                Text(b.text)
            }
            .padding(.horizontal, 16).padding(.vertical, 10)
            .background(.regularMaterial, in: Capsule())
            .shadow(radius: 6, y: 2)
            .padding(.bottom, 18)
            .transition(.move(edge: .bottom).combined(with: .opacity))
            .animation(.spring, value: store.banner)
            .onTapGesture { store.banner = nil }
        }
    }
}

/// Reusable page scaffold: title, subtitle and scrolling content.
struct Page<Content: View>: View {
    let title: String
    let subtitle: String?
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(title).font(.largeTitle.weight(.semibold))
                    if let subtitle { Text(subtitle).foregroundStyle(.secondary) }
                }
                content
            }
            .padding(28)
            .frame(maxWidth: 980, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct Card<Content: View>: View {
    var title: String?
    var systemImage: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let title {
                Label(title, systemImage: systemImage ?? "circle")
                    .font(.headline)
                    .labelStyle(.titleAndIcon)
            }
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08)))
    }
}

struct PathRow: View {
    @EnvironmentObject var store: Store
    let label: String
    let path: String?

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label).foregroundStyle(.secondary).frame(width: 210, alignment: .leading)
            if let path {
                Text(path.tildePath).textSelection(.enabled).font(.system(.body, design: .monospaced))
                    .lineLimit(1).truncationMode(.middle)
                Spacer()
                Button { store.reveal(path) } label: { Image(systemName: "arrow.right.circle") }
                    .buttonStyle(.borderless).help("Zobrazit ve Finderu")
            } else {
                Text("—").foregroundStyle(.tertiary)
                Spacer()
            }
        }
    }
}

struct ResultView: View {
    let title: String
    let text: String
    var isError = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(title, systemImage: isError ? "xmark.octagon.fill" : "checkmark.seal.fill")
                .foregroundStyle(isError ? .red : .green)
                .font(.headline)
            ScrollView {
                Text(text)
                    .font(.system(.callout, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
            }
            .frame(minHeight: 80, maxHeight: 260)
            .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color.primary.opacity(0.1)))
        }
    }
}

struct StatusDot: View {
    let ok: Bool
    var body: some View {
        Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
            .foregroundStyle(ok ? .green : .orange)
    }
}
