import SwiftUI
import Charts
import UIKit

private enum GoalFocusLayout {
    static let coordinateSpace = "goal-focus-space"
}

private struct FocusedWidgetFramePreferenceKey: PreferenceKey {
    static var defaultValue: CGRect?

    static func reduce(value: inout CGRect?, nextValue: () -> CGRect?) {
        if let next = nextValue() { value = next }
    }
}

extension View {
    func reportFocusedWidgetFrame(_ isFocused: Bool) -> some View {
        background {
            GeometryReader { proxy in
                Color.clear.preference(
                    key: FocusedWidgetFramePreferenceKey.self,
                    value: isFocused ? proxy.frame(in: .named(GoalFocusLayout.coordinateSpace)) : nil
                )
            }
        }
    }

    func pressAndHoldToFocus(enabled: Bool = true, action: @escaping () -> Void) -> some View {
        modifier(PressAndHoldFocusModifier(enabled: enabled, action: action))
    }

    func pressAndHoldToEdit(enabled: Bool = true, action: @escaping () -> Void) -> some View {
        modifier(PressAndHoldFocusModifier(enabled: enabled, action: action))
    }

    func editableFocusStyle(
        isFocused: Bool,
        isDimmed: Bool,
        cornerRadius: CGFloat,
        outlineOutset: CGFloat = 0,
        accent: Color = Theme.brand
    ) -> some View {
        modifier(EditableFocusStyle(
            isFocused: isFocused,
            isDimmed: isDimmed,
            cornerRadius: cornerRadius,
            outlineOutset: outlineOutset,
            accent: accent
        ))
    }
}

/// Gives focus-mode entry the same tactile press-down and release response used
/// throughout iOS, plus a light impact when the long press completes.
struct PressAndHoldFocusModifier: ViewModifier {
    let enabled: Bool
    let action: () -> Void
    @State private var isPressing = false

    @ViewBuilder
    func body(content: Content) -> some View {
        if enabled {
            content
                .scaleEffect(isPressing ? 0.975 : 1)
                .brightness(isPressing ? -0.015 : 0)
                .animation(.interactiveSpring(response: 0.22, dampingFraction: 0.76), value: isPressing)
                .onLongPressGesture(
                    minimumDuration: 0.4,
                    maximumDistance: 14,
                    perform: {
                        UIImpactFeedbackGenerator(style: .light).impactOccurred()
                        action()
                    },
                    onPressingChanged: { pressing in
                        isPressing = pressing
                    }
                )
        } else {
            content
        }
    }
}

/// Mirrors the native iOS context-menu lift: the active surface rises above its
/// surroundings while unrelated content recedes, making its live controls clear.
private struct EditableFocusStyle: ViewModifier {
    let isFocused: Bool
    let isDimmed: Bool
    let cornerRadius: CGFloat
    let outlineOutset: CGFloat
    let accent: Color

    func body(content: Content) -> some View {
        content
            .scaleEffect(isFocused ? 1.018 : 1)
            .opacity(isDimmed ? 0.38 : 1)
            .saturation(isDimmed ? 0.55 : 1)
            .shadow(
                color: Color.black.opacity(isFocused ? 0.18 : 0),
                radius: isFocused ? 18 : 0,
                x: 0,
                y: isFocused ? 9 : 0
            )
            .overlay {
                RoundedRectangle(cornerRadius: cornerRadius + outlineOutset, style: .continuous)
                    .strokeBorder(accent.opacity(isFocused ? 0.8 : 0), lineWidth: 1.5)
                    .padding(-outlineOutset)
            }
            .zIndex(isFocused ? 10 : 0)
            .animation(.interactiveSpring(response: 0.3, dampingFraction: 0.82), value: isFocused)
            .animation(.easeOut(duration: 0.18), value: isDimmed)
    }
}

struct GoalCategory: Identifiable {
    let id: String
    let name: String
    let icon: String
    let goals: [Goal]
    let showsCombinedChart: Bool

    var aggregate: Double? {
        if goals.allSatisfy({ $0.kind == "streak" }) { return nil }
        let measurable = goals.filter { ($0.target ?? 0) != 0 }
        guard !measurable.isEmpty else { return nil }
        let directions = Set(measurable.map(\.direction))
        if Set(measurable.map(\.unit)).count == 1,
           directions.count == 1,
           directions.first == "reach" {
            let current = measurable.reduce(0) { $0 + $1.currentValue }
            let target = measurable.reduce(0) { $0 + ($1.target ?? 0) }
            guard target != 0 else { return nil }
            let raw = current / target * 100
            return (raw * 10).rounded() / 10
        }
        let average = measurable.reduce(0) { result, goal in
            result + (goal.pct ?? 0)
        } / Double(measurable.count)
        return (average * 10).rounded() / 10
    }

    var aggregateIsReversed: Bool {
        let measurable = goals.filter { ($0.target ?? 0) != 0 }
        return !measurable.isEmpty && measurable.allSatisfy { $0.direction == "under" }
    }

    var hasGoalOverLimit: Bool {
        goals.contains { $0.status == "over" }
    }

    var groupName: String? {
        guard let marker = id.range(of: "-group:") else { return nil }
        return String(id[marker.upperBound...])
    }

    var cadence: String? {
        guard let marker = id.range(of: "-section:") else { return nil }
        return String(id[marker.upperBound...])
    }

    var composerMode: GoalComposerMode {
        goals.first?.isRoutine == true ? .routine : .goal
    }

    func groupWidgetId(named groupName: String) -> String {
        "\(composerMode == .routine ? "routine" : "goal")-group:\(groupName)"
    }

    var customIcon: String? { goals.first?.groupIcon }
    var customColor: String? { goals.first?.groupColor }
}

/// Builds the goal categories shown on the Goals tab and available as dashboard
/// widgets. Ids match the React frontend's widget ids (`goal-group:<name>` /
/// `goal-section:<key>`) so copilot dashboard actions work on both clients.
/// Groups come from the backend `Goal.group` field; cadence sections are derived
/// from each goal's period.
func goalCategories(from goals: [Goal]) -> [GoalCategory] {
    categorizedGoals(from: goals.filter { !$0.isRoutine }, idPrefix: "goal", includeRoutines: false)
}

func routineCategories(from goals: [Goal]) -> [GoalCategory] {
    categorizedGoals(from: goals.filter(\.isRoutine), idPrefix: "routine", includeRoutines: true)
}

private func categorizedGoals(from goals: [Goal], idPrefix: String, includeRoutines: Bool) -> [GoalCategory] {
    let cadences: [(key: String, label: String, symbol: String)] = [
        ("daily", "Daily", "sun.max.fill"), ("weekly", "Weekly", "calendar"),
        ("monthly", "Monthly", "calendar.circle.fill"), ("interval", "Every N days", "repeat"),
        ("once", "One-time", "flag.fill"), ("ongoing", "Streaks", "flame.fill"),
    ]
    var result: [GoalCategory] = []
    var seen: Set<String> = []
    for goal in goals {
        guard let name = goal.group, !seen.contains(name) else { continue }
        seen.insert(name)
        result.append(.init(id: "\(idPrefix)-group:\(name)", name: name, icon: "tag.fill",
                            goals: goals.filter { $0.group == name }, showsCombinedChart: true))
    }
    for cadence in cadences where includeRoutines || cadence.key == "once" || cadence.key == "ongoing" {
        let members = goals.filter { goal in
            guard goal.group == nil else { return false }
            return (goal.kind == "streak" ? "ongoing" : goal.period) == cadence.key
        }
        if !members.isEmpty {
            result.append(.init(id: "\(idPrefix)-section:\(cadence.key)", name: cadence.label, icon: cadence.symbol,
                                goals: members, showsCombinedChart: false))
        }
    }
    return result
}

extension Goal {
    var isRoutine: Bool { period != "once" }
    /// Weekly numeric routines are completion checklists, not score targets.
    /// Financial goals keep their metric-based progress even with a weekly window.
    var usesScheduledCheckins: Bool { kind == "numeric" && period == "weekly" }
    var isManual: Bool {
        (kind == "save" && accountId == nil) || kind == "numeric"
            || (kind == "financial" && financialSource == "manual")
    }
    var symbol: String {
        switch kind {
        case "save": return "banknote.fill"
        case "spend_cap": return "creditcard.fill"
        case "financial": return "dollarsign.arrow.circlepath"
        case "numeric": return "chart.line.uptrend.xyaxis"
        case "streak": return "flame.fill"
        default: return "target"
        }
    }
    func format(_ value: Double) -> String {
        unit == "$" ? value.currency : unit == "days" ? "\(Int(value)) days" : value.formatted()
    }
    var scheduledWeekdays: [String] {
        let raw = weeklyDays.isEmpty ? (weeklyDay?.split(separator: ",").map(String.init) ?? []) : weeklyDays
        let selected = Set(raw.map { $0.lowercased() })
        return WeekdaySchedule.ordered.filter(selected.contains)
    }
    var weeklyScheduleLabel: String {
        scheduledWeekdays.map { String($0.prefix(3)).capitalized }.joined(separator: ", ")
    }
}

enum WeekdaySchedule {
    static let ordered = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    static func endDay(whenWeekStartsOn start: String) -> String {
        guard let index = ordered.firstIndex(of: start) else { return "saturday" }
        return ordered[(index + ordered.count - 1) % ordered.count]
    }
}

