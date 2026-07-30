import SwiftUI

enum ScheduleCalendar {
    static let calendar = Calendar.current

    static func monthStart(_ date: Date) -> Date {
        let parts = calendar.dateComponents([.year, .month], from: date)
        return calendar.date(from: parts) ?? date
    }

    static func monthGrid(_ month: Date) -> [Date?] {
        let start = monthStart(month)
        guard let days = calendar.range(of: .day, in: .month, for: start) else { return [] }
        let weekday = calendar.component(.weekday, from: start)
        let leading = (weekday - calendar.firstWeekday + 7) % 7
        var result = Array<Date?>(repeating: nil, count: leading)
        result += days.compactMap { day in
            calendar.date(byAdding: .day, value: day - 1, to: start)
        }.map(Optional.some)
        while result.count % 7 != 0 { result.append(nil) }
        return result
    }

    static func loadingRange(_ month: Date) -> (start: String, end: String) {
        let dates = monthGrid(month).compactMap { $0 }
        return ((dates.first ?? month).apiDate, (dates.last ?? month).apiDate)
    }

    static var weekdaySymbols: [String] {
        let symbols = calendar.veryShortStandaloneWeekdaySymbols
        let offset = max(calendar.firstWeekday - 1, 0)
        return Array(symbols[offset...] + symbols[..<offset])
    }

    static func weekDates(containing date: Date) -> [Date] {
        let start = calendar.dateInterval(of: .weekOfYear, for: date)?.start ?? date
        return (0..<7).compactMap { calendar.date(byAdding: .day, value: $0, to: start) }
    }

    static func date(fromAPI value: String, fallback: Date = Date()) -> Date {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.date(from: value) ?? fallback
    }

    static func time(fromAPI value: String?, fallback: Date = Date()) -> Date {
        guard let value else { return fallback }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm"
        return formatter.date(from: value) ?? fallback
    }
}

private enum ScheduleSection: String, CaseIterable, Identifiable {
    case routines = "Routines"
    case calendar = "Calendar"
    var id: String { rawValue }
}

private struct ScheduleDaySelection: Identifiable {
    let date: Date
    var id: String { date.apiDate }
}

struct ScheduleView: View {
    @EnvironmentObject private var store: MoneyStore
    @State private var selectedDate = Date()
    @State private var visibleMonth = ScheduleCalendar.monthStart(Date())
    @State private var section = ScheduleSection.routines
    @State private var addingReminder = false
    @State private var addingEvent = false
    @State private var addingRoutine = false

    private var categories: [GoalCategory] { routineCategories(from: store.goals) }
    private var range: (start: String, end: String) { ScheduleCalendar.loadingRange(visibleMonth) }
    private var loadKey: String { "\(section.rawValue)-\(visibleMonth.apiDate)" }

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 14) {
                Picker("Schedule view", selection: $section) {
                    ForEach(ScheduleSection.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)

                switch section {
                case .routines:
                    ScheduleAgendaWidget(date: Date(), items: store.scheduleItems)
                    ForEach(categories) { category in GoalCategoryWidget(category: category) }
                    if categories.isEmpty { EmptyWidget(text: "No routines yet") }
                case .calendar:
                    ScheduleCalendarWidget(
                        month: $visibleMonth,
                        selectedDate: $selectedDate,
                        items: store.scheduleItems
                    ) { date in
                        selectedDate = date
                    }
                    ScheduleAgendaWidget(date: selectedDate, items: store.scheduleItems)
                }
            }
            .padding()
        }
        .background(Theme.canvas)
        .navigationTitle("Schedule")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Menu {
                    Button { addingEvent = true } label: {
                        Label("New event", systemImage: "calendar.badge.plus")
                    }
                    Button { addingReminder = true } label: {
                        Label("New reminder", systemImage: "bell.badge")
                    }
                    Button { addingRoutine = true } label: {
                        Label("New routine", systemImage: "repeat")
                    }
                } label: {
                    Image(systemName: "plus")
                }
                .accessibilityLabel("Add to schedule")
            }
        }
        .sheet(isPresented: $addingReminder) {
            AddReminderView(initialDate: selectedDate) {
                await loadVisibleMonth()
            }
        }
        .sheet(isPresented: $addingEvent) {
            AddEventView(initialDate: selectedDate) {
                await loadVisibleMonth()
            }
        }
        .sheet(isPresented: $addingRoutine) { AddGoalView(mode: .routine) }
        .task(id: loadKey) { await loadActiveRange() }
        .refreshable {
            await store.loadGoals()
            await store.loadTodayRoutineTasks(force: true)
            await loadActiveRange()
        }
    }

    private func loadVisibleMonth() async {
        await store.loadSchedule(from: range.start, through: range.end)
    }

    private func loadActiveRange() async {
        if section == .calendar {
            await loadVisibleMonth()
        } else {
            await store.loadSchedule(
                from: Date().apiDate,
                through: Date().apiDate,
                requestNotificationPermission: true
            )
            await store.loadTodayRoutineTasks()
        }
    }
}

