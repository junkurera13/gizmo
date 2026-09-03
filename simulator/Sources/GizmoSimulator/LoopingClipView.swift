import AppKit
import AVFoundation
import SwiftUI

/// The simulator plays the MP4; the board receives the same clip as JPEG frames.
/// No controls, audio, transitions, or other content over the device screen.
struct LoopingClipView: NSViewRepresentable {
    let url: URL
    let onPlaybackEvent: (String) -> Void

    func makeNSView(context: Context) -> ClipSurface {
        ClipSurface(url: url, onPlaybackEvent: onPlaybackEvent)
    }

    func updateNSView(_ view: ClipSurface, context: Context) {}

    static func dismantleNSView(_ view: ClipSurface, coordinator: ()) {
        view.stop()
    }
}

@MainActor
final class ClipSurface: NSView {
    private let videoLayer = AVPlayerLayer()
    private let player = AVQueuePlayer()
    private var looper: AVPlayerLooper?
    private var readyObservation: NSKeyValueObservation?
    private var loopObservation: NSKeyValueObservation?
    private var started = false
    private var reportedLoop = false
    private var stopped = false
    private let onPlaybackEvent: (String) -> Void

    init(url: URL, onPlaybackEvent: @escaping (String) -> Void) {
        self.onPlaybackEvent = onPlaybackEvent
        super.init(frame: .zero)
        wantsLayer = true
        layer = videoLayer
        videoLayer.videoGravity = .resizeAspectFill
        videoLayer.opacity = 0
        videoLayer.actions = ["bounds": NSNull(), "position": NSNull(), "opacity": NSNull()]
        player.isMuted = true
        player.volume = 0
        videoLayer.player = player
        looper = AVPlayerLooper(player: player, templateItem: AVPlayerItem(url: url))
        readyObservation = videoLayer.observe(\.isReadyForDisplay, options: [.initial, .new]) { [weak self] _, _ in
            Task { @MainActor [weak self] in
                guard let self, !self.stopped, self.videoLayer.isReadyForDisplay else { return }
                self.videoLayer.opacity = 1
                if !self.started {
                    self.started = true
                    self.onPlaybackEvent("playing muted")
                }
            }
        }
        loopObservation = looper?.observe(\.loopCount, options: [.new]) { [weak self] _, _ in
            Task { @MainActor [weak self] in
                guard let self, !self.stopped, !self.reportedLoop,
                      (self.looper?.loopCount ?? 0) > 0 else { return }
                self.reportedLoop = true
                self.onPlaybackEvent("looped")
            }
        }
        player.play()
    }

    required init?(coder: NSCoder) { nil }

    func stop() {
        guard !stopped else { return }
        stopped = true
        readyObservation?.invalidate()
        loopObservation?.invalidate()
        player.pause()
        looper?.disableLooping()
        player.removeAllItems()
        videoLayer.player = nil
        looper = nil
        videoLayer.opacity = 0
        onPlaybackEvent("stopped")
    }
}