enum WeeklyTaskWindow {
    static func currentWeek(from tasks: [GoalTask], goal: Goal, now: Date = Date()) -> [GoalTask] {
        let calendar = Calendar.current
        let today = calendar.startOfDay(for: now)
        let weekdayNumbers = [
            "sunday": 1, "monday": 2, "tuesday": 3, "wednesday": 4,
            "thursday": 5, "friday": 6, "saturday": 7
        ]
        let currentWeekday = calendar.component(.weekday, from: today)
        let startWeekday = weekdayNumbers[goal.weeklyResetDay] ?? 1
        let daysSinceStart = (currentWeekday - startWeekday + 7) % 7
        guard let start = calendar.date(byAdding: .day, value: -daysSinceStart, to: today),
              let end = calendar.date(byAdding: .day, value: 6, to: start) else { return [] }
        let startKey = start.apiDate
        let endKey = end.apiDate
        let goalTasks = tasks.filter { $0.goalId == goal.id }
        var visible = goalTasks.filter {
            $0.scheduledFor >= startKey && $0.scheduledFor <= endKey
        }

        // A routine created after one of this cycle's selected days receives the
        // next occurrence for that weekday from the API. Keep that occurrence on
        // the board so choosing Sunday + Friday always shows both checkboxes.
        let representedDays = Set(visible.map { $0.scheduledFor.weekdayName.lowercased() })
        for weekday in goal.scheduledWeekdays where !representedDays.contains(weekday) {
            if let next = goalTasks
                .filter({
                    $0.scheduledFor > endKey
                        && $0.scheduledFor.weekdayName.lowercased() == weekday
                })
                .min(by: { $0.scheduledFor < $1.scheduledFor }) {
                visible.append(next)
            }
        }
        return visible.sorted { $0.scheduledFor < $1.scheduledFor }
    }
}

/// An Apple Reminders-style week control shared by routine cards and dashboard
/// widgets. Each occurrence owns a full-width row so multi-day schedules stay
/// legible without turning the card into a grid of tiny controls.
struct WeeklyCheckinStrip: View {
    @EnvironmentObject private var store: MoneyStore
    let tasks: [GoalTask]

    var body: some View {
        VStack(spacing: 0) {
            ForEach(tasks) { task in
                Button {
                    Task { await store.check(task) }
                } label: {
                    HStack(spacing: 10) {
                        Image(systemName: task.completed ? "checkmark.circle.fill" : "circle")
                            .font(.title3)
                            .foregroundStyle(checkinColor(task))
                        Text(task.scheduledFor.weekdayName)
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(titleColor(task))
                            .strikethrough(task.completed)
                        Spacer()
                        Text(statusLabel(task))
                            .font(.caption.weight(task.missed ? .semibold : .regular))
                            .foregroundStyle(statusColor(task))
                    }
                    .frame(maxWidth: .infinity, minHeight: 40)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(isUpcoming(task))
                .accessibilityLabel(accessibilityLabel(task))
                if task.id != tasks.last?.id {
                    Divider().padding(.leading, 30)
                }
            }
        }
    }

    private func isUpcoming(_ task: GoalTask) -> Bool {
        task.scheduledFor > Date().apiDate
    }

    private func checkinColor(_ task: GoalTask) -> Color {
        if task.completed { return Theme.brand }
        if task.missed { return Theme.negative }
        return Color.secondary
    }

    private func titleColor(_ task: GoalTask) -> Color {
        if task.missed { return Theme.negative }
        if task.completed || isUpcoming(task) { return Color.secondary }
        return Color.primary
    }

    private func statusLabel(_ task: GoalTask) -> String {
        if task.missed { return "Missed" }
        if task.scheduledFor == Date().apiDate { return "Today" }
        return task.scheduledFor.monthDay
    }

    private func statusColor(_ task: GoalTask) -> Color {
        task.missed ? Theme.negative : Color.secondary
    }

    private func accessibilityLabel(_ task: GoalTask) -> String {
        if task.completed { return "Mark \(task.name) incomplete for \(task.scheduledFor.weekdayName)" }
        if task.missed { return "Complete missed \(task.name) for \(task.scheduledFor.weekdayName)" }
        if isUpcoming(task) { return "\(task.name) is due \(task.scheduledFor.weekdayName)" }
        return "Complete \(task.name) for \(task.scheduledFor.weekdayName)"
    }
}

/// Reusable weekly performance snapshot for routine details and future dashboard
/// placements. It intentionally derives from check-ins already in memory.
struct WeeklyRoutineSummary: View {
    let tasks: [GoalTask]
    let reminderTime: String?

    private var completedCount: Int { tasks.filter(\.completed).count }
    private var missedCount: Int { tasks.count { $0.missed && !$0.completed } }
    private var progress: Double {
        tasks.isEmpty ? 0 : Double(completedCount) / Double(tasks.count)
    }
    private var nextTask: GoalTask? {
        tasks.first { !$0.completed && !$0.missed && $0.scheduledFor >= Date().apiDate }
    }

    var body: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle().stroke(Theme.brand.opacity(0.13), lineWidth: 6)
                Circle()
                    .trim(from: 0, to: progress)
                    .stroke(Theme.brand, style: StrokeStyle(lineWidth: 6, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                Text("\(completedCount)/\(tasks.count)")
                    .font(.caption2.weight(.bold).monospacedDigit())
            }
            .frame(width: 54, height: 54)
            VStack(alignment: .leading, spacing: 4) {
                Text("This week")
                    .font(.subheadline.weight(.semibold))
                Text(summaryText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if missedCount > 0 {
                    Label("\(missedCount) missed", systemImage: "exclamationmark.circle.fill")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Theme.negative)
                }
            }
            Spacer(minLength: 6)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(completedCount) of \(tasks.count) completed this week. \(summaryText)")
    }

    private var summaryText: String {
        if !tasks.isEmpty && completedCount == tasks.count { return "Everything is checked off" }
        if let nextTask {
            let time = reminderTime.map { " · \($0.localizedTime)" } ?? ""
            return "Next: \(nextTask.scheduledFor.weekdayName)\(time)"
        }
        if missedCount > 0 { return "Catch up when you’re ready" }
        return "Nothing else scheduled"
    }
}

struct GoalsView: View {
    @EnvironmentObject private var store: MoneyStore
    @State private var adding = false
    @State private var showingHistory = false
    @State private var focusedWidgetFrame: CGRect?

    private var categories: [GoalCategory] { goalCategories(from: store.goals) }

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 14) {
                ForEach(categories) { category in GoalCategoryWidget(category: category) }
                if categories.isEmpty { EmptyWidget(text: "No outcome goals yet") }
            }
            .padding()
        }
        .background(Theme.canvas)
        .coordinateSpace(name: GoalFocusLayout.coordinateSpace)
        .onPreferenceChange(FocusedWidgetFramePreferenceKey.self) { focusedWidgetFrame = $0 }
        .simultaneousGesture(focusDismissGesture)
        .navigationTitle("Goals")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if #available(iOS 26.0, *) {
                ToolbarItemGroup(placement: .navigationBarTrailing) { goalsToolbarButtons }
                    .sharedBackgroundVisibility(.hidden)
            } else {
                ToolbarItemGroup(placement: .navigationBarTrailing) { goalsToolbarButtons }
            }
        }
        .sheet(isPresented: $adding) { AddGoalView(mode: .goal) }
        .sheet(isPresented: $showingHistory) { ArchivedGoalsView().environmentObject(store).tint(Theme.brand) }
        .refreshable { await store.loadGoals() }
    }

    @ViewBuilder private var goalsToolbarButtons: some View {
        Button { showingHistory = true } label: { Image(systemName: "clock.arrow.circlepath") }
            .buttonStyle(.plain)
            .accessibilityLabel("Goal history")
        Button { adding = true } label: { Image(systemName: "plus") }
            .buttonStyle(.plain)
            .accessibilityLabel("Add goal")
    }

    private var focusDismissGesture: some Gesture {
        SpatialTapGesture().onEnded { value in
            guard store.focusedWidgetId != nil,
                  let focusedWidgetFrame,
                  !focusedWidgetFrame.contains(value.location) else { return }
            store.clearFocus()
        }
    }
}

/// A calendar-day checklist assembled from every routine cadence. Weekly and
/// monthly routines appear here only when their scheduled occurrence is today.
struct RoutineTodayWidget: View {
    @EnvironmentObject private var store: MoneyStore
    @State private var editingGoal: GoalEditorSelection?

    var body: some View {
        WidgetCard("Today's to-do") {
            if store.todayRoutineTasks.isEmpty {
                Label("Nothing scheduled today", systemImage: "checkmark.circle")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                ForEach(store.todayRoutineTasks) { task in
                    taskRow(task)
                    if task.id != store.todayRoutineTasks.last?.id { Divider() }
                }
            }
        }
        .sheet(item: $editingGoal) { selection in
            GoalDetailView(goalId: selection.id)
                .environmentObject(store)
                .tint(Theme.brand)
                .dynamicTypeSize(.small)
        }
        .task { await store.loadTodayRoutineTasks() }
    }

