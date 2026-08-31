import SwiftUI

/// What Gizmo's face is doing right now. Derived from Friend's state.
enum GizmoFaceMode: Equatable {
    case booting
    case idle
    case attentive
    case talking
    case thinking
}

/// Gizmo's face: two warm eyes on black, always alive.
/// Procedural stand-in for the 240x240 glass until real art lands in glass/.
struct GizmoFaceView: View {
    let mode: GizmoFaceMode

    @State private var bootStarted = Date()

    private static let eyeColor = Color(red: 1.0, green: 0.82, blue: 0.29)

    var body: some View {
        TimelineView(.animation) { timeline in
            Canvas { context, size in
                draw(in: &context, size: size, now: timeline.date)
            }
        }
        .background(Color.black)
        .onAppear {
            if mode == .booting { bootStarted = Date() }
        }
        .onChange(of: mode) { _, newMode in
            if newMode == .booting { bootStarted = Date() }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private func draw(in context: inout GraphicsContext, size: CGSize, now: Date) {
        let t = now.timeIntervalSinceReferenceDate
        let scale = min(size.width, size.height) / 240

        var eyeWidth = 40.0
        var eyeHeight = 58.0
        var offset = CGPoint(x: 0, y: -4)
        var openness = 1.0
        var alpha = 1.0

        switch mode {
        case .booting:
            let progress = min(1, max(0, now.timeIntervalSince(bootStarted) / 1.25))
            openness = easeOutBack(progress)
            alpha = min(1, progress * 3 + 0.15)
        case .idle:
            openness = blink(t)
            let gaze = wanderingGaze(t)
            offset.x += gaze.x
            offset.y += gaze.y
        case .attentive:
            eyeWidth *= 1.05
            eyeHeight *= 1.18
            offset.y -= 4
            openness = blink(t, period: 5.3)
        case .talking:
            openness = blink(t, period: 4.4) * (1 + 0.09 * sin(t * 11.4))
            offset.y += sin(t * 11.4) * 2
        case .thinking:
            eyeHeight *= 0.72
            offset.x += 9
            offset.y -= 9 - sin(t * 2.1) * 1.8
        }

        let height = max(eyeHeight * openness, 5)
        var paths: [Path] = []
        for side in [-1.0, 1.0] {
            let rect = CGRect(
                x: size.width / 2 + (side * 42 + offset.x) * scale - eyeWidth * scale / 2,
                y: size.height / 2 + offset.y * scale - height * scale / 2,
                width: eyeWidth * scale,
                height: height * scale
            )
            let radius = min(eyeWidth, height) * 0.42 * scale
            paths.append(Path(roundedRect: rect, cornerRadius: radius))
        }

        // Soft glow behind the eyes, then the eyes themselves.
        context.drawLayer { layer in
            layer.addFilter(.blur(radius: 7 * scale))
            for path in paths {
                layer.fill(path, with: .color(Self.eyeColor.opacity(0.55 * alpha)))
            }
        }
        for path in paths {
            context.fill(path, with: .color(Self.eyeColor.opacity(alpha)))
        }
    }

    /// 1 = open, 0 = closed. Occasional quick blinks with organic jitter.
    private func blink(_ t: Double, period: Double = 3.4) -> Double {
        let cycle = floor(t / period)
        if pseudoRandom(cycle) < 0.18 { return 1 }
        let phase = t - cycle * period
        let closeTime = 0.13
        if phase < closeTime { return 1 - smoothstep(phase / closeTime) }
        if phase < closeTime * 2 { return smoothstep((phase - closeTime) / closeTime) }
        return 1
    }

    /// Eyes drift to a new spot every couple of seconds, easing between spots.
    private func wanderingGaze(_ t: Double, period: Double = 2.7) -> CGPoint {
        let cycle = floor(t / period)
        let progress = min(1, (t - cycle * period) / 0.35)
        let from = gazeTarget(cycle - 1)
        let to = gazeTarget(cycle)
        let s = smoothstep(progress)
        return CGPoint(x: from.x + (to.x - from.x) * s, y: from.y + (to.y - from.y) * s)
    }

    private func gazeTarget(_ cycle: Double) -> CGPoint {
        CGPoint(
            x: (pseudoRandom(cycle * 7.31) - 0.5) * 24,
            y: (pseudoRandom(cycle * 3.77) - 0.5) * 14
        )
    }

    private func pseudoRandom(_ n: Double) -> Double {
        let x = sin(n * 12.9898) * 43758.5453
        return x - floor(x)
    }

    private func smoothstep(_ x: Double) -> Double {
        let clamped = min(1, max(0, x))
        return clamped * clamped * (3 - 2 * clamped)
    }

    private func easeOutBack(_ x: Double) -> Double {
        let c1 = 1.70158
        let c3 = c1 + 1
        return 1 + c3 * pow(x - 1, 3) + c1 * pow(x - 1, 2)
    }
}
