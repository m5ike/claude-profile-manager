import AppKit
import SwiftUI

/// Documentation helper: when launched with `-snapshotDir /path`, the app walks through its
/// main screens, renders its own window into PNG files and quits. Needs no Screen Recording
/// permission because it only draws the app's own views.
@MainActor
enum Snapshotter {
    static var directory: String? { UserDefaults.standard.string(forKey: "snapshotDir") }
    /// One-shot request for ToolView to open its migration sheet during a snapshot run.
    static var openToolMigration = false

    static func run(store: Store) async {
        guard let dir = directory else { return }
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        if UserDefaults.standard.string(forKey: "snapshotAppearance") == "light" {
            NSApp.appearance = NSAppearance(named: .aqua)
        }
        try? await Task.sleep(nanoseconds: 1_500_000_000)
        guard let window = NSApp.windows.first(where: { $0.isVisible && $0.contentView != nil }) else { return }
        window.setContentSize(NSSize(width: 1180, height: 760))
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        let first = store.config.profiles.first(where: { $0.kind == .both })?.name ?? store.config.profiles.first?.name
        var steps: [(String, SidebarItem)] = [("01-prehled", .overview)]
        if let first { steps.append(("02-profil", .profile(first))) }
        steps += [("09-codex", .tool("codex")), ("10-opencode", .tool("opencode")), ("12-grok", .tool("grok"))]
        steps += [("04-zalohy", .backups), ("05-migrace", .migration), ("06-projekty", .projects),
                  ("07-prostredi", .environment), ("08-protokol", .activity)]

        // Keep documentation screenshots free of machine-specific absolute paths.
        let home = ProcessInfo.processInfo.environment["HOME"] ?? NSHomeDirectory()
        for (name, item) in steps {
            if item == .activity {
                store.log = store.log.map { e in
                    var e = e
                    e.output = e.output.replacingOccurrences(of: home, with: "~")
                    return e
                }
            }
            store.selection = item
            try? await Task.sleep(nanoseconds: 900_000_000)
            capture(window, to: "\(dir)/\(name).png")
            if name == "10-opencode" {
                openToolMigration = true
                store.selection = .tool("codex")
                try? await Task.sleep(nanoseconds: 1_400_000_000)
                if let sheet = window.attachedSheet { capture(sheet, to: "\(dir)/11-migrace-nastroje.png") }
                sheet: do { window.attachedSheet.map { window.endSheet($0) } }
                try? await Task.sleep(nanoseconds: 700_000_000)
            }
            if name == "02-profil" {
                store.showNewProfile = true
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                if let sheet = window.attachedSheet { capture(sheet, to: "\(dir)/03-novy-profil.png") }
                store.showNewProfile = false
                try? await Task.sleep(nanoseconds: 700_000_000)
            }
        }
        NSApp.terminate(nil)
    }

    static func capture(_ window: NSWindow, to path: String) {
        // Capture the whole frame view so the title bar / toolbar are included.
        guard let view = window.contentView?.superview ?? window.contentView else { return }
        view.layoutSubtreeIfNeeded()
        guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: rep)
        if let data = rep.representation(using: .png, properties: [:]) {
            try? data.write(to: URL(fileURLWithPath: path))
        }
    }
}
