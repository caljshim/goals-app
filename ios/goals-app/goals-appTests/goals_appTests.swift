//
//  goals_appTests.swift
//  goals-appTests
//
//  Created by Caleb Shim on 7/18/26.
//

import XCTest
@testable import goals_app

final class goals_appTests: XCTestCase {
    func testGoalTimelineFillsQuietCalendarDaysThroughRequestedEnd() throws {
        let history = [
            HistoryPoint(value: 10, at: "2026-07-19T12:00:00"),
            HistoryPoint(value: 15, at: "2026-07-22T12:00:00"),
        ]
        let end = try XCTUnwrap(Calendar.current.date(from: DateComponents(year: 2026, month: 7, day: 22)))

        let timeline = GoalChartTimeline.daily(history, through: end)

        XCTAssertEqual(timeline.map(\.dayKey), ["2026-07-19", "2026-07-20", "2026-07-21", "2026-07-22"])
        XCTAssertEqual(timeline.map(\.value), [10, 10, 10, 15])
        XCTAssertEqual(timeline.map(\.isRecorded), [true, false, false, true])
    }

    func testGoalTimelineUsesLastUpdateForEachDay() throws {
        let history = [
            HistoryPoint(value: 10, at: "2026-07-19T10:00:00"),
            HistoryPoint(value: 12, at: "2026-07-19T18:00:00"),
        ]
        let end = try XCTUnwrap(Calendar.current.date(from: DateComponents(year: 2026, month: 7, day: 19)))

        let timeline = GoalChartTimeline.daily(history, through: end)

        XCTAssertEqual(timeline.count, 1)
        XCTAssertEqual(timeline.first?.value, 12)
    }

    func testActionReceiptHiddenWhenReplyAlreadyDescribesIt() {
        let actions = CopilotActionReceiptFilter.visibleActions(
            reply: "I categorized the unbudgeted transactions as dining.",
            actions: ["Categorized unbudgeted transactions as dining"]
        )

        XCTAssertTrue(actions.isEmpty)
    }

    func testDistinctActionReceiptRemainsVisible() {
        let actions = CopilotActionReceiptFilter.visibleActions(
            reply: "I reviewed this month's activity.",
            actions: ["Created a dining budget"]
        )

        XCTAssertEqual(actions, ["Created a dining budget"])
    }

    func testDuplicateActionReceiptsCollapse() {
        let actions = CopilotActionReceiptFilter.visibleActions(
            reply: "Done.",
            actions: ["Updated transaction category", "Updated transaction category"]
        )

        XCTAssertEqual(actions, ["Updated transaction category"])
    }

    // MARK: - DashboardReorder

    func testReorderedMovesCardDownward() {
        XCTAssertEqual(
            DashboardReorder.reordered(["a", "b", "c", "d"], move: "a", to: 2),
            ["b", "c", "a", "d"]
        )
    }

    func testReorderedMovesCardUpward() {
        XCTAssertEqual(
            DashboardReorder.reordered(["a", "b", "c", "d"], move: "d", to: 1),
            ["a", "d", "b", "c"]
        )
    }

    func testReorderedClampsPastEnd() {
        XCTAssertEqual(
            DashboardReorder.reordered(["a", "b", "c"], move: "a", to: 99),
            ["b", "c", "a"]
        )
    }

    func testReorderedIsNoOpForSameSlotOrMissingID() {
        XCTAssertEqual(DashboardReorder.reordered(["a", "b", "c"], move: "b", to: 1), ["a", "b", "c"])
        XCTAssertEqual(DashboardReorder.reordered(["a", "b", "c"], move: "zzz", to: 0), ["a", "b", "c"])
    }

    func testTargetIndexAboveAllRowsIsZero() {
        let mids: [String: CGFloat] = ["a": 50, "b": 150, "c": 250]
        XCTAssertEqual(
            DashboardReorder.targetIndex(order: ["a", "b", "c"], midY: mids, liftedID: "b", fingerY: 10),
            0
        )
    }

