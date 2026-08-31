import AppKit
import SwiftUI

struct TrackballSurface: NSViewRepresentable {
    var longPressSeconds: TimeInterval
    var onRoll: (CGSize) -> Void
    var onClick: () -> Void
    var onHold: () -> Void
    var onPressed: (Bool) -> Void
    var onHover: (Bool) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(
            longPressSeconds: longPressSeconds,
            onRoll: onRoll,
            onClick: onClick,
            onHold: onHold,
            onPressed: onPressed,
            onHover: onHover
        )
    }

    func makeNSView(context: Context) -> TrackballNSView {
        let view = TrackballNSView()
        view.handler = context.coordinator
        return view
    }

    func updateNSView(_ nsView: TrackballNSView, context: Context) {
        context.coordinator.longPressSeconds = longPressSeconds
        context.coordinator.onRoll = onRoll
        context.coordinator.onClick = onClick
        context.coordinator.onHold = onHold
        context.coordinator.onPressed = onPressed
        context.coordinator.onHover = onHover
        nsView.handler = context.coordinator
    }

    @MainActor
    final class Coordinator {
        var longPressSeconds: TimeInterval
        var onRoll: (CGSize) -> Void
        var onClick: () -> Void
        var onHold: () -> Void
        var onPressed: (Bool) -> Void
        var onHover: (Bool) -> Void

        private var pressed = false
        private var pressStartedAt: Date?

        init(
            longPressSeconds: TimeInterval,
            onRoll: @escaping (CGSize) -> Void,
            onClick: @escaping () -> Void,
            onHold: @escaping () -> Void,
            onPressed: @escaping (Bool) -> Void,
            onHover: @escaping (Bool) -> Void
        ) {
            self.longPressSeconds = longPressSeconds
            self.onRoll = onRoll
            self.onClick = onClick
            self.onHold = onHold
            self.onPressed = onPressed
            self.onHover = onHover
        }

        func hover(_ hovering: Bool) {
            onHover(hovering)
        }

        func roll(dx: CGFloat, dy: CGFloat) {
            guard !pressed else { return }
            guard dx != 0 || dy != 0 else { return }
            onRoll(CGSize(width: dx, height: dy))
        }

        func pressBegan() {
            guard !pressed else { return }
            pressed = true
            pressStartedAt = Date()
            onPressed(true)
        }

        func pressEnded() {
            guard pressed else { return }
            let held = Date().timeIntervalSince(pressStartedAt ?? Date()) >= longPressSeconds
            pressed = false
            pressStartedAt = nil
            onPressed(false)
            if held {
                onHold()
            } else {
                onClick()
            }
        }
    }
}

final class TrackballNSView: NSView {
    var handler: TrackballSurface.Coordinator?
    private var trackingArea: NSTrackingArea?
    private var eventMonitor: Any?
    private var hovering = false

    override var isOpaque: Bool { false }
    override var acceptsFirstResponder: Bool { true }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        window?.acceptsMouseMovedEvents = true
        updateTrackingAreas()
        if window == nil {
            stopMonitor()
            if hovering {
                hovering = false
                handler?.hover(false)
            }
        }
    }

    override func layout() {
        super.layout()
        window?.invalidateCursorRects(for: self)
    }

    override func resetCursorRects() {
        addCursorRect(bounds, cursor: .openHand)
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingArea {
            removeTrackingArea(trackingArea)
        }
        let area = NSTrackingArea(
            rect: bounds,
            options: [.mouseEnteredAndExited, .mouseMoved, .activeInKeyWindow, .inVisibleRect],
            owner: self,
            userInfo: nil
        )
        trackingArea = area
        addTrackingArea(area)
    }

    override func hitTest(_ point: NSPoint) -> NSView? {
        guard circleContains(point) else { return nil }
        return super.hitTest(point)
    }

    override func mouseEntered(with event: NSEvent) {
        startMonitor()
        handleHoverEvent(event)
    }

    override func mouseExited(with event: NSEvent) {
        stopMonitor()
        endHover()
    }

    override func mouseDown(with event: NSEvent) {
        handler?.pressBegan()
    }

    override func mouseUp(with event: NSEvent) {
        handler?.pressEnded()
    }

    private func beginHover() {
        guard !hovering else { return }
        hovering = true
        handler?.hover(true)
    }

    private func endHover() {
        guard hovering else { return }
        hovering = false
        handler?.hover(false)
    }

    private func startMonitor() {
        guard eventMonitor == nil else { return }
        eventMonitor = NSEvent.addLocalMonitorForEvents(matching: [.mouseMoved, .scrollWheel]) { [weak self] event in
            self?.handleHoverEvent(event)
            return event
        }
    }

    private func stopMonitor() {
        if let eventMonitor {
            NSEvent.removeMonitor(eventMonitor)
            self.eventMonitor = nil
        }
    }

    private func handleHoverEvent(_ event: NSEvent) {
        let location = convert(event.locationInWindow, from: nil)
        guard circleContains(location) else {
            endHover()
            return
        }

        beginHover()

        switch event.type {
        case .mouseMoved:
            handler?.roll(dx: event.deltaX, dy: event.deltaY)
        case .scrollWheel:
            let scale: CGFloat = event.hasPreciseScrollingDeltas ? 1 : 8
            handler?.roll(
                dx: event.scrollingDeltaX * scale,
                dy: -event.scrollingDeltaY * scale
            )
        default:
            break
        }
    }

    private func circleContains(_ point: NSPoint) -> Bool {
        let radius = min(bounds.width, bounds.height) / 2 + 2
        let dx = point.x - bounds.midX
        let dy = point.y - bounds.midY
        return (dx * dx) + (dy * dy) <= radius * radius
    }
}
