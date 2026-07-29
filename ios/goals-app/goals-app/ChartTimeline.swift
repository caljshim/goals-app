import Foundation

/// A calendar-day sample derived from goal history. Quiet days carry the most
/// recent value so charts describe elapsed time instead of database write times.
struct GoalChartPoint: Identifiable {
    let day: Date
    let dayKey: String
    let value: Double
    let isRecorded: Bool

    var id: String { dayKey }
}

enum GoalChartTimeline {
    private static var calendar: Calendar {
        var value = Calendar(identifier: .gregorian)
        value.timeZone = .current
        return value
    }

    /// Collapses multiple updates on one day to the final value, fills every
    /// intervening day, and carries active values through the requested end.
    static func daily(_ history: [HistoryPoint], through requestedEnd: Date = Date()) -> [GoalChartPoint] {
        guard !history.isEmpty else { return [] }

        var lastValueByDay: [String: Double] = [:]
        for point in history.sorted(by: { $0.at < $1.at }) {
            lastValueByDay[dayKey(from: point.at)] = point.value
        }

        let keys = lastValueByDay.keys.sorted()
        guard let firstKey = keys.first,
              let lastKey = keys.last,
              var cursor = date(from: firstKey),
              let lastRecordedDay = date(from: lastKey) else { return [] }

        let requestedDay = calendar.startOfDay(for: requestedEnd)
        let end = max(lastRecordedDay, requestedDay)
        var lastValue = lastValueByDay[firstKey] ?? 0
        var result: [GoalChartPoint] = []

        while cursor <= end {
            let key = dayKey(from: cursor)
            let recorded = lastValueByDay[key]
            if let recorded { lastValue = recorded }
            result.append(GoalChartPoint(
                day: cursor,
                dayKey: key,
                value: lastValue,
                isRecorded: recorded != nil
            ))
            guard let next = calendar.date(byAdding: .day, value: 1, to: cursor) else { break }
            cursor = next
        }
        return result
    }

    /// Ended goals should remain flat through their end date, not through today.
    static func dailyThroughStoredEnd(_ history: [HistoryPoint], endedAt: String?) -> [GoalChartPoint] {
        let fallback = history.compactMap { date(from: $0.at) }.max() ?? Date()
        return daily(history, through: endedAt.flatMap(date(from:)) ?? fallback)
    }

    private static func dayKey(from raw: String) -> String {
        String(raw.prefix(10))
    }

    private static func dayKey(from date: Date) -> String {
        let parts = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
    }

    private static func date(from raw: String) -> Date? {
        let values = raw.prefix(10).split(separator: "-").compactMap { Int($0) }
        guard values.count == 3 else { return nil }
        return calendar.date(from: DateComponents(year: values[0], month: values[1], day: values[2]))
    }
}
