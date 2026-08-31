import AppKit
import Combine
import Foundation

struct NormalizedRect: Codable, Equatable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

struct ScreenGeometry: Codable, Equatable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double
    let cornerRadius: Double
    let pixelWidth: Int
    let pixelHeight: Int
    let contentMode: String

    var rect: NormalizedRect {
        NormalizedRect(x: x, y: y, width: width, height: height)
    }
}

struct DeviceControl: Codable, Identifiable, Equatable {
    let id: String
    let label: String
    let shape: String
    let rect: NormalizedRect
    let shortAction: String
    let longAction: String
    let longPressSeconds: Double
}

struct DeviceSkin: Codable, Equatable {
    let id: String
    let name: String
    let imageFilename: String
    let pressedImageFilename: String?
    let canvasWidth: Int
    let canvasHeight: Int
    let stageColor: String
    let screen: ScreenGeometry
    let controls: [DeviceControl]
}

enum ProjectLocator {
    static func repositoryRoot() -> URL? {
        if let explicit = ProcessInfo.processInfo.environment["GIZMO_REPO_ROOT"], !explicit.isEmpty {
            return URL(fileURLWithPath: explicit, isDirectory: true)
        }

        var candidates = [
            Bundle.main.bundleURL,
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath, isDirectory: true),
        ]

        if let executable = Bundle.main.executableURL {
            candidates.append(executable.deletingLastPathComponent())
        }

        for candidate in candidates {
            var cursor = candidate
            for _ in 0..<9 {
                let marker = cursor.appendingPathComponent("pyproject.toml")
                if FileManager.default.fileExists(atPath: marker.path) {
                    return cursor
                }
                cursor.deleteLastPathComponent()
            }
        }
        return nil
    }
}

@MainActor
final class DeviceSkinStore: ObservableObject {
    static let shared = DeviceSkinStore()

    @Published private(set) var skin: DeviceSkin?
    @Published private(set) var image: NSImage?
    @Published private(set) var pressedImage: NSImage?
    @Published private(set) var directoryURL: URL?
    @Published private(set) var errorMessage: String?

    private init() {}

    func loadDefault() {
        guard skin == nil else { return }

        let bundled = Bundle.main.resourceURL?
            .appendingPathComponent("DeviceSkins", isDirectory: true)
            .appendingPathComponent("current", isDirectory: true)

        let source = ProjectLocator.repositoryRoot()?
            .appendingPathComponent("simulator/DeviceSkins/current", isDirectory: true)

        for candidate in [bundled, source].compactMap({ $0 }) {
            if FileManager.default.fileExists(atPath: candidate.appendingPathComponent("skin.json").path) {
                load(from: candidate)
                return
            }
        }

        errorMessage = "No device skin found."
    }

    func reload() {
        guard let directoryURL else {
            loadDefault()
            return
        }
        load(from: directoryURL)
    }

    func chooseSkin() {
        let panel = NSOpenPanel()
        panel.title = "Choose a Gizmo device skin folder"
        panel.message = "Choose a folder containing skin.json and its device image."
        panel.prompt = "Use Skin"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false

        if panel.runModal() == .OK, let url = panel.url {
            load(from: url)
        }
    }

    private func load(from directory: URL) {
        do {
            let manifestURL = directory.appendingPathComponent("skin.json")
            let data = try Data(contentsOf: manifestURL)
            let decoded = try JSONDecoder().decode(DeviceSkin.self, from: data)
            let imageURL = directory.appendingPathComponent(decoded.imageFilename)

            guard let loadedImage = NSImage(contentsOf: imageURL) else {
                throw SkinError.unreadableImage(imageURL.lastPathComponent)
            }

            skin = decoded
            image = loadedImage
            if let pressedName = decoded.pressedImageFilename {
                pressedImage = NSImage(contentsOf: directory.appendingPathComponent(pressedName))
            } else {
                pressedImage = nil
            }
            directoryURL = directory
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private enum SkinError: LocalizedError {
    case unreadableImage(String)

    var errorDescription: String? {
        switch self {
        case .unreadableImage(let name):
            return "Could not load \(name)."
        }
    }
}