    func testTargetIndexBelowAllRowsIsLastIndex() {
        let mids: [String: CGFloat] = ["a": 50, "b": 150, "c": 250]
        XCTAssertEqual(
            DashboardReorder.targetIndex(order: ["a", "b", "c"], midY: mids, liftedID: "b", fingerY: 999),
            2
        )
    }

    func testTargetIndexExcludesLiftedRowSoRestIsStable() {
        // Lifted "b" resting near its own slot (150) should not shuffle.
        let mids: [String: CGFloat] = ["a": 50, "b": 150, "c": 250]
        XCTAssertEqual(
            DashboardReorder.targetIndex(order: ["a", "b", "c"], midY: mids, liftedID: "b", fingerY: 160),
            1
        )
    }

    func testTargetIndexSkipsRowsWithNoMeasuredFrame() {
        // "c" unmeasured (off-screen): finger below "a" only.
        let mids: [String: CGFloat] = ["a": 50, "b": 150]
        XCTAssertEqual(
            DashboardReorder.targetIndex(order: ["a", "b", "c"], midY: mids, liftedID: "b", fingerY: 120),
            1
        )
    }

    // MARK: - System widgets

    func testWidgetSnapshotRemainingFilterKeepsEventsAndIncompleteTasks() {
        let snapshot = AudelWidgetSnapshot(
            generatedAt: Date(),
            tasks: [
                widgetTask(id: "done", title: "Done", completed: true),
                widgetTask(id: "later", title: "Later", completed: false),
                widgetTask(id: "event", source: "event", title: "Appointment", completed: false),
            ]
        )

        XCTAssertEqual(snapshot.tasks(for: .remaining).map(\.id), ["event", "later"])
        XCTAssertEqual(snapshot.completedCount, 1)
        XCTAssertEqual(snapshot.remainingCount, 1)
    }

    func testWidgetSnapshotSortsTimedItemsBeforeUntimedItems() {
        let snapshot = AudelWidgetSnapshot(
            generatedAt: Date(),
            tasks: [
                widgetTask(id: "untimed", title: "Untimed"),
                widgetTask(id: "evening", title: "Evening", reminderTime: "18:00"),
                widgetTask(id: "morning", title: "Morning", reminderTime: "08:00"),
            ]
        )

        XCTAssertEqual(
            snapshot.tasks(for: .everything).map(\.id),
            ["morning", "evening", "untimed"]
        )
    }

    func testAudelDeepLinksResolveToExistingTabs() {
        XCTAssertEqual(AudelDeepLink.tab(for: URL(string: "audel://assistant")!), "audel")
        XCTAssertEqual(AudelDeepLink.tab(for: URL(string: "audel://schedule")!), "routines")
        XCTAssertNil(AudelDeepLink.tab(for: URL(string: "https://example.com")!))
    }

    func testWidgetFileStorePersistsSnapshotAndConfigurationWithoutPreferences() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: directory) }

        let store = AudelWidgetFileStore(directoryURL: directory)
        let snapshot = AudelWidgetSnapshot(
            generatedAt: Date(timeIntervalSince1970: 1_775_000_000),
            tasks: [widgetTask(id: "persisted", title: "Persist me")]
        )

        store.saveSnapshot(snapshot)
        store.setBaseURL("https://example.com/api")

        XCTAssertEqual(store.loadSnapshot(), snapshot)
        XCTAssertEqual(store.baseURL, URL(string: "https://example.com/api"))
    }

    private func widgetTask(
        id: String,
        source: String = "routine",
        title: String,
        reminderTime: String? = nil,
        completed: Bool = false
    ) -> AudelWidgetTask {
        AudelWidgetTask(
            id: id,
            source: source,
            sourceID: 1,
            title: title,
            scheduledFor: "2026-07-29",
            reminderTime: reminderTime,
            completed: completed,
            missed: false
        )
    }
}
