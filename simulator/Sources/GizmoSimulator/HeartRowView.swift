import AppKit
import SwiftUI

/// Home HUD: clock and battery on one line at the top, centered, sitting
/// on the same baseline — the original status bar, not split to corners.
/// She's in the space below.
struct HomeClusterView: View {
    let level: Double
    let character: SpriteAnimation?

    var body: some View {
        GeometryReader { proxy in
            let w = proxy.size.width
            let h = proxy.size.height
            let timeSize = w * 0.05
            let timeFont = GlassFonts.clock(size: timeSize)
            let capHeight = timeFont.capHeight

            ZStack {
                if let character {
                    SpriteAnimationView(animation: character)
                        .frame(width: w * 0.48, height: h * 0.68)
                        .offset(y: h * 0.05)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
                }

                TimelineView(.everyMinute) { timeline in
                    HStack(alignment: .firstTextBaseline, spacing: capHeight * 0.7) {
                        Text(Self.clockText(timeline.date))
                            .font(Font(timeFont))
                            .foregroundStyle(Color.white)

                        BatteryView(level: level, side: capHeight)
                            .alignmentGuide(.firstTextBaseline) { $0[.bottom] - capHeight / 5 }
                    }
                    .padding(.top, h * 0.045)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                }
            }
        }
    }

    private static func clockText(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "H:mm"
        return formatter.string(from: date)
    }
}

/// Same battery the firmware draws in screens.cpp: a ~2:1 white outline one
/// cap height tall, 1px wall with diagonal corner steps, 2px padding, then
/// the nub. Charge fills the interior proportionally.
private struct BatteryView: View {
    let level: Double
    let side: CGFloat

    var body: some View {
        Canvas { context, _ in
            let wall = max(1, (side / 12).rounded())
            let pad = wall * 2
            let bodyW = side * 2
            let bodyH = side
            let nubW = wall * 2
            let nubH = side * 2 / 5

            func fill(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) {
                context.fill(Path(CGRect(x: x, y: y, width: w, height: h)), with: .color(.white))
            }
            fill(wall * 2, 0, bodyW - wall * 4, wall)
            fill(wall * 2, bodyH - wall, bodyW - wall * 4, wall)
            fill(0, wall * 2, wall, bodyH - wall * 4)
            fill(bodyW - wall, wall * 2, wall, bodyH - wall * 4)
            fill(wall, wall, wall, wall)
            fill(bodyW - wall * 2, wall, wall, wall)
            fill(wall, bodyH - wall * 2, wall, wall)
            fill(bodyW - wall * 2, bodyH - wall * 2, wall, wall)
            let charge = min(max(level, 0), 1)
            if charge > 0 {
                let inset = wall + pad
                fill(inset, inset, (bodyW - inset * 2) * charge, bodyH - inset * 2)
            }
            fill(bodyW + wall, (bodyH - nubH) / 2, nubW, nubH)
        }
        .frame(width: side * 2 + max(1, (side / 12).rounded()) * 3, height: side)
    }
}
