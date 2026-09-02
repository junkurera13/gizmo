import Foundation

struct BackendConfiguration {
    let baseURL: URL
    let token: String?
    var error: String? = nil

    var isRemote: Bool {
        !["127.0.0.1", "localhost", "::1"].contains(baseURL.host ?? "")
    }

    var webSocketURL: URL {
        var parts = URLComponents(url: baseURL.appendingPathComponent("ws"), resolvingAgainstBaseURL: false)!
        parts.scheme = baseURL.scheme == "https" ? "wss" : "ws"
        return parts.url!
    }

    func request(for url: URL) -> URLRequest {
        var request = URLRequest(url: url)
        request.timeoutInterval = 8
        // Never forward the device credential to an unrelated media host.
        if url.host == baseURL.host {
            if let token, !token.isEmpty {
                request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            }
            request.setValue(DeviceIdentity.id, forHTTPHeaderField: "X-Gizmo-Device")
        }
        return request
    }

    static func load() -> BackendConfiguration {
        var values: [String: String] = [:]
        if let root = ProjectLocator.repositoryRoot(),
           let contents = try? String(contentsOf: root.appendingPathComponent(".env"), encoding: .utf8) {
            for line in contents.split(separator: "\n") {
                let parts = line.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
                guard parts.count == 2 else { continue }
                let key = parts[0].trimmingCharacters(in: .whitespaces)
                guard ["GIZMO_BRAIN_URL", "GIZMO_DEVICE_TOKEN"].contains(key) else { continue }
                values[key] = parts[1].trimmingCharacters(in: .whitespacesAndNewlines)
                    .trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
            }
        }
        values.merge(ProcessInfo.processInfo.environment) { _, environment in environment }
        guard let url = URL(string: values["GIZMO_BRAIN_URL"] ?? "http://127.0.0.1:43147"),
              ["https", "http"].contains(url.scheme ?? ""), url.host != nil,
              url.user == nil, url.password == nil else {
            return BackendConfiguration(baseURL: URL(string: "http://127.0.0.1:43147")!, token: nil,
                                        error: "GIZMO_BRAIN_URL must be a valid HTTP or HTTPS URL.")
        }
        return BackendConfiguration(baseURL: url, token: values["GIZMO_DEVICE_TOKEN"])
    }
}
