import AppKit
import Combine
import Foundation
import SwiftUI

enum ConnectionStatus: String {
    case offline
    case starting
    case connecting
    case connected
    case failed
}

struct SimulatorEvent: Identifiable {
    let id = UUID()
    let time: Date
    let name: String
    let detail: String
}

enum ConversationRole {
    case gizmo
    case user
}

struct ConversationMessage: Identifiable {
    let id = UUID()
    let role: ConversationRole
    let text: String
    let time: Date
}

struct ScreenClip: Identifiable {
    let id: String
    let stillPath: String
    let frames: [Data]
    let fps: Int
    let width: Int
    let height: Int
    let encodedBytes: Int
}

private struct PendingCue {
    var still: NSImage?
    var clip: ScreenClip?
    var task: Task<Void, Never>?
}

@MainActor
final class SimulatorModel: ObservableObject {
    static let shared = SimulatorModel()

    @Published private(set) var connectionStatus: ConnectionStatus = .offline
    @Published private(set) var deviceState = "powered_off"
    @Published private(set) var transport = "—"
    @Published private(set) var screenOn = false
    @Published private(set) var viewingStill = false
    @Published private(set) var spokenLine = ""
    @Published private(set) var screenImage: NSImage?
    @Published private(set) var screenImageID: String?
    @Published private(set) var screenClip: ScreenClip?
    @Published private(set) var events: [SimulatorEvent] = []
    @Published private(set) var conversation: [ConversationMessage] = []
    @Published private(set) var isPushToTalking = false
    @Published private(set) var voiceError: String?
    @Published private(set) var microphoneStatus: String?
    @Published private(set) var microphoneLevel: Double = 0

    // Fake battery until the real body reports one.
    @Published private(set) var batteryLevel: Double = 1.0

    private var bootSound: NSSound?
    private var bootSoundTask: Task<Void, Never>?
    private var hasColdBooted = false
    /// The glass owns the splash. A 1.25-second local frame drop leads into the
    /// existing 14-frame blink; the final wordmark then holds for its old beat.
    static let splashMinimum: Duration = .milliseconds(5050)
    @Published private(set) var splashHolding = false
    private var splashTask: Task<Void, Never>?

    /// What the glass shows. While the splash is up it stays on the boot
    /// flipbook even if the brain has already moved to listening.
    @Published private(set) var glassState = "powered_off"
    /// Bumped on every cold boot so the splash flipbook always restarts.
    @Published private(set) var bootGeneration = 0
    /// Last switch position we sent. Stale friend events cannot undo it.
    private var pendingPowerOn: Bool?

    // The hardware power toggle: physically cuts power. While off, no
    // other control does anything. Flipping it on is the cold boot.
    @Published private(set) var poweredOff = true

    private let backend = BackendConfiguration.load()
    private let hardwareProfile = HardwarePlaybackProfile.load()
    private var baseHTTPURL: URL { backend.baseURL }
    private let session = URLSession(configuration: .default)
    private var screenImageTask: Task<Void, Never>?
    private var screenImageRequest = UUID()
    private var requestedStillPath: String?
    private var screenClipTask: Task<Void, Never>?
    private var screenClipRequest = UUID()
    private var requestedClipPath: String?
    private var clipStillPath: String?
    /// Held film cues buffered but not yet told to play (`go`). Same contract
    /// as the body: preload still + bounded MJPEG, ack, wait for go.
    private var pendingCues: [Int: PendingCue] = [:]
    private var socket: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var sendTask: Task<Void, Never>?
    private var microphonePressID = UUID()
    private var microphoneBytes = 0
    private var microphonePeak = 0
    private var microphoneStartedAt: Date?
    private var reconnectTask: Task<Void, Never>?
    private var backendProcess: Process?
    private var launchedBackend = false
    private var hasStarted = false
    private var isShuttingDown = false
    @Published private(set) var cameraOpen = false
    @Published private(set) var cameraImage: NSImage?
    @Published private(set) var cameraError: String?
    private let camera = CameraFeed()
    private var cameraID = UUID()
    private var selectTask: Task<Void, Never>?
    private let microphone = MicrophoneCapture()
    private let speaker = SpeakerPlayback()

    enum GlassSetting: String {
        case brightness
        case volume
    }

    static let settingSteps = 10
    @Published private(set) var settingsOpen = false
    @Published private(set) var settingsFocus: GlassSetting = .volume
    @Published private(set) var settingsAdjusting = false
    @Published private(set) var brightnessStep = 8
    @Published private(set) var volumeStep = 8

    /// Black veil on the glass. Step 10 is full; step 0 stays just readable.
    var screenDim: Double {
        (1.0 - Double(brightnessStep) / Double(Self.settingSteps)) * 0.82
    }

    private init() {
        speaker.setOutputVolume(Float(volumeStep) / Float(Self.settingSteps))
    }

    private var worldMotion: Animation? {
        NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
            ? nil
            : .spring(response: 0.4, dampingFraction: 0.92)
    }

