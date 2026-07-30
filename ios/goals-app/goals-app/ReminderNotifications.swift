import CryptoKit
import Foundation
import UIKit
import UserNotifications

enum ReminderNotificationScheduler {
    static let reminderCategoryIdentifier = "SCHEDULE_REMINDER"
    static let routineCategoryIdentifier = "SCHEDULE_ROUTINE"
    static let persistentReminderCategoryIdentifier = "PERSISTENT_SCHEDULE_REMINDER"
    static let persistentRoutineCategoryIdentifier = "PERSISTENT_SCHEDULE_ROUTINE"
    static let completeActionIdentifier = "COMPLETE_SCHEDULE_ITEM"
    static let stopActionIdentifier = "STOP_PERSISTENT_REMINDER"
    static let snoozeActionIdentifier = "SNOOZE_PERSISTENT_SCHEDULE_ITEM"
    private static let requestPrefix = "schedule-"
    private static let rollingNudgeCount = 12
    private static let schedulerVersion = 2

    static func registerActions() {
        let complete = UNNotificationAction(
            identifier: completeActionIdentifier,
            title: "Done",
            options: []
        )
        let reminderCategory = UNNotificationCategory(
            identifier: reminderCategoryIdentifier,
            actions: [complete],
            intentIdentifiers: [],
            options: []
        )
        let routineCategory = UNNotificationCategory(
            identifier: routineCategoryIdentifier,
            actions: [complete],
            intentIdentifiers: [],
            options: []
        )
        let snooze = UNNotificationAction(
            identifier: snoozeActionIdentifier,
            title: "Snooze",
            options: []
        )
        let stop = UNNotificationAction(
            identifier: stopActionIdentifier,
            title: "Stop",
            options: [.destructive]
        )
        let persistentReminderCategory = UNNotificationCategory(
            identifier: persistentReminderCategoryIdentifier,
            actions: [snooze, stop],
            intentIdentifiers: [],
            options: []
        )
        let persistentRoutineCategory = UNNotificationCategory(
            identifier: persistentRoutineCategoryIdentifier,
            actions: [snooze, complete],
            intentIdentifiers: [],
            options: []
        )
        UNUserNotificationCenter.current().setNotificationCategories([
            reminderCategory,
            routineCategory,
            persistentReminderCategory,
            persistentRoutineCategory,
        ])
    }

    static func sync(_ items: [ScheduleItem], requestAuthorization: Bool) async {
        guard await isAuthorized(requestIfNeeded: requestAuthorization) else { return }
        let pending = await pendingRequests()
        for item in items {
            let itemPrefix = prefix(
                source: item.source,
                sourceId: item.sourceId,
                scheduledFor: item.scheduledFor
            )
            await reconcile(
                item,
                pending: pending.filter { $0.identifier.hasPrefix(itemPrefix) }
            )
        }
    }

    static func schedule(_ reminder: Reminder, requestAuthorization: Bool) async {
        await cancel(reminderId: reminder.id)
        // An "important" reminder rings like a real alarm (iOS 26+) instead of a
        // silent-respecting notification. The alarm replaces the notification so
        // it doesn't fire twice.
        if #available(iOS 26.0, *),
           reminder.important, !reminder.completed,
           let time = reminder.reminderTime,
           let fireDate = dueDate(day: reminder.scheduledFor, time: time),
           fireDate > Date() {
            await ReminderAlarm.scheduleOnce(
                id: ReminderAlarmID.make(source: "reminder", sourceId: reminder.id),
                title: reminder.title,
                at: fireDate
            )
            return
        }
        guard !reminder.completed,
              reminder.reminderTime != nil,
              await isAuthorized(requestIfNeeded: requestAuthorization) else { return }
        await enqueue(
            source: "reminder",
            sourceId: reminder.id,
            title: reminder.title,
            notes: reminder.notes,
            scheduledFor: reminder.scheduledFor,
            reminderTime: reminder.reminderTime,
            persistent: reminder.repeatUntilCompleted,
            intervalMinutes: reminder.nudgeIntervalMinutes
        )
    }

