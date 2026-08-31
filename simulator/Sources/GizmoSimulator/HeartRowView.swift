import SwiftUI

/// Phone-style status strip across the top of the glass: time on the
/// left, Gizmo's energy as five small hearts on the right. Always there
/// while the face is up; hidden whenever the screen is busy being a
/// camera, a video, or a kept page.
struct StatusBarView: View {
    let art: HeartArt
    let level: Double

    var body: some View {
        GeometryReader { proxy in
            let heartSide = proxy.size.width * 0.055
            let halfSteps = max(0, min(10, Int((level * 10).rounded())))

            TimelineView(.everyMinute) { timeline in
                HStack(alignment: .center, spacing: 0) {
                    Text(Self.clockText(timeline.date))
                        .font(.system(size: proxy.size.width * 0.042, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Color.white)

                    Spacer(minLength: 0)

                    HStack(spacing: heartSide * 0.22) {
                        ForEach(0..<5, id: \.self) { index in
                            Image(nsImage: image(at: index, halfSteps: halfSteps))
                                .resizable()
                                .interpolation(.none)
                                .aspectRatio(contentMode: .fit)
                                .frame(width: heartSide, height: heartSide)
                        }
                    }
                }
                .padding(.horizontal, proxy.size.width * 0.05)
                .padding(.top, proxy.size.height * 0.045)
            }
        }
    }

    private static func clockText(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "H:mm"
        return formatter.string(from: date)
    }

    private func image(at index: Int, halfSteps: Int) -> NSImage {
        let filled = halfSteps - index * 2
        if filled >= 2 { return art.full }
        if filled == 1 { return art.half }
        return art.empty
    }
}
