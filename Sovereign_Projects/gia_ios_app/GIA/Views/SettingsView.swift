//
//  SettingsView.swift
//  GIA - GODWORKS SYSTEM iOS Sovereign Client
//
//  Created for GIA Ecosystem.
//

import SwiftUI

public struct SettingsView: View {
    @AppStorage("gia_server_url") private var serverURL: String = "http://REDACTED_IP:8757"
    @AppStorage("gia_server_token") private var serverToken: String = ""
    @AppStorage("gia_selected_model") private var selectedModel: String = "llama3.1:8b"
    @AppStorage("gia_temperature") private var temperature: Double = 0.4
    @AppStorage("gia_num_ctx") private var numCtx: Int = 32768
    
    @State private var connectionStatus: String?
    @State private var isTesting: Bool = false
    @State private var safetyUnlocked: Bool = false
    
    public init() {}
    
    public var body: some View {
        NavigationStack {
            ZStack {
                GIATheme.bg.ignoresSafeArea()
                
                ScrollView {
                    VStack(spacing: 16) {
                        // Connection & Endpoint
                        connectionSection
                        
                        // Model & Parameters
                        modelParametersSection
                        
                        // Security & Safety Overrides
                        safetySection
                        
                        // App Info & Version
                        appInfoSection
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 14)
                }
            }
            .navigationTitle("Ajustes & Conexión")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(GIATheme.panel, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
    }
    
    // MARK: - Connection Section
    
    private var connectionSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "antenna.radiowaves.left.and.right")
                    .foregroundColor(GIATheme.teal)
                Text("SERVIDOR GIA (HOST LOCAL / TÚNEL)")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundColor(GIATheme.teal)
            }
            
            VStack(alignment: .leading, spacing: 6) {
                Text("URL del Servidor")
                    .font(.system(size: 11))
                    .foregroundColor(GIATheme.dim)
                TextField("http://REDACTED_IP:8757", text: $serverURL)
                    .font(.system(size: 13, design: .monospaced))
                    .foregroundColor(GIATheme.txt)
                    .padding(10)
                    .background(GIATheme.panelAlt)
                    .cornerRadius(8)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
            }
            
            VStack(alignment: .leading, spacing: 6) {
                Text("Clave de Acceso / Token (?key= o X-GIA-Key)")
                    .font(.system(size: 11))
                    .foregroundColor(GIATheme.dim)
                SecureField("Token del servidor (opcional en LAN)", text: $serverToken)
                    .font(.system(size: 13, design: .monospaced))
                    .foregroundColor(GIATheme.txt)
                    .padding(10)
                    .background(GIATheme.panelAlt)
                    .cornerRadius(8)
            }
            
            if let status = connectionStatus {
                Text(status)
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundColor(status.contains("✅") ? GIATheme.teal : .orange)
                    .padding(.top, 2)
            }
            
            Button(action: {
                Task {
                    await testConnection()
                }
            }) {
                HStack {
                    if isTesting {
                        ProgressView().tint(GIATheme.bg)
                    } else {
                        Image(systemName: "bolt.fill")
                        Text("Probar Conexión")
                            .font(.system(size: 13, weight: .bold))
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .foregroundColor(GIATheme.bg)
                .background(GIATheme.teal)
                .cornerRadius(8)
            }
            .disabled(isTesting)
        }
        .padding(14)
        .giaGlassCard()
    }
    
    // MARK: - Model & Parameters Section
    
    private var modelParametersSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "slider.horizontal.3")
                    .foregroundColor(GIATheme.gold)
                Text("INFERENCIA & PARÁMETROS")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundColor(GIATheme.gold)
            }
            
            VStack(alignment: .leading, spacing: 6) {
                Text("Modelo por Defecto")
                    .font(.system(size: 11))
                    .foregroundColor(GIATheme.dim)
                TextField("llama3.1:8b", text: $selectedModel)
                    .font(.system(size: 13, design: .monospaced))
                    .foregroundColor(GIATheme.txt)
                    .padding(10)
                    .background(GIATheme.panelAlt)
                    .cornerRadius(8)
            }
            
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Temperatura")
                        .font(.system(size: 11))
                        .foregroundColor(GIATheme.dim)
                    Spacer()
                    Text(String(format: "%.2f", temperature))
                        .font(.system(size: 12, weight: .bold, design: .monospaced))
                        .foregroundColor(GIATheme.teal)
                }
                Slider(value: $temperature, in: 0.0...1.0, step: 0.05)
                    .tint(GIATheme.teal)
            }
            
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Ventana de Contexto (Tokens)")
                        .font(.system(size: 11))
                        .foregroundColor(GIATheme.dim)
                    Spacer()
                    Text("\(numCtx)")
                        .font(.system(size: 12, weight: .bold, design: .monospaced))
                        .foregroundColor(GIATheme.gold)
                }
                Picker("Contexto", selection: $numCtx) {
                    Text("4096").tag(4096)
                    Text("8192").tag(8192)
                    Text("16384").tag(16384)
                    Text("32768").tag(32768)
                }
                .pickerStyle(.segmented)
            }
        }
        .padding(14)
        .giaGlassCard()
    }
    
    // MARK: - Safety Section
    
    private var safetySection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: "shield.lefthalf.filled")
                    .foregroundColor(.orange)
                Text("CAPA DE SEGURIDAD")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundColor(.orange)
            }
            
            Toggle(isOn: $safetyUnlocked) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Desbloqueo Extra del Sistema")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundColor(GIATheme.txt)
                    Text("Permite ejecución avanzada de herramientas y capacidades extendidas.")
                        .font(.system(size: 11))
                        .foregroundColor(GIATheme.dim)
                }
            }
            .tint(GIATheme.teal)
            .onChange(of: safetyUnlocked) { unlocked in
                Task {
                    await toggleSafety(unlocked: unlocked)
                }
            }
        }
        .padding(14)
        .giaGlassCard()
    }
    
    // MARK: - App Info Section
    
    private var appInfoSection: some View {
        VStack(spacing: 6) {
            Text("GIA Sovereign Client for iOS")
                .font(.system(size: 12, weight: .bold, design: .monospaced))
                .foregroundColor(GIATheme.teal)
            Text("GODWORKS SYSTEM • Protocolo Soberano v6.8")
                .font(.system(size: 10, design: .monospaced))
                .foregroundColor(GIATheme.dim)
        }
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity)
    }
    
    private func testConnection() async {
        isTesting = true
        connectionStatus = nil
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        
        do {
            let status = try await GIANetworkService.shared.fetchStatus(baseURL: serverURL, token: serverToken)
            if status.ok {
                connectionStatus = "✅ Conexión exitosa. Modelo activo: \(status.model ?? "N/A")"
                UINotificationFeedbackGenerator().notificationOccurred(.success)
            } else {
                connectionStatus = "⚠️ Servidor respondió sin estado OK."
            }
        } catch {
            connectionStatus = "❌ Error: \(error.localizedDescription)"
            UINotificationFeedbackGenerator().notificationOccurred(.error)
        }
        isTesting = false
    }
    
    private func toggleSafety(unlocked: Bool) async {
        let endpoint = unlocked ? "/api/safety/unlock" : "/api/safety/lock"
        guard let url = URL(string: "\(serverURL)\(endpoint)\(serverToken.isEmpty ? "" : "?key=\(serverToken)")") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !serverToken.isEmpty { req.setValue(serverToken, forHTTPHeaderField: "X-GIA-Key") }
        
        _ = try? await URLSession.shared.data(for: req)
    }
}
