import SwiftUI
import UIKit

// MARK: - "Ledger pine" design tokens
//
// One brand hue (pine → mint in dark), copper instead of alarm-red for
// over-budget/negative states, honey gold for streaks and milestones.
// Money and metrics are set in rounded type with monospaced digits.

extension Color {
    init(light: UInt32, dark: UInt32, lightAlpha: Double = 1, darkAlpha: Double = 1) {
        self.init(uiColor: UIColor { traits in
            let dark_ = traits.userInterfaceStyle == .dark
            let hex = dark_ ? dark : light
            return UIColor(
                red: CGFloat((hex >> 16) & 0xFF) / 255,
                green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255,
                alpha: dark_ ? darkAlpha : lightAlpha
            )
        })
    }
}

enum Theme {
    /// Brand + "money in / on track". Deep pine in light, mint in dark.
    static let brand = Color(light: 0x146B54, dark: 0x63D0A8)
    /// Text/icons placed on top of a brand-filled surface.
    static let onBrand = Color(light: 0xFFFFFF, dark: 0x0B1512)
    /// "Money out / over budget". Copper, not alarm-red.
    static let negative = Color(light: 0xB0562F, dark: 0xE0906A)
    /// Streaks, milestones, recommendations.
    static let honey = Color(light: 0xB9871F, dark: 0xE3BE5E)
    /// Screen background: a faint green cast so cards read as paper.
    static let canvas = Color(light: 0xF0F3F1, dark: 0x0D1210)
    /// Card surface.
    static let card = Color(light: 0xFFFFFF, dark: 0x171D1A)
    static let cardStroke = Color(light: 0x14352A, dark: 0xFFFFFF, lightAlpha: 0.06, darkAlpha: 0.09)
    static let shadow = Color(light: 0x0A2A1F, dark: 0x000000, lightAlpha: 0.07, darkAlpha: 0.0)
    /// Categorical scale for charts, derived from the palette.
    static let chartScale: [Color] = [
        brand,
        honey,
        Color(light: 0x46698C, dark: 0x8FB4D9),
        negative,
        Color(light: 0x7A5586, dark: 0xB491C0),
        Color(light: 0x5E7A6E, dark: 0x9DB8AC),
        Color(light: 0x8C4658, dark: 0xD98FA4),
        Color(light: 0x6E6146, dark: 0xC2B08A),
    ]
}

extension Font {
    /// The single most important number on a card.
    static let heroNumber = Font.system(size: 26, weight: .bold, design: .rounded)
    /// Secondary metrics (portfolio cells, averages).
    static let statNumber = Font.system(.title3, design: .rounded).weight(.bold)
}

extension View {
    /// Keep a figure on one line; shrink it a little instead of wrapping.
    func fitOneLine(minScale: CGFloat = 0.55) -> some View {
        lineLimit(1).minimumScaleFactor(minScale)
    }
}

extension Text {
    /// Quiet uppercase tracked label used for every card title.
    func widgetTitle() -> some View {
        font(.caption.weight(.semibold))
            .tracking(1.1)
            .textCase(.uppercase)
            .foregroundStyle(.secondary)
    }
}

// MARK: - Signature components

/// The app's one progress language: capsule gauge with a soft self-tinted
/// track, gradient fill, and a copper overflow state. `pct` is 0–100+.
struct GaugeBar: View {
    let pct: Double
    var tint: Color = Theme.brand
    var over: Bool? = nil
    var height: CGFloat = 10
    var reverse: Bool = false

    var body: some View {
        let isOver = over ?? (pct > 100)
        let fill = min(max(pct, 0), 100) / 100
        let color = isOver ? Theme.negative : tint
        GeometryReader { geo in
            ZStack(alignment: reverse ? .trailing : .leading) {
                Capsule().fill(color.opacity(0.14))
                Capsule()
                    .fill(LinearGradient(colors: [color.opacity(0.7), color], startPoint: .leading, endPoint: .trailing))
                    .frame(width: max(geo.size.width * fill, pct > 0 ? height : 0))
            }
        }
        .frame(height: height)
        .animation(.spring(duration: 0.45), value: pct)
        .accessibilityElement()
        .accessibilityLabel(Text(reverse ? "\(Int(pct)) percent toward lower target" : "\(Int(pct)) percent"))
    }
}

/// SF symbol in a tinted rounded square; replaces ad-hoc emoji icons.
struct IconChip: View {
    let symbol: String
    var tint: Color = Theme.brand

    var body: some View {
        Image(systemName: symbol)
            .font(.footnote.weight(.semibold))
            .foregroundStyle(tint)
            .frame(width: 27, height: 27)
            .background(tint.opacity(0.13), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

/// Small capsule status label ("Recommended", "Sandbox").
struct TagBadge: View {
    let text: String
    var symbol: String? = nil
    var tint: Color = Theme.brand

    var body: some View {
        HStack(spacing: 4) {
            if let symbol { Image(systemName: symbol).font(.caption2.weight(.semibold)) }
            Text(text).font(.caption2.weight(.bold)).tracking(0.6).textCase(.uppercase)
        }
        .foregroundStyle(tint)
        .padding(.horizontal, 9).padding(.vertical, 4)
        .background(tint.opacity(0.12), in: Capsule())
    }
}
