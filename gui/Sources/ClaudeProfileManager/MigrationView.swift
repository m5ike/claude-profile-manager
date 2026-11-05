import SwiftUI

/// Lets other screens hand a preselected backup to the migration form.
@MainActor
final class MigrationDraft {
    static let shared = MigrationDraft()
    var preselectBackup: String?
}

struct MigrationView: View {
    enum SourceKind: String, CaseIterable, Identifiable {
        case profile, backup
        var id: String { rawValue }
    }

    @EnvironmentObject var store: Store
    @State private var sourceKind: SourceKind = .profile
    @State private var sourceProfile = ""
    @State private var sourceBackup = ""
    @State private var target = ""
    @State private var scope: Scope = .cli
    @State private var components: Set<Component> = Set(Component.allCases)
    @State private var conflict: ConflictPolicy = .error
    @State private var workspaces = false
    @State private var credentials = false
    @State private var mappings = ""
    @State private var dryRunOK: [String]?
    @State private var result: (title: String, text: String, error: Bool)?
    @State private var confirmApply = false

    private var baseArgs: [String] {
        var args: [String] = sourceKind == .profile
            ? ["migrate", sourceProfile, target] : ["migrate-backup", sourceBackup, target]
        args += ["--scope", scope.rawValue,
                 "--components", Component.allCases.filter(components.contains).map(\.rawValue).joined(separator: ","),
                 "--conflict", conflict.rawValue]
        if workspaces { args.append("--workspaces") }
        if credentials && sourceKind == .profile { args.append("--credentials") }
        return args + mappingArguments(mappings)
    }

