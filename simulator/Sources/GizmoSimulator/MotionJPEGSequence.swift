import AppKit
import Foundation

enum MotionJPEGError: LocalizedError {
    case response
    case contentType
    case tooLarge(Int)
    case metadata
    case incomplete

    var errorDescription: String? {
        switch self {
        case .response: "MJPEG request failed"
        case .contentType: "Show frames were not MJPEG"
        case .tooLarge(let maximum): "Show frames exceed the \(maximum)-byte preview bound"
        case .metadata: "Show frame metadata does not match the preview profile"
        case .incomplete: "Show frame sequence is incomplete"
        }
    }
}

struct MotionJPEGSequence {
    let frames: [Data]
    let fps: Int
    let width: Int
    let height: Int
    let encodedBytes: Int

    init(data: Data, response: HTTPURLResponse, profile: HardwarePlaybackProfile) throws {
        guard response.statusCode == 200 else { throw MotionJPEGError.response }
        let contentType = response.value(forHTTPHeaderField: "Content-Type")?
            .split(separator: ";", maxSplits: 1).first?.lowercased()
        guard contentType == "video/x-motion-jpeg" else { throw MotionJPEGError.contentType }
        guard Int(response.value(forHTTPHeaderField: "X-Gizmo-Frame-Rate") ?? "") == profile.fps,
              Int(response.value(forHTTPHeaderField: "X-Gizmo-Frame-Width") ?? "") == profile.width,
              Int(response.value(forHTTPHeaderField: "X-Gizmo-Frame-Height") ?? "") == profile.height,
              let expectedCount = Int(response.value(forHTTPHeaderField: "X-Gizmo-Frame-Count") ?? ""),
              expectedCount > 0 else { throw MotionJPEGError.metadata }

        let startMarker = Data([0xff, 0xd8])
        let endMarker = Data([0xff, 0xd9])
        var cursor = data.startIndex
        var decoded: [Data] = []
        decoded.reserveCapacity(expectedCount)
        while cursor < data.endIndex,
              let start = data.range(of: startMarker, in: cursor..<data.endIndex)?.lowerBound {
            let afterStart = data.index(start, offsetBy: startMarker.count)
            guard let end = data.range(of: endMarker, in: afterStart..<data.endIndex)?.upperBound else {
                throw MotionJPEGError.incomplete
            }
            let frame = data.subdata(in: start..<end)
            guard let bitmap = NSBitmapImageRep(data: frame),
                  bitmap.pixelsWide == profile.width,
                  bitmap.pixelsHigh == profile.height else { throw MotionJPEGError.metadata }
            decoded.append(frame)
            cursor = end
        }
        guard decoded.count == expectedCount else { throw MotionJPEGError.incomplete }
        frames = decoded
        fps = profile.fps
        width = profile.width
        height = profile.height
        encodedBytes = data.count
    }
}

func downloadBoundedFrames(
    session: URLSession,
    request: URLRequest,
    maximumBytes: Int
) async throws -> (Data, HTTPURLResponse) {
    let (bytes, response) = try await session.bytes(for: request)
    guard let http = response as? HTTPURLResponse else { throw MotionJPEGError.response }
    if response.expectedContentLength > maximumBytes {
        throw MotionJPEGError.tooLarge(maximumBytes)
    }
    var data = Data()
    if response.expectedContentLength > 0 {
        data.reserveCapacity(min(Int(response.expectedContentLength), maximumBytes))
    }
    for try await byte in bytes {
        try Task.checkCancellation()
        guard data.count < maximumBytes else { throw MotionJPEGError.tooLarge(maximumBytes) }
        data.append(byte)
    }
    return (data, http)
}
