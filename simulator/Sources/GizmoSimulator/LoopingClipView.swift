import AppKit
import ImageIO
import SwiftUI

/// Plays the same finite JPEG frame sequence intended for the physical body.
/// No controls, audio, transitions, or other content over the device screen.
struct LoopingClipView: NSViewRepresentable {
    let clip: ScreenClip
    let onPlaybackEvent: (String) -> Void

    func makeNSView(context: Context) -> ClipSurface {
        ClipSurface(clip: clip, onPlaybackEvent: onPlaybackEvent)
    }

    func updateNSView(_ view: ClipSurface, context: Context) {}

    static func dismantleNSView(_ view: ClipSurface, coordinator: ()) {
        view.stop()
    }
}

@MainActor
final class ClipSurface: NSView {
    private let frameLayer = CALayer()
    private let frames: [Data]
    private let fps: Int
    private var timer: Timer?
    private var frameIndex = 0
    private var startedAt: TimeInterval = 0
    private var reportedLoop = false
    private var stopped = false
    private let onPlaybackEvent: (String) -> Void

    init(clip: ScreenClip, onPlaybackEvent: @escaping (String) -> Void) {
        frames = clip.frames
        fps = clip.fps
        self.onPlaybackEvent = onPlaybackEvent
        super.init(frame: .zero)
        wantsLayer = true
        layer = frameLayer
        frameLayer.contentsGravity = .resizeAspectFill
        frameLayer.magnificationFilter = .linear
        frameLayer.minificationFilter = .linear
        frameLayer.actions = ["bounds": NSNull(), "position": NSNull(), "contents": NSNull()]
        displayFrame(at: 0)
        startedAt = ProcessInfo.processInfo.systemUptime
        onPlaybackEvent("playing \(fps) fps MJPEG")
        let timer = Timer(timeInterval: 1 / Double(fps), repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.advance() }
        }
        self.timer = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    required init?(coder: NSCoder) { nil }

    func stop() {
        guard !stopped else { return }
        stopped = true
        timer?.invalidate()
        timer = nil
        frameLayer.contents = nil
        onPlaybackEvent("stopped")
    }

    private func advance() {
        guard !stopped, !frames.isEmpty else { return }
        frameIndex += 1
        if frameIndex == frames.count {
            frameIndex = 0
            if !reportedLoop {
                reportedLoop = true
                let elapsed = Int(((ProcessInfo.processInfo.systemUptime - startedAt) * 1_000).rounded())
                let target = Int((Double(frames.count) / Double(fps) * 1_000).rounded())
                onPlaybackEvent("looped in \(elapsed) ms; target \(target) ms")
            }
        }
        displayFrame(at: frameIndex)
    }

    private func displayFrame(at index: Int) {
        guard frames.indices.contains(index),
              let source = CGImageSourceCreateWithData(frames[index] as CFData, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { return }
        frameLayer.contents = image
    }
}
