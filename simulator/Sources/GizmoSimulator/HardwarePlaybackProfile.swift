import Foundation

struct HardwarePlaybackProfile: Decodable {
    let provisional: Bool
    let width: Int
    let height: Int
    let fps: Int
    let maxEncodedBytes: Int

    static let fallback = HardwarePlaybackProfile(
        provisional: true,
        width: 320,
        height: 240,
        fps: 24,
        maxEncodedBytes: 4 * 1024 * 1024
    )

    static func load() -> HardwarePlaybackProfile {
        var candidates: [URL] = []
        if let resource = Bundle.main.resourceURL {
            candidates.append(resource.appendingPathComponent("hardware-preview.json"))
        }
        if let root = ProjectLocator.repositoryRoot() {
            candidates.append(root.appendingPathComponent("simulator/hardware-preview.json"))
        }
        for url in candidates {
            guard let data = try? Data(contentsOf: url),
                  let profile = try? JSONDecoder().decode(HardwarePlaybackProfile.self, from: data),
                  (1...1024).contains(profile.width),
                  (1...1024).contains(profile.height),
                  (1...24).contains(profile.fps),
                  (1...(64 * 1024 * 1024)).contains(profile.maxEncodedBytes) else { continue }
            return profile
        }
        return fallback
    }
}