    private var controlMotion: Animation? {
        NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
            ? nil
            : .spring(response: 0.22, dampingFraction: 0.9)
    }

    func start() {
        guard !hasStarted else { return }
        hasStarted = true
        isShuttingDown = false
        appendEvent("identity", "This body is \(DeviceIdentity.id)")
        appendEvent(
            "glass profile",
            "\(hardwareProfile.width)×\(hardwareProfile.height) at \(hardwareProfile.fps) fps; "
                + "\(hardwareProfile.maxEncodedBytes)-byte encoded cap; provisional=\(hardwareProfile.provisional)"
        )

        Task {
            await ensureBackendAndConnect()
        }
    }

    func reconnect() {
        closeCamera()
        closeSettings(animated: false)
        stopMicrophone()
        sendTask?.cancel()
        reconnectTask?.cancel()
        reconnectTask = nil
        receiveTask?.cancel()
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
        connectionStatus = .connecting

        Task {
            await ensureBackendAndConnect()
        }
    }

    func shutdown() {
        isShuttingDown = true
        closeCamera()
        closeSettings(animated: false)
        clearShow()
        reconnectTask?.cancel()
        reconnectTask = nil
        stopMicrophone()
        sendTask?.cancel()
        speaker.shutdown()
        stopBootSound()
        isPushToTalking = false
        receiveTask?.cancel()
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil

        if launchedBackend, let backendProcess, backendProcess.isRunning {
            backendProcess.terminate()
        }
        backendProcess = nil
        launchedBackend = false
        connectionStatus = .offline
    }

