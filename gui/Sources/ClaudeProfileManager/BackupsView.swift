import SwiftUI

struct BackupsView: View {
    @EnvironmentObject var store: Store
    @State private var selection: BackupInfo.ID?
    @State private var restoreTarget: BackupInfo?
    @State private var showImport = false
    @State private var result: (title: String, text: String)?

    private var selected: BackupInfo? { store.backups.first { $0.id == selection } }

    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .top) {
                BadgeIcon(symbol: "externaldrive.fill", color: Color(hex: 0x0891B2), size: 46)
                VStack(alignment: .leading, spacing: 4) {
                    Text("Zálohy a přenos").font(.system(size: 28, weight: .bold, design: .rounded))
                    Text("Ověřené souborové snapshoty v INSTALL_DIR/backups. Plná záloha obsahuje i souborová přihlášení – není šifrovaná.")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button { showImport = true } label: { Label("Importovat archiv…", systemImage: "square.and.arrow.down") }
            }
            .padding([.horizontal, .top], 28).padding(.bottom, 14)

            Table(store.backups, selection: $selection) {
                TableColumn("Vytvořeno") { b in
                    Label(b.created.map { $0.formatted(date: .abbreviated, time: .standard) } ?? "—",
                          systemImage: b.isImport ? "square.and.arrow.down" : "clock")
                }
                .width(min: 170, ideal: 190)
                TableColumn("Profil") { Text($0.profile) }.width(min: 80, ideal: 110)
                TableColumn("Rozsah") { Text($0.scopes.joined(separator: " + ").uppercased()) }.width(min: 70, ideal: 90)
                TableColumn("Položek") { Text("\($0.entries)").monospacedDigit() }.width(min: 60, ideal: 70)
                TableColumn("Druh") { Text($0.isImport ? "Import" : "Záloha") }.width(min: 60, ideal: 70)
                TableColumn("Adresář") { Text($0.name).font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary) }
            }
            .contextMenu(forSelectionType: BackupInfo.ID.self) { ids in
                if let id = ids.first, let b = store.backups.first(where: { $0.id == id }) { actions(for: b) }
            }
            .overlay {
                if store.backups.isEmpty {
                    VStack(spacing: 8) {
                        Image(systemName: "externaldrive").font(.largeTitle).foregroundStyle(.tertiary)
                        Text("Zatím žádné zálohy").foregroundStyle(.secondary)
                        Text("Zálohu vytvoříte v detailu profilu.").font(.caption).foregroundStyle(.tertiary)
                    }
                }
            }

            Divider()
            HStack(spacing: 10) {
                if let b = selected {
                    actionsBar(for: b)
                } else {
                    Text("Vyberte zálohu pro ověření, obnovu, export nebo migraci.").foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(14)
            if let result {
                ResultView(title: result.title, text: result.text).padding([.horizontal, .bottom], 14)
            }
        }
        .sheet(item: $restoreTarget) { RestoreSheet(backup: $0) }
        .onAppear { if Snapshotter.directory != nil { selection = store.backups.first?.id } }
        .sheet(isPresented: $showImport) { ImportSheet() }
    }

    @ViewBuilder private func actionsBar(for b: BackupInfo) -> some View {
        Button { verify(b) } label: { Label("Ověřit integritu", systemImage: "checkmark.shield") }
        Button { restoreTarget = b } label: { Label("Obnovit…", systemImage: "clock.arrow.circlepath") }
            .disabled(b.isImport)
            .help(b.isImport ? "Importovanou zálohu z jiného Macu přeneste přes Migraci." : "Přesná obnova do původních cest")
        Button { export(b) } label: { Label("Exportovat…", systemImage: "square.and.arrow.up") }
        Button { store.selection = .migration; MigrationDraft.shared.preselectBackup = b.path.path } label: {
            Label("Migrovat do profilu…", systemImage: "arrow.right.doc.on.clipboard")
        }
        Button { store.reveal(b.path.path) } label: { Label("Finder", systemImage: "folder") }
    }

    @ViewBuilder private func actions(for b: BackupInfo) -> some View {
        Button("Ověřit integritu") { verify(b) }
        Button("Obnovit…") { restoreTarget = b }.disabled(b.isImport)
        Button("Exportovat…") { export(b) }
        Button("Migrovat do profilu…") { store.selection = .migration; MigrationDraft.shared.preselectBackup = b.path.path }
        Divider()
        Button("Zobrazit ve Finderu") { store.reveal(b.path.path) }
    }

    private func verify(_ b: BackupInfo) {
        Task {
            if let r = await store.execute(["verify", b.path.path], label: "Ověřuji SHA-256…",
                                           success: "Záloha je kompletní a neporušená.") {
                result = ("Ověření zálohy", prettyJSON(r.json))
            }
        }
    }

    private func export(_ b: BackupInfo) {
        guard let out = chooseSavePath(defaultName: "claude-\(b.profile)-transfer.tar.gz") else { return }
        Task {
            if let r = await store.execute(["export", b.path.path, out], label: "Exportuji archiv…",
                                           success: "Archiv vytvořen.") {
                let sha = (try? String(contentsOfFile: out + ".sha256", encoding: .utf8))?
                    .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                result = ("Export dokončen",
                          prettyJSON(r.json) + "\n\nSHA-256 (předejte jiným důvěryhodným kanálem):\n" + sha)
            }
        }
    }
}

