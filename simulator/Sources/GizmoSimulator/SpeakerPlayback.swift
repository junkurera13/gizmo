import AVFoundation

@MainActor
final class SpeakerPlayback {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let format = AVAudioFormat(standardFormatWithSampleRate: 24_000, channels: 1)!

    init() {
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: format)
    }

    func enqueue(_ data: Data) throws {
        guard !data.isEmpty, data.count % 2 == 0 else { return }
        let frames = data.count / 2
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames)),
              let output = buffer.floatChannelData?[0] else { return }
        buffer.frameLength = AVAudioFrameCount(frames)
        data.withUnsafeBytes { bytes in
            for index in 0..<frames {
                let sample = bytes.loadUnaligned(fromByteOffset: index * 2, as: Int16.self)
                output[index] = Float(Int16(littleEndian: sample)) / 32768.0
            }
        }
        if !engine.isRunning { try engine.start() }
        player.scheduleBuffer(buffer)
        if !player.isPlaying { player.play() }
    }

    func interrupt() {
        player.stop()
    }

    func shutdown() {
        player.stop()
        engine.stop()
    }
}
