import SwiftUI
import Charts

struct GoalCategory: Identifiable {
    let id: String
    let name: String
    let icon: String
    let goals: [Goal]
    let showsCombinedChart: Bool

    var aggregate: Double? {
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
    for cadence in cadences where includeRoutines || cadence.key == "once" {
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
    var isRoutine: Bool { kind == "streak" || period != "once" }
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
}

struct GoalsView: View {
    @EnvironmentObject private var store: MoneyStore
    @State private var adding = false
    @State private var showingHistory = false

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
}

struct RoutinesView: View {
    @EnvironmentObject private var store: MoneyStore
    @State private var adding = false

    private var categories: [GoalCategory] { routineCategories(from: store.goals) }

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 14) {
                ForEach(categories) { category in GoalCategoryWidget(category: category) }
                if categories.isEmpty { EmptyWidget(text: "No routines yet") }
            }.padding()
        }
        .background(Theme.canvas)
        .navigationTitle("Routines")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if #available(iOS 26.0, *) {
                ToolbarItemGroup(placement: .navigationBarTrailing) { routinesToolbarButtons }
                    .sharedBackgroundVisibility(.hidden)
            } else {
                ToolbarItemGroup(placement: .navigationBarTrailing) { routinesToolbarButtons }
            }
        }
        .sheet(isPresented: $adding) { AddGoalView(mode: .routine) }
        .refreshable { await store.loadGoals() }
    }

    @ViewBuilder private var routinesToolbarButtons: some View {
        Button { adding = true } label: { Image(systemName: "plus") }
            .buttonStyle(.plain)
            .accessibilityLabel("Add routine")
    }
}

struct GoalCategoryWidget: View {
    @EnvironmentObject private var store: MoneyStore
    let category: GoalCategory
    @AppStorage private var expanded: Bool
    @AppStorage private var chartExpanded: Bool
    @State private var addingToGroup = false
    @State private var renamingGroup = false
    @State private var renameDraft = ""
    @State private var pickingIcon = false
    @State private var pickingColor = false
    @State private var nameDraft = ""

    init(category: GoalCategory) {
        self.category = category
        _expanded = AppStorage(wrappedValue: false, LocalUIStateKey.goalCategoryExpanded(category.id))
        _chartExpanded = AppStorage(wrappedValue: false, LocalUIStateKey.goalCategoryChartExpanded(category.id))
    }

    private var focused: Bool { store.isFocused(category.id) }
    /// Preserves the pre-focus-mode tint rule (custom color, else the ongoing-streak
    /// honey accent, else brand) so unfocused rendering stays identical to today.
    private var groupAccent: Color {
        category.customColor.map(Customization.color(for:))
            ?? (category.id.hasSuffix("section:ongoing") ? Theme.honey : Theme.brand)
    }

