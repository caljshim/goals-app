import AppIntents
import Foundation
import Security
import WidgetKit

enum AudelWidgetConstants {
    static let appGroupIdentifier = "group.calebshim.goals-app"
    static let keychainService = "calebshim.goals-app.widget-api"
    static let keychainAccount = "backend-bearer-token"
    static let todayWidgetKind = "AudelTodayWidget"
    static let selectedTabKey = "money.ui.selectedTab"
    static let snapshotFilename = "audel-widget-today.json"
    static let configurationFilename = "audel-widget-configuration.json"
}

struct AudelWidgetTask: Codable, Hashable, Identifiable, Sendable {
    let id: String
    let source: String
    let sourceID: Int
    let title: String
    let scheduledFor: String
    let reminderTime: String?
    var completed: Bool
    var missed: Bool

    var isActionable: Bool {
        source == "routine" || source == "reminder"
    }

    var timeLabel: String? {
        guard let reminderTime, !reminderTime.isEmpty else { return nil }
        let parts = reminderTime.split(separator: ":")
        guard parts.count >= 2,
              let hour = Int(parts[0]),
              let minute = Int(parts[1]) else {
            return reminderTime
        }
        let suffix = hour >= 12 ? "PM" : "AM"
        let displayHour = hour % 12 == 0 ? 12 : hour % 12
        return String(format: "%d:%02d %@", displayHour, minute, suffix)
    }
}

struct AudelWidgetSnapshot: Codable, Equatable, Sendable {
    let generatedAt: Date
    var tasks: [AudelWidgetTask]

    static let empty = AudelWidgetSnapshot(generatedAt: .distantPast, tasks: [])

    static let placeholder = AudelWidgetSnapshot(
        generatedAt: Date(),
        tasks: [
            AudelWidgetTask(
                id: "routine:1:today",
                source: "routine",
                sourceID: 1,
                title: "Morning walk",
                scheduledFor: AudelWidgetDate.today,
                reminderTime: "08:00",
                completed: true,
                missed: false
            ),
            AudelWidgetTask(
                id: "routine:2:today",
                source: "routine",
                sourceID: 2,
                title: "Read for 20 minutes",
                scheduledFor: AudelWidgetDate.today,
                reminderTime: "19:30",
                completed: false,
                missed: false
            ),
        ]
    )

    func tasks(for filter: AudelWidgetTaskFilter) -> [AudelWidgetTask] {
        tasks
            .filter { filter == .everything || !$0.completed }
            .sorted {
                let firstTime = $0.reminderTime ?? "99:99"
                let secondTime = $1.reminderTime ?? "99:99"
                if firstTime != secondTime {
                    return firstTime < secondTime
                }
                return $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending
            }
    }

    var actionableCount: Int {
        tasks.filter(\.isActionable).count
    }

    var completedCount: Int {
        tasks.filter { $0.isActionable && $0.completed }.count
    }

    var remainingCount: Int {
        max(actionableCount - completedCount, 0)
    }
}

enum AudelWidgetTaskFilter: String, AppEnum, Codable, Sendable {
    case remaining
    case everything

    static let typeDisplayRepresentation: TypeDisplayRepresentation = "Items"
    static let caseDisplayRepresentations: [Self: DisplayRepresentation] = [
        .remaining: "Remaining",
        .everything: "Everything",
    ]
}

@available(iOS 17.0, *)
struct AudelTodayConfigurationIntent: WidgetConfigurationIntent {
    static let title: LocalizedStringResource = "Configure Today"
    static let description = IntentDescription("Choose which scheduled items Audel shows.")

    @Parameter(title: "Show", default: .remaining)
    var filter: AudelWidgetTaskFilter
}

struct AudelWidgetFileStore {
    private struct Configuration: Codable {
        let baseURL: String
    }

    let directoryURL: URL

    private var snapshotURL: URL {
        directoryURL.appendingPathComponent(
            AudelWidgetConstants.snapshotFilename,
            isDirectory: false
        )
    }

    private var configurationURL: URL {
        directoryURL.appendingPathComponent(
            AudelWidgetConstants.configurationFilename,
            isDirectory: false
        )
    }

    func loadSnapshot() -> AudelWidgetSnapshot {
        guard let data = try? Data(contentsOf: snapshotURL),
              let snapshot = try? JSONDecoder().decode(AudelWidgetSnapshot.self, from: data) else {
            return .empty
        }
        return snapshot
    }

    func saveSnapshot(_ snapshot: AudelWidgetSnapshot) {
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        try? data.write(to: snapshotURL, options: .atomic)
    }

