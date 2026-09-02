import AppKit
import SwiftUI

struct ContentView: View {
    @ObservedObject private var model = SimulatorModel.shared
    @ObservedObject private var skinStore = DeviceSkinStore.shared

    var body: some View {
        HStack(spacing: 0) {
            DeviceStageView(model: model, skinStore: skinStore)
                .frame(minWidth: 540)

            Divider()

            ConversationPanel(model: model)
                .frame(width: 370)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .task {
            skinStore.loadDefault()
            SpriteStore.shared.load()
            model.start()
        }
    }
}

private struct DeviceStageView: View {
    @ObservedObject var model: SimulatorModel
    @ObservedObject var skinStore: DeviceSkinStore

    var body: some View {
        GeometryReader { proxy in
            ZStack {
                stageColor
                    .ignoresSafeArea()

                if let skin = skinStore.skin, let image = skinStore.image {
                    let aspectRatio = CGFloat(skin.canvasWidth) / CGFloat(skin.canvasHeight)
                    let availableWidth = proxy.size.width * 0.98
                    let availableHeight = proxy.size.height * 0.94
                    let width = min(availableWidth, availableHeight * aspectRatio)
                    let height = width / aspectRatio

                    DeviceView(
                        model: model,
                        skin: skin,
                        deviceImage: image,
                        pressedDeviceImage: skinStore.pressedImage
                    )
                        .frame(width: width, height: height)
                } else {
                    VStack(spacing: 12) {
                        ProgressView()
                        Text(skinStore.errorMessage ?? "Loading Gizmo…")
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private var stageColor: Color {
        guard let value = skinStore.skin?.stageColor else {
            return Color(nsColor: .underPageBackgroundColor)
        }
        return Color(hex: value)
    }
}

private struct DeviceView: View {
    @ObservedObject var model: SimulatorModel
    @ObservedObject private var spriteStore = SpriteStore.shared
    @ObservedObject private var cameraFeed = CameraFeed.shared
    let skin: DeviceSkin
    let deviceImage: NSImage
    let pressedDeviceImage: NSImage?

    @State private var pressedControl: String?
    @State private var pressStartedAt: Date?

    var body: some View {
        GeometryReader { proxy in
            let canvasSize = proxy.size

            ZStack(alignment: .topLeading) {
                deviceArtwork(deviceImage, size: canvasSize)
                    .opacity(showingPressedSkin ? 0 : 1)
                    .animation(nil, value: showingPressedSkin)

                if let pressedDeviceImage {
                    deviceArtwork(pressedDeviceImage, size: canvasSize)
                        .opacity(showingPressedSkin ? 1 : 0)
                        .animation(nil, value: showingPressedSkin)
                }

                screen(size: canvasSize)
                navigationControls(size: canvasSize)

                ForEach(skin.controls.filter { $0.shortAction == "ptt" }) { control in
                    sideButtonHitArea(control, rect: frame(for: control.rect, size: canvasSize))
                }
            }
        }
        .aspectRatio(CGFloat(skin.canvasWidth) / CGFloat(skin.canvasHeight), contentMode: .fit)
    }

    @ViewBuilder
    private func screen(size: CGSize) -> some View {
        let rect = frame(for: skin.screen.rect, size: size)
        let radius = skin.screen.cornerRadius * min(size.width, size.height)

        ZStack {
            Color.black

            if let screenImage = model.screenImage, model.viewingStill {
                Image(nsImage: screenImage)
                    .resizable()
                    .interpolation(.none)
                    .aspectRatio(contentMode: skin.screen.contentMode == "fill" ? .fill : .fit)
                    .padding(10)
            } else if model.deviceState == "seeing" {
                viewfinder
            } else if let spriteName, let animation = spriteStore.animation(for: spriteName) {
                SpriteAnimationView(animation: animation)
            }

            statusBar
                .frame(width: rect.width, height: rect.height, alignment: .top)
                .animation(.easeOut(duration: 0.28), value: statusBarVisible)
        }
        .frame(width: rect.width, height: rect.height)
        .clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
        .position(x: rect.midX, y: rect.midY)
        .opacity(model.screenOn ? 1 : 0)
        .animation(.easeOut(duration: 0.16), value: model.screenOn)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
        .onChange(of: model.deviceState) { _, state in
            if state == "seeing" {
                CameraFeed.shared.start()
            } else {
                CameraFeed.shared.stop()
            }
        }
    }

    /// Camera mode: the live feed fills the glass, and the wizard's
    /// floating head drifts on top of it, watching along.
    @ViewBuilder
    private var viewfinder: some View {
        ZStack {
            if let frame = cameraFeed.frame {
                Image(decorative: frame, scale: 1)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
            } else if cameraFeed.unavailable {
                VStack(spacing: 6) {
                    Image(systemName: "video.slash")
                        .font(.system(size: 22, weight: .light))
                    Text("No camera")
                        .font(.system(size: 11))
                }
                .foregroundStyle(Color.white.opacity(0.4))
            } else {
                Color.black
            }
        }
    }

    /// The status strip shows whenever the glass belongs to the face.
    /// Camera, videos, and kept pages own the whole screen.
    private var statusBarVisible: Bool {
        guard model.screenOn, !model.viewingStill else { return false }
        return !["asleep", "seeing"].contains(model.deviceState)
    }

    @ViewBuilder
    private var statusBar: some View {
        if statusBarVisible {
            StatusBarView(art: spriteStore.hearts, level: model.batteryLevel)
                .transition(.opacity)
        }
    }

    /// Which of Jun's animations to play for the current device state.
    /// Missing animations fall back inside SpriteStore, then to the
    /// procedural face below, so art can land one folder at a time.
    private var spriteName: String? {
        switch model.deviceState {
        case "booting":
            return "boot"
        case "listening":
            return model.isPushToTalking ? "listen" : "idle"
        case "talking":
            return "talk"
        case "showing":
            return "show"
        case "thinking", "making", "reaching":
            return "think"
        default:
            return nil
        }
    }

    @ViewBuilder
    private func navigationControls(size: CGSize) -> some View {
        if
            let up = skin.controls.first(where: { $0.shortAction == "navigateUp" }),
            let down = skin.controls.first(where: { $0.shortAction == "navigateDown" }),
            let select = skin.controls.first(where: { $0.shortAction == "select" })
        {
            let upRect = frame(for: up.rect, size: size)
            let downRect = frame(for: down.rect, size: size)
            let selectRect = frame(for: select.rect, size: size)
            let pillRect = upRect.union(downRect)

            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: pillRect.width / 2, style: .continuous)
                    .fill(Color.white.opacity(0.09))
                    .overlay {
                        RoundedRectangle(cornerRadius: pillRect.width / 2, style: .continuous)
                            .stroke(Color.white.opacity(0.16), lineWidth: 1)
                    }
                    .frame(width: pillRect.width, height: pillRect.height)
                    .position(x: pillRect.midX, y: pillRect.midY)

                Rectangle()
                    .fill(Color.white.opacity(0.13))
                    .frame(width: pillRect.width * 0.62, height: 1)
                    .position(x: pillRect.midX, y: upRect.maxY)

                navigationButton(up, symbol: "chevron.up", rect: upRect)
                navigationButton(down, symbol: "chevron.down", rect: downRect)

                Button {
                    perform(control: select)
                } label: {
                    ZStack {
                        Circle()
                            .fill(Color.white.opacity(0.09))
                        Circle()
                            .stroke(Color.white.opacity(0.16), lineWidth: 1)
                        Image(systemName: "checkmark")
                            .font(.system(size: max(10, selectRect.width * 0.27), weight: .bold))
                            .foregroundStyle(Color.white.opacity(0.9))
                    }
                    .frame(width: selectRect.width, height: selectRect.height)
                }
                .buttonStyle(DeviceHardwareButtonStyle())
                .position(x: selectRect.midX, y: selectRect.midY)
                .help(helpText(for: select))
                .accessibilityLabel(select.label)
                .accessibilityHint(helpText(for: select))
            }
            .frame(width: size.width, height: size.height, alignment: .topLeading)
        }
    }

    private func navigationButton(
        _ control: DeviceControl,
        symbol: String,
        rect: CGRect
    ) -> some View {
        Button {
            perform(control: control)
        } label: {
            Image(systemName: symbol)
                .font(.system(size: max(10, rect.width * 0.29), weight: .semibold))
                .foregroundStyle(Color.white.opacity(0.9))
                .frame(width: rect.width, height: rect.height)
                .contentShape(Rectangle())
        }
        .buttonStyle(DeviceHardwareButtonStyle())
        .position(x: rect.midX, y: rect.midY)
        .help(helpText(for: control))
        .accessibilityLabel(control.label)
        .accessibilityHint(helpText(for: control))
    }

    private func perform(control: DeviceControl) {
        switch control.shortAction {
        case "navigateUp":
            model.navigate("up")
        case "navigateDown":
            model.navigate("down")
        case "select":
            model.select()
        default:
            break
        }
    }

    @ViewBuilder
    private func sideButtonHitArea(_ control: DeviceControl, rect: CGRect) -> some View {
        let isPressed = pressedControl == control.id
        let usesPressedSkin = control.shortAction == "ptt" && pressedDeviceImage != nil

        RoundedRectangle(cornerRadius: 10, style: .continuous)
            .fill(isPressed && !usesPressedSkin ? Color.white.opacity(0.16) : Color.clear)
            .frame(width: rect.width, height: rect.height)
            .contentShape(Rectangle())
            .position(x: rect.midX, y: rect.midY)
            .scaleEffect(isPressed && !usesPressedSkin ? 0.97 : 1)
            .animation(.spring(response: 0.18, dampingFraction: 1), value: isPressed)
            .gesture(sideButtonGesture(control))
            .help(helpText(for: control))
            .accessibilityLabel(control.label)
            .accessibilityHint(helpText(for: control))
            .accessibilityAddTraits(.isButton)
            .accessibilityAction {
                if model.isPushToTalking {
                    model.endPushToTalk()
                } else {
                    model.beginPushToTalk()
                }
            }
    }

    private func sideButtonGesture(_ control: DeviceControl) -> some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { _ in
                if pressStartedAt == nil {
                    pressStartedAt = Date()
                    pressedControl = control.id
                    if control.shortAction == "ptt" {
                        model.beginPushToTalk()
                    }
                }
            }
            .onEnded { _ in
                if control.shortAction == "ptt" {
                    model.endPushToTalk()
                }
                pressedControl = nil
                pressStartedAt = nil
            }
    }

    private func helpText(for control: DeviceControl) -> String {
        switch control.shortAction {
        case "navigateUp":
            return "Navigate up."
        case "navigateDown":
            return "Navigate down."
        case "select":
            return "Select."
        case "ptt":
            return "Hold to talk. Wakes him if he's asleep."
        default:
            return control.label
        }
    }

    private func frame(for rect: NormalizedRect, size: CGSize) -> CGRect {
        CGRect(
            x: rect.x * size.width,
            y: rect.y * size.height,
            width: rect.width * size.width,
            height: rect.height * size.height
        )
    }

    private func deviceArtwork(_ image: NSImage, size: CGSize) -> some View {
        Image(nsImage: image)
            .resizable()
            .interpolation(.high)
            .frame(width: size.width, height: size.height)
    }

    private var showingPressedSkin: Bool {
        pressedDeviceImage != nil && (model.isPushToTalking || pressedControl == "side")
    }
}

private struct DeviceHardwareButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(configuration.isPressed ? 0.62 : 1)
            .scaleEffect(configuration.isPressed ? 0.94 : 1)
            .animation(.spring(response: 0.18, dampingFraction: 0.9), value: configuration.isPressed)
    }
}

private struct ConversationPanel: View {
    @ObservedObject var model: SimulatorModel
    @State private var draft = ""

