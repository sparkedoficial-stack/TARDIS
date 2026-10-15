//
//  MonitorViewModel.swift
//  GIA - GODWORKS SYSTEM iOS Sovereign Client
//
//  Created for GIA Ecosystem.
//

import SwiftUI
import Combine

@MainActor
public final class MonitorViewModel: ObservableObject {
    @Published public var monitorData: MonitorData?
    @Published public var isLoading: Bool = false
    @Published public var errorMessage: String?
    @Published public var isAutoRefreshing: Bool = true
    @Published public var lastUpdated: Date?
    
    @AppStorage("gia_server_url") private var serverURL: String = "http://REDACTED_IP:8757"
    @AppStorage("gia_server_token") private var serverToken: String = ""
    
    private var timer: Timer?
    private let network = GIANetworkService.shared
    
    public init() {
        startPolling()
    }
    
    public func startPolling() {
        fetchData()
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self = self, self.isAutoRefreshing else { return }
                self.fetchData()
            }
        }
    }
    
    public func stopPolling() {
        timer?.invalidate()
        timer = nil
    }
    
    public func fetchData() {
        guard !serverURL.isEmpty else { return }
        
        Task {
            do {
                let data = try await network.fetchMonitor(baseURL: serverURL, token: serverToken)
                self.monitorData = data
                self.lastUpdated = Date()
                self.errorMessage = nil
            } catch {
                self.errorMessage = error.localizedDescription
            }
        }
    }
    
    deinit {
        timer?.invalidate()
    }
}
