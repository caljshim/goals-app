import SwiftUI

/// iOS-side mapping of the backend's portable customization tokens to SF Symbols
/// and Theme colors. Token lists mirror backend/app/budget/goal_customization.py.
enum Customization {
    static let iconCatalog: [String] = [
        "tag", "flame", "target", "bank", "card", "cashflow", "chart", "star",
        "heart", "run", "book", "house", "car", "plane", "cart", "gift",
        "briefcase", "grad", "dumbbell", "food", "coffee", "leaf", "bolt", "trophy",
        "flag", "calendar", "bell", "moon", "sun", "drop", "paw", "sparkle",
    ]

    static let colorCatalog: [String] = [
        "pine", "honey", "copper", "sky", "plum", "sage", "rose", "clay", "teal", "slate",
    ]

    private static let symbols: [String: String] = [
        "tag": "tag.fill", "flame": "flame.fill", "target": "target",
        "bank": "banknote.fill", "card": "creditcard.fill",
        "cashflow": "dollarsign.arrow.circlepath", "chart": "chart.line.uptrend.xyaxis",
        "star": "star.fill", "heart": "heart.fill", "run": "figure.run",
        "book": "book.fill", "house": "house.fill", "car": "car.fill",
        "plane": "airplane", "cart": "cart.fill", "gift": "gift.fill",
        "briefcase": "briefcase.fill", "grad": "graduationcap.fill",
        "dumbbell": "dumbbell.fill", "food": "fork.knife",
        "coffee": "cup.and.saucer.fill", "leaf": "leaf.fill", "bolt": "bolt.fill",
        "trophy": "trophy.fill", "flag": "flag.fill", "calendar": "calendar",
        "bell": "bell.fill", "moon": "moon.fill", "sun": "sun.max.fill",
        "drop": "drop.fill", "paw": "pawprint.fill", "sparkle": "sparkles",
    ]

    private static let colors: [String: Color] = [
        "pine": Theme.brand, "honey": Theme.honey, "copper": Theme.negative,
        "sky": Color(light: 0x46698C, dark: 0x8FB4D9),
        "plum": Color(light: 0x7A5586, dark: 0xB491C0),
        "sage": Color(light: 0x5E7A6E, dark: 0x9DB8AC),
        "rose": Color(light: 0x8C4658, dark: 0xD98FA4),
        "clay": Color(light: 0x6E6146, dark: 0xC2B08A),
        "teal": Color(light: 0x0F6E6A, dark: 0x5FC9C2),
        "slate": Color(light: 0x4A5A66, dark: 0x9BB0BE),
    ]

    static func symbol(for token: String) -> String { symbols[token] ?? "target" }
    static func color(for token: String) -> Color { colors[token] ?? Theme.brand }
}
