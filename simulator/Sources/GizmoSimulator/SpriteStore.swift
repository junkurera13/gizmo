import AppKit
import Combine
import Foundation

struct HeartArt {
    let full: NSImage
    let half: NSImage
    let empty: NSImage
}

struct SpriteAnimation: Equatable {
    let name: String
    let frames: [NSImage]
    let fps: Double
    let loop: Bool
    let wander: Bool

    static func == (lhs: SpriteAnimation, rhs: SpriteAnimation) -> Bool {
        lhs.name == rhs.name && lhs.frames.count == rhs.frames.count
    }
}

/// Scratch preview player for Jun's drawings in glass/sprites/.
///
/// Not the character architecture. Folder names follow today's device
/// states as a temporary hook so a sheet can be tried on the glass.
/// After the design lands, this mapping gets rebuilt. Empty glass is black.
@MainActor
final class SpriteStore: ObservableObject {
    static let shared = SpriteStore()

    @Published private(set) var animations: [String: SpriteAnimation] = [:]
    @Published private(set) var hearts: HeartArt?
    @Published private(set) var lastLoadNote: String?

    private static let fallbacks: [String: [String]] = [
        "listen": ["idle"],
        "talk": ["idle"],
        "think": ["idle"],
        "see": ["think", "idle"],
        "show": ["think", "idle"],
        "sleep": ["idle"],
    ]

    private init() {}

    func animation(for name: String) -> SpriteAnimation? {
        if let hit = animations[name] {
            return hit
        }
        for candidate in Self.fallbacks[name] ?? [] {
            if let hit = animations[candidate] {
                return hit
            }
        }
        return nil
    }

    func load() {
        guard let root = ProjectLocator.repositoryRoot() else {
            lastLoadNote = "Repository not found; no sprites loaded."
            return
        }
        let spritesDir = root.appendingPathComponent("glass/sprites", isDirectory: true)
        let manager = FileManager.default

        guard let entries = try? manager.contentsOfDirectory(
            at: spritesDir,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) else {
            animations = [:]
            lastLoadNote = "No glass/sprites folder yet — glass stays black."
            return
        }

        let overrides = Self.readOverrides(at: spritesDir.appendingPathComponent("sprites.json"))
        var loaded: [String: SpriteAnimation] = [:]

        var loadedHearts: HeartArt?

        for entry in entries {
            guard (try? entry.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true else {
                continue
            }
            let name = entry.lastPathComponent.lowercased()

            // hearts/ holds the battery art (full/half/empty), not a flipbook.
            if name == "hearts" {
                if let full = NSImage(contentsOf: entry.appendingPathComponent("full.png")),
                   let half = NSImage(contentsOf: entry.appendingPathComponent("half.png")),
                   let empty = NSImage(contentsOf: entry.appendingPathComponent("empty.png")) {
                    loadedHearts = HeartArt(full: full, half: half, empty: empty)
                }
                continue
            }

            let frames = Self.readFrames(in: entry)
            guard !frames.isEmpty else { continue }

            let meta = overrides[name]
            loaded[name] = SpriteAnimation(
                name: name,
                frames: frames,
                fps: meta?.fps ?? 10,
                loop: meta?.loop ?? !["boot", "sleep"].contains(name),
                wander: meta?.wander ?? (name == "see")
            )
        }

        animations = loaded
        hearts = loadedHearts
        lastLoadNote = loaded.isEmpty
            ? "glass/sprites is empty — glass stays black."
            : "Loaded \(loaded.count) animation(s): \(loaded.keys.sorted().joined(separator: ", "))."
    }

    private static func readFrames(in directory: URL) -> [NSImage] {
        let manager = FileManager.default
        guard let files = try? manager.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        ) else {
            return []
        }

        return files
            .filter { $0.pathExtension.lowercased() == "png" }
            .sorted {
                $0.lastPathComponent.compare(
                    $1.lastPathComponent,
                    options: [.numeric, .caseInsensitive]
                ) == .orderedAscending
            }
            .compactMap { NSImage(contentsOf: $0) }
    }

    private struct AnimationOverride: Decodable {
        let fps: Double?
        let loop: Bool?
        let wander: Bool?
    }

    private static func readOverrides(at url: URL) -> [String: AnimationOverride] {
        guard let data = try? Data(contentsOf: url),
              let decoded = try? JSONDecoder().decode([String: AnimationOverride].self, from: data)
        else {
            return [:]
        }
        return Dictionary(uniqueKeysWithValues: decoded.map { ($0.key.lowercased(), $0.value) })
    }
}