    static func cancel(reminderId: Int) async {
        await cancel(prefix: prefix(source: "reminder", sourceId: reminderId))
        if #available(iOS 26.0, *) {
            ReminderAlarm.cancel(id: ReminderAlarmID.make(source: "reminder", sourceId: reminderId))
        }
    }

    static func cancel(source: String, sourceId: Int) async {
        await cancel(prefix: prefix(source: source, sourceId: sourceId))
        if #available(iOS 26.0, *), source == "routine" {
            ReminderAlarm.cancel(id: ReminderAlarmID.make(source: "routine", sourceId: sourceId))
        }
    }

    static func cancel(source: String, sourceId: Int, scheduledFor: String) async {
        await cancel(prefix: prefix(source: source, sourceId: sourceId, scheduledFor: scheduledFor))
    }

    static func schedule(_ item: ScheduleItem, requestAuthorization: Bool) async {
        guard await isAuthorized(requestIfNeeded: requestAuthorization) else { return }
        let itemPrefix = prefix(
            source: item.source,
            sourceId: item.sourceId,
            scheduledFor: item.scheduledFor
        )
        let pending = await pendingRequests()
            .filter { $0.identifier.hasPrefix(itemPrefix) }
        await reconcile(item, pending: pending)
    }

    private static func reconcile(
        _ item: ScheduleItem,
        pending: [UNNotificationRequest]
    ) async {
        // Important daily/weekly routines ring as a single recurring AlarmKit alarm
        // (iOS 26+) instead of per-occurrence notifications.
        if #available(iOS 26.0, *), item.source == "routine", item.important,
           item.period == "daily" || item.period == "weekly" {
            if !pending.isEmpty {
                await cancel(source: item.source, sourceId: item.sourceId, scheduledFor: item.scheduledFor)
            }
            await scheduleRoutineAlarm(item)
            return
        }
        guard !item.completed,
              item.reminderTime != nil,
              item.scheduledFor >= Date().apiDate else {
            if !pending.isEmpty {
                await cancel(
                    source: item.source,
                    sourceId: item.sourceId,
                    scheduledFor: item.scheduledFor
                )
            }
            return
        }
        if requestsAreCurrent(pending, for: item) { return }
        if !pending.isEmpty {
            await cancel(
                source: item.source,
                sourceId: item.sourceId,
                scheduledFor: item.scheduledFor
            )
        }
        await enqueue(
            source: item.source,
            sourceId: item.sourceId,
            title: item.title,
            notes: item.notes,
            scheduledFor: item.scheduledFor,
            reminderTime: item.reminderTime,
            persistent: item.repeatUntilCompleted,
            intervalMinutes: item.nudgeIntervalMinutes
        )
    }

    static func snooze(_ item: ScheduleItem, minutes: Int? = nil) async {
        guard item.source == "routine", item.repeatUntilCompleted, !item.completed else { return }
        await cancel(source: item.source, sourceId: item.sourceId, scheduledFor: item.scheduledFor)
        let interval = max(item.nudgeIntervalMinutes ?? 60, 30)
        let delay = max(minutes ?? interval, 5)
        await enqueue(
            source: item.source,
            sourceId: item.sourceId,
            title: item.title,
            notes: item.notes,
            scheduledFor: item.scheduledFor,
            reminderTime: item.reminderTime,
            persistent: true,
            intervalMinutes: interval,
            firstFireDate: Date().addingTimeInterval(TimeInterval(delay * 60))
        )
    }

    private static func cancel(prefix: String) async {
        let center = UNUserNotificationCenter.current()
        let requests = await pendingRequests()
        let ids = requests.map(\.identifier).filter { $0.hasPrefix(prefix) }
        center.removePendingNotificationRequests(withIdentifiers: ids)
        center.removeDeliveredNotifications(withIdentifiers: ids)
    }

    private static func pendingRequests() async -> [UNNotificationRequest] {
        await withCheckedContinuation { continuation in
            UNUserNotificationCenter.current().getPendingNotificationRequests {
                continuation.resume(returning: $0)
            }
        }
    }

    private static func requestsAreCurrent(
        _ requests: [UNNotificationRequest],
        for item: ScheduleItem
    ) -> Bool {
        guard !requests.isEmpty else { return false }
        let expectedInterval = max(item.nudgeIntervalMinutes ?? 60, 30)
        let expectedCategory: String
        if item.source == "routine" {
            expectedCategory = item.repeatUntilCompleted
                ? persistentRoutineCategoryIdentifier
                : routineCategoryIdentifier
        } else {
            expectedCategory = item.repeatUntilCompleted
                ? persistentReminderCategoryIdentifier
                : reminderCategoryIdentifier
        }

        return requests.allSatisfy { request in
            let content = request.content
            let info = content.userInfo
            return info["scheduler_version"] as? Int == schedulerVersion
                && info["schedule_source"] as? String == item.source
                && info["source_id"] as? Int == item.sourceId
                && info["scheduled_for"] as? String == item.scheduledFor
                && info["reminder_time"] as? String == item.reminderTime
                && info["nudge_interval_minutes"] as? Int == expectedInterval
                && info["repeat_until_completed"] as? Bool == item.repeatUntilCompleted
                && content.title == item.title
                && content.categoryIdentifier == expectedCategory
        }
    }

    private static func enqueue(
        source: String,
        sourceId: Int,
        title: String,
        notes: String?,
        scheduledFor: String,
        reminderTime: String?,
        persistent: Bool,
        intervalMinutes: Int?,
        firstFireDate: Date? = nil
    ) async {
        guard let due = dueDate(day: scheduledFor, time: reminderTime) else { return }
        let now = Date()
        guard persistent || due > now else { return }
        let intervalMinutes = max(intervalMinutes ?? 60, 30)
        let interval = TimeInterval(intervalMinutes * 60)
        let first = firstFireDate ?? nextFireDate(
            due: due,
            now: now,
            interval: interval,
            persistent: persistent
        )
        // iOS caps pending notifications per app. Future routine occurrences get
        // one alert; today's occurrence owns the rolling nudge queue.
        let shouldQueueNudges = persistent && (
            source == "reminder" || scheduledFor == Date().apiDate || firstFireDate != nil
        )
        let count = shouldQueueNudges ? rollingNudgeCount : 1
        let center = UNUserNotificationCenter.current()

        for index in 0..<count {
            let fireDate = first.addingTimeInterval(TimeInterval(index) * interval)
            let content = UNMutableNotificationContent()
            content.title = title
            // The title is the reminder. Repeating it with generic explanatory
            // copy underneath makes the banner noisier without adding information.
            content.body = ""
            content.sound = .default
            if source == "routine" {
                content.categoryIdentifier = persistent
                    ? persistentRoutineCategoryIdentifier
                    : routineCategoryIdentifier
            } else {
                content.categoryIdentifier = persistent
                    ? persistentReminderCategoryIdentifier
                    : reminderCategoryIdentifier
            }
            content.userInfo = [
                "schedule_source": source,
                "source_id": sourceId,
                "scheduled_for": scheduledFor,
                "reminder_time": reminderTime ?? "",
                "nudge_interval_minutes": intervalMinutes,
                "repeat_until_completed": persistent,
                "scheduler_version": schedulerVersion,
            ]
            let trigger = UNCalendarNotificationTrigger(
                dateMatching: Calendar.current.dateComponents(
                    [.year, .month, .day, .hour, .minute, .second], from: fireDate
                ),
                repeats: false
            )
            let request = UNNotificationRequest(
                identifier: "\(prefix(source: source, sourceId: sourceId, scheduledFor: scheduledFor))\(index)",
                content: content,
                trigger: trigger
            )
            try? await center.add(request)
        }
    }

    private static func nextFireDate(
        due: Date,
        now: Date,
        interval: TimeInterval,
        persistent: Bool
    ) -> Date {
        guard persistent, due <= now else { return due }
        let elapsed = now.timeIntervalSince(due)
        let elapsedIntervals = floor(elapsed / interval)
        return due.addingTimeInterval((elapsedIntervals + 1) * interval)
    }

    private static func isAuthorized(requestIfNeeded: Bool) async -> Bool {
        let center = UNUserNotificationCenter.current()
        let settings = await center.notificationSettings()
        switch settings.authorizationStatus {
        case .authorized, .provisional, .ephemeral:
            return true
        case .notDetermined where requestIfNeeded:
            return (try? await center.requestAuthorization(options: [.alert, .badge, .sound])) == true
        default:
            return false
        }
    }

    @available(iOS 26.0, *)
    private static func scheduleRoutineAlarm(_ item: ScheduleItem) async {
        guard !item.completed, let time = item.reminderTime else { return }
        let parts = time.split(separator: ":")
        guard parts.count >= 2, let hour = Int(parts[0]), let minute = Int(parts[1]) else { return }
        let weekdays: [Locale.Weekday]
        switch item.period {
        case "daily":
            weekdays = [.sunday, .monday, .tuesday, .wednesday, .thursday, .friday, .saturday]
        case "weekly":
            guard let day = weekday(fromAPIDate: item.scheduledFor) else { return }
            weekdays = [day]
        default:
            return
        }
        await ReminderAlarm.scheduleWeekly(
            id: ReminderAlarmID.make(source: "routine", sourceId: item.sourceId),
            title: item.title, weekdays: weekdays, hour: hour, minute: minute
        )
    }

    private static func weekday(fromAPIDate apiDate: String) -> Locale.Weekday? {
        let formatter = DateFormatter()
        formatter.calendar = Calendar.current
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        guard let date = formatter.date(from: apiDate) else { return nil }
        switch Calendar.current.component(.weekday, from: date) {
        case 1: return .sunday
        case 2: return .monday
        case 3: return .tuesday
        case 4: return .wednesday
        case 5: return .thursday
        case 6: return .friday
        case 7: return .saturday
        default: return nil
        }
    }

    private static func dueDate(day: String, time: String?) -> Date? {
        guard let time else { return nil }
        let formatter = DateFormatter()
        formatter.calendar = Calendar.current
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd HH:mm"
        return formatter.date(from: "\(day) \(time)")
    }

    private static func prefix(source: String, sourceId: Int, scheduledFor: String? = nil) -> String {
        let base = "\(requestPrefix)\(source)-\(sourceId)-"
        return scheduledFor.map { "\(base)\($0)-" } ?? base
    }
}

