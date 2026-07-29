import SwiftUI
import UIKit
import PhotosUI
import Charts
import LinkKit
import Security

// MARK: - API models

struct Account: Codable, Identifiable {
    let id, itemId: Int
    let plaidAccountId, name: String
    let persistentAccountId: String?
    let officialName: String?
    let type: String
    let subtype, mask: String?
    let currentBalance, availableBalance: Double?
    let currency: String
}

struct Transaction: Codable, Identifiable {
    let id, accountId: Int
    let date, name: String
    let merchantName: String?
    let amount: Double
    let category, userCategory: String?
    let effectiveCategory: String
    let pending, isManual: Bool
    let reimbursesTransactionId: Int?
    let reimbursementCategory: String?
    let isBudgeted: Bool?
}
extension Transaction {
    private var isPeerPaymentName: Bool {
        name.range(of: "zelle|venmo", options: [.regularExpression, .caseInsensitive]) != nil
    }
    var isIncomingPeerPayment: Bool {
        category == "TRANSFER_IN" && amount < 0 && isPeerPaymentName
    }
    var isOutgoingPeerPayment: Bool {
        category == "TRANSFER_OUT" && amount > 0 && isPeerPaymentName
    }
    var needsPeerPaymentReview: Bool {
        if isIncomingPeerPayment { return userCategory == nil && reimbursesTransactionId == nil }
        if isOutgoingPeerPayment { return userCategory == nil }
        return false
    }
}

struct Budget: Codable, Identifiable { let id: Int; let category: String; let monthlyLimit: Double; let period: String }
struct BudgetProgress: Codable, Identifiable {
    var id: String { "\(category):\(period)" }
    let budgetId: Int; let category, period, windowStart, windowEnd: String
    let limit, spent, remaining, pct: Double
}
struct SpendingCategory: Codable, Identifiable { var id: String { category }; let category: String; let total: Double }
struct MonthlyTrend: Codable, Identifiable { var id: String { month }; let month: String; let income, expense: Double }
struct Summary: Codable {
    let spendingByCategory: [SpendingCategory]
    let incomeTotal, expenseTotal, net: Double
    let monthlyTrend: [MonthlyTrend]
    let budgetProgress: [BudgetProgress]
    let completeMonths: [String]
}
struct HistoryPoint: Codable, Identifiable { var id: String { at }; let value: Double; let at: String }
struct Goal: Codable, Identifiable {
    let id: Int; let name, kind, period, direction: String; let step: Double
    let target: Double?; let accountId: Int?; let category: String?; let current, anchorValue: Double?
    let accountIds: [Int]?; let financialMetric, financialRule, financialSource: String?
    let since, deadline, group, weeklyDay, reminderTime: String?; let weeklyDays: [String]
    let repeatUntilCompleted: Bool; let nudgeIntervalMinutes: Int?
    let resetTime, weeklyResetDay: String; let monthlyResetDay: Int; let intervalDays: Int?
    let currentValue: Double; let pct: Double?; let status, unit: String; let linkedLabel: String?
    let days, bestDays, weeklyStreak: Int?; let history, milestones: [HistoryPoint]
    let archivedAt: String?
    let icon, color: String?
    let resolvedIcon, resolvedColor: String
    let groupIcon, groupColor: String?
}
struct GoalTask: Codable, Identifiable {
    var id: String { "\(goalId)-\(scheduledFor)" }
    let goalId: Int; let name, period, scheduledFor: String; let completed, missed: Bool
    let reminderTime: String?
}
struct Reminder: Codable, Identifiable {
    let id: Int
    let title, scheduledFor: String
    let reminderTime, notes: String?
    let completed: Bool
    let repeatUntilCompleted: Bool
    let nudgeIntervalMinutes: Int?
    let createdAt: String
}
struct CalendarEvent: Codable, Identifiable {
    let id: Int
    let title, scheduledFor: String
    let startTime, endTime, location, notes: String?
    let createdAt: String
}
struct ScheduleItem: Codable, Identifiable {
    let id, source: String
    let sourceId: Int
    let title, scheduledFor: String
    let reminderTime: String?
    var completed, missed: Bool
    let notes, period: String?
    let repeatUntilCompleted: Bool
    let nudgeIntervalMinutes: Int?
    let endTime, location: String?
}
struct Position: Codable, Identifiable {
    var id: String { symbol }
    let symbol, underlyingSymbol, instrumentType: String; let quantity: Double
    let averageOpenPrice: Double?; let price, multiplier, marketValue: Double; let expiresAt: String?
}
struct PortfolioAccount: Codable, Identifiable {
    var id: String { accountNumber }
    let accountNumber: String; let nickname: String?; let type: String
    let netLiquidatingValue, cashBalance, equityBuyingPower, derivativeBuyingPower, maintenanceExcess: Double?
    let positions: [Position]
}
struct Portfolio: Codable { let environment: String; let accounts: [PortfolioAccount] }
struct ChatMessage: Codable, Identifiable {
    var id = UUID()
    let role, content: String
    var attachmentIds: [String]? = nil
    var actions: [String]? = nil
    enum CodingKeys: String, CodingKey { case role, content, attachmentIds }
}
struct MediaAsset: Codable, Identifiable {
    let id, filename, mediaType: String
    let byteSize, width, height: Int
    let sha256, createdAt: String
}
struct DashboardAction: Codable { let type: String; let widgetIds: [String]? }
struct ChatResponse: Codable { let reply: String; let actions: [String]; let refresh: Bool; let uiActions: [DashboardAction]? }
struct AgentJob: Codable, Identifiable {
    let id, kind, status, stage: String
    let total, completed: Int
    let message: String?
    let categorized, remaining: Int?
    let error: String?
}
struct EmptyResponse: Codable {}
struct LinkTokenResponse: Codable { let linkToken: String }
struct ExchangeResponse: Codable { let itemId: String; let accounts: Int }
struct BankRefreshResponse: Codable {
    let requested: Int
    let accepted: Int
    let temporarilyUnavailable: Int
}

// MARK: - Networking

enum APIError: LocalizedError {
    case invalidResponse, server(String)
    var errorDescription: String? {
        switch self { case .invalidResponse: return "The server returned an invalid response."; case .server(let value): return value }
    }
}

private struct APIRuntimeConfiguration {
    let baseURL: URL
    let apiKey: String?

    private static let defaultBaseURL = URL(string: "http://127.0.0.1:8100/api")!
    private static let savedBaseURLKey = "debug.apiBaseURL"

    static func load() -> APIRuntimeConfiguration {
        let environment = ProcessInfo.processInfo.environment
        let environmentURL = clean(environment["API_BASE_URL"])
        let environmentKey = clean(environment["APP_API_KEY"])

#if DEBUG
        if let environmentURL {
            UserDefaults.standard.set(environmentURL, forKey: savedBaseURLKey)
        }
        if let environmentKey {
            DevelopmentAPIKeyStore.save(environmentKey)
        }
        let urlValue = environmentURL
            ?? clean(UserDefaults.standard.string(forKey: savedBaseURLKey))
        let keyValue = environmentKey ?? DevelopmentAPIKeyStore.load()
#else
        let urlValue = environmentURL
        let keyValue = environmentKey
#endif

        return APIRuntimeConfiguration(
            baseURL: normalizedBaseURL(urlValue) ?? defaultBaseURL,
            apiKey: keyValue
        )
    }

    private static func clean(_ value: String?) -> String? {
        guard let value = value?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else {
            return nil
        }
        return value
    }

    private static func normalizedBaseURL(_ value: String?) -> URL? {
        guard let value, var components = URLComponents(string: value) else {
            return nil
        }
        if components.path.isEmpty || components.path == "/" {
            components.path = "/api"
        }
        return components.url
    }
}

private enum DevelopmentAPIKeyStore {
    private static let service = "calebshim.goals-app.debug-api"
    private static let account = "bearer-token"

    static func save(_ value: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        let attributes: [String: Any] = [
            kSecValueData as String: Data(value.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        if SecItemUpdate(query as CFDictionary, attributes as CFDictionary) == errSecItemNotFound {
            var item = query
            attributes.forEach { item[$0.key] = $0.value }
            SecItemAdd(item as CFDictionary, nil)
        }
    }

    static func load() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }
}

actor APIClient {
    static let shared = APIClient()
    private let baseURL: URL
    private let apiKey: String?
    private let decoder: JSONDecoder = { let value = JSONDecoder(); value.keyDecodingStrategy = .convertFromSnakeCase; return value }()
    private let encoder: JSONEncoder = { let value = JSONEncoder(); value.keyEncodingStrategy = .convertToSnakeCase; return value }()

    private init() {
        let configuration = APIRuntimeConfiguration.load()
        baseURL = configuration.baseURL
        apiKey = configuration.apiKey
    }

    func request<T: Decodable>(_ path: String, method: String = "GET", query: [URLQueryItem] = [], body: AnyEncodable? = nil) async throws -> T {
        var components = URLComponents(url: baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query }
        var request = URLRequest(url: components.url!)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let apiKey {
            request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        }
        if let body { request.httpBody = try encoder.encode(body) }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard 200..<300 ~= http.statusCode else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw APIError.server(detail ?? "Request failed (\(http.statusCode)).")
        }
        if T.self == EmptyResponse.self { return EmptyResponse() as! T }
        return try decoder.decode(T.self, from: data)
    }

    func uploadImage(_ data: Data, filename: String) async throws -> MediaAsset {
        var request = URLRequest(url: baseURL.appendingPathComponent("media"))
        request.httpMethod = "POST"
        request.httpBody = data
        request.setValue("image/jpeg", forHTTPHeaderField: "Content-Type")
        let safeName = filename.unicodeScalars.map {
            (32...126).contains($0.value) ? Character(String($0)) : "_"
        }
        request.setValue(String(safeName), forHTTPHeaderField: "X-Filename")
        if let apiKey {
            request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        }
        let (responseData, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        guard 200..<300 ~= http.statusCode else {
            let detail = (
                try? JSONSerialization.jsonObject(with: responseData)
                    as? [String: Any]
            )?["detail"] as? String
            throw APIError.server(
                detail ?? "Image upload failed (\(http.statusCode))."
            )
        }
        return try decoder.decode(MediaAsset.self, from: responseData)
    }
}

struct AnyEncodable: Encodable {
    private let encodeValue: (Encoder) throws -> Void
    init<T: Encodable>(_ value: T) { encodeValue = value.encode }
    func encode(to encoder: Encoder) throws { try encodeValue(encoder) }
}
struct ManualTransaction: Encodable { let accountId: Int; let date, name: String; let amount: Double }
struct ManualTransactionUpdateBody: Encodable {
    let accountId: Int
    let date, name: String
    let amount: Double
}
struct TransactionCategoryBody: Encodable { let userCategory: String? }
struct ReimbursementUpdateBody: Encodable { let targetId: Int? }
struct BulkTransactionCategoryBody: Encodable {
    let transactionIds: [Int]
    let userCategory: String
}
struct BulkReimbursementBody: Encodable {
    let transactionIds: [Int]
    let targetId: Int
}
struct NewBudget: Encodable { let category: String; let monthlyLimit: Double; let period: String }
struct BudgetUpdateBody: Encodable {
    let category: String
    let monthlyLimit: Double
    let period: String
}
struct GoalProgressBody: Encodable { let current: Double?; let add: Double? }
struct GoalTargetBody: Encodable { let target: Double }
struct GoalNameBody: Encodable { let name: String }
struct NewGoalBody: Encodable {
    let name, kind, period, direction: String
    let target, current: Double?
    let step: Double
    let group, category: String?
    let weeklyDays: [String]?
    let reminderTime: String?
    let repeatUntilCompleted: Bool
    let nudgeIntervalMinutes: Int?
    let accountIds: [Int]?
    let financialMetric, financialRule, financialSource: String?
}
struct RoutineScheduleBody: Encodable {
    let weeklyDays: [String]
    let weeklyResetDay: String
    let reminderTime: String?
    let repeatUntilCompleted: Bool
    let nudgeIntervalMinutes: Int?
    enum CodingKeys: String, CodingKey {
        case weeklyDays, weeklyResetDay, reminderTime, repeatUntilCompleted, nudgeIntervalMinutes
    }
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(weeklyDays, forKey: .weeklyDays)
        try container.encode(weeklyResetDay, forKey: .weeklyResetDay)
        if let reminderTime {
            try container.encode(reminderTime, forKey: .reminderTime)
        } else {
            try container.encodeNil(forKey: .reminderTime)
        }
        try container.encode(repeatUntilCompleted, forKey: .repeatUntilCompleted)
        try container.encodeIfPresent(nudgeIntervalMinutes, forKey: .nudgeIntervalMinutes)
    }
}
struct GoalGroupUpdateBody: Encodable { let goalIds: [Int]; let name: String }
struct GoalGroupEndBody: Encodable { let goalIds: [Int] }
struct GoalAppearanceBody: Encodable {
    let icon: String?
    let color: String?
    enum CodingKeys: String, CodingKey { case icon, color }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        if let icon { try c.encode(icon, forKey: .icon) } else { try c.encodeNil(forKey: .icon) }
        if let color { try c.encode(color, forKey: .color) } else { try c.encodeNil(forKey: .color) }
    }
}

struct GroupAppearanceBody: Encodable {
    let icon: String?
    let color: String?
    enum CodingKeys: String, CodingKey { case icon, color }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        if let icon { try c.encode(icon, forKey: .icon) } else { try c.encodeNil(forKey: .icon) }
        if let color { try c.encode(color, forKey: .color) } else { try c.encodeNil(forKey: .color) }
    }
}

struct GroupSettings: Codable { let name: String; let icon, color: String? }
struct CheckinBody: Encodable { let scheduledFor: String; let completed, allowOverdue: Bool }
struct ReminderCreateBody: Encodable {
    let title, scheduledFor: String
    let reminderTime, notes: String?
    let repeatUntilCompleted: Bool
    let nudgeIntervalMinutes: Int?
}
struct ReminderUpdateBody: Encodable {
    let title, scheduledFor: String
    let reminderTime, notes: String?
    let repeatUntilCompleted: Bool
    let nudgeIntervalMinutes: Int?

    enum CodingKeys: String, CodingKey {
        case title, scheduledFor, reminderTime, notes
        case repeatUntilCompleted, nudgeIntervalMinutes
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(title, forKey: .title)
        try container.encode(scheduledFor, forKey: .scheduledFor)
        try container.encode(reminderTime, forKey: .reminderTime)
        try container.encode(notes, forKey: .notes)
        try container.encode(repeatUntilCompleted, forKey: .repeatUntilCompleted)
        try container.encode(nudgeIntervalMinutes, forKey: .nudgeIntervalMinutes)
    }
}
struct ReminderCompletionBody: Encodable { let completed: Bool }
struct ReminderSnoozeBody: Encodable {
    let scheduledFor, reminderTime: String
}
struct CalendarEventCreateBody: Encodable {
    let title, scheduledFor: String
    let startTime, endTime, location, notes: String?
}
struct CalendarEventUpdateBody: Encodable {
    let title, scheduledFor: String
    let startTime, endTime, location, notes: String?

    enum CodingKeys: String, CodingKey {
        case title, scheduledFor, startTime, endTime, location, notes
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(title, forKey: .title)
        try container.encode(scheduledFor, forKey: .scheduledFor)
        try container.encode(startTime, forKey: .startTime)
        try container.encode(endTime, forKey: .endTime)
        try container.encode(location, forKey: .location)
        try container.encode(notes, forKey: .notes)
    }
}
struct ChatBody: Encodable {
    let messages: [ChatMessage]
    let timezone: String
}
struct CategorizeUnbudgetedJobBody: Encodable {
    let month, timezone, idempotencyKey: String
}

// MARK: - App state

@MainActor final class MoneyStore: ObservableObject {
    @Published var accounts: [Account] = []; @Published var transactions: [Transaction] = []
    @Published var budgets: [Budget] = []; @Published var summary: Summary?
    @Published var goals: [Goal] = []
    @Published var archivedGoals: [Goal] = []
    @Published var todayRoutineTasks: [GoalTask] = []
    @Published var weekRoutineTasks: [GoalTask] = []
    @Published var scheduleItems: [ScheduleItem] = []
    @Published var focusedWidgetId: String?
    @Published var goalCelebration: Goal?
    @Published var portfolio: Portfolio?
    @Published var messages: [ChatMessage] = ChatStorage.load() { didSet { ChatStorage.save(messages) } }
    @Published var loading = false; @Published var error: String?
    @Published var bankRefreshNotice: String?
    @Published private(set) var financeRefreshInFlight = false
    @Published private(set) var copilotRequestInFlight = false
    @Published private(set) var activeAgentJob: AgentJob?
    private let api = APIClient.shared
    private var hasLoadedGoals = false
    private var hasLoadedRoutineTasks = false
    private var routineTasksLoading = false
    private var financeRefreshTask: Task<Void, Never>?
    private var consumedAgentShortcutIds: Set<UUID> = []
    private var agentJobPollingTask: Task<Void, Never>?
    private var pollingAgentJobId: String?
    private static let activeAgentJobKey = "money.copilot.active-job-id"
    var hasLinkedBank: Bool { accounts.contains { $0.plaidAccountId != "manual-local" } }

