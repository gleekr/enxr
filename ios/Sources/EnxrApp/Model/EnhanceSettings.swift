import Foundation

// MARK: - Denoise presets (mirrors config.py DENOISE)
enum DenoisePreset: String, CaseIterable, Identifiable, Codable {
    case slow      = "slow"
    case med       = "med"
    case fast      = "fast"
    case very_fast = "very_fast"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .slow:      return "Slow (best)"
        case .med:       return "Balanced"
        case .fast:      return "Fast"
        case .very_fast: return "Off"
        }
    }

    var subtitle: String {
        switch self {
        case .slow:      return "nlmeans full strength"
        case .med:       return "~1x realtime"
        case .fast:      return "light, for clean clips"
        case .very_fast: return "batch / no denoise"
        }
    }

    // FFmpeg filter fragments (mirrors config.py DENOISE dict)
    var filters: [String] {
        switch self {
        case .slow:      return ["nlmeans=s=4:p=9:r=18"]
        case .med:       return ["nlmeans=s=2:p=6:r=12"]
        case .fast:      return ["nlmeans=s=1:p=4:r=8"]
        case .very_fast: return []
        }
    }

    // CRF + x264 preset pairing (mirrors _encoder_args)
    var x264Preset: String {
        switch self {
        case .slow:      return "slow"
        case .med:       return "medium"
        case .fast:      return "fast"
        case .very_fast: return "ultrafast"
        }
    }

    var crf: Int {
        switch self {
        case .slow:      return 22
        case .med:       return 23
        case .fast:      return 26
        case .very_fast: return 28
        }
    }
}

// MARK: - Enhance (sharpen) level (mirrors config.py SHARPEN)
struct EnhanceLevel {
    let value: Int   // 0-5

    init(_ v: Int) { value = max(0, min(5, v)) }

    var label: String {
        ["None", "Subtle", "Light", "Standard", "Strong", "Max"][value]
    }

    // FFmpeg unsharp filter (mirrors config.py SHARPEN dict)
    var filters: [String] {
        let strengths: [Double] = [0, 0.4, 0.6, 0.85, 1.1, 1.4]
        guard value > 0 else { return [] }
        let la = strengths[value]
        return ["unsharp=lx=5:ly=5:la=\(la):cx=5:cy=5:ca=0.0"]
    }
}

// MARK: - Complete enhancement job settings
struct EnhanceSettings {
    var targetRes: Int           // short-side px
    var denoise: DenoisePreset
    var enhance: EnhanceLevel
    var isPortrait: Bool

    // Builds the FFmpeg -vf filter chain (mirrors config.py build_chain)
    func filterChain(sourceShortSide: Int) -> String {
        let doScale = targetRes > sourceShortSide
        var parts: [String] = ["format=yuv420p"]
        parts += denoise.filters
        parts += enhance.filters
        if doScale {
            if isPortrait {
                parts.append("zscale=w=\(targetRes):h=-2:filter=lanczos:dither=error_diffusion")
            } else {
                parts.append("zscale=w=-2:h=\(targetRes):filter=lanczos:dither=error_diffusion")
            }
        }
        parts.append("format=yuv420p")
        return parts.joined(separator: ",")
    }
}
