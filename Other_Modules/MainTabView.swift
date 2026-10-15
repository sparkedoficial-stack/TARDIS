//
//  MainTabView.swift
//  GIA - GODWORKS SYSTEM iOS Sovereign Client
//
//  Created for GIA Ecosystem.
//

import SwiftUI

public struct MainTabView: View {
    @State private var selectedTab: Int = 0
    
    public init() {
        // Personalizar apariencia de la barra de pestañas (TabBar)
        let appearance = UITabBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = UIColor(GIATheme.panel)
        
        // Item normal
        appearance.stackedLayoutAppearance.normal.iconColor = UIColor(GIATheme.dim)
        appearance.stackedLayoutAppearance.normal.titleTextAttributes = [
            .foregroundColor: UIColor(GIATheme.dim),
            .font: UIFont.monospacedSystemFont(ofSize: 10, weight: .medium)
        ]
        
        // Item seleccionado (Teal GIA)
        appearance.stackedLayoutAppearance.selected.iconColor = UIColor(GIATheme.teal)
        appearance.stackedLayoutAppearance.selected.titleTextAttributes = [
            .foregroundColor: UIColor(GIATheme.teal),
            .font: UIFont.monospacedSystemFont(ofSize: 10, weight: .bold)
        ]
        
        UITabBar.appearance().standardAppearance = appearance
        UITabBar.appearance().scrollEdgeAppearance = appearance
    }
    
    public var body: some View {
        TabView(selection: $selectedTab) {
            ChatView()
                .tabItem {
                    Label("Chat", systemImage: "bubble.left.and.bubble.right.fill")
                }
                .tag(0)
            
            SensorsView()
                .tabItem {
                    Label("Sensores", systemImage: "waveform.path.ecg")
                }
                .tag(1)
            
            MonitorView()
                .tabItem {
                    Label("Monitor", systemImage: "chart.xyaxis.line")
                }
                .tag(2)
            
            SettingsView()
                .tabItem {
                    Label("Ajustes", systemImage: "gearshape.fill")
                }
                .tag(3)
        }
        .tint(GIATheme.teal)
    }
}
