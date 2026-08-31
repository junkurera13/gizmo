import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

guard CommandLine.arguments.count == 3 else {
    FileHandle.standardError.write(Data("usage: remove_studio_background input.png output.png\n".utf8))
    exit(2)
}

let inputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])

guard
    let source = CGImageSourceCreateWithURL(inputURL as CFURL, nil),
    let sourceImage = CGImageSourceCreateImageAtIndex(source, 0, nil)
else {
    FileHandle.standardError.write(Data("could not read input image\n".utf8))
    exit(3)
}

let width = sourceImage.width
let height = sourceImage.height
let bytesPerRow = width * 4
var pixels = [UInt8](repeating: 0, count: height * bytesPerRow)

guard let context = CGContext(
    data: &pixels,
    width: width,
    height: height,
    bitsPerComponent: 8,
    bytesPerRow: bytesPerRow,
    space: CGColorSpaceCreateDeviceRGB(),
    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue
) else {
    FileHandle.standardError.write(Data("could not create image context\n".utf8))
    exit(4)
}

context.draw(sourceImage, in: CGRect(x: 0, y: 0, width: width, height: height))

func isStudioBackground(_ pixelIndex: Int) -> Bool {
    let offset = pixelIndex * 4
    let red = Int(pixels[offset])
    let green = Int(pixels[offset + 1])
    let blue = Int(pixels[offset + 2])
    let brightest = max(red, green, blue)
    let darkest = min(red, green, blue)
    let chroma = brightest - darkest

    // The source is an achromatic studio sweep. Flood-filling from the canvas
    // edge keeps enclosed black glass and device highlights intact while also
    // removing the connected floor shadow.
    return brightest > 28 && chroma < 34
}

var background = [Bool](repeating: false, count: width * height)
var queue = [Int]()
queue.reserveCapacity(width * height / 2)

func enqueue(_ x: Int, _ y: Int) {
    guard x >= 0, x < width, y >= 0, y < height else { return }
    let index = y * width + x
    guard !background[index], isStudioBackground(index) else { return }
    background[index] = true
    queue.append(index)
}

for x in 0..<width {
    enqueue(x, 0)
    enqueue(x, height - 1)
}
for y in 0..<height {
    enqueue(0, y)
    enqueue(width - 1, y)
}

var cursor = 0
while cursor < queue.count {
    let index = queue[cursor]
    cursor += 1
    let x = index % width
    let y = index / width
    enqueue(x - 1, y)
    enqueue(x + 1, y)
    enqueue(x, y - 1)
    enqueue(x, y + 1)
}

var foregroundPixels = 0
for index in 0..<(width * height) {
    let offset = index * 4
    if background[index] {
        pixels[offset] = 0
        pixels[offset + 1] = 0
        pixels[offset + 2] = 0
        pixels[offset + 3] = 0
    } else {
        pixels[offset + 3] = 255
        foregroundPixels += 1
    }
}

guard
    let outputImage = context.makeImage(),
    let destination = CGImageDestinationCreateWithURL(
        outputURL as CFURL,
        UTType.png.identifier as CFString,
        1,
        nil
    )
else {
    FileHandle.standardError.write(Data("could not create output image\n".utf8))
    exit(5)
}

CGImageDestinationAddImage(destination, outputImage, nil)
guard CGImageDestinationFinalize(destination) else {
    FileHandle.standardError.write(Data("could not write output image\n".utf8))
    exit(6)
}

print("wrote \(outputURL.path) (\(width)x\(height), \(foregroundPixels) foreground pixels)")