/// Widget-ready month selector that marks reminders, routines, and goal deadlines.
struct ScheduleCalendarWidget: View {
    @Binding var month: Date
    @Binding var selectedDate: Date
    let items: [ScheduleItem]
    var onSelect: ((Date) -> Void)? = nil

    private let columns = Array(repeating: GridItem(.flexible(), spacing: 4), count: 7)
    private var dates: [Date?] { ScheduleCalendar.monthGrid(month) }

    var body: some View {
        WidgetCard("") {
            HStack {
                Button { moveMonth(-1) } label: { Image(systemName: "chevron.left") }
                    .buttonStyle(.plain).accessibilityLabel("Previous month")
                Spacer()
                Text(month.formatted(.dateTime.month(.wide).year()))
                    .font(.headline)
                Spacer()
                Button { moveMonth(1) } label: { Image(systemName: "chevron.right") }
                    .buttonStyle(.plain).accessibilityLabel("Next month")
            }
            .foregroundStyle(Theme.brand)

            LazyVGrid(columns: columns, spacing: 7) {
                ForEach(Array(ScheduleCalendar.weekdaySymbols.enumerated()), id: \.offset) { _, symbol in
                    Text(symbol).font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
                }
                ForEach(Array(dates.enumerated()), id: \.offset) { _, date in
                    if let date { dayCell(date) } else { Color.clear.frame(height: 39) }
                }
            }
        }
    }

    private func dayCell(_ date: Date) -> some View {
        let selected = Calendar.current.isDate(date, inSameDayAs: selectedDate)
        let today = Calendar.current.isDateInToday(date)
        let sources = Set(items.filter { $0.scheduledFor == date.apiDate }.map(\.source))
        return Button {
            selectedDate = date
            onSelect?(date)
        } label: {
            VStack(spacing: 3) {
                Text("\(Calendar.current.component(.day, from: date))")
                    .font(.caption.weight(selected ? .bold : .regular))
                    .foregroundStyle(selected ? Theme.onBrand : Color.primary)
                    .frame(width: 28, height: 26)
                    .background(selected ? Theme.brand : Color.clear, in: Circle())
                    .overlay(Circle().stroke(today && !selected ? Theme.brand : .clear, lineWidth: 1))
                HStack(spacing: 2) {
                    ForEach(Array(sources.sorted().prefix(3)), id: \.self) { source in
                        Circle().fill(color(for: source)).frame(width: 4, height: 4)
                    }
                }
                .frame(height: 4)
            }
            .frame(maxWidth: .infinity, minHeight: 39)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(date.formatted(date: .complete, time: .omitted))
        .accessibilityValue(sources.isEmpty ? "No scheduled items" : "\(sources.count) schedule types")
    }

    private func color(for source: String) -> Color {
        switch source {
        case "event": return .blue
        case "reminder": return Theme.honey
        case "goal_deadline": return Theme.negative
        default: return Theme.brand
        }
    }

    private func moveMonth(_ amount: Int) {
        guard let next = Calendar.current.date(byAdding: .month, value: amount, to: month) else { return }
        month = ScheduleCalendar.monthStart(next)
        selectedDate = month
    }
}

/// Widget-ready agenda for the selected calendar day.
struct ScheduleAgendaWidget: View {
    @EnvironmentObject private var store: MoneyStore
    let date: Date
    let items: [ScheduleItem]
    @State private var editingItem: ScheduleItem?
    @State private var editingGoal: GoalEditorSelection?

