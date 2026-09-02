import AppKit
import SwiftUI

/// Home HUD: hearts and time on one line at the top, centered, sitting
/// on the same baseline — the original status bar, not split to corners.
/// She's in the space below.
struct HomeClusterView: View {
    let art: HeartArt?
    let level: Double
    let character: SpriteAnimation?

    var body: some View {
        GeometryReader { proxy in
            let w = proxy.size.width
            let h = proxy.size.height
            let timeSize = w * 0.05
            let timeFont = GlassFonts.clock(size: timeSize)
            let capHeight = timeFont.capHeight
            let halfSteps = max(0, min(10, Int((level * 10).rounded())))

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

                        HeartRow(art: art, halfSteps: halfSteps, side: capHeight)
                            .alignmentGuide(.firstTextBaseline) { $0[.bottom] }
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

private struct HeartRow: View {
    let art: HeartArt?
    let halfSteps: Int
    let side: CGFloat

    var body: some View {
        HStack(spacing: side * 0.2) {
            ForEach(0..<5, id: \.self) { index in
                heart(at: index)
            }
        }
    }

    @ViewBuilder
    private func heart(at index: Int) -> some View {
        let filled = halfSteps - index * 2
        if let image = image(at: index) {
            Image(nsImage: image)
                .resizable()
                .interpolation(.none)
                .aspectRatio(contentMode: .fit)
                .frame(width: side, height: side)
                // Heart PNGs are 96×96 with 9px padding; scale so the
                // glyph itself is `side` (the time's cap height).
                .scaleEffect(96.0 / 78.0)
        } else {
            Image(systemName: filled > 0 ? "heart.fill" : "heart")
                .resizable()
                .aspectRatio(contentMode: .fit)
                .foregroundStyle(Color.red.opacity(filled == 1 ? 0.55 : 1))
                .frame(width: side, height: side)
        }
    }

    private func image(at index: Int) -> NSImage? {
        guard let art else { return nil }
        let filled = halfSteps - index * 2
        if filled >= 2 { return art.full }
        if filled == 1 { return art.half }
        return art.empty
    }
}