    func setBaseURL(_ value: String) {
        guard let data = try? JSONEncoder().encode(Configuration(baseURL: value)) else {
            return
        }
        try? data.write(to: configurationURL, options: .atomic)
    }

    var baseURL: URL? {
        guard let data = try? Data(contentsOf: configurationURL),
              let configuration = try? JSONDecoder().decode(Configuration.self, from: data) else {
            return nil
        }
        return URL(string: configuration.baseURL)
    }
}

enum AudelWidgetStore {
    private static let fileStore: AudelWidgetFileStore? = {
        guard let directoryURL = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: AudelWidgetConstants.appGroupIdentifier
        ) else {
            return nil
        }
        return AudelWidgetFileStore(directoryURL: directoryURL)
    }()

    private static let writeQueue = DispatchQueue(
        label: "com.audel.widget-store",
        qos: .utility
    )

    static func load() -> AudelWidgetSnapshot {
        fileStore?.loadSnapshot() ?? .empty
    }

    static func save(_ snapshot: AudelWidgetSnapshot, reloadTimelines: Bool = true) {
        fileStore?.saveSnapshot(snapshot)
        if reloadTimelines {
            WidgetCenter.shared.reloadTimelines(ofKind: AudelWidgetConstants.todayWidgetKind)
        }
    }

    static func saveInBackground(
        _ snapshot: AudelWidgetSnapshot,
        reloadTimelines: Bool = true
    ) {
        writeQueue.async {
            save(snapshot, reloadTimelines: reloadTimelines)
        }
    }

    static func replace(_ task: AudelWidgetTask) {
        var snapshot = load()
        if let index = snapshot.tasks.firstIndex(where: { $0.id == task.id }) {
            snapshot.tasks[index] = task
        } else {
            snapshot.tasks.append(task)
        }
        save(AudelWidgetSnapshot(generatedAt: Date(), tasks: snapshot.tasks))
    }

    static func setBaseURL(_ value: String) {
        fileStore?.setBaseURL(value)
    }

    static var baseURL: URL? {
        fileStore?.baseURL
    }
}

enum AudelWidgetRuntime {
    private static let bootstrapQueue = DispatchQueue(
        label: "com.audel.widget-bootstrap",
        qos: .utility
    )

    /// Copies Xcode's development configuration into stores shared with the
    /// extension. The backend credential remains in a shared Keychain access
    /// group; it is never written into widget preferences or timeline data.
    static func bootstrapFromEnvironment() {
        let environment = ProcessInfo.processInfo.environment
        let baseURL = normalizedBaseURL(environment["API_BASE_URL"])
        let apiKey = clean(environment["APP_API_KEY"])
        guard baseURL != nil || apiKey != nil else { return }

        bootstrapQueue.async {
            if let baseURL {
                AudelWidgetStore.setBaseURL(baseURL.absoluteString)
            }
            if let apiKey {
                AudelWidgetCredentialStore.save(apiKey)
            }
        }
    }

    private static func normalizedBaseURL(_ value: String?) -> URL? {
        guard let value = clean(value),
              var components = URLComponents(string: value) else {
            return nil
        }
        if components.path.isEmpty || components.path == "/" {
            components.path = "/api"
        }
        return components.url
    }

    private static func clean(_ value: String?) -> String? {
        guard let value = value?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else {
            return nil
        }
        return value
    }
}

private enum AudelWidgetCredentialStore {
    private static var accessGroup: String? {
        guard let prefix = Bundle.main.object(
            forInfoDictionaryKey: "AppIdentifierPrefix"
        ) as? String,
              !prefix.isEmpty,
              !prefix.contains("$") else {
            return nil
        }
        return "\(prefix)calebshim.goals-app.shared"
    }

