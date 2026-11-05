import SwiftUI

struct NewProfileSheet: View {
    @EnvironmentObject var store: Store
    @Environment(\.dismiss) private var dismiss
    let register: Bool

    @State private var name = ""
    @State private var kind: ProfileKind = .both
    @State private var cliDir = ""
    @State private var guiDir = ""
    @State private var makeLaunchers = true
    @State private var working = false

    private var nameValid: Bool { isValidProfileName(name) }
    private var exists: Bool { store.profile(name) != nil }
    private var pathsValid: Bool {
        guard register else { return true }
        if kind.hasCLI && !cliDir.hasPrefix("/") { return false }
        if kind.hasGUI && !guiDir.hasPrefix("/") { return false }
        return true
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 4) {
                Text(register ? "Zaregistrovat existující data" : "Nový profil").font(.title2.weight(.semibold))
                Text(register
                     ? "Převezme existující adresáře bez kopírování a beze změny obsahu, např. výchozí ~/.claude."
                     : "Vytvoří prázdné, oddělené datové adresáře. Přihlásíte se při prvním spuštění.")
                    .foregroundStyle(.secondary)
            }
            .padding([.horizontal, .top], 20)

            Form {
                Section {
                    TextField("Název", text: $name, prompt: Text("např. osobni"))
                    if !name.isEmpty && !nameValid {
                        Text("1–32 malých písmen ASCII, číslic, _ a -; začíná písmenem; prefix gui- je rezervovaný.")
                            .font(.caption).foregroundStyle(.red)
                    } else if exists {
                        Text("Profil s tímto názvem už existuje.").font(.caption).foregroundStyle(.red)
                    }
                    Picker("Typ profilu", selection: $kind) {
                        ForEach(ProfileKind.allCases) { Label($0.title, systemImage: $0.symbol).tag($0) }
                    }
                    .pickerStyle(.radioGroup)
                }
                Section(register ? "Adresáře (povinné)" : "Adresáře (volitelné – jinak výchozí)") {
                    if kind.hasCLI {
                        DirectoryField(label: "CLI data", path: $cliDir,
                                       placeholder: register ? "~/.claude" : "INSTALL_DIR/data/claude-\(name.isEmpty ? "NAZEV" : name)",
                                       suggestion: register ? NSHomeDirectory() + "/.claude" : nil)
                    }
                    if kind.hasGUI {
                        DirectoryField(label: "Desktop data", path: $guiDir,
                                       placeholder: register ? "~/Library/Application Support/Claude"
                                           : "~/Library/Application Support/Claude-\(name.isEmpty ? "NAZEV" : name)",
                                       suggestion: register ? NSHomeDirectory() + "/Library/Application Support/Claude" : nil)
                    }
                }
                Section {
                    Toggle("Po vytvoření vygenerovat spouštěče (claude-\(name.isEmpty ? "NAZEV" : name), Claude \(name.isEmpty ? "NAZEV" : name).app)",
                           isOn: $makeLaunchers)
                } footer: {
                    Text(register
                         ? "Používejte jen jednu registraci pro každou skutečnou cestu. Přihlašovací údaje se nekopírují."
                         : "Profil CLI + Desktop vytvoří oba datové kořeny i oba spouštěče.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .formStyle(.grouped)

            HStack {
                Spacer()
                Button("Zrušit", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button(register ? "Zaregistrovat" : "Vytvořit profil") {
                    working = true
                    Task {
                        let ok = await store.createProfile(
                            name: name, kind: kind,
                            cliDir: cliDir.isEmpty ? nil : (cliDir as NSString).expandingTildeInPath,
                            guiDir: guiDir.isEmpty ? nil : (guiDir as NSString).expandingTildeInPath,
                            register: register, makeLaunchers: makeLaunchers)
                        working = false
                        if ok { dismiss() }
                    }
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(!nameValid || exists || !pathsValid || working)
            }
            .padding(20)
        }
        .frame(width: 600)
    }
}

struct DirectoryField: View {
    let label: String
    @Binding var path: String
    let placeholder: String
    var suggestion: String?

    var body: some View {
        LabeledContent(label) {
            HStack {
                TextField("", text: $path, prompt: Text(placeholder))
                if let suggestion, path.isEmpty {
                    Button("Výchozí") { path = suggestion }
                }
                Button("Vybrat…") {
                    if let p = choosePath(directories: true) { path = p }
                }
            }
        }
    }
}
