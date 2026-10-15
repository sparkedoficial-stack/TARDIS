//
//  AudioVoiceService.swift
//  GIA - GODWORKS SYSTEM iOS Sovereign Client
//
//  Created for GIA Ecosystem.
//

import Foundation
import AVFoundation
import Speech
import Combine

@MainActor
public final class AudioVoiceService: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {
    public static let shared = AudioVoiceService()
    
    private let speechSynthesizer = AVSpeechSynthesizer()
    private var speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "es-ES"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()
    
    @Published public private(set) var isSpeaking: Bool = false
    @Published public private(set) var isRecording: Bool = false
    @Published public private(set) var recognizedText: String = ""
    @Published public var hasPermission: Bool = false
    
    public override init() {
        super.init()
        speechSynthesizer.delegate = self
        requestPermissions()
    }
    
    public func requestPermissions() {
        SFSpeechRecognizer.requestAuthorization { [weak self] authStatus in
            Task { @MainActor in
                self?.hasPermission = (authStatus == .authorized)
            }
        }
    }
    
    // MARK: - Text to Speech (Local iOS Voice)
    
    public func speak(text: String, language: String = "es-ES", rate: Float = 0.52) {
        stopSpeaking()
        
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: language)
        utterance.rate = rate
        utterance.pitchMultiplier = 1.0
        utterance.volume = 1.0
        
        isSpeaking = true
        speechSynthesizer.speak(utterance)
    }
    
    public func stopSpeaking() {
        if speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }
        isSpeaking = false
    }
    
    // MARK: - Speech to Text (Voice Input)
    
    public func startRecording(onResult: @escaping (String) -> Void) throws {
        if isRecording {
            stopRecording()
            return
        }
        
        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.record, mode: .measurement, options: .duckOthers)
        try audioSession.setActive(true, options: .notifyOthersOnDeactivation)
        
        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest = recognitionRequest else {
            throw NSError(domain: "GIAAudio", code: 1, userInfo: [NSLocalizedDescriptionKey: "No se pudo crear la solicitud de audio."])
        }
        recognitionRequest.shouldReportPartialResults = true
        
        let inputNode = audioEngine.inputNode
        recognitionTask = speechRecognizer?.recognitionTask(with: recognitionRequest) { [weak self] result, error in
            guard let self = self else { return }
            var isFinal = false
            if let result = result {
                self.recognizedText = result.bestTranscription.formattedString
                onResult(self.recognizedText)
                isFinal = result.isFinal
            }
            if error != nil || isFinal {
                self.stopRecording()
            }
        }
        
        let recordingFormat = inputNode.outputFormat(forBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { buffer, _ in
            recognitionRequest.append(buffer)
        }
        
        audioEngine.prepare()
        try audioEngine.start()
        isRecording = true
    }
    
    public func stopRecording() {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionRequest = nil
        recognitionTask?.cancel()
        recognitionTask = nil
        isRecording = false
        
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
    
    // MARK: - AVSpeechSynthesizerDelegate
    
    public nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in
            self.isSpeaking = false
        }
    }
    
    public nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in
            self.isSpeaking = false
        }
    }
}
