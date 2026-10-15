//
//  SensorsView.swift
//  GIA - GODWORKS SYSTEM iOS Sovereign Client
//
//  Created for GIA Ecosystem.
//

import SwiftUI

public struct SensorsView: View {
    @StateObject private var sensors = MotionSensorManager.shared
    @AppStorage("gia_server_url") private var serverURL: String = "http://REDACTED_IP:8757"
    @AppStorage("gia_server_token") private var serverToken: String = ""
    
    @State private var oracleMessage: String?
    @State private var isOracleLoading: Bool = false
    
    public init() {}
    
    public var body: some View {
        NavigationStack {
            ZStack {
                GIATheme.bg.ignoresSafeArea()
                
                ScrollView {
                    VStack(spacing: 16) {
                        // Sensor Header & Streaming Status
                        headerCard
                        
                        // Kinematic Vector Grid (Accel & Gyro)
                        kinematicGrid
                        
                        // Shannon Entropy & Noise Gauge
                        entropyCard
                        
                        // Oracle Trigger Card
                        oracleCard
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 14)
                }
            }
            .navigationTitle("Sensores & Entropía")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(GIATheme.panel, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .onAppear {
                sensors.startSensors(streamToServer: true, baseURL: serverURL, token: serverToken)
            }
        }
    }
    
    // MARK: - Header Status Card
    
    private var headerCard: some View {
        VStack(spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("REJILLA SENSORIAL CUÁNTICA")
                        .font(.system(size: 11, weight: .bold, design: .monospaced))
                        .foregroundColor(GIATheme.teal)
                    Text("Telemetría Física y Ruido Ambiental iOS")
                        .font(.system(size: 13))
                        .foregroundColor(GIATheme.txt)
                }
                Spacer()
                
                Button(action: {
                    if sensors.isStreaming {
                        sensors.stopSensors()
                    } else {
                        sensors.startSensors(streamToServer: true, baseURL: serverURL, token: serverToken)
                    }
                }) {
                    Text(sensors.isStreaming ? "ACTIVO (1 Hz)" : "PAUSADO")
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 5)
                        .foregroundColor(sensors.isStreaming ? GIATheme.bg : GIATheme.dim)
                        .background(sensors.isStreaming ? GIATheme.teal : GIATheme.panelAlt)
                        .cornerRadius(6)
                }
            }
            
            Divider().background(GIATheme.border)
            
