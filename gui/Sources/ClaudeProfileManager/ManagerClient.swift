import Foundation

struct CommandResult {
    let status: Int32
    let stdout: String
    let stderr: String

    var json: Any? {
        guard let data = stdout.data(using: .utf8), !data.isEmpty else { return nil }
        return try? JSONSerialization.jsonObject(with: data)
    }

    /// Error text emitted by claude-manager.py ("ERROR: ...") without the prefix.
    var errorMessage: String {
        let lines = stderr.split(separator: "\n").map(String.init)
        if let line = lines.last(where: { $0.hasPrefix("ERROR: ") }) {
            return String(line.dropFirst("ERROR: ".count))
        }
        let text = stderr.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? "Příkaz skončil s kódem \(status)." : text
    }
}

struct ManagerError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

/// Thin, stateless bridge to claude-manager.py. All safety logic (dry-runs, locks, backups,
/// journals) stays in the Python backend; the GUI only builds argument lists.
struct ManagerClient {
    var python: String
    var script: String

    var installDir: URL { URL(fileURLWithPath: script).deletingLastPathComponent() }

    func run(_ arguments: [String], environment extra: [String: String] = [:]) async -> CommandResult {
        let python = self.python, script = self.script
        return await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: python)
                process.arguments = [script] + arguments
                var env = ProcessInfo.processInfo.environment
                env["PYTHONUNBUFFERED"] = "1"
                env["PYTHONIOENCODING"] = "utf-8"
                for (k, v) in extra { env[k] = v }
                process.environment = env
                process.standardInput = FileHandle.nullDevice
                let out = Pipe(), err = Pipe()
                process.standardOutput = out
                process.standardError = err
                var outData = Data(), errData = Data()
                let group = DispatchGroup()
                group.enter()
                DispatchQueue.global().async {
                    outData = out.fileHandleForReading.readDataToEndOfFile(); group.leave()
                }
                group.enter()
                DispatchQueue.global().async {
                    errData = err.fileHandleForReading.readDataToEndOfFile(); group.leave()
                }
                do {
                    try process.run()
                } catch {
                    try? out.fileHandleForWriting.close()
                    try? err.fileHandleForWriting.close()
                    group.wait()
                    continuation.resume(returning: CommandResult(
                        status: 127, stdout: "",
                        stderr: "ERROR: Nelze spustit \(python): \(error.localizedDescription)"))
                    return
                }
                process.waitUntilExit()
                group.wait()
                continuation.resume(returning: CommandResult(
                    status: process.terminationStatus,
                    stdout: String(decoding: outData, as: UTF8.self),
                    stderr: String(decoding: errData, as: UTF8.self)))
            }
        }
    }

    // MARK: - Discovery

    static let defaultScriptCandidates: [String] = [
        NSHomeDirectory() + "/.local/share/claude-profile-manager/claude-manager.py",
        NSHomeDirectory() + "/Applications/claude-profile-manager/claude-manager.py",
    ]

    static let pythonCandidates = [
        "/opt/homebrew/bin/python3", "/usr/local/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/Current/bin/python3", "/usr/bin/python3",
    ]

    static func detectPython() -> String {
        pythonCandidates.first { FileManager.default.isExecutableFile(atPath: $0) } ?? "/usr/bin/python3"
    }

    static func detectScript() -> String? {
        var candidates = defaultScriptCandidates
        // App built inside the repository (gui/build/…): look for a sibling checkout.
        var dir = Bundle.main.bundleURL.deletingLastPathComponent()
        for _ in 0..<4 {
            candidates.append(dir.appendingPathComponent("claude-manager.py").path)
            dir.deleteLastPathComponent()
        }
        return candidates.first { FileManager.default.fileExists(atPath: $0) }
    }

    static func isManagerScript(_ path: String) -> Bool {
        guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return false }
        return text.contains("Claude Profile Manager") && text.contains("def dispatch(")
    }

    // MARK: - Filesystem reads (read-only, no backend lock needed)

    func listBackups() -> [BackupInfo] {
        let base = installDir.appendingPathComponent("backups")
        let fm = FileManager.default
        guard let items = try? fm.contentsOfDirectory(at: base, includingPropertiesForKeys: nil) else {
            return []
        }
        return items.compactMap { url -> BackupInfo? in
            let manifest = url.appendingPathComponent("manifest.json")
            guard let data = try? Data(contentsOf: manifest),
                  let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return nil
            }
            let roots = raw["roots"] as? [String: Any] ?? [:]
            let files = raw["files"] as? [String: Any] ?? [:]
            let count = files.values.reduce(0) { $0 + (($1 as? [String: Any])?.count ?? 0) }
            let created = (raw["created"] as? Double).map { Date(timeIntervalSince1970: $0) }
            return BackupInfo(path: url, profile: raw["profile"] as? String ?? "?",
                              created: created, complete: raw["complete"] as? Bool ?? false,
                              scopes: roots.keys.sorted(), entries: count)
        }.sorted { ($0.created ?? .distantPast) > ($1.created ?? .distantPast) }
    }

    func listToolBackups() -> [ToolBackupInfo] {
        let base = installDir.appendingPathComponent("tool-backups")
        guard let items = try? FileManager.default.contentsOfDirectory(at: base, includingPropertiesForKeys: nil)
        else { return [] }
        return items.compactMap { url -> ToolBackupInfo? in
            guard let data = try? Data(contentsOf: url.appendingPathComponent("manifest.json")),
                  let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  raw["format"] as? String == "tool-1", raw["complete"] as? Bool == true else { return nil }
            return ToolBackupInfo(path: url, tool: raw["tool"] as? String ?? "?",
                                  profile: raw["profile"] as? String ?? "?",
                                  created: (raw["created"] as? Double).map { Date(timeIntervalSince1970: $0) },
                                  entries: (raw["files"] as? [String: Any])?.count ?? 0)
        }.sorted { ($0.created ?? .distantPast) > ($1.created ?? .distantPast) }
    }

    var hasPendingTransaction: Bool {
        FileManager.default.fileExists(atPath: installDir.appendingPathComponent("transaction.json").path)
    }

    var hasPendingUpdate: Bool {
        FileManager.default.fileExists(atPath: installDir.appendingPathComponent("update-transaction.json").path)
    }
}