    private var dayItems: [ScheduleItem] {
        items.filter { $0.scheduledFor == date.apiDate }
    }

    var body: some View {
        WidgetCard(Calendar.current.isDateInToday(date) ? "Today" : date.formatted(.dateTime.weekday(.wide).month(.abbreviated).day())) {
            if dayItems.isEmpty {
                Label("Nothing scheduled", systemImage: "calendar.badge.checkmark")
                    .font(.subheadline).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                ForEach(dayItems) { item in
                    interactiveRow(item)
                    if item.id != dayItems.last?.id { Divider() }
                }
            }
        }
        .sheet(item: $editingItem) { item in
            if item.source == "event" {
                AddEventView(editing: item) {}
            } else {
                AddReminderView(editing: item) {}
            }
        }
        .sheet(item: $editingGoal) { selection in
            GoalDetailView(goalId: selection.id)
                .environmentObject(store)
                .tint(Theme.brand)
                .dynamicTypeSize(.small)
        }
    }

    @ViewBuilder private func interactiveRow(_ item: ScheduleItem) -> some View {
        if item.source == "reminder" || item.source == "event" || item.source == "routine" {
            agendaRow(item)
                .pressAndHoldToEdit {
                    if item.source == "routine" {
                        editingGoal = GoalEditorSelection(id: item.sourceId)
                    } else {
                        editingItem = item
                    }
                }
        } else {
            agendaRow(item)
        }
    }

