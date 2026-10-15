//
//  ChatView.swift
//  GIA - GODWORKS SYSTEM iOS Sovereign Client
//
//  Created for GIA Ecosystem.
//

import SwiftUI

public struct ChatView: View {
    @StateObject private var viewModel = ChatViewModel()
    @StateObject private var voiceService = AudioVoiceService.shared
    @FocusState private var isInputFocused: Bool
    
    public init() {}
    
    public var body: some View {
        NavigationStack {
            ZStack {
                GIATheme.bg.ignoresSafeArea()
                
                VStack(spacing: 0) {
                    // Header Bar
                    headerView
                    
                    // Temporal Vector Selector
                    temporalVectorBar
                    
                    // Chat Messages Scroll
                    messagesScrollView
                    
                    // Options & Toggles Bar
                    optionsToggleBar
                    
                    // Message Input Field
                    inputBar
                }
            }
            .navigationBarHidden(true)
            .alert(item: Binding<ErrorAlertItem?>(
                get: { viewModel.errorMessage.map { ErrorAlertItem(message: $0) } },
                set: { _ in viewModel.errorMessage = nil }
            )) { item in
                Alert(title: Text("Estado del Sistema GIA"), message: Text(item.message), dismissButton: .default(Text("OK")))
            }
        }
    }
    
    // MARK: - Header
    
    private var headerView: some View {
        HStack(spacing: 12) {
            // Sigilo Rombo GIA
            ZStack {
                Rectangle()
                    .stroke(GIATheme.teal, lineWidth: 1.5)
                    .rotationEffect(.degrees(45))
                    .frame(width: 20, height: 20)
                Circle()
                    .fill(GIATheme.gold)
                    .frame(width: 4, height: 4)
            }
            .frame(width: 28, height: 28)
            
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text("GIA")
                        .font(.system(size: 16, weight: .bold, design: .monospaced))
                        .foregroundColor(GIATheme.teal)
                        .tracking(2)
                    
                    Circle()
                        .fill(viewModel.isOnline ? GIATheme.teal : GIATheme.dim)
                        .frame(width: 7, height: 7)
                        .shadow(color: viewModel.isOnline ? GIATheme.teal : .clear, radius: 4)
                }
                Text(viewModel.selectedModel)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundColor(GIATheme.dim)
            }
            
            Spacer()
            
            Button(action: { viewModel.clearHistory() }) {
                Image(systemName: "trash")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundColor(GIATheme.dim)
                    .padding(8)
                    .background(Circle().fill(GIATheme.panel))
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(GIATheme.panel.opacity(0.95))
        .overlay(
            Rectangle()
                .frame(height: 1)
                .foregroundColor(GIATheme.border),
            alignment: .bottom
        )
    }
    
    // MARK: - Temporal Vector Bar
    
    private var temporalVectorBar: some View {
        HStack(spacing: 8) {
            ForEach(TemporalDirection.allCases) { direction in
                Button(action: {
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.7)) {
                        viewModel.selectedDirection = direction
                        UIImpactFeedbackGenerator(style: .light).impactOccurred()
                    }
                }) {
                    HStack(spacing: 4) {
                        if direction == .future {
                            Image(systemName: "sparkles")
                                .font(.system(size: 10))
                        }
                        Text(direction.shortBadge)
                            .font(.system(size: 11, weight: .bold, design: .monospaced))
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .foregroundColor(viewModel.selectedDirection == direction ? GIATheme.bg : (direction == .future ? GIATheme.gold : GIATheme.dim))
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .fill(
                                viewModel.selectedDirection == direction
                                ? (direction == .future ? GIATheme.gold : GIATheme.teal)
                                : GIATheme.panelAlt
                            )
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(
                                direction == .future && viewModel.selectedDirection != direction
                                ? GIATheme.gold.opacity(0.4)
                                : GIATheme.border,
                                lineWidth: 1
                            )
                    )
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(GIATheme.bg)
    }
    
    // MARK: - Messages Scroll View
    
    private var messagesScrollView: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 14) {
                    ForEach(viewModel.messages) { msg in
                        MessageBubbleView(message: msg)
                            .id(msg.id)
                    }
                    
                    if viewModel.isLoading {
                        HStack(spacing: 8) {
                            ProgressView()
                                .tint(GIATheme.teal)
                            Text("Colapsando respuesta sintrópica...")
                                .font(.system(size: 12, design: .monospaced))
                                .foregroundColor(GIATheme.teal)
                        }
                        .padding(.vertical, 8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 16)
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
            }
            .onChange(of: viewModel.messages.count) { _ in
                if let last = viewModel.messages.last {
                    withAnimation {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
        }
    }
    
    // MARK: - Quick Toggles Bar
    
    private var optionsToggleBar: some View {
        HStack(spacing: 12) {
            ToggleOptionPill(
                icon: "globe",
                title: "Web",
                isOn: $viewModel.useWeb
            )
            ToggleOptionPill(
                icon: "speaker.wave.2",
                title: "Voz PC",
                isOn: $viewModel.useVoice
            )
            ToggleOptionPill(
                icon: "iphone.radiowaves.left.and.right",
                title: "Voz iOS",
                isOn: $viewModel.localSpeechOutput
            )
            
            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 6)
        .background(GIATheme.panel.opacity(0.6))
    }
    
    // MARK: - Input Bar
    
    private var inputBar: some View {
        HStack(spacing: 10) {
            // Dictation Button
            Button(action: {
                if voiceService.isRecording {
                    voiceService.stopRecording()
                } else {
                    do {
                        try voiceService.startRecording { text in
                            viewModel.inputText = text
                        }
                    } catch {
                        viewModel.errorMessage = error.localizedDescription
                    }
                }
            }) {
                Image(systemName: voiceService.isRecording ? "mic.circle.fill" : "mic.fill")
                    .font(.system(size: 18))
                    .foregroundColor(voiceService.isRecording ? .red : GIATheme.teal)
                    .frame(width: 36, height: 36)
                    .background(Circle().fill(GIATheme.panelAlt))
            }
            
            // Text Input Field
            TextField("Transmite un comando o pregunta a GIA...", text: $viewModel.inputText, axis: .vertical)
                .font(.system(size: 14))
                .foregroundColor(GIATheme.txt)
                .lineLimit(1...4)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 18)
                        .fill(GIATheme.panelAlt)
                        .overlay(
                            RoundedRectangle(cornerRadius: 18)
                                .stroke(GIATheme.border, lineWidth: 1)
                        )
                )
                .focused($isInputFocused)
            
            // Send Button
            Button(action: {
                viewModel.sendMessage()
                isInputFocused = false
            }) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 32))
                    .foregroundColor(
                        viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading
                        ? GIATheme.dim
                        : GIATheme.teal
                    )
            }
            .disabled(viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(GIATheme.panel)
    }
}

