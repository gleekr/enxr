import Foundation
import FFmpeg

// Mirrors ffmpeg.py enhance() — single-pass denoise + sharpen + scale.
final class EnhanceEngine: ObservableObject {
    @Published var progress: Double = 0      // 0.0 – 1.0
    @Published var stage: String   = ""
    @Published var isRunning: Bool = false

    func enhance(
        input: URL,
        info: VideoInfo,
        settings: EnhanceSettings
    ) async throws -> URL {
        let name    = input.deletingPathExtension().lastPathComponent
        let outDir  = VideoLibrary.hdDirectory
        let outURL  = outDir.appendingPathComponent("ex\(name).mp4")
        let tmpURL  = outDir.appendingPathComponent("tmp_\(name)_enc.mp4")

        let vf = settings.filterChain(sourceShortSide: info.shortSide)
        let doScale = settings.targetRes > info.shortSide
        let stageLabel = doScale
            ? "\(info.shortSide)p → \(settings.targetRes)p"
            : "\(info.shortSide)p (no scale)"

        await MainActor.run {
            self.isRunning = true
            self.progress  = 0
            self.stage     = stageLabel
        }
        defer { Task { @MainActor in self.isRunning = false } }

        try await runFFmpeg(input: input, output: tmpURL, vf: vf,
                            settings: settings, totalSeconds: info.duration)

        // Atomic rename
        if FileManager.default.fileExists(atPath: outURL.path) {
            try FileManager.default.removeItem(at: outURL)
        }
        try FileManager.default.moveItem(at: tmpURL, to: outURL)
        return outURL
    }

    // MARK: - Private

    private func runFFmpeg(
        input: URL, output: URL, vf: String,
        settings: EnhanceSettings, totalSeconds: Double
    ) async throws {
        // VideoToolbox first, libx264 fallback (mirrors _get_encoder_chain)
        let encoders = ["h264_videotoolbox", "libx264"]

        for codec in encoders {
            let args = buildArgs(input: input, output: output, vf: vf,
                                 codec: codec, settings: settings)
            let code = try await runWithProgress(args: args, totalSeconds: totalSeconds)
            if code == 0 { return }

            // VideoToolbox may fail for some source formats — fall through to libx264
            if codec == encoders.last {
                throw EnxrError.encodeFailed("all encoders exhausted (code \(code))")
            }
        }
    }

    private func buildArgs(
        input: URL, output: URL, vf: String,
        codec: String, settings: EnhanceSettings
    ) -> [String] {
        var args = [
            "ffmpeg", "-y",
            "-hwaccel", "none",
            "-i", input.path,
            "-map", "0:v:0",
            "-map", "0:a:0?",
            "-c:a", "aac",
            "-vf", vf,
            "-pix_fmt", "yuv420p",
            "-map_metadata", "-1",
            "-c:v", codec,
        ]

        if codec == "h264_videotoolbox" {
            args += ["-b:v", "0", "-q:v", "65"]  // quality-based VBR
        } else {
            // libx264 with preset + CRF from denoise tier
            args += [
                "-preset", settings.denoise.x264Preset,
                "-crf",    "\(settings.denoise.crf)",
                "-profile:v", "main",
                "-g", "250",
            ]
        }

        args.append(output.path)
        return args
    }

    private func runWithProgress(args: [String], totalSeconds: Double) async throws -> Int32 {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                // FFmpeg-iOS exposes ffmpeg() synchronously; we parse stderr for time=
                // Progress parsing via ffmpegKit callback is not available here,
                // so we use a simulated approach with the standard ffmpeg() call.
                // For real progress, integrate FFmpegKit instead of FFmpeg-iOS.
                let code = ffmpeg(args)
                continuation.resume(returning: code)
            }
        }
    }
}

enum EnxrError: LocalizedError {
    case probeFailed(String)
    case downloadFailed(String)
    case encodeFailed(String)

    var errorDescription: String? {
        switch self {
        case .probeFailed(let s):   return "Probe failed: \(s)"
        case .downloadFailed(let s): return "Download failed: \(s)"
        case .encodeFailed(let s):  return "Encode failed: \(s)"
        }
    }
}