    private func agendaRow(_ item: ScheduleItem) -> some View {
        HStack(spacing: 11) {
            Button {
                Task { await store.toggleScheduleItem(item) }
            } label: {
                Image(systemName: symbol(for: item))
                    .font(.title3)
                    .foregroundStyle(color(for: item))
                    .frame(width: 24)
            }
            .buttonStyle(.plain)
            .disabled(
                item.source == "event"
                    || item.source == "goal_deadline"
                    || item.scheduledFor > Date().apiDate
            )

            VStack(alignment: .leading, spacing: 3) {
                Text(item.title)
                    .font(.subheadline.weight(.medium)).foregroundStyle(.primary)
                    .strikethrough(item.completed)
                if item.source != "reminder" {
                    HStack(spacing: 5) {
                        Text(sourceLabel(item))
                        if let notes = item.notes, item.source == "event" {
                            Text("· \(notes)").lineLimit(1)
                        }
                    }
                    .font(.caption).foregroundStyle(item.missed ? Theme.negative : Color.secondary)
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 5) {
                if let time = item.reminderTime {
                    Text(timeLabel(item, start: time))
                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
                if (item.source == "reminder" || item.source == "routine"),
                   item.repeatUntilCompleted, !item.completed {
                    Menu {
                        Menu {
                            ForEach([15, 30, 60, 120, 240], id: \.self) { minutes in
                                Button(snoozeLabel(minutes)) {
                                    Task { await store.snoozeReminder(item, minutes: minutes) }
                                }
                            }
                        } label: {
                            Label("Snooze", systemImage: "clock.arrow.circlepath")
                        }
                        Button(role: item.source == "reminder" ? .destructive : nil) {
                            Task { await store.toggleScheduleItem(item) }
                        } label: {
                            Label(
                                item.source == "reminder" ? "Stop reminders" : "Mark done",
                                systemImage: item.source == "reminder" ? "bell.slash" : "checkmark"
                            )
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                            .font(.title3)
                            .foregroundStyle(Theme.brand)
                    }
                    .accessibilityLabel("Persistent notification options")
                }
            }
        }
    }

    private func symbol(for item: ScheduleItem) -> String {
        if item.source == "event" { return "calendar" }
        if item.source == "goal_deadline" { return item.completed ? "flag.checkered.circle.fill" : "flag.checkered" }
        return item.completed ? "checkmark.circle.fill" : "circle"
    }

    private func color(for item: ScheduleItem) -> Color {
        if item.missed { return Theme.negative }
        if item.source == "event" { return .blue }
        if item.source == "reminder" { return item.completed ? Theme.brand : Theme.honey }
        if item.source == "goal_deadline" { return Theme.negative }
        return item.completed ? Theme.brand : Color.secondary
    }

    private func sourceLabel(_ item: ScheduleItem) -> String {
        if item.missed { return "Missed · \(baseSourceLabel(item))" }
        return baseSourceLabel(item)
    }

    private func baseSourceLabel(_ item: ScheduleItem) -> String {
        switch item.source {
        case "event":
            return item.location.map { "Event · \($0)" } ?? "Event"
        case "reminder":
            if item.repeatUntilCompleted {
                return "Persistent reminder · every \(item.nudgeIntervalMinutes ?? 60) min"
            }
            return "Reminder"
        case "goal_deadline": return item.completed ? "Goal completed" : "Goal deadline"
        default:
            let cadence = "\((item.period ?? "Routine").pretty) routine"
            if item.repeatUntilCompleted {
                return "\(cadence) · every \(item.nudgeIntervalMinutes ?? 60) min until done"
            }
            return cadence
        }
    }

    private func timeLabel(_ item: ScheduleItem, start: String) -> String {
        guard let end = item.endTime else { return start.localizedTime }
        return "\(start.localizedTime)–\(end.localizedTime)"
    }

    private func snoozeLabel(_ minutes: Int) -> String {
        if minutes < 60 { return "\(minutes) minutes" }
        let hours = minutes / 60
        return hours == 1 ? "1 hour" : "\(hours) hours"
    }
}

/// Reusable selected-day surface shared by the Schedule calendar and dashboard
/// calendar widget. Creation stays attached to the date the user tapped.
struct ScheduleDayDetailView: View {
    @EnvironmentObject private var store: MoneyStore
    @Environment(\.dismiss) private var dismiss
    let date: Date
    @State private var addingEvent = false
    @State private var addingReminder = false

    var body: some View {
        NavigationStack {
            ScrollView {
                ScheduleAgendaWidget(date: date, items: store.scheduleItems)
                    .padding()
            }
            .background(Theme.canvas)
            .navigationTitle(date.formatted(.dateTime.weekday(.wide).month(.wide).day()))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Menu {
                        Button { addingEvent = true } label: {
                            Label("New event", systemImage: "calendar.badge.plus")
                        }
                        Button { addingReminder = true } label: {
                            Label("New reminder", systemImage: "bell.badge")
                        }
                    } label: {
                        Image(systemName: "plus")
                    }
                    .accessibilityLabel("Add to this day")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .sheet(isPresented: $addingEvent) {
            AddEventView(initialDate: date) { await reloadDay() }
        }
        .sheet(isPresented: $addingReminder) {
            AddReminderView(initialDate: date) { await reloadDay() }
        }
    }

    private func reloadDay() async {
        await store.loadSchedule(from: date.apiDate, through: date.apiDate)
    }
}

struct AddEventView: View {
    @EnvironmentObject private var store: MoneyStore
    @Environment(\.dismiss) private var dismiss
    let onSaved: () async -> Void
    let editingItem: ScheduleItem?
    @State private var title = ""
    @State private var scheduledDate: Date
    @State private var includesTime = false
    @State private var startTime = Date()
    @State private var includesEndTime = false
    @State private var endTime = Date().addingTimeInterval(3600)
    @State private var location = ""
    @State private var notes = ""
    @State private var saving = false
    @State private var confirmingDelete = false

    init(initialDate: Date, onSaved: @escaping () async -> Void) {
        self.onSaved = onSaved
        editingItem = nil
        _scheduledDate = State(initialValue: initialDate)
    }

    init(editing item: ScheduleItem, onSaved: @escaping () async -> Void) {
        editingItem = item
        self.onSaved = onSaved
        _title = State(initialValue: item.title)
        _scheduledDate = State(initialValue: ScheduleCalendar.date(fromAPI: item.scheduledFor))
        _includesTime = State(initialValue: item.reminderTime != nil)
        _startTime = State(initialValue: ScheduleCalendar.time(fromAPI: item.reminderTime))
        _includesEndTime = State(initialValue: item.endTime != nil)
        _endTime = State(initialValue: ScheduleCalendar.time(
            fromAPI: item.endTime,
            fallback: ScheduleCalendar.time(fromAPI: item.reminderTime).addingTimeInterval(3600)
        ))
        _location = State(initialValue: item.location ?? "")
        _notes = State(initialValue: item.notes ?? "")
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Event") {
                    TextField("Event name", text: $title)
                    DatePicker("Date", selection: $scheduledDate, displayedComponents: .date)
                    Toggle("Add a time", isOn: $includesTime)
                    if includesTime {
                        DatePicker("Starts", selection: $startTime, displayedComponents: .hourAndMinute)
                        Toggle("Add an end time", isOn: $includesEndTime)
                        if includesEndTime {
                            DatePicker(
                                "Ends",
                                selection: $endTime,
                                in: startTime.addingTimeInterval(60)...,
                                displayedComponents: .hourAndMinute
                            )
                        }
                    }
                    TextField("Location (optional)", text: $location)
                }
                Section("Notes") {
                    TextField("Optional details", text: $notes, axis: .vertical)
                        .lineLimit(2...5)
                }
                if let editingItem {
                    Section {
                        Button("Delete event", role: .destructive) { confirmingDelete = true }
                            .frame(maxWidth: .infinity)
                    }
                    .confirmationDialog(
                        "Delete this event?",
                        isPresented: $confirmingDelete,
                        titleVisibility: .visible
                    ) {
                        Button("Delete event", role: .destructive) {
                            Task {
                                await store.deleteEvent(editingItem)
                                dismiss()
                            }
                        }
                        Button("Cancel", role: .cancel) {}
                    }
                }
            }
            .navigationTitle(editingItem == nil ? "New event" : "Edit event")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(editingItem == nil ? "Add" : "Save") { save() }
                        .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || saving)
                }
            }
        }
    }

    private func save() {
        saving = true
        Task {
            let cleanLocation = location.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
            let cleanNotes = notes.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
            let saved: CalendarEvent?
            if let editingItem {
                saved = await store.updateEvent(
                    editingItem,
                    title: title,
                    date: scheduledDate.apiDate,
                    startTime: includesTime ? startTime.apiTime : nil,
                    endTime: includesTime && includesEndTime ? endTime.apiTime : nil,
                    location: cleanLocation,
                    notes: cleanNotes
                )
            } else {
                saved = await store.createEvent(
                    title: title,
                    date: scheduledDate.apiDate,
                    startTime: includesTime ? startTime.apiTime : nil,
                    endTime: includesTime && includesEndTime ? endTime.apiTime : nil,
                    location: cleanLocation,
                    notes: cleanNotes
                )
            }
            saving = false
            if saved != nil {
                await onSaved()
                dismiss()
            }
        }
    }
}

