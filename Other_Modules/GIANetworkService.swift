//
//  GIANetworkService.swift
//  GIA - GODWORKS SYSTEM iOS Sovereign Client
//
//  Created for GIA Ecosystem.
//

import Foundation
import Combine

public enum NetworkError: LocalizedError {
    case invalidURL
    case unauthorized
    case serverError(String)
    case decodingError(String)
    case connectionFailed(String)
    
    public var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "La URL del servidor es inválida."
        case .unauthorized:
            return "No autorizado. Verifica el token / clave de acceso (X-GIA-Key)."
        case .serverError(let msg):
            return "Error del servidor GIA: \(msg)"
        case .decodingError(let msg):
            return "Error al decodificar la respuesta: \(msg)"
        case .connectionFailed(let msg):
            return "No se pudo conectar con el nodo GIA: \(msg)"
        }
    }
}

public actor GIANetworkService {
    public static let shared = GIANetworkService()
    
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder
    
    public init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 180.0 // Permitir inferencia larga de modelos locales
        config.timeoutIntervalForResource = 300.0
        config.waitsForConnectivity = true
        self.session = URLSession(configuration: config)
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }
    
    // MARK: - Core Request Builder
    
    private func makeURL(endpoint: String, baseURL: String, token: String, queryItems: [URLQueryItem] = []) throws -> URL {
        var cleanBase = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if !cleanBase.hasPrefix("http://") && !cleanBase.hasPrefix("https://") {
            cleanBase = "http://" + cleanBase
        }
        if cleanBase.hasSuffix("/") {
            cleanBase.removeLast()
        }
        
        guard var components = URLComponents(string: "\(cleanBase)\(endpoint)") else {
            throw NetworkError.invalidURL
        }
        
        var items = queryItems
        if !token.isEmpty {
            items.append(URLQueryItem(name: "key", value: token))
        }
        if !items.isEmpty {
            components.queryItems = items
        }
        
        guard let finalURL = components.url else {
            throw NetworkError.invalidURL
        }
        return finalURL
    }
    
    private func makeRequest(url: URL, method: String, token: String, body: Data? = nil) -> URLRequest {
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.setValue("GIA-iOS-Native/1.0", forHTTPHeaderField: "User-Agent")
        if !token.isEmpty {
            req.setValue(token, forHTTPHeaderField: "X-GIA-Key")
        }
        req.httpBody = body
        return req
    }
    
    // MARK: - API Methods
    
    /// Envía un mensaje al endpoint `/api/chat`
    public func sendChat(
        baseURL: String,
        token: String,
        payload: ChatRequestPayload
    ) async throws -> ChatResponsePayload {
        let url = try makeURL(endpoint: "/api/chat", baseURL: baseURL, token: token)
        let bodyData = try encoder.encode(payload)
        let req = makeRequest(url: url, method: "POST", token: token, body: bodyData)
        
        do {
            let (data, response) = try await session.data(for: req)
            guard let httpResponse = response as? HTTPURLResponse else {
                throw NetworkError.connectionFailed("Respuesta no válida del servidor.")
            }
            if httpResponse.statusCode == 401 {
                throw NetworkError.unauthorized
            }
            guard (200...299).contains(httpResponse.statusCode) else {
                let errString = String(data: data, encoding: .utf8) ?? "HTTP \(httpResponse.statusCode)"
                throw NetworkError.serverError(errString)
            }
            
            return try decoder.decode(ChatResponsePayload.self, from: data)
        } catch let err as NetworkError {
            throw err
        } catch let decErr as DecodingError {
            throw NetworkError.decodingError(decErr.localizedDescription)
        } catch {
            throw NetworkError.connectionFailed(error.localizedDescription)
        }
    }
    
    /// Obtiene el estado general del sistema `/api/status`
    public func fetchStatus(baseURL: String, token: String) async throws -> SystemStatusResponse {
        let url = try makeURL(endpoint: "/api/status", baseURL: baseURL, token: token)
        let req = makeRequest(url: url, method: "GET", token: token)
        
        let (data, response) = try await session.data(for: req)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw NetworkError.connectionFailed("Sin respuesta.")
        }
        if httpResponse.statusCode == 401 { throw NetworkError.unauthorized }
        return try decoder.decode(SystemStatusResponse.self, from: data)
    }
    
    /// Obtiene métricas de hardware y monitor `/api/monitor`
    public func fetchMonitor(baseURL: String, token: String) async throws -> MonitorData {
        let url = try makeURL(endpoint: "/api/monitor", baseURL: baseURL, token: token)
        let req = makeRequest(url: url, method: "GET", token: token)
        
        let (data, response) = try await session.data(for: req)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw NetworkError.connectionFailed("Sin respuesta.")
        }
        if httpResponse.statusCode == 401 { throw NetworkError.unauthorized }
        return try decoder.decode(MonitorData.self, from: data)
    }
    
    /// Transmite un paquete de sensores `/api/telemetry`
    public func sendTelemetry(baseURL: String, token: String, packet: SensorPacket) async throws -> TelemetryResponse {
        let url = try makeURL(endpoint: "/api/telemetry", baseURL: baseURL, token: token)
        let bodyData = try encoder.encode(packet)
        let req = makeRequest(url: url, method: "POST", token: token, body: bodyData)
        
        let (data, response) = try await session.data(for: req)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw NetworkError.connectionFailed("Sin respuesta.")
        }
        if httpResponse.statusCode == 401 { throw NetworkError.unauthorized }
        return try decoder.decode(TelemetryResponse.self, from: data)
    }
    
    /// Solicita estado de bloqueos de seguridad `/api/safety/status`
    public func fetchSafetyStatus(baseURL: String, token: String) async throws -> Bool {
        let url = try makeURL(endpoint: "/api/safety/status", baseURL: baseURL, token: token)
        let req = makeRequest(url: url, method: "GET", token: token)
        let (data, _) = try await session.data(for: req)
        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let ok = json["ok"] as? Bool {
            return ok
        }
        return false
    }
}
