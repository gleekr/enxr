import SwiftUI
import AVFoundation

struct DownloadView: View {
    @EnvironmentObject private var library: VideoLibrary
    @StateObject private var downloader = DownloadEngine()
    @StateObject private var enhancer   = EnhanceEngine()

    @State private var urlText: String = ""
    @State private var phase: Phase    = .idle
    @State private var probeInfo: VideoInfo?
    @State private var showEnhanceSheet = false
    @State private var downloadedURL: URL?
    @State private var errorMessage: String?

    enum Phase {
        case idle, downloading, probing, enhancing, done
    }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            VStack(spacing: 0) {
                header
                    .padding(.top, 60)
                    .padding(.bottom, 32)

                urlField

                if let err = errorMessage {
                    ErrorBanner(message: err) { errorMessage = nil }
                        .padding(.top, 12)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                Spacer()

                statusSection

                Spacer(minLength: 80)
            }
            .padding(.horizontal, 24)
        }
        .sheet(isPresented: $showEnhanceSheet) {
            if let info = probeInfo, let srcURL = downloadedURL {
                EnhanceSheet(info: info, sourceURL: srcURL,
                             enhancer: enhancer) { item in
                    library.add(item)
                    showEnhanceSheet = false
                    phase = .done
                    urlText = ""
                }
            }
        }
        .animation(.spring(duration: 0.3), value: phase)
        .animation(.spring(duration: 0.3), value: errorMessage)
    }

    // MARK: - Sub-views

    private var header: some View {
        VStack(spacing: 6) {
            Text("enxr")
                .font(.system(size: 38, weight: .black, design: .rounded))
                .foregroundColor(.white)
            Text("restore · sharpen · upscale")
                .font(.system(size: 13, weight: .medium))
                .foregroundColor(Color(white: 0.4))
                .kerning(1.2)
        }
    }

    private var urlField: some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                Image(systemName: "link")
                    .foregroundColor(Color(white: 0.4))
                    .font(.system(size: 16, weight: .medium))

                TextField("Paste URL or file path", text: $urlText)
                    .foregroundColor(.white)
                    .tint(.white)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    .onSubmit { startDownload() }

                if !urlText.isEmpty {
                    Button { urlText = "" } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundColor(Color(white: 0.35))
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(Color(white: 0.08))
                    .overlay(
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .stroke(urlText.isEmpty ? Color.clear : Color.white.opacity(0.15), lineWidth: 1)
                    )
            )

            // Paste + Go row
            HStack(spacing: 10) {
                Button(action: pasteFromClipboard) {
                    Label("Paste", systemImage: "doc.on.clipboard")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundColor(Color(white: 0.55))
                        .padding(.horizontal, 14)
                        .padding(.vertical, 9)
                        .background(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .fill(Color(white: 0.1))
                        )
                }
                .buttonStyle(.plain)

                Spacer()

                GoButton(enabled: canGo, action: startDownload)
            }
        }
    }

    private var statusSection: some View {
        Group {
            switch phase {
            case .idle:
                EmptyView()

            case .downloading:
                StatusCard(
                    icon: "arrow.down.circle",
                    title: downloader.statusText.isEmpty ? "Downloading..." : downloader.statusText,
                    progress: downloader.progress,
                    tint: .cyan
                )

            case .probing:
                StatusCard(icon: "waveform.badge.magnifyingglass",
                           title: "Analysing video...",
                           progress: nil, tint: .indigo)

            case .enhancing:
                StatusCard(
                    icon: "sparkles",
                    title: enhancer.stage.isEmpty ? "Processing..." : enhancer.stage,
                    progress: enhancer.progress,
                    tint: .purple
                )

            case .done:
                DoneCard()
            }
        }
    }

    // MARK: - Actions

    private var canGo: Bool {
        !urlText.trimmingCharacters(in: .whitespaces).isEmpty && phase == .idle
    }

    private func pasteFromClipboard() {
        if let str = UIPasteboard.general.string, !str.isEmpty {
            urlText = str
        }
    }

    private func startDownload() {
        let raw = urlText.trimmingCharacters(in: .whitespaces)
        guard !raw.isEmpty else { return }
        errorMessage = nil

        Task {
            do {
                if raw.hasPrefix("http://") || raw.hasPrefix("https://") {
                    // Remote URL
                    phase = .downloading
                    let downloaded = try await downloader.download(urlString: raw)
                    downloadedURL = downloaded
                } else {
                    // Local file
                    let local = URL(fileURLWithPath: (raw as NSString).expandingTildeInPath)
                    guard FileManager.default.fileExists(atPath: local.path) else {
                        throw EnxrError.downloadFailed("file not found: \(raw)")
                    }
                    downloadedURL = local
                }

                // Probe
                phase = .probing
                let info = try await ProbeEngine.probeWithAVFoundation(downloadedURL!)
                probeInfo = info

                // Show enhance sheet
                phase = .idle
                showEnhanceSheet = true

            } catch {
                phase = .idle
                errorMessage = error.localizedDescription
            }
        }
    }
}