struct AddReminderView: View {
    @EnvironmentObject private var store: MoneyStore
    @Environment(\.dismiss) private var dismiss
    let onSaved: () async -> Void
    let editingItem: ScheduleItem?
    @State private var title = ""
    @State private var scheduledDate: Date
    @State private var includesTime = false
    @State private var reminderTime = Date()
    @State private var notes = ""
    @State private var repeatUntilCompleted = false
    @State private var nudgeIntervalMinutes = 60
    @State private var important = false
    @State private var saving = false
    @State private var confirmingDelete = false

    init(initialDate: Date, onSaved: @escaping () async -> Void) {
        self.onSaved = onSaved
        editingItem = nil
        _scheduledDate = State(initialValue: initialDate)
    }

    init(editing item: ScheduleItem, onSaved: @escaping () async -> Void) {
        editingItem = item
        self.onSaved = onSaved
        _title = State(initialValue: item.title)
        _scheduledDate = State(initialValue: ScheduleCalendar.date(fromAPI: item.scheduledFor))
        _includesTime = State(initialValue: item.reminderTime != nil)
        _reminderTime = State(initialValue: ScheduleCalendar.time(fromAPI: item.reminderTime))
        _notes = State(initialValue: item.notes ?? "")
        _repeatUntilCompleted = State(initialValue: item.repeatUntilCompleted)
        _nudgeIntervalMinutes = State(initialValue: item.nudgeIntervalMinutes ?? 60)
        _important = State(initialValue: item.important)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Reminder") {
                    TextField("What do you need to remember?", text: $title)
                    DatePicker("Date", selection: $scheduledDate, displayedComponents: .date)
                    Toggle("Add a time", isOn: $includesTime)
                    if includesTime {
                        DatePicker("Time", selection: $reminderTime, displayedComponents: .hourAndMinute)
                        Toggle(isOn: $important) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Important")
                                Text("Rings like an alarm — breaks through silent & Focus")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        if important, #unavailable(iOS 26.0) {
                            Text("On this iOS version, important reminders use repeated alerts instead of a true alarm.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        if !important {
                            Toggle("Keep reminding me until I stop it", isOn: $repeatUntilCompleted)
                            if repeatUntilCompleted {
                                Picker("Nudge me", selection: $nudgeIntervalMinutes) {
                                    Text("Every 30 minutes").tag(30)
                                    Text("Every hour").tag(60)
                                    Text("Every 2 hours").tag(120)
                                    Text("Every 4 hours").tag(240)
                                }
                            }
                        }
                    }
                }
                Section("Notes") {
                    TextField("Optional details", text: $notes, axis: .vertical).lineLimit(2...5)
                }
                if let editingItem {
                    Section {
                        Button("Delete reminder", role: .destructive) { confirmingDelete = true }
                            .frame(maxWidth: .infinity)
                    }
                    .confirmationDialog(
                        "Delete this reminder?",
                        isPresented: $confirmingDelete,
                        titleVisibility: .visible
                    ) {
                        Button("Delete reminder", role: .destructive) {
                            Task {
                                await store.deleteReminder(editingItem)
                                dismiss()
                            }
                        }
                        Button("Cancel", role: .cancel) {}
                    }
                }
            }
            .navigationTitle(editingItem == nil ? "New reminder" : "Edit reminder")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button(editingItem == nil ? "Add" : "Save") { save() }
                        .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || saving)
                }
            }
        }
    }

    private func save() {
        saving = true
        Task {
            let cleanNotes = notes.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
            let saved: Reminder?
            if let editingItem {
                saved = await store.updateReminder(
                    editingItem,
                    title: title,
                    date: scheduledDate.apiDate,
                    time: includesTime ? reminderTime.apiTime : nil,
                    notes: cleanNotes,
                    repeatUntilCompleted: includesTime && !important && repeatUntilCompleted,
                    nudgeIntervalMinutes: includesTime && !important && repeatUntilCompleted ? nudgeIntervalMinutes : nil,
                    important: includesTime && important
                )
            } else {
                saved = await store.createReminder(
                    title: title,
                    date: scheduledDate.apiDate,
                    time: includesTime ? reminderTime.apiTime : nil,
                    notes: cleanNotes,
                    repeatUntilCompleted: includesTime && !important && repeatUntilCompleted,
                    nudgeIntervalMinutes: includesTime && !important && repeatUntilCompleted ? nudgeIntervalMinutes : nil,
                    important: includesTime && important
                )
            }
            saving = false
            if saved != nil {
                await onSaved()
                dismiss()
            }
        }
    }
}