    private func taskRow(_ task: GoalTask) -> some View {
        Button {
            Task { await store.check(task) }
        } label: {
            HStack(spacing: 11) {
                Image(systemName: task.completed ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundStyle(task.completed ? Theme.brand : Color.secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(task.name)
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(Color.primary)
                        .strikethrough(task.completed)
                    if task.period != "daily" {
                        Text(task.period.pretty)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if let reminderTime = task.reminderTime {
                    Text(reminderTime.localizedTime)
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pressAndHoldToEdit {
            editingGoal = GoalEditorSelection(id: task.goalId)
        }
        .accessibilityLabel("\(task.name), \(task.completed ? "completed" : "not completed"), \(task.period) routine")
        .accessibilityHint(task.completed ? "Marks this routine incomplete" : "Marks this routine complete")
    }
}

struct GoalCategoryWidget: View {
    @EnvironmentObject private var store: MoneyStore
    let category: GoalCategory
    @AppStorage private var expanded: Bool
    @AppStorage private var chartExpanded: Bool
    @State private var addingToGroup = false
    @State private var pickingIcon = false
    @State private var pickingColor = false
    @State private var nameDraft = ""
    @State private var confirmingEnd = false

    init(category: GoalCategory) {
        self.category = category
        _expanded = AppStorage(wrappedValue: false, LocalUIStateKey.goalCategoryExpanded(category.id))
        _chartExpanded = AppStorage(wrappedValue: false, LocalUIStateKey.goalCategoryChartExpanded(category.id))
    }

    private var focused: Bool { store.isFocused(category.id) }
    private var dimmed: Bool { store.focusedWidgetId != nil && !focused }
    /// Preserves the pre-focus-mode tint rule (custom color, else the ongoing-streak
    /// honey accent, else brand) so unfocused rendering stays identical to today.
    private var groupAccent: Color {
        category.customColor.map(Customization.color(for:))
            ?? (category.id.hasSuffix("section:ongoing") ? Theme.honey : Theme.brand)
    }

    var body: some View {
        categoryCard
        .confirmationDialog(
            "End “\(category.groupName ?? category.name)”?",
            isPresented: $confirmingEnd,
            titleVisibility: .visible
        ) {
            Button("End group", role: .destructive) { endGroup() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This ends all \(category.goals.count) goals in this group.")
        }
        .sheet(isPresented: $addingToGroup) {
            AddGoalView(
                mode: category.composerMode,
                initialGroup: category.groupName,
                initialPeriod: category.cadence
            )
        }
    }

    private var categoryCard: some View {
        WidgetCard("", showsShadow: false) {
            categoryHeader
                // Once the group is focused, leave the header's buttons in sole
                // control of their touch area. Keeping the parent long-press
                // recognizer installed here competes with taps in the icon and
                // color popovers, making their selections appear unresponsive.
                .pressAndHoldToFocus(
                    enabled: category.groupName != nil && !focused
                ) {
                    nameDraft = category.groupName ?? category.name
                    store.focus(category.id)
                }
            expandedContent
        }
            .editableFocusStyle(isFocused: focused, isDimmed: dimmed, cornerRadius: 20)
            .reportFocusedWidgetFrame(focused)
    }

    /// When focused, the icon/name/gauge become live edit controls, so the header can't
    /// be wrapped in the whole-area expand `Button` any more (a `Button` swallows taps
    /// meant for controls nested in its label). Not-focused rendering keeps the original
    /// tap-anywhere-to-expand `Button` wrapper unchanged.
    private var categoryHeader: some View {
        Group {
            if focused {
                headerContent
            } else {
                Button { withAnimation { expanded.toggle() } } label: {
                    headerContent.contentShape(Rectangle())
                }
                    .buttonStyle(.plain)
            }
        }
    }

    private var headerContent: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: expanded ? "chevron.down" : "chevron.right").font(.caption).foregroundStyle(.secondary)
                if focused {
                    Button { pickingIcon = true } label: {
                        if let customIcon = category.customIcon {
                            IconChip(symbol: Customization.symbol(for: customIcon), tint: groupAccent)
                        } else {
                            Image(systemName: "plus.circle")
                                .font(.title3.weight(.medium))
                                .foregroundStyle(Theme.brand)
                                .frame(width: 32, height: 32)
                                .contentShape(Rectangle())
                        }
                    }
                    .buttonStyle(.plain)
                    .popover(isPresented: $pickingIcon) {
                        IconPickerPopover(selected: category.customIcon,
                                          defaultIcon: nil, accent: groupAccent) { token in
                            pickingIcon = false
                            if let name = category.groupName {
                                Task { await store.setGroupAppearance(name, icon: token, color: category.customColor) }
                            }
                        }
                    }
                    .accessibilityLabel(category.customIcon == nil ? "Choose group icon" : "Change group icon")
                } else if let customIcon = category.customIcon {
                    IconChip(symbol: Customization.symbol(for: customIcon), tint: groupAccent)
                } else if category.groupName == nil {
                    IconChip(symbol: category.icon, tint: groupAccent)
                }
                if focused {
                    TextField("Group name", text: $nameDraft)
                        .font(.headline).textFieldStyle(.roundedBorder)
                        .onSubmit { commitFocusedName() }
                } else {
                    Text(category.name).font(.headline)
                }
                GoalCountBadge(count: category.goals.count)
                Spacer()
                if focused {
                    Button { pickingColor = true } label: {
                        Image(systemName: "paintpalette.fill")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(groupAccent)
                            .frame(width: 30, height: 30)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .popover(isPresented: $pickingColor) {
                        ColorPickerPopover(selected: category.customColor) { token in
                            pickingColor = false
                            if let name = category.groupName {
                                Task { await store.setGroupAppearance(name, icon: category.customIcon, color: token) }
                            }
                        }
                    }
                    .accessibilityLabel("Change group color")
                    Button { addingToGroup = true } label: {
                        Image(systemName: "plus")
                            .font(.subheadline.weight(.semibold))
                            .frame(width: 30, height: 30)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(Theme.brand)
                    .accessibilityLabel(category.composerMode == .routine ? "Add routine to group" : "Add goal to group")
                    Button(role: .destructive) { confirmingEnd = true } label: {
                        Image(systemName: "trash")
                            .font(.subheadline.weight(.semibold))
                            .frame(width: 30, height: 30)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(Theme.negative)
                    .accessibilityLabel("End group")
                    Button("Done") { store.clearFocus() }
                        .font(.caption.weight(.semibold)).foregroundStyle(Theme.brand)
                }
                if let aggregate = category.aggregate {
                    Text("\(aggregate.cleanNumber)%")
                        .font(.system(.subheadline, design: .rounded).weight(.bold).monospacedDigit())
                        .foregroundStyle(category.hasGoalOverLimit ? Theme.negative : Theme.brand)
                }
            }
            if let aggregate = category.aggregate {
                GaugeBar(pct: aggregate, tint: groupAccent,
                         over: category.hasGoalOverLimit, reverse: category.aggregateIsReversed)
            }
        }
    }

    @ViewBuilder private var expandedContent: some View {
        if expanded {
            if category.showsCombinedChart && category.goals.contains(where: { !$0.history.isEmpty }) {
                Button(chartExpanded ? "Hide combined trend" : "Show combined trend") { withAnimation { chartExpanded.toggle() } }
                    .font(.caption).foregroundStyle(.secondary)
                if chartExpanded { GoalCategoryChart(goals: category.goals) }
            }
            ForEach(category.goals) { goal in
                Divider()
                GoalRow(goal: goal)
            }
        }
    }

    private func commitFocusedName() {
        performGroupRename(to: nameDraft, clearsFocus: true)
    }

    private func performGroupRename(to proposedName: String, clearsFocus: Bool) {
        let cleanName = proposedName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanName.isEmpty, cleanName.count <= 80 else {
            if clearsFocus { nameDraft = category.groupName ?? category.name }
            return
        }
        guard cleanName != category.groupName else {
            if clearsFocus { store.clearFocus() }
            return
        }
        Task {
            if await store.renameGoalGroup(category.goals, to: cleanName) {
                let newId = category.groupWidgetId(named: cleanName)
                DashboardSettings.replaceWidget(category.id, with: newId)
                UserDefaults.standard.set(expanded, forKey: LocalUIStateKey.goalCategoryExpanded(newId))
                UserDefaults.standard.set(chartExpanded, forKey: LocalUIStateKey.goalCategoryChartExpanded(newId))
                if clearsFocus { store.clearFocus() }
            } else if clearsFocus {
                nameDraft = category.groupName ?? category.name
            }
        }
    }

    private func endGroup() {
        Task {
            if await store.endGoalGroup(category.goals) {
                DashboardSettings.removeWidget(category.id)
            }
        }
    }
}

struct GoalCountBadge: View {
    let count: Int
    var body: some View {
        Text("\(count)").font(.caption.bold()).foregroundStyle(.secondary)
            .padding(.horizontal, 7).padding(.vertical, 3)
            .background(Color.secondary.opacity(0.1)).clipShape(Capsule())
    }
}

struct GoalCategoryChart: View {
    let goals: [Goal]
    private var chartGoals: [Goal] { goals.filter { !$0.history.isEmpty } }
    private var mixedUnits: Bool { Set(chartGoals.map(\.unit)).count > 1 }

    var body: some View {
        Chart {
            ForEach(chartGoals) { goal in
                ForEach(GoalChartTimeline.daily(goal.history)) { point in
                    LineMark(
                        x: .value("Date", point.day),
                        y: .value("Value", normalized(point.value, goal: goal))
                    )
                    .foregroundStyle(by: .value("Goal", goal.name))
                    .lineStyle(.init(lineWidth: 2))
                    .interpolationMethod(.stepEnd)
                }
            }
        }
        .chartForegroundStyleScale(range: Theme.chartScale)
        .chartLegend(position: .bottom, spacing: 6)
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 6)) {
                AxisGridLine()
                AxisTick()
                AxisValueLabel(format: .dateTime.month(.abbreviated).day())
            }
        }
        .frame(height: 180)
    }

    private func normalized(_ value: Double, goal: Goal) -> Double {
        mixedUnits && (goal.target ?? 0) != 0 ? value / (goal.target ?? 1) * 100 : value
    }
}

/// One slim row per goal: name, value, thin gauge. Single tap opens the detail
/// sheet; on manual goals, double-tap the left half to subtract a step and the
/// right half to add one.
struct GoalEditorSelection: Identifiable {
    let id: Int
}

struct GoalRow: View {
    @EnvironmentObject private var store: MoneyStore
    let goal: Goal
    @State private var showingDetail = false

    private var accent: Color {
        goal.groupColor.map(Customization.color(for:))
            ?? (goal.kind == "streak" ? Theme.honey : Theme.brand)
    }
    private var usesScheduledCheckins: Bool { goal.usesScheduledCheckins }
    private var qualifyingWeeklyStreak: Int? {
        guard let streak = goal.weeklyStreak, streak >= 3 else { return nil }
        return streak
    }
    private var currentWeekTasks: [GoalTask] {
        WeeklyTaskWindow.currentWeek(from: store.weekRoutineTasks, goal: goal)
    }

    var body: some View {
        rowContent
        .pressAndHoldToEdit { showingDetail = true }
        .sheet(isPresented: $showingDetail) {
            GoalDetailView(goalId: goal.id).environmentObject(store).tint(Theme.brand).dynamicTypeSize(.small)
        }
        .accessibilityHint(goal.isManual && !usesScheduledCheckins ? "Double-tap left to subtract \(goal.format(goal.step)), right to add it. Use the details button for more." : "Tap for details.")
        .task {
            if usesScheduledCheckins { await store.loadTodayRoutineTasks() }
        }
    }

    private var rowContent: some View {
        HStack(alignment: .top, spacing: 8) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 8) {
                    Text(goal.name)
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(Color.primary)
                        .lineLimit(1)
                    if let streak = qualifyingWeeklyStreak {
                        Text("🔥 \(streak)")
                            .font(.caption.weight(.bold).monospacedDigit())
                            .foregroundStyle(.secondary)
                            .accessibilityLabel("\(streak) week streak")
                    }
                    Spacer(minLength: 8)
                    if !usesScheduledCheckins && goal.kind != "streak" {
                        Text(valueLabel).font(.subheadline.monospacedDigit()).foregroundStyle(.secondary).fitOneLine()
                    }
                }
                if goal.period == "weekly" {
                    if usesScheduledCheckins {
                        HStack(spacing: 10) {
                            if let reminderTime = goal.reminderTime {
                                Label(reminderTime.localizedTime, systemImage: "clock")
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .font(.caption.weight(.medium))
                    } else {
                        Label(
                            (goal.weeklyScheduleLabel.isEmpty ? "No days selected" : goal.weeklyScheduleLabel)
                                + (goal.reminderTime.map { " · \($0.localizedTime)" } ?? ""),
                            systemImage: "calendar"
                        )
                        .font(.caption)
                        .foregroundStyle(goal.weeklyScheduleLabel.isEmpty ? Theme.negative : .secondary)
                    }
                } else if let reminderTime = goal.reminderTime {
                    Label(reminderTime.localizedTime, systemImage: "clock")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if usesScheduledCheckins, !currentWeekTasks.isEmpty {
                    WeeklyCheckinStrip(tasks: currentWeekTasks)
                }
                if goal.kind == "streak" { streakSummary }
                if !usesScheduledCheckins && goal.kind != "streak" { goalGauge }
            }
            .contentShape(Rectangle())
            .overlay {
                if !usesScheduledCheckins { interactionOverlay }
            }
            Button { showingDetail = true } label: {
                Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
                    .frame(width: 26, height: 28).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Details for \(goal.name)")
        }
        .padding(.vertical, 4)
        .background(Theme.card)
    }

    @ViewBuilder private var goalGauge: some View {
        if let pct = store.displayedPct(goal) {
            GaugeBar(pct: pct, tint: accent, over: goal.status == "over",
                     height: 6, reverse: goal.direction == "under")
        }
    }

    private var streakSummary: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                ZStack {
                    Circle().fill(Theme.honey.opacity(0.16))
                    Image(systemName: "flame.fill")
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(Theme.honey)
                }
                .frame(width: 42, height: 42)
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline, spacing: 4) {
                        Text("\(goal.days ?? Int(goal.currentValue))")
                            .font(.title2.weight(.bold).monospacedDigit())
                        Text((goal.days ?? Int(goal.currentValue)) == 1 ? "day" : "days")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                    }
                    Text("Current run")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if let best = goal.bestDays {
                    VStack(alignment: .trailing, spacing: 2) {
                        Label("Best", systemImage: "trophy.fill")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(Theme.honey)
                        Text("\(best) days")
                            .font(.caption.weight(.semibold).monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
            }
            if let target = goal.target, let pct = goal.pct {
                GaugeBar(pct: pct, tint: Theme.honey, height: 5)
                HStack {
                    Text(goal.status == "milestone" ? "Milestone reached" : "Next milestone")
                    Spacer()
                    Text("\(Int(target)) days")
                }
                .font(.caption2)
                .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder private var interactionOverlay: some View {
        // Only manual goals register double-taps; keeping single-tap off this
        // surface is what makes both gestures fire without delay.
        if goal.isManual && !usesScheduledCheckins {
            HStack(spacing: 0) {
                Color.clear.contentShape(Rectangle()).onTapGesture(count: 2) { decrement() }
                Color.clear.contentShape(Rectangle()).onTapGesture(count: 2) { increment() }
            }
        } else {
            Color.clear.contentShape(Rectangle()).onTapGesture { showingDetail = true }
        }
    }

    private func increment() { store.queueAdjust(goal, by: goal.step) }
    private func decrement() { store.queueAdjust(goal, by: -goal.step) }

    private var valueLabel: String {
        let current = store.displayedValue(goal)
        if let target = goal.target {
            let comparison = goal.direction == "under" ? "→ <" : "/"
            return "\(goal.format(current)) \(comparison) \(goal.format(target))"
        }
        return goal.format(current)
    }
}

/// Dashboard widget for a single pinned goal.
struct GoalWidget: View {
    let goal: Goal
    var body: some View { WidgetCard("") { GoalRow(goal: goal) } }
}

/// Everything that used to crowd the goal card lives here: steppers, exact-value
/// and target editing, history, and milestones, including ending the goal.
struct GoalDetailView: View {
    @EnvironmentObject private var store: MoneyStore
    let goalId: Int
    @State private var editingValue = false
    @State private var valueDraft = ""
    @State private var editingStep = false
    @State private var stepDraft = ""
    @State private var editingName = false
    @State private var nameDraft = ""
    @State private var editingRoutineSchedule = false
    @State private var confirmingStreakReset = false
    @State private var editingTarget = false
    @State private var targetDraft = ""

    private var goal: Goal? { store.goals.first { $0.id == goalId } }
    private var qualifyingWeeklyStreak: Int? {
        guard let streak = goal?.weeklyStreak, streak >= 3 else { return nil }
        return streak
    }

    var body: some View {
        if let goal {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 10) {
                        if editingName {
                            TextField(goal.isRoutine ? "Routine name" : "Goal name", text: $nameDraft)
                                .font(.title3.weight(.bold))
                                .textFieldStyle(.roundedBorder)
                                .onSubmit { commitGoalName(goal) }
                            Button { commitGoalName(goal) } label: { Image(systemName: "checkmark") }
                                .buttonStyle(.plain)
                                .accessibilityLabel("Save name")
                            Button { editingName = false } label: { Image(systemName: "xmark") }
                                .buttonStyle(.plain)
                                .foregroundStyle(.secondary)
                                .accessibilityLabel("Cancel name edit")
                        } else {
                            Text(goal.name).font(.title3.weight(.bold))
                            Button {
                                nameDraft = goal.name
                                editingName = true
                            } label: {
                                Image(systemName: "pencil")
                                    .font(.caption.weight(.semibold))
                            }
                            .buttonStyle(.plain)
                            .foregroundStyle(.secondary)
                            .accessibilityLabel("Rename \(goal.name)")
                        }
                        if let streak = qualifyingWeeklyStreak {
                            Text("🔥 \(streak)")
                                .font(.subheadline.weight(.bold).monospacedDigit())
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                    }
                    if goal.kind == "streak" { streakDetailHero(goal) }
                    if !goal.usesScheduledCheckins && goal.kind != "streak" {
                        HStack(alignment: .firstTextBaseline, spacing: 7) {
                            Text(goal.format(store.displayedValue(goal))).font(.heroNumber.monospacedDigit()).fitOneLine()
                            if let target = goal.target {
                                Button {
                                    targetDraft = target.editableNumber
                                    editingTarget = true
                                } label: {
                                    HStack(spacing: 4) {
                                        Text("\(goal.direction == "under" ? "→ <" : "/") \(goal.format(target))")
                                        Image(systemName: "pencil").font(.caption2)
                                    }
                                    .font(.subheadline.monospacedDigit())
                                    .foregroundStyle(.secondary)
                                    .fitOneLine()
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel("Edit target, currently \(goal.format(target))")
                            } else {
                                Button("Set target") {
                                    targetDraft = ""
                                    editingTarget = true
                                }
                                .font(.caption.weight(.medium))
                                .buttonStyle(.bordered)
                                .controlSize(.small)
                            }
                            Spacer()
                            if let pct = store.displayedPct(goal) { Text("\(pct.formatted())%").font(.subheadline.monospacedDigit()).foregroundStyle(goal.status == "over" ? Theme.negative : .secondary) }
                        }
                    }
                    if goal.isManual && !goal.usesScheduledCheckins { editor(goal) }
                    if goal.usesScheduledCheckins { weeklyChecklist(goal) }
                    if !goal.usesScheduledCheckins && goal.kind != "streak", let pct = store.displayedPct(goal) {
                        GaugeBar(
                            pct: pct,
                            tint: goal.groupColor.map(Customization.color(for:))
                                ?? (goal.kind == "streak" ? Theme.honey : Theme.brand),
                            over: goal.status == "over",
                            reverse: goal.direction == "under"
                        )
                    }
                    if !goal.usesScheduledCheckins { metadata(goal) }
                    if goal.isRoutine && goal.kind != "streak" && goal.period != "once" {
                        Button { editingRoutineSchedule = true } label: {
                            Label("Edit schedule", systemImage: "calendar.badge.clock")
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                    }
                    if !goal.usesScheduledCheckins && (!goal.history.isEmpty || !goal.milestones.isEmpty) {
                        Divider()
                        GoalHistoryChart(goal: goal)
                        milestones(goal)
                    }
                    if goal.kind == "streak" {
                        Divider()
                        Button(role: .destructive) { confirmingStreakReset = true } label: {
                            Label("Reset streak", systemImage: "arrow.counterclockwise")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 20)
                .padding(.top, 32)
            }
            .background(Theme.canvas)
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
            .sheet(isPresented: $editingRoutineSchedule) {
                RoutineScheduleEditor(goal: goal).environmentObject(store).tint(Theme.brand)
            }
            .task {
                if goal.usesScheduledCheckins { await store.loadTodayRoutineTasks() }
            }
            .confirmationDialog(
                "Reset \(goal.name)?",
                isPresented: $confirmingStreakReset,
                titleVisibility: .visible
            ) {
                Button("Reset streak", role: .destructive) {
                    Task { await store.resetStreak(goal) }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("The current counter returns to zero. This run is preserved as your best streak when applicable.")
            }
            .alert("Goal target", isPresented: $editingTarget) {
                TextField("Target", text: $targetDraft).keyboardType(.decimalPad)
                Button("Cancel", role: .cancel) {}
                Button("Save") {
                    if let value = Double(targetDraft), value > 0 {
                        Task { await store.setGoalTarget(goal, target: value) }
                    }
                }
                .disabled(Double(targetDraft).map { $0 <= 0 } ?? true)
            } message: {
                Text(goal.direction == "under" ? "Set the highest value that still counts as success." : "Set the final value you want to reach.")
            }
            .alert("Step amount", isPresented: $editingStep) {
                TextField("Amount", text: $stepDraft).keyboardType(.decimalPad)
                Button("Cancel", role: .cancel) {}
                Button("Save") {
                    if let value = Double(stepDraft), value > 0 { Task { await store.setGoalStep(goal, step: value) } }
                }.disabled(Double(stepDraft).map { $0 <= 0 } ?? true)
            } message: {
                Text("Steppers and double-tap change this goal by this amount.")
            }
            .overlay {
                if store.goalCelebration?.id == goal.id {
                    GoalCompletionOverlay(goal: goal)
                        .environmentObject(store)
                }
            }
        }
    }

    @ViewBuilder private func editor(_ goal: Goal) -> some View {
        HStack(spacing: 10) {
            Button { store.queueAdjust(goal, by: -goal.step) } label: { Image(systemName: "minus") }
                .buttonStyle(IncrementButtonStyle()).disabled(store.displayedValue(goal) <= 0)
            if editingValue {
                TextField("Value", text: $valueDraft).keyboardType(.decimalPad).textFieldStyle(.roundedBorder).frame(width: 100)
                Button { commitValue(goal) } label: { Image(systemName: "checkmark") }.buttonStyle(IncrementButtonStyle())
                Button { editingValue = false } label: { Image(systemName: "xmark") }.buttonStyle(IncrementButtonStyle())
            } else {
                Button("Edit value") { valueDraft = store.displayedValue(goal).cleanNumber; editingValue = true }
                    .font(.caption.weight(.medium)).buttonStyle(.bordered).controlSize(.small)
            }
            Button { store.queueAdjust(goal, by: goal.step) } label: { Image(systemName: "plus") }
                .buttonStyle(IncrementButtonStyle())
            Spacer()
            Button("Step \(goal.format(goal.step))") { stepDraft = goal.step.cleanNumber; editingStep = true }
                .font(.caption.weight(.medium)).foregroundStyle(.secondary)
        }
    }

    private func streakDetailHero(_ goal: Goal) -> some View {
        let current = goal.days ?? Int(goal.currentValue)
        return VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 14) {
                ZStack {
                    Circle().fill(Theme.honey.opacity(0.2))
                    Image(systemName: "flame.fill")
                        .font(.system(size: 28, weight: .semibold))
                        .foregroundStyle(Theme.honey)
                }
                .frame(width: 58, height: 58)
                VStack(alignment: .leading, spacing: 1) {
                    HStack(alignment: .firstTextBaseline, spacing: 5) {
                        Text("\(current)")
                            .font(.system(size: 36, weight: .bold, design: .rounded).monospacedDigit())
                        Text(current == 1 ? "day" : "days")
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(.secondary)
                    }
                    Text("and counting")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if let best = goal.bestDays {
                    VStack(alignment: .trailing, spacing: 3) {
                        Image(systemName: "trophy.fill").foregroundStyle(Theme.honey)
                        Text("Best \(best)")
                            .font(.caption.weight(.semibold).monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
            }
            if let target = goal.target, let pct = goal.pct {
                VStack(alignment: .leading, spacing: 6) {
                    GaugeBar(pct: pct, tint: Theme.honey)
                    HStack {
                        Text("Next milestone")
                        Spacer()
                        Text("\(Int(target)) days")
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
            }
        }
        .padding(16)
        .background(
            LinearGradient(
                colors: [Theme.honey.opacity(0.15), Theme.card],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            ),
            in: RoundedRectangle(cornerRadius: 18, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(Theme.honey.opacity(0.2))
        }
    }

    @ViewBuilder private func weeklyChecklist(_ goal: Goal) -> some View {
        let tasks = currentWeekTasks(for: goal)
        VStack(alignment: .leading, spacing: 12) {
            if tasks.isEmpty {
                Text("No more scheduled days this week.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                WeeklyRoutineSummary(tasks: tasks, reminderTime: goal.reminderTime)
                Divider()
                WeeklyCheckinStrip(tasks: tasks)
            }
        }
        .padding(.vertical, 4)
    }

    private func currentWeekTasks(for goal: Goal) -> [GoalTask] {
        WeeklyTaskWindow.currentWeek(from: store.weekRoutineTasks, goal: goal)
    }

    private func metadata(_ goal: Goal) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                if let linked = goal.linkedLabel { Label(linked.pretty, systemImage: "link") }
                if let metric = goal.financialMetric { Label(metric.pretty, systemImage: "chart.xyaxis.line") }
                if goal.period != "once" { Text("· \(periodLabel(goal))") }
                if let deadline = goal.deadline { Spacer(); Text("by \(deadline.shortDate)") }
            }
            if goal.period == "weekly" {
                Label(goal.weeklyScheduleLabel.isEmpty ? "No scheduled days" : goal.weeklyScheduleLabel, systemImage: "calendar")
            }
            if let reminderTime = goal.reminderTime {
                Label(reminderTime.localizedTime, systemImage: "clock")
            }
        }.font(.caption).foregroundStyle(.secondary)
    }

    @ViewBuilder private func milestones(_ goal: Goal) -> some View {
        if !goal.milestones.isEmpty {
            Label(goal.milestones.map { "\(goal.format($0.value)) (\($0.at.shortDate))" }.joined(separator: " · "), systemImage: "medal.fill")
                .font(.caption).foregroundStyle(Theme.honey)
        }
    }

    private func periodLabel(_ goal: Goal) -> String {
        switch goal.period {
        case "daily": return "today"
        case "weekly": return "this week"
        case "monthly": return "this month"
        case "interval": return "on its interval"
        default: return ""
        }
    }

    private func commitValue(_ goal: Goal) {
        guard let value = Double(valueDraft) else { return }
        editingValue = false
        Task { await store.setGoalProgress(goal, current: value) }
    }

    private func commitGoalName(_ goal: Goal) {
        let clean = nameDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty, clean.count <= 80 else { return }
        editingName = false
        if clean != goal.name { Task { await store.setGoalName(goal, name: clean) } }
    }
}

enum GoalChartRange: String, CaseIterable, Identifiable {
    case week, month, threeMonths, sixMonths, year, all

    var id: String { rawValue }
    var label: String {
        switch self {
        case .week: return "1W"
        case .month: return "1M"
        case .threeMonths: return "3M"
        case .sixMonths: return "6M"
        case .year: return "1Y"
        case .all: return "All"
        }
    }
    var days: Int? {
        switch self {
        case .week: return 7
        case .month: return 30
        case .threeMonths: return 90
        case .sixMonths: return 180
        case .year: return 365
        case .all: return nil
        }
    }
}

/// Reusable stock-style range control for goal charts and dashboard widgets.
struct GoalChartRangePicker: View {
    @Binding var selection: GoalChartRange

    var body: some View {
        HStack(spacing: 0) {
            ForEach(GoalChartRange.allCases) { range in
                Button { selection = range } label: {
                    Text(range.label)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(selection == range ? Theme.brand : .secondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                        .overlay(alignment: .bottom) {
                            Rectangle()
                                .fill(selection == range ? Theme.brand : .clear)
                                .frame(height: 2)
                        }
                }
                .buttonStyle(.plain)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Chart time range")
    }
}

/// A widget-ready goal trajectory that defaults to one week and preserves the
/// selected time range locally for each goal.
struct GoalHistoryChart: View {
    let goal: Goal
    @AppStorage private var selectedRangeRaw: String

    init(goal: Goal) {
        self.goal = goal
        _selectedRangeRaw = AppStorage(
            wrappedValue: GoalChartRange.week.rawValue,
            LocalUIStateKey.goalChartRange(goal.id)
        )
    }

    private var selection: Binding<GoalChartRange> {
        Binding(
            get: { GoalChartRange(rawValue: selectedRangeRaw) ?? .week },
            set: { selectedRangeRaw = $0.rawValue }
        )
    }

    private var visibleHistory: [GoalChartPoint] {
        let daily = GoalChartTimeline.daily(goal.history)
        guard let days = selection.wrappedValue.days,
              let cutoff = Calendar.current.date(byAdding: .day, value: -days, to: Date()) else {
            return daily
        }
        return daily.filter { $0.day >= Calendar.current.startOfDay(for: cutoff) }
    }

    var body: some View {
        VStack(spacing: 8) {
            GoalChartRangePicker(selection: selection)
            if visibleHistory.isEmpty {
                Text("No points in this range yet.")
                    .font(.caption).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 150)
            } else {
                Chart {
                    ForEach(visibleHistory) { point in
                        LineMark(
                            x: .value("Date", point.day),
                            y: .value("Value", point.value)
                        )
                        .foregroundStyle(Theme.brand)
                        .lineStyle(.init(lineWidth: 2))
                        .interpolationMethod(.stepEnd)
                    }
                    ForEach(visibleHistory.filter(\.isRecorded)) { point in
                        PointMark(
                            x: .value("Date", point.day),
                            y: .value("Value", point.value)
                        )
                        .foregroundStyle(Theme.brand)
                    }
                    if let target = goal.target {
                        RuleMark(y: .value("Target", target))
                            .foregroundStyle(.secondary.opacity(0.45))
                            .lineStyle(.init(lineWidth: 1, dash: [5, 4]))
                    }
                    ForEach(goal.milestones) { milestone in
                        RuleMark(y: .value("Milestone", milestone.value))
                            .foregroundStyle(Theme.honey)
                            .lineStyle(.init(lineWidth: 1, dash: [3, 3]))
                    }
                }
                .chartXAxis {
                    AxisMarks(values: .automatic(desiredCount: selection.wrappedValue == .week ? 7 : 6)) {
                        AxisGridLine()
                        AxisTick()
                        AxisValueLabel(format: .dateTime.month(.abbreviated).day())
                    }
                }
                .frame(height: 170)
            }
        }
    }
}

/// Reusable completion surface for goal rows, detail sheets, and future
/// dashboard goal widgets. The backend records the old target as a milestone
/// before advancing it, so either action keeps a durable audit trail.
struct GoalCompletionOverlay: View {
    @EnvironmentObject private var store: MoneyStore
    let goal: Goal
    @State private var targetDraft: Double
    @State private var saving = false

    init(goal: Goal) {
        self.goal = goal
        _targetDraft = State(initialValue: Self.suggestedTarget(for: goal))
    }

    var body: some View {
        ZStack {
            Color.black.opacity(0.42).ignoresSafeArea()
            ConfettiCelebrationView()
                .allowsHitTesting(false)

            VStack(spacing: 18) {
                Image(systemName: "trophy.fill")
                    .font(.system(size: 32, weight: .bold))
                    .foregroundStyle(Theme.honey)
                VStack(spacing: 6) {
                    celebrationHeadline
                    Text(goal.name)
                        .font(.headline)
                        .multilineTextAlignment(.center)
                    Text(GoalCompletionStatistic.personal(for: goal))
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }

                VStack(alignment: .leading, spacing: 7) {
                    Text(goal.direction == "under" ? "Set a lower goal" : "Raise your goal")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    HStack(spacing: 8) {
                        if goal.unit == "$" {
                            Text("$").foregroundStyle(.secondary)
                        }
                        TextField("New target", value: $targetDraft, format: .number)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                        if goal.unit != "$", !goal.unit.isEmpty {
                            Text(goal.unit).foregroundStyle(.secondary)
                        }
                    }
                    .padding(.horizontal, 12)
                    .frame(minHeight: 44)
                    .background(Color.secondary.opacity(0.1), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                }

                HStack(spacing: 8) {
                    Button { advance() } label: {
                        Label(goal.direction == "under" ? "Lower" : "Raise", systemImage: goal.direction == "under" ? "arrow.down.right" : "arrow.up.right")
                    }
                    .buttonStyle(CompletionActionButtonStyle(tone: .brand))
                    .disabled(!validTarget || saving)

                    Button {
                        saving = true
                        Task {
                            await store.endGoal(goal.id)
                            saving = false
                        }
                    } label: {
                        Label("End goal", systemImage: "flag.checkered")
                    }
                    .buttonStyle(CompletionActionButtonStyle(tone: .finish))
                    .disabled(saving)
                    .accessibilityHint("Ends this goal and keeps its history")

                    Button { store.dismissGoalCelebration() } label: {
                        Label("Later", systemImage: "clock")
                    }
                    .buttonStyle(CompletionActionButtonStyle(tone: .neutral))
                    .disabled(saving)
                }
            }
            .padding(24)
            .frame(maxWidth: 360)
            .background(Theme.card, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).strokeBorder(Theme.cardStroke))
            .shadow(color: Color.black.opacity(0.2), radius: 28, y: 12)
            .padding(24)
        }
        .accessibilityAddTraits(.isModal)
    }

    @ViewBuilder private var celebrationHeadline: some View {
        let phrase = GoalCelebrationPhrase.forGoal(goal)
        if phrase.italic {
            Text(phrase.text).font(.title2.bold()).italic()
        } else {
            Text(phrase.text).font(.title2.bold())
        }
    }

    private var validTarget: Bool {
        guard targetDraft > 0, let target = goal.target else { return false }
        return goal.direction == "under" ? targetDraft < target : targetDraft > target
    }

    private func advance() {
        guard validTarget else { return }
        saving = true
        Task {
            await store.advanceGoal(goal, target: targetDraft)
            saving = false
        }
    }

    private static func suggestedTarget(for goal: Goal) -> Double {
        guard let target = goal.target else { return max(goal.step, 1) }
        let change = max(goal.step, target * 0.1)
        if goal.direction == "under" {
            return max(0.01, target - change)
        }
        return max(target + change, goal.currentValue + change)
    }
}

struct GoalCelebrationPhrase {
    let text: String
    let italic: Bool

    private static let library: [GoalCelebrationPhrase] = [
        .init(text: "BAAAAANG", italic: false),
        .init(text: "*Feels the aura", italic: true),
        .init(text: "Well done.", italic: false),
        .init(text: "Knew you could do it.", italic: false),
        .init(text: "Was there ever a doubt?", italic: false),
        .init(text: "Okay, show-off.", italic: false),
    ]

    static func forGoal(_ goal: Goal) -> GoalCelebrationPhrase {
        library[goal.id % library.count]
    }
}

enum GoalCompletionStatistic {
    static func personal(for goal: Goal) -> String {
        guard let target = goal.target, target > 0 else {
            return "\(goal.history.count) progress updates got you here."
        }

        let difference = goal.direction == "under"
            ? max(0, target - goal.currentValue)
            : max(0, goal.currentValue - target)
        let percent = difference / target * 100
        if percent >= 0.05 {
            let direction = goal.direction == "under" ? "below your limit" : "past your target"
            return "You finished \(percent.cleanNumber)% \(direction)."
        }

        let loggedDays = Set(goal.history.map { String($0.at.prefix(10)) }).count
        if loggedDays > 1 {
            return "You stacked progress across \(loggedDays) logged days."
        }
        return "You landed right on \(goal.format(target))."
    }
}

enum CompletionActionTone { case brand, finish, neutral }

struct CompletionActionButtonStyle: ButtonStyle {
    let tone: CompletionActionTone
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.caption.weight(.semibold))
            .lineLimit(1)
            .minimumScaleFactor(0.8)
            .frame(maxWidth: .infinity, minHeight: 42)
            .foregroundStyle(foregroundColor)
            .background(backgroundColor.opacity(configuration.isPressed ? 0.72 : 1))
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(strokeColor))
            .opacity(isEnabled ? 1 : 0.45)
    }

    private var foregroundColor: Color {
        tone == .brand ? Theme.onBrand : tone == .finish ? Theme.negative : .primary
    }

    private var backgroundColor: Color {
        switch tone {
        case .brand: return Theme.brand
        case .finish: return Theme.negative.opacity(0.12)
        case .neutral: return Color.secondary.opacity(0.1)
        }
    }

    private var strokeColor: Color {
        switch tone {
        case .brand: return Theme.brand
        case .finish: return Theme.negative.opacity(0.28)
        case .neutral: return Color.secondary.opacity(0.16)
        }
    }
}

private struct ConfettiParticle: Identifiable {
    let id: Int
    let horizontalFraction: CGFloat
    let delay: Double
    let duration: Double
    let rotation: Double
    let colorIndex: Int

    static let celebration: [ConfettiParticle] = {
        var result: [ConfettiParticle] = []
        for index in 0..<36 {
            let horizontalIndex: Int = (index * 37) % 100
            let horizontalFraction = CGFloat(horizontalIndex) / 100
            let delayIndex: Int = index % 9
            let durationIndex: Int = index % 5
            let rotationIndex: Int = (index * 47) % 420
            let colorIndex: Int = index % Theme.chartScale.count
            let particle = ConfettiParticle(
                id: index,
                horizontalFraction: horizontalFraction,
                delay: Double(delayIndex) * 0.055,
                duration: 1.25 + Double(durationIndex) * 0.12,
                rotation: Double(180 + rotationIndex),
                colorIndex: colorIndex
            )
            result.append(particle)
        }
        return result
    }()
}

/// Lightweight, dependency-free confetti that can be embedded in any widget or
/// modal without coupling celebration behavior to the Goals screen.
struct ConfettiCelebrationView: View {
    @State private var falling = false

    var body: some View {
        GeometryReader { proxy in
            ForEach(ConfettiParticle.celebration) { particle in
                RoundedRectangle(cornerRadius: 2)
                    .fill(Theme.chartScale[particle.colorIndex])
                    .frame(width: particle.id.isMultiple(of: 3) ? 7 : 5, height: 11)
                    .rotationEffect(.degrees(falling ? particle.rotation : 0))
                    .position(
                        x: proxy.size.width * particle.horizontalFraction,
                        y: falling ? proxy.size.height + 18 : -18
                    )
                    .animation(
                        .easeIn(duration: particle.duration).delay(particle.delay),
                        value: falling
                    )
            }
        }
        .ignoresSafeArea()
        .onAppear { falling = true }
    }
}

struct ArchivedGoalsView: View {
    @EnvironmentObject private var store: MoneyStore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 14) {
                    ForEach(store.archivedGoals) { goal in
                        ArchivedGoalHistoryWidget(goal: goal)
                    }
                    if store.archivedGoals.isEmpty {
                        EmptyWidget(text: "Ended goals will appear here with their full history.")
                    }
                }
                .padding()
            }
            .background(Theme.canvas)
            .navigationTitle("Goal History")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .task { await store.loadArchivedGoals() }
            .refreshable { await store.loadArchivedGoals() }
        }
    }
}

/// Read-only ended-goal widget. Its expanded state is stored locally so the
/// same component behaves consistently in Goal History or a custom dashboard.
struct ArchivedGoalHistoryWidget: View {
    let goal: Goal
    @AppStorage private var expanded: Bool

    init(goal: Goal) {
        self.goal = goal
        _expanded = AppStorage(wrappedValue: false, LocalUIStateKey.archivedGoalExpanded(goal.id))
    }

    var body: some View {
        WidgetCard("", showsShadow: false) {
            Button { withAnimation { expanded.toggle() } } label: {
                HStack(spacing: 10) {
                    IconChip(symbol: "flag.checkered", tint: Theme.honey)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(goal.name).font(.headline).foregroundStyle(.primary)
                        Text(endLabel).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Image(systemName: expanded ? "chevron.down" : "chevron.right")
                        .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                }
            }
            .buttonStyle(.plain)

            if expanded {
                Divider()
                HStack(alignment: .firstTextBaseline) {
                    Text("Final value").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Text(finalValueLabel).font(.subheadline.weight(.semibold).monospacedDigit())
                }
                if !goal.history.isEmpty {
                    let timeline = GoalChartTimeline.dailyThroughStoredEnd(
                        goal.history,
                        endedAt: goal.archivedAt
                    )
                    Chart {
                        ForEach(timeline) { point in
                            LineMark(
                                x: .value("Date", point.day),
                                y: .value("Value", point.value)
                            )
                            .foregroundStyle(Theme.brand)
                            .interpolationMethod(.stepEnd)
                        }
                        ForEach(timeline.filter(\.isRecorded)) { point in
                            PointMark(
                                x: .value("Date", point.day),
                                y: .value("Value", point.value)
                            )
                            .foregroundStyle(Theme.brand)
                        }
                    }
                    .chartXAxis {
                        AxisMarks(values: .automatic(desiredCount: 6)) {
                            AxisGridLine()
                            AxisTick()
                            AxisValueLabel(format: .dateTime.month(.abbreviated).day())
                        }
                    }
                    .frame(height: 150)
                } else {
                    Text("No progress entries were recorded.").font(.caption).foregroundStyle(.secondary)
                }
                if !goal.milestones.isEmpty {
                    Label(
                        goal.milestones.map { "\(goal.format($0.value)) (\($0.at.shortDate))" }.joined(separator: " · "),
                        systemImage: "medal.fill"
                    )
                    .font(.caption)
                    .foregroundStyle(Theme.honey)
                }
            }
        }
    }

    private var endLabel: String {
        guard let archivedAt = goal.archivedAt else { return "Ended" }
        return "Ended \(String(archivedAt.prefix(10)).shortDate)"
    }

    private var finalValueLabel: String {
        guard let target = goal.target else { return goal.format(goal.currentValue) }
        let comparison = goal.direction == "under" ? "→ <" : "/"
        return "\(goal.format(goal.currentValue)) \(comparison) \(goal.format(target))"
    }
}

struct IncrementButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.caption.bold()).foregroundStyle(Theme.brand).frame(width: 26, height: 26)
            .background(Theme.brand.opacity(configuration.isPressed ? 0.25 : 0.1))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

struct WeekdayPicker: View {
    @Binding var selection: Set<String>

    var body: some View {
        HStack(spacing: 5) {
            ForEach(WeekdaySchedule.ordered, id: \.self) { day in
                let selected = selection.contains(day)
                Button {
                    if selected { selection.remove(day) } else { selection.insert(day) }
                } label: {
                    Text(String(day.prefix(1)).uppercased())
                        .font(.caption2.bold())
                        .frame(maxWidth: .infinity).frame(height: 30)
                        .foregroundStyle(selected ? Color.white : Color.secondary)
                        .background(selected ? Theme.brand : Color.secondary.opacity(0.1))
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
                .buttonStyle(.plain)
                .accessibilityLabel(day.capitalized)
                .accessibilityValue(selected ? "Selected" : "Not selected")
            }
        }
    }
}

struct RoutineScheduleEditor: View {
    @EnvironmentObject private var store: MoneyStore
    @Environment(\.dismiss) private var dismiss
    let goal: Goal
    @State private var selection: Set<String>
    @State private var weekStartsOn: String
    @State private var hasReminderTime: Bool
    @State private var reminderTime: Date
    @State private var repeatUntilCompleted: Bool
    @State private var nudgeIntervalMinutes: Int
    @State private var important: Bool
    @State private var saving = false

    init(goal: Goal) {
        self.goal = goal
        _selection = State(initialValue: Set(goal.scheduledWeekdays))
        _weekStartsOn = State(initialValue: goal.weeklyResetDay)
        _hasReminderTime = State(initialValue: goal.reminderTime != nil)
        _reminderTime = State(initialValue: Self.parseTime(goal.reminderTime))
        _repeatUntilCompleted = State(initialValue: goal.repeatUntilCompleted)
        _nudgeIntervalMinutes = State(initialValue: goal.nudgeIntervalMinutes ?? 60)
        _important = State(initialValue: goal.important)
    }

    private var supportsAlarm: Bool { goal.period == "daily" || goal.period == "weekly" }

    var body: some View {
        NavigationStack {
            Form {
                if goal.period == "weekly" {
                    Section("Appears on") {
                        WeekdayPicker(selection: $selection)
                        Text(summary).font(.caption).foregroundStyle(selection.isEmpty ? Theme.negative : .secondary)
                    }
                    Section("Weekly cycle") {
                        Picker("Week starts", selection: $weekStartsOn) {
                            ForEach(WeekdaySchedule.ordered, id: \.self) { day in
                                Text(day.capitalized).tag(day)
                            }
                        }
                        Text(weekRangeSummary)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Section("Time") {
                    Toggle("Add a time", isOn: $hasReminderTime)
                    if hasReminderTime {
                        DatePicker("Reminder", selection: $reminderTime, displayedComponents: .hourAndMinute)
                        if supportsAlarm {
                            Toggle(isOn: $important) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Important")
                                    Text("Rings like an alarm — breaks through silent & Focus")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            if important, #unavailable(iOS 26.0) {
                                Text("On this iOS version, important routines use repeated alerts instead of a true alarm.")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        if !important {
                            Toggle("Keep nudging until done", isOn: $repeatUntilCompleted)
                            if repeatUntilCompleted {
                                Picker("Nudge every", selection: $nudgeIntervalMinutes) {
                                    Text("30 minutes").tag(30)
                                    Text("1 hour").tag(60)
                                    Text("2 hours").tag(120)
                                    Text("4 hours").tag(240)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle(goal.period == "weekly" ? "Weekly schedule" : "Routine schedule")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        saving = true
                        Task {
                            let days = WeekdaySchedule.ordered.filter(selection.contains)
                            await store.setRoutineSchedule(
                                goal,
                                days: days,
                                weekStartsOn: weekStartsOn,
                                reminderTime: hasReminderTime ? reminderTime.apiTime : nil,
                                repeatUntilCompleted: hasReminderTime && !important && repeatUntilCompleted,
                                nudgeIntervalMinutes: !important && repeatUntilCompleted ? nudgeIntervalMinutes : nil,
                                important: hasReminderTime && supportsAlarm && important
                            )
                            saving = false
                            dismiss()
                        }
                    }.disabled(saving)
                }
            }
        }
    }

    private var summary: String {
        let days = WeekdaySchedule.ordered.filter(selection.contains)
        return days.isEmpty ? "No scheduled days. This goal will still track weekly, but won’t appear on a specific day." : days.map(\.capitalized).joined(separator: ", ")
    }

    private var weekRangeSummary: String {
        let end = WeekdaySchedule.endDay(whenWeekStartsOn: weekStartsOn)
        return "Your week runs \(weekStartsOn.capitalized) through \(end.capitalized)."
    }

    private static func parseTime(_ value: String?) -> Date {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm"
        return value.flatMap(formatter.date(from:))
            ?? Calendar.current.date(bySettingHour: 9, minute: 0, second: 0, of: Date())
            ?? Date()
    }
}

/// Compact color chooser shown as a popover anchored to a widget's gauge in
/// focus mode. `nil` = Default (inherit / brand). Applies on tap.
struct ColorPickerPopover: View {
    let selected: String?
    let onPick: (String?) -> Void
    private let columns = Array(repeating: GridItem(.flexible(), spacing: 12), count: 5)

    var body: some View {
        LazyVGrid(columns: columns, spacing: 12) {
            cell(nil)
            ForEach(Customization.colorCatalog, id: \.self) { cell($0) }
        }
        .padding()
        .frame(minWidth: 240)
        .presentationCompactAdaptation(.popover)
    }

    @ViewBuilder private func cell(_ token: String?) -> some View {
        Button { onPick(token) } label: {
            Circle()
                .fill(token.map(Customization.color(for:)) ?? Color.secondary.opacity(0.25))
                .frame(width: 34, height: 34)
                .overlay { if token == nil { Image(systemName: "slash.circle").font(.caption) } }
                .overlay(Circle().strokeBorder(Theme.brand, lineWidth: token == selected ? 3 : 0))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(token ?? "Default color")
    }
}

/// Compact icon chooser shown as a popover anchored to a widget's icon in focus
/// mode. `nil` = Default (derive from kind / group). Applies on tap.
struct IconPickerPopover: View {
    let selected: String?
    let defaultIcon: String?
    let accent: Color
    let onPick: (String?) -> Void
    private let columns = Array(repeating: GridItem(.flexible(), spacing: 12), count: 6)

    var body: some View {
        ScrollView {
            LazyVGrid(columns: columns, spacing: 12) {
                cell(nil)
                ForEach(Customization.iconCatalog, id: \.self) { cell($0) }
            }
            .padding()
        }
        .frame(minWidth: 280, minHeight: 240)
        .presentationCompactAdaptation(.popover)
    }

    @ViewBuilder private func cell(_ token: String?) -> some View {
        Button { onPick(token) } label: {
            Image(systemName: iconSymbol(for: token))
                .font(.footnote.weight(.semibold))
                .foregroundStyle(token == nil ? Color.secondary : accent)
                .frame(width: 40, height: 40)
                .background((token == nil ? Color.secondary : accent).opacity(0.13),
                            in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(Theme.brand, lineWidth: token == selected ? 2 : 0))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(token ?? (defaultIcon == nil ? "No icon" : "Default icon"))
    }

    private func iconSymbol(for token: String?) -> String {
        if let token { return Customization.symbol(for: token) }
        if let defaultIcon { return Customization.symbol(for: defaultIcon) }
        return "slash.circle"
    }
}

enum GoalComposerMode: Equatable { case goal, routine }

struct AddGoalView: View {
    @EnvironmentObject private var store: MoneyStore
    @Environment(\.dismiss) private var dismiss
    let mode: GoalComposerMode
    @State private var name = ""
    @State private var kind = "financial"
    @State private var period: String
    @State private var target = ""
    @State private var current = ""
    @State private var direction = "reach"
    @State private var step = "1"
    @State private var group = ""
    @State private var category = ""
    @State private var weeklyDays: Set<String> = []
    @State private var hasReminderTime = false
    @State private var repeatUntilCompleted = false
    @State private var nudgeIntervalMinutes = 60
    @State private var reminderTime = Calendar.current.date(
        bySettingHour: 9, minute: 0, second: 0, of: Date()
    ) ?? Date()
    @State private var financialMetric = "account_balance"
    @State private var financialRule = "reach"
    @State private var financialSource = "accounts"
    @State private var selectedAccountIds: Set<Int> = []

    init(mode: GoalComposerMode = .goal, initialGroup: String? = nil, initialPeriod: String? = nil) {
        self.mode = mode
        let startsAsStreak = initialPeriod == "ongoing"
        _kind = State(initialValue: startsAsStreak ? "streak" : "financial")
        _period = State(initialValue: startsAsStreak ? "once" : (initialPeriod ?? (mode == .goal ? "once" : "daily")))
        _group = State(initialValue: initialGroup ?? "")
    }

    var body: some View {
        NavigationStack {
            Form {
                TextField("Goal name", text: $name)
                Picker("Kind", selection: $kind) {
                    Text("Financial").tag("financial")
                    Text("Numeric").tag("numeric")
                    if mode == .goal { Text("Streak").tag("streak") }
                }
                .onChange(of: kind) { selected in
                    if selected == "financial" { period = "once" }
                    else if selected == "streak" { period = "once" }
                    else if mode == .routine && period == "once" { period = "daily" }
                }
                if (mode == .routine || (kind == "financial" && financialUsesWindow)) && kind != "streak" {
                    Picker(kind == "financial" ? "Window" : "Cadence", selection: $period) {
                        Text("Daily").tag("daily"); Text("Weekly").tag("weekly")
                        Text("Monthly").tag("monthly")
                        if kind != "financial" { Text("Every N days").tag("interval") }
                    }
                }
                if mode == .routine && period == "weekly" && kind != "streak" {
                    Section("Appears on") {
                        WeekdayPicker(selection: $weeklyDays)
                        Text(weeklyDays.isEmpty ? "Choose the days this goal should appear." : WeekdaySchedule.ordered.filter(weeklyDays.contains).map(\.capitalized).joined(separator: ", "))
                            .font(.caption).foregroundStyle(weeklyDays.isEmpty ? Theme.negative : .secondary)
                    }
                }
                if mode == .routine && period != "once" && kind != "streak" {
                    Section("Time") {
                        Toggle("Add a time", isOn: $hasReminderTime)
                        if hasReminderTime {
                            DatePicker("Reminder", selection: $reminderTime, displayedComponents: .hourAndMinute)
                            Toggle("Keep nudging until done", isOn: $repeatUntilCompleted)
                            if repeatUntilCompleted {
                                Picker("Nudge every", selection: $nudgeIntervalMinutes) {
                                    Text("30 minutes").tag(30)
                                    Text("1 hour").tag(60)
                                    Text("2 hours").tag(120)
                                    Text("4 hours").tag(240)
                                }
                            }
                        }
                    }
                }
                if kind == "numeric" && !isWeeklyChecklistRoutine {
                    Picker("Direction", selection: $direction) {
                        Text("Reach target").tag("reach")
                        Text("Go under target").tag("under")
                    }
                }
                if kind == "financial" {
                    Section("Financial setup") {
                        Picker("Track with", selection: $financialSource) {
                            Text("Linked accounts").tag("accounts")
                            Text("Manual updates").tag("manual")
                        }
                        .onChange(of: financialSource) { _ in
                            financialMetric = "account_balance"
                            financialRule = "reach"
                            selectedAccountIds.removeAll()
                            period = "once"
                        }
                        if financialSource == "accounts" {
                            Picker("Metric", selection: $financialMetric) {
                                Text("Account balance").tag("account_balance")
                                Text("Debt balance").tag("debt_balance")
                                Text("Net worth").tag("net_worth")
                                Text("Income").tag("income")
                                Text("Cash flow").tag("cash_flow")
                            }
                            .onChange(of: financialMetric) { metric in
                                financialRule = metric == "debt_balance" ? "reduce_to" : "reach"
                                period = financialUsesWindow ? "monthly" : "once"
                            }
                        }
                        Picker("Rule", selection: $financialRule) {
                            Text("Reach at least").tag("reach")
                            Text("Stay under").tag("stay_under")
                            Text("Reduce to").tag("reduce_to")
                        }
                        if financialSource == "manual" {
                            TextField("Current amount", text: $current).keyboardType(.decimalPad)
                        } else {
                            ForEach(store.accounts) { account in
                                Toggle(isOn: accountSelection(account.id)) {
                                    VStack(alignment: .leading) {
                                        Text(account.name)
                                        Text(account.subtype ?? account.type).font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                            }
                            if accountsAreOptional {
                                Text("Leave every account off to use all accounts.")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                if !isWeeklyChecklistRoutine {
                    TextField("Target", text: $target).keyboardType(.decimalPad)
                }
                if (kind == "save" || kind == "numeric") && !isWeeklyChecklistRoutine {
                    TextField(direction == "under" && kind == "numeric" ? "Starting value (required)" : "Current value", text: $current)
                        .keyboardType(.decimalPad)
                }
                if direction == "under" && kind == "numeric" && !isWeeklyChecklistRoutine {
                    Text("The starting value is the anchor and must be higher than the target.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if !isWeeklyChecklistRoutine && (kind == "save" || kind == "numeric" || (kind == "financial" && financialSource == "manual")) {
                    TextField("Step", text: $step).keyboardType(.decimalPad)
                }
                TextField("Group (optional)", text: $group)
            }
            .navigationTitle(mode == .goal ? "New goal" : "New routine")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Create") {
                        Task {
                            let orderedDays = WeekdaySchedule.ordered.filter(weeklyDays.contains)
                            let spendingCategory = category.trimmingCharacters(in: .whitespacesAndNewlines).uppercased().replacingOccurrences(of: " ", with: "_")
                            await store.addGoal(
                                name: name,
                                kind: kind,
                                period: period,
                                direction: kind == "numeric" && !isWeeklyChecklistRoutine ? direction : "reach",
                                target: isWeeklyChecklistRoutine ? 1 : Double(target),
                                current: isWeeklyChecklistRoutine ? 0 : Double(current),
                                step: isWeeklyChecklistRoutine ? 1 : (Double(step) ?? 1),
                                group: group.isEmpty ? nil : group,
                                category: spendingCategory.isEmpty ? nil : spendingCategory,
                                weeklyDays: orderedDays,
                                reminderTime: hasReminderTime ? reminderTime.apiTime : nil,
                                repeatUntilCompleted: hasReminderTime && repeatUntilCompleted,
                                nudgeIntervalMinutes: repeatUntilCompleted ? nudgeIntervalMinutes : nil,
                                accountIds: selectedAccountIds.sorted(),
                                financialMetric: kind == "financial" ? financialMetric : nil,
                                financialRule: kind == "financial" ? financialRule : nil,
                                financialSource: kind == "financial" ? financialSource : nil
                            )
                            dismiss()
                        }
                    }.disabled(!canCreate)
                }
            }
        }
    }

    private var canCreate: Bool {
        guard !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
        if isWeeklyChecklistRoutine { return !weeklyDays.isEmpty }
        if kind == "financial" {
            if financialSource == "manual" {
                if financialRule == "reduce_to" {
                    guard let startingValue = Double(current), let targetValue = Double(target) else { return false }
                    return startingValue > targetValue
                }
            } else if !accountsAreOptional && selectedAccountIds.isEmpty {
                return false
            }
        }
        guard let targetValue = Double(target) else { return kind == "streak" }
        if kind == "numeric" && direction == "under" {
            guard let startingValue = Double(current) else { return false }
            return startingValue > targetValue
        }
        return true
    }

    private var isWeeklyChecklistRoutine: Bool {
        mode == .routine && kind == "numeric" && period == "weekly"
    }

    private var financialUsesWindow: Bool {
        financialSource == "accounts" && ["income", "cash_flow"].contains(financialMetric)
    }

    private var accountsAreOptional: Bool {
        ["net_worth", "income", "cash_flow"].contains(financialMetric)
    }

    private func accountSelection(_ id: Int) -> Binding<Bool> {
        Binding(
            get: { selectedAccountIds.contains(id) },
            set: { selected in
                if selected { selectedAccountIds.insert(id) }
                else { selectedAccountIds.remove(id) }
            }
        )
    }
}