    private var mappingsValid: Bool {
        mappings.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }.allSatisfy {
            let parts = $0.split(separator: "=", maxSplits: 1).map(String.init)
            return parts.count == 2 && parts[0].hasPrefix("/") && parts[1].hasPrefix("/") && parts[0] != "/"
        }
    }

    private var formValid: Bool {
        let source = sourceKind == .profile ? sourceProfile : sourceBackup
        return !source.isEmpty && !target.isEmpty && !components.isEmpty && mappingsValid
            && !(sourceKind == .profile && sourceProfile == target)
    }

    var body: some View {
        Page(title: "Migrace", subtitle: "Přenos vybraných komponent mezi profily nebo ze zálohy. Vždy nejprve zkouška nanečisto.", symbol: "arrow.left.arrow.right", tint: Brand.violet) {
            StepsView(current: dryRunOK == baseArgs ? 2 : 1)

            Card(title: "Zdroj a cíl", systemImage: "arrow.left.arrow.right") {
                Picker("Zdroj", selection: $sourceKind) {
                    Text("Profil").tag(SourceKind.profile)
                    Text("Ověřená / importovaná záloha").tag(SourceKind.backup)
                }
                .labelsHidden().pickerStyle(.segmented).frame(maxWidth: 420)
                Grid(alignment: .leading, verticalSpacing: 10) {
                    GridRow {
                        Text("Zdroj").foregroundStyle(.secondary)
                        if sourceKind == .profile {
                            Picker("", selection: $sourceProfile) {
                                Text("Vyberte…").tag("")
                                ForEach(store.config.profiles) { Text($0.name).tag($0.name) }
                            }.labelsHidden().frame(width: 300)
                        } else {
                            Picker("", selection: $sourceBackup) {
                                Text("Vyberte…").tag("")
                                ForEach(store.backups) { b in
                                    Text("\(b.profile) · \(b.created?.formatted(date: .abbreviated, time: .shortened) ?? b.name)\(b.isImport ? " (import)" : "")")
                                        .tag(b.path.path)
                                }
                            }.labelsHidden().frame(width: 300)
                        }
                    }
                    GridRow {
                        Text("Cíl").foregroundStyle(.secondary)
                        Picker("", selection: $target) {
                            Text("Vyberte…").tag("")
                            ForEach(store.config.profiles) { Text($0.name).tag($0.name) }
                        }.labelsHidden().frame(width: 300)
                    }
                    GridRow {
                        Text("Rozsah").foregroundStyle(.secondary)
                        Picker("", selection: $scope) {
                            ForEach(Scope.allCases) { Text($0.title).tag($0) }
                        }.labelsHidden().pickerStyle(.segmented).frame(width: 300)
                    }
                }
                Text("Rozsah určuje, které lokální datové stromy se mění. Nejde o převod CLI na Desktop ani naopak.")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Card(title: "Komponenty", systemImage: "square.stack.3d.up") {
                ForEach(Component.allCases) { c in
                    Toggle(c.title, isOn: Binding(
                        get: { components.contains(c) },
                        set: { if $0 { components.insert(c) } else { components.remove(c) } }))
                }
                Text("Aktivace pluginů (enabledPlugins) je součást settings.json – pro plný přenos zvolte pluginy i nastavení.")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Card(title: "Možnosti", systemImage: "gearshape.2") {
                Picker("Při konfliktu", selection: $conflict) {
                    ForEach(ConflictPolicy.allCases) { Text($0.title).tag($0) }
                }
                .frame(maxWidth: 420)
                Toggle("Přenést i scratch workspaces Desktopu (--workspaces)", isOn: $workspaces)
                if sourceKind == .profile {
                    Toggle("Kopírovat CLI .credentials.json (--credentials)", isOn: $credentials)
                    if credentials {
                        Label("Kopíruje se jen souborový CLI credential, ne Keychain ani přihlášení Desktopu.",
                              systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange)
                    }
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text("Přemapování cest projektů (jeden řádek STARÁ=NOVÁ, absolutní cesty)")
                    TextEditor(text: $mappings)
                        .font(.system(.callout, design: .monospaced))
                        .frame(height: 64)
                        .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(mappingsValid ? Color.primary.opacity(0.15) : .red))
                }
            }

            HStack {
                Button {
                    Task { await run(apply: false) }
                } label: { Label("1. Zkouška nanečisto (dry-run)", systemImage: "eye") }
                .controlSize(.large)
                .disabled(!formValid || store.isBusy)
                Button {
                    confirmApply = true
                } label: { Label("2. Provést migraci", systemImage: "checkmark.circle") }
                .controlSize(.large).buttonStyle(.borderedProminent)
                .disabled(dryRunOK != baseArgs || store.isBusy)
                .help("Aktivní až po úspěšné zkoušce se stejnými parametry")
                Spacer()
            }
            if let result { ResultView(title: result.title, text: result.text, isError: result.error) }
        }
        .confirmationDialog("Provést migraci do profilu \(target)?", isPresented: $confirmApply) {
            Button("Zazálohovat cíl a provést") { Task { await run(apply: true) } }
        } message: {
            Text("Před zápisem se vytvoří záloha cílového profilu. Všechny Claude procesy musí být ukončené.")
        }
        .onAppear {
            if Snapshotter.directory != nil, store.config.profiles.count > 1 {
                let names = store.config.profiles.filter { $0.kind.hasCLI }.map(\.name)
                sourceProfile = names.first ?? ""; target = names.last ?? ""
                components = [.settings, .skills, .plugins]
                mappings = "/Users/jan/Developer/app=/Users/jan/Developer/app-pracovni"
            }
            if let b = MigrationDraft.shared.preselectBackup {
                sourceKind = .backup; sourceBackup = b; MigrationDraft.shared.preselectBackup = nil
            }
        }
    }

    private func run(apply: Bool) async {
        let args = baseArgs
        let full = apply ? args + ["--apply", "--yes"] : args
        if let r = await store.execute(full, label: apply ? "Provádím migraci…" : "Připravuji a ověřuji staging…",
                                       success: apply ? "Migrace dokončena." : "Zkouška proběhla bez chyb.") {
            dryRunOK = apply ? nil : args
            result = (apply ? "Migrace provedena" : "Výsledek zkoušky – nic nebylo změněno", prettyJSON(r.json), false)
            if apply { await store.refresh() }
        } else {
            dryRunOK = nil
            result = ("Operace odmítnuta", store.log.first?.error ?? "", true)
        }
    }
}

struct StepsView: View {
    let current: Int
    var body: some View {
        HStack(spacing: 0) {
            step(1, "Nastavit parametry a spustit zkoušku")
            Image(systemName: "chevron.right").foregroundStyle(.tertiary).padding(.horizontal, 10)
            step(2, "Zkontrolovat výsledek a provést")
        }
        .font(.callout)
    }

    private func step(_ n: Int, _ text: String) -> some View {
        HStack(spacing: 6) {
            Text("\(n)").font(.caption.weight(.bold)).foregroundStyle(.white)
                .frame(width: 20, height: 20)
                .background(n <= current ? Color.accentColor : Color.secondary.opacity(0.5), in: Circle())
            Text(text).foregroundStyle(n <= current ? .primary : .secondary)
        }
    }
}
