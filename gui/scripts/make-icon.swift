// Renders gui/Resources/Logo.svg into a PNG (needs macOS 14+, where NSImage reads SVG).
// Usage: swift make-icon.swift Logo.svg out.png [size]
import AppKit

let args = CommandLine.arguments
guard args.count >= 3, let logo = NSImage(contentsOf: URL(fileURLWithPath: args[1])) else {
    FileHandle.standardError.write("usage: make-icon.swift Logo.svg out.png [size]\n".data(using: .utf8)!)
    exit(2)
}
let size = args.count > 3 ? Int(args[3]) ?? 1024 : 1024
guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                                 bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                 colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { exit(1) }
rep.size = NSSize(width: size, height: size)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
NSGraphicsContext.current?.imageInterpolation = .high
logo.draw(in: NSRect(x: 0, y: 0, width: size, height: size))
NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: args[2]))