    func loadAll() async {
        loading = true; defer { loading = false }
        async let a: Void = loadAccounts(); async let t: Void = loadTransactions(); async let s: Void = loadSummary()
        async let g: Void = loadGoals(); async let p: Void = loadPortfolio()
        let month = Date().monthGridRange
        async let c: Void = loadSchedule(
            from: month.start, through: month.end, requestNotificationPermission: true
        )
        _ = await (a, t, s, g, p, c)
    }
    func loadOnLaunch() async {
        resumeAgentJobIfNeeded()
        await loadAll()
        if hasLinkedBank { await sync(silent: true) }
    }
    func loadFinances() async {
        async let accounts: Void = loadAccounts()
        async let transactions: Void = loadTransactions()
        async let summary: Void = loadSummary()
        async let goals: Void = loadGoals()
        _ = await (accounts, transactions, summary, goals)
    }
    func loadAccounts() async { do { accounts = try await api.request("accounts") } catch { show(error) } }
    func loadTransactions() async { do { transactions = try await api.request("transactions") } catch { show(error) } }
    func loadSummary() async {
        do {
            summary = try await api.request("dashboard/summary", query: [.init(name: "month", value: Self.currentMonth)])
            budgets = try await api.request("budgets")
        } catch { show(error) }
    }
    func loadGoals() async {
        do {
            let loaded: [Goal] = try await api.request("goals")
            if hasLoadedGoals {
                detectCompletion(from: goals, to: loaded)
            }
            goals = loaded
            hasLoadedGoals = true
        } catch { show(error) }
    }
    func loadArchivedGoals() async {
        do {
            archivedGoals = try await api.request(
                "goals", query: [.init(name: "archived", value: "true")]
            )
        } catch { show(error) }
    }
    func loadTodayRoutineTasks(force: Bool = false) async {
        guard force || !hasLoadedRoutineTasks else { return }
        guard !routineTasksLoading else { return }
        routineTasksLoading = true
        defer { routineTasksLoading = false }
        do {
            async let dayTasks: [GoalTask] = api.request(
                "goal-tasks", query: [.init(name: "scope", value: "day")]
            )
            async let weekTasks: [GoalTask] = api.request(
                "goal-tasks", query: [.init(name: "scope", value: "week")]
            )
            async let monthTasks: [GoalTask] = api.request(
                "goal-tasks", query: [.init(name: "scope", value: "month")]
            )
            let (day, week, month) = try await (dayTasks, weekTasks, monthTasks)
            weekRoutineTasks = week
            let today = Date().apiDate
            let dueToday = (day + week + month).filter { $0.scheduledFor == today }
            let unique = Dictionary(dueToday.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
            todayRoutineTasks = unique.values.sorted {
                let firstTime = $0.reminderTime ?? "99:99"
                let secondTime = $1.reminderTime ?? "99:99"
                if firstTime != secondTime { return firstTime < secondTime }
                return $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
            }
            hasLoadedRoutineTasks = true
        } catch { show(error) }
    }
    func loadPortfolio() async { do { portfolio = try await api.request("portfolio") } catch { /* Portfolio can be unconfigured. */ } }
    func loadSchedule(
        from start: String,
        through end: String,
        requestNotificationPermission: Bool = false
    ) async {
        do {
            let loaded: [ScheduleItem] = try await api.request(
                "schedule",
                query: [.init(name: "start", value: start), .init(name: "end", value: end)]
            )
            scheduleItems.removeAll { $0.scheduledFor >= start && $0.scheduledFor <= end }
            scheduleItems += loaded
            scheduleItems.sort {
                if $0.scheduledFor != $1.scheduledFor { return $0.scheduledFor < $1.scheduledFor }
                return ($0.reminderTime ?? "99:99") < ($1.reminderTime ?? "99:99")
            }
            publishTodayWidget()
            await ReminderNotificationScheduler.sync(
                loaded.filter { $0.source == "reminder" || $0.source == "routine" },
                requestAuthorization: requestNotificationPermission
            )
        } catch { show(error) }
    }
    @discardableResult
    func createReminder(
        title: String,
        date: String,
        time: String?,
        notes: String?,
        repeatUntilCompleted: Bool,
        nudgeIntervalMinutes: Int?
    ) async -> Reminder? {
        do {
            let reminder: Reminder = try await api.request(
                "reminders", method: "POST",
                body: .init(ReminderCreateBody(
                    title: title,
                    scheduledFor: date,
                    reminderTime: time,
                    notes: notes,
                    repeatUntilCompleted: repeatUntilCompleted,
                    nudgeIntervalMinutes: nudgeIntervalMinutes
                ))
            )
            await ReminderNotificationScheduler.schedule(reminder, requestAuthorization: time != nil)
            return reminder
        } catch {
            show(error)
            return nil
        }
    }
    func toggleScheduleItem(_ item: ScheduleItem) async {
        guard item.source != "goal_deadline" else { return }
        do {
            if item.source == "reminder" {
                let updated: Reminder = try await api.request(
                    "reminders/\(item.sourceId)", method: "PATCH",
                    body: .init(ReminderCompletionBody(completed: !item.completed))
                )
                updateScheduleItem(item.id, completed: updated.completed)
                await ReminderNotificationScheduler.schedule(updated, requestAuthorization: false)
            } else {
                let updated: GoalTask = try await api.request(
                    "goals/\(item.sourceId)/checkin", method: "PATCH",
                    body: .init(CheckinBody(
                        scheduledFor: item.scheduledFor,
                        completed: !item.completed,
                        allowOverdue: item.scheduledFor < Date().apiDate
                    ))
                )
                updateScheduleItem(item.id, completed: updated.completed)
                var notificationItem = item
                notificationItem.completed = updated.completed
                if updated.completed {
                    await ReminderNotificationScheduler.cancel(
                        source: item.source,
                        sourceId: item.sourceId,
                        scheduledFor: item.scheduledFor
                    )
                } else {
                    await ReminderNotificationScheduler.schedule(
                        notificationItem,
                        requestAuthorization: false
                    )
                }
                await loadGoals()
                await loadTodayRoutineTasks(force: true)
            }
        } catch { show(error) }
    }
    func snoozeReminder(_ item: ScheduleItem, minutes: Int? = nil) async {
        guard item.repeatUntilCompleted, !item.completed else { return }
        if item.source == "routine" {
            await ReminderNotificationScheduler.snooze(item, minutes: minutes)
            return
        }
        guard item.source == "reminder" else { return }
        let interval = max(minutes ?? item.nudgeIntervalMinutes ?? 60, 5)
        let next = Date().addingTimeInterval(TimeInterval(interval * 60))
        do {
            let updated: Reminder = try await api.request(
                "reminders/\(item.sourceId)", method: "PATCH",
                body: .init(ReminderSnoozeBody(
                    scheduledFor: next.apiDate,
                    reminderTime: next.apiTime
                ))
            )
            await ReminderNotificationScheduler.schedule(updated, requestAuthorization: false)
            await loadSchedule(
                from: min(item.scheduledFor, updated.scheduledFor),
                through: max(item.scheduledFor, updated.scheduledFor)
            )
        } catch { show(error) }
    }
    func deleteReminder(_ item: ScheduleItem) async {
        guard item.source == "reminder" else { return }
        do {
            let _: EmptyResponse = try await api.request(
                "reminders/\(item.sourceId)", method: "DELETE"
            )
            scheduleItems.removeAll { $0.id == item.id }
            await ReminderNotificationScheduler.cancel(reminderId: item.sourceId)
        } catch { show(error) }
    }
    @discardableResult
    func updateReminder(
        _ item: ScheduleItem,
        title: String,
        date: String,
        time: String?,
        notes: String?,
        repeatUntilCompleted: Bool,
        nudgeIntervalMinutes: Int?
    ) async -> Reminder? {
        guard item.source == "reminder" else { return nil }
        do {
            let updated: Reminder = try await api.request(
                "reminders/\(item.sourceId)",
                method: "PATCH",
                body: .init(ReminderUpdateBody(
                    title: title,
                    scheduledFor: date,
                    reminderTime: time,
                    notes: notes,
                    repeatUntilCompleted: repeatUntilCompleted,
                    nudgeIntervalMinutes: nudgeIntervalMinutes
                ))
            )
            await ReminderNotificationScheduler.cancel(reminderId: item.sourceId)
            await ReminderNotificationScheduler.schedule(updated, requestAuthorization: time != nil)
            await loadSchedule(
                from: min(item.scheduledFor, updated.scheduledFor),
                through: max(item.scheduledFor, updated.scheduledFor)
            )
            return updated
        } catch {
            show(error)
            return nil
        }
    }
    @discardableResult
    func createEvent(
        title: String,
        date: String,
        startTime: String?,
        endTime: String?,
        location: String?,
        notes: String?
    ) async -> CalendarEvent? {
        do {
            let event: CalendarEvent = try await api.request(
                "events", method: "POST",
                body: .init(CalendarEventCreateBody(
                    title: title,
                    scheduledFor: date,
                    startTime: startTime,
                    endTime: endTime,
                    location: location,
                    notes: notes
                ))
            )
            return event
        } catch {
            show(error)
            return nil
        }
    }
    func deleteEvent(_ item: ScheduleItem) async {
        guard item.source == "event" else { return }
        do {
            let _: EmptyResponse = try await api.request(
                "events/\(item.sourceId)", method: "DELETE"
            )
            scheduleItems.removeAll { $0.id == item.id }
        } catch { show(error) }
    }
    @discardableResult
    func updateEvent(
        _ item: ScheduleItem,
        title: String,
        date: String,
        startTime: String?,
        endTime: String?,
        location: String?,
        notes: String?
    ) async -> CalendarEvent? {
        guard item.source == "event" else { return nil }
        do {
            let updated: CalendarEvent = try await api.request(
                "events/\(item.sourceId)",
                method: "PATCH",
                body: .init(CalendarEventUpdateBody(
                    title: title,
                    scheduledFor: date,
                    startTime: startTime,
                    endTime: endTime,
                    location: location,
                    notes: notes
                ))
            )
            await loadSchedule(
                from: min(item.scheduledFor, updated.scheduledFor),
                through: max(item.scheduledFor, updated.scheduledFor)
            )
            return updated
        } catch {
            show(error)
            return nil
        }
    }
    private func updateScheduleItem(_ id: String, completed: Bool) {
        guard let index = scheduleItems.firstIndex(where: { $0.id == id }) else { return }
        scheduleItems[index].completed = completed
        scheduleItems[index].missed = scheduleItems[index].scheduledFor < Date().apiDate && !completed
        publishTodayWidget()
    }
    private func publishTodayWidget() {
        let today = Date().apiDate
        let tasks = scheduleItems
            .filter { $0.scheduledFor == today }
            .map {
                AudelWidgetTask(
                    id: $0.id,
                    source: $0.source,
                    sourceID: $0.sourceId,
                    title: $0.title,
                    scheduledFor: $0.scheduledFor,
                    reminderTime: $0.reminderTime,
                    completed: $0.completed,
                    missed: $0.missed
                )
            }
        AudelWidgetStore.save(
            AudelWidgetSnapshot(generatedAt: Date(), tasks: tasks)
        )
    }
    func ensureManualAccount() async throws -> Account {
        let account: Account = try await api.request("accounts/manual", method: "POST")
        if !accounts.contains(where: { $0.id == account.id }) { accounts.append(account) }
        return account
    }
    func createBankLinkToken(itemId: Int? = nil) async throws -> String {
        let query = itemId.map { [URLQueryItem(name: "item_id", value: String($0))] } ?? []
        let response: LinkTokenResponse = try await api.request(
            "plaid/link-token", method: "POST", query: query
        )
        return response.linkToken
    }
    func finishBankLink(publicToken: String, updateMode: Bool = false) async throws {
        if updateMode {
            await sync()
            return
        }
        let _: ExchangeResponse = try await api.request(
            "plaid/exchange", method: "POST",
            body: .init(["public_token": publicToken])
        )
        await loadAll()
    }
    func sync(silent: Bool = false) async {
        do {
            try await requestPlaidSync()
            await loadFinances()
        } catch {
            if !silent { show(error) }
        }
    }

    func refreshFinances(silent: Bool = false) async {
        if let financeRefreshTask {
            await financeRefreshTask.value
            return
        }
        financeRefreshInFlight = true
        let task = Task { [weak self] in
            guard let self else { return }
            await self.performFinanceRefresh(silent: silent)
        }
        financeRefreshTask = task
        await task.value
        financeRefreshTask = nil
        financeRefreshInFlight = false
    }

    private func performFinanceRefresh(silent: Bool) async {
        bankRefreshNotice = nil
        guard hasLinkedBank else {
            await loadFinances()
            return
        }

        var response: BankRefreshResponse?
        var refreshError: Error?
        var syncError: Error?
        do {
            response = try await api.request("plaid/refresh", method: "POST")
            if response?.accepted ?? 0 > 0 {
                try? await Task.sleep(nanoseconds: 8_000_000_000)
            }
        } catch {
            refreshError = error
        }

        // Even when the institution rejects an on-demand pull, Plaid may have
        // cursor updates from its normal background refreshes ready to ingest.
        do {
            try await requestPlaidSync()
        } catch {
            syncError = error
        }
        await loadFinances()

        if let response, response.temporarilyUnavailable > 0 {
            bankRefreshNotice = response.temporarilyUnavailable == response.requested
                ? "Your bank is temporarily unavailable. Showing the latest available data."
                : "One bank is temporarily unavailable. Showing its latest available data."
        } else if let refreshError, !silent {
            show(refreshError)
        } else if let syncError, !silent {
            show(syncError)
        }
    }

    private func requestPlaidSync() async throws {
        let _: [String: Int] = try await api.request("plaid/sync", method: "POST")
    }
    func addTransaction(accountId: Int, date: Date, name: String, amount: Double) async {
        do {
            let resolvedAccountId = accountId == 0 ? try await ensureManualAccount().id : accountId
            let _: Transaction = try await api.request("transactions", method: "POST", body: .init(ManualTransaction(accountId: resolvedAccountId, date: date.apiDate, name: name, amount: amount)))
            await loadTransactions(); await loadSummary()
        } catch { show(error) }
    }
    @discardableResult
    func updateManualTransaction(
        _ transaction: Transaction,
        accountId: Int,
        date: Date,
        name: String,
        amount: Double
    ) async -> Bool {
        guard transaction.isManual else { return false }
        do {
            let resolvedAccountId = accountId == 0 ? try await ensureManualAccount().id : accountId
            let updated: Transaction = try await api.request(
                "transactions/\(transaction.id)",
                method: "PATCH",
                body: .init(ManualTransactionUpdateBody(
                    accountId: resolvedAccountId,
                    date: date.apiDate,
                    name: name,
                    amount: amount
                ))
            )
            replaceTransaction(updated)
            await loadSummary()
            return true
        } catch {
            show(error)
            return false
        }
    }
    func deleteTransaction(_ id: Int) async { do { let _: EmptyResponse = try await api.request("transactions/\(id)", method: "DELETE"); await loadTransactions() } catch { show(error) } }
    @discardableResult
    func updateTransactionCategory(_ id: Int, category: String) async -> Bool {
        let normalized = category.split(whereSeparator: \.isWhitespace).joined(separator: "_").uppercased()
        guard !normalized.isEmpty else { return false }
        do {
            let updated: Transaction = try await api.request(
                "transactions/\(id)", method: "PATCH",
                body: .init(TransactionCategoryBody(userCategory: normalized))
            )
            replaceTransaction(updated)
            await loadSummary()
            return true
        } catch {
            show(error)
            return false
        }
    }
    @discardableResult
    func bulkUpdateTransactionCategory(_ ids: [Int], category: String) async -> Bool {
        let normalized = category.split(whereSeparator: \.isWhitespace).joined(separator: "_").uppercased()
        guard !ids.isEmpty, !normalized.isEmpty else { return false }
        do {
            let updated: [Transaction] = try await api.request(
                "transactions/bulk-category", method: "PATCH",
                body: .init(BulkTransactionCategoryBody(
                    transactionIds: ids,
                    userCategory: normalized
                ))
            )
            updated.forEach(replaceTransaction)
            await loadSummary()
            return true
        } catch {
            show(error)
            return false
        }
    }
    @discardableResult
    func setReimbursement(_ id: Int, targetId: Int?) async -> Bool {
        do {
            let updated: Transaction = try await api.request(
                "transactions/\(id)/reimburses", method: "PATCH",
                body: .init(ReimbursementUpdateBody(targetId: targetId))
            )
            replaceTransaction(updated)
            await loadSummary()
            return true
        } catch {
            show(error)
            return false
        }
    }
    @discardableResult
    func bulkSetReimbursement(_ ids: [Int], targetId: Int) async -> Bool {
        guard !ids.isEmpty else { return false }
        do {
            let updated: [Transaction] = try await api.request(
                "transactions/bulk-reimburses", method: "PATCH",
                body: .init(BulkReimbursementBody(
                    transactionIds: ids,
                    targetId: targetId
                ))
            )
            updated.forEach(replaceTransaction)
            await loadSummary()
            return true
        } catch {
            show(error)
            return false
        }
    }
    private func replaceTransaction(_ updated: Transaction) {
        guard let index = transactions.firstIndex(where: { $0.id == updated.id }) else {
            transactions.append(updated)
            return
        }
        transactions[index] = updated
    }
    func setMerchantCategory(transactionId: Int, category: String) async {
        do {
            let _: [Transaction] = try await api.request(
                "transactions/\(transactionId)/merchant-category", method: "PATCH",
                body: .init(["category": category.uppercased()])
            )
            await loadTransactions(); await loadSummary()
        } catch { show(error) }
    }
    func addBudget(category: String, limit: Double, period: String = "monthly") async -> Bool {
        let normalized = category.split(whereSeparator: \.isWhitespace).joined(separator: "_").uppercased()
        guard !normalized.isEmpty, limit > 0 else { return false }
        do {
            let _: Budget = try await api.request(
                "budgets", method: "POST",
                body: .init(NewBudget(category: normalized, monthlyLimit: limit, period: period))
            )
            await loadSummary()
            return true
        } catch {
            show(error)
            return false
        }
    }
    func deleteBudget(_ id: Int) async { do { let _: EmptyResponse = try await api.request("budgets/\(id)", method: "DELETE"); await loadSummary() } catch { show(error) } }
    @discardableResult
    func updateBudget(_ budget: Budget, category: String, limit: Double, period: String) async -> Bool {
        let normalized = category.split(whereSeparator: \.isWhitespace).joined(separator: "_").uppercased()
        guard !normalized.isEmpty, limit > 0 else { return false }
        do {
            let _: Budget = try await api.request(
                "budgets/\(budget.id)",
                method: "PATCH",
                body: .init(BudgetUpdateBody(
                    category: normalized,
                    monthlyLimit: limit,
                    period: period
                ))
            )
            await loadSummary()
            return true
        } catch {
            show(error)
            return false
        }
    }
    func addGoal(name: String, kind: String, period: String, direction: String = "reach", target: Double?, current: Double?, step: Double, group: String?, category: String? = nil, weeklyDays: [String] = [], reminderTime: String? = nil, repeatUntilCompleted: Bool = false, nudgeIntervalMinutes: Int? = nil, accountIds: [Int] = [], financialMetric: String? = nil, financialRule: String? = nil, financialSource: String? = nil) async {
        do {
            let body = NewGoalBody(name: name, kind: kind, period: period, direction: direction, target: target, current: current, step: step, group: group, category: category, weeklyDays: period == "weekly" ? weeklyDays : nil, reminderTime: reminderTime, repeatUntilCompleted: repeatUntilCompleted, nudgeIntervalMinutes: repeatUntilCompleted ? nudgeIntervalMinutes : nil, accountIds: accountIds.isEmpty ? nil : accountIds, financialMetric: financialMetric, financialRule: financialRule, financialSource: financialSource)
            let created: Goal = try await api.request("goals", method: "POST", body: .init(body))
            goals.append(created)
            if created.period != "once" {
                await loadTodayRoutineTasks(force: true)
                if created.reminderTime != nil {
                    await loadSchedule(
                        from: Date().apiDate,
                        through: Date().apiDate,
                        requestNotificationPermission: true
                    )
                }
            }
        } catch { show(error) }
    }
    // MARK: Coalesced goal adjustments
    // One serial worker per goal turns a burst of taps into a single relative PATCH.
    // The absolute optimistic value keeps the UI correct even while the server's
    // response replaces the stored goal underneath it.
    @Published private(set) var optimisticGoalValues: [Int: Double] = [:]
    private var pendingGoalDeltas: [Int: Double] = [:]
    private var adjustmentGenerations: [Int: Int] = [:]
    private var adjustmentWorkers: [Int: Task<Void, Never>] = [:]
    private var exactGoalUpdates: Set<Int> = []

    func displayedValue(_ goal: Goal) -> Double { optimisticGoalValues[goal.id] ?? goal.currentValue }

    func displayedPct(_ goal: Goal) -> Double? {
        guard let target = goal.target, target != 0 else { return goal.pct }
        if goal.direction == "under" {
            guard let anchor = goal.anchorValue, anchor > target else { return goal.pct }
            return (max(0, (anchor - displayedValue(goal)) / (anchor - target) * 1000)).rounded() / 10
        }
        return (displayedValue(goal) / target * 1000).rounded() / 10
    }

    func queueAdjust(_ goal: Goal, by delta: Double) {
        let current = displayedValue(goal)
        let next = max(0, current + delta)
        let applied = next - current
        guard applied != 0 else { return }

        optimisticGoalValues[goal.id] = next
        pendingGoalDeltas[goal.id, default: 0] += applied
        adjustmentGenerations[goal.id, default: 0] += 1
        startAdjustmentWorkerIfNeeded(goalId: goal.id)
    }

    private func startAdjustmentWorkerIfNeeded(goalId: Int) {
        guard adjustmentWorkers[goalId] == nil, !exactGoalUpdates.contains(goalId) else { return }
        adjustmentWorkers[goalId] = Task { [weak self] in await self?.runAdjustmentWorker(goalId: goalId) }
    }

    private func runAdjustmentWorker(goalId: Int) async {
        while !Task.isCancelled {
            let generation = adjustmentGenerations[goalId, default: 0]
            try? await Task.sleep(nanoseconds: 500_000_000)
            guard !Task.isCancelled else { break }
            guard generation == adjustmentGenerations[goalId, default: 0] else { continue }

            let delta = pendingGoalDeltas.removeValue(forKey: goalId) ?? 0
            guard delta != 0 else { break }
            do {
                let updated: Goal = try await api.request(
                    "goals/\(goalId)/progress", method: "PATCH",
                    body: .init(GoalProgressBody(current: nil, add: delta))
                )
                replaceGoal(updated, detectCompletion: true)
            } catch {
                // Roll back only the failed batch. Any taps queued during the request
                // remain optimistic and will be sent by the next loop iteration.
                if let optimistic = optimisticGoalValues[goalId] {
                    optimisticGoalValues[goalId] = max(0, optimistic - delta)
                }
                show(error)
            }

            if pendingGoalDeltas[goalId] == nil { break }
        }

        adjustmentWorkers[goalId] = nil
        adjustmentGenerations[goalId] = nil
        if pendingGoalDeltas[goalId] == nil { optimisticGoalValues[goalId] = nil }
    }

    func setGoalStep(_ goal: Goal, step: Double) async {
        do {
            let updated: Goal = try await api.request("goals/\(goal.id)", method: "PATCH", body: .init(["step": step]))
            replaceGoal(updated)
        } catch { show(error) }
    }
    func setGoalTarget(_ goal: Goal, target: Double) async {
        guard target > 0 else { return }
        do {
            let updated: Goal = try await api.request(
                "goals/\(goal.id)", method: "PATCH",
                body: .init(GoalTargetBody(target: target))
            )
            replaceGoal(updated)
        } catch { show(error) }
    }
    func advanceGoal(_ goal: Goal, target: Double) async {
        guard target > 0 else { return }
        do {
            let updated: Goal = try await api.request(
                "goals/\(goal.id)/raise", method: "POST",
                body: .init(GoalTargetBody(target: target))
            )
            replaceGoal(updated)
            goalCelebration = nil
        } catch { show(error) }
    }
    func setGoalAppearance(_ goal: Goal, icon: String?, color: String?) async {
        do {
            let updated: Goal = try await api.request(
                "goals/\(goal.id)", method: "PATCH",
                body: .init(GoalAppearanceBody(icon: icon, color: color)))
            replaceGoal(updated)
        } catch { show(error) }
    }
    func setGoalName(_ goal: Goal, name: String) async {
        let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty, clean.count <= 80 else { return }
        do {
            let updated: Goal = try await api.request(
                "goals/\(goal.id)", method: "PATCH", body: .init(GoalNameBody(name: clean)))
            replaceGoal(updated)
        } catch { show(error) }
    }

    func focus(_ id: String) { focusedWidgetId = id }
    func clearFocus() { focusedWidgetId = nil }
    func isFocused(_ id: String) -> Bool { focusedWidgetId == id }

    func setGroupAppearance(_ name: String, icon: String?, color: String?) async {
        do {
            // APIClient's URL builder percent-encodes path components. Passing an
            // already encoded name would turn `%20` into `%2520` and customize a
            // different, literal group name on the backend.
            let _: GroupSettings = try await api.request(
                "goal-groups/\(name)/customization",
                method: "PUT", body: .init(GroupAppearanceBody(icon: icon, color: color)))
            await loadGoals()  // refetch so the cascade (group_color -> members) is reflected
        } catch { show(error) }
    }
    func setRoutineSchedule(
        _ goal: Goal,
        days: [String],
        weekStartsOn: String,
        reminderTime: String?,
        repeatUntilCompleted: Bool,
        nudgeIntervalMinutes: Int?
    ) async {
        do {
            let updated: Goal = try await api.request(
                "goals/\(goal.id)", method: "PATCH",
                body: .init(RoutineScheduleBody(
                    weeklyDays: days,
                    weeklyResetDay: weekStartsOn,
                    reminderTime: reminderTime,
                    repeatUntilCompleted: repeatUntilCompleted,
                    nudgeIntervalMinutes: repeatUntilCompleted ? nudgeIntervalMinutes : nil
                ))
            )
            replaceGoal(updated)
            await loadTodayRoutineTasks(force: true)
            // A cadence/time edit can remove occurrences that are no longer
            // returned by /schedule, so clear the whole old queue before rebuilding it.
            await ReminderNotificationScheduler.cancel(source: "routine", sourceId: goal.id)
            await loadSchedule(
                from: Date().apiDate,
                through: Date().apiDate,
                requestNotificationPermission: reminderTime != nil
            )
        } catch { show(error) }
    }
    func resetStreak(_ goal: Goal) async {
        do {
            let updated: Goal = try await api.request("goals/\(goal.id)/reset", method: "POST")
            replaceGoal(updated)
        } catch { show(error) }
    }
    func setGoalProgress(_ goal: Goal, current: Double) async {
        // An exact value is an ordering boundary: let queued relative adjustments
        // commit first, then send the absolute value so it cannot be overwritten.
        if let worker = adjustmentWorkers[goal.id] { await worker.value }
        exactGoalUpdates.insert(goal.id)
        optimisticGoalValues[goal.id] = current
        do {
            let updated: Goal = try await api.request("goals/\(goal.id)/progress", method: "PATCH", body: .init(GoalProgressBody(current: current, add: nil)))
            replaceGoal(updated, detectCompletion: true)
        } catch { show(error) }
        exactGoalUpdates.remove(goal.id)
        if pendingGoalDeltas[goal.id] == nil { optimisticGoalValues[goal.id] = nil }
        else { startAdjustmentWorkerIfNeeded(goalId: goal.id) }
    }
    func endGoal(_ id: Int) async {
        clearPendingAdjustments(for: id)
        do {
            let _: EmptyResponse = try await api.request("goals/\(id)", method: "DELETE")
            goals.removeAll { $0.id == id }
            todayRoutineTasks.removeAll { $0.goalId == id }
            weekRoutineTasks.removeAll { $0.goalId == id }
            scheduleItems.removeAll {
                ($0.source == "routine" || $0.source == "goal_deadline") && $0.sourceId == id
            }
            await ReminderNotificationScheduler.cancel(source: "routine", sourceId: id)
            DashboardSettings.removeWidget("goal:\(id)")
            if goalCelebration?.id == id { goalCelebration = nil }
            await loadArchivedGoals()
        } catch { show(error) }
    }
    func renameGoalGroup(_ members: [Goal], to name: String) async -> Bool {
        let cleanName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanName.isEmpty, cleanName.count <= 80 else { return false }
        do {
            let updated: [Goal] = try await api.request(
                "goal-groups", method: "PATCH",
                body: .init(GoalGroupUpdateBody(goalIds: members.map(\.id), name: cleanName))
            )
            for goal in updated { replaceGoal(goal) }
            return true
        } catch {
            show(error)
            return false
        }
    }
    func endGoalGroup(_ members: [Goal]) async -> Bool {
        let ids = members.map(\.id)
        ids.forEach(clearPendingAdjustments)
        do {
            let endedIds: [Int] = try await api.request(
                "goal-groups/end", method: "POST",
                body: .init(GoalGroupEndBody(goalIds: ids))
            )
            let ended = Set(endedIds)
            goals.removeAll { ended.contains($0.id) }
            todayRoutineTasks.removeAll { ended.contains($0.goalId) }
            weekRoutineTasks.removeAll { ended.contains($0.goalId) }
            scheduleItems.removeAll {
                ($0.source == "routine" || $0.source == "goal_deadline")
                    && ended.contains($0.sourceId)
            }
            for id in ended {
                await ReminderNotificationScheduler.cancel(source: "routine", sourceId: id)
            }
            if let celebration = goalCelebration, ended.contains(celebration.id) { goalCelebration = nil }
            await loadArchivedGoals()
            return true
        } catch {
            show(error)
            return false
        }
    }
    private func clearPendingAdjustments(for id: Int) {
        adjustmentWorkers[id]?.cancel()
        adjustmentWorkers[id] = nil; pendingGoalDeltas[id] = nil; optimisticGoalValues[id] = nil; exactGoalUpdates.remove(id)
    }
    func dismissGoalCelebration() { goalCelebration = nil }

    private func replaceGoal(_ updated: Goal, detectCompletion shouldDetect: Bool = false) {
        guard let index = goals.firstIndex(where: { $0.id == updated.id }) else { goals.append(updated); return }
        let previous = goals[index]
        goals[index] = updated
        if shouldDetect, crossedCompletion(from: previous, to: updated) {
            goalCelebration = updated
        }
    }
    private func detectCompletion(from previous: [Goal], to updated: [Goal]) {
        let priorById = Dictionary(uniqueKeysWithValues: previous.map { ($0.id, $0) })
        if let completed = updated.first(where: { goal in
            priorById[goal.id].map { crossedCompletion(from: $0, to: goal) } ?? false
        }) {
            goalCelebration = completed
        }
    }
    private func crossedCompletion(from previous: Goal, to updated: Goal) -> Bool {
        guard updated.period == "once",
              (["save", "numeric"].contains(updated.kind)
               || (updated.kind == "financial" && updated.financialSource == "manual")),
              let previousTarget = previous.target,
              let updatedTarget = updated.target else { return false }
        let wasComplete = previous.direction == "under"
            ? previous.currentValue <= previousTarget
            : previous.currentValue >= previousTarget
        let isComplete = updated.direction == "under"
            ? updated.currentValue <= updatedTarget
            : updated.currentValue >= updatedTarget
        return !wasComplete && isComplete
    }
    func check(_ task: GoalTask) async {
        do {
            let updated: GoalTask = try await api.request(
                "goals/\(task.goalId)/checkin", method: "PATCH",
                body: .init(CheckinBody(
                    scheduledFor: task.scheduledFor,
                    completed: !task.completed,
                    allowOverdue: task.scheduledFor < Date().apiDate
                )))
            if let index = todayRoutineTasks.firstIndex(where: { $0.id == updated.id }) {
                todayRoutineTasks[index] = updated
            }
            if let index = weekRoutineTasks.firstIndex(where: { $0.id == updated.id }) {
                weekRoutineTasks[index] = updated
            }
            await loadGoals()
        } catch { show(error) }
    }
    @discardableResult
    func uploadImage(_ data: Data, filename: String) async throws -> MediaAsset {
        try await api.uploadImage(data, filename: filename)
    }
    func send(_ text: String, attachmentIds: [String] = []) async -> Bool {
        let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard (!clean.isEmpty || !attachmentIds.isEmpty),
              !copilotRequestInFlight else { return false }
        copilotRequestInFlight = true
        defer { copilotRequestInFlight = false }
        messages.append(.init(
            role: "user",
            content: clean,
            attachmentIds: attachmentIds.isEmpty ? nil : attachmentIds
        ))
        await requestCopilotReply()
        return true
    }
    func submitAgentShortcut(_ shortcut: AgentShortcutInvocation) {
        guard !copilotRequestInFlight,
              !consumedAgentShortcutIds.contains(shortcut.id) else { return }
        consumedAgentShortcutIds.insert(shortcut.id)
        switch shortcut.request.action {
        case .chat:
            Task { await send(shortcut.request.prompt) }
        case .categorizeUnbudgeted:
            Task { await startUnbudgetedCategorization(shortcut) }
        }
    }
    @discardableResult
    func regenerate(from messageId: UUID, replacement: String? = nil) async -> Bool {
        guard !copilotRequestInFlight else { return false }
        guard let index = messages.firstIndex(where: { $0.id == messageId }),
              messages[index].role == "user" else { return false }
        let original = messages[index].content
        let attachmentIds = messages[index].attachmentIds
        let clean = (replacement ?? original).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty || !(attachmentIds ?? []).isEmpty else { return false }

        copilotRequestInFlight = true
        defer { copilotRequestInFlight = false }
        messages = Array(messages[..<index])
        messages.append(.init(
            role: "user",
            content: clean,
            attachmentIds: attachmentIds
        ))
        await requestCopilotReply()
        return true
    }
    private func requestCopilotReply() async {
        do {
            let response: ChatResponse = try await api.request(
                "assistant/chat",
                method: "POST",
                body: .init(ChatBody(
                    messages: Array(messages.suffix(20)),
                    timezone: TimeZone.current.identifier
                ))
            )
            messages.append(.init(role: "assistant", content: response.reply, actions: response.actions))
            DashboardSettings.apply(response.uiActions ?? [])
            if response.refresh { await loadAll() }
        } catch { show(error) }
    }
    private func startUnbudgetedCategorization(_ shortcut: AgentShortcutInvocation) async {
        guard !copilotRequestInFlight else { return }
        copilotRequestInFlight = true
        messages.append(.init(role: "user", content: shortcut.request.prompt))
        do {
            let job: AgentJob = try await api.request(
                "assistant/jobs/categorize-unbudgeted",
                method: "POST",
                body: .init(CategorizeUnbudgetedJobBody(
                    month: Self.currentMonth,
                    timezone: TimeZone.current.identifier,
                    idempotencyKey: shortcut.id.uuidString
                ))
            )
            activeAgentJob = job
            UserDefaults.standard.set(job.id, forKey: Self.activeAgentJobKey)
            beginPollingAgentJob(job.id)
        } catch {
            copilotRequestInFlight = false
            show(error)
        }
    }
    private func resumeAgentJobIfNeeded() {
        guard let jobId = UserDefaults.standard.string(forKey: Self.activeAgentJobKey),
              !jobId.isEmpty else { return }
        copilotRequestInFlight = true
        beginPollingAgentJob(jobId)
    }
    private func beginPollingAgentJob(_ jobId: String) {
        guard pollingAgentJobId != jobId else { return }
        agentJobPollingTask?.cancel()
        pollingAgentJobId = jobId
        agentJobPollingTask = Task { await pollAgentJob(jobId) }
    }
    private func pollAgentJob(_ jobId: String) async {
        while !Task.isCancelled {
            do {
                let job: AgentJob = try await api.request("assistant/jobs/\(jobId)")
                activeAgentJob = job
                switch job.status {
                case "completed":
                    messages.append(.init(
                        role: "assistant",
                        content: job.message ?? "I finished reviewing those transactions."
                    ))
                    clearActiveAgentJob()
                    async let transactions: Void = loadTransactions()
                    async let summary: Void = loadSummary()
                    _ = await (transactions, summary)
                    return
                case "failed":
                    let detail = job.error?.trimmingCharacters(in: .whitespacesAndNewlines)
                    messages.append(.init(
                        role: "assistant",
                        content: detail.map { "I couldn't finish that review: \($0)" }
                            ?? "I couldn't finish reviewing those transactions."
                    ))
                    clearActiveAgentJob()
                    return
                default:
                    try await Task.sleep(nanoseconds: 1_250_000_000)
                }
            } catch is CancellationError {
                return
            } catch {
                clearActiveAgentJob()
                show(error)
                return
            }
        }
    }
    private func clearActiveAgentJob() {
        UserDefaults.standard.removeObject(forKey: Self.activeAgentJobKey)
        activeAgentJob = nil
        copilotRequestInFlight = false
        pollingAgentJobId = nil
        agentJobPollingTask = nil
    }
    func clearChat() { messages = [] }
    private func show(_ value: Error) {
        // SwiftUI routinely cancels `.task` and `.refreshable` work when a view is
        // replaced or a newer refresh supersedes it. That is control flow, not a
        // backend/network failure, so it should never become a user-facing alert.
        if value is CancellationError { return }
        if let urlError = value as? URLError, urlError.code == .cancelled { return }
        let nsError = value as NSError
        if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled { return }
        if Task.isCancelled { return }
        error = value.localizedDescription
    }
    static var currentMonth: String { let f = DateFormatter(); f.dateFormat = "yyyy-MM"; return f.string(from: Date()) }
}

enum ChatStorage {
    private static let key = "money.copilot.history"
    private static let cap = 60
    private struct StoredMessage: Codable {
        let role, content: String
        let attachmentIds: [String]?
    }