// MARK: - Message Bubble Component

public struct MessageBubbleView: View {
    public let message: ChatMessage
    
    public var body: some View {
        HStack {
            if message.isUser {
                Spacer(minLength: 40)
            }
            
            VStack(alignment: message.isUser ? .trailing : .leading, spacing: 6) {
                // Retro / Future Tag
                if !message.isUser && message.direction == .future {
                    HStack(spacing: 4) {
                        Image(systemName: "sparkles")
                            .font(.system(size: 9))
                        Text("COLAPSO RETROCAUSAL Ψ")
                            .font(.system(size: 9, weight: .bold, design: .monospaced))
                    }
                    .foregroundColor(GIATheme.teal)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(GIATheme.teal.opacity(0.12))
                    .cornerRadius(4)
                }
                
                // Content text
                Text(message.content)
                    .font(.system(size: 14.5))
                    .foregroundColor(GIATheme.txt)
                    .lineSpacing(3)
                    .textSelection(.enabled)
                
                // Future Echo Box (if available)
                if let echo = message.futureEcho, !echo.isEmpty {
                    VStack(alignment: .leading, spacing: 3) {
                        HStack {
                            Image(systemName: "wave.3.forward")
                                .font(.system(size: 9))
                            Text("ECO ESPECTRAL (FASE DESPLAZADA)")
                                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                        }
                        .foregroundColor(GIATheme.gold)
                        
                        Text(echo)
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(GIATheme.gold.opacity(0.9))
                    }
                    .padding(8)
                    .background(Color.black.opacity(0.4))
                    .cornerRadius(8)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(GIATheme.gold.opacity(0.35), lineWidth: 1)
                    )
                }
                
                // Web Sources
                if let sources = message.webSources, !sources.isEmpty {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Fuentes:")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundColor(GIATheme.dim)
                        ForEach(sources.prefix(2), id: \.self) { src in
                            Text(src)
                                .font(.system(size: 9, design: .monospaced))
                                .foregroundColor(GIATheme.teal.opacity(0.8))
                                .lineLimit(1)
                        }
                    }
                    .padding(.top, 2)
                }
                
                // Footer (Metadata)
                HStack(spacing: 8) {
                    if let elapsed = message.elapsedSeconds {
                        Text(String(format: "%.1fs", elapsed))
                            .font(.system(size: 9, design: .monospaced))
                            .foregroundColor(GIATheme.dim)
                    }
                    if let provider = message.provider {
                        Text(provider.uppercased())
                            .font(.system(size: 9, weight: .bold, design: .monospaced))
                            .foregroundColor(GIATheme.teal.opacity(0.7))
                    }
                    Text(message.timestamp, style: .time)
                        .font(.system(size: 9))
                        .foregroundColor(GIATheme.dim)
                }
                .padding(.top, 2)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(
                        message.isUser
                        ? GIATheme.userBubble
                        : (message.direction == .future ? GIATheme.giaBubble : GIATheme.panelAlt)
                    )
            )
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .stroke(
                        message.isUser
                        ? GIATheme.border
                        : (message.direction == .future ? GIATheme.teal.opacity(0.4) : GIATheme.border),
                        lineWidth: 1
                    )
            )
            .shadow(color: (message.direction == .future && !message.isUser) ? GIATheme.teal.opacity(0.12) : .clear, radius: 8)
            
            if !message.isUser {
                Spacer(minLength: 40)
            }
        }
    }
}

// MARK: - Toggle Option Pill

public struct ToggleOptionPill: View {
    public let icon: String
    public let title: String
    @Binding public var isOn: Bool
    
    public var body: some View {
        Button(action: {
            isOn.toggle()
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
        }) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 10))
                Text(title)
                    .font(.system(size: 11, weight: .medium))
            }
            .padding(.horizontal, 9)
            .padding(.vertical, 4)
            .foregroundColor(isOn ? GIATheme.teal : GIATheme.dim)
            .background(
                Capsule()
                    .fill(isOn ? GIATheme.teal.opacity(0.15) : GIATheme.panelAlt)
            )
            .overlay(
                Capsule()
                    .stroke(isOn ? GIATheme.teal.opacity(0.4) : GIATheme.border, lineWidth: 1)
            )
        }
    }
}

public struct ErrorAlertItem: Identifiable {
    public var id: String { message }
    public let message: String
}
