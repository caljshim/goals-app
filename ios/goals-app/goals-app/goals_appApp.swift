//
//  goals_appApp.swift
//  goals-app
//
//  Created by Caleb Shim on 7/18/26.
//

import SwiftUI

@main
struct goals_appApp: App {
    @UIApplicationDelegateAdaptor(ReminderNotificationDelegate.self) private var notificationDelegate

    init() {
        AudelWidgetRuntime.bootstrapFromEnvironment()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