final class ReminderNotificationDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        ReminderNotificationScheduler.registerActions()
        return true
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse
    ) async {
        let action = response.actionIdentifier
        guard [
            ReminderNotificationScheduler.completeActionIdentifier,
            ReminderNotificationScheduler.stopActionIdentifier,
            ReminderNotificationScheduler.snoozeActionIdentifier,
        ].contains(action),
        let source = response.notification.request.content.userInfo["schedule_source"] as? String,
        let sourceId = response.notification.request.content.userInfo["source_id"] as? Int,
        let scheduledFor = response.notification.request.content.userInfo["scheduled_for"] as? String else {
            return
        }
        do {
            if source == "routine" {
                if action == ReminderNotificationScheduler.snoozeActionIdentifier {
                    let interval = max(
                        response.notification.request.content.userInfo["nudge_interval_minutes"] as? Int ?? 60,
                        30
                    )
                    let item = ScheduleItem(
                        id: "routine:\(sourceId):\(scheduledFor)",
                        source: source,
                        sourceId: sourceId,
                        title: response.notification.request.content.title,
                        scheduledFor: scheduledFor,
                        reminderTime: Date().apiTime,
                        completed: false,
                        missed: scheduledFor < Date().apiDate,
                        notes: nil,
                        period: "routine",
                        repeatUntilCompleted: true,
                        nudgeIntervalMinutes: interval,
                        important: false,
                        endTime: nil,
                        location: nil
                    )
                    await ReminderNotificationScheduler.snooze(item)
                } else {
                    let _: GoalTask = try await APIClient.shared.request(
                        "goals/\(sourceId)/checkin",
                        method: "PATCH",
                        body: .init(CheckinBody(
                            scheduledFor: scheduledFor,
                            completed: true,
                            allowOverdue: scheduledFor < Date().apiDate
                        ))
                    )
                    await ReminderNotificationScheduler.cancel(
                        source: source,
                        sourceId: sourceId,
                        scheduledFor: scheduledFor
                    )
                }
            } else if action == ReminderNotificationScheduler.snoozeActionIdentifier {
                let interval = max(
                    response.notification.request.content.userInfo["nudge_interval_minutes"] as? Int ?? 60,
                    30
                )
                let next = Date().addingTimeInterval(TimeInterval(interval * 60))
                let reminder: Reminder = try await APIClient.shared.request(
                    "reminders/\(sourceId)",
                    method: "PATCH",
                    body: .init(ReminderSnoozeBody(
                        scheduledFor: next.apiDate,
                        reminderTime: next.apiTime
                    ))
                )
                await ReminderNotificationScheduler.schedule(reminder, requestAuthorization: false)
            } else {
                let _: Reminder = try await APIClient.shared.request(
                    "reminders/\(sourceId)",
                    method: "PATCH",
                    body: .init(ReminderCompletionBody(completed: true))
                )
                await ReminderNotificationScheduler.cancel(reminderId: sourceId)
            }
        } catch {
            // The reminder remains active and can be managed after connectivity returns.
        }
    }
}