    func select() {
        DeviceHaptics.controlTick()
        guard !poweredOff, !splashHolding else { return }
        if settingsOpen {
            selectTask?.cancel()
            selectTask = nil
            send(["type": "select"])
            return
        }
        if selectTask != nil {
            selectTask?.cancel()
            selectTask = nil
            if cameraOpen { closeCamera() } else { openCamera() }
            return
        }
        selectTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(320))
            guard let self, !Task.isCancelled else { return }
            self.selectTask = nil
            if self.cameraOpen { self.closeCamera() }
            if self.viewingStill { self.clearShow() }
            self.send(["type": "select"])
        }
    }

    private func openCamera() {
        guard !poweredOff, !splashHolding, screenOn, deviceState != "asleep", !settingsOpen else { return }
        clearShow()
        cameraOpen = true
        cameraImage = nil
        cameraError = nil
        let id = UUID()
        cameraID = id
        appendEvent("camera", "Opened camera world")
        camera.capture(id: id) { [weak self] result in
            Task { @MainActor in
                guard let self, self.cameraOpen, self.cameraID == id else { return }
                switch result {
                case .success(let snapshot): self.cameraImage = NSImage(data: snapshot.jpeg)
                case .failure(let error): self.cameraError = error.message
                }
            }
        }
    }

    private func closeCamera() {
        selectTask?.cancel()
        selectTask = nil
        cameraID = UUID()
        camera.cancel()
        if cameraOpen { appendEvent("camera", "Closed camera world") }
        cameraOpen = false
        cameraImage = nil
        cameraError = nil
    }

    /// Ding lands when the final boot frame (the wordmark) first appears, not on power-on.
    /// That's the last flipbook frame: delay is (frameCount - 1) / fps.
    private func playBootSound() {
        bootSoundTask?.cancel()
        bootSound?.stop()

        let url = ProjectLocator.repositoryRoot()?
            .appendingPathComponent("glass/sounds/boot.wav")
        guard let url, FileManager.default.fileExists(atPath: url.path) else { return }

        let boot = SpriteStore.shared.animation(for: "boot")
        let fps = boot?.fps ?? 8
        let lastIndex = max((boot?.frames.count ?? 1) - 1, 0)
        let wordmarkDelay = fps > 0 ? Double(lastIndex) / fps : 0

        bootSoundTask = Task { @MainActor [weak self] in
            if wordmarkDelay > 0 {
                try? await Task.sleep(for: .seconds(wordmarkDelay))
            }
            guard let self, !Task.isCancelled, !self.poweredOff, self.splashHolding else {
                return
            }
            self.bootSound = NSSound(contentsOf: url, byReference: true)
            self.bootSound?.play()
        }
    }

    private func stopBootSound() {
        bootSoundTask?.cancel()
        bootSoundTask = nil
        bootSound?.stop()
        bootSound = nil
    }

    private func beginSplashHold() {
        splashTask?.cancel()
        splashHolding = true
        refreshGlassState()
        splashTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: Self.splashMinimum)
            guard let self, !Task.isCancelled else { return }
            self.splashHolding = false
            self.refreshGlassState()
        }
    }

    private func endSplashHold() {
        splashTask?.cancel()
        splashTask = nil
        splashHolding = false
        refreshGlassState()
    }

    private func refreshGlassState() {
        let next: String
        if poweredOff {
            next = "powered_off"
        } else if splashHolding {
            next = "booting"
        } else {
            next = deviceState
        }
        if glassState != next {
            glassState = next
        }
    }

    func drainBattery() {
        batteryLevel = batteryLevel <= 0 ? 1.0 : max(0, batteryLevel - 0.1)
    }

    func togglePower() {
        if poweredOff {
            // Flipping the toggle on: power arrives, cold boot begins.
            applyPowerOff(false)
            hasColdBooted = true
            bootGeneration += 1
            pendingPowerOn = true
            deviceState = "booting"
            screenOn = true
            beginSplashHold()
            playBootSound()
            send(["type": "power", "on": true])
        } else {
            // Hard cut. Not sleep. Sleep is idle-only and any button wakes it.
            applyPowerOff(true)
            pendingPowerOn = false
            send(["type": "power", "on": false])
        }
        NSHapticFeedbackManager.defaultPerformer.perform(.alignment, performanceTime: .now)
    }

    private func applyPowerOff(_ off: Bool) {
        poweredOff = off
        if off {
            closeCamera()
            closeSettings(animated: false)
            clearShow()
            speaker.interrupt()
            stopBootSound()
            endSplashHold()
            if isPushToTalking {
                endPushToTalk()
            }
            screenOn = false
            deviceState = "powered_off"
        }
        refreshGlassState()
    }

    func beginPushToTalk() {
        // Press means "listen". If he is asleep the same press wakes him
        // first; the brain handles both. While the power toggle is off
        // there is no power: nothing reports.
        guard !poweredOff, !isPushToTalking else { return }
        // Splash owns the glass. Talk waits until the wordmark is done.
        guard !splashHolding else { return }

        startListening()
    }

    private func startListening() {
        guard connectionStatus == .connected, !poweredOff, !isPushToTalking else { return }

        isPushToTalking = true
        let pressID = UUID()
        microphonePressID = pressID
        microphoneBytes = 0
        microphonePeak = 0
        microphoneLevel = 0
        microphoneStartedAt = Date()
        microphoneStatus = "Opening microphone…"
        speaker.interrupt()
        voiceError = nil
        send(["type": "ptt", "active": true])

        Task {
            guard await MicrophoneCapture.requestAccess() else {
                guard isPushToTalking, microphonePressID == pressID else { return }
                stopMicrophone()
                voiceError = "Allow Gizmo Simulator in System Settings → Privacy & Security → Microphone."
                send(["type": "ptt", "active": false])
                return
            }

            guard isPushToTalking, microphonePressID == pressID else { return }
            do {
                try microphone.start { [weak self] pcm in
                    Task { @MainActor in
                        guard let self, self.microphonePressID == pressID else { return }
                        self.sendAudio(pcm)
                    }
                }
                microphoneStatus = "Listening — release to send"
            } catch {
                guard isPushToTalking, microphonePressID == pressID else { return }
                stopMicrophone()
                voiceError = "Microphone unavailable: \(error.localizedDescription)"
                send(["type": "ptt", "active": false])
                appendEvent("microphone", error.localizedDescription)
            }
        }
    }

    func endPushToTalk() {
        guard isPushToTalking else { return }
        let held = Date().timeIntervalSince(microphoneStartedAt ?? Date())
        let capturedBytes = microphoneBytes
        let capturedPeak = microphonePeak
        stopMicrophone()
        send(["type": "ptt", "active": false])
        // Diagnostics only: a bump too short to carry speech is not an error.
        if held >= 0.3 {
            appendEvent("microphone", "Sent \(capturedBytes) PCM bytes; peak \(capturedPeak).")
            if capturedBytes == 0 {
                voiceError = "No microphone audio. Check your Mac's sound input and microphone permission."
            } else if capturedPeak < 8 {
                voiceError = "The microphone is silent. Check your Mac's sound input."
            } else {
                microphoneStatus = "Sent — waiting for Gizmo"
            }
        }
    }

    private func stopMicrophone() {
        microphone.stop()
        isPushToTalking = false
        microphonePressID = UUID()
        microphoneStatus = nil
        microphoneLevel = 0
    }

    func navigate(_ direction: String) {
        guard ["up", "down"].contains(direction) else { return }
        DeviceHaptics.controlTick()
        guard !poweredOff else { return }
        selectTask?.cancel()
        selectTask = nil
        // Camera is a local sensor world. Those rocker edges stay here so
        // Friend can treat every forwarded "up" as Settings.
        if !splashHolding, screenOn, deviceState != "asleep" {
            if cameraOpen {
                if direction == "up" { closeCamera() }
                return
            }
            if direction == "down", !settingsOpen {
                openCamera()
                return
            }
        }
        send(["type": "navigate", "direction": direction])
    }

    private func closeSettings(animated: Bool = true) {
        let wasOpen = settingsOpen
        let apply = {
            self.settingsOpen = false
            self.settingsAdjusting = false
            self.settingsFocus = .volume
        }
        if animated {
            withAnimation(worldMotion, apply)
        } else {
            apply()
        }
        if wasOpen { appendEvent("settings", "Closed settings") }
    }

    private func applySettings(_ object: [String: Any], allowOpen: Bool) {
        let source: [String: Any]
        if object["type"] as? String == "settings" {
            source = object
        } else if let nested = object["settings"] as? [String: Any] {
            source = nested
        } else {
            return
        }

        let open = allowOpen && (source["open"] as? Bool ?? false)
        let adjusting = open && (source["adjusting"] as? Bool ?? false)
        let focus: GlassSetting = source["focus"] as? String == "brightness" ? .brightness : .volume
        let brightness = clampSettingStep(source["brightness"])
        let volume = clampSettingStep(source["volume"])
        let panelChanged = open != settingsOpen
            || adjusting != settingsAdjusting
            || focus != settingsFocus
        let volumeChanged = volume != volumeStep
        let levelChanged = brightness != brightnessStep || volumeChanged
        guard panelChanged || levelChanged else {
            speaker.setOutputVolume(Float(volume) / Float(Self.settingSteps))
            return
        }

        withAnimation(open != settingsOpen ? worldMotion : controlMotion) {
            settingsOpen = open
            settingsAdjusting = adjusting
            settingsFocus = focus
            brightnessStep = brightness
            volumeStep = volume
        }
        speaker.setOutputVolume(Float(volume) / Float(Self.settingSteps))
        if volumeChanged, adjusting {
            speaker.previewVolumeTick()
        }
        appendEvent(
            "settings",
            open
                ? "\(adjusting ? "Adjusting" : "Focus") \(focus.rawValue) · bright \(brightness) · vol \(volume)"
                : "Closed settings"
        )
    }

    private func clampSettingStep(_ value: Any?) -> Int {
        let number: Int
        if let intValue = value as? Int {
            number = intValue
        } else if let doubleValue = value as? Double {
            number = Int(doubleValue.rounded())
        } else if let nsNumber = value as? NSNumber {
            number = nsNumber.intValue
        } else {
            number = 8
        }
        return min(Self.settingSteps, max(0, number))
    }

    func say(_ text: String) {
        guard !poweredOff else { return }
        let cleaned = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return }
        send(["type": "text", "text": cleaned])
        appendConversation(role: .user, text: cleaned)
        appendEvent("you", cleaned)
    }

    private func ensureBackendAndConnect() async {
        if let error = backend.error {
            connectionStatus = .failed
            appendEvent("connection", error)
            return
        }
        if backend.isRemote && (backend.baseURL.scheme != "https" || backend.token?.isEmpty != false) {
            connectionStatus = .failed
            appendEvent("connection", "Cloud mode requires HTTPS and GIZMO_DEVICE_TOKEN.")
            return
        }
        let healthy = await backendIsHealthy()
        appendEvent("connection", "health=\(healthy) remote=\(backend.isRemote) ownBrain=\(launchedBackend)")
        if healthy {
            if backend.isRemote || launchedBackend {
                connect()
                return
            }
            // Something is already on our port that we did not start: a brain
            // left over from an earlier app run, possibly on stale code. The
            // app owns its brain. Evict it and start a fresh one.
            appendEvent("runtime", "Replacing a leftover Friend on port 43147.")
            await evictStaleBackend()
        }

        if backend.isRemote {
            connectionStatus = .offline
            appendEvent("connection", "Cloud brain unavailable. Reconnecting…")
            scheduleReconnect()
            return
        }

        connectionStatus = .starting
        do {
            try launchBackend()
        } catch {
            connectionStatus = .failed
            appendEvent("runtime error", error.localizedDescription)
            return
        }

        for _ in 0..<40 {
            if await backendIsHealthy() {
                connect()
                return
            }
            try? await Task.sleep(for: .milliseconds(125))
        }

        connectionStatus = .failed
        appendEvent("runtime error", "Friend did not start on port 43147.")
    }

    private func backendIsHealthy() async -> Bool {
        do {
            let url = baseHTTPURL.appendingPathComponent("health")
            let (_, response) = try await session.data(for: backend.request(for: url))
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    /// Terminates whatever is listening on the local brain port and waits
    /// for it to go away. Used only for processes this app did not start.
    private func evictStaleBackend() async {
        let port = backend.baseURL.port ?? 43147
        let lsof = Process()
        lsof.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        lsof.arguments = ["-ti", "tcp:\(port)", "-sTCP:LISTEN"]
        let pipe = Pipe()
        lsof.standardOutput = pipe
        lsof.standardError = FileHandle.nullDevice
        guard (try? lsof.run()) != nil else { return }
        let output = pipe.fileHandleForReading.readDataToEndOfFile()
        lsof.waitUntilExit()

        let pids = String(decoding: output, as: UTF8.self)
            .split(whereSeparator: \.isNewline)
            .compactMap { Int32($0.trimmingCharacters(in: .whitespaces)) }
        for pid in pids where pid != ProcessInfo.processInfo.processIdentifier {
            kill(pid, SIGTERM)
        }

        for _ in 0..<40 {
            if !(await backendIsHealthy()) { return }
            try? await Task.sleep(for: .milliseconds(125))
        }
        for pid in pids where pid != ProcessInfo.processInfo.processIdentifier {
            kill(pid, SIGKILL)
        }
    }

    private func launchBackend() throws {
        guard let root = ProjectLocator.repositoryRoot() else {
            throw RuntimeError.repositoryNotFound
        }

        let executable = root.appendingPathComponent(".venv/bin/gizmo")
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw RuntimeError.runtimeMissing(executable.path)
        }

        let process = Process()
        process.executableURL = executable
        process.arguments = ["--host", "127.0.0.1", "--port", "43147"]
        process.currentDirectoryURL = root
        // A brain that dies on startup must leave a trace. data/ is gitignored.
        let log = Self.openBrainLog(in: root)
        process.standardOutput = log ?? FileHandle.nullDevice
        process.standardError = log ?? FileHandle.nullDevice
        try process.run()

        backendProcess = process
        launchedBackend = true
        appendEvent("runtime", "Started Friend locally. Log: data/brain.log")
    }

    private static func openBrainLog(in root: URL) -> FileHandle? {
        openLog(named: "brain.log", in: root)
    }

    /// The app's own event trail, since the events panel has no UI yet.
    private static let eventLog: FileHandle? = {
        guard let root = ProjectLocator.repositoryRoot() else { return nil }
        return openLog(named: "simulator.log", in: root)
    }()

    private static func openLog(named name: String, in root: URL) -> FileHandle? {
        let dir = root.appendingPathComponent("data", isDirectory: true)
        let url = dir.appendingPathComponent(name)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        // Fresh log per launch; the previous run's tail is what you'd want anyway.
        FileManager.default.createFile(atPath: url.path, contents: nil)
        return try? FileHandle(forWritingTo: url)
    }

    private func connect() {
        connectionStatus = .connecting
        var request = backend.request(for: backend.webSocketURL)
        // Advertise held-cue film playback: the brain only starts Cinema when
        // a connected body asks for held glass cues.
        request.setValue("1", forHTTPHeaderField: "X-Gizmo-Glass-Cues")
        let task = session.webSocketTask(with: request)
        socket = task
        task.resume()

        receiveTask?.cancel()
        receiveTask = Task { [weak self] in
            await self?.receiveLoop(task)
        }
    }

    private func receiveLoop(_ task: URLSessionWebSocketTask) async {
        while !Task.isCancelled {
            do {
                let message = try await task.receive()
                switch message {
                case .string(let string):
                    handleMessage(Data(string.utf8))
                case .data(let data):
                    handleMessage(data)
                @unknown default:
                    break
                }
            } catch {
                if !Task.isCancelled {
                    markDisconnected("Friend disconnected. Reconnecting…")
                }
                return
            }
        }
    }

    private func markDisconnected(_ detail: String) {
        guard !isShuttingDown else { return }
        closeCamera()
        closeSettings(animated: false)
        stopMicrophone()
        dropPendingCues()
        sendTask?.cancel()
        speaker.interrupt()
        connectionStatus = .offline
        socket = nil
        appendEvent("connection", detail)
        scheduleReconnect()
    }

    private func scheduleReconnect() {
        guard reconnectTask == nil, !isShuttingDown else { return }
        reconnectTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(400))
            guard let self, !Task.isCancelled, !self.isShuttingDown else { return }

            // Clear the slot before connecting so an immediate socket failure
            // can schedule the next retry instead of leaving the UI dead.
            self.reconnectTask = nil
            await self.ensureBackendAndConnect()
        }
    }

    private func handleMessage(_ data: Data) {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }

        let type = object["type"] as? String ?? "event"
        if type == "hello" {
            connectionStatus = .connected
            pendingPowerOn = nil
            // The switch is truth. A brain that disagrees on connect (left
            // over from an earlier run, or restarted under a device that is
            // still on) is told the switch position and follows it.
            if let brainPower = object["power"] as? Bool, brainPower != !poweredOff {
                pendingPowerOn = !poweredOff
                if !poweredOff {
                    hasColdBooted = false
                    bootGeneration += 1
                }
                send(["type": "power", "on": !poweredOff])
                appendEvent("power", poweredOff ? "Brain was on; switch is off. Cutting power."
                                                : "Brain was off; switch is on. Booting.")
            }
        }

        if let power = object["power"] as? Bool {
            if let pending = pendingPowerOn {
                if power == pending {
                    pendingPowerOn = nil
                    if !power { applyPowerOff(true) }
                    else { poweredOff = false }
                }
            } else if type == "hello" {
                if !power { applyPowerOff(true) }
                else { poweredOff = false }
            } else if poweredOff && power {
                // Stale "still on" after a hard off. Do not turn the glass back on.
            } else if !power {
                applyPowerOff(true)
            } else {
                poweredOff = false
            }
        }

        if poweredOff && type != "hello" {
            screenOn = false
            deviceState = "powered_off"
            refreshGlassState()
        } else if let state = object["state"] as? String {
            if state == "talking", deviceState != "talking" { spokenLine = "" }
            deviceState = state
            if isPushToTalking, ["asleep", "booting"].contains(state) {
                stopMicrophone()
            }
            // The chime is for the cold boot only — the once-per-power-up
            // ritual. Waking from sleep is silent, like a phone.
            refreshGlassState()
            if state == "booting", !hasColdBooted {
                hasColdBooted = true
                beginSplashHold()
                playBootSound()
            }
        }
        if let path = object["transport"] as? String {
            transport = path
        }
        if let isOn = object["screen"] as? Bool {
            screenOn = poweredOff ? false : isOn
        }
        if poweredOff || !screenOn || deviceState == "asleep" {
            closeCamera()
        }
        applySettings(
            object,
            allowOpen: !poweredOff && screenOn && deviceState != "asleep"
        )
        if poweredOff || !screenOn || deviceState == "asleep" || deviceState == "booting"
            || object["viewing"] as? Bool == false {
            clearShow()
        }

        if type == "audio", let pcm = object["pcm"] as? String, let data = Data(base64Encoded: pcm) {
            guard !poweredOff, screenOn, !isPushToTalking else { return }
            do { try speaker.enqueue(data) }
            catch { appendEvent("speaker error", error.localizedDescription) }
        } else if type == "transcript_delta" {
            spokenLine += object["text"] as? String ?? ""
        } else if type == "transcript", object["role"] as? String == "gizmo" {
            spokenLine = object["text"] as? String ?? ""
            appendConversation(role: .gizmo, text: spokenLine)
        } else if type == "transcript", object["role"] as? String == "user" {
            microphoneStatus = nil
            appendConversation(role: .user, text: object["text"] as? String ?? "")
        } else if type == "interrupted" {
            speaker.interrupt()
            spokenLine = ""
        } else if type == "glass" {
            if let cue = object["cue"] as? Int {
                if object["hold"] as? Bool == true {
                    holdCue(cue, object: object)
                } else if object["go"] as? Bool == true {
                    playCue(cue, object: object)
                }
            } else {
                // Reconnect snapshots can contain both URLs in the same event.
                if let still = object["still"] as? String { loadScreenImage(path: still) }
                if let frames = object["frames"] as? String { loadScreenFrames(path: frames) }
            }
        } else if type == "error" {
            appendEvent("error", object["message"] as? String ?? "Unknown error")
        }

        appendEvent(type, eventDetail(object))
    }

    private func loadScreenImage(path: String) {
        guard !poweredOff, screenOn, deviceState != "asleep", deviceState != "booting",
              let url = URL(string: path, relativeTo: baseHTTPURL)?.absoluteURL,
              var parts = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return }
        if requestedStillPath == path, screenImageTask != nil || screenImageID == path { return }
        requestedStillPath = path
        screenImageTask?.cancel()
        let requestID = UUID()
        screenImageRequest = requestID
        parts.queryItems = (parts.queryItems ?? []).filter { !["w", "h"].contains($0.name) } + [
            URLQueryItem(name: "w", value: String(hardwareProfile.width)),
            URLQueryItem(name: "h", value: String(hardwareProfile.height)),
        ]
        guard let sizedURL = parts.url else { return }

        screenImageTask = Task {
            defer {
                if screenImageRequest == requestID { screenImageTask = nil }
            }
            do {
                let (data, response) = try await session.data(for: backend.request(for: sizedURL))
                guard !Task.isCancelled, screenImageRequest == requestID,
                      requestedStillPath == path, !poweredOff, screenOn,
                      (response as? HTTPURLResponse)?.statusCode == 200,
                      let image = NSImage(data: data) else { return }
                if clipStillPath != path { clearClip() }
                screenImage = image
                screenImageID = path
                viewingStill = true
                appendEvent(
                    "show displayed",
                    "\(path) at \(hardwareProfile.width)×\(hardwareProfile.height); state=\(deviceState)"
                )
            } catch {
                if !Task.isCancelled { appendEvent("screen error", error.localizedDescription) }
            }
        }
    }

    private func clearShow() {
        dropPendingCues()
        clearClip()
        screenImageRequest = UUID()
        screenImageTask?.cancel()
        screenImageTask = nil
        requestedStillPath = nil
        viewingStill = false
        screenImage = nil
        screenImageID = nil
    }

    private func loadScreenFrames(path: String) {
        guard !poweredOff, screenOn, deviceState != "asleep", deviceState != "booting",
              let url = URL(string: path, relativeTo: baseHTTPURL)?.absoluteURL,
              url.scheme == baseHTTPURL.scheme, url.host == baseHTTPURL.host,
              url.port == baseHTTPURL.port, url.pathExtension == "mjpeg",
              let stillPath = stillPath(forFramesPath: path),
              var parts = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return }
        guard screenImageID == stillPath || requestedStillPath == stillPath else { return }
        if requestedClipPath == path, screenClipTask != nil || screenClip?.id == path { return }
        clearClip()
        requestedClipPath = path
        clipStillPath = stillPath
        parts.queryItems = (parts.queryItems ?? []).filter { !["w", "h", "fps"].contains($0.name) } + [
            URLQueryItem(name: "w", value: String(hardwareProfile.width)),
            URLQueryItem(name: "h", value: String(hardwareProfile.height)),
            URLQueryItem(name: "fps", value: String(hardwareProfile.fps)),
        ]
        guard let framesURL = parts.url else { return }
        let requestID = UUID()
        screenClipRequest = requestID
        screenClipTask = Task {
            defer {
                if screenClipRequest == requestID { screenClipTask = nil }
            }
            do {
                var request = backend.request(for: framesURL)
                request.timeoutInterval = 35
                let (data, response) = try await downloadBoundedFrames(
                    session: session,
                    request: request,
                    maximumBytes: hardwareProfile.maxEncodedBytes
                )
                guard !Task.isCancelled, screenClipRequest == requestID,
                      !poweredOff, screenOn,
                      screenImageID == stillPath || requestedStillPath == stillPath else { return }
                let sequence = try MotionJPEGSequence(
                    data: data,
                    response: response,
                    profile: hardwareProfile
                )
                guard !Task.isCancelled, screenClipRequest == requestID,
                      screenImageID == stillPath || requestedStillPath == stillPath else { return }
                screenClip = ScreenClip(
                    id: path,
                    stillPath: stillPath,
                    frames: sequence.frames,
                    fps: sequence.fps,
                    width: sequence.width,
                    height: sequence.height,
                    encodedBytes: sequence.encodedBytes
                )
                appendEvent(
                    "clip loaded",
                    "\(sequence.frames.count) JPEGs; \(sequence.width)×\(sequence.height) at "
                        + "\(sequence.fps) fps; \(sequence.encodedBytes) encoded bytes"
                )
            } catch {
                if !Task.isCancelled { appendEvent("clip error", error.localizedDescription) }
            }
        }
    }

    /// Held cue: buffer the still and bounded MJPEG, ack, then wait for `go`.
    /// Same preload contract the body speaks — the segment must never paint
    /// before the brain says go.
    private func holdCue(_ cue: Int, object: [String: Any]) {
        func fail() {
            send(["type": "glass_ready", "cue": cue, "kind": "motion", "ok": false])
        }
        guard !poweredOff, screenOn, deviceState != "asleep",
              let stillPath = object["still"] as? String,
              let framesPath = object["frames"] as? String,
              let stillURL = showURL(stillPath, extension: "jpg", extras: []),
              let framesURL = showURL(framesPath, extension: "mjpeg", extras: [("fps", hardwareProfile.fps)])
        else {
            fail()
            return
        }
        pendingCues[cue]?.task?.cancel()
        let task = Task {
            do {
                let (stillData, stillResponse) = try await session.data(for: backend.request(for: stillURL))
                guard !Task.isCancelled,
                      (stillResponse as? HTTPURLResponse)?.statusCode == 200,
                      let still = NSImage(data: stillData)
                else { throw URLError(.badServerResponse) }
                var request = backend.request(for: framesURL)
                request.timeoutInterval = 35
                let (framesData, framesResponse) = try await downloadBoundedFrames(
                    session: session,
                    request: request,
                    maximumBytes: hardwareProfile.maxEncodedBytes
                )
                guard !Task.isCancelled else { return }
                let sequence = try MotionJPEGSequence(
                    data: framesData, response: framesResponse, profile: hardwareProfile
                )
                pendingCues[cue] = PendingCue(
                    still: still,
                    clip: ScreenClip(
                        id: framesPath,
                        stillPath: stillPath,
                        frames: sequence.frames,
                        fps: sequence.fps,
                        width: sequence.width,
                        height: sequence.height,
                        encodedBytes: sequence.encodedBytes
                    )
                )
                appendEvent(
                    "film cue buffered",
                    "\(cue): \(sequence.frames.count) JPEGs at \(sequence.fps) fps"
                )
                send(["type": "glass_ready", "cue": cue, "kind": "motion", "ok": true])
            } catch {
                if !Task.isCancelled {
                    pendingCues.removeValue(forKey: cue)
                    appendEvent("film cue error", "\(cue): \(error.localizedDescription)")
                    fail()
                }
            }
        }
        pendingCues[cue] = PendingCue(task: task)
    }

    /// `go` on a buffered cue: promote it to the glass with its caption.
    private func playCue(_ cue: Int, object: [String: Any]) {
        if let pending = pendingCues.removeValue(forKey: cue), let still = pending.still, let clip = pending.clip {
            clearClip()
            screenImageRequest = UUID()
            screenImageTask?.cancel()
            clipStillPath = clip.stillPath
            screenImage = still
            screenImageID = clip.stillPath
            screenClip = clip
            viewingStill = true
            if let caption = object["text"] as? String { spokenLine = caption }
            appendEvent("film playing", "\(clip.frames.count) frames at \(clip.fps) fps")
        } else {
            // Missed or evicted buffer: degrade to the plain show path.
            if let still = object["still"] as? String { loadScreenImage(path: still) }
            if let frames = object["frames"] as? String { loadScreenFrames(path: frames) }
        }
    }

    private func showURL(_ path: String, extension ext: String, extras: [(String, Int)]) -> URL? {
        guard let url = URL(string: path, relativeTo: baseHTTPURL)?.absoluteURL,
              url.scheme == baseHTTPURL.scheme, url.host == baseHTTPURL.host,
              url.port == baseHTTPURL.port, url.pathExtension == ext,
              var parts = URLComponents(url: url, resolvingAgainstBaseURL: false)
        else { return nil }
        var items = (parts.queryItems ?? []).filter { !["w", "h", "fps"].contains($0.name) } + [
            URLQueryItem(name: "w", value: String(hardwareProfile.width)),
            URLQueryItem(name: "h", value: String(hardwareProfile.height)),
        ]
        for (name, value) in extras {
            items.append(URLQueryItem(name: name, value: String(value)))
        }
        parts.queryItems = items
        return parts.url
    }

    private func dropPendingCues() {
        for (_, cue) in pendingCues { cue.task?.cancel() }
        pendingCues.removeAll()
    }

    private func stillPath(forFramesPath path: String) -> String? {
        guard var parts = URLComponents(string: path), parts.url?.pathExtension == "mjpeg" else {
            return nil
        }
        parts.path = (parts.path as NSString).deletingPathExtension + ".jpg"
        parts.query = nil
        parts.fragment = nil
        return parts.string
    }

    func clipPlaybackEvent(_ event: String, path: String) {
        appendEvent("clip \(event)", path)
    }

    private func clearClip() {
        screenClipRequest = UUID()
        screenClipTask?.cancel()
        screenClipTask = nil
        requestedClipPath = nil
        clipStillPath = nil
        screenClip = nil
    }

    private func send(_ payload: [String: Any]) {
        guard let socket else {
            appendEvent("connection", "Not connected.")
            return
        }

        do {
            let data = try JSONSerialization.data(withJSONObject: payload)
            guard let text = String(data: data, encoding: .utf8) else { return }

            // Keep PTT down -> PCM chunks -> PTT up in wire order. Separate
            // unstructured sends could let the release overtake the audio.
            let previousSend = sendTask
            sendTask = Task {
                await previousSend?.value
                guard !Task.isCancelled, self.socket === socket else { return }
                do {
                    try await socket.send(.string(text))
                } catch {
                    appendEvent("send error", error.localizedDescription)
                    markDisconnected("Could not reach Friend. Reconnecting…")
                }
            }
        } catch {
            appendEvent("send error", error.localizedDescription)
        }
    }

    private func sendAudio(_ pcm: Data) {
        guard isPushToTalking, !pcm.isEmpty else { return }
        let peak = pcm.withUnsafeBytes { bytes in
            stride(from: 0, to: bytes.count - 1, by: 2).reduce(0) { highest, offset in
                max(highest, abs(Int(Int16(littleEndian: bytes.loadUnaligned(fromByteOffset: offset, as: Int16.self)))))
            }
        }
        microphoneBytes += pcm.count
        microphonePeak = max(microphonePeak, peak)
        microphoneLevel = Double(peak) / 32768.0
        send(["type": "audio", "pcm": pcm.base64EncodedString()])
    }

    private func eventDetail(_ object: [String: Any]) -> String {
        if let text = object["text"] as? String, !text.isEmpty {
            return text
        }
        if let name = object["name"] as? String {
            return name
        }
        if let hint = object["hint"] as? String, !hint.isEmpty {
            return hint
        }
        return deviceState
    }

    private func appendEvent(_ name: String, _ detail: String) {
        Self.eventLog?.write(Data("\(Date()) [\(name)] \(detail)\n".utf8))
        events.insert(SimulatorEvent(time: Date(), name: name, detail: detail), at: 0)
        if events.count > 120 {
            events.removeLast(events.count - 120)
        }
    }

    private func appendConversation(role: ConversationRole, text: String) {
        let cleaned = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return }
        if let last = conversation.last, last.role == role, last.text == cleaned {
            return
        }
        conversation.append(ConversationMessage(role: role, text: cleaned, time: Date()))
    }
}

private enum RuntimeError: LocalizedError {
    case repositoryNotFound
    case runtimeMissing(String)

    var errorDescription: String? {
        switch self {
        case .repositoryNotFound:
            return "Could not locate the Gizmo repository."
        case .runtimeMissing(let path):
            return "Friend is not installed at \(path). Run the repository setup first."
        }
    }
}