    var body: some View {
        Group {
            if expanded {
                categoryCard
            } else {
                SwipeActionRow(actionLabel: "End") { endGroup() } content: { categoryCard }
            }
        }
        .sheet(isPresented: $addingToGroup) {
            AddGoalView(
                mode: category.composerMode,
                initialGroup: category.groupName,
                initialPeriod: category.cadence
            )
        }
        .alert("Rename group", isPresented: $renamingGroup) {
            TextField("Group name", text: $renameDraft)
            Button("Cancel", role: .cancel) {}
            Button("Save") { renameGroup() }
                .disabled(renameDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        } message: {
            Text("Every goal in this card will move together under the new name.")
        }
    }

    private var categoryCard: some View {
        WidgetCard("") { categoryHeader; expandedContent }
            .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous)
                .strokeBorder(Theme.brand, lineWidth: focused ? 2 : 0))
            .onLongPressGesture(minimumDuration: 0.4) {
                nameDraft = category.groupName ?? category.name
                store.focus(category.id)
            }
            .contextMenu {
                Button { addingToGroup = true } label: {
                    Label(category.composerMode == .routine ? "Add routine here" : "Add goal here", systemImage: "plus")
                }
                Button { beginRename() } label: {
                    Label("Rename group", systemImage: "pencil")
                }
                Divider()
                Button(role: .destructive) { endGroup() } label: {
                    Label(category.composerMode == .routine ? "End routines" : "End goal group", systemImage: "flag.checkered")
                }
            }
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
                Button { withAnimation { expanded.toggle() } } label: { headerContent }
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
                        IconChip(symbol: category.customIcon.map(Customization.symbol(for:)) ?? category.icon,
                                 tint: groupAccent)
                    }
                    .buttonStyle(.plain)
                    .popover(isPresented: $pickingIcon) {
                        IconPickerPopover(selected: category.customIcon,
                                          defaultIcon: "tag", accent: groupAccent) { token in
                            pickingIcon = false
                            if let name = category.groupName {
                                Task { await store.setGroupAppearance(name, icon: token, color: category.customColor) }
                            }
                        }
                    }
                } else {
                    IconChip(symbol: category.customIcon.map(Customization.symbol(for:)) ?? category.icon,
                             tint: groupAccent)
                }
                if focused {
                    TextField("Group name", text: $nameDraft)
                        .font(.headline).textFieldStyle(.roundedBorder)
                        .onSubmit {
                            Task { _ = await store.renameGoalGroup(category.goals, to: nameDraft) }
                        }
                } else {
                    Text(category.name).font(.headline)
                }
                GoalCountBadge(count: category.goals.count)
                Spacer()
                if focused {
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
                if focused {
                    Button { pickingColor = true } label: {
                        GaugeBar(pct: aggregate, tint: groupAccent,
                                 over: category.hasGoalOverLimit, reverse: category.aggregateIsReversed)
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
                } else {
                    GaugeBar(pct: aggregate, tint: groupAccent,
                             over: category.hasGoalOverLimit, reverse: category.aggregateIsReversed)
                }
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

    private func beginRename() {
        renameDraft = category.groupName ?? category.name
        renamingGroup = true
    }

    private func renameGroup() {
        let cleanName = renameDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanName.isEmpty else { return }
        Task {
            if await store.renameGoalGroup(category.goals, to: cleanName) {
                let newId = category.groupWidgetId(named: cleanName)
                DashboardSettings.replaceWidget(category.id, with: newId)
                UserDefaults.standard.set(expanded, forKey: LocalUIStateKey.goalCategoryExpanded(newId))
                UserDefaults.standard.set(chartExpanded, forKey: LocalUIStateKey.goalCategoryChartExpanded(newId))
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

/// Reusable swipe action for editable, user-owned widgets and rows. Bank-backed
/// finance widgets intentionally remain read-only and do not adopt this component.
struct SwipeActionRow<Content: View>: View {
    let actionLabel: String
    let systemImage: String
    let cornerRadius: CGFloat
    let action: () -> Void
    @ViewBuilder let content: Content
    @State private var restingOffset: CGFloat = 0
    @GestureState private var dragOffset: CGFloat = 0

    private let actionWidth: CGFloat = 82
    private var offset: CGFloat {
        min(0, max(-actionWidth, restingOffset + dragOffset))
    }

    init(actionLabel: String, systemImage: String = "flag.checkered", cornerRadius: CGFloat = 20, action: @escaping () -> Void, @ViewBuilder content: () -> Content) {
        self.actionLabel = actionLabel
        self.systemImage = systemImage
        self.cornerRadius = cornerRadius
        self.action = action
        self.content = content()
    }

    var body: some View {
        ZStack(alignment: .trailing) {
            Button(role: .destructive) {
                withAnimation(.easeOut(duration: 0.2)) { restingOffset = 0 }
                action()
            } label: {
                VStack(spacing: 4) {
                    Image(systemName: systemImage)
                    Text(actionLabel).font(.caption.weight(.semibold))
                }
                .foregroundStyle(.white)
                .frame(width: actionWidth)
                .frame(maxHeight: .infinity)
                .background(Theme.negative)
            }
            .buttonStyle(.plain)

            content.offset(x: offset)
        }
        .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
        .simultaneousGesture(
            DragGesture(minimumDistance: 18)
                .updating($dragOffset) { value, state, _ in
                    guard abs(value.translation.width) > abs(value.translation.height) else { return }
                    state = value.translation.width
                }
                .onEnded { value in
                    guard abs(value.translation.width) > abs(value.translation.height) else { return }
                    let projected = restingOffset + value.predictedEndTranslation.width
                    withAnimation(.easeOut(duration: 0.2)) {
                        restingOffset = projected < -actionWidth / 2 ? -actionWidth : 0
                    }
                }
        )
        .accessibilityAction(named: Text(actionLabel)) { action() }
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
                ForEach(goal.history) { point in
                    LineMark(x: .value("Date", String(point.at.prefix(10)).monthSlashDay), y: .value("Value", normalized(point.value, goal: goal)))
                        .foregroundStyle(by: .value("Goal", goal.name)).lineStyle(.init(lineWidth: 2))
                }
            }
        }
        .chartForegroundStyleScale(range: Theme.chartScale)
        .chartLegend(position: .bottom, spacing: 6)
        .frame(height: 180)
    }

    private func normalized(_ value: Double, goal: Goal) -> Double {
        mixedUnits && (goal.target ?? 0) != 0 ? value / (goal.target ?? 1) * 100 : value
    }
}

/// One slim row per goal: name, value, thin gauge. Single tap opens the detail
/// sheet; on manual goals, double-tap the left half to subtract a step and the
/// right half to add one.
struct GoalRow: View {
    @EnvironmentObject private var store: MoneyStore
    let goal: Goal
    @State private var showingDetail = false

    var body: some View {
        SwipeActionRow(actionLabel: "End", cornerRadius: 0) {
            Task { await store.endGoal(goal.id) }
        } content: {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 8) {
                        Text(goal.name).font(.subheadline.weight(.medium)).lineLimit(1)
                        Spacer(minLength: 8)
                        Text(valueLabel).font(.subheadline.monospacedDigit()).foregroundStyle(.secondary).fitOneLine()
                    }
                    if goal.period == "weekly" {
                        Label(goal.weeklyScheduleLabel.isEmpty ? "No days selected" : goal.weeklyScheduleLabel, systemImage: "calendar")
                            .font(.caption).foregroundStyle(goal.weeklyScheduleLabel.isEmpty ? Theme.negative : .secondary)
                    }
                    if let pct = store.displayedPct(goal) {
                        GaugeBar(pct: pct, tint: Customization.color(for: goal.resolvedColor),
                                 over: goal.status == "over", height: 6, reverse: goal.direction == "under")
                    }
                }
                .contentShape(Rectangle())
                .overlay {
                    // Only manual goals register double-taps; keeping single-tap off this
                    // surface is what makes both gestures fire without delay.
                    if goal.isManual {
                        HStack(spacing: 0) {
                            Color.clear.contentShape(Rectangle()).onTapGesture(count: 2) { decrement() }
                            Color.clear.contentShape(Rectangle()).onTapGesture(count: 2) { increment() }
                        }
                    } else {
                        Color.clear.contentShape(Rectangle()).onTapGesture { showingDetail = true }
                    }
                }
                Button { showingDetail = true } label: {
                    Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
                        .frame(width: 26, height: 34).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Details for \(goal.name)")
            }
            .padding(.vertical, 4)
            .background(Theme.card)
            .contextMenu {
                Button { showingDetail = true } label: {
                    Label("Edit goal", systemImage: "pencil")
                }
                Button(role: .destructive) {
                    Task { await store.endGoal(goal.id) }
                } label: {
                    Label("End goal", systemImage: "flag.checkered")
                }
            }
        }
        .sheet(isPresented: $showingDetail) {
            GoalDetailView(goalId: goal.id).environmentObject(store).tint(Theme.brand).dynamicTypeSize(.small)
        }
        .accessibilityElement(children: .combine)
        .accessibilityHint(goal.isManual ? "Double-tap left to subtract \(goal.format(goal.step)), right to add it. Use the details button for more." : "Tap for details.")
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
/// and target editing, history, and milestones. Ending lives on the swipe action.
struct GoalDetailView: View {
    @EnvironmentObject private var store: MoneyStore
    let goalId: Int
    @State private var editingValue = false
    @State private var valueDraft = ""
    @State private var editingStep = false
    @State private var stepDraft = ""
    @State private var editingWeeklySchedule = false
    @State private var confirmingStreakReset = false
    @State private var editingTarget = false
    @State private var targetDraft = ""
    @State private var customizing = false

    private var goal: Goal? { store.goals.first { $0.id == goalId } }

    var body: some View {
        if let goal {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 10) {
                        IconChip(symbol: Customization.symbol(for: goal.resolvedIcon), tint: Customization.color(for: goal.resolvedColor))
                        Text(goal.name).font(.title3.weight(.bold))
                        Spacer()
                    }
                    Button { customizing = true } label: {
                        Label("Customize appearance", systemImage: "paintpalette")
                    }.buttonStyle(.bordered).controlSize(.small)
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
                    if goal.isManual { editor(goal) }
                    if let pct = store.displayedPct(goal) {
                        GaugeBar(pct: pct, over: goal.status == "over", reverse: goal.direction == "under")
                    }
                    metadata(goal)
                    if goal.period == "weekly" {
                        Button { editingWeeklySchedule = true } label: {
                            Label("Edit scheduled days", systemImage: "calendar.badge.clock")
                        }.buttonStyle(.bordered).controlSize(.small)
                    }
                    if !goal.history.isEmpty || !goal.milestones.isEmpty {
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
                .padding(20)
            }
            .background(Theme.canvas)
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
            .sheet(isPresented: $editingWeeklySchedule) {
                WeeklyScheduleEditor(goal: goal).environmentObject(store).tint(Theme.brand)
            }
            .sheet(isPresented: $customizing) {
                IconColorPicker(title: "Goal appearance",
                                defaultIcon: goal.resolvedIcon,
                                icon: goal.icon, color: goal.color) { icon, color in
                    Task { await store.setGoalAppearance(goal, icon: icon, color: color) }
                }.tint(Theme.brand)
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

    private var visibleHistory: [HistoryPoint] {
        let grouped = Dictionary(grouping: goal.history) { String($0.at.prefix(10)) }
        let daily = grouped.compactMap { day, points in
            points.sorted { $0.at < $1.at }.last.map { HistoryPoint(value: $0.value, at: day) }
        }.sorted { $0.at < $1.at }
        guard let days = selection.wrappedValue.days,
              let cutoff = Calendar.current.date(byAdding: .day, value: -days, to: Date()) else {
            return daily
        }
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        let cutoffKey = formatter.string(from: cutoff)
        return daily.filter { $0.at >= cutoffKey }
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
                            x: .value("Date", point.at.monthSlashDay),
                            y: .value("Value", point.value)
                        )
                        .foregroundStyle(Theme.brand)
                        .lineStyle(.init(lineWidth: 2))
                        PointMark(
                            x: .value("Date", point.at.monthSlashDay),
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
        WidgetCard("") {
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
                    Chart(goal.history) { point in
                        LineMark(
                            x: .value("Date", point.at.monthSlashDay),
                            y: .value("Value", point.value)
                        )
                        .foregroundStyle(Theme.brand)
                        PointMark(
                            x: .value("Date", point.at.monthSlashDay),
                            y: .value("Value", point.value)
                        )
                        .foregroundStyle(Theme.brand)
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

struct WeeklyScheduleEditor: View {
    @EnvironmentObject private var store: MoneyStore
    @Environment(\.dismiss) private var dismiss
    let goal: Goal
    @State private var selection: Set<String>
    @State private var saving = false

    init(goal: Goal) {
        self.goal = goal
        _selection = State(initialValue: Set(goal.scheduledWeekdays))
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Appears on") {
                    WeekdayPicker(selection: $selection)
                    Text(summary).font(.caption).foregroundStyle(selection.isEmpty ? Theme.negative : .secondary)
                }
            }
            .navigationTitle("Weekly schedule")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        saving = true
                        Task {
                            let days = WeekdaySchedule.ordered.filter(selection.contains)
                            await store.setGoalWeeklyDays(goal, days: days)
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
    let defaultIcon: String
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
            Image(systemName: token.map(Customization.symbol(for:)) ?? Customization.symbol(for: defaultIcon))
                .font(.footnote.weight(.semibold))
                .foregroundStyle(token == nil ? Color.secondary : accent)
                .frame(width: 40, height: 40)
                .background((token == nil ? Color.secondary : accent).opacity(0.13),
                            in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(Theme.brand, lineWidth: token == selected ? 2 : 0))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(token ?? "Default icon")
    }
}

/// Reusable appearance editor for a goal or a group. `nil` icon/color means
/// "use the default / inherit"; the grids include an explicit Default swatch.
struct IconColorPicker: View {
    let title: String
    let defaultIcon: String
    @State var icon: String?
    @State var color: String?
    let onSave: (_ icon: String?, _ color: String?) -> Void
    @Environment(\.dismiss) private var dismiss

    private let columns = Array(repeating: GridItem(.flexible(), spacing: 12), count: 6)

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("Color").font(.subheadline.weight(.semibold))
                    LazyVGrid(columns: columns, spacing: 12) {
                        swatch(nil)
                        ForEach(Customization.colorCatalog, id: \.self) { swatch($0) }
                    }
                    Text("Icon").font(.subheadline.weight(.semibold))
                    LazyVGrid(columns: columns, spacing: 12) {
                        iconCell(nil)
                        ForEach(Customization.iconCatalog, id: \.self) { iconCell($0) }
                    }
                }
                .padding()
            }
            .background(Theme.canvas)
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { onSave(icon, color); dismiss() }
                }
            }
        }
    }

    private var accent: Color { color.map(Customization.color(for:)) ?? Theme.brand }

    @ViewBuilder private func swatch(_ token: String?) -> some View {
        let selected = token == color
        Button { color = token } label: {
            Circle()
                .fill(token.map(Customization.color(for:)) ?? Color.secondary.opacity(0.25))
                .frame(width: 34, height: 34)
                .overlay { if token == nil { Image(systemName: "slash.circle").font(.caption) } }
                .overlay(Circle().strokeBorder(Theme.brand, lineWidth: selected ? 3 : 0))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(token ?? "Default color")
    }

    @ViewBuilder private func iconCell(_ token: String?) -> some View {
        let selected = token == icon
        Button { icon = token } label: {
            Image(systemName: token.map(Customization.symbol(for:)) ?? Customization.symbol(for: defaultIcon))
                .font(.footnote.weight(.semibold))
                .foregroundStyle(token == nil ? Color.secondary : accent)
                .frame(width: 40, height: 40)
                .background((token == nil ? Color.secondary : accent).opacity(0.13),
                            in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(Theme.brand, lineWidth: selected ? 2 : 0))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(token ?? "Default icon")
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
                    if mode == .routine { Text("Streak").tag("streak") }
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
                if kind == "numeric" {
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
                TextField("Target", text: $target).keyboardType(.decimalPad)
                if kind == "save" || kind == "numeric" {
                    TextField(direction == "under" && kind == "numeric" ? "Starting value (required)" : "Current value", text: $current)
                        .keyboardType(.decimalPad)
                }
                if direction == "under" && kind == "numeric" {
                    Text("The starting value is the anchor and must be higher than the target.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if kind == "save" || kind == "numeric" || (kind == "financial" && financialSource == "manual") {
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
                            await store.addGoal(name: name, kind: kind, period: period, direction: kind == "numeric" ? direction : "reach", target: Double(target), current: Double(current), step: Double(step) ?? 1, group: group.isEmpty ? nil : group, category: spendingCategory.isEmpty ? nil : spendingCategory, weeklyDays: orderedDays, accountIds: selectedAccountIds.sorted(), financialMetric: kind == "financial" ? financialMetric : nil, financialRule: kind == "financial" ? financialRule : nil, financialSource: kind == "financial" ? financialSource : nil)
                            dismiss()
                        }
                    }.disabled(!canCreate)
                }
            }
        }
    }

    private var canCreate: Bool {
        guard !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
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