// MARK: - AlarmKit (important reminders ring like an alarm)

/// Deterministic alarm identifier so scheduling and cancellation agree without
/// persisting a lookup table. Available on all OS versions so cancel paths work
/// even though scheduling is iOS 26+.
enum ReminderAlarmID {
    static func make(source: String, sourceId: Int) -> UUID {
        let key = "audel-alarm-\(source)-\(sourceId)"
        let digest = SHA256.hash(data: Data(key.utf8))
        var bytes = Array(digest.prefix(16))
        bytes[6] = (bytes[6] & 0x0F) | 0x50  // version 5
        bytes[8] = (bytes[8] & 0x3F) | 0x80  // RFC 4122 variant
        return bytes.withUnsafeBufferPointer { NSUUID(uuidBytes: $0.baseAddress) as UUID }
    }
}

#if canImport(AlarmKit)
import AlarmKit
import SwiftUI

/// Empty metadata payload — reminder alarms carry no custom data.
@available(iOS 26.0, *)
struct ReminderAlarmMetadata: AlarmMetadata { init() {} }

/// Wraps AlarmKit so an "important" reminder rings like a real alarm — breaking
/// through silent mode and Focus — instead of a silent-respecting notification.
/// iOS 26+ only; callers fall back to notifications on older systems.
@available(iOS 26.0, *)
enum ReminderAlarm {
    static func requestAuthorization() async -> Bool {
        switch AlarmManager.shared.authorizationState {
        case .authorized: return true
        case .denied: return false
        case .notDetermined:
            return (try? await AlarmManager.shared.requestAuthorization()) == .authorized
        @unknown default: return false
        }
    }

