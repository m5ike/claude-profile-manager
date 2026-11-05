// Renders the app icon (1024×1024 PNG). Usage: swift make-icon.swift out.png
import AppKit

let size: CGFloat = 1024
let image = NSImage(size: NSSize(width: size, height: size))
image.lockFocus()
let ctx = NSGraphicsContext.current!.cgContext
let inset: CGFloat = 100
let rect = CGRect(x: inset, y: inset, width: size - 2 * inset, height: size - 2 * inset)
let path = CGPath(roundedRect: rect, cornerWidth: 185, cornerHeight: 185, transform: nil)

ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -12), blur: 30, color: NSColor.black.withAlphaComponent(0.35).cgColor)
ctx.addPath(path); ctx.setFillColor(NSColor.black.cgColor); ctx.fillPath()
ctx.restoreGState()

ctx.saveGState()
ctx.addPath(path); ctx.clip()
let colors = [NSColor(calibratedRed: 0.86, green: 0.47, blue: 0.33, alpha: 1).cgColor,
              NSColor(calibratedRed: 0.55, green: 0.25, blue: 0.20, alpha: 1).cgColor] as CFArray
let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0, 1])!
ctx.drawLinearGradient(gradient, start: CGPoint(x: 0, y: size), end: CGPoint(x: size, y: 0), options: [])
ctx.restoreGState()

func symbol(_ name: String, _ pt: CGFloat, _ alpha: CGFloat, at center: CGPoint) {
    let cfg = NSImage.SymbolConfiguration(pointSize: pt, weight: .semibold)
        .applying(.init(paletteColors: [NSColor.white.withAlphaComponent(alpha)]))
    guard let img = NSImage(systemSymbolName: name, accessibilityDescription: nil)?.withSymbolConfiguration(cfg) else { return }
    let s = img.size
    img.draw(in: CGRect(x: center.x - s.width / 2, y: center.y - s.height / 2, width: s.width, height: s.height))
}
symbol("person.2.fill", 380, 1.0, at: CGPoint(x: size / 2, y: size / 2 + 70))
symbol("terminal", 120, 0.9, at: CGPoint(x: size / 2 - 120, y: 270))
symbol("macwindow", 120, 0.9, at: CGPoint(x: size / 2 + 120, y: 270))
image.unlockFocus()

let rep = NSBitmapImageRep(data: image.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
