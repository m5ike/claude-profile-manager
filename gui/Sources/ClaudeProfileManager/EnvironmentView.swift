import SwiftUI

struct EnvironmentView: View {
    @EnvironmentObject var store: Store
    @State private var binary = ""
    @State private var guiApp = ""
    @State private var confirmPath = false
    @State private var confirmRecover = false
    @State private var doctorJSON = ""

    var body: some View {
        Page(title: "Prostředí a diagnostika", subtitle: "Cesty ke Claude, PATH v shellu a kontrola stavu instalace.") {
            Card(title: "Claude Code CLI", systemImage: "terminal") {
                Text("Absolutní cesta ke skutečnému spustitelnému souboru claude – ne k symlinku na tohoto správce.")
                    .font(.callout).foregroundStyle(.secondary)
                HStack {
                    TextField("", text: $binary, prompt: Text("/Users/…/.local/bin/claude"))
                        .font(.system(.body, design: .monospaced))
                    Button("Najít") { Task { await detectBinary() } }
                        .help("Zjistí `command -v claude` v přihlašovacím shellu")
                    Button("Vybrat…") { if let p = choosePath(directories: false) { binary = p } }
                    Button("Uložit") {
                        Task { await store.execute(["set-binary", binary], label: "Ověřuji…", success: "Cesta ke Claude CLI uložena.")
                               await store.refresh() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(binary.isEmpty || binary == store.config.binary)
                }
                if let b = store.doctor?.binary {
                    Label("Používá se: \(b.tildePath)", systemImage: "checkmark.circle").foregroundStyle(.green).font(.callout)
                }
            }

            Card(title: "Claude Desktop", systemImage: "macwindow") {
                HStack {
                    TextField("", text: $guiApp).font(.system(.body, design: .monospaced))
                    Button("Vybrat…") {
                        if let p = choosePath(directories: true, message: "Vyberte Claude.app", startAt: "/Applications") { guiApp = p }
                    }
                    Button("Uložit") {
                        Task { await store.execute(["set-gui-app", guiApp], label: "Ověřuji…", success: "Cesta k Claude.app uložena.")
                               await store.refresh() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(guiApp.isEmpty || guiApp == store.config.guiApp)
                }
            }

            Card(title: "Příkazy claude-NAZEV v Terminálu (PATH)", systemImage: "chevron.left.forwardslash.chevron.right") {
                if let d = store.doctor {
                    if d.pathNotRequired {
                        Text("Žádný profil nemá CLI – PATH není potřeba.").foregroundStyle(.secondary)
                    } else {
                        HStack { StatusDot(ok: d.pathManagedBlock == true); Text("Blok správce v \(d.pathFile?.tildePath ?? "shell rc")") }
                        HStack { StatusDot(ok: d.pathInCurrent == true); Text("INSTALL_DIR/sbin v PATH aktuálního prostředí aplikace") }
                        if d.pathManagedBlock != true {
                            Button("Přidat blok do shellu…") { confirmPath = true }.buttonStyle(.borderedProminent)
                        } else {
                            Text("Nové okno Terminálu načte změny automaticky.").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }

            Card(title: "Diagnostika", systemImage: "stethoscope") {
                if let d = store.doctor {
                    Grid(alignment: .leading, verticalSpacing: 6) {
                        GridRow { Text("Verze správce").foregroundStyle(.secondary); Text(d.version) }
                        GridRow { Text("Python").foregroundStyle(.secondary); Text(d.python) }
                        GridRow { Text("INSTALL_DIR").foregroundStyle(.secondary); Text(d.root.tildePath).textSelection(.enabled) }
                    }
                    if d.issues.isEmpty {
                        Label("Nebyly nalezeny žádné problémy.", systemImage: "checkmark.seal.fill").foregroundStyle(.green)
                    } else {
                        ForEach(d.issues, id: \.self) { Label($0, systemImage: "exclamationmark.triangle").foregroundStyle(.orange) }
                    }
                }
                HStack {
                    Button("Spustit diagnostiku") {
                        Task {
                            if let r = await store.execute(["doctor"], label: "Diagnostika…") { doctorJSON = prettyJSON(r.json) }
                            await store.refresh()
                        }
                    }
                    if store.pendingTransaction {
                        Button("Obnovit přerušenou transakci…") { confirmRecover = true }
                            .buttonStyle(.borderedProminent).tint(.orange)
                    }
                    Button("Otevřít INSTALL_DIR") { store.reveal(store.client.installDir.path) }
                }
                if !doctorJSON.isEmpty { ResultView(title: "Výstup doctor", text: doctorJSON) }
            }
        }
        .onAppear {
            binary = store.config.binary; guiApp = store.config.guiApp
            if Snapshotter.directory != nil { binary = binary.tildePath }
        }
        .onChange(of: store.config.binary) { binary = $0 }
        .confirmationDialog("Upravit spouštěcí soubor shellu?", isPresented: $confirmPath) {
            Button("Zazálohovat a přidat blok") {
                Task { await store.execute(["path", "--write", "--yes"], label: "Upravuji shell…",
                                           success: "PATH blok přidán. Otevřete nové okno Terminálu."); await store.refresh() }
            }
        } message: {
            Text("Do \(store.doctor?.pathFile?.tildePath ?? "~/.zshrc") se přidá označený, idempotentní blok s INSTALL_DIR/sbin. Ostatní obsah zůstane beze změny a původní soubor se zazálohuje do shell-backups.")
        }
        .confirmationDialog("Spustit obnovu přerušené transakce?", isPresented: $confirmRecover) {
            Button("Spustit recover") {
                Task { await store.execute(["recover"], label: "Obnovuji…", success: "Obnova dokončena."); await store.refresh() }
            }
        } message: {
            Text("Ukončete všechny Claude procesy. Obnova podle journalu dokončí potvrzený commit, nebo vrátí původní kořeny. Nemažte ručně transaction.json ani adresáře .cm-*.")
        }
    }

    private func detectBinary() async {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/zsh")
        p.arguments = ["-lic", "command -v claude"]
        let out = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        p.standardInput = FileHandle.nullDevice
        do {
            try p.run()
            let data = await Task.detached { out.fileHandleForReading.readDataToEndOfFile() }.value
            p.waitUntilExit()
            let path = String(decoding: data, as: UTF8.self).split(separator: "\n")
                .map(String.init).last { $0.hasPrefix("/") } ?? ""
            let resolved = (path as NSString).resolvingSymlinksInPath
            if path.isEmpty {
                store.show("Příkaz claude nebyl v shellu nalezen.", error: true)
            } else if resolved.hasSuffix("claude-manager.py") {
                store.show("Nalezený claude je spouštěč tohoto správce – vyberte skutečný binary.", error: true)
            } else {
                binary = path
            }
        } catch {
            store.show(error.localizedDescription, error: true)
        }
    }
}

struct ActivityView: View {
    @EnvironmentObject var store: Store
    @State private var selection: LogEntry.ID?

    var body: some View {
        HSplitView {
            List(store.log, selection: $selection) { e in
                HStack(alignment: .top) {
                    StatusDot(ok: e.succeeded)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(e.arguments.first ?? "").font(.headline)
                        Text(e.date.formatted(date: .omitted, time: .standard)).font(.caption).foregroundStyle(.secondary)
                    }
                }
                .tag(e.id)
            }
            .frame(minWidth: 220, idealWidth: 260)
            .overlay { if store.log.isEmpty { Text("Zatím žádné operace").foregroundStyle(.secondary) } }

            VStack(alignment: .leading, spacing: 12) {
                if let e = store.log.first(where: { $0.id == selection }) ?? store.log.first {
                    HStack {
                        Text(e.commandLine).font(.system(.body, design: .monospaced)).textSelection(.enabled)
                        Spacer()
                        Button("Kopírovat") {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString("$ \(e.commandLine)\n\(e.output)\(e.error)", forType: .string)
                        }
                    }
                    Text("Návratový kód \(e.status) · \(e.date.formatted(date: .abbreviated, time: .standard))")
                        .foregroundStyle(.secondary)
                    if !e.output.isEmpty { ResultView(title: "Výstup", text: e.output) }
                    if !e.error.isEmpty { ResultView(title: "Chybový výstup", text: e.error, isError: !e.succeeded) }
                    Spacer()
                } else {
                    Text("Protokol obsahuje všechny příkazy, které aplikace předala claude-manager.py, včetně jejich výstupu.")
                        .foregroundStyle(.secondary)
                    Spacer()
                }
            }
            .padding(20)
            .frame(minWidth: 420, maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .toolbar {
            ToolbarItem {
                Button { store.log.removeAll() } label: { Label("Vymazat protokol", systemImage: "trash") }
                    .disabled(store.log.isEmpty)
            }
        }
    }
}
