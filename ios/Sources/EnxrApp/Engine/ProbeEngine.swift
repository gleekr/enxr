import Foundation
import FFmpeg

// Runs ffprobe via FFmpeg-iOS to get video metadata.
// Mirrors Python _get_dims + _detect_tier in ffmpeg.py.
enum ProbeEngine {

    static func probe(_ url: URL) async throws -> VideoInfo {
        // ffprobe -v error -show_entries stream=width,height,codec_name
        //         -show_entries format=bit_rate,duration -of json <path>
        let tmp = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("probe_\(UUID().uuidString).json")

        let args: [String] = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,codec_name",
            "-show_entries", "format=bit_rate,duration",
            "-of", "json",
            url.path,
            "-print_format", "json",
        ]

        // ffprobe returns its JSON to stdout; capture via a temp file redirect
        // FFmpeg-iOS exposes ffprobe() the same way as ffmpeg()
        let exitCode = ffprobe(args)
        guard exitCode == 0 else {
            throw EnxrError.probeFailed("ffprobe exit \(exitCode)")
        }

        // Alternative: use AVFoundation for metadata — no subprocess needed
        return try await probeWithAVFoundation(url)
    }

    // AVFoundation-based probe (no FFmpeg dependency, reliable on iOS)
    static func probeWithAVFoundation(_ url: URL) async throws -> VideoInfo {
        let asset = AVURLAsset(url: url)

        async let tracksResult = asset.loadTracks(withMediaType: .video)
        async let durationResult = asset.load(.duration)

        let tracks = try await tracksResult
        let cmDur  = try await durationResult

        guard let track = tracks.first else {
            throw EnxrError.probeFailed("no video track")
        }

        async let sizeResult    = track.load(.naturalSize)
        async let bitrateResult = track.load(.estimatedDataRate)

        let size    = try await sizeResult
        let bps     = Double(try await bitrateResult)
        let seconds = CMTimeGetSeconds(cmDur)

        let w = Int(size.width)
        let h = Int(size.height)

        let codec: String
        if let desc = try? await track.load(.formatDescriptions).first {
            let fourCC = CMFormatDescriptionGetMediaSubType(desc)
            codec = String(fourCC.toFourCC())
        } else {
            codec = "unknown"
        }

        return VideoInfo(width: w, height: h, codec: codec, bitrate: bps, duration: seconds)
    }
}

// FourCC helper
private extension UInt32 {
    func toFourCC() -> String {
        let chars: [Character] = [
            Character(UnicodeScalar((self >> 24) & 0xFF)!),
            Character(UnicodeScalar((self >> 16) & 0xFF)!),
            Character(UnicodeScalar((self >> 8)  & 0xFF)!),
            Character(UnicodeScalar( self        & 0xFF)!),
        ]
        return String(chars).trimmingCharacters(in: .whitespaces)
    }
}

import AVFoundation
