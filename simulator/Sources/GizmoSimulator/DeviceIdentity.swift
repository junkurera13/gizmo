import Foundation

/// Who this body is. On hardware this is the serial burned in at the
/// factory; here it is minted on first launch and kept, so this install is
/// one Gizmo with one memory, distinct from every other install.
///
/// `GIZMO_DEVICE_ID` in the environment overrides it, for testing as a
/// specific device or for a deliberate fresh start.
enum DeviceIdentity {
    private static let key = "gizmo.device.id"

    static let id: String = {
        if let forced = ProcessInfo.processInfo.environment["GIZMO_DEVICE_ID"], !forced.isEmpty {
            return forced
        }
        let defaults = UserDefaults.standard
        if let existing = defaults.string(forKey: key), !existing.isEmpty {
            return existing
        }
        let minted = "sim-" + UUID().uuidString.lowercased().replacingOccurrences(of: "-", with: "").prefix(16)
        defaults.set(minted, forKey: key)
        return minted
    }()
}
