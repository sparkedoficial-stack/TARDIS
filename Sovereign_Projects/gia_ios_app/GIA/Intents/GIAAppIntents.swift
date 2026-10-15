//
//  GIAAppIntents.swift
//  GIA - GODWORKS SYSTEM iOS Sovereign Client
//
//  Created for GIA Ecosystem.
//

import AppIntents
import Foundation

// MARK: - Preguntar a GIA (Siri Intent)

public struct AskGIAIntent: AppIntent {
    public static var title: LocalizedStringResource = "Preguntar a GIA"
    public static var description = IntentDescription("Envía un mensaje o consulta al nodo de inteligencia GIA.")
    
    @Parameter(title: "Mensaje", description: "El texto o pregunta para GIA")
    public var message: String
    
    public init() {}
    public init(message: String) {
        self.message = message
    }
    
    public func perform() async throws -> some ReturnsValue<String> & ProvidesDialog {
        let serverURL = UserDefaults.standard.string(forKey: "gia_server_url") ?? "http://REDACTED_IP:8757"
        let serverToken = UserDefaults.standard.string(forKey: "gia_server_token") ?? ""
        let selectedModel = UserDefaults.standard.string(forKey: "gia_selected_model") ?? "llama3.1:8b"
        
        let payload = ChatRequestPayload(
            message: message,
            history: [],
            useWeb: true,
            useVoice: false,
            useRetro: false,
            direction: .present,
            model: selectedModel
        )
        
        do {
            let response = try await GIANetworkService.shared.sendChat(
                baseURL: serverURL,
                token: serverToken,
                payload: payload
            )
            
            let replyText = response.reply ?? "GIA no devolvió texto de respuesta."
            return .result(value: replyText, dialog: IntentDialog(stringLiteral: replyText))
        } catch {
            let errorText = "No se pudo comunicar con GIA: \(error.localizedDescription)"
            return .result(value: errorText, dialog: IntentDialog(stringLiteral: errorText))
        }
    }
}

// MARK: - Consultar Estado de GIA

public struct GIAStatusIntent: AppIntent {
    public static var title: LocalizedStringResource = "Estado de GIA"
    public static var description = IntentDescription("Comprueba si el nodo anfitrión GIA está activo y en línea.")
    
    public init() {}
    
    public func perform() async throws -> some ReturnsValue<String> & ProvidesDialog {
        let serverURL = UserDefaults.standard.string(forKey: "gia_server_url") ?? "http://REDACTED_IP:8757"
        let serverToken = UserDefaults.standard.string(forKey: "gia_server_token") ?? ""
        
        do {
            let status = try await GIANetworkService.shared.fetchStatus(baseURL: serverURL, token: serverToken)
            if status.ok {
                let model = status.model ?? "N/A"
                let diag = "Nodo GIA en línea. Modelo activo: \(model)."
                return .result(value: diag, dialog: IntentDialog(stringLiteral: diag))
            } else {
                return .result(value: "El nodo GIA no respondió correctamente.", dialog: "El nodo GIA no respondió correctamente.")
            }
        } catch {
            let err = "GIA no disponible: \(error.localizedDescription)"
            return .result(value: err, dialog: IntentDialog(stringLiteral: err))
        }
    }
}

// MARK: - App Shortcuts Provider

public struct GIAShortcuts: AppShortcutsProvider {
    public static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: AskGIAIntent(),
            phrases: [
                "Pregunta a \(.applicationName)",
                "Preguntar a \(.applicationName) \(\.$message)",
                "Habla con \(.applicationName)"
            ],
            shortTitle: "Preguntar a GIA",
            systemImageName: "bubble.left.and.bubble.right.fill"
        )
        AppShortcut(
            intent: GIAStatusIntent(),
            phrases: [
                "Estado de \(.applicationName)",
                "Verificar \(.applicationName)"
            ],
            shortTitle: "Estado de GIA",
            systemImageName: "bolt.fill"
        )
    }
}
