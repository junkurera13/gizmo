import AppKit
import Foundation
import ImageIO
import UniformTypeIdentifiers

guard CommandLine.arguments.count == 3 else {
    FileHandle.standardError.write(Data("usage: make_app_icon source.png AppIcon.icns\n".utf8))
    exit(2)
}

let sourceURL = URL(fileURLWithPath: CommandLine.arguments[1])
let icnsURL = URL(fileURLWithPath: CommandLine.arguments[2])

guard
    let sourceImage = NSImage(contentsOf: sourceURL),
    let source = sourceImage.cgImage(forProposedRect: nil, context: nil, hints: nil)
else {
    FileHandle.standardError.write(Data("could not read source icon\n".utf8))
    exit(3)
}

let iconset = FileManager.default.temporaryDirectory
    .appendingPathComponent("GizmoAppIcon-\(UUID().uuidString).iconset", isDirectory: true)

try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)

let sizes: [(name: String, pixels: Int)] = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]

for size in sizes {
    guard
        let context = CGContext(
            data: nil,
            width: size.pixels,
            height: size.pixels,
            bitsPerComponent: 8,
            bytesPerRow: 0,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue
        )
    else {
        FileHandle.standardError.write(Data("could not scale icon to \(size.pixels)\n".utf8))
        exit(4)
    }

    context.interpolationQuality = .none
    context.draw(source, in: CGRect(x: 0, y: 0, width: size.pixels, height: size.pixels))

    guard let scaled = context.makeImage() else {
        FileHandle.standardError.write(Data("could not write \(size.name)\n".utf8))
        exit(5)
    }

    let url = iconset.appendingPathComponent(size.name)
    guard
        let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)
    else {
        FileHandle.standardError.write(Data("could not create \(size.name)\n".utf8))
        exit(6)
    }
    CGImageDestinationAddImage(destination, scaled, nil)
    guard CGImageDestinationFinalize(destination) else {
        FileHandle.standardError.write(Data("could not finalize \(size.name)\n".utf8))
        exit(7)
    }
}

let process = Process()
process.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
process.arguments = ["-c", "icns", "-o", icnsURL.path, iconset.path]
try process.run()
process.waitUntilExit()
try? FileManager.default.removeItem(at: iconset)

guard process.terminationStatus == 0 else {
    FileHandle.standardError.write(Data("iconutil failed\n".utf8))
    exit(Int32(process.terminationStatus))
}
