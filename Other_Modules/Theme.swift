//
//  Theme.swift
//  GIA - GODWORKS SYSTEM iOS Sovereign Client
//
//  Created for GIA Ecosystem.
//

import SwiftUI

public enum GIATheme {
    public static let bg = Color(hex: "0A0E14")
    public static let panel = Color(hex: "111823")
    public static let panelAlt = Color(hex: "16202E")
    public static let teal = Color(hex: "00D4C8")
    public static let gold = Color(hex: "E8B64A")
    public static let purple = Color(hex: "B39DDB")
    public static let txt = Color(hex: "D6E0EA")
    public static let dim = Color(hex: "5F6B7A")
    public static let userBubble = Color(hex: "1A2536")
    public static let giaBubble = Color(hex: "0E2B2A")
    public static let border = Color(hex: "1C2836")
    public static let borderGlow = Color(hex: "00D4C8").opacity(0.3)
    
    public static let cyberGradient = LinearGradient(
        colors: [Color(hex: "00D4C8"), Color(hex: "0E6C68")],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
    
    public static let retroGradient = LinearGradient(
        colors: [Color(hex: "0E2B2A"), Color(hex: "091722")],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
}

public extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let a, r, g, b: UInt64
        switch hex.count {
        case 3: // RGB (12-bit)
            (a, r, g, b) = (255, (int >> 8) * 17, (int >> 4 & 0xF) * 17, (int & 0xF) * 17)
        case 6: // RGB (24-bit)
            (a, r, g, b) = (255, int >> 16, int >> 8 & 0xFF, int & 0xFF)
        case 8: // ARGB (32-bit)
            (a, r, g, b) = (int >> 24, int >> 16 & 0xFF, int >> 8 & 0xFF, int & 0xFF)
        default:
            (a, r, g, b) = (255, 0, 212, 200)
        }
        self.init(
            .sRGB,
            red: Double(r) / 255,
            green: Double(g) / 255,
            blue: Double(b) / 255,
            opacity: Double(a) / 255
        )
    }
}

public struct GIAGlassCard: ViewModifier {
    public var cornerRadius: CGFloat = 14
    public var borderColor: Color = GIATheme.border
    
    public func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: cornerRadius)
                    .fill(GIATheme.panel.opacity(0.85))
                    .overlay(
                        RoundedRectangle(cornerRadius: cornerRadius)
                            .stroke(borderColor, lineWidth: 1)
                    )
                    .shadow(color: GIATheme.teal.opacity(0.05), radius: 8, x: 0, y: 4)
            )
    }
}

public extension View {
    func giaGlassCard(cornerRadius: CGFloat = 14, borderColor: Color = GIATheme.border) -> some View {
        modifier(GIAGlassCard(cornerRadius: cornerRadius, borderColor: borderColor))
    }
}