    private static func attributes(title: String) -> AlarmAttributes<ReminderAlarmMetadata> {
        let stopButton = AlarmButton(
            text: "Stop", textColor: .white, systemImageName: "stop.fill"
        )
        let alert = AlarmPresentation.Alert(
            title: LocalizedStringResource(stringLiteral: title),
            stopButton: stopButton
        )
        return AlarmAttributes(
            presentation: AlarmPresentation(alert: alert),
            metadata: ReminderAlarmMetadata(),
            tintColor: Theme.brand
        )
    }

    /// One-time alarm at a specific wall-clock date.
    static func scheduleOnce(id: UUID, title: String, at date: Date) async {
        guard await requestAuthorization() else { return }
        let config = AlarmManager.AlarmConfiguration.alarm(
            schedule: .fixed(date),
            attributes: attributes(title: title),
            sound: .default
        )
        _ = try? await AlarmManager.shared.schedule(id: id, configuration: config)
    }

    /// Recurring alarm at a time of day on the given weekdays (daily == all seven).
    static func scheduleWeekly(
        id: UUID, title: String, weekdays: [Locale.Weekday], hour: Int, minute: Int
    ) async {
        guard await requestAuthorization() else { return }
        let relative = Alarm.Schedule.Relative(
            time: .init(hour: hour, minute: minute),
            repeats: weekdays.isEmpty ? .never : .weekly(weekdays)
        )
        let config = AlarmManager.AlarmConfiguration.alarm(
            schedule: .relative(relative),
            attributes: attributes(title: title),
            sound: .default
        )
        _ = try? await AlarmManager.shared.schedule(id: id, configuration: config)
    }

    static func cancel(id: UUID) {
        try? AlarmManager.shared.cancel(id: id)
    }
}
#endif
