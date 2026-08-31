import AppKit
import SwiftUI

@main
struct GizmoSimulatorApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup("Gizmo Simulator") {
            ContentView()
                .frame(minWidth: 920, minHeight: 680)
        }
        .defaultSize(width: 1160, height: 780)
        .windowToolbarStyle(.unifiedCompact)
        .commands {
            CommandMenu("Device") {
                Button("Press Trackball") {
                    SimulatorModel.shared.click()
                }
                .keyboardShortcut(.space, modifiers: [])

                Button("Hold Trackball") {
                    SimulatorModel.shared.hold()
                }
                .keyboardShortcut("r", modifiers: [])

                Divider()

                Button("Power") {
                    SimulatorModel.shared.togglePower()
                }
                .keyboardShortcut("p", modifiers: [])

                Button("Navigate Up") {
                    SimulatorModel.shared.navigate("up")
                }
                .keyboardShortcut(.upArrow, modifiers: [])

                Button("Navigate Down") {
                    SimulatorModel.shared.navigate("down")
                }
                .keyboardShortcut(.downArrow, modifiers: [])

                Button("Navigate Left") {
                    SimulatorModel.shared.navigate("left")
                }
                .keyboardShortcut(.leftArrow, modifiers: [])

                Button("Navigate Right") {
                    SimulatorModel.shared.navigate("right")
                }
                .keyboardShortcut(.rightArrow, modifiers: [])

                Divider()

                Button("Reconnect") {
                    SimulatorModel.shared.reconnect()
                }
                .keyboardShortcut("k", modifiers: [.command])

                Button("Reload Sprites") {
                    SpriteStore.shared.load()
                }
                .keyboardShortcut("r", modifiers: [.command])

                Divider()

                Button("Drain Battery 10%") {
                    SimulatorModel.shared.drainBattery()
                }
                .keyboardShortcut("b", modifiers: [.command, .shift])
            }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationWillTerminate(_ notification: Notification) {
        SimulatorModel.shared.shutdown()
    }
}
