//
//  MotionSensorManager.swift
//  GIA - GODWORKS SYSTEM iOS Sovereign Client
//
//  Created for GIA Ecosystem.
//

import Foundation
import CoreMotion
import Combine

@MainActor
public final class MotionSensorManager: ObservableObject {
    public static let shared = MotionSensorManager()
    
    private let motionManager = CMMotionManager()
    private var timer: Timer?
    
    @Published public private(set) var isStreaming: Bool = false
    @Published public private(set) var accelX: Double = 0.0
    @Published public private(set) var accelY: Double = 0.0
    @Published public private(set) var accelZ: Double = 0.0
    @Published public private(set) var magnitude: Double = 0.0
    @Published public private(set) var gyroX: Double = 0.0
    @Published public private(set) var gyroY: Double = 0.0
    @Published public private(set) var gyroZ: Double = 0.0
    @Published public private(set) var entropyShannon: Double = 0.0
    @Published public private(set) var lamportClock: Int = 0
    @Published public private(set) var lastTelemetrySync: Date?
    
    private var entropyHistory: [Double] = []
    
    public init() {
        motionManager.accelerometerUpdateInterval = 0.1
        motionManager.gyroUpdateInterval = 0.1
    }
    
    public func startSensors(streamToServer: Bool = false, baseURL: String = "", token: String = "") {
        guard !isStreaming else { return }
        
        if motionManager.isAccelerometerAvailable {
            motionManager.startAccelerometerUpdates(to: .main) { [weak self] data, _ in
                guard let self = self, let data = data else { return }
                self.accelX = data.acceleration.x * 9.80665
                self.accelY = data.acceleration.y * 9.80665
                self.accelZ = data.acceleration.z * 9.80665
                self.magnitude = sqrt(pow(self.accelX, 2) + pow(self.accelY, 2) + pow(self.accelZ, 2))
                self.updateEntropy(value: self.magnitude)
            }
        }
        
        if motionManager.isGyroAvailable {
            motionManager.startGyroUpdates(to: .main) { [weak self] data, _ in
                guard let self = self, let data = data else { return }
                self.gyroX = data.rotationRate.x
                self.gyroY = data.rotationRate.y
                self.gyroZ = data.rotationRate.z
            }
        }
        
        isStreaming = true
        
        if streamToServer {
            timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
                Task { @MainActor [weak self] in
                    guard let self = self else { return }
                    await self.syncWithServer(baseURL: baseURL, token: token)
                }
            }
        }
    }
    
    public func stopSensors() {
        motionManager.stopAccelerometerUpdates()
        motionManager.stopGyroUpdates()
        timer?.invalidate()
        timer = nil
        isStreaming = false
    }
    
    private func updateEntropy(value: Double) {
        entropyHistory.append(value)
        if entropyHistory.count > 40 {
            entropyHistory.removeFirst()
        }
        // Shannon entropy calculation over sensor float jitter
        let count = Double(entropyHistory.count)
        guard count > 1 else { return }
        
        var bins: [Int: Int] = [:]
        for val in entropyHistory {
            let bin = Int(val * 10.0)
            bins[bin, default: 0] += 1
        }
        var ent: Double = 0.0
        for (_, c) in bins {
            let p = Double(c) / count
            if p > 0 {
                ent -= p * log2(p)
            }
        }
        self.entropyShannon = round(ent * 1000) / 1000.0
    }
    
    private func calculateSiderealTime() -> Double {
        let now = Date().timeIntervalSince1970
        let days = (now / 86400.0) - 10957.5
        let gmst = 18.697374558 + 24.06570982441908 * days
        let siderealHours = gmst.truncatingRemainder(dividingBy: 24.0)
        return siderealHours < 0 ? siderealHours + 24.0 : siderealHours
    }
    
    private func syncWithServer(baseURL: String, token: String) async {
        guard !baseURL.isEmpty else { return }
        lamportClock += 1
        
        let packet = SensorPacket(
            ts: Date().timeIntervalSince1970,
            kinematic: .init(
                x: accelX,
                y: accelY,
                z: accelZ,
                magnitude: magnitude,
                gyro_x: gyroX,
                gyro_y: gyroY,
                gyro_z: gyroZ
            ),
            acoustic_level: 0.0,
            sidereal_local: calculateSiderealTime(),
            lamport: lamportClock,
            battery_pct: nil,
            device_source: "iOS-CoreMotion"
        )
        
        do {
            _ = try await GIANetworkService.shared.sendTelemetry(baseURL: baseURL, token: token, packet: packet)
            self.lastTelemetrySync = Date()
        } catch {
            // Silencioso en caso de error de fondo
        }
    }
}
