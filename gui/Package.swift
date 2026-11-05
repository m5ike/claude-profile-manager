// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "ClaudeProfileManager",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "ClaudeProfileManager",
            path: "Sources/ClaudeProfileManager"
        )
    ]
)
