import AVFoundation
import CoreImage
import Foundation

/// One world-camera snapshot per hold. No viewfinder or continuous upload.
/// All AVFoundation state belongs to `queue`; callbacks never touch the UI.
final class CameraFeed: NSObject, @unchecked Sendable {
    struct Snapshot: Sendable {
        let jpeg: Data
        let width: Int
        let height: Int
    }

    enum CaptureError: Error, Sendable {
        case permissionDenied, unavailable, timedOut, encodingFailed

        var message: String {
            switch self {
            case .permissionDenied:
                "Camera permission needed — voice still works. Allow Camera in System Settings."
            case .unavailable: "Camera unavailable — voice still works."
            case .timedOut: "Camera did not deliver a frame — voice still works."
            case .encodingFailed: "Could not prepare the camera snapshot — voice still works."
            }
        }
    }

    private let session = AVCaptureSession()
    private let output = AVCaptureVideoDataOutput()
    private let queue = DispatchQueue(label: "studio.gizmo.simulator.camera")
    private let context = CIContext()
    private var configured = false
    private var readyAfter = ContinuousClock.now
    private var requestID: UUID?
    private var completion: (@Sendable (Result<Snapshot, CaptureError>) -> Void)?

    func capture(id: UUID, completion: @escaping @Sendable (Result<Snapshot, CaptureError>) -> Void) {
        queue.async {
            self.cancelOnQueue()
            self.requestID = id
            self.completion = completion
            switch AVCaptureDevice.authorizationStatus(for: .video) {
            case .authorized:
                self.startOnQueue(id: id)
            case .notDetermined:
                AVCaptureDevice.requestAccess(for: .video) { granted in
                    self.queue.async {
                        guard self.requestID == id else { return }
                        if granted { self.startOnQueue(id: id) }
                        else { self.finish(.failure(.permissionDenied)) }
                    }
                }
            default:
                self.finish(.failure(.permissionDenied))
            }
        }
    }

    func cancel() {
        queue.async { self.cancelOnQueue() }
    }

    private func cancelOnQueue() {
        requestID = nil
        completion = nil
        if session.isRunning { session.stopRunning() }
    }

    private func startOnQueue(id: UUID) {
        guard configureIfNeeded() else {
            finish(.failure(.unavailable))
            return
        }
        // A missing/busy camera must never keep capturing indefinitely.
        queue.asyncAfter(deadline: .now() + 5) {
            guard self.requestID == id else { return }
            self.finish(.failure(.timedOut))
        }
        session.startRunning()
        // Give camera exposure a brief warm-up. The eventual body sensor needs
        // its own measured start-up interval; microphone input never waits.
        readyAfter = .now + .milliseconds(400)
        if !session.isRunning { finish(.failure(.unavailable)) }
    }

    private func finish(_ result: Result<Snapshot, CaptureError>) {
        let callback = completion
        cancelOnQueue()
        callback?(result)
    }

    private func configureIfNeeded() -> Bool {
        if configured { return true }
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device) else { return false }

        session.beginConfiguration()
        defer { session.commitConfiguration() }
        guard session.canSetSessionPreset(.vga640x480),
              session.canAddInput(input) else { return false }
        session.sessionPreset = .vga640x480
        session.addInput(input)
        guard session.canAddOutput(output) else {
            session.removeInput(input)
            return false
        }
        output.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ]
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: queue)
        session.addOutput(output)
        configured = true
        return true
    }
}

extension CameraFeed: AVCaptureVideoDataOutputSampleBufferDelegate {
    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        guard requestID != nil, ContinuousClock.now >= readyAfter,
              let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }

        // Camera context is independent of the undecided display aspect.
        // Preserve the full frame (and book text), bounded to VGA / 128 KiB.
        let source = CIImage(cvPixelBuffer: pixelBuffer)
        let scale = min(1, 640 / source.extent.width, 480 / source.extent.height)
        let image = source.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
        // A dark scene is valid camera input, not a capture failure.
        for quality in [0.75, 0.55] {
            if let jpeg = context.jpegRepresentation(
                of: image, colorSpace: colorSpace,
                options: [CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): quality]
            ), jpeg.count <= 128 * 1024 {
                finish(.success(Snapshot(jpeg: jpeg, width: Int(image.extent.width), height: Int(image.extent.height))))
                return
            }
        }
        finish(.failure(.encodingFailed))
    }
}
