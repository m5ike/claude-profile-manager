import AppKit
import SwiftUI

/// Visual language shared by every screen: brand palette, badge icons, logo.
enum Brand {
    static let accent = Color(hex: 0x4F46E5)      // indigo – primary actions, selection
    static let accentLight = Color(hex: 0x6366F1)
    static let deep = Color(hex: 0x1E1B4B)
    static let violet = Color(hex: 0x7C3AED)

    static let heroGradient = LinearGradient(
        colors: [Color(hex: 0x6366F1), Color(hex: 0x4338CA), Color(hex: 0x1E1B4B)],
        startPoint: .topLeading, endPoint: .bottomTrailing)

    /// Neutral, distinguishable colours (deliberately not the vendors' brand colours).
    static func color(forTool id: String) -> Color {
        switch id {
        case "codex": return Color(hex: 0x0D9488)
        case "gemini": return Color(hex: 0x2563EB)
        case "copilot": return Color(hex: 0x64748B)
        case "opencode": return Color(hex: 0xD97706)
        case "grok": return Color(hex: 0xE11D48)
        default: return accent
        }
    }

    static func color(for kind: ProfileKind) -> Color {
        switch kind {
        case .cli: return accent
        case .gui: return Color(hex: 0x0EA5E9)
        case .both: return violet
        }
    }
}

extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255, opacity: opacity)
    }
}

/// Rounded, gradient-filled symbol tile – the app's icon style for profiles, tools and sections.
struct BadgeIcon: View {
    let symbol: String
    var color: Color = Brand.accent
    var size: CGFloat = 28

    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.28, style: .continuous)
            .fill(LinearGradient(colors: [color.opacity(0.85), color],
                                 startPoint: .topLeading, endPoint: .bottomTrailing))
            .overlay(RoundedRectangle(cornerRadius: size * 0.28, style: .continuous)
                .strokeBorder(Color.white.opacity(0.18)))
            .overlay(Image(systemName: symbol)
                .font(.system(size: size * 0.5, weight: .semibold))
                .foregroundStyle(.white))
            .frame(width: size, height: size)
            .shadow(color: color.opacity(0.25), radius: size * 0.12, y: size * 0.05)
            .accessibilityHidden(true)
    }
}

/// The app logo (bundled Logo.svg; falls back to the application icon).
struct LogoView: View {
    var size: CGFloat = 48

    private static let image: NSImage = {
        if let url = Bundle.main.url(forResource: "Logo", withExtension: "svg"),
           let img = NSImage(contentsOf: url) { return img }
        return NSApp.applicationIconImage
    }()

    var body: some View {
        Image(nsImage: Self.image)
            .resizable()
            .interpolation(.high)
            .frame(width: size, height: size)
            .accessibilityLabel("Claude Profile Manager")
    }
}

/// Small rounded label, e.g. "CLI", "2 profily".
struct Pill: View {
    let text: String
    var color: Color = .secondary

    var body: some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 7).padding(.vertical, 2)
            .foregroundStyle(color)
            .background(color.opacity(0.12), in: Capsule())
    }
}