    static func load() -> [ChatMessage] {
        guard let data = UserDefaults.standard.data(forKey: key),
              let stored = try? JSONDecoder().decode([StoredMessage].self, from: data) else { return [] }
        return stored.map {
            ChatMessage(
                role: $0.role,
                content: $0.content,
                attachmentIds: $0.attachmentIds
            )
        }
    }
    static func save(_ messages: [ChatMessage]) {
        let stored = messages.suffix(cap).map {
            StoredMessage(
                role: $0.role,
                content: $0.content,
                attachmentIds: $0.attachmentIds
            )
        }
        UserDefaults.standard.set(try? JSONEncoder().encode(stored), forKey: key)
    }
}

enum DashboardSettings {
    static let defaults = ["left-to-spend", "monthly-averages", "spending-by-category", "portfolio-summary"]
    private static let retiredRoutineChecklists = Set([
        "goal-todo-day", "goal-todo-week", "goal-todo-month",
        "routine-todo-day", "routine-todo-week", "routine-todo-month",
    ])
    static var widgets: [String] {
        get {
            let saved = UserDefaults.standard.stringArray(forKey: "money.dashboard.widgets") ?? defaults
            let cleaned = saved
                .filter { !retiredRoutineChecklists.contains($0) }
                .map { $0 == "routine-section:ongoing" ? "goal-section:ongoing" : $0 }
            if cleaned != saved { UserDefaults.standard.set(cleaned, forKey: "money.dashboard.widgets") }
            return cleaned
        }
        set { UserDefaults.standard.set(Array(NSOrderedSet(array: newValue)) as? [String] ?? newValue, forKey: "money.dashboard.widgets") }
    }
    static func apply(_ actions: [DashboardAction]) {
        var result = widgets
        for action in actions {
            let ids = action.widgetIds ?? []
            switch action.type {
            case "dashboard.set_widgets": result = ids
            case "dashboard.add_widgets": result += ids.filter { !result.contains($0) }
            case "dashboard.remove_widgets": result.removeAll { ids.contains($0) }
            case "dashboard.clear_widgets": result = []
            case "dashboard.reset_widgets": result = defaults
            default: break
            }
        }
        widgets = result
    }
    static func replaceWidget(_ oldId: String, with newId: String) {
        widgets = widgets.map { $0 == oldId ? newId : $0 }
    }
    static func removeWidget(_ id: String) {
        widgets = widgets.filter { $0 != id }
    }
}

// MARK: - Shared widgets

struct WidgetCard<Content: View>: View {
    let title: String
    let showsShadow: Bool
    @ViewBuilder let content: Content
    init(
        _ title: String,
        showsShadow: Bool = true,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.showsShadow = showsShadow
        self.content = content()
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) { if !title.isEmpty { Text(title).widgetTitle() }; content }
            .frame(maxWidth: .infinity, alignment: .leading).padding(16)
            .background(Theme.card, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Theme.cardStroke))
            .shadow(
                color: showsShadow ? Theme.shadow : .clear,
                radius: showsShadow ? 12 : 0,
                y: showsShadow ? 4 : 0
            )
    }
}
struct MetricWidget: View { let title: String, value: String; var color: Color = .primary
    var body: some View { WidgetCard(title) { Text(value).font(.statNumber.monospacedDigit()).foregroundStyle(color).fitOneLine() } }
}
struct BudgetBarWidget: View { let budget: BudgetProgress
    var body: some View { VStack(alignment: .leading, spacing: 6) { HStack { Text(budget.category.pretty).font(.subheadline.weight(.medium)).lineLimit(1); Text("· \(budget.period.capitalized)").font(.caption).foregroundStyle(.tertiary); Spacer(); Text("\(budget.spent.currency) / \(budget.limit.currency)").foregroundStyle(.secondary).font(.caption.monospacedDigit()).fitOneLine() }; GaugeBar(pct: budget.pct) } }
}
struct EmptyWidget: View { let text: String; var body: some View { VStack(spacing: 10) { IconChip(symbol: "tray", tint: .secondary); Text(text).font(.subheadline).foregroundStyle(.secondary) }.frame(maxWidth: .infinity).padding(30) } }

