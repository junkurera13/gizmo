import AppKit
import Foundation

guard CommandLine.arguments.count == 4 else {
    fputs("usage: prepare_device_skin.swift <source.png> <idle.png> <pressed.png>\n", stderr)
    exit(2)
}

let sourceURL = URL(fileURLWithPath: CommandLine.arguments[1])
let idleURL = URL(fileURLWithPath: CommandLine.arguments[2])
let pressedURL = URL(fileURLWithPath: CommandLine.arguments[3])

guard
    let sourceImage = NSImage(contentsOf: sourceURL),
    let sourceData = sourceImage.tiffRepresentation,
    let source = NSBitmapImageRep(data: sourceData)
else {
    fputs("could not read source image\n", stderr)
    exit(1)
}

let width = source.pixelsWide
let height = source.pixelsHigh
let pixelCount = width * height

func makeBitmap() -> NSBitmapImageRep {
    guard let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: width,
        pixelsHigh: height,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else {
        fatalError("could not create output bitmap")
    }
    return bitmap
}

func sourceColor(x: Int, y: Int) -> NSColor {
    source.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB) ?? .clear
}

func byte(_ component: CGFloat) -> UInt8 {
    UInt8(max(0, min(255, Int((component * 255).rounded()))))
}

func writePixel(
    _ bitmap: NSBitmapImageRep,
    x: Int,
    y: Int,
    red: UInt8,
    green: UInt8,
    blue: UInt8,
    alpha: UInt8
) {
    guard let data = bitmap.bitmapData else { return }
    let offset = (y * bitmap.bytesPerRow) + (x * 4)
    data[offset] = red
    data[offset + 1] = green
    data[offset + 2] = blue
    data[offset + 3] = alpha
}

func readPixel(_ bitmap: NSBitmapImageRep, x: Int, y: Int) -> (UInt8, UInt8, UInt8, UInt8) {
    guard let data = bitmap.bitmapData else { return (0, 0, 0, 0) }
    let offset = (y * bitmap.bytesPerRow) + (x * 4)
    return (data[offset], data[offset + 1], data[offset + 2], data[offset + 3])
}

// The supplied render has a dark studio background surrounding a continuous
// yellow/pink device silhouette. Flooding only dark pixels from the canvas
// edges removes that connected background while preserving enclosed dark
// details such as the screen, sensor, grille holes, and shell shading.
func isBackgroundCandidate(_ color: NSColor) -> Bool {
    let red = color.redComponent
    let green = color.greenComponent
    let blue = color.blueComponent
    let luminance = (red * 0.2126) + (green * 0.7152) + (blue * 0.0722)
    let isPink = red > 0.08 && red > green * 1.22 && red > blue * 1.08
    return luminance < 0.42 && !isPink
}

var background = [UInt8](repeating: 0, count: pixelCount)
var queue = [Int]()
queue.reserveCapacity(pixelCount / 2)

func enqueueIfBackground(x: Int, y: Int) {
    guard x >= 0, x < width, y >= 0, y < height else { return }
    let index = (y * width) + x
    guard background[index] == 0, isBackgroundCandidate(sourceColor(x: x, y: y)) else { return }
    background[index] = 1
    queue.append(index)
}

for x in 0..<width {
    enqueueIfBackground(x: x, y: 0)
    enqueueIfBackground(x: x, y: height - 1)
}
for y in 0..<height {
    enqueueIfBackground(x: 0, y: y)
    enqueueIfBackground(x: width - 1, y: y)
}

var cursor = 0
while cursor < queue.count {
    let index = queue[cursor]
    cursor += 1
    let x = index % width
    let y = index / width
    enqueueIfBackground(x: x - 1, y: y)
    enqueueIfBackground(x: x + 1, y: y)
    enqueueIfBackground(x: x, y: y - 1)
    enqueueIfBackground(x: x, y: y + 1)
}

let idle = makeBitmap()
for y in 0..<height {
    for x in 0..<width {
        let index = (y * width) + x
        let color = sourceColor(x: x, y: y)
        writePixel(
            idle,
            x: x,
            y: y,
            red: byte(color.redComponent),
            green: byte(color.greenComponent),
            blue: byte(color.blueComponent),
            alpha: background[index] == 1 ? 0 : 255
        )
    }
}

// Retract the protruding portion of the PTT button by 22 pixels. The shifted
// button is clipped at the shell edge so it reads as moving behind the body,
// while every other device pixel remains identical to the idle cutout.
let pressed = makeBitmap()
if let pressedData = pressed.bitmapData, let idleData = idle.bitmapData {
    memcpy(pressedData, idleData, idle.bytesPerRow * height)
}

let pttYRange = 310...815
let shellEdgeX = 116
let pressDepth = 22
var pttPixels: [(x: Int, y: Int, red: UInt8, green: UInt8, blue: UInt8, alpha: UInt8)] = []

for y in pttYRange {
    for x in 0..<shellEdgeX {
        let (red, green, blue, alpha) = readPixel(idle, x: x, y: y)
        guard alpha > 0 else { continue }
        pttPixels.append((x, y, red, green, blue, alpha))
        writePixel(pressed, x: x, y: y, red: 0, green: 0, blue: 0, alpha: 0)
    }
}

for pixel in pttPixels {
    let targetX = pixel.x + pressDepth
    guard targetX < shellEdgeX else { continue }
    writePixel(
        pressed,
        x: targetX,
        y: pixel.y,
        red: pixel.red,
        green: pixel.green,
        blue: pixel.blue,
        alpha: pixel.alpha
    )
}

func writePNG(_ bitmap: NSBitmapImageRep, to url: URL) throws {
    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw CocoaError(.fileWriteUnknown)
    }
    try data.write(to: url, options: .atomic)
}

try writePNG(idle, to: idleURL)
try writePNG(pressed, to: pressedURL)

print("wrote \(idleURL.path)")
print("wrote \(pressedURL.path)")
