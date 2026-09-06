import SwiftUI

/// The viewfinder and character strip keep the same geometry in every voice state.
struct CameraWorldView: View {
    @ObservedObject var model: SimulatorModel
    @ObservedObject private var sprites = SpriteStore.shared

    var body: some View {
        GeometryReader { proxy in
            let w = proxy.size.width
            let h = proxy.size.height
            let strip = h * 0.22
            VStack(spacing: 0) {
                ZStack {
                    Color(white: 0.055)
                    if let image = model.cameraImage {
                        Image(nsImage: image)
                            .resizable()
                            .scaledToFill()
                            .frame(width: w, height: h - strip)
                            .clipped()
                    } else if let error = model.cameraError {
                        VStack(spacing: 8) {
                            Image(systemName: "camera.slash")
                            Text(error)
                                .font(.system(size: w * 0.038))
                                .multilineTextAlignment(.center)
                        }
                        .foregroundStyle(.white.opacity(0.65))
                        .padding(w * 0.08)
                    } else {
                        ProgressView().controlSize(.small)
                    }
                }
                .frame(width: w, height: h - strip)
                .clipShape(UnevenRoundedRectangle(bottomLeadingRadius: w * 0.075, bottomTrailingRadius: w * 0.075))

                HStack(spacing: w * 0.025) {
                    if let character = sprites.animation(for: model.glassState == "talking" ? "talk" : "idle") {
                        SpriteAnimationView(animation: character)
                            .frame(width: w * 0.19, height: strip * 0.87)
                    }
                    if model.glassState == "talking", !model.isPushToTalking, !model.spokenLine.isEmpty {
                        Text(model.spokenLine.split(whereSeparator: \.isWhitespace).suffix(10).joined(separator: " "))
                            .font(.system(size: w * 0.047, weight: .medium))
                            .foregroundStyle(.white)
                            .lineLimit(2)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    } else {
                        Spacer(minLength: 0)
                    }
                }
                .padding(.horizontal, w * 0.045)
                .frame(width: w, height: strip)
            }
            .background(.black)
        }
    }
}
