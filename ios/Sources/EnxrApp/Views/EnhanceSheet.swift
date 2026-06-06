import SwiftUI
import AVFoundation

// Bottom sheet: resolution / denoise / enhance pickers → runs FFmpeg in-process.
// Mirrors the 3-prompt step machine in enxr.py action_enhance_file().
struct EnhanceSheet: View {
    let info: VideoInfo
    let sourceURL: URL
    @ObservedObject var enhancer: EnhanceEngine
    let onComplete: (VideoItem) -> Void

    @State private var targetRes: Int
    @State private var denoise: DenoisePreset
    @State private var enhanceLevel: Int = 3
    @State private var isProcessing = false
    @State private var errorMessage: String?

    @Environment(\.dismiss) private var dismiss

    init(info: VideoInfo, sourceURL: URL, enhancer: EnhanceEngine,
         onComplete: @escaping (VideoItem) -> Void) {
        self.info       = info
        self.sourceURL  = sourceURL
        self.enhancer   = enhancer
        self.onComplete = onComplete
        _targetRes      = State(initialValue: info.suggestedTarget)
        _denoise        = State(initialValue: info.suggestedDenoise)
    }

    var body: some View {
        NavigationStack {
            ZStack {
                Color(white: 0.05).ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 24) {
                        videoInfoCard
                        resolutionPicker
                        denoisePicker
                        enhanceLevelPicker
                        actionButton
                            .padding(.bottom, 32)
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 8)
                }
            }
            .navigationTitle("Enhance")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                        .foregroundColor(Color(white: 0.5))
                        .disabled(isProcessing)
                }
            }
        }
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .preferredColorScheme(.dark)
    }

    // MARK: - Sections

    private var videoInfoCard: some View {
        HStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text("\(info.width) × \(info.height)")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(.white)
                Text("\(info.shortSide)p \(info.isPortrait ? "portrait" : "landscape")")
                    .font(.system(size: 12))
                    .foregroundColor(Color(white: 0.45))
            }
            Spacer()
            TierBadge(tier: info.tier)
        }
        .padding(16)
        .background(card)
    }

    private var resolutionPicker: some View {
        SectionCard(title: "1. Resolution") {
            VStack(spacing: 0) {
                // Source (no upscale) option
                ResOption(label: "Source \(info.shortSide)p", subtitle: "no upscale",
                          selected: targetRes == info.shortSide) {
                    targetRes = info.shortSide
                }
                ForEach(info.upscaleOptions, id: \.self) { res in
                    Divider().background(Color(white: 0.12))
                    ResOption(label: "\(res)p",
                              subtitle: res == info.suggestedTarget ? "recommended" : nil,
                              selected: targetRes == res) {
                        targetRes = res
                    }
                }
            }
        }
    }

    private var denoisePicker: some View {
        SectionCard(title: "2. Denoise") {
            VStack(spacing: 0) {
                ForEach(Array(DenoisePreset.allCases.enumerated()), id: \.offset) { i, preset in
                    if i > 0 { Divider().background(Color(white: 0.12)) }
                    PresetRow(label: preset.label, subtitle: preset.subtitle,
                              selected: denoise == preset,
                              recommended: preset == info.suggestedDenoise) {
                        denoise = preset
                    }
                }
            }
        }
    }

    private var enhanceLevelPicker: some View {
        SectionCard(title: "3. Enhance (sharpen)") {
            VStack(spacing: 12) {
                HStack {
                    Text(EnhanceLevel(enhanceLevel).label)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.white)
                    Spacer()
                    Text("Level \(enhanceLevel)")
                        .font(.system(size: 12))
                        .foregroundColor(Color(white: 0.4))
                }

                Slider(value: Binding(
                    get: { Double(enhanceLevel) },
                    set: { enhanceLevel = Int($0.rounded()) }
                ), in: 0...5, step: 1)
                .tint(.white)

                HStack {
                    Text("None").font(.system(size: 11)).foregroundColor(Color(white: 0.35))
                    Spacer()
                    Text("Max").font(.system(size: 11)).foregroundColor(Color(white: 0.35))
                }
            }
            .padding(.vertical, 4)
        }
    }

    private var actionButton: some View {
        Group {
            if isProcessing {
                VStack(spacing: 16) {
                    ProgressView(value: enhancer.progress)
                        .tint(.purple)

                    Text(enhancer.stage)
                        .font(.system(size: 13))
                        .foregroundColor(Color(white: 0.5))

                    if enhancer.progress > 0 {
                        Text("\(Int(enhancer.progress * 100))%")
                            .font(.system(size: 22, weight: .bold, design: .monospaced))
                            .foregroundColor(.white)
                    }
                }
                .padding(20)
                .background(card)
            } else {
                VStack(spacing: 12) {
                    if let err = errorMessage {
                        Text(err)
                            .font(.system(size: 13))
                            .foregroundColor(.red)
                            .multilineTextAlignment(.center)
                    }

                    Button(action: startEnhance) {
                        HStack(spacing: 8) {
                            Image(systemName: "sparkles")
                            Text("Enhance Now")
                                .font(.system(size: 17, weight: .bold))
                        }
                        .foregroundColor(.black)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(
                            RoundedRectangle(cornerRadius: 14, style: .continuous)
                                .fill(Color.white)
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    // MARK: - Helpers

    private var card: some ShapeStyle {
        AnyShapeStyle(Color(white: 0.09))
    }

    private func startEnhance() {
        errorMessage = nil
        isProcessing = true

        let settings = EnhanceSettings(
            targetRes: targetRes,
            denoise: denoise,
            enhance: EnhanceLevel(enhanceLevel),
            isPortrait: info.isPortrait
        )

        Task {
            do {
                let outURL = try await enhancer.enhance(
                    input: sourceURL,
                    info: info,
                    settings: settings
                )

                let attrs    = try? FileManager.default.attributesOfItem(atPath: outURL.path)
                let fileSize = attrs?[.size] as? Int64 ?? 0

                let item = VideoItem(
                    filename: outURL.lastPathComponent,
                    originalURL: nil,
                    resolution: targetRes,
                    fileSize: fileSize,
                    duration: info.duration
                )

                UINotificationFeedbackGenerator().notificationOccurred(.success)
                onComplete(item)
            } catch {
                isProcessing = false
                errorMessage = error.localizedDescription
                UINotificationFeedbackGenerator().notificationOccurred(.error)
            }
        }
    }
}

// MARK: - Reusable row components

struct ResOption: View {
    let label: String
    let subtitle: String?
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(label)
                        .font(.system(size: 15, weight: selected ? .semibold : .regular))
                        .foregroundColor(selected ? .white : Color(white: 0.65))
                    if let sub = subtitle {
                        Text(sub)
                            .font(.system(size: 12))
                            .foregroundColor(Color(white: 0.35))
                    }
                }
                Spacer()
                if selected {
                    Image(systemName: "checkmark")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundColor(.white)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
        .buttonStyle(.plain)
    }
}

struct PresetRow: View {
    let label: String
    let subtitle: String
    let selected: Bool
    let recommended: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 6) {
                        Text(label)
                            .font(.system(size: 15, weight: selected ? .semibold : .regular))
                            .foregroundColor(selected ? .white : Color(white: 0.65))
                        if recommended {
                            Text("suggested")
                                .font(.system(size: 10, weight: .medium))
                                .foregroundColor(Color(white: 0.4))
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(
                                    Capsule().fill(Color(white: 0.15))
                                )
                        }
                    }
                    Text(subtitle)
                        .font(.system(size: 12))
                        .foregroundColor(Color(white: 0.35))
                }
                Spacer()
                if selected {
                    Image(systemName: "checkmark")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundColor(.white)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
        .buttonStyle(.plain)
    }
}

struct SectionCard<Content: View>: View {
    let title: String
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title)
                .font(.system(size: 12, weight: .semibold))
                .foregroundColor(Color(white: 0.4))
                .kerning(0.8)
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 8)

            content()
                .padding(.bottom, 8)
        }
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color(white: 0.09))
        )
    }
}

struct TierBadge: View {
    let tier: QualityTier

    var tintColor: Color {
        switch tier {
        case .excellent: return .green
        case .good:      return .cyan
        case .fair:      return .yellow
        case .poor:      return .orange
        case .broken:    return .red
        }
    }

    var body: some View {
        Text(tier.label)
            .font(.system(size: 11, weight: .semibold))
            .foregroundColor(tintColor)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(
                Capsule()
                    .fill(tintColor.opacity(0.15))
                    .overlay(Capsule().stroke(tintColor.opacity(0.3), lineWidth: 1))
            )
    }
}
