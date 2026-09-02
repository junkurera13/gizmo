import SwiftUI

/// Plays one sprite flipbook on the glass: numbered PNGs, pixel-crisp, no
/// smoothing. Looping cycles; one-shots hold the last frame. `wander` is a
/// leftover preview flag, not character spec.
struct SpriteAnimationView: View {
    let animation: SpriteAnimation

    @State private var startedAt = Date()

    var body: some View {
        GeometryReader { proxy in
            TimelineView(.animation) { timeline in
                let elapsed = timeline.date.timeIntervalSince(startedAt)
                let frame = frameIndex(at: elapsed)
                let drift = animation.wander ? wanderOffset(at: elapsed, in: proxy.size) : .zero
                let scale: CGFloat = animation.wander ? 0.62 : 1.0

                Image(nsImage: animation.frames[frame])
                    .resizable()
                    .interpolation(.none)
                    .aspectRatio(contentMode: .fit)
                    .frame(
                        width: proxy.size.width * scale,
                        height: proxy.size.height * scale
                    )
                    .position(
                        x: proxy.size.width / 2 + drift.width,
                        y: proxy.size.height / 2 + drift.height
                    )
            }
        }
        .onAppear { startedAt = Date() }
        .onChange(of: animation.name) { _, _ in
            startedAt = Date()
        }
    }

    private func frameIndex(at elapsed: TimeInterval) -> Int {
        let count = animation.frames.count
        guard count > 1, animation.fps > 0 else { return 0 }
        let raw = Int(elapsed * animation.fps)
        return animation.loop ? raw % count : min(raw, count - 1)
    }

    /// Smooth, organic drift built from two incommensurate sine waves —
    /// never repeats visibly, never leaves the glass.
    private func wanderOffset(at elapsed: TimeInterval, in size: CGSize) -> CGSize {
        let t = elapsed
        let ampX = size.width * 0.16
        let ampY = size.height * 0.14
        let x = sin(t * 0.9) * 0.6 + sin(t * 0.53 + 1.7) * 0.4
        let y = cos(t * 0.7 + 0.8) * 0.6 + sin(t * 0.41) * 0.4
        return CGSize(width: x * ampX, height: y * ampY)
    }
}