// MARK: - Sub-components

struct GoButton: View {
    let enabled: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Text("Go")
                    .font(.system(size: 16, weight: .bold))
                Image(systemName: "arrow.right")
                    .font(.system(size: 14, weight: .bold))
            }
            .foregroundColor(enabled ? .black : Color(white: 0.3))
            .padding(.horizontal, 22)
            .padding(.vertical, 11)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(enabled ? Color.white : Color(white: 0.15))
            )
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .animation(.easeOut(duration: 0.2), value: enabled)
    }
}

struct StatusCard: View {
    let icon: String
    let title: String
    let progress: Double?   // nil = indeterminate
    let tint: Color

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: icon)
                .font(.system(size: 30, weight: .semibold))
                .foregroundColor(tint)

            Text(title)
                .font(.system(size: 14, weight: .medium))
                .foregroundColor(Color(white: 0.7))
                .multilineTextAlignment(.center)

            if let p = progress {
                ProgressBar(value: p, tint: tint)
                    .frame(height: 4)
            } else {
                IndeterminateBar(tint: tint)
                    .frame(height: 4)
            }
        }
        .padding(24)
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(Color(white: 0.07))
        )
    }
}

struct DoneCard: View {
    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 36))
                .foregroundColor(.green)
            Text("Saved to library")
                .font(.system(size: 15, weight: .semibold))
                .foregroundColor(Color(white: 0.8))
        }
        .padding(28)
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(Color(white: 0.07))
        )
    }
}

struct ErrorBanner: View {
    let message: String
    let dismiss: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundColor(.orange)
            Text(message)
                .font(.system(size: 13))
                .foregroundColor(Color(white: 0.85))
                .lineLimit(3)
            Spacer()
            Button(action: dismiss) {
                Image(systemName: "xmark")
                    .foregroundColor(Color(white: 0.4))
                    .font(.system(size: 12, weight: .bold))
            }
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color.orange.opacity(0.12))
        )
    }
}

struct ProgressBar: View {
    let value: Double
    let tint: Color

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 2)
                    .fill(Color(white: 0.15))
                RoundedRectangle(cornerRadius: 2)
                    .fill(tint)
                    .frame(width: geo.size.width * max(0, min(1, value)))
                    .animation(.linear(duration: 0.3), value: value)
            }
        }
    }
}

struct IndeterminateBar: View {
    let tint: Color
    @State private var offset: CGFloat = -1

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 2)
                    .fill(Color(white: 0.15))
                RoundedRectangle(cornerRadius: 2)
                    .fill(tint)
                    .frame(width: geo.size.width * 0.35)
                    .offset(x: geo.size.width * (offset + 0.5))
            }
            .clipped()
        }
        .onAppear {
            withAnimation(.linear(duration: 1.2).repeatForever(autoreverses: false)) {
                offset = 1.35
            }
        }
    }
}