/// Dashboard adapter for the reusable calendar widget.
struct ScheduleCalendarDashboardWidget: View {
    @EnvironmentObject private var store: MoneyStore
    @State private var month = ScheduleCalendar.monthStart(Date())
    @State private var selectedDate = Date()
    @State private var selectedDay: ScheduleDaySelection?

    var body: some View {
        ScheduleCalendarWidget(
            month: $month,
            selectedDate: $selectedDate,
            items: store.scheduleItems
        ) { date in
            selectedDay = ScheduleDaySelection(date: date)
        }
            .task(id: month.apiDate) {
                let range = ScheduleCalendar.loadingRange(month)
                await store.loadSchedule(from: range.start, through: range.end)
            }
            .sheet(item: $selectedDay) { selection in
                ScheduleDayDetailView(date: selection.date)
                    .presentationDragIndicator(.visible)
            }
    }
}

/// Dashboard adapter for today's merged agenda.
struct ScheduleTodayDashboardWidget: View {
    @EnvironmentObject private var store: MoneyStore
    private let today = Date()

    var body: some View {
        ScheduleAgendaWidget(date: today, items: store.scheduleItems)
            .task {
                let month = ScheduleCalendar.monthStart(today)
                let range = ScheduleCalendar.loadingRange(month)
                await store.loadSchedule(from: range.start, through: range.end)
            }
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
