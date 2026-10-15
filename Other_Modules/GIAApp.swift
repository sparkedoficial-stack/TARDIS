//
//  GIAApp.swift
//  GIA - GODWORKS SYSTEM iOS Sovereign Client
//
//  Created for GIA Ecosystem.
//

import SwiftUI

@main
struct GIAApp: App {
    init() {
        // Inicializar configuración por defecto si es la primera vez
        let defaults: [String: Any] = [
            "gia_server_url": "http://REDACTED_IP:8757",
            "gia_server_token": "",
            "gia_selected_model": "llama3.1:8b",
            "gia_temperature": 0.4,
            "gia_num_ctx": 32768
        ]
        UserDefaults.standard.register(defaults: defaults)
    }
    
    var body: some Scene {
        WindowGroup {
            MainTabView()
                .preferredColorScheme(.dark)
        }
    }
}