// MARK: - Root navigation

struct ContentView: View {
    @StateObject private var store: MoneyStore
    @State private var hasCompletedInitialLoad: Bool
    @AppStorage(LocalUIStateKey.selectedTab) private var selection = "dashboard"
    private let loadsRemoteData: Bool
    private var unbudgetedCount: Int {
        store.transactions.filter {
            $0.date.hasPrefix(MoneyStore.currentMonth) && $0.isBudgeted == false
        }.count
    }

    @MainActor init() {
        _store = StateObject(wrappedValue: MoneyStore())
        _hasCompletedInitialLoad = State(initialValue: false)
        loadsRemoteData = true
    }

    init(store: MoneyStore, loadsRemoteData: Bool) {
        _store = StateObject(wrappedValue: store)
        _hasCompletedInitialLoad = State(initialValue: !loadsRemoteData)
        self.loadsRemoteData = loadsRemoteData
    }

    var body: some View {
        TabView(selection: $selection) {
            NavigationStack { DashboardView() }.tabItem { Label("Dashboard", systemImage: "square.grid.2x2") }.tag("dashboard")
            NavigationStack { FinancesView() }
                .tabItem { Label("Finances", systemImage: "creditcard") }
                .badge(unbudgetedCount)
                .tag("finances")
            NavigationStack {
                CopilotView()
                    .navigationTitle("Audel")
                    .navigationBarTitleDisplayMode(.inline)
            }
            .tabItem {
                // Icon-only: the Audel mark is distinctive enough to stand
                // without a title. iOS centers a label-less tab icon, so it
                // reads as a prominent center action among the labeled tabs.
                Image(uiImage: AudelTabIcon.image)
                    .accessibilityLabel("Audel")
            }
            .tag("audel")
            NavigationStack { GoalsView() }.tabItem { Label("Goals", systemImage: "target") }.tag("goals")
            NavigationStack { ScheduleView() }.tabItem { Label("Schedule", systemImage: "calendar") }.tag("routines")
            // Invest tab hidden for now (2026-07-28). Restore this line to bring it back.
            // NavigationStack { InvestView() }.tabItem { Label("Invest", systemImage: "chart.line.uptrend.xyaxis") }.tag("invest")
        }
        .environmentObject(store)
        .tint(Theme.brand)
        .dynamicTypeSize(.small)
        .task {
            guard loadsRemoteData else { return }
            await store.loadOnLaunch()
            withAnimation(.easeOut(duration: 0.2)) {
                hasCompletedInitialLoad = true
            }
        }
        .onAppear {
            let validTabs = ["dashboard", "finances", "goals", "routines", "audel"]
            if !validTabs.contains(selection) { selection = "dashboard" }
        }
        .onOpenURL { url in
            if let tab = AudelDeepLink.tab(for: url) {
                selection = tab
            }
        }
        .overlay {
            if !hasCompletedInitialLoad {
                AudelLoadingScreen()
                    .transition(.opacity)
            } else if let goal = store.goalCelebration {
                GoalCompletionOverlay(goal: goal)
                    .environmentObject(store)
            }
        }
        .alert("Something went wrong", isPresented: Binding(get: { store.error != nil }, set: { if !$0 { store.error = nil } })) { Button("OK") { store.error = nil } } message: { Text(store.error ?? "") }
    }
}

private enum AudelTabIcon {
    static let image: UIImage = {
        guard let source = UIImage(named: "AudelLaunchLogo") else {
            return UIImage(systemName: "sparkles") ?? UIImage()
        }
        let size = CGSize(width: 30, height: 30)
        let rendered = UIGraphicsImageRenderer(size: size).image { _ in
            // The source PNG has generous transparent padding for launch-screen
            // use. Drawing beyond this small canvas crops that padding while
            // preserving the complete Audel mark at native tab-bar scale.
            source.draw(in: CGRect(x: -10, y: -10, width: 50, height: 50))
        }
        return rendered.withRenderingMode(.alwaysTemplate)
    }()
}

private struct AudelLoadingScreen: View {
    var body: some View {
        ZStack {
            Color("LaunchBackground")
            Image("AudelLaunchLogo")
                .resizable()
                .scaledToFit()
                .frame(width: 250, height: 250)
                .accessibilityHidden(true)
        }
        .ignoresSafeArea()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Audel is loading")
    }
}

// MARK: - Dashboard

enum DashboardWidgetSource: String { case finances = "Finances", goals = "Goals", routines = "Schedule", invest = "Invest" }

struct DashboardWidgetDefinition: Identifiable {
    let id, title: String
    let source: DashboardWidgetSource
}

enum DashboardWidgetRegistry {
    static let definitions: [DashboardWidgetDefinition] = [
        .init(id: "left-to-spend", title: "Left to spend", source: .finances),
        .init(id: "monthly-averages", title: "Monthly averages", source: .finances),
        .init(id: "spending-by-category", title: "Spending chart", source: .finances),
        .init(id: "income-vs-expense", title: "Income vs expense", source: .finances),
        .init(id: "category-transactions", title: "Transactions by category", source: .finances),
        .init(id: "recent-transactions", title: "Recent transactions", source: .finances),
        .init(id: "unbudgeted-transactions", title: "Unbudgeted spending", source: .finances),
        .init(id: "p2p-review", title: "Zelle & Venmo review", source: .finances),
        .init(id: "account-balances", title: "Account balances", source: .finances),
        .init(id: "account-sync", title: "Connect or sync bank", source: .finances),
        .init(id: "budget-progress", title: "Budget progress", source: .finances),
        .init(id: "routine-today", title: "Today's to-do", source: .routines),
        .init(id: "schedule-calendar", title: "Calendar", source: .routines),
        .init(id: "schedule-today", title: "Today's schedule", source: .routines),
        .init(id: "portfolio-summary", title: "Portfolio summary", source: .invest),
        .init(id: "portfolio-positions", title: "Portfolio positions", source: .invest),
    ]

    static func definition(for id: String) -> DashboardWidgetDefinition? { definitions.first { $0.id == id } }
}

/// Pure, UI-free reorder math for the dashboard. Kept separate so it can be
/// unit-tested without a running view (mirrors `GoalChartTimeline`).
enum DashboardReorder {
    /// Move `liftedID` to `index` in `order`. Returns `order` unchanged when the
    /// id is absent or already at the clamped destination. `index` is clamped to
    /// `0..<order.count`.
    static func reordered(_ order: [String], move liftedID: String, to index: Int) -> [String] {
        guard let from = order.firstIndex(of: liftedID) else { return order }
        let clamped = max(0, min(index, order.count - 1))
        if from == clamped { return order }
        var next = order
        next.remove(at: from)
        next.insert(liftedID, at: clamped)
        return next
    }

    /// Destination index for the lifted card: the number of *other* rows whose
    /// measured midpoint sits above the finger. Rows missing from `midY`
    /// (e.g. not yet laid out) are ignored. Excluding the lifted row keeps the
    /// order stable when the finger rests near the lifted card's own slot.
    static func targetIndex(order: [String], midY: [String: CGFloat], liftedID: String, fingerY: CGFloat) -> Int {
        var index = 0
        for id in order where id != liftedID {
            if let mid = midY[id], mid < fingerY { index += 1 }
        }
        return max(0, min(index, order.count - 1))
    }
}

/// Collects each dashboard row's layout frame (in the "dashReorder" space) so the
/// lifted card can track the finger and the reorder math can find midpoints.
struct RowFramePreferenceKey: PreferenceKey {
    static var defaultValue: [String: CGRect] = [:]
    static func reduce(value: inout [String: CGRect], nextValue: () -> [String: CGRect]) {
        value.merge(nextValue()) { _, new in new }
    }
}

struct DashboardView: View {
    @EnvironmentObject var store: MoneyStore
    @State private var widgets = DashboardSettings.widgets
    @AppStorage(LocalUIStateKey.dashboardEditing) private var customizing = false
    @SwiftUI.Environment(\.accessibilityReduceMotion) private var reduceMotion

    // Reorder session
    @State private var liftedID: String?
    @State private var fingerY: CGFloat = 0
    @State private var rowFrames: [String: CGRect] = [:]

    private let reorderSpace = "dashReorder"

    var body: some View {
        ScrollView { LazyVStack(spacing: 16) {
            HStack(alignment: .firstTextBaseline) {
                Text("Money").font(.system(size: 28, weight: .bold, design: .rounded))
                Spacer()
                Text(Date().formatted(.dateTime.month(.wide).year())).font(.subheadline).foregroundStyle(.secondary)
            }
            .padding(.bottom, 2)

            if widgets.isEmpty { EmptyWidget(text: "Your dashboard is empty — tap Edit dashboard below to add a widget.") }

            ForEach(widgets, id: \.self) { id in
                let isLifted = liftedID == id
                let isCollapsed = liftedID != nil && !isLifted
                rowContent(id: id, isCollapsed: isCollapsed)
                    .background(GeometryReader { geo in
                        Color.clear.preference(
                            key: RowFramePreferenceKey.self,
                            value: [id: geo.frame(in: .named(reorderSpace))]
                        )
                    })
                    .scaleEffect(isLifted && !reduceMotion ? 1.03 : 1)
                    .shadow(color: Theme.shadow, radius: isLifted ? 14 : 0, x: 0, y: isLifted ? 8 : 0)
                    .offset(y: isLifted ? liftOffset(id) : 0)
                    .zIndex(isLifted ? 1 : 0)
                    .gesture(customizing ? reorderGesture(id: id) : nil)
            }

            if customizing { AddWidgetsPanel(existing: widgets) { id in withAnimation { widgets.append(id) }; save() } }
            Button(customizing ? "Done" : "Edit dashboard") { withAnimation { customizing.toggle() } }
                .font(.subheadline.weight(.medium)).foregroundStyle(Theme.brand)
                .frame(maxWidth: .infinity).padding(.top, 6)
            if customizing { Button("Reset to defaults") { withAnimation { widgets = DashboardSettings.defaults }; save() }.font(.caption).foregroundStyle(.secondary) }
        }.padding() }
        .coordinateSpace(name: reorderSpace)
        .onPreferenceChange(RowFramePreferenceKey.self) { rowFrames = $0 }
        .background(Theme.canvas)
        .toolbar(.hidden, for: .navigationBar)
        .refreshable { await store.refreshFinances() }
        .onAppear { widgets = DashboardSettings.widgets }
    }

    // MARK: Rows

    @ViewBuilder
    func rowContent(id: String, isCollapsed: Bool) -> some View {
        if isCollapsed {
            collapsedChip(id: id)
        } else if customizing {
            VStack(spacing: 8) {
                editHeader(id: id)
                DashboardWidget(id: id)
            }
            .contentShape(Rectangle())
        } else {
            DashboardWidget(id: id)
        }
    }

    func editHeader(id: String) -> some View {
        HStack {
            Text(widgetTitle(id)).font(.caption.bold()).foregroundStyle(.secondary)
            Spacer()
            Button {
                removeWidget(id)
            } label: {
                Image(systemName: "minus.circle.fill").foregroundStyle(Theme.negative)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Remove \(widgetTitle(id))")
            Image(systemName: "line.3.horizontal")
                .foregroundStyle(.secondary)
                .accessibilityLabel("Drag to reorder")
        }
    }

    func collapsedChip(id: String) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                if let source = DashboardWidgetRegistry.definition(for: id)?.source.rawValue {
                    Text(source.uppercased()).font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
                }
                Text(widgetTitle(id)).font(.subheadline.weight(.semibold))
            }
            Spacer()
            Image(systemName: "line.3.horizontal").foregroundStyle(.secondary)
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.card))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(Theme.cardStroke, lineWidth: 1))
        .contentShape(Rectangle())
    }

    // MARK: Reorder gesture

    func reorderGesture(id: String) -> some Gesture {
        LongPressGesture(minimumDuration: 0.3)
            .sequenced(before: DragGesture(minimumDistance: 0, coordinateSpace: .named(reorderSpace)))
            .onChanged { value in
                guard case .second(true, let drag?) = value else { return }
                guard liftedID == nil || liftedID == id else { return }
                if liftedID == nil {
                    liftedID = id
                    UIImpactFeedbackGenerator(style: .medium).impactOccurred()
                }
                fingerY = drag.location.y
                evaluateReorder()
            }
            .onEnded { _ in endReorder() }
    }

    func liftOffset(_ id: String) -> CGFloat {
        guard let mid = rowFrames[id]?.midY else { return 0 }
        return fingerY - mid
    }

    func evaluateReorder() {
        guard let liftedID else { return }
        let midY = rowFrames.mapValues { $0.midY }
        let target = DashboardReorder.targetIndex(order: widgets, midY: midY, liftedID: liftedID, fingerY: fingerY)
        let next = DashboardReorder.reordered(widgets, move: liftedID, to: target)
        if next != widgets {
            UISelectionFeedbackGenerator().selectionChanged()
            withAnimation(reduceMotion ? nil : .snappy) { widgets = next }
        }
    }

    func endReorder() {
        withAnimation(reduceMotion ? nil : .snappy) { liftedID = nil }
        fingerY = 0
        save()
    }

    func save() { DashboardSettings.widgets = widgets }

    func removeWidget(_ id: String) {
        withAnimation { widgets.removeAll { $0 == id } }
        save()
    }

    func widgetTitle(_ id: String) -> String {
        DashboardWidgetRegistry.definition(for: id)?.title
            ?? store.goals.first { "goal:\($0.id)" == id }?.name
            ?? goalCategories(from: store.goals).first { $0.id == id }?.name
            ?? routineCategories(from: store.goals).first { $0.id == id }?.name
            ?? id.pretty
    }
}

struct WidgetSource: Identifiable {
    struct Item { let id, name: String; var indent = false }
    let id, name, symbol: String
    let items: [Item]
}

struct AddWidgetsPanel: View {
    @EnvironmentObject var store: MoneyStore
    let existing: [String]
    let add: (String) -> Void
    @AppStorage(LocalUIStateKey.dashboardOpenSource) private var openSource = ""
    @AppStorage(LocalUIStateKey.dashboardPreview) private var previewing = ""

    private var sources: [WidgetSource] {
        func registered(_ source: DashboardWidgetSource) -> [WidgetSource.Item] {
            DashboardWidgetRegistry.definitions.filter { $0.source == source }.map { .init(id: $0.id, name: $0.title) }
        }
        var goals = registered(.goals)
        for category in goalCategories(from: store.goals) {
            goals.append(.init(id: category.id, name: category.name))
            goals += category.goals.map { .init(id: "goal:\($0.id)", name: $0.name, indent: true) }
        }
        var routines = registered(.routines)
        for category in routineCategories(from: store.goals) {
            routines.append(.init(id: category.id, name: category.name))
            routines += category.goals.map { .init(id: "goal:\($0.id)", name: $0.name, indent: true) }
        }
        return [
            WidgetSource(id: "finances", name: "Finances", symbol: "creditcard.fill", items: registered(.finances).filter { !existing.contains($0.id) }),
            WidgetSource(id: "goals", name: "Goals", symbol: "target", items: goals.filter { !existing.contains($0.id) }),
            WidgetSource(id: "routines", name: "Schedule", symbol: "calendar", items: routines.filter { !existing.contains($0.id) }),
            WidgetSource(id: "invest", name: "Invest", symbol: "chart.line.uptrend.xyaxis", items: registered(.invest).filter { !existing.contains($0.id) }),
        ]
    }

    var body: some View {
        WidgetCard("Add widgets") {
            HStack(spacing: 10) { ForEach(sources) { source in sourceButton(source) } }
            if let source = sources.first(where: { $0.id == openSource }) {
                if source.items.isEmpty {
                    Text("Everything from \(source.name) is already on your dashboard.").font(.caption).foregroundStyle(.secondary)
                } else {
                    VStack(spacing: 2) { ForEach(source.items, id: \.id) { item in widgetRow(item) } }
                }
            }
        }
    }

