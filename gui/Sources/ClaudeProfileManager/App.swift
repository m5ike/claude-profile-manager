import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct ClaudeProfileManagerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var store = Store()

    var body: some Scene {
        WindowGroup("Claude Profile Manager") {
            ContentView()
                .environmentObject(store)
                .tint(Brand.accent)
                .frame(minWidth: 980, minHeight: 640)
        }
        .windowToolbarStyle(.unified)
        .commands {
            CommandGroup(replacing: .appInfo) {
                Button("O aplikaci Claude Profile Manager") {
                    let credits = NSAttributedString(
                        string: "Správce oddělených profilů Claude Code, Claude Desktop, Codex CLI, Gemini CLI, Copilot CLI, opencode a Grok Build CLI.\nBackend claude-manager.py \(store.doctor?.version ?? "?")",
                        attributes: [.font: NSFont.systemFont(ofSize: 11), .foregroundColor: NSColor.secondaryLabelColor])
                    NSApp.orderFrontStandardAboutPanel(options: [.credits: credits])
                }
            }
            CommandGroup(replacing: .newItem) {
                Button("Nový profil…") { store.showNewProfile = true }
                    .keyboardShortcut("n")
                Button("Zaregistrovat existující data…") { store.showRegister = true }
                    .keyboardShortcut("n", modifiers: [.command, .shift])
            }
            CommandMenu("Správce") {
                Button("Obnovit") { Task { await store.refresh() } }
                    .keyboardShortcut("r")
                Divider()
                Button("Přehled") { store.selection = .overview }.keyboardShortcut("1")
                Button("Zálohy a přenos") { store.selection = .backups }.keyboardShortcut("2")
                Button("Migrace") { store.selection = .migration }.keyboardShortcut("3")
                Button("Projekty") { store.selection = .projects }.keyboardShortcut("4")
                Button("Prostředí a diagnostika") { store.selection = .environment }.keyboardShortcut("5")
                Button("Protokol činností") { store.selection = .activity }.keyboardShortcut("l")
            }
            CommandGroup(replacing: .help) {
                Button("Nápověda Claude Profile Manager") { store.openHelp() }
                    .keyboardShortcut("?")
            }
        }

        Settings {
            PreferencesView()
                .environmentObject(store)
                .frame(width: 560)
        }
    }
}
