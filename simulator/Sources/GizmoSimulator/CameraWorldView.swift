import SwiftUI

/// The viewfinder fills the glass in every voice state.
struct CameraWorldView: View {
    @ObservedObject var model: SimulatorModel

    var body: some View {
        GeometryReader { proxy in
            let w = proxy.size.width
            ZStack {
                Color(white: 0.055)
                if let image = model.cameraImage {
                    Image(nsImage: image)
                        .resizable()
                        .scaledToFill()
                        .frame(width: w, height: proxy.size.height)
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
        }
        .background(.black)
    }
}