    private func sourceButton(_ source: WidgetSource) -> some View {
        let isOpen = openSource == source.id
        return Button {
            withAnimation(.spring(duration: 0.3)) {
                openSource = isOpen ? "" : source.id
                previewing = ""
            }
        } label: {
            VStack(spacing: 5) {
                Image(systemName: source.symbol)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(isOpen ? Theme.onBrand : Theme.brand)
                    .frame(width: 46, height: 46)
                    .background(isOpen ? AnyShapeStyle(Theme.brand) : AnyShapeStyle(Theme.brand.opacity(0.12)), in: RoundedRectangle(cornerRadius: 13, style: .continuous))
                Text(source.name).font(.caption2.weight(.medium)).foregroundStyle(isOpen ? Theme.brand : .secondary)
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder private func widgetRow(_ item: WidgetSource.Item) -> some View {
        let isPreviewing = previewing == item.id
        VStack(spacing: 8) {
            HStack {
                Button {
                    withAnimation(.spring(duration: 0.3)) { previewing = isPreviewing ? "" : item.id }
                } label: {
                    HStack(spacing: 7) {
                        Image(systemName: isPreviewing ? "chevron.down" : "chevron.right").font(.caption2).foregroundStyle(.secondary)
                        Text(item.name).font(.subheadline).lineLimit(1)
                        Spacer()
                    }
                }.buttonStyle(.plain)
                Button("Add") { add(item.id) }
                    .font(.caption.weight(.semibold)).buttonStyle(.bordered).tint(Theme.brand).controlSize(.small)
            }
            if isPreviewing {
                DashboardWidget(id: item.id)
                    .allowsHitTesting(false)
                    .padding(.leading, 18)
            }
        }
        .padding(.vertical, 3)
        .padding(.leading, item.indent ? 22 : 0)
    }
}

struct DashboardWidget: View {
    @EnvironmentObject var store: MoneyStore; let id: String
    @ViewBuilder var body: some View {
        switch id {
        case "left-to-spend": LeftToSpendWidget()
        case "monthly-averages": MonthlyAverageWidget()
        case "spending-by-category": SpendingChartWidget()
        case "income-vs-expense": IncomeExpenseChartWidget()
        case "category-transactions": CategoryTransactionsWidget()
        case "recent-transactions": RecentTransactionsWidget()
        case "unbudgeted-transactions": UnbudgetedTransactionsDashboardWidget()
        case "p2p-review": PeerPaymentReviewDashboardWidget()
        case "account-balances": AccountBalancesWidget()
        case "account-sync": BankConnectionWidget()
        case "budget-progress": LeftToSpendWidget(title: "Budget progress")
        case "budget-form": AddBudgetWidget()
        case "routine-today": RoutineTodayWidget()
        case "schedule-calendar": ScheduleCalendarDashboardWidget()
        case "schedule-today": ScheduleTodayDashboardWidget()
        case "portfolio-summary": PortfolioSummaryWidget()
        case "portfolio-positions": PortfolioPositionsWidget()
        default:
            if let goal = store.goals.first(where: { "goal:\($0.id)" == id }) { GoalWidget(goal: goal) }
            else if let category = goalCategories(from: store.goals).first(where: { $0.id == id }) { GoalCategoryWidget(category: category) }
            else if let category = routineCategories(from: store.goals).first(where: { $0.id == id }) { GoalCategoryWidget(category: category) }
            else if let legacyCategory = legacyRoutineCategory(for: id) { GoalCategoryWidget(category: legacyCategory) }
            else { EmptyWidget(text: "Widget unavailable") }
        }
    }

    private func legacyRoutineCategory(for id: String) -> GoalCategory? {
        if id == "routine-section:ongoing" {
            return goalCategories(from: store.goals).first { $0.id == "goal-section:ongoing" }
        }
        if id.hasPrefix("routine-group:") {
            let suffix = id.dropFirst("routine-group:".count)
            return goalCategories(from: store.goals).first { $0.id == "goal-group:\(suffix)" }
        }
        if id.hasPrefix("goal-section:") {
            let suffix = id.dropFirst("goal-section:".count)
            return routineCategories(from: store.goals).first { $0.id == "routine-section:\(suffix)" }
        }
        if id.hasPrefix("goal-group:") {
            let suffix = id.dropFirst("goal-group:".count)
            return routineCategories(from: store.goals).first { $0.id == "routine-group:\(suffix)" }
        }
        return nil
    }
}

struct MerchantBreakdown: Identifiable { var id: String { name }; let name: String; let total: Double; let count: Int; let last: String }

/// Compact three-window summary used by the Overview's left-to-spend widget.
struct BudgetPeriodSummaryControl: View {
    @Binding var selection: String
    let progress: [BudgetProgress]
    private let periods = [("daily", "Today"), ("weekly", "Week"), ("monthly", "Month")]
    var body: some View {
        HStack(spacing: 8) {
            ForEach(periods, id: \.0) { period, label in
                let rows = progress.filter { $0.period == period }
                let remaining = rows.reduce(0) { $0 + $1.remaining }
                Button { selection = period } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(label).font(.caption2).foregroundStyle(.secondary)
                        Text(rows.isEmpty ? "—" : remaining.currency)
                            .font(.subheadline.weight(.bold).monospacedDigit())
                            .foregroundStyle(remaining < 0 ? Theme.negative : Theme.brand)
                            .lineLimit(1)
                            .minimumScaleFactor(0.85)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(9)
                    .background(selection == period ? Theme.brand.opacity(0.13) : Color.secondary.opacity(0.07),
                                in: RoundedRectangle(cornerRadius: 10))
                }
                .buttonStyle(.plain)
            }
        }
    }
}

struct LeftToSpendWidget: View {
    @EnvironmentObject var store: MoneyStore
    @StoredStringSet(LocalUIStateKey.leftToSpendExpanded) private var expanded
    @AppStorage(LocalUIStateKey.budgetPeriod) private var selectedPeriod = "monthly"
    var title = "Left to spend"
    var allowsDelete = false
    var showsAddForm = false
    @State private var editingBudget: Budget?
    private var budgets: [BudgetProgress] {
        (store.summary?.budgetProgress ?? []).filter { $0.period == selectedPeriod }
    }
    private var allBudgets: [BudgetProgress] { store.summary?.budgetProgress ?? [] }

    var body: some View {
        WidgetCard(title) {
            BudgetPeriodSummaryControl(selection: $selectedPeriod, progress: allBudgets)
            if budgets.isEmpty {
                Text("No \(selectedPeriod) budgets set — ask Audel or add one in Budgets.").foregroundStyle(.secondary)
            } else {
                ForEach(budgets) { budget in
                    budgetRow(budget)
                    if budget.id != budgets.last?.id { Divider() }
                }
            }
            if showsAddForm {
                Divider()
                Text("Add \(selectedPeriod) budget")
                    .font(.subheadline.weight(.semibold))
                AddBudgetWidget(
                    usesCard: false,
                    defaultPeriod: selectedPeriod,
                    showsPeriodPicker: false,
                    compact: true
                )
            }
        }
        .sheet(item: $editingBudget) { budget in
            EditBudgetView(budget: budget)
        }
    }

    @ViewBuilder private func budgetRow(_ budget: BudgetProgress) -> some View {
        let row = BudgetDisclosureRow(
            budget: budget,
            isOpen: expanded.contains(budget.id),
            toggle: { toggle(budget.id) }
        )
        if allowsDelete,
           let storedBudget = store.budgets.first(where: {
               $0.category == budget.category && $0.period == budget.period
           }) {
            row
                .pressAndHoldToEdit {
                    editingBudget = storedBudget
                }
        } else {
            row
        }
    }

    private func toggle(_ category: String) {
        var next = expanded
        if next.contains(category) { next.remove(category) } else { next.insert(category) }
        expanded = next
    }
}

struct BudgetDisclosureRow: View {
    @EnvironmentObject private var store: MoneyStore
    let budget: BudgetProgress
    let isOpen: Bool
    let toggle: () -> Void

    private var windowTransactions: [Transaction] {
        store.transactions.filter { $0.date >= budget.windowStart && $0.date <= budget.windowEnd }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button(action: toggle) {
                HStack(spacing: 7) {
                    Image(systemName: isOpen ? "chevron.down" : "chevron.right")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text(budget.category.pretty)
                        .font(.subheadline.weight(.medium))
                        .lineLimit(1)
                    Spacer()
                    VStack(alignment: .trailing, spacing: 0) {
                        Text(budget.remaining.currency)
                            .font(.subheadline.weight(.medium).monospacedDigit())
                            .lineLimit(1)
                            .minimumScaleFactor(0.85)
                        Text("left")
                            .font(.caption2.weight(.medium))
                    }
                    .foregroundStyle(budget.remaining < 0 ? Theme.negative : Theme.brand)
                    .layoutPriority(1)
                }
            }
            .buttonStyle(.plain)
            Text("\(budget.spent.currency) of \(budget.limit.currency)")
            .font(.caption.monospacedDigit())
            .foregroundStyle(.secondary)
            GaugeBar(pct: budget.pct)
            if isOpen { breakdown }
        }
        .padding(.vertical, 3)
    }

    private var breakdown: some View {
        let merchants = merchants(for: budget.category)
        let reimbursements = reimbursements(for: budget.category)
        return VStack(alignment: .leading, spacing: 5) {
            if merchants.isEmpty && reimbursements.isEmpty {
                Text("No spending in this budget window.")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
            ForEach(merchants) { merchant in
                HStack {
                    Text(merchant.name + (merchant.count > 1 ? " ×\(merchant.count)" : "")).lineLimit(1)
                    Spacer()
                    Text("last \(merchant.last.monthDay) · \(merchant.total.currency)").foregroundStyle(.secondary)
                }
                .font(.caption)
            }
            ForEach(reimbursements) { transaction in
                HStack {
                    VStack(alignment: .leading, spacing: 1) {
                        Text("↩ \(transaction.merchantName ?? transaction.name)").lineLimit(1)
                        if transaction.reimbursesTransactionId == nil {
                            Text("Applied to \(budget.category.pretty)")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    Text("\(transaction.date.monthDay) · \(transaction.amount.currency)")
                }
                .font(.caption)
                .foregroundStyle(Theme.brand)
            }
            if !reimbursements.isEmpty {
                Divider()
                HStack { Text("Net counted"); Spacer(); Text(budget.spent.currency) }
                    .font(.caption.bold())
            }
        }
        .padding(.leading, 16)
        .overlay(alignment: .leading) {
            Rectangle().fill(Color.secondary.opacity(0.15)).frame(width: 2)
        }
    }

    private func merchants(for category: String) -> [MerchantBreakdown] {
        let matches = windowTransactions.filter { $0.effectiveCategory == category && $0.amount >= 0 }
        let grouped: [String: [Transaction]] = Dictionary(grouping: matches) {
            $0.merchantName ?? $0.name
        }
        let merchants: [MerchantBreakdown] = grouped.map { entry in
            let items = entry.value
            let total = items.reduce(0.0) { $0 + $1.amount }
            let visitCount = Set(items.map(\.date)).count
            let lastDate = items.map(\.date).max() ?? ""
            return MerchantBreakdown(
                name: entry.key,
                total: total,
                count: visitCount,
                last: lastDate
            )
        }
        return merchants.sorted { $0.total > $1.total }
    }
    private func reimbursements(for category: String) -> [Transaction] {
        windowTransactions
            .filter { $0.reimbursementCategory == category }
            .sorted { $0.date > $1.date }
    }
}

struct MonthlyAverageWidget: View {
    @EnvironmentObject var store: MoneyStore
    @State private var selectedMonths: Set<String>?
    private var trend: [MonthlyTrend] { store.summary?.monthlyTrend ?? [] }
    private var defaults: Set<String> {
        let complete = store.summary?.completeMonths ?? []
        let source = complete.isEmpty ? trend.map(\.month).filter { $0 != MoneyStore.currentMonth } : complete
        return Set(source.suffix(3))
    }
    private var selected: Set<String> { selectedMonths ?? defaults }
    private var months: [MonthlyTrend] { trend.filter { selected.contains($0.month) } }
    var body: some View {
        WidgetCard("Monthly averages") {
            Text("Averaging \(months.count) \(months.count == 1 ? "month" : "months"):").font(.caption).foregroundStyle(.secondary)
            MonthlyAverageMonthPicker(
                trend: trend,
                completeMonths: Set(store.summary?.completeMonths ?? []),
                selected: selected
            ) { month in
                var next = selected
                if next.contains(month) { next.remove(month) } else { next.insert(month) }
                selectedMonths = next
            }
            HStack { avg("Avg income / mo", \MonthlyTrend.income, Theme.brand); avg("Avg expenses / mo", \MonthlyTrend.expense, Theme.negative); avg("Avg net / mo", nil, net < 0 ? Theme.negative : Theme.brand) }
            Text("Expenses are net of Zelle/Venmo with people (reimbursements in, payments out). Card payments and account transfers excluded.").font(.caption2).foregroundStyle(.tertiary)
        }
    }
    private var net: Double { average(\MonthlyTrend.income) - average(\MonthlyTrend.expense) }
    private func average(_ key: KeyPath<MonthlyTrend, Double>) -> Double { months.reduce(0) { $0 + $1[keyPath: key] } / Double(max(months.count, 1)) }
    private func avg(_ name: String, _ key: KeyPath<MonthlyTrend, Double>?, _ color: Color) -> some View {
        let value = key.map(average) ?? net
        return VStack(alignment: .leading) { Text(name).font(.caption2).foregroundStyle(.secondary); Text(value.compactCurrency).font(.system(.subheadline, design: .rounded).weight(.bold).monospacedDigit()).foregroundStyle(color).fitOneLine() }.frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Keeps the newest month fully visible when the widget first lays out or receives data.
struct MonthlyAverageMonthPicker: View {
    let trend: [MonthlyTrend]
    let completeMonths: Set<String>
    let selected: Set<String>
    let toggle: (String) -> Void

    private var newestMonth: String? { trend.last?.month }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(trend) { month in
                        let isSelected = selected.contains(month.month)
                        Button(month.month.monthLabel) { toggle(month.month) }
                            .font(.caption)
                            .buttonStyle(.bordered)
                            .tint(isSelected ? Theme.brand : .secondary)
                            .italic(!completeMonths.contains(month.month) && !isSelected)
                            .id(month.month)
                    }
                }
                .padding(.horizontal, 1)
            }
            .onAppear { showNewestMonth(using: proxy) }
            .onChange(of: newestMonth) { _ in showNewestMonth(using: proxy) }
        }
    }

    private func showNewestMonth(using proxy: ScrollViewProxy) {
        guard let newestMonth else { return }
        DispatchQueue.main.async {
            proxy.scrollTo(newestMonth, anchor: .trailing)
        }
    }
}

struct SpendingChartWidget: View { @EnvironmentObject var store: MoneyStore
    var body: some View { WidgetCard("Spending by category") { Chart(store.summary?.spendingByCategory ?? []) { item in BarMark(x: .value("Spent", item.total), y: .value("Category", item.category.pretty)).foregroundStyle(by: .value("Category", item.category.pretty)).cornerRadius(5) }.chartForegroundStyleScale(range: Theme.chartScale).chartLegend(.hidden).frame(height: 230) } }
}
struct IncomeExpenseChartWidget: View { @EnvironmentObject var store: MoneyStore
    var body: some View { WidgetCard("Income vs expense") { Chart { ForEach(store.summary?.monthlyTrend ?? []) { m in BarMark(x: .value("Month", m.month.monthName), y: .value("Income", m.income)).foregroundStyle(Theme.brand); BarMark(x: .value("Month", m.month.monthName), y: .value("Expense", m.expense)).foregroundStyle(Theme.negative) } }.frame(height: 220) } }
}
struct RecentTransactionsWidget: View { @EnvironmentObject var store: MoneyStore
    var body: some View { WidgetCard("Recent transactions") { ForEach(store.transactions.prefix(8)) { TransactionRow(transaction: $0) } } }
}
struct AccountBalancesWidget: View { @EnvironmentObject var store: MoneyStore
    var body: some View { WidgetCard("Account balances") { ForEach(store.accounts) { account in HStack { VStack(alignment: .leading) { Text(account.name).font(.subheadline.bold()); Text("\((account.subtype ?? account.type).pretty) ••\(account.mask ?? "")").font(.caption).foregroundStyle(.secondary) }; Spacer(); Text(account.currentBalance?.currency ?? "—").font(.subheadline.weight(.semibold).monospacedDigit()).fitOneLine() } } } }
}

struct BankConnectionWidget: View {
    @EnvironmentObject var store: MoneyStore
    private var linkedItems: [Account] {
        Dictionary(
            grouping: store.accounts.filter { $0.plaidAccountId != "manual-local" },
            by: \.itemId
        )
        .values
        .compactMap(\.first)
        .sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
    }

    var body: some View {
        WidgetCard(!store.hasLinkedBank ? "Connect your bank" : "Bank connection") {
            if !store.hasLinkedBank {
                TagBadge(text: "Recommended", symbol: "star.fill", tint: Theme.honey)
                Text("Linking your bank automatically imports balances and transactions so your budgets stay current.")
                    .font(.subheadline).foregroundStyle(.secondary)
            } else {
                let linkedCount = store.accounts.filter { $0.plaidAccountId != "manual-local" }.count
                Text("\(linkedCount) account\(linkedCount == 1 ? "" : "s") connected")
                    .font(.subheadline).foregroundStyle(.secondary)
                ForEach(linkedItems) { account in
                    PlaidLinkButton(
                        itemId: account.itemId,
                        title: "Reconnect \(account.name)"
                    )
                }
            }
            PlaidLinkButton()
        }
    }
}

struct PlaidLinkButton: View {
    @EnvironmentObject var store: MoneyStore
    var itemId: Int?
    var title: String?
    @State private var linkSession: PlaidLinkSession?
    @State private var isPresenting = false
    @State private var isPreparing = false
    @State private var isReady = false
    @State private var linkError: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button {
                if isReady { isPresenting = true } else { prepare() }
            } label: {
                Label(
                    title ?? (!store.hasLinkedBank ? "Connect a bank" : "Connect another bank"),
                    systemImage: itemId == nil ? "building.columns.fill" : "arrow.triangle.2.circlepath"
                )
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent).tint(Theme.brand)
            .disabled(isPreparing)
            if isPreparing { ProgressView("Preparing secure connection…").font(.caption) }
            if let linkError { Text(linkError).font(.caption).foregroundStyle(Theme.negative) }
        }
        .task { if linkSession == nil { await prepareSession() } }
        .sheet(isPresented: $isPresenting, onDismiss: resetSession) {
            if let linkSession { linkSession.sheet() }
        }
    }

    private func prepare() {
        isPreparing = true
        Task { await prepareSession(openWhenReady: true) }
    }

    @MainActor private func prepareSession(openWhenReady: Bool = false) async {
        guard linkSession == nil else {
            isPreparing = false
            if openWhenReady && isReady { isPresenting = true }
            return
        }
        isPreparing = true; linkError = nil
        do {
            let token = try await store.createBankLinkToken(itemId: itemId)
            let configuration = LinkTokenConfiguration(
                token: token,
                onSuccess: { success in
                    Task { @MainActor in
                        isPresenting = false
                        do {
                            try await store.finishBankLink(
                                publicToken: success.publicToken,
                                updateMode: itemId != nil
                            )
                        } catch {
                            linkError = error.localizedDescription
                        }
                        resetSession()
                    }
                },
                onExit: { exit in
                    Task { @MainActor in
                        isPresenting = false
                        if exit.error != nil { linkError = "Bank connection was not completed. Please try again." }
                        resetSession()
                    }
                },
                onEvent: { _ in },
                onLoad: {
                    Task { @MainActor in
                        isReady = true; isPreparing = false
                        if openWhenReady { isPresenting = true }
                    }
                }
            )
            linkSession = try Plaid.createPlaidLinkSession(configuration: configuration)
        } catch {
            isPreparing = false
            linkError = error.localizedDescription
        }
    }

    @MainActor private func resetSession() {
        linkSession = nil; isReady = false; isPreparing = false
    }
}

// MARK: - Finances

struct FinancesView: View {
    @EnvironmentObject private var store: MoneyStore
    @AppStorage(LocalUIStateKey.financesSection) private var section = "Overview"
    @State private var addingManual = false
    private let sections = ["Overview", "Transactions", "Budgets"]

    var body: some View {
        VStack(spacing: 10) {
            if !store.hasLinkedBank { BankRecommendationBanner { addingManual = true } }
            if let notice = store.bankRefreshNotice {
                BankRefreshNotice(notice: notice) {
                    store.bankRefreshNotice = nil
                }
            }
            Picker("Section", selection: $section) {
                ForEach(sections, id: \.self) { item in
                    Text(item)
                }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal)
            Group {
                switch section {
                case "Transactions": TransactionsView()
                case "Budgets": BudgetsView()
                default: FinanceOverviewView()
                }
            }
        }
        .navigationTitle("Finances")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if #available(iOS 26.0, *) {
                ToolbarItemGroup(placement: .navigationBarTrailing) {
                    financeToolbarButtons
                }
                .sharedBackgroundVisibility(.hidden)
            } else {
                ToolbarItemGroup(placement: .navigationBarTrailing) {
                    financeToolbarButtons
                }
            }
        }
        .background(Theme.canvas)
        .sheet(isPresented: $addingManual) { AddTransactionView() }
        .onAppear {
            if !sections.contains(section) { section = "Overview" }
        }
    }

    @ViewBuilder private var financeToolbarButtons: some View {
        if section == "Transactions" {
            Button { addingManual = true } label: {
                Image(systemName: "plus")
                    .accessibilityLabel("Add transaction")
            }
            .buttonStyle(.plain)
        }
        Button {
            Task { await store.refreshFinances() }
        } label: {
            if store.financeRefreshInFlight {
                ProgressView()
                    .controlSize(.small)
                    .accessibilityLabel("Refreshing finances")
            } else {
                Image(systemName: "arrow.clockwise")
                    .accessibilityLabel("Refresh finances")
            }
        }
        .buttonStyle(.plain)
        .disabled(store.financeRefreshInFlight)
        NavigationLink {
            AccountsView()
                .navigationTitle("Accounts")
                .navigationBarTitleDisplayMode(.inline)
        } label: {
            Image(systemName: "gearshape")
                .accessibilityLabel("Account settings")
        }
        .buttonStyle(.plain)
    }
}

struct BankRefreshNotice: View {
    let notice: String
    let dismiss: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "building.columns")
                .foregroundStyle(Theme.honey)
            Text(notice)
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer(minLength: 4)
            Button(action: dismiss) {
                Image(systemName: "xmark")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss bank status")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Theme.honey.opacity(0.1), in: RoundedRectangle(cornerRadius: 14))
        .padding(.horizontal)
    }
}

