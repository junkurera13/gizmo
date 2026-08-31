// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "GizmoSimulator",
    platforms: [
        .macOS(.v15),
    ],
    products: [
        .executable(name: "GizmoSimulator", targets: ["GizmoSimulator"]),
    ],
    targets: [
        .executableTarget(
            name: "GizmoSimulator",
            path: "Sources/GizmoSimulator"
        ),
    ]
)
