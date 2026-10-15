//
//  MonitorView.swift
//  GIA - GODWORKS SYSTEM iOS Sovereign Client
//
//  Created for GIA Ecosystem.
//

import SwiftUI

public struct MonitorView: View {
    @StateObject private var viewModel = MonitorViewModel()
    
    public init() {}
    
    public var body: some View {
        NavigationStack {
            ZStack {
                GIATheme.bg.ignoresSafeArea()
                
                ScrollView {
                    VStack(spacing: 16) {
                        if let error = viewModel.errorMessage {
                            HStack {
                                Image(systemName: "exclamationmark.triangle.fill")
                                    .foregroundColor(.orange)
                                Text(error)
                                    .font(.system(size: 12))
                                    .foregroundColor(GIATheme.txt)
                            }
                            .padding(10)
                            .frame(maxWidth: .infinity)
                            .background(Color.orange.opacity(0.15))
                            .cornerRadius(8)
                        }
                        
                        // Main Hardware Resource Rings (CPU & RAM)
                        hardwareOverview
                        
                        // GPU & VRAM Status (if available)
                        if let gpu = viewModel.monitorData?.gpu, gpu.name != nil {
                            gpuStatusCard(gpu: gpu)
                        }
                        
                        // Loaded Models in Ollama
                        loadedModelsCard
                        
                        // Top Memory Processes
                        topProcessesCard
                        
                        // Cluster Nodes
                        if let nodes = viewModel.monitorData?.nodes, !nodes.isEmpty {
                            clusterNodesCard(nodes: nodes)
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 14)
                }
            }
            .navigationTitle("Monitor de Nodo")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(GIATheme.panel, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(action: { viewModel.fetchData() }) {
                        Image(systemName: "arrow.clockwise")
                            .foregroundColor(GIATheme.teal)
                    }
                }
            }
        }
    }
    
    // MARK: - CPU & RAM Overview
    
