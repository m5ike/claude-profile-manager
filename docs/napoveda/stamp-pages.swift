// Adds "Claude Profile Manager – Nápověda · strana N / M" footers (cover page excluded).
// Usage: swift stamp-pages.swift in.pdf out.pdf
import AppKit
import PDFKit

let args = CommandLine.arguments
guard args.count == 3, let doc = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
    FileHandle.standardError.write("usage: stamp-pages.swift in.pdf out.pdf\n".data(using: .utf8)!); exit(2)
}
let total = doc.pageCount
let out = NSMutableData()
let consumer = CGDataConsumer(data: out as CFMutableData)!
var box = doc.page(at: 0)!.bounds(for: .mediaBox)
let ctx = CGContext(consumer: consumer, mediaBox: &box, nil)!
let font = NSFont.systemFont(ofSize: 7.5)
let attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: NSColor(white: 0.45, alpha: 1)]

for i in 0..<total {
    let page = doc.page(at: i)!
    var media = page.bounds(for: .mediaBox)
    ctx.beginPage(mediaBox: &media)
    page.draw(with: .mediaBox, to: ctx)
    if i > 0 {
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: false)
        let left = NSAttributedString(string: "Claude Profile Manager – Nápověda", attributes: attrs)
        let right = NSAttributedString(string: "\(i + 1) / \(total)", attributes: attrs)
        left.draw(at: NSPoint(x: 48, y: 26))
        right.draw(at: NSPoint(x: media.width - 48 - right.size().width, y: 26))
        NSGraphicsContext.restoreGraphicsState()
    }
    ctx.endPage()
}
ctx.closePDF()
let result = PDFDocument(data: out as Data)!
// Keep the clickable table-of-contents links from the source PDF.
for i in 0..<total {
    for a in doc.page(at: i)!.annotations { result.page(at: i)!.addAnnotation(a.copy() as! PDFAnnotation) }
}
result.documentAttributes = [PDFDocumentAttribute.titleAttribute: "Claude Profile Manager – Nápověda",
                             PDFDocumentAttribute.subjectAttribute: "Uživatelská příručka grafické aplikace pro macOS"]
result.write(to: URL(fileURLWithPath: args[2]))
print("Pages: \(total)")
