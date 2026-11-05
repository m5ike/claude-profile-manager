import SwiftUI

struct ProjectsView: View {
    @EnvironmentObject var store: Store
    @State private var profile = ""
    @State private var source = ""
    @State private var destination = ""
    @State private var dryRunOK: [String]?
    @State private var result: (title: String, text: String, error: Bool)?

    private var args: [String] { ["project-copy", profile, source, destination] }

    var body: some View {
        Page(title: "Projekty", subtitle: "Evidence projektových adresářů a bezpečné kopírování projektu pro jiný profil.", symbol: "folder.fill", tint: Color(hex: 0x2563EB)) {
            Card(title: "Evidované projekty", systemImage: "folder") {
                if store.config.profiles.allSatisfy({ $0.projects.isEmpty }) {
                    Text("Žádný profil zatím nemá evidovaný projekt.").foregroundStyle(.secondary)
                }
                ForEach(store.config.profiles.filter { !$0.projects.isEmpty }) { p in
                    Text(p.name).font(.subheadline.weight(.semibold)).padding(.top, 4)
                    ForEach(p.projects, id: \.self) { PathRow(label: "", path: $0) }
                }
                Menu("Přidat existující projekt do profilu") {
                    ForEach(store.config.profiles) { p in
                        Button(p.name) {
                            if let dir = choosePath(directories: true) {
                                Task {
                                    await store.execute(["project-add", p.name, dir], label: "Přidávám…",
                                                        success: "Projekt přidán do profilu \(p.name).")
                                    await store.refresh()
                                }
                            }
                        }
                    }
                }
                .fixedSize()
            }

            Card(title: "Kopírovat projekt", systemImage: "doc.on.doc") {
                Text("Vytvoří nový adresář a ověří kopii včetně necommitnutých souborů a .git. Existující cíl se nikdy nepřepíše. Linked worktree, submodul, externí symlinky a aktivní Git locky jsou odmítnuty.")
                    .font(.callout).foregroundStyle(.secondary)
                Form {
                    Picker("Cílový profil", selection: $profile) {
                        Text("Vyberte…").tag("")
                        ForEach(store.config.profiles) { Text($0.name).tag($0.name) }
                    }
                    DirectoryField(label: "Zdrojový projekt", path: $source, placeholder: "~/Developer/aplikace")
                    LabeledContent("Nový adresář") {
                        HStack {
                            TextField("", text: $destination, prompt: Text("~/Developer/aplikace-pracovni"))
                            Button("Vybrat…") { if let p = chooseSavePath(defaultName: (source as NSString).lastPathComponent + "-kopie") { destination = p } }
                        }
                    }
                }
                .formStyle(.grouped)
                HStack {
                    Button("Zkouška nanečisto") { Task { await run(apply: false) } }
                        .disabled(profile.isEmpty || !source.hasPrefix("/") || !destination.hasPrefix("/"))
                    Button("Kopírovat") { Task { await run(apply: true) } }
                        .buttonStyle(.borderedProminent)
                        .disabled(dryRunOK != args)
                    Spacer()
                }
                Text("Tip: po zkopírování použijte v Migraci přemapování STARÁ=NOVÁ cesta, aby historie ukazovala na novou kopii.")
                    .font(.caption).foregroundStyle(.secondary)
                if let result { ResultView(title: result.title, text: result.text, isError: result.error) }
            }
        }
    }

    private func run(apply: Bool) async {
        let a = args
        if let r = await store.execute(apply ? a + ["--apply", "--yes"] : a,
                                       label: apply ? "Kopíruji projekt…" : "Kontroluji projekt…",
                                       success: apply ? "Projekt zkopírován a ověřen." : "Kontrola v pořádku.") {
            dryRunOK = apply ? nil : a
            result = (apply ? "Kopie dokončena" : "Výsledek zkoušky", prettyJSON(r.json), false)
            if apply { await store.refresh() }
        } else {
            dryRunOK = nil
            result = ("Odmítnuto", store.log.first?.error ?? "", true)
        }
    }
}