    static func save(_ value: String) {
        var query = baseQuery
        let attributes: [String: Any] = [
            kSecValueData as String: Data(value.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        if SecItemUpdate(query as CFDictionary, attributes as CFDictionary) == errSecItemNotFound {
            attributes.forEach { query[$0.key] = $0.value }
            SecItemAdd(query as CFDictionary, nil)
        }
    }

    static func load() -> String? {
        var query = baseQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    private static var baseQuery: [String: Any] {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: AudelWidgetConstants.keychainService,
            kSecAttrAccount as String: AudelWidgetConstants.keychainAccount,
        ]
        if let accessGroup {
            query[kSecAttrAccessGroup as String] = accessGroup
        }
        return query
    }
}

enum AudelWidgetDate {
    static var today: String {
        let components = Calendar.current.dateComponents([.year, .month, .day], from: Date())
        return String(
            format: "%04d-%02d-%02d",
            components.year ?? 0,
            components.month ?? 0,
            components.day ?? 0
        )
    }
}

enum AudelDeepLink {
    static func tab(for url: URL) -> String? {
        guard url.scheme?.lowercased() == "audel" else { return nil }
        switch url.host?.lowercased() {
        case "assistant", "audel":
            return "audel"
        case "schedule":
            return "routines"
        case "goals":
            return "goals"
        case "finances":
            return "finances"
        case "dashboard":
            return "dashboard"
        default:
            return nil
        }
    }
}

enum AudelWidgetAPI {
    private struct RemoteScheduleItem: Decodable {
        let id: String
        let source: String
        let sourceID: Int
        let title: String
        let scheduledFor: String
        let reminderTime: String?
        let completed: Bool
        let missed: Bool

        var widgetTask: AudelWidgetTask {
            AudelWidgetTask(
                id: id,
                source: source,
                sourceID: sourceID,
                title: title,
                scheduledFor: scheduledFor,
                reminderTime: reminderTime,
                completed: completed,
                missed: missed
            )
        }
    }

    static func refreshToday() async throws -> AudelWidgetSnapshot {
        let today = AudelWidgetDate.today
        let tasks: [RemoteScheduleItem] = try await request(
            "schedule",
            query: [
                URLQueryItem(name: "start", value: today),
                URLQueryItem(name: "end", value: today),
            ]
        )
        let snapshot = AudelWidgetSnapshot(
            generatedAt: Date(),
            tasks: tasks.map(\.widgetTask)
        )
        AudelWidgetStore.save(snapshot, reloadTimelines: false)
        return snapshot
    }

    static func setCompleted(
        source: String,
        sourceID: Int,
        scheduledFor: String,
        completed: Bool
    ) async throws {
        switch source {
        case "routine":
            try await requestWithoutResponse(
                "goals/\(sourceID)/checkin",
                method: "PATCH",
                body: [
                    "scheduled_for": scheduledFor,
                    "completed": completed,
                    "allow_overdue": scheduledFor < AudelWidgetDate.today,
                ]
            )
        case "reminder":
            try await requestWithoutResponse(
                "reminders/\(sourceID)",
                method: "PATCH",
                body: ["completed": completed]
            )
        default:
            throw AudelWidgetError.notActionable
        }
    }

    private static func request<T: Decodable>(
        _ path: String,
        method: String = "GET",
        query: [URLQueryItem] = []
    ) async throws -> T {
        let request = try makeRequest(path, method: method, query: query, body: nil)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response, data: data)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: data)
    }

    private static func requestWithoutResponse(
        _ path: String,
        method: String,
        body: [String: Any]
    ) async throws {
        let data = try JSONSerialization.data(withJSONObject: body)
        let request = try makeRequest(path, method: method, body: data)
        let (responseData, response) = try await URLSession.shared.data(for: request)
        try validate(response, data: responseData)
    }

    private static func makeRequest(
        _ path: String,
        method: String,
        query: [URLQueryItem] = [],
        body: Data?
    ) throws -> URLRequest {
        guard let baseURL = AudelWidgetStore.baseURL,
              var components = URLComponents(
                url: baseURL.appendingPathComponent(path),
                resolvingAgainstBaseURL: false
              ) else {
            throw AudelWidgetError.openAppToConfigure
        }
        if !query.isEmpty {
            components.queryItems = query
        }
        guard let url = components.url else {
            throw AudelWidgetError.invalidResponse
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let apiKey = AudelWidgetCredentialStore.load() {
            request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private static func validate(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw AudelWidgetError.invalidResponse
        }
        guard 200..<300 ~= http.statusCode else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw AudelWidgetError.server(detail ?? "Request failed (\(http.statusCode)).")
        }
    }
}

enum AudelWidgetError: Error, CustomLocalizedStringResourceConvertible {
    case invalidResponse
    case notActionable
    case openAppToConfigure
    case server(String)

    var localizedStringResource: LocalizedStringResource {
        switch self {
        case .invalidResponse:
            return "Audel received an invalid response."
        case .notActionable:
            return "This schedule item cannot be completed."
        case .openAppToConfigure:
            return "Open Audel once to configure the widget."
        case .server(let message):
            return LocalizedStringResource(stringLiteral: message)
        }
    }
}

@available(iOS 17.0, *)
struct SetScheduleItemCompletionIntent: AppIntent {
    static let title: LocalizedStringResource = "Update Schedule Item"
    static let description = IntentDescription("Marks an Audel routine or reminder complete.")
    static let isDiscoverable = false