struct BankRecommendationBanner: View {
    let addManually: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack { Label("Connect a bank", systemImage: "building.columns.fill").font(.headline).foregroundStyle(Theme.brand); Spacer(); TagBadge(text: "Recommended", tint: Theme.honey) }
            Text("Automatically import balances and transactions. Plaid handles your bank login securely; this app never sees your credentials.")
                .font(.caption).foregroundStyle(.secondary)
            HStack { PlaidLinkButton(); Button("Enter manually", action: addManually).buttonStyle(.bordered) }
        }
        .padding(16).background(Theme.brand.opacity(0.08), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Theme.brand.opacity(0.25)))
        .padding(.horizontal)
    }
}
struct FinanceOverviewView: View {
    @EnvironmentObject var store: MoneyStore

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 14) {
                UnbudgetedTransactionsNotice(transactions: store.transactions)
                LeftToSpendWidget(allowsDelete: true)
                MonthlyAverageWidget()
                SpendingChartWidget()
                IncomeExpenseChartWidget()
                CategoryTransactionsWidget()
            }
            .padding(.horizontal)
            .padding(.top, 2)
            .padding(.bottom)
        }
        .refreshable {
            await store.refreshFinances()
        }
    }
}

struct CategoryMerchant: Identifiable { var id: String { key }; let key: String; let items: [Transaction]; let total: Double; let latest: String }
struct TransactionCategoryGroup: Identifiable { var id: String { category }; let category: String; let merchants: [CategoryMerchant]; let count: Int; let total: Double }

struct CategoryTransactionsWidget: View {
    @EnvironmentObject var store: MoneyStore
    @StoredStringSet(LocalUIStateKey.transactionCategoriesExpanded) private var expanded
    @State private var newCategoryMerchant: CategoryMerchant?
    @State private var newCategory = ""
    private let transfers = Set(["LOAN_PAYMENTS", "LOAN_DISBURSEMENTS", "TRANSFER_IN", "TRANSFER_OUT"])
    private var spending: [Transaction] { store.transactions.filter { $0.date >= Date.threeMonthStart && !transfers.contains($0.effectiveCategory) } }
    private var categories: [String] { Array(Set(spending.map(\.effectiveCategory))).sorted() }
    private var groups: [TransactionCategoryGroup] {
        Dictionary(grouping: spending, by: \.effectiveCategory).map { category, items in
            TransactionCategoryGroup(category: category, merchants: merchantGroups(items), count: items.count, total: items.reduce(0) { $0 + $1.amount })
        }.sorted { $0.total > $1.total }
    }
    private func merchantGroups(_ items: [Transaction]) -> [CategoryMerchant] {
        let grouped: [String: [Transaction]] = Dictionary(grouping: items) { transaction in transaction.merchantName ?? transaction.name }
        let result: [CategoryMerchant] = grouped.map { entry in
            let rows = entry.value
            let total = rows.reduce(0.0) { sum, transaction in sum + transaction.amount }
            return CategoryMerchant(key: entry.key, items: rows, total: total, latest: rows.map(\.date).max() ?? "")
        }
        return result.sorted { lhs, rhs in lhs.latest == rhs.latest ? lhs.total > rhs.total : lhs.latest > rhs.latest }
    }
    var body: some View {
        WidgetCard("Transactions by category (past 3 months)") {
            if groups.isEmpty { Text("No transactions.").foregroundStyle(.secondary) }
            ForEach(groups) { group in
                let open = expanded.contains(group.category)
                Button { toggle(group.category) } label: {
                    HStack { Image(systemName: open ? "chevron.down" : "chevron.right").font(.caption2); Text(group.category.pretty).fontWeight(.medium); Text("· \(group.count) txns").foregroundStyle(.secondary); Spacer(); Text(group.total.currency).foregroundStyle(.secondary) }
                }.buttonStyle(.plain)
                if open {
                    ForEach(group.merchants) { merchant in
                        VStack(alignment: .leading, spacing: 5) {
                            HStack {
                                Text(merchant.key).lineLimit(1)
                                if merchant.items.count > 1 { Text("×\(merchant.items.count)").font(.caption2).padding(.horizontal, 6).background(Color.secondary.opacity(0.12)).clipShape(Capsule()) }
                                Spacer(); Text(merchant.total.currency).font(.subheadline.monospacedDigit()).foregroundStyle(merchant.total < 0 ? Theme.brand : .primary)
                            }
                            HStack {
                                Text(merchant.latest.shortDate).font(.caption).foregroundStyle(.secondary)
                                Spacer()
                                Menu {
                                    ForEach(categories, id: \.self) { category in Button(category.pretty) { recategorize(merchant, as: category) } }
                                    Divider(); Button("New category…") { newCategory = ""; newCategoryMerchant = merchant }
                                } label: { Label(group.category.pretty, systemImage: "chevron.up.chevron.down").font(.caption) }
                            }
                        }.padding(.leading, 18).padding(.vertical, 3)
                    }
                }
                Divider()
            }
        }
        .alert("New category", isPresented: Binding(get: { newCategoryMerchant != nil }, set: { if !$0 { newCategoryMerchant = nil } })) {
            TextField("Category name", text: $newCategory)
            Button("Cancel", role: .cancel) { newCategoryMerchant = nil }
            Button("Save") { if let merchant = newCategoryMerchant { recategorize(merchant, as: newCategory) }; newCategoryMerchant = nil }.disabled(newCategory.trimmingCharacters(in: .whitespaces).isEmpty)
        } message: { Text("This creates a rule for this merchant, including past and future transactions.") }
    }
    private func toggle(_ category: String) {
        var next = expanded
        if next.contains(category) { next.remove(category) } else { next.insert(category) }
        expanded = next
    }
    private func recategorize(_ merchant: CategoryMerchant, as category: String) { guard let id = merchant.items.first?.id else { return }; Task { await store.setMerchantCategory(transactionId: id, category: category) } }
}
struct UnbudgetedTransactionsNotice: View {
    let transactions: [Transaction]
    @State private var reviewing = false

    private var rows: [Transaction] {
        transactions.filter { $0.date.hasPrefix(MoneyStore.currentMonth) && $0.isBudgeted == false }
    }
    @ViewBuilder var body: some View {
        if !rows.isEmpty {
            ReviewPrompt(
                symbol: "exclamationmark.triangle.fill",
                tint: Theme.honey,
                title: "Review \(rows.count) unbudgeted transaction\(rows.count == 1 ? "" : "s")",
                subtitle: "Choose a budget category for each transaction."
            ) { reviewing = true }
            .sheet(isPresented: $reviewing) { UnbudgetedTransactionsReviewView() }
        }
    }
}

struct ReviewPrompt: View {
    let symbol: String
    let tint: Color
    let title: String
    let subtitle: String
    let review: () -> Void

