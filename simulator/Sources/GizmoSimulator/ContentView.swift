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
            let side = min(proxy.size.width, proxy.size.height) * 0.94

            ZStack {
                stageColor
                    .ignoresSafeArea()

                if let skin = skinStore.skin, let image = skinStore.image {
                    DeviceView(
                        model: model,
                        skin: skin,
                        deviceImage: image,
                        pressedDeviceImage: skinStore.pressedImage
                    )
                        .frame(width: side, height: side)
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
    @State private var trackballOffset: CGSize = .zero
    @State private var trackballRemainder: CGSize = .zero
    @State private var hoveringTrackball = false

    var body: some View {
        GeometryReader { proxy in
            let size = proxy.size.width

            ZStack(alignment: .topLeading) {
                deviceArtwork(deviceImage, size: size)
                    .opacity(showingPressedSkin ? 0 : 1)
                    .animation(nil, value: showingPressedSkin)

                if let pressedDeviceImage {
                    deviceArtwork(pressedDeviceImage, size: size)
                        .opacity(showingPressedSkin ? 1 : 0)
                        .animation(nil, value: showingPressedSkin)
                }

                screen(size: size)
                movingTrackball(size: size)

                ForEach(skin.controls) { control in
                    controlHitArea(control, size: size)
                }
            }
        }
        .aspectRatio(1, contentMode: .fit)
    }

    @ViewBuilder
    private func screen(size: CGFloat) -> some View {
        let rect = frame(for: skin.screen.rect, size: size)
        let radius = skin.screen.cornerRadius * size

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
            } else if let faceMode {
                GizmoFaceView(mode: faceMode)
            }

            statusBar
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
                GizmoFaceView(mode: .thinking)
            }

            if let head = spriteStore.animations["see"] {
                SpriteAnimationView(animation: head)
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
        if statusBarVisible, let hearts = spriteStore.hearts {
            StatusBarView(art: hearts, level: model.batteryLevel)
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

    private var faceMode: GizmoFaceMode? {
        switch model.deviceState {
        case "booting":
            return .booting
        case "listening":
            return model.isPushToTalking ? .attentive : .idle
        case "talking":
            return .talking
        case "thinking", "seeing", "showing", "making", "reaching":
            return .thinking
        default:
            return nil
        }
    }

    @ViewBuilder
    private func movingTrackball(size: CGFloat) -> some View {
        if let control = skin.controls.first(where: { $0.id == "trackball" }) {
            let outer = frame(for: control.rect, size: size)
            let inner = outer.insetBy(dx: outer.width * 0.145, dy: outer.height * 0.145)

            ZStack(alignment: .topLeading) {
                deviceArtwork(deviceImage, size: size)
                    .offset(
                        x: -inner.minX + trackballOffset.width,
                        y: -inner.minY + trackballOffset.height
                    )
            }
            .frame(width: inner.width, height: inner.height)
            .clipShape(Circle())
            .position(x: inner.midX, y: inner.midY)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
        }
    }

    @ViewBuilder
    private func controlHitArea(_ control: DeviceControl, size: CGFloat) -> some View {
        let rect = frame(for: control.rect, size: size)

        if control.id == "trackball" {
            trackballHitArea(control, rect: rect)
        } else {
            sideButtonHitArea(control, rect: rect)
        }
    }

    @ViewBuilder
    private func trackballHitArea(_ control: DeviceControl, rect: CGRect) -> some View {
        let isPressed = pressedControl == control.id

        TrackballSurface(
            longPressSeconds: control.longPressSeconds,
            onRoll: { delta in
                rollTrackball(delta, in: rect)
            },
            onClick: {
                model.click()
            },
            onHold: {
                model.hold()
            },
            onPressed: { pressed in
                pressedControl = pressed ? control.id : nil
            },
            onHover: { hovering in
                hoveringTrackball = hovering
                if !hovering {
                    trackballRemainder = .zero
                    withAnimation(.spring(response: 0.32, dampingFraction: 0.82)) {
                        trackballOffset = .zero
                    }
                }
            }
        )
        .frame(width: rect.width, height: rect.height)
        .background(
            Circle()
                .fill(
                    isPressed
                        ? Color.white.opacity(0.12)
                        : hoveringTrackball ? Color.white.opacity(0.05) : Color.clear
                )
        )
        .position(x: rect.midX, y: rect.midY)
        .help(helpText(for: control))
        .accessibilityLabel(control.label)
        .accessibilityHint(helpText(for: control))
        .accessibilityAddTraits(.isButton)
        .accessibilityAction {
            model.click()
        }
    }

    @ViewBuilder
    private func sideButtonHitArea(_ control: DeviceControl, rect: CGRect) -> some View {
        let isPressed = pressedControl == control.id
        let usesPressedSkin = control.shortAction == "ptt"

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

    private func rollTrackball(_ delta: CGSize, in rect: CGRect) {
        trackballRemainder.width += delta.width
        trackballRemainder.height += delta.height

        let visualMax = max(7, rect.width * 0.055)
        trackballOffset = clamped(trackballRemainder, maximum: visualMax)

        let threshold = max(24, rect.width * 0.16)
        var steps = 0
        while steps < 6 {
            let dx = trackballRemainder.width
            let dy = trackballRemainder.height
            if abs(dx) >= threshold, abs(dx) >= abs(dy) {
                model.navigate(dx < 0 ? "left" : "right")
                trackballRemainder.width -= dx < 0 ? -threshold : threshold
            } else if abs(dy) >= threshold {
                model.navigate(dy < 0 ? "up" : "down")
                trackballRemainder.height -= dy < 0 ? -threshold : threshold
            } else {
                break
            }
            steps += 1
        }
    }

    private func clamped(_ translation: CGSize, maximum: CGFloat) -> CGSize {
        let distance = hypot(translation.width, translation.height)
        guard distance > maximum, distance > 0 else { return translation }
        let scale = maximum / distance
        return CGSize(width: translation.width * scale, height: translation.height * scale)
    }

    private func helpText(for control: DeviceControl) -> String {
        if control.id == "trackball" {
            return "Hover to navigate. Click to select. Hold to Reach."
        }
        if control.shortAction == "ptt" {
            return "Press and hold to talk."
        }
        return control.label
    }

    private func frame(for rect: NormalizedRect, size: CGFloat) -> CGRect {
        CGRect(
            x: rect.x * size,
            y: rect.y * size,
            width: rect.width * size,
            height: rect.height * size
        )
    }

    private func deviceArtwork(_ image: NSImage, size: CGFloat) -> some View {
        Image(nsImage: image)
            .resizable()
            .interpolation(.high)
            .frame(width: size, height: size)
    }

    private var showingPressedSkin: Bool {
        pressedDeviceImage != nil && (model.isPushToTalking || pressedControl == "side")
    }
}

private struct ConversationPanel: View {
    @ObservedObject var model: SimulatorModel
    @State private var draft = ""

    var body: some View {
        VStack(spacing: 0) {
            header
            transcript
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
                    .foregroundStyle(model.deviceState == "asleep" ? Color.red : Color.primary)
            }
            .buttonStyle(.plain)
            .background(Circle().fill(Color.primary.opacity(0.06)))
            .help(model.deviceState == "asleep" ? "Turn Gizmo on" : "Turn Gizmo off")
            .accessibilityLabel(model.deviceState == "asleep" ? "Turn Gizmo on" : "Turn Gizmo off")
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
