import AppKit
import Combine
import Foundation

struct SpriteAnimation: Equatable {
    let name: String
    let frames: [NSImage]
    let fps: Double
    let loop: Bool
    let wander: Bool
    /// Slot pattern: each entry is a frame index held for `period` seconds.
    /// The firmware format for character states — open, blink, lean, paint.
    let slots: [Int]?
    let period: TimeInterval

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
    @Published private(set) var lastLoadNote: String?

    private static let fallbacks: [String: [String]] = [
        "talking": ["idle"],
        "sleeping": ["idle"],
        "see": ["thinking", "idle"],
        "show": ["thinking", "idle"],
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

        for entry in entries {
            guard (try? entry.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true else {
                continue
            }
            let name = entry.lastPathComponent.lowercased()
            if name == "hearts" { continue }

            let frames = Self.readFrames(in: entry)
            guard !frames.isEmpty else { continue }

            let meta = overrides[name]
            loaded[name] = SpriteAnimation(
                name: name,
                frames: frames,
                fps: meta?.fps ?? 10,
                loop: meta?.loop ?? !["boot", "sleep"].contains(name),
                wander: meta?.wander ?? (name == "see"),
                slots: meta?.slots,
                period: (meta?.periodMs ?? 0) / 1000
            )
        }

        animations = loaded
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
        let slots: [Int]?
        let periodMs: Double?

        enum CodingKeys: String, CodingKey {
            case fps, loop, wander, slots
            case periodMs = "period_ms"
        }
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