    var body: some View {
        Button(action: review) {
            HStack(spacing: 10) {
                Image(systemName: symbol)
                    .font(.title3)
                    .foregroundStyle(tint)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.subheadline.weight(.semibold))
                    Text(subtitle).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            .padding(12)
            .background(tint.opacity(0.08), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

struct P2PReviewPrompt: View {
    let count: Int
    let review: () -> Void

    var body: some View {
        ReviewPrompt(
            symbol: "arrow.left.arrow.right.circle.fill",
            tint: Theme.brand,
            title: "Review \(count) Zelle/Venmo payment\(count == 1 ? "" : "s")",
            subtitle: "Link reimbursements, assign spending, or dismiss."
        ) { review() }
    }
}

enum AgentShortcutAction {
    case chat
    case categorizeUnbudgeted
}

struct AgentShortcutRequest {
    let prompt: String
    let action: AgentShortcutAction

    static let unbudgetedTransactions = AgentShortcutRequest(
        prompt: """
        Can you categorize all of my unbudgeted transactions from this month? Use my existing budgets and leave anything you're unsure about for me to review.
        """,
        action: .categorizeUnbudgeted
    )

    static let peerPayments = AgentShortcutRequest(
        prompt: """
        Can you categorize all of my unresolved Zelle and Venmo transactions? Use my existing categories and leave anything you're unsure about for me to review.
        """,
        action: .chat
    )
}

/// One user tap, identified independently from the SwiftUI view presenting it.
/// Keeping this id stable prevents sheet reconstruction from submitting the same
/// contextual request more than once.
struct AgentShortcutInvocation: Identifiable {
    let id = UUID()
    let request: AgentShortcutRequest
}

/// A reusable contextual entry point into the same Copilot conversation and tool loop.
/// New surfaces only need to supply a focused request; they do not need custom agent UI.
struct AskAgentButton: View {
    @EnvironmentObject private var store: MoneyStore
    let request: AgentShortcutRequest
    @State private var invocation: AgentShortcutInvocation?

    var body: some View {
        Button { invocation = AgentShortcutInvocation(request: request) } label: {
            HStack(spacing: 10) {
                Image(systemName: "sparkles")
                    .foregroundStyle(Theme.brand)
                Text("Ask Audel")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityHint("Opens Audel and sends a request to review these transactions")
        .sheet(item: $invocation) { shortcut in
            CopilotView(initialShortcut: shortcut)
                .environmentObject(store)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
    }
}

/// Reusable contextual composer for surfaces where a preset Audel shortcut is
/// helpful but the user may want to give more specific instructions.
struct AudelPromptComposer: View {
    @EnvironmentObject private var store: MoneyStore
    let context: String
    let placeholder: String
    @State private var prompt = ""
    @State private var invocation: AgentShortcutInvocation?

    var body: some View {
        HStack(spacing: 9) {
            Image(systemName: "sparkles")
                .foregroundStyle(Theme.brand)
            TextField(placeholder, text: $prompt, axis: .vertical)
                .lineLimit(1...3)
                .onSubmit(submit)
            Button(action: submit) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.title2)
                    .foregroundStyle(Theme.brand)
            }
            .buttonStyle(.plain)
            .disabled(cleanPrompt.isEmpty || store.copilotRequestInFlight)
            .accessibilityLabel("Send to Audel")
        }
        .sheet(item: $invocation) { shortcut in
            CopilotView(initialShortcut: shortcut)
                .environmentObject(store)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
    }

    private var cleanPrompt: String {
        prompt.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func submit() {
        guard !cleanPrompt.isEmpty, !store.copilotRequestInFlight else { return }
        let request = AgentShortcutRequest(
            prompt: "\(context): \(cleanPrompt)",
            action: .chat
        )
        prompt = ""
        invocation = AgentShortcutInvocation(request: request)
    }
}

struct UnbudgetedTransactionsReviewView: View {
    @EnvironmentObject private var store: MoneyStore
    @SwiftUI.Environment(\.dismiss) private var dismiss
    @State private var savingId: Int?
    @State private var selectedIds: Set<Int> = []
    @State private var bulkSaving = false
    @State private var visibleCount = 20
    private let pageSize = 20

    private var transactions: [Transaction] {
        store.transactions.filter {
            $0.date.hasPrefix(MoneyStore.currentMonth) && $0.isBudgeted == false
        }.sorted { $0.date > $1.date }
    }
    private var visibleTransactions: [Transaction] {
        Array(transactions.prefix(visibleCount))
    }
    private var selectedTransactions: [Transaction] {
        transactions.filter { selectedIds.contains($0.id) }
    }
    private var budgetCategories: [String] {
        Array(Set(store.budgets.map(\.category))).sorted()
    }

    var body: some View {
        NavigationStack {
            List {
                if !transactions.isEmpty {
                    Section {
                        AskAgentButton(request: .unbudgetedTransactions)
                        AudelPromptComposer(
                            context: "For my unbudgeted transactions this month",
                            placeholder: "Tell Audel what to do"
                        )
                    }
                    Section {
                        ForEach(visibleTransactions) { transaction in
                            unbudgetedRow(transaction)
                        }
                        if visibleCount < transactions.count {
                            HStack {
                                Spacer()
                                ProgressView().controlSize(.small)
                                Spacer()
                            }
                            .onAppear { loadNextPage() }
                        }
                    } footer: { Text("Choose a budget for each transaction. This changes only that transaction.") }
                } else {
                    VStack(spacing: 8) {
                        Image(systemName: "checkmark.circle")
                            .font(.largeTitle)
                            .foregroundStyle(Theme.brand)
                        Text("All caught up").font(.headline)
                        Text("Every spending transaction this month has a matching budget.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 30)
                }
            }
            .navigationTitle("Unbudgeted spending")
            .navigationBarTitleDisplayMode(.inline)
            .safeAreaInset(edge: .bottom) {
                if !selectedTransactions.isEmpty { bulkActionBar }
            }
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    if !transactions.isEmpty {
                        Button(selectedIds.count == transactions.count ? "Clear" : "Select all") {
                            selectedIds = selectedIds.count == transactions.count
                                ? []
                                : Set(transactions.map(\.id))
                        }
                    }
                }
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
        }
    }

    private func unbudgetedRow(_ transaction: Transaction) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 10) {
                Button { toggleSelection(transaction.id) } label: {
                    Image(systemName: selectedIds.contains(transaction.id) ? "checkmark.circle.fill" : "circle")
                        .font(.title3)
                        .foregroundStyle(selectedIds.contains(transaction.id) ? Theme.brand : Color.secondary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(
                    selectedIds.contains(transaction.id) ? "Deselect transaction" : "Select transaction"
                )
                VStack(alignment: .leading, spacing: 2) {
                    Text(transaction.merchantName ?? transaction.name)
                        .font(.subheadline.weight(.medium))
                    Text("\(transaction.date.shortDate) · \(transaction.effectiveCategory.pretty)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text(transaction.amount.currency)
                    .font(.subheadline.weight(.semibold).monospacedDigit())
                    .fitOneLine()
            }
            HStack(spacing: 10) {
                Menu {
                    ForEach(budgetCategories, id: \.self) { category in
                        Button(category.pretty) { categorize(transaction, as: category) }
                    }
                } label: {
                    Text("Choose budget")
                        .lineLimit(1)
                        .fixedSize(horizontal: true, vertical: false)
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(budgetCategories.isEmpty || savingId != nil)
                if budgetCategories.isEmpty {
                    Text("Create a budget first")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
            }
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
        .onLongPressGesture { toggleSelection(transaction.id) }
        .disabled(savingId == transaction.id || bulkSaving)
    }

    private var bulkActionBar: some View {
        VStack(spacing: 9) {
            HStack {
                Text("\(selectedTransactions.count) selected")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Button("Clear") { selectedIds.removeAll() }
                    .font(.caption.weight(.medium))
            }
            Menu {
                ForEach(budgetCategories, id: \.self) { category in
                    Button(category.pretty) { bulkCategorize(as: category) }
                }
            } label: {
                Label("Assign budget category", systemImage: "folder")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(budgetCategories.isEmpty || bulkSaving)
        }
        .padding(.horizontal)
        .padding(.vertical, 10)
        .background(.bar)
    }

    private func loadNextPage() {
        visibleCount = min(visibleCount + pageSize, transactions.count)
    }

    private func categorize(_ transaction: Transaction, as category: String) {
        guard savingId == nil else { return }
        savingId = transaction.id
        Task {
            if await store.updateTransactionCategory(transaction.id, category: category) {
                selectedIds.remove(transaction.id)
            }
            savingId = nil
        }
    }

    private func toggleSelection(_ id: Int) {
        if selectedIds.contains(id) {
            selectedIds.remove(id)
        } else {
            selectedIds.insert(id)
        }
    }

    private func bulkCategorize(as category: String) {
        let ids = selectedTransactions.map(\.id)
        guard !ids.isEmpty, !bulkSaving else { return }
        bulkSaving = true
        Task {
            if await store.bulkUpdateTransactionCategory(ids, category: category) {
                selectedIds.subtract(ids)
            }
            bulkSaving = false
        }
    }
}

struct UnbudgetedTransactionsDashboardWidget: View {
    @EnvironmentObject private var store: MoneyStore

    private var hasUnbudgetedTransactions: Bool {
        store.transactions.contains {
            $0.date.hasPrefix(MoneyStore.currentMonth) && $0.isBudgeted == false
        }
    }

    var body: some View {
        WidgetCard("Unbudgeted spending") {
            if hasUnbudgetedTransactions {
                UnbudgetedTransactionsNotice(transactions: store.transactions)
            } else {
                Text("All current spending categories have monthly budgets.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

struct PeerPaymentReviewDashboardWidget: View {
    @EnvironmentObject private var store: MoneyStore
    @State private var reviewing = false

    private var pendingCount: Int {
        store.transactions.filter(\.needsPeerPaymentReview).count
    }

    var body: some View {
        WidgetCard("Zelle & Venmo review") {
            if pendingCount > 0 {
                P2PReviewPrompt(count: pendingCount) { reviewing = true }
            } else {
                Text("All peer payments have been reviewed.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .sheet(isPresented: $reviewing) { PeerPaymentReviewView() }
    }
}

struct TransactionRow: View {
    let transaction: Transaction
    var manageReimbursement: (() -> Void)? = nil
    var unlinkReimbursement: (() -> Void)? = nil

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(transaction.merchantName ?? transaction.name).font(.subheadline)
                Text("\(transaction.date.shortDate) · \(transaction.effectiveCategory.pretty)")
                    .font(.caption).foregroundStyle(.secondary)
                if transaction.isBudgeted == false {
                    Label("No matching budget", systemImage: "flag.fill")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(Theme.honey)
                }
                if transaction.isIncomingPeerPayment {
                    reimbursementControls
                }
            }
            Spacer()
            Text(transaction.amount.currency)
                .foregroundStyle(transaction.amount < 0 ? Theme.brand : .primary)
                .font(.subheadline.weight(.medium).monospacedDigit()).fitOneLine()
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder private var reimbursementControls: some View {
        HStack(spacing: 10) {
            if transaction.reimbursesTransactionId != nil {
                Label("Linked reimbursement", systemImage: "arrow.uturn.backward")
                    .font(.caption2.weight(.medium)).foregroundStyle(Theme.brand)
            } else if let category = transaction.reimbursementCategory {
                Label("Reduces \(category.pretty)", systemImage: "arrow.uturn.backward")
                    .font(.caption2.weight(.medium)).foregroundStyle(Theme.brand)
            }
            if let manageReimbursement {
                Button(transaction.reimbursesTransactionId == nil ? "Link expense" : "Change", action: manageReimbursement)
                    .font(.caption2.weight(.semibold)).buttonStyle(.plain).foregroundStyle(Theme.brand)
            }
            if let unlinkReimbursement, transaction.reimbursesTransactionId != nil {
                Button("Unlink", action: unlinkReimbursement)
                    .font(.caption2).buttonStyle(.plain).foregroundStyle(.secondary)
            }
        }
    }
}
struct TransactionsView: View {
    @EnvironmentObject private var store: MoneyStore
    @State private var search = ""
    @State private var reviewingPeerPayments = false
    @State private var reimbursementToLink: Transaction?
    @State private var editingManualTransaction: Transaction?

    private var visible: [Transaction] {
        guard !search.isEmpty else { return store.transactions }
        return store.transactions.filter {
            ($0.merchantName ?? $0.name).localizedCaseInsensitiveContains(search)
                || $0.effectiveCategory.localizedCaseInsensitiveContains(search)
        }
    }
    private var pendingPeerPayments: [Transaction] {
        store.transactions.filter(\.needsPeerPaymentReview)
    }

    var body: some View {
        VStack(spacing: 0) {
            TransactionSearchField(text: $search)
                .padding(.horizontal)
                .padding(.vertical, 8)
            VStack(spacing: 8) {
                UnbudgetedTransactionsNotice(transactions: store.transactions)
                if !pendingPeerPayments.isEmpty {
                    P2PReviewPrompt(count: pendingPeerPayments.count) { reviewingPeerPayments = true }
                }
            }
            .padding(.horizontal)
            .padding(.bottom, pendingPeerPayments.isEmpty ? 0 : 4)
            List {
                ForEach(visible) { transaction in
                    TransactionRow(
                        transaction: transaction,
                        manageReimbursement: transaction.isIncomingPeerPayment
                            ? { reimbursementToLink = transaction } : nil,
                        unlinkReimbursement: transaction.reimbursesTransactionId != nil
                            ? {
                                Task<Void, Never> {
                                    _ = await store.setReimbursement(transaction.id, targetId: nil)
                                }
                            } : nil
                    )
                        .pressAndHoldToEdit(enabled: transaction.isManual) {
                            editingManualTransaction = transaction
                        }
                }
            }
            .listStyle(.plain)
            .refreshable {
                await store.refreshFinances()
            }
        }
        .sheet(isPresented: $reviewingPeerPayments) { PeerPaymentReviewView() }
        .sheet(item: $reimbursementToLink) { ReimbursementExpensePicker(reimbursement: $0) }
        .sheet(item: $editingManualTransaction) { transaction in
            AddTransactionView(editing: transaction)
        }
    }
}

struct PeerPaymentReviewView: View {
    @EnvironmentObject private var store: MoneyStore
    @SwiftUI.Environment(\.dismiss) private var dismiss
    @State private var selectedIds: Set<Int> = []
    @State private var bulkLinking = false
    @State private var saving = false

    private var incoming: [Transaction] {
        store.transactions.filter { $0.isIncomingPeerPayment && $0.needsPeerPaymentReview }
    }
    private var outgoing: [Transaction] {
        store.transactions.filter { $0.isOutgoingPeerPayment && $0.needsPeerPaymentReview }
    }
    private var pending: [Transaction] { incoming + outgoing }
    private var selectedTransactions: [Transaction] {
        pending.filter { selectedIds.contains($0.id) }
    }
    private var selectedIncoming: [Transaction] {
        selectedTransactions.filter(\.isIncomingPeerPayment)
    }
    private var categories: [String] {
        let excluded = Set(["INCOME", "TRANSFER_IN", "TRANSFER_OUT", "LOAN_PAYMENTS", "LOAN_DISBURSEMENTS", "UNCATEGORIZED"])
        let values = Set(store.budgets.map(\.category) + store.transactions.map(\.effectiveCategory))
            .subtracting(excluded)
        let budgeted = Set(store.budgets.map(\.category))
        return values.sorted {
            if budgeted.contains($0) != budgeted.contains($1) { return budgeted.contains($0) }
            return $0 < $1
        }
    }

    var body: some View {
        NavigationStack {
            List {
                if !incoming.isEmpty || !outgoing.isEmpty {
                    Section {
                        AskAgentButton(request: .peerPayments)
                        AudelPromptComposer(
                            context: "For my unresolved Zelle and Venmo transactions",
                            placeholder: "Tell Audel what to do"
                        )
                    }
                }
                if !incoming.isEmpty {
                    Section {
                        ForEach(incoming) { transaction in
                            peerPaymentRow(transaction, received: true)
                        }
                    } header: { Text("Received — reimburse an expense") }
                      footer: { Text("Link it to the exact expense, apply it to a budget, or mark it as not a reimbursement so it does not change spending.") }
                }
                if !outgoing.isEmpty {
                    Section {
                        ForEach(outgoing) { transaction in
                            peerPaymentRow(transaction, received: false)
                        }
                    } header: { Text("Sent — was it spending?") }
                      footer: { Text("Choose a category if this was spending, or mark it as not spending so it stays out of spending totals.") }
                }
                if incoming.isEmpty && outgoing.isEmpty {
                    VStack(spacing: 8) {
                        Image(systemName: "checkmark.circle").font(.largeTitle).foregroundStyle(Theme.brand)
                        Text("All caught up").font(.headline)
                        Text("There are no Zelle or Venmo payments waiting for review.")
                            .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity).padding(.vertical, 30)
                }
            }
            .navigationTitle("Review payments")
            .navigationBarTitleDisplayMode(.inline)
            .safeAreaInset(edge: .bottom) {
                if !selectedTransactions.isEmpty { bulkActionBar }
            }
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    if !pending.isEmpty {
                        Button(selectedIds.count == pending.count ? "Clear" : "Select all") {
                            selectedIds = selectedIds.count == pending.count
                                ? []
                                : Set(pending.map(\.id))
                        }
                    }
                }
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .sheet(isPresented: $bulkLinking) {
                ReimbursementExpensePicker(reimbursements: selectedIncoming) {
                    selectedIds.removeAll()
                }
            }
        }
    }

    private func peerPaymentRow(_ transaction: Transaction, received: Bool) -> some View {
        Button {
            if selectedIds.contains(transaction.id) {
                selectedIds.remove(transaction.id)
            } else {
                selectedIds.insert(transaction.id)
            }
        } label: {
            HStack {
                Image(systemName: selectedIds.contains(transaction.id) ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundStyle(selectedIds.contains(transaction.id) ? Theme.brand : Color.secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(transaction.merchantName ?? transaction.name)
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(.primary)
                    Text(transaction.date.shortDate).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Text(transaction.amount.currency)
                    .font(.subheadline.weight(.semibold).monospacedDigit())
                    .foregroundStyle(received ? Theme.brand : .primary)
            }
        }
        .buttonStyle(.plain)
        .padding(.vertical, 4)
        .disabled(saving)
    }

    private var bulkActionBar: some View {
        VStack(spacing: 9) {
            HStack {
                Text("\(selectedTransactions.count) selected")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Button("Clear") { selectedIds.removeAll() }
                    .font(.caption.weight(.medium))
            }
            HStack(spacing: 10) {
                Menu {
                    ForEach(categories, id: \.self) { category in
                        Button(category.pretty) { bulkResolve(category: category) }
                    }
                } label: {
                    Label("Assign category", systemImage: "folder")
                }
                .buttonStyle(.borderedProminent)

                if selectedIncoming.count == selectedTransactions.count {
                    Button { bulkLinking = true } label: {
                        Label("Link expense", systemImage: "link")
                    }
                    .buttonStyle(.bordered)
                }

                Menu {
                    if selectedIncoming.count == selectedTransactions.count {
                        Button("Not reimbursements") { bulkResolve(category: "TRANSFER_IN") }
                    } else if selectedIncoming.isEmpty {
                        Button("Not spending") { bulkResolve(category: "TRANSFER_OUT") }
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                        .font(.title3)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("More bulk actions")
            }
            .disabled(saving)
        }
        .padding(.horizontal)
        .padding(.vertical, 10)
        .background(.bar)
    }

    private func bulkResolve(category: String) {
        let ids = selectedTransactions.map(\.id)
        guard !ids.isEmpty, !saving else { return }
        saving = true
        Task {
            if await store.bulkUpdateTransactionCategory(ids, category: category) {
                selectedIds.removeAll()
            }
            saving = false
        }
    }
}

struct ReimbursementExpensePicker: View {
    @EnvironmentObject private var store: MoneyStore
    @SwiftUI.Environment(\.dismiss) private var dismiss
    let reimbursements: [Transaction]
    var onLinked: () -> Void = {}
    @State private var search = ""
    @State private var saving = false

    private let transfers = Set(["LOAN_PAYMENTS", "LOAN_DISBURSEMENTS", "TRANSFER_IN", "TRANSFER_OUT"])
    init(reimbursement: Transaction, onLinked: @escaping () -> Void = {}) {
        reimbursements = [reimbursement]
        self.onLinked = onLinked
    }
    init(reimbursements: [Transaction], onLinked: @escaping () -> Void = {}) {
        self.reimbursements = reimbursements
        self.onLinked = onLinked
    }
    private var candidates: [Transaction] {
        let reimbursementIds = Set(reimbursements.map(\.id))
        return store.transactions
            .filter { !reimbursementIds.contains($0.id) && $0.amount > 0 && !transfers.contains($0.effectiveCategory) }
            .filter {
                search.isEmpty
                    || ($0.merchantName ?? $0.name).localizedCaseInsensitiveContains(search)
                    || $0.effectiveCategory.localizedCaseInsensitiveContains(search)
            }
            .sorted { $0.date > $1.date }
    }

    var body: some View {
        NavigationStack {
            List(candidates) { expense in
                Button {
                    link(to: expense)
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(expense.merchantName ?? expense.name).foregroundStyle(.primary)
                            Text("\(expense.date.shortDate) · \(expense.effectiveCategory.pretty)")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(expense.amount.currency)
                            .font(.subheadline.monospacedDigit()).foregroundStyle(.primary)
                    }
                }
                .disabled(saving)
            }
            .searchable(text: $search, prompt: "Search an expense")
            .navigationTitle(reimbursements.count == 1 ? "Reimbursed expense" : "Link reimbursements")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            .overlay {
                if candidates.isEmpty {
                    VStack(spacing: 8) {
                        Image(systemName: "magnifyingglass").font(.largeTitle).foregroundStyle(.secondary)
                        Text(search.isEmpty ? "No expenses available" : "No matching expenses").font(.headline)
                        Text(search.isEmpty ? "There are no spending transactions to link." : "Try a different merchant or category.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    .multilineTextAlignment(.center).padding()
                }
            }
        }
    }

    private func link(to expense: Transaction) {
        let ids = reimbursements.map(\.id)
        guard !ids.isEmpty, !saving else { return }
        saving = true
        Task {
            let succeeded: Bool
            if ids.count == 1, let id = ids.first {
                succeeded = await store.setReimbursement(id, targetId: expense.id)
            } else {
                succeeded = await store.bulkSetReimbursement(ids, targetId: expense.id)
            }
            if succeeded {
                onLinked()
                dismiss()
            } else {
                saving = false
            }
        }
    }
}

struct TransactionSearchField: View {
    @Binding var text: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
            TextField("Merchant, description, or category", text: $text)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.search)
            if !text.isEmpty {
                Button { text = "" } label: {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Clear search")
            }
        }
        .padding(.horizontal, 12)
        .frame(minHeight: 38)
        .background(Color.secondary.opacity(0.1), in: RoundedRectangle(cornerRadius: 11, style: .continuous))
    }
}
private enum ManualTransactionType: String, CaseIterable, Identifiable {
    case expense = "Expense"
    case income = "Income"

    var id: Self { self }
    func signedAmount(_ amount: Double) -> Double { self == .expense ? amount : -amount }
}

struct AddTransactionView: View {
    @EnvironmentObject private var store: MoneyStore
    @SwiftUI.Environment(\.dismiss) private var dismiss
    @State private var type: ManualTransactionType = .expense
    @State private var accountId = 0
    @State private var date = Date()
    @State private var name = ""
    @State private var amount = ""
    @State private var confirmingDelete = false
    let editingTransaction: Transaction?

    init() {
        editingTransaction = nil
    }

    init(editing transaction: Transaction) {
        editingTransaction = transaction
        _type = State(initialValue: transaction.amount >= 0 ? .expense : .income)
        _accountId = State(initialValue: transaction.accountId)
        _date = State(initialValue: ScheduleCalendar.date(fromAPI: transaction.date))
        _name = State(initialValue: transaction.name)
        _amount = State(initialValue: abs(transaction.amount).editableNumber)
    }

    private var positiveAmount: Double? {
        guard let value = Double(amount), value > 0 else { return nil }
        return value
    }

    var body: some View {
        NavigationStack {
            Form {
                Picker("Type", selection: $type) {
                    ForEach(ManualTransactionType.allCases) { type in
                        Text(type.rawValue).tag(type)
                    }
                }
                .pickerStyle(.segmented)
                Picker("Account", selection: $accountId) {
                    Text(store.accounts.isEmpty ? "Manual finances (created automatically)" : "Manual finances").tag(0)
                    ForEach(store.accounts) { Text($0.name).tag($0.id) }
                }
                DatePicker("Date", selection: $date, displayedComponents: .date)
                TextField("Description", text: $name)
                TextField("Amount", text: $amount)
                    .keyboardType(.decimalPad)
                if let editingTransaction {
                    Section {
                        Button("Delete transaction", role: .destructive) { confirmingDelete = true }
                            .frame(maxWidth: .infinity)
                    }
                    .confirmationDialog(
                        "Delete this transaction?",
                        isPresented: $confirmingDelete,
                        titleVisibility: .visible
                    ) {
                        Button("Delete transaction", role: .destructive) {
                            Task {
                                await store.deleteTransaction(editingTransaction.id)
                                dismiss()
                            }
                        }
                        Button("Cancel", role: .cancel) {}
                    }
                }
            }
            .navigationTitle(editingTransaction == nil ? "Add transaction" : "Edit transaction")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(editingTransaction == nil ? "Add" : "Save", action: save)
                        .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || positiveAmount == nil)
                }
            }
        }
    }

    private func save() {
        guard let positiveAmount else { return }
        let signedAmount = type.signedAmount(positiveAmount)
        Task {
            if let editingTransaction {
                if await store.updateManualTransaction(
                    editingTransaction,
                    accountId: accountId,
                    date: date,
                    name: name,
                    amount: signedAmount
                ) {
                    dismiss()
                }
            } else {
                await store.addTransaction(
                    accountId: accountId,
                    date: date,
                    name: name,
                    amount: signedAmount
                )
                dismiss()
            }
        }
    }
}
struct AccountsView: View {
    @EnvironmentObject private var store: MoneyStore

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                if !store.hasLinkedBank { BankConnectionWidget() }
                ForEach(store.accounts) { account in
                    WidgetCard(account.name) {
                        Text("\((account.subtype ?? account.type).pretty) ••\(account.mask ?? "")")
                            .font(.caption).foregroundStyle(.secondary)
                        Text(account.currentBalance?.currency ?? "—")
                            .font(.heroNumber.monospacedDigit()).fitOneLine()
                    }
                }
                if store.hasLinkedBank { BankConnectionWidget() }
            }
            .padding()
        }
        .refreshable {
            await store.refreshFinances()
        }
    }
}
struct BudgetsView: View {
    @EnvironmentObject private var store: MoneyStore

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 14) {
                LeftToSpendWidget(allowsDelete: true, showsAddForm: true)
            }
            .padding(.horizontal)
            .padding(.top, 2)
            .padding(.bottom)
        }
        .refreshable {
            await store.refreshFinances()
        }
    }
}

struct AddBudgetWidget: View {
    @EnvironmentObject private var store: MoneyStore
    var usesCard = true
    var defaultPeriod = "monthly"
    var showsPeriodPicker = true
    var compact = false
    @State private var category = ""
    @State private var limit = ""
    @State private var period = "monthly"
    @State private var saving = false

    private var amount: Double? { Double(limit) }
    private var canAdd: Bool {
        !category.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (amount ?? 0) > 0
            && !saving
    }

    var body: some View {
        Group {
            if usesCard {
                WidgetCard("Add budget") { fields }
            } else {
                fields
            }
        }
        .onAppear { period = defaultPeriod }
        .onChange(of: defaultPeriod) { period = $0 }
    }

    @ViewBuilder private var fields: some View {
        if compact {
            HStack(spacing: 8) {
                TextField("Category", text: $category)
                    .textFieldStyle(.roundedBorder)
                    .textInputAutocapitalization(.words)
                    .submitLabel(.next)
                HStack(spacing: 3) {
                    Text("$").foregroundStyle(.secondary)
                    TextField("Limit", text: $limit)
                        .keyboardType(.decimalPad)
                }
                .padding(.horizontal, 8)
                .frame(width: 92)
                .frame(minHeight: 36)
                .background(Color.secondary.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
                Button("Add", action: add)
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                    .disabled(!canAdd)
            }
        } else {
            TextField("Budget", text: $category)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.words)
                .submitLabel(.next)
            HStack(spacing: 10) {
                HStack(spacing: 5) {
                    Text("$").foregroundStyle(.secondary)
                    TextField("Limit", text: $limit)
                        .keyboardType(.decimalPad)
                }
                .padding(.horizontal, 10)
                .frame(minHeight: 36)
                .background(Color.secondary.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
                Button("Add", action: add)
                    .buttonStyle(.borderedProminent)
                    .disabled(!canAdd)
            }
        }
        if showsPeriodPicker {
            Picker("Resets", selection: $period) {
                Text("Daily").tag("daily")
                Text("Weekly").tag("weekly")
                Text("Monthly").tag("monthly")
            }
            .pickerStyle(.segmented)
        }
    }

    private func add() {
        guard canAdd, let amount else { return }
        saving = true
        Task {
            if await store.addBudget(category: category, limit: amount, period: period) {
                category = ""
                limit = ""
            }
            saving = false
        }
    }
}

struct EditBudgetView: View {
    @EnvironmentObject private var store: MoneyStore
    @SwiftUI.Environment(\.dismiss) private var dismiss
    let budget: Budget
    @State private var category: String
    @State private var limit: String
    @State private var period: String
    @State private var saving = false
    @State private var confirmingDelete = false

    init(budget: Budget) {
        self.budget = budget
        _category = State(initialValue: budget.category.pretty)
        _limit = State(initialValue: budget.monthlyLimit.editableNumber)
        _period = State(initialValue: budget.period)
    }

    private var amount: Double? { Double(limit) }
    private var canSave: Bool {
        !category.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (amount ?? 0) > 0
            && !saving
    }

    var body: some View {
        NavigationStack {
            Form {
                TextField("Budget", text: $category)
                    .textInputAutocapitalization(.words)
                TextField("Limit", text: $limit)
                    .keyboardType(.decimalPad)
                Picker("Resets", selection: $period) {
                    Text("Daily").tag("daily")
                    Text("Weekly").tag("weekly")
                    Text("Monthly").tag("monthly")
                }
                .pickerStyle(.segmented)
                Section {
                    Button("Delete budget", role: .destructive) { confirmingDelete = true }
                        .frame(maxWidth: .infinity)
                }
            }
            .navigationTitle("Edit budget")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save", action: save)
                        .disabled(!canSave)
                }
            }
            .confirmationDialog(
                "Delete this budget?",
                isPresented: $confirmingDelete,
                titleVisibility: .visible
            ) {
                Button("Delete budget", role: .destructive) {
                    Task {
                        await store.deleteBudget(budget.id)
                        dismiss()
                    }
                }
                Button("Cancel", role: .cancel) {}
            }
        }
    }

    private func save() {
        guard let amount, canSave else { return }
        saving = true
        Task {
            if await store.updateBudget(
                budget,
                category: category,
                limit: amount,
                period: period
            ) {
                dismiss()
            } else {
                saving = false
            }
        }
    }
}

// MARK: - Investing

struct InvestView: View { @EnvironmentObject var store: MoneyStore
    var body: some View { ScrollView { LazyVStack(spacing: 14) { if store.portfolio?.environment != "prod" { TagBadge(text: "Sandbox — simulated money", symbol: "testtube.2", tint: Theme.honey) }; PortfolioSummaryWidget(); PortfolioPositionsWidget(); if store.portfolio == nil { EmptyWidget(text: "Portfolio unavailable. Configure read-only tastytrade OAuth in backend/.env.") } }.padding() }.background(Theme.canvas).navigationTitle("Invest").navigationBarTitleDisplayMode(.inline).refreshable { await store.loadPortfolio() } }
}
struct PortfolioSummaryWidget: View { @EnvironmentObject var store: MoneyStore
    var body: some View { ForEach(store.portfolio?.accounts ?? []) { account in WidgetCard(account.nickname ?? account.accountNumber) { HStack { MetricCell("Value", account.netLiquidatingValue); MetricCell("Cash", account.cashBalance); MetricCell("Buying power", account.equityBuyingPower) } } } }
}
struct MetricCell: View { let name: String; let value: Double?; init(_ name: String, _ value: Double?) { self.name = name; self.value = value }
    var body: some View { VStack(alignment: .leading) { Text(name).font(.caption).foregroundStyle(.secondary); Text(value?.compactCurrency ?? "—").font(.system(.subheadline, design: .rounded).weight(.bold).monospacedDigit()).fitOneLine() }.frame(maxWidth: .infinity, alignment: .leading) }
}
struct PortfolioPositionsWidget: View { @EnvironmentObject var store: MoneyStore
    var positions: [Position] { store.portfolio?.accounts.flatMap(\.positions) ?? [] }
    var body: some View { WidgetCard("Open positions") { ForEach(positions) { position in HStack { VStack(alignment: .leading) { Text(position.symbol).font(.system(.subheadline, design: .rounded).weight(.bold)); Text("\(position.instrumentType.pretty) · \(position.quantity.formatted()) shares").font(.caption).foregroundStyle(.secondary) }; Spacer(); VStack(alignment: .trailing) { Text(position.marketValue.currency).font(.subheadline.weight(.medium).monospacedDigit()).fitOneLine(); Text("@ \(position.price.currency)").font(.caption.monospacedDigit()).foregroundStyle(.secondary).fitOneLine() } }.padding(.vertical, 3) }; if positions.isEmpty { Text("No open positions.").foregroundStyle(.secondary) } } }
}

// MARK: - Copilot

private struct CopilotTopOffsetKey: PreferenceKey {
    static var defaultValue: CGFloat = -.greatestFiniteMagnitude

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

struct CopilotView: View {
    @EnvironmentObject private var store: MoneyStore
    var initialShortcut: AgentShortcutInvocation? = nil
    @State private var input = ""
    @State private var editingMessageId: UUID?
    @State private var scrollRequest = 0
    @State private var visibleMessageCount = 5
    @State private var didInitialScroll = false
    @State private var loadingEarlierMessages = false
    @State private var topTriggerOffset = -CGFloat.greatestFiniteMagnitude
    @State private var historyLoadArmed = false
    @State private var handledHistoryLoadForDrag = false
    @FocusState private var inputFocused: Bool

    private var sending: Bool { store.copilotRequestInFlight }
    private var visibleMessages: ArraySlice<ChatMessage> {
        store.messages.suffix(visibleMessageCount)
    }
    private var hasEarlierMessages: Bool {
        store.messages.count > visibleMessageCount
    }

    let starters = [
        "Add a spending chart to my dashboard",
        "Set a $500 monthly budget for eating out",
        "Create a goal to save $2,000 by December",
        "How risky is my portfolio right now?",
    ]

    var body: some View {
        VStack(spacing: 0) {
            newChatButton
            conversation
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            composer
        }
        .background(Theme.canvas)
        .task(id: initialShortcut?.id) {
            guard let initialShortcut else { return }
            store.submitAgentShortcut(initialShortcut)
        }
    }

    @ViewBuilder private var newChatButton: some View {
        if !store.messages.isEmpty {
            HStack {
                Spacer()
                Button {
                    cancelEditing()
                    store.clearChat()
                } label: {
                    Label("New chat", systemImage: "square.and.pencil")
                        .font(.caption.weight(.medium))
                }
                .foregroundStyle(.secondary)
            }
            .padding(.horizontal)
            .padding(.top, 14)
        }
    }

    private var conversation: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 12) {
                    emptyConversation
                    earlierMessagesTrigger
                    ForEach(visibleMessages) { message in
                        CopilotMessageRow(
                            message: message,
                            busy: sending,
                            onEdit: { beginEditing(message) },
                            onResend: { resend(message) }
                        )
                        .id(message.id)
                    }
                    if sending { thinkingRow }
                    Color.clear
                        .frame(height: 1)
                        .id("copilot-conversation-bottom")
                }
                .padding()
            }
            .coordinateSpace(name: "copilot-conversation")
            .scrollDismissesKeyboard(.interactively)
            .onPreferenceChange(CopilotTopOffsetKey.self) { offset in
                topTriggerOffset = offset
                guard didInitialScroll, historyLoadArmed, offset >= -72 else { return }
                loadEarlierMessages(using: proxy)
            }
            .simultaneousGesture(
                DragGesture(minimumDistance: 4)
                    .onChanged { value in
                        guard value.translation.height > 0,
                              !handledHistoryLoadForDrag else { return }
                        historyLoadArmed = true
                        if didInitialScroll, topTriggerOffset >= -72 {
                            loadEarlierMessages(using: proxy)
                        }
                    }
                    .onEnded { _ in
                        historyLoadArmed = false
                        handledHistoryLoadForDrag = false
                    }
            )
            .onChange(of: store.messages.count) { count in
                if count == 0 {
                    visibleMessageCount = 5
                }
                scrollToConversationBottom(proxy)
            }
            .onChange(of: scrollRequest) { _ in
                scrollToConversationBottom(proxy)
            }
            .onChange(of: sending) { value in
                if value { scrollToConversationBottom(proxy) }
            }
            .onChange(of: inputFocused) { focused in
                if focused { scrollToConversationBottom(proxy) }
            }
            .onReceive(
                NotificationCenter.default.publisher(
                    for: UIResponder.keyboardWillChangeFrameNotification
                )
            ) { _ in
                scrollToConversationBottom(proxy)
            }
            .onAppear {
                prepareInitialConversation(using: proxy)
            }
        }
    }

    @ViewBuilder private var earlierMessagesTrigger: some View {
        if hasEarlierMessages {
            HStack(spacing: 7) {
                if loadingEarlierMessages {
                    ProgressView()
                        .controlSize(.small)
                }
                Text(loadingEarlierMessages ? "Loading earlier messages…" : "Scroll up for earlier messages")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 28)
            .background {
                GeometryReader { geometry in
                    Color.clear.preference(
                        key: CopilotTopOffsetKey.self,
                        value: geometry.frame(in: .named("copilot-conversation")).minY
                    )
                }
            }
        }
    }

    @ViewBuilder private var emptyConversation: some View {
        if store.messages.isEmpty {
            VStack(spacing: 12) {
                IconChip(symbol: "sparkles")
                Text("Ask Audel about budgets, spending, your portfolio, or where to invest. Audel cannot place trades.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            .padding(.top, 24)

            ForEach(starters, id: \.self) { starter in
                Button(starter) { submit(starter) }
                    .buttonStyle(.bordered)
                    .font(.subheadline)
                    .disabled(sending)
            }
        }
    }

    private var thinkingRow: some View {
        HStack {
            HStack(spacing: 8) {
                ProgressView()
                Text(store.activeAgentJob.map { "\($0.stage)…" } ?? "Thinking…")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .padding(12)
            .background(Theme.card)
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            Spacer(minLength: 40)
        }
        .padding(.top, 6)
        .id("thinking")
    }

    private var composer: some View {
        VStack(spacing: 8) {
            if editingMessageId != nil {
                HStack {
                    Label("Editing prompt", systemImage: "pencil")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                    Spacer()
                    Button("Cancel", action: cancelEditing)
                        .font(.caption.weight(.medium))
                }
            }
            HStack {
                TextField("Ask anything", text: $input, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .focused($inputFocused)
                    .onSubmit { submit(input) }
                Button { submit(input) } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.title)
                        .foregroundStyle(Theme.brand)
                        .accessibilityLabel(editingMessageId == nil ? "Send" : "Save and resend")
                }
                .disabled(input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || sending)
            }
        }
        .padding()
        .background(.bar)
    }

    private func beginEditing(_ message: ChatMessage) {
        guard !sending else { return }
        editingMessageId = message.id
        input = message.content
        inputFocused = true
    }

    private func cancelEditing() {
        editingMessageId = nil
        input = ""
        inputFocused = false
    }

    private func submit(_ text: String) {
        let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty, !sending else { return }
        let messageId = editingMessageId
        input = ""
        editingMessageId = nil
        scrollRequest &+= 1
        Task {
            if let messageId {
                await store.regenerate(from: messageId, replacement: clean)
            } else {
                await store.send(clean)
            }
        }
    }

    private func resend(_ message: ChatMessage) {
        guard !sending else { return }
        cancelEditing()
        Task {
            await store.regenerate(from: message.id)
        }
    }

    private func prepareInitialConversation(using proxy: ScrollViewProxy) {
        visibleMessageCount = 5
        didInitialScroll = false
        Task { @MainActor in
            await Task<Never, Never>.yield()
            proxy.scrollTo("copilot-conversation-bottom", anchor: .bottom)
            await Task<Never, Never>.yield()
            didInitialScroll = true
        }
    }

    private func loadEarlierMessages(using proxy: ScrollViewProxy) {
        guard hasEarlierMessages, !loadingEarlierMessages,
              let currentTopId = visibleMessages.first?.id else { return }
        loadingEarlierMessages = true
        historyLoadArmed = false
        handledHistoryLoadForDrag = true
        visibleMessageCount = min(store.messages.count, visibleMessageCount + 5)

        Task { @MainActor in
            await Task<Never, Never>.yield()
            var transaction = SwiftUI.Transaction()
            transaction.disablesAnimations = true
            withTransaction(transaction) {
                proxy.scrollTo(currentTopId, anchor: .top)
            }
            await Task<Never, Never>.yield()
            loadingEarlierMessages = false
        }
    }

    private func scrollToConversationBottom(_ proxy: ScrollViewProxy) {
        // SwiftUI can publish the message before its LazyVStack has finished
        // laying it out. Scroll after that layout pass, then settle once more
        // after the keyboard/Thinking row animation changes the viewport.
        Task { @MainActor in
            await Task<Never, Never>.yield()
            withAnimation(.easeOut(duration: 0.2)) {
                proxy.scrollTo("copilot-conversation-bottom", anchor: .bottom)
            }
            try? await Task<Never, Never>.sleep(nanoseconds: 350_000_000)
            proxy.scrollTo("copilot-conversation-bottom", anchor: .bottom)
        }
    }
}

struct CopilotMessageRow: View {
    let message: ChatMessage
    let busy: Bool
    let onEdit: () -> Void
    let onResend: () -> Void

    private var isUser: Bool { message.role == "user" }
    private var visibleActions: [String] {
        CopilotActionReceiptFilter.visibleActions(
            reply: message.content,
            actions: message.actions ?? []
        )
    }

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: 40) }
            VStack(alignment: isUser ? .trailing : .leading, spacing: 6) {
                messageBubble
                if isUser { promptActions }
            }
            if !isUser { Spacer(minLength: 40) }
        }
    }

    private var messageBubble: some View {
        VStack(alignment: .leading, spacing: 5) {
            CopilotMarkdownText(content: message.content)
            ForEach(visibleActions, id: \.self) { action in
                Label(action, systemImage: "checkmark")
                    .font(.caption)
                    .foregroundStyle(isUser ? Theme.onBrand : Theme.brand)
            }
        }
        .padding(12)
        .background(isUser ? Theme.brand : Theme.card)
        .foregroundStyle(isUser ? Theme.onBrand : .primary)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private var promptActions: some View {
        HStack(spacing: 12) {
            Button(action: onEdit) {
                Label("Edit", systemImage: "pencil")
            }
            Button(action: onResend) {
                Label("Resend", systemImage: "arrow.clockwise")
            }
        }
        .font(.caption.weight(.medium))
        .foregroundStyle(.secondary)
        .buttonStyle(.plain)
        .disabled(busy)
    }
}

/// Tool actions are useful receipts, but models often restate the same change in
/// their prose. Hide only high-overlap receipts so one response never reads like
/// two separate Audel answers.
enum CopilotActionReceiptFilter {
    private static let ignoredWords: Set<String> = [
        "and", "are", "for", "from", "has", "have", "into", "the", "this",
        "that", "to", "was", "were", "with", "your",
    ]

    static func visibleActions(reply: String, actions: [String]) -> [String] {
        let replyTokens = tokens(in: reply)
        var seen: Set<String> = []
        return actions.filter { action in
            let normalized = action.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            guard !normalized.isEmpty, seen.insert(normalized).inserted else { return false }
            let actionTokens = tokens(in: action)
            guard actionTokens.count >= 2 else { return true }
            let overlap = actionTokens.intersection(replyTokens).count
            return Double(overlap) / Double(actionTokens.count) < 0.65
        }
    }

    private static func tokens(in text: String) -> Set<String> {
        let words = text.lowercased().components(separatedBy: CharacterSet.alphanumerics.inverted)
        return Set(words.compactMap { word in
            guard word.count >= 3, !ignoredWords.contains(word) else { return nil }
            // A short stem makes "categorize" and "categorized" equivalent
            // without pulling a natural-language library into the client.
            return String(word.prefix(7))
        })
    }
}

struct CopilotMarkdownText: View {
    let content: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(CopilotContentParser.parse(content).enumerated()), id: \.offset) { _, block in
                switch block {
                case .text(let text):
                    CopilotInlineMarkdownText(content: text)
                case .table(let headers, let rows):
                    CopilotTableCards(headers: headers, rows: rows)
                }
            }
        }
    }
}

struct CopilotInlineMarkdownText: View {
    let content: String

    var body: some View {
        Text(attributedContent)
    }

    private var attributedContent: AttributedString {
        let options = AttributedString.MarkdownParsingOptions(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        )
        return (try? AttributedString(markdown: content, options: options))
            ?? AttributedString(content)
    }
}

struct CopilotTableCards: View {
    let headers: [String]
    let rows: [[String]]

    var body: some View {
        VStack(spacing: 8) {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                VStack(alignment: .leading, spacing: 7) {
                    CopilotInlineMarkdownText(content: row[0])
                        .font(.subheadline.weight(.semibold))
                    ForEach(headers.indices.dropFirst(), id: \.self) { index in
                        HStack(alignment: .top, spacing: 12) {
                            Text(headers[index])
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Spacer(minLength: 8)
                            CopilotInlineMarkdownText(content: row[index])
                                .font(.caption.weight(.medium))
                                .multilineTextAlignment(.trailing)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(Color.primary.opacity(0.055))
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .strokeBorder(Color.primary.opacity(0.09))
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Comparison table")
    }
}

enum CopilotContentBlock {
    case text(String)
    case table(headers: [String], rows: [[String]])
}

enum CopilotContentParser {
    static func parse(_ content: String) -> [CopilotContentBlock] {
        let lines = content.components(separatedBy: "\n")
        var blocks: [CopilotContentBlock] = []
        var textLines: [String] = []
        var index = 0

        func appendText() {
            guard !textLines.isEmpty else { return }
            blocks.append(.text(textLines.joined(separator: "\n")))
            textLines.removeAll()
        }

        while index < lines.count {
            let headers = pipeRow(lines[index])
            let separator = index + 1 < lines.count ? pipeRow(lines[index + 1]) : nil
            let separatorIsValid = headers != nil
                && (headers?.count ?? 0) >= 2
                && separator?.count == headers?.count
                && separator?.allSatisfy(isSeparatorCell) == true

            guard separatorIsValid, let headers else {
                textLines.append(lines[index])
                index += 1
                continue
            }

            index += 2
            var rows: [[String]] = []
            while index < lines.count,
                  let row = pipeRow(lines[index]),
                  row.count == headers.count {
                rows.append(row)
                index += 1
            }

            guard !rows.isEmpty else {
                textLines.append(lines[index - 2])
                textLines.append(lines[index - 1])
                continue
            }
            appendText()
            blocks.append(.table(headers: headers, rows: rows))
        }

        appendText()
        return blocks
    }

    private static func pipeRow(_ line: String) -> [String]? {
        var value = line.trimmingCharacters(in: .whitespaces)
        guard value.contains("|") else { return nil }
        if value.hasPrefix("|") { value.removeFirst() }
        if value.hasSuffix("|") { value.removeLast() }

        var cells: [String] = []
        var cell = ""
        var escaped = false
        for character in value {
            if escaped {
                cell.append(character)
                escaped = false
            } else if character == "\\" {
                escaped = true
            } else if character == "|" {
                cells.append(cell.trimmingCharacters(in: .whitespaces))
                cell = ""
            } else {
                cell.append(character)
            }
        }
        if escaped { cell.append("\\") }
        cells.append(cell.trimmingCharacters(in: .whitespaces))
        return cells
    }

    private static func isSeparatorCell(_ cell: String) -> Bool {
        var value = cell
        if value.hasPrefix(":") { value.removeFirst() }
        if value.hasSuffix(":") { value.removeLast() }
        return value.count >= 3 && value.allSatisfy { $0 == "-" }
    }
}

// MARK: - Formatting

extension Double {
    var currency: String { formatted(.currency(code: "USD")) }
    var compactCurrency: String { abs(self) >= 1_000_000 ? String(format: "$%.1fM", self / 1_000_000) : abs(self) >= 1_000 ? String(format: "$%.1fK", self / 1_000) : currency }
    var cleanNumber: String { rounded() == self ? String(Int(self)) : formatted() }
    /// Locale-independent text for numeric editor fields. Display formatting can
    /// contain grouping separators that `Double.init(_:)` does not parse.
    var editableNumber: String { rounded() == self ? String(Int(self)) : String(self) }
}
extension String {
    var pretty: String { replacingOccurrences(of: "_", with: " ").split(separator: " ").map { $0.prefix(1).uppercased() + $0.dropFirst().lowercased() }.joined(separator: " ") }
    var shortDate: String { let input = DateFormatter(); input.dateFormat = "yyyy-MM-dd"; let output = DateFormatter(); output.dateStyle = .medium; return input.date(from: self).map(output.string) ?? self }
    var monthDay: String { let input = DateFormatter(); input.dateFormat = "yyyy-MM-dd"; let output = DateFormatter(); output.dateFormat = "MMM d"; return input.date(from: self).map(output.string) ?? self }
    var monthLabel: String { let input = DateFormatter(); input.dateFormat = "yyyy-MM"; let output = DateFormatter(); output.dateFormat = "MMM ''yy"; return input.date(from: self).map(output.string) ?? self }
    var monthName: String { let input = DateFormatter(); input.dateFormat = "yyyy-MM"; let output = DateFormatter(); output.dateFormat = "MMM"; return input.date(from: self).map(output.string) ?? self }
    var monthSlashDay: String { let input = DateFormatter(); input.dateFormat = "yyyy-MM-dd"; let output = DateFormatter(); output.dateFormat = "M/d"; return input.date(from: String(prefix(10))).map(output.string) ?? self }
    var weekdayName: String { let input = DateFormatter(); input.locale = Locale(identifier: "en_US_POSIX"); input.dateFormat = "yyyy-MM-dd"; let output = DateFormatter(); output.dateFormat = "EEEE"; return input.date(from: String(prefix(10))).map(output.string) ?? self }
    var localizedTime: String { let input = DateFormatter(); input.locale = Locale(identifier: "en_US_POSIX"); input.dateFormat = "HH:mm"; let output = DateFormatter(); output.timeStyle = .short; return input.date(from: self).map(output.string) ?? self }
}
extension Date {
    var apiDate: String { let formatter = DateFormatter(); formatter.dateFormat = "yyyy-MM-dd"; return formatter.string(from: self) }
    var apiTime: String { let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX"); formatter.dateFormat = "HH:mm"; return formatter.string(from: self) }
    var monthGridRange: (start: String, end: String) {
        var components = Calendar.current.dateComponents([.year, .month], from: self)
        components.day = 1
        let start = Calendar.current.date(from: components) ?? self
        let end = Calendar.current.date(byAdding: DateComponents(month: 1, day: -1), to: start) ?? self
        return (start.apiDate, end.apiDate)
    }
    static var threeMonthStart: String {
        var components = Calendar.current.dateComponents([.year, .month], from: Date())
        components.day = 1
        let start = Calendar.current.date(byAdding: .month, value: -2, to: Calendar.current.date(from: components)!)!
        return start.apiDate
    }
}

struct ContentView_Previews: PreviewProvider {
    @MainActor
    static var previews: some View {
        ContentView(store: MoneyStore(), loadsRemoteData: false)
    }
}
