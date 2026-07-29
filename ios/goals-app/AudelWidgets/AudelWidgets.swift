import AppIntents
import SwiftUI
import WidgetKit

@main
struct AudelWidgetBundle: WidgetBundle {
    var body: some Widget {
        AudelTodayWidget()
    }
}

struct AudelTodayEntry: TimelineEntry {
    let date: Date
    let configuration: AudelTodayConfigurationIntent
    let snapshot: AudelWidgetSnapshot
    let errorMessage: String?
}

struct AudelTodayProvider: AppIntentTimelineProvider {
    func placeholder(in context: Context) -> AudelTodayEntry {
        AudelTodayEntry(
            date: Date(),
            configuration: AudelTodayConfigurationIntent(),
            snapshot: .placeholder,
            errorMessage: nil
        )
    }

    func snapshot(
        for configuration: AudelTodayConfigurationIntent,
        in context: Context
    ) async -> AudelTodayEntry {
        if context.isPreview {
            return AudelTodayEntry(
                date: Date(),
                configuration: configuration,
                snapshot: .placeholder,
                errorMessage: nil
            )
        }
        return await currentEntry(configuration: configuration)
    }

    func timeline(
        for configuration: AudelTodayConfigurationIntent,
        in context: Context
    ) async -> Timeline<AudelTodayEntry> {
        let entry = await currentEntry(configuration: configuration)
        let nextRefresh = Calendar.current.date(
            byAdding: .minute,
            value: 15,
            to: Date()
        ) ?? Date().addingTimeInterval(15 * 60)
        return Timeline(entries: [entry], policy: .after(nextRefresh))
    }

    private func currentEntry(
        configuration: AudelTodayConfigurationIntent
    ) async -> AudelTodayEntry {
        do {
            return AudelTodayEntry(
                date: Date(),
                configuration: configuration,
                snapshot: try await AudelWidgetAPI.refreshToday(),
                errorMessage: nil
            )
        } catch {
            let cached = AudelWidgetStore.load()
            return AudelTodayEntry(
                date: Date(),
                configuration: configuration,
                snapshot: cached,
                errorMessage: cached.tasks.isEmpty ? error.localizedDescription : nil
            )
        }
    }
}

struct AudelTodayWidget: Widget {
    var body: some WidgetConfiguration {
        AppIntentConfiguration(
            kind: AudelWidgetConstants.todayWidgetKind,
            intent: AudelTodayConfigurationIntent.self,
            provider: AudelTodayProvider()
        ) { entry in
            AudelTodayWidgetView(entry: entry)
                .containerBackground(for: .widget) {
                    Color.audelWidgetBackground
                }
        }
        .configurationDisplayName("Today with Audel")
        .description("See and complete today's routines and reminders.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
        .contentMarginsDisabled()
    }
}

private struct AudelTodayWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: AudelTodayEntry

    private var tasks: [AudelWidgetTask] {
        entry.snapshot.tasks(for: entry.configuration.filter)
    }

    private var visibleTasks: ArraySlice<AudelWidgetTask> {
        tasks.prefix(family == .systemLarge ? 7 : family == .systemMedium ? 3 : 1)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: family == .systemSmall ? 10 : 8) {
            header
            if let errorMessage = entry.errorMessage {
                unavailable(errorMessage)
            } else if tasks.isEmpty {
                emptyState
            } else {
                taskList
            }
            Spacer(minLength: 0)
            if family != .systemSmall {
                footer
            }
        }
        .padding(16)
        .widgetURL(URL(string: "audel://schedule"))
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                Text("TODAY")
                    .font(.caption2.weight(.bold))
                    .tracking(1.2)
                    .foregroundStyle(.secondary)
                Text(statusTitle)
                    .font(family == .systemSmall ? .headline : .title3)
                    .fontWeight(.bold)
                    .fontDesign(.rounded)
                    .lineLimit(1)
            }
            Spacer()
            ZStack {
                Circle()
                    .fill(Color.audelBrand.opacity(0.13))
                Image(systemName: "sparkles")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(Color.audelBrand)
            }
            .frame(width: 30, height: 30)
        }
    }

    private var statusTitle: String {
        let remaining = entry.snapshot.remainingCount
        if remaining == 0, entry.snapshot.actionableCount > 0 {
            return "All clear"
        }
        return "\(remaining) remaining"
    }

    private var taskList: some View {
        VStack(spacing: 0) {
            ForEach(visibleTasks) { task in
                AudelWidgetTaskRow(task: task, compact: family == .systemSmall)
                if task.id != visibleTasks.last?.id {
                    Divider().opacity(0.45)
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 6) {
            Image(systemName: "checkmark.circle.fill")
                .font(.title2)
                .foregroundStyle(Color.audelBrand)
            Text(entry.configuration.filter == .remaining ? "Nothing left for today." : "Nothing scheduled today.")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func unavailable(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Image(systemName: "iphone.and.arrow.forward")
                .font(.title3)
                .foregroundStyle(Color.audelBrand)
            Text("Open Audel once")
                .font(.subheadline.weight(.semibold))
            Text(message)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
    }

    private var footer: some View {
        HStack(spacing: 5) {
            Text("\(entry.snapshot.completedCount) of \(entry.snapshot.actionableCount) done")
            Spacer()
            Text(entry.snapshot.generatedAt, style: .time)
        }
        .font(.caption2)
        .foregroundStyle(.tertiary)
    }
}

private struct AudelWidgetTaskRow: View {
    let task: AudelWidgetTask
    let compact: Bool

    var body: some View {
        HStack(spacing: 9) {
            completionControl
            VStack(alignment: .leading, spacing: 2) {
                Text(task.title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(task.completed ? .secondary : .primary)
                    .strikethrough(task.completed)
                    .lineLimit(compact ? 2 : 1)
                if !compact, let detail {
                    Text(detail)
                        .font(.caption2)
                        .foregroundStyle(task.missed ? Color.audelNegative : .secondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, compact ? 2 : 7)
    }

    @ViewBuilder private var completionControl: some View {
        if task.isActionable {
            Button(intent: SetScheduleItemCompletionIntent(task: task, completed: !task.completed)) {
                Image(systemName: task.completed ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundStyle(task.completed ? Color.audelBrand : .secondary)
                    .contentTransition(.symbolEffect(.replace))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(task.completed ? "Mark \(task.title) incomplete" : "Complete \(task.title)")
        } else {
            Image(systemName: task.source == "event" ? "calendar" : "target")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color.audelBrand)
                .frame(width: 20)
        }
    }

    private var detail: String? {
        if task.missed {
            return task.timeLabel.map { "Missed · \($0)" } ?? "Missed"
        }
        if let time = task.timeLabel {
            return time
        }
        switch task.source {
        case "event":
            return "Event"
        case "goal_deadline":
            return "Goal deadline"
        default:
            return nil
        }
    }
}

private extension Color {
    static let audelBrand = Color(
        light: 0x146B54,
        dark: 0x63D0A8
    )
    static let audelNegative = Color(
        light: 0xB0562F,
        dark: 0xE0906A
    )
    static let audelWidgetBackground = Color(
        light: 0xFFFFFF,
        dark: 0x171D1A
    )

    init(light: UInt32, dark: UInt32) {
        self.init(
            uiColor: UIColor { traits in
                let value = traits.userInterfaceStyle == .dark ? dark : light
                return UIColor(
                    red: CGFloat((value >> 16) & 0xFF) / 255,
                    green: CGFloat((value >> 8) & 0xFF) / 255,
                    blue: CGFloat(value & 0xFF) / 255,
                    alpha: 1
                )
            }
        )
    }
}