struct RestoreSheet: View {
    @EnvironmentObject var store: Store
    @Environment(\.dismiss) private var dismiss
    let backup: BackupInfo
    @State private var target = ""
    @State private var scope: Scope = .both
    @State private var understood = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Přesná obnova snapshotu", systemImage: "clock.arrow.circlepath").font(.title2.weight(.semibold))
            Text("Obnova nahradí vybrané kořeny profilu obsahem zálohy, včetně souborových přihlášení. Vyžaduje stejné původní cesty. Před obnovou se automaticky vytvoří záloha aktuálního stavu. Keychain se neobnovuje a platnost tokenů není zaručena.")
                .foregroundStyle(.secondary)
            Form {
                Picker("Profil", selection: $target) {
                    ForEach(store.config.profiles) { Text($0.name).tag($0.name) }
                }
                Picker("Rozsah", selection: $scope) {
                    ForEach(Scope.allCases) { Text($0.title).tag($0) }
                }
                .pickerStyle(.segmented)
                LabeledContent("Záloha", value: backup.name)
                LabeledContent("Obsahuje", value: backup.scopes.joined(separator: " + ").uppercased())
            }
            .formStyle(.grouped)
            Toggle("Rozumím, že aktuální data profilu budou nahrazena a všechny Claude procesy jsou ukončené.", isOn: $understood)
            HStack {
                Spacer()
                Button("Zrušit", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Obnovit", role: .destructive) {
                    Task {
                        if await store.execute(["restore", target, backup.path.path, "--scope", scope.rawValue, "--yes"],
                                               label: "Obnovuji…", success: "Obnova dokončena.") != nil {
                            await store.refresh()
                            dismiss()
                        }
                    }
                }
                .buttonStyle(.borderedProminent).tint(.red)
                .disabled(!understood || target.isEmpty)
            }
        }
        .padding(22).frame(width: 560)
        .onAppear { target = store.profile(backup.profile) != nil ? backup.profile : "" }
    }
}

struct ImportSheet: View {
    @EnvironmentObject var store: Store
    @Environment(\.dismiss) private var dismiss
    @State private var archive = ""
    @State private var sha = ""
    @State private var output: String?

    private var shaValid: Bool { sha.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Import archivu z jiného Macu", systemImage: "square.and.arrow.down").font(.title2.weight(.semibold))
            Text("Import pouze ověří a bezpečně rozbalí zálohu do správce – žádný profil nepřepisuje. Data pak přenesete přes Migraci → Ze zálohy.")
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
                        TextField("", text: $sha, prompt: Text("64 znaků malými písmeny"))
                            .font(.system(.body, design: .monospaced))
                        Button("Ze souboru .sha256") {
                            if let s = try? String(contentsOfFile: archive + ".sha256", encoding: .utf8) {
                                sha = String(s.prefix(64)).lowercased()
                            } else {
                                store.show("Soubor \(archive).sha256 nebyl nalezen.", error: true)
                            }
                        }
                        .disabled(archive.isEmpty)
                    }
                }
            }
            .formStyle(.grouped)
            Label("Hash ze stejného úložiště jako archiv chrání jen před poškozením, ne před podvržením. Ideálně ho ověřte z jiného, důvěryhodného kanálu.",
                  systemImage: "info.circle")
                .font(.caption).foregroundStyle(.secondary)
            if let output { ResultView(title: "Import dokončen", text: output) }
            HStack {
                Spacer()
                Button(output == nil ? "Zrušit" : "Zavřít", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Importovat") {
                    Task {
                        if let r = await store.execute(["import", archive, "--sha256", sha], label: "Ověřuji a rozbaluji…",
                                                       success: "Archiv importován.") {
                            output = prettyJSON(r.json)
                            await store.refresh()
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(archive.isEmpty || !shaValid || output != nil)
            }
        }
        .padding(22).frame(width: 620)
    }
}