    var body: some View {
        VStack(spacing: 0) {
            header
            transcript
            if let error = model.voiceError {
                Text(error)
                    .font(.system(size: 12))
                    .foregroundStyle(.red)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
            } else if let status = model.microphoneStatus {
                Text(status)
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                    .accessibilityValue("Microphone input level \(Int(model.microphoneLevel * 100)) percent")
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
            }
            composer
        }
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private var header: some View {
        HStack {
            Spacer()

            Button {
                model.togglePower()
            } label: {
                Image(systemName: "power")
                    .font(.system(size: 14, weight: .semibold))
                    .frame(width: 30, height: 30)
                    .foregroundStyle(model.poweredOff ? Color.red : Color.primary)
            }
            .buttonStyle(.plain)
            .background(Circle().fill(Color.primary.opacity(0.06)))
            .help(model.poweredOff ? "Power on (cold boot)" : "Shut down")
            .accessibilityLabel(model.poweredOff ? "Power on" : "Shut down")
            .disabled(model.connectionStatus != .connected)
        }
        .padding(.horizontal, 16)
        .frame(height: 48)
    }

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 8) {
                    if model.conversation.isEmpty {
                        emptyConversation
                    } else {
                        ForEach(model.conversation) { message in
                            MessageBubble(message: message)
                                .id(message.id)
                                .transition(
                                    .move(edge: message.role == .user ? .trailing : .leading)
                                        .combined(with: .opacity)
                                )
                        }
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 18)
                .animation(.spring(response: 0.3, dampingFraction: 0.92), value: model.conversation.count)
            }
            .onChange(of: model.conversation.count) { _, _ in
                guard let last = model.conversation.last else { return }
                withAnimation(.easeOut(duration: 0.2)) {
                    proxy.scrollTo(last.id, anchor: .bottom)
                }
            }
        }
    }

    private var emptyConversation: some View {
        VStack(spacing: 9) {
            Image(systemName: "message")
                .font(.system(size: 21, weight: .light))
                .foregroundStyle(.tertiary)
            Text("Your conversation with Gizmo\nwill show up here.")
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .lineSpacing(2)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 82)
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 9) {
            TextField("Message", text: $draft, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...5)
                .font(.system(size: 14))
                .padding(.horizontal, 13)
                .padding(.vertical, 9)
                .background(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(Color.primary.opacity(0.15), lineWidth: 1)
                )
                .onSubmit(send)

            Button(action: send) {
                Image(systemName: "arrow.up")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 32, height: 32)
                    .background(Circle().fill(draftIsEmpty ? Color.secondary.opacity(0.35) : Color.blue))
            }
            .buttonStyle(.plain)
            .disabled(draftIsEmpty || model.connectionStatus != .connected)
            .accessibilityLabel("Send message")
        }
        .padding(14)
        .background(.bar)
    }

    private var draftIsEmpty: Bool {
        draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func send() {
        guard !draftIsEmpty else { return }
        model.say(draft)
        draft = ""
    }
}

private struct MessageBubble: View {
    let message: ConversationMessage

    var body: some View {
        HStack {
            if message.role == .user {
                Spacer(minLength: 54)
            }

            Text(message.text)
                .font(.system(size: 14))
                .foregroundStyle(message.role == .user ? Color.white : Color.primary)
                .lineSpacing(2)
                .textSelection(.enabled)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(message.role == .user ? Color.blue : Color.primary.opacity(0.08))
                )

            if message.role == .gizmo {
                Spacer(minLength: 54)
            }
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(message.role == .user ? "You: \(message.text)" : "Gizmo: \(message.text)")
    }
}

private extension Color {
    init(hex: String) {
        let cleaned = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var value: UInt64 = 0
        Scanner(string: cleaned).scanHexInt64(&value)

        let red = Double((value >> 16) & 0xFF) / 255
        let green = Double((value >> 8) & 0xFF) / 255
        let blue = Double(value & 0xFF) / 255
        self.init(red: red, green: green, blue: blue)
    }
}