    private var hardwareOverview: some View {
        HStack(spacing: 14) {
            // CPU Ring
            VStack(spacing: 8) {
                ZStack {
                    Circle()
                        .stroke(GIATheme.panelAlt, lineWidth: 8)
                        .frame(width: 70, height: 70)
                    
                    Circle()
                        .trim(from: 0, to: CGFloat((viewModel.monitorData?.cpu ?? 0) / 100.0))
                        .stroke(GIATheme.teal, style: StrokeStyle(lineWidth: 8, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                        .frame(width: 70, height: 70)
                    
                    Text("\(Int(viewModel.monitorData?.cpu ?? 0))%")
                        .font(.system(size: 14, weight: .bold, design: .monospaced))
                        .foregroundColor(GIATheme.teal)
                }
                
                Text("CPU ANFITRIÓN")
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundColor(GIATheme.dim)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .giaGlassCard()
            
            // RAM Ring
            VStack(spacing: 8) {
                ZStack {
                    Circle()
                        .stroke(GIATheme.panelAlt, lineWidth: 8)
                        .frame(width: 70, height: 70)
                    
                    Circle()
                        .trim(from: 0, to: CGFloat((viewModel.monitorData?.ram_pct ?? 0) / 100.0))
                        .stroke(GIATheme.gold, style: StrokeStyle(lineWidth: 8, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                        .frame(width: 70, height: 70)
                    
                    Text("\(Int(viewModel.monitorData?.ram_pct ?? 0))%")
                        .font(.system(size: 14, weight: .bold, design: .monospaced))
                        .foregroundColor(GIATheme.gold)
                }
                
                Text("RAM (\(String(format: "%.1f", viewModel.monitorData?.ram_used_gb ?? 0))/\(String(format: "%.0f", viewModel.monitorData?.ram_total_gb ?? 0))GB)")
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundColor(GIATheme.dim)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .giaGlassCard()
        }
    }
    
    // MARK: - GPU Status Card
    
    private func gpuStatusCard(gpu: GPUStats) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: "cpu.fill")
                    .foregroundColor(GIATheme.teal)
                Text(gpu.name ?? "GPU Dedicada")
                    .font(.system(size: 12, weight: .bold, design: .monospaced))
                    .foregroundColor(GIATheme.txt)
                Spacer()
                if let temp = gpu.temp {
                    Text("\(Int(temp))°C")
                        .font(.system(size: 12, weight: .bold, design: .monospaced))
                        .foregroundColor(temp > 75 ? .red : GIATheme.teal)
                }
            }
            
            if let vramUsed = gpu.vram_used, let vramTotal = gpu.vram_total, vramTotal > 0 {
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("VRAM")
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(GIATheme.dim)
                        Spacer()
                        Text("\(Int(vramUsed)) / \(Int(vramTotal)) MB")
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(GIATheme.txt)
                    }
                    
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            RoundedRectangle(cornerRadius: 4)
                                .fill(GIATheme.panelAlt)
                                .frame(height: 6)
                            RoundedRectangle(cornerRadius: 4)
                                .fill(GIATheme.teal)
                                .frame(width: geo.size.width * CGFloat(vramUsed / vramTotal), height: 6)
                        }
                    }
                    .frame(height: 6)
                }
            }
        }
        .padding(14)
        .giaGlassCard()
    }
    
    // MARK: - Loaded Models Card
    
    private var loadedModelsCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: "cube.fill")
                    .foregroundColor(GIATheme.teal)
                Text("MODELOS CARGADOS EN MEMORIA (OLLAMA)")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundColor(GIATheme.dim)
            }
            
            if let models = viewModel.monitorData?.loaded_models, !models.isEmpty {
                VStack(spacing: 8) {
                    ForEach(models) { model in
                        HStack {
                            Circle()
                                .fill(GIATheme.teal)
                                .frame(width: 6, height: 6)
                            Text(model.name)
                                .font(.system(size: 12, weight: .medium, design: .monospaced))
                                .foregroundColor(GIATheme.txt)
                            Spacer()
                            Text(String(format: "%.1f GB", model.gb))
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundColor(GIATheme.gold)
                        }
                        .padding(8)
                        .background(GIATheme.panelAlt)
                        .cornerRadius(6)
                    }
                }
            } else {
                Text("Ningún modelo cargado en VRAM en este momento.")
                    .font(.system(size: 12))
                    .foregroundColor(GIATheme.dim)
                    .padding(.vertical, 4)
            }
        }
        .padding(14)
        .giaGlassCard()
    }
    
    // MARK: - Top Processes
    
    private var topProcessesCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("PROCESOS PRINCIPALES (RAM)")
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundColor(GIATheme.dim)
            
            if let procs = viewModel.monitorData?.top_procs {
                ForEach(procs) { proc in
                    HStack {
                        Text(proc.name)
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundColor(GIATheme.txt)
                            .lineLimit(1)
                        Spacer()
                        Text(String(format: "%.2f GB", proc.gb))
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(GIATheme.dim)
                    }
                    Divider().background(GIATheme.border)
                }
            }
        }
        .padding(14)
        .giaGlassCard()
    }
    
    // MARK: - Cluster Nodes Card
    
    private func clusterNodesCard(nodes: [ClusterNodeInfo]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: "network")
                    .foregroundColor(GIATheme.teal)
                Text("NODOS DEL CLUSTER")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundColor(GIATheme.dim)
            }
            
            ForEach(nodes) { node in
                HStack {
                    Circle()
                        .fill(node.ok ? Color.green : Color.red)
                        .frame(width: 6, height: 6)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(node.name)
                            .font(.system(size: 12, weight: .medium))
                            .foregroundColor(GIATheme.txt)
                        Text(node.url)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(GIATheme.dim)
                    }
                    Spacer()
                    if let lat = node.latency_ms {
                        Text("\(Int(lat))ms")
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(GIATheme.teal)
                    }
                }
                .padding(8)
                .background(GIATheme.panelAlt)
                .cornerRadius(6)
            }
        }
        .padding(14)
        .giaGlassCard()
    }
}
