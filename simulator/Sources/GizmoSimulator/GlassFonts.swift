import AppKit
import CoreText
import Foundation

/// Type we can actually ship. Files live in `glass/fonts/` so the Mac
/// preview and later the body share one face. Missing files fall back
/// to the system clock font.
@MainActor
enum GlassFonts {
    private static var didRegister = false

    static func register() {
        guard !didRegister else { return }
        didRegister = true
        guard let dir = ProjectLocator.repositoryRoot()?
            .appendingPathComponent("glass/fonts", isDirectory: true)
        else { return }

        let files = (try? FileManager.default.contentsOfDirectory(
            at: dir,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        )) ?? []

        for url in files where ["ttf", "otf"].contains(url.pathExtension.lowercased()) {
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        }
    }

    /// Outfit Medium with tabular digits — the home clock.
    static func clock(size: CGFloat) -> NSFont {
        register()
        let wghtAxis = 0x77676874 // 'wght'
        let descriptor = NSFontDescriptor(fontAttributes: [
            .family: "Outfit",
            .size: size,
            NSFontDescriptor.AttributeName(rawValue: kCTFontVariationAttribute as String): [
                wghtAxis: 500,
            ],
            .featureSettings: [[
                NSFontDescriptor.FeatureKey.typeIdentifier: kNumberSpacingType,
                NSFontDescriptor.FeatureKey.selectorIdentifier: kMonospacedNumbersSelector,
            ]],
        ])
        if let font = NSFont(descriptor: descriptor, size: size),
           font.familyName?.localizedCaseInsensitiveContains("Outfit") == true
        {
            return font
        }
        return NSFont.monospacedDigitSystemFont(ofSize: size, weight: .medium)
    }
}
