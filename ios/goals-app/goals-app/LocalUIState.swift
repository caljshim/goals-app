import SwiftUI

/// Stable keys for presentation state that should survive app relaunches.
/// Keeping them centralized prevents a widget rename or reorder from losing state.
enum LocalUIStateKey {
    private static let namespace = "money.ui"

    static let selectedTab = "\(namespace).selectedTab"
    static let financesSection = "\(namespace).finances.section"
    static let dashboardEditing = "\(namespace).dashboard.editing"
    static let dashboardOpenSource = "\(namespace).dashboard.openSource"
    static let dashboardPreview = "\(namespace).dashboard.preview"
    static let leftToSpendExpanded = "\(namespace).leftToSpend.expanded"
    static let budgetPeriod = "\(namespace).budgets.period"
    static let transactionCategoriesExpanded = "\(namespace).transactionCategories.expanded"

    static func goalCategoryExpanded(_ id: String) -> String {
        "\(namespace).goalCategory.\(id).expanded"
    }

    static func goalCategoryChartExpanded(_ id: String) -> String {
        "\(namespace).goalCategory.\(id).chartExpanded"
    }

    static func archivedGoalExpanded(_ id: Int) -> String {
        "\(namespace).archivedGoal.\(id).expanded"
    }

    static func goalChartRange(_ id: Int) -> String {
        "\(namespace).goalChart.\(id).range"
    }
}

/// `AppStorage` adapter for expandable collections whose members have stable IDs.
@propertyWrapper
struct StoredStringSet: DynamicProperty {
    @AppStorage private var encoded: String

    init(_ key: String) {
        _encoded = AppStorage(wrappedValue: "[]", key)
    }

    var wrappedValue: Set<String> {
        get {
            guard let data = encoded.data(using: .utf8),
                  let values = try? JSONDecoder().decode([String].self, from: data) else {
                return []
            }
            return Set(values)
        }
        nonmutating set {
            guard let data = try? JSONEncoder().encode(newValue.sorted()),
                  let value = String(data: data, encoding: .utf8) else { return }
            encoded = value
        }
    }
}
