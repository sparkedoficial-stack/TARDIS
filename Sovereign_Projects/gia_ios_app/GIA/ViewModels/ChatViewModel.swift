//
//  ChatViewModel.swift
//  GIA - GODWORKS SYSTEM iOS Sovereign Client
//
//  Created for GIA Ecosystem.
//

import SwiftUI
import Combine

@MainActor
public final class ChatViewModel: ObservableObject {
    @Published public var messages: [ChatMessage] = []
    @Published public var inputText: String = ""
    @Published public var isLoading: Bool = false
    @Published public var selectedDirection: TemporalDirection = .present
    @Published public var useWeb: Bool = true
    @Published public var useVoice: Bool = false
    @Published public var useRetro: Bool = false
    @Published public var localSpeechOutput: Bool = false
    @Published public var errorMessage: String?
    @Published public var isOnline: Bool = false
    @Published public var availableModels: [String] = []
    
    // Configuración persistente
    @AppStorage("gia_server_url") public var serverURL: String = "http://REDACTED_IP:8757"
    @AppStorage("gia_server_token") public var serverToken: String = ""
    @AppStorage("gia_selected_model") public var selectedModel: String = "llama3.1:8b"
    
    private let network = GIANetworkService.shared
    private let voice = AudioVoiceService.shared
    
    public init() {
        self.messages = [
            ChatMessage(
                role: "assistant",
                content: "Sistema GIA conectado. Nodo Soberano listo. ¿En qué colaboramos hoy?",
                timestamp: Date(),
                direction: .present,
                provider: "local"
            )
        ]
        Task {
            await checkStatus()
        }
    }
    
    public func checkStatus() async {
        do {
            let status = try await network.fetchStatus(baseURL: serverURL, token: serverToken)
            self.isOnline = status.ok
            if let models = status.models, !models.isEmpty {
                self.availableModels = models
            }
        } catch {
            self.isOnline = false
        }
    }
    
    public func sendMessage() {
        let trimmed = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isLoading else { return }
        
        let userMsg = ChatMessage(
            role: "user",
            content: trimmed,
            timestamp: Date(),
            direction: selectedDirection
        )
        
        messages.append(userMsg)
        inputText = ""
        isLoading = true
        errorMessage = nil
        
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        
        let payload = ChatRequestPayload(
            message: userMsg.content,
            history: messages.dropLast(),
            useWeb: useWeb,
            useVoice: useVoice,
            useRetro: selectedDirection == .future || useRetro,
            direction: selectedDirection,
            model: selectedModel.isEmpty ? nil : selectedModel
        )
        
        Task {
            do {
                let response = try await network.sendChat(
                    baseURL: serverURL,
                    token: serverToken,
                    payload: payload
                )
                
                if response.ok, let reply = response.reply {
                    let retro = response.retro_analysis
                    let assistantMsg = ChatMessage(
                        role: "assistant",
                        content: reply,
                        timestamp: Date(),
                        direction: selectedDirection,
                        webSources: response.web_sources,
                        provider: response.provider,
                        model: response.model,
                        elapsedSeconds: response.elapsed_s,
                        futureEcho: retro?.future_echo,
                        entropy: retro?.entropy,
                        syntropyCoherence: retro?.quantum_coherence
                    )
                    messages.append(assistantMsg)
                    UINotificationFeedbackGenerator().notificationOccurred(.success)
                    
                    // Si el usuario activó la voz en el iPhone
                    if localSpeechOutput {
                        voice.speak(text: reply)
                    }
                } else {
                    let err = response.error ?? "Respuesta vacía del nodo."
                    self.errorMessage = err
                    messages.append(ChatMessage(
                        role: "assistant",
                        content: "⚠️ [Error]: \(err)",
                        timestamp: Date(),
                        direction: selectedDirection
                    ))
                    UINotificationFeedbackGenerator().notificationOccurred(.error)
                }
            } catch {
                self.errorMessage = error.localizedDescription
                messages.append(ChatMessage(
                    role: "assistant",
                    content: "⚠️ [Fallo de Conexión]: \(error.localizedDescription)",
                    timestamp: Date(),
                    direction: selectedDirection
                ))
                UINotificationFeedbackGenerator().notificationOccurred(.error)
            }
            self.isLoading = false
        }
    }
    
    public func clearHistory() {
        messages.removeAll()
        messages.append(
            ChatMessage(
                role: "assistant",
                content: "Historial de conversación reiniciado.",
                timestamp: Date(),
                direction: .present
            )
        )
    }
}