    @Parameter(title: "Item ID")
    var itemID: String

    @Parameter(title: "Source")
    var source: String

    @Parameter(title: "Source ID")
    var sourceID: Int

    @Parameter(title: "Title")
    var itemTitle: String

    @Parameter(title: "Date")
    var scheduledFor: String

    @Parameter(title: "Completed")
    var completed: Bool

    init() {}

    init(task: AudelWidgetTask, completed: Bool) {
        itemID = task.id
        source = task.source
        sourceID = task.sourceID
        itemTitle = task.title
        scheduledFor = task.scheduledFor
        self.completed = completed
    }

    func perform() async throws -> some IntentResult {
        try await AudelWidgetAPI.setCompleted(
            source: source,
            sourceID: sourceID,
            scheduledFor: scheduledFor,
            completed: completed
        )
        var task = AudelWidgetStore.load().tasks.first(where: { $0.id == itemID })
            ?? AudelWidgetTask(
                id: itemID,
                source: source,
                sourceID: sourceID,
                title: itemTitle,
                scheduledFor: scheduledFor,
                reminderTime: nil,
                completed: completed,
                missed: false
            )
        task.completed = completed
        task.missed = scheduledFor < AudelWidgetDate.today && !completed
        AudelWidgetStore.replace(task)
        return .result()
    }
}

@available(iOS 17.0, *)
struct CompleteNextRoutineIntent: AppIntent {
    static let title: LocalizedStringResource = "Complete Next Routine"
    static let description = IntentDescription("Completes the next unfinished routine due today.")

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let snapshot = try await AudelWidgetAPI.refreshToday()
        guard let task = snapshot.tasks(for: .remaining).first(where: {
            $0.source == "routine" && !$0.completed
        }) else {
            return .result(dialog: "You have no unfinished routines due today.")
        }
        try await AudelWidgetAPI.setCompleted(
            source: task.source,
            sourceID: task.sourceID,
            scheduledFor: task.scheduledFor,
            completed: true
        )
        var completedTask = task
        completedTask.completed = true
        completedTask.missed = false
        AudelWidgetStore.replace(completedTask)
        return .result(dialog: "Completed \(task.title).")
    }
}

@available(iOS 17.0, *)
struct RefreshAudelWidgetIntent: AppIntent {
    static let title: LocalizedStringResource = "Refresh Audel"
    static let description = IntentDescription("Refreshes today's Audel schedule.")

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let snapshot = try await AudelWidgetAPI.refreshToday()
        WidgetCenter.shared.reloadTimelines(ofKind: AudelWidgetConstants.todayWidgetKind)
        return .result(dialog: "Audel refreshed \(snapshot.tasks.count) items for today.")
    }
}

struct OpenAudelIntent: AppIntent {
    static let title: LocalizedStringResource = "Open Audel"
    static let description = IntentDescription("Opens your Audel conversation.")
    static let openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        UserDefaults.standard.set("audel", forKey: AudelWidgetConstants.selectedTabKey)
        return .result()
    }
}

struct OpenAudelScheduleIntent: AppIntent {
    static let title: LocalizedStringResource = "Open Schedule"
    static let description = IntentDescription("Opens today's Audel schedule.")
    static let openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        UserDefaults.standard.set("routines", forKey: AudelWidgetConstants.selectedTabKey)
        return .result()
    }
}

@available(iOS 17.0, *)
struct AudelAppShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: OpenAudelIntent(),
            phrases: [
                "Open \(.applicationName)",
                "Talk to \(.applicationName)",
            ],
            shortTitle: "Open Audel",
            systemImageName: "sparkles"
        )
        AppShortcut(
            intent: OpenAudelScheduleIntent(),
            phrases: [
                "Show my \(.applicationName) schedule",
                "What's on my \(.applicationName) schedule",
            ],
            shortTitle: "Open Schedule",
            systemImageName: "calendar"
        )
        AppShortcut(
            intent: CompleteNextRoutineIntent(),
            phrases: [
                "Complete my next \(.applicationName) routine",
                "Finish my next routine in \(.applicationName)",
            ],
            shortTitle: "Complete Routine",
            systemImageName: "checkmark.circle"
        )
        AppShortcut(
            intent: RefreshAudelWidgetIntent(),
            phrases: [
                "Refresh \(.applicationName)",
            ],
            shortTitle: "Refresh Audel",
            systemImageName: "arrow.clockwise"
        )
    }

    static let shortcutTileColor: ShortcutTileColor = .teal
}
