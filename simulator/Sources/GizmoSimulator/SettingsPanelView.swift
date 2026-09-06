import SwiftUI

/// System overlay above Home. Two rows, rocker to hover, Select to grab a
/// row and rocker to change it. Down past Volume returns Home.
struct SettingsPanelView: View {
    @ObservedObject var model: SimulatorModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Namespace private var focusNS

    var body: some View {
        GeometryReader { proxy in
            let w = proxy.size.width
            let h = proxy.size.height

            ZStack {
                Color.black

                VStack(spacing: h * 0.09) {
                    settingRow(.brightness, width: w, height: h)
                    settingRow(.volume, width: w, height: h)
                }
                .padding(.horizontal, w * 0.09)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Settings")
    }

    private func settingRow(_ setting: SimulatorModel.GlassSetting, width w: CGFloat, height h: CGFloat) -> some View {
        let focused = model.settingsFocus == setting
        let adjusting = focused && model.settingsAdjusting
        let labelSize = w * 0.054
        let iconSize = w * 0.084
        let meterHeight = h * 0.048
        let caretWidth = w * 0.015
        let value = setting == .brightness ? model.brightnessStep : model.volumeStep

        return HStack(alignment: .center, spacing: w * 0.035) {
            ZStack {
                if focused {
                    Capsule()
                        .fill(Color.white)
                        .frame(width: caretWidth, height: h * 0.072)
                        .matchedGeometryEffect(id: "settings-focus", in: focusNS)
                }
            }
            .frame(width: caretWidth, height: h * 0.12)

            Image(systemName: iconName(for: setting, value: value))
                .font(.system(size: iconSize, weight: .medium))
                .foregroundStyle(Color.white.opacity(focused ? 1 : 0.34))
                .frame(width: iconSize * 1.15, height: iconSize * 1.15)

            VStack(alignment: .leading, spacing: h * 0.018) {
                Text(setting.title)
                    .font(Font(GlassFonts.ui(size: labelSize, weight: focused ? 600 : 500)))
                    .tracking(w * 0.004)
                    .foregroundStyle(Color.white.opacity(focused ? 1 : 0.34))

                LevelMeter(
                    steps: SimulatorModel.settingSteps,
                    value: value,
                    lit: focused,
                    height: meterHeight
                )
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if adjusting {
                VStack(spacing: h * 0.012) {
                    Image(systemName: "chevron.up")
                        .foregroundStyle(Color.white.opacity(value < SimulatorModel.settingSteps ? 0.95 : 0.28))
                    Image(systemName: "chevron.down")
                        .foregroundStyle(Color.white.opacity(value > 0 ? 0.95 : 0.28))
                }
                .font(.system(size: w * 0.034, weight: .bold))
                .transition(.opacity.combined(with: .scale(scale: 0.85)))
            }
        }
        .padding(.vertical, h * 0.02)
        .scaleEffect(adjusting ? 1.03 : 1, anchor: .leading)
        .animation(rowMotion, value: focused)
        .animation(rowMotion, value: adjusting)
        .animation(rowMotion, value: value)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(setting.title)
        .accessibilityValue("\(value) of \(SimulatorModel.settingSteps)")
        .accessibilityAddTraits(focused ? .isSelected : [])
        .accessibilityHint(adjusting ? "Up and down change the level. Select confirms." : "Select to adjust.")
    }

    private var rowMotion: Animation? {
        reduceMotion ? nil : .spring(response: 0.22, dampingFraction: 0.9)
    }

    private func iconName(for setting: SimulatorModel.GlassSetting, value: Int) -> String {
        switch setting {
        case .brightness:
            return value <= 2 ? "sun.min.fill" : "sun.max.fill"
        case .volume:
            if value == 0 { return "speaker.slash.fill" }
            if value <= 3 { return "speaker.wave.1.fill" }
            if value <= 7 { return "speaker.wave.2.fill" }
            return "speaker.wave.3.fill"
        }
    }
}

private struct LevelMeter: View {
    let steps: Int
    let value: Int
    let lit: Bool
    let height: CGFloat

    var body: some View {
        HStack(spacing: height * 0.32) {
            ForEach(0..<steps, id: \.self) { index in
                let filled = index < value
                Capsule()
                    .fill(Color.white.opacity(filled ? (lit ? 1 : 0.5) : (lit ? 0.18 : 0.08)))
                    .frame(maxWidth: .infinity)
                    .frame(height: filled ? height : height * 0.62)
            }
        }
        .frame(height: height)
    }
}

extension SimulatorModel.GlassSetting {
    var title: String {
        switch self {
        case .brightness: "BRIGHTNESS"
        case .volume: "VOLUME"
        }
    }
}
