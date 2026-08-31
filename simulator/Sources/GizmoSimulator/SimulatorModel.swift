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
    @Published private(set) var deviceState = "asleep"
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

    // Fake battery until the real body reports one.
    @Published private(set) var batteryLevel: Double = 1.0

    private var bootSound: NSSound?
    private var hasColdBooted = false

    // The hardware power toggle: physically cuts power. While off, no
    // other control does anything. Flipping it on is the cold boot.
    @Published private(set) var poweredOff = true

    private let baseHTTPURL = URL(string: "http://127.0.0.1:43147")!
    private let webSocketURL = URL(string: "ws://127.0.0.1:43147/ws")!
    private let session = URLSession(configuration: .default)
    private var socket: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var backendProcess: Process?
    private var launchedBackend = false
    private var hasStarted = false
    private let microphone = MicrophoneCapture()

    private init() {}

    func start() {
        guard !hasStarted else { return }
        hasStarted = true

        Task {
            await ensureBackendAndConnect()
        }
    }

    func reconnect() {
        receiveTask?.cancel()
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil

        Task {
            await ensureBackendAndConnect()
        }
    }

    func shutdown() {
        microphone.stop()
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

    func click() {
        DeviceHaptics.trackballTick()
        guard !poweredOff, deviceState != "asleep" else { return }
        send(["type": "click"])
    }

    func hold() {
        guard !poweredOff, deviceState != "asleep" else { return }
        send(["type": "hold"])
    }

    /// The Game Boy moment: one chime, same every time, synced to the
    /// boot animation. The sound is Jun's file at glass/sounds/boot.wav.
    private func playBootSound() {
        let url = ProjectLocator.repositoryRoot()?
            .appendingPathComponent("glass/sounds/boot.wav")
        guard let url, FileManager.default.fileExists(atPath: url.path) else { return }
        bootSound?.stop()
        bootSound = NSSound(contentsOf: url, byReference: true)
        bootSound?.play()
    }

    func drainBattery() {
        batteryLevel = batteryLevel <= 0 ? 1.0 : max(0, batteryLevel - 0.1)
    }

    func togglePower() {
        if poweredOff {
            // Flipping the toggle on: power arrives, cold boot begins.
            poweredOff = false
            hasColdBooted = false
            send(["type": "power", "on": true])
        } else {
            // Flipping it off: everything stops, whatever he was doing.
            if isPushToTalking {
                endPushToTalk()
            }
            poweredOff = true
            send(["type": "power", "on": false])
        }
        NSHapticFeedbackManager.defaultPerformer.perform(.alignment, performanceTime: .now)
    }

    func beginPushToTalk() {
        // The body reports every press, even while asleep — the brain
        // decides what it means (a press while sleeping wakes him).
        // While the power toggle is off there is no power: nothing reports.
        guard connectionStatus == .connected, !poweredOff, !isPushToTalking else { return }

        isPushToTalking = true
        voiceError = nil
        send(["type": "ptt", "active": true])

        Task {
            guard await MicrophoneCapture.requestAccess() else {
                guard isPushToTalking else { return }
                isPushToTalking = false
                voiceError = "Microphone access is off"
                send(["type": "ptt", "active": false])
                return
            }

            guard isPushToTalking else { return }
            do {
                try microphone.start { [weak self] pcm in
                    Task { @MainActor in
                        self?.sendAudio(pcm)
                    }
                }
            } catch {
                guard isPushToTalking else { return }
                isPushToTalking = false
                voiceError = "Microphone unavailable"
                send(["type": "ptt", "active": false])
                appendEvent("microphone", error.localizedDescription)
            }
        }
    }

    func endPushToTalk() {
        guard isPushToTalking else { return }
        microphone.stop()
        isPushToTalking = false
        send(["type": "ptt", "active": false])
    }

    func navigate(_ direction: String) {
        guard ["up", "down", "left", "right"].contains(direction) else { return }
        DeviceHaptics.trackballTick()
        guard !poweredOff, deviceState != "asleep" else { return }
        send(["type": "navigate", "direction": direction])
    }

    func say(_ text: String) {
        guard !poweredOff else { return }
        let cleaned = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return }
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
        if await backendIsHealthy() {
            connect()
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
            let (_, response) = try await session.data(from: url)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
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
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()

        backendProcess = process
        launchedBackend = true
        appendEvent("runtime", "Started Friend locally.")
    }

    private func connect() {
        connectionStatus = .connecting
        let task = session.webSocketTask(with: webSocketURL)
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
                    connectionStatus = .offline
                    appendEvent("connection", "Friend disconnected.")
                }
                return
            }
        }
    }

    private func handleMessage(_ data: Data) {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }

        let type = object["type"] as? String ?? "event"
        if let state = object["state"] as? String {
            let previous = deviceState
            deviceState = state
            // The chime is for the cold boot only — the once-per-power-up
            // ritual. Waking from sleep is silent, like a phone.
            if state == "booting", previous == "asleep", !hasColdBooted {
                hasColdBooted = true
                playBootSound()
            }
        }
        if let path = object["transport"] as? String {
            transport = path
        }
        if let isOn = object["screen"] as? Bool {
            screenOn = isOn
        }
        if let viewing = object["viewing"] as? Bool {
            viewingStill = viewing
            if !viewing {
                screenImage = nil
            }
        }

        if type == "hello" {
            connectionStatus = .connected
        } else if type == "transcript", object["role"] as? String == "gizmo" {
            spokenLine = object["text"] as? String ?? ""
            appendConversation(role: .gizmo, text: spokenLine)
        } else if type == "interrupted" {
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
                let (data, _) = try await session.data(from: url)
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

            Task {
                do {
                    try await socket.send(.string(text))
                } catch {
                    appendEvent("send error", error.localizedDescription)
                }
            }
        } catch {
            appendEvent("send error", error.localizedDescription)
        }
    }

    private func sendAudio(_ pcm: Data) {
        guard isPushToTalking, !pcm.isEmpty else { return }
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
