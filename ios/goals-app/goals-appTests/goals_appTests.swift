//
//  goals_appTests.swift
//  goals-appTests
//
//  Created by Caleb Shim on 7/18/26.
//

import XCTest
@testable import goals_app

final class goals_appTests: XCTestCase {
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
}
