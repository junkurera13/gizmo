import AVFoundation
import CoreImage
import Foundation

/// Live Mac-camera frames for the simulated world camera.
///
/// The `seeing` viewfinder path is leftover. Product: See keeps his face
/// on the glass. Don't treat this feed-on-glass as the character.
final class CameraFeed: NSObject, ObservableObject, @unchecked Sendable {
    static let shared = CameraFeed()

    @Published private(set) var frame: CGImage?
    @Published private(set) var unavailable = false

    private let session = AVCaptureSession()
    private let output = AVCaptureVideoDataOutput()
    private let queue = DispatchQueue(label: "studio.gizmo.simulator.camera")
    private let context = CIContext()
    private var configured = false
    private var lastFrameAt: CFTimeInterval = 0

    private override init() {
        super.init()
    }

    func start() {
        Task {
            guard await Self.requestAccess() else {
                await MainActor.run { self.unavailable = true }
                return
            }
            self.queue.async {
                self.configureIfNeeded()
                if !self.session.isRunning {
                    self.session.startRunning()
                }
            }
        }
    }

    func stop() {
        queue.async {
            if self.session.isRunning {
                self.session.stopRunning()
            }
            DispatchQueue.main.async {
                self.frame = nil
            }
        }
    }

    private static func requestAccess() async -> Bool {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            return true
        case .notDetermined:
            return await AVCaptureDevice.requestAccess(for: .video)
        default:
            return false
        }
    }

    private func configureIfNeeded() {
        guard !configured else { return }

        session.beginConfiguration()
        session.sessionPreset = .vga640x480

        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input)
        else {
            session.commitConfiguration()
            DispatchQueue.main.async { self.unavailable = true }
            return
        }
        session.addInput(input)

        output.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ]
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: queue)
        if session.canAddOutput(output) {
            session.addOutput(output)
        }

        session.commitConfiguration()
        configured = true
    }
}

extension CameraFeed: AVCaptureVideoDataOutputSampleBufferDelegate {
    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        let now = CACurrentMediaTime()
        guard now - lastFrameAt >= 1.0 / 12.0 else { return }
        lastFrameAt = now

        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }

        // The glass is square: crop the widescreen frame to its center.
        let image = CIImage(cvPixelBuffer: pixelBuffer)
        let side = min(image.extent.width, image.extent.height)
        let cropped = image.cropped(
            to: CGRect(
                x: image.extent.midX - side / 2,
                y: image.extent.midY - side / 2,
                width: side,
                height: side
            )
        )

        guard let cgImage = context.createCGImage(cropped, from: cropped.extent) else { return }

        DispatchQueue.main.async {
            self.frame = cgImage
        }
    }
}