            HStack {
                Text("Reloj Lamport: #\(sensors.lamportClock)")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(GIATheme.gold)
                Spacer()
                if let last = sensors.lastTelemetrySync {
                    Text("Sync: \(last, style: .time)")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(GIATheme.dim)
                }
            }
        }
        .padding(14)
        .giaGlassCard(borderColor: GIATheme.teal.opacity(0.3))
    }
    
    // MARK: - Kinematic Vector Grid
    
    private var kinematicGrid: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("VECTORES CINEMÁTICOS (m/s² & rad/s)")
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundColor(GIATheme.dim)
            
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                MetricPill(title: "Acel. Magnitud", value: String(format: "%.2f", sensors.magnitude), unit: "m/s²", color: GIATheme.teal)
                MetricPill(title: "Aceleración Z", value: String(format: "%.2f", sensors.accelZ), unit: "g-force", color: GIATheme.teal)
                MetricPill(title: "Aceleración X", value: String(format: "%.2f", sensors.accelX), unit: "m/s²", color: GIATheme.txt)
                MetricPill(title: "Aceleración Y", value: String(format: "%.2f", sensors.accelY), unit: "m/s²", color: GIATheme.txt)
                MetricPill(title: "Giroscopio X", value: String(format: "%.3f", sensors.gyroX), unit: "rad/s", color: GIATheme.gold)
                MetricPill(title: "Giroscopio Y", value: String(format: "%.3f", sensors.gyroY), unit: "rad/s", color: GIATheme.gold)
            }
        }
        .padding(14)
        .giaGlassCard()
    }
    
    // MARK: - Shannon Entropy Card
    
    private var entropyCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "waveform.path.ecg")
                    .foregroundColor(GIATheme.gold)
                Text("ENTROPÍA DE SHANNON (RUIDO FÍSICO)")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundColor(GIATheme.gold)
                Spacer()
                Text("\(String(format: "%.3f", sensors.entropyShannon)) bits")
                    .font(.system(size: 13, weight: .bold, design: .monospaced))
                    .foregroundColor(GIATheme.gold)
            }
            
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 6)
                        .fill(GIATheme.panelAlt)
                        .frame(height: 10)
                    
                    RoundedRectangle(cornerRadius: 6)
                        .fill(
                            LinearGradient(
                                colors: [GIATheme.teal, GIATheme.gold],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .frame(width: max(8, min(geo.size.width, geo.size.width * CGFloat(sensors.entropyShannon / 5.0))), height: 10)
                }
            }
            .frame(height: 10)
            
            Text("Las micro-vibraciones y el sensor inercial del iPhone alimentan la semilla del cono de luz retrocausal en el servidor.")
                .font(.system(size: 11))
                .foregroundColor(GIATheme.dim)
                .lineSpacing(2)
        }
        .padding(14)
        .giaGlassCard(borderColor: GIATheme.gold.opacity(0.3))
    }
    
    // MARK: - Oracle Card
    
    private var oracleCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "eye.circle.fill")
                    .foregroundColor(GIATheme.teal)
                Text("ORÁCULO SEMBRADO POR RUIDO REAL")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundColor(GIATheme.teal)
            }
            
            Text("Genera una transmisión en GIA derivada directamente del estado físico medido por este teléfono en este instante.")
                .font(.system(size: 11))
                .foregroundColor(GIATheme.dim)
            
            if let msg = oracleMessage {
                Text(msg)
                    .font(.system(size: 13, design: .monospaced))
                    .foregroundColor(GIATheme.txt)
                    .padding(10)
                    .background(GIATheme.panelAlt)
                    .cornerRadius(8)
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(GIATheme.teal.opacity(0.3), lineWidth: 1))
            }
            
            Button(action: {
                Task {
                    await triggerOracle()
                }
            }) {
                HStack {
                    if isOracleLoading {
                        ProgressView().tint(GIATheme.bg)
                    } else {
                        Image(systemName: "sparkles")
                        Text("Consultar Oráculo Físico")
                            .font(.system(size: 13, weight: .bold))
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .foregroundColor(GIATheme.bg)
                .background(GIATheme.teal)
                .cornerRadius(10)
            }
            .disabled(isOracleLoading)
        }
        .padding(14)
        .giaGlassCard()
    }
    
    private func triggerOracle() async {
        isOracleLoading = true
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        
        guard let url = URL(string: "\(serverURL)/api/telemetry/oracle\(serverToken.isEmpty ? "" : "?key=\(serverToken)")") else {
            isOracleLoading = false
            return
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !serverToken.isEmpty { req.setValue(serverToken, forHTTPHeaderField: "X-GIA-Key") }
        
        do {
            let (data, _) = try await URLSession.shared.data(for: req)
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let msg = json["message"] as? String {
                self.oracleMessage = msg
                UINotificationFeedbackGenerator().notificationOccurred(.success)
            }
        } catch {
            self.oracleMessage = "Error al consultar oráculo: \(error.localizedDescription)"
        }
        isOracleLoading = false
    }
}

public struct MetricPill: View {
    public let title: String
    public let value: String
    public let unit: String
    public let color: Color
    
    public var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.system(size: 10, design: .monospaced))
                .foregroundColor(GIATheme.dim)
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(value)
                    .font(.system(size: 16, weight: .bold, design: .monospaced))
                    .foregroundColor(color)
                Text(unit)
                    .font(.system(size: 9))
                    .foregroundColor(GIATheme.dim)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(GIATheme.panelAlt)
        .cornerRadius(8)
    }
}
