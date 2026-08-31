import AVFoundation
import Foundation

final class MicrophoneCapture: @unchecked Sendable {
    private let engine = AVAudioEngine()
    private var converter: AVAudioConverter?
    private var running = false

    static func requestAccess() async -> Bool {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            return true
        case .notDetermined:
            return await AVCaptureDevice.requestAccess(for: .audio)
        default:
            return false
        }
    }

    func start(onPCM: @escaping @Sendable (Data) -> Void) throws {
        guard !running else { return }

        let input = engine.inputNode
        let sourceFormat = input.outputFormat(forBus: 0)
        guard sourceFormat.sampleRate > 0,
              let targetFormat = AVAudioFormat(
                commonFormat: .pcmFormatInt16,
                sampleRate: 24_000,
                channels: 1,
                interleaved: true
              ),
              let converter = AVAudioConverter(from: sourceFormat, to: targetFormat)
        else {
            throw MicrophoneError.unsupportedFormat
        }

        self.converter = converter
        input.installTap(onBus: 0, bufferSize: 2_048, format: sourceFormat) { buffer, _ in
            let ratio = targetFormat.sampleRate / sourceFormat.sampleRate
            let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * ratio)) + 1
            guard let converted = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: capacity) else {
                return
            }

            do {
                try converter.convert(to: converted, from: buffer)
            } catch {
                return
            }

            guard converted.frameLength > 0,
                  let bytes = converted.audioBufferList.pointee.mBuffers.mData
            else { return }

            let byteCount = Int(converted.audioBufferList.pointee.mBuffers.mDataByteSize)
            onPCM(Data(bytes: bytes, count: byteCount))
        }

        engine.prepare()
        try engine.start()
        running = true
    }

    func stop() {
        guard running else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        converter = nil
        running = false
    }
}

private enum MicrophoneError: LocalizedError {
    case unsupportedFormat

    var errorDescription: String? {
        "The Mac microphone format could not be converted to Gizmo audio."
    }
}
