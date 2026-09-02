import AppKit
import Combine
import Foundation
import UniformTypeIdentifiers

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
    @Published private(set) var cameraSource = "No frame"
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
    /// The glass owns the splash. Blink is 14 frames at 8 fps (~1.75 s);
    /// then `14.png` (the wordmark) holds for a beat so it can be read.
    static let splashMinimum: Duration = .milliseconds(3800)
    /// Finger-down is a tap. The title card only yields after a real hold.
    static let startHoldMinimum: Duration = .milliseconds(400)
    @Published private(set) var splashHolding = false
    private var splashTask: Task<Void, Never>?
    private var startHoldTask: Task<Void, Never>?

    /// What the glass shows. While the splash is up it stays on the boot
    /// flipbook even if the brain has already moved to listening.
    @Published private(set) var glassState = "powered_off"
    /// Bumped on every cold boot so the splash flipbook always restarts.
    @Published private(set) var bootGeneration = 0
    /// Last switch position we sent. Stale friend events cannot undo it.
    private var pendingPowerOn: Bool?
    /// After a cold-boot splash, sit on the title card until the first
    /// pink-button hold. Wake from sleep skips this.
    @Published private(set) var awaitingStart = false

    // The hardware power toggle: physically cuts power. While off, no
    // other control does anything. Flipping it on is the cold boot.
    @Published private(set) var poweredOff = true

    private let backend = BackendConfiguration.load()
    private var baseHTTPURL: URL { backend.baseURL }
    private let session = URLSession(configuration: .default)
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
    private let microphone = MicrophoneCapture()
    private let speaker = SpeakerPlayback()

    private init() {}

    func start() {
        guard !hasStarted else { return }
        hasStarted = true
        isShuttingDown = false

        Task {
            await ensureBackendAndConnect()
        }
    }

    func reconnect() {
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
        reconnectTask?.cancel()
        reconnectTask = nil
        stopMicrophone()
        sendTask?.cancel()
        speaker.shutdown()
        stopBootSound()
        cancelStartHold()
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
        // The body reports every press; the brain decides what it means
        // (while asleep, any button simply wakes him).
        guard !poweredOff else { return }
        send(["type": "select"])
    }

    /// Ding lands when `14.png` (the wordmark) first appears, not on power-on.
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
        awaitingStart = true
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
        } else if awaitingStart, deviceState != "asleep" {
            next = "start"
        } else {
            next = deviceState
        }
        if glassState != next {
            glassState = next
        }
    }

    func dismissStartScreen() {
        guard awaitingStart else { return }
        cancelStartHold()
        awaitingStart = false
        refreshGlassState()
    }

    private func cancelStartHold() {
        startHoldTask?.cancel()
        startHoldTask = nil
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
            speaker.interrupt()
            stopBootSound()
            cancelStartHold()
            endSplashHold()
            if isPushToTalking {
                endPushToTalk()
            }
            screenOn = false
            deviceState = "powered_off"
            awaitingStart = false
        }
        refreshGlassState()
    }

    func beginPushToTalk() {
        // Press means "listen". If he is asleep the same press wakes him
        // first; the brain handles both. While the power toggle is off
        // there is no power: nothing reports.
        guard !poweredOff, !isPushToTalking else { return }
        // Splash owns the glass. A hold during it must not skip the title card.
        guard !splashHolding else { return }

        if awaitingStart {
            armStartHold()
            return
        }

        startListening()
    }

    /// Title card stays up until the pink button has been down long enough.
    /// Release early and nothing happens. Same hold then becomes talk.
    private func armStartHold() {
        guard startHoldTask == nil else { return }
        startHoldTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: Self.startHoldMinimum)
            guard let self, !Task.isCancelled, !self.poweredOff, self.awaitingStart else {
                return
            }
            self.startHoldTask = nil
            self.dismissStartScreen()
            self.startListening()
        }
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
        cancelStartHold()
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
        send(["type": "navigate", "direction": direction])
    }

    func say(_ text: String) {
        guard !poweredOff else { return }
        let cleaned = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return }
        dismissStartScreen()
        send(["type": "text", "text": cleaned])
        appendConversation(role: .user, text: cleaned)
        appendEvent("you", cleaned)
    }

    func point(hint: String) {
        let cleaned = hint.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return }
        cameraSource = cleaned
        send(["type": "frame", "hint": cleaned])
    }

    func chooseCameraFrame() {
        let panel = NSOpenPanel()
        panel.title = "Choose a world-camera frame"
        panel.prompt = "Point Gizmo"
        panel.allowedContentTypes = [.image]
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false

        guard panel.runModal() == .OK, let url = panel.url else { return }

        do {
            let data = try Data(contentsOf: url)
            cameraSource = url.lastPathComponent
            send([
                "type": "frame",
                "image": data.base64EncodedString(),
                "hint": url.deletingPathExtension().lastPathComponent,
            ])
        } catch {
            appendEvent("camera error", error.localizedDescription)
        }
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
        let task = session.webSocketTask(with: backend.request(for: backend.webSocketURL))
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
        stopMicrophone()
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
            deviceState = state
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
        if let viewing = object["viewing"] as? Bool {
            viewingStill = viewing
            if !viewing {
                screenImage = nil
            }
        }

        if type == "audio", let pcm = object["pcm"] as? String, let data = Data(base64Encoded: pcm) {
            guard !poweredOff, screenOn, !isPushToTalking else { return }
            do { try speaker.enqueue(data) }
            catch { appendEvent("speaker error", error.localizedDescription) }
        } else if type == "transcript", object["role"] as? String == "gizmo" {
            spokenLine = object["text"] as? String ?? ""
            appendConversation(role: .gizmo, text: spokenLine)
        } else if type == "transcript", object["role"] as? String == "user" {
            microphoneStatus = nil
            appendConversation(role: .user, text: object["text"] as? String ?? "")
        } else if type == "interrupted" {
            speaker.interrupt()
            spokenLine = ""
        } else if type == "glass", let still = object["still"] as? String {
            loadScreenImage(path: still)
        } else if type == "error" {
            appendEvent("error", object["message"] as? String ?? "Unknown error")
        }

        appendEvent(type, eventDetail(object))
    }

    private func loadScreenImage(path: String) {
        guard let url = URL(string: path, relativeTo: baseHTTPURL)?.absoluteURL else { return }

        Task {
            do {
                let (data, _) = try await session.data(for: backend.request(for: url))
                if let image = NSImage(data: data) {
                    screenImage = image
                }
            } catch {
                appendEvent("screen error", error.localizedDescription)
            }
        }
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
