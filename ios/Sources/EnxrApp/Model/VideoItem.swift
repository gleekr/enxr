import Foundation
import AVKit

struct VideoItem: Identifiable, Codable {
    let id: UUID
    let filename: String
    let originalURL: String?
    let createdAt: Date
    var resolution: Int        // short side in px
    var fileSize: Int64        // bytes
    var duration: Double       // seconds

    init(filename: String, originalURL: String? = nil,
         resolution: Int = 0, fileSize: Int64 = 0, duration: Double = 0) {
        self.id          = UUID()
        self.filename    = filename
        self.originalURL = originalURL
        self.createdAt   = Date()
        self.resolution  = resolution
        self.fileSize    = fileSize
        self.duration    = duration
    }

    var fileURL: URL {
        VideoLibrary.hdDirectory.appendingPathComponent(filename)
    }

    var formattedSize: String {
        ByteCountFormatter.string(fromByteCount: fileSize, countStyle: .file)
    }

    var formattedDuration: String {
        let m = Int(duration) / 60
        let s = Int(duration) % 60
        return m > 0 ? "\(m)m \(s)s" : "\(s)s"
    }
}

// MARK: - Quality tier (mirrors Python _detect_tier)
enum QualityTier: Int {
    case excellent = 1, good, fair, poor, broken

    var label: String {
        switch self {
        case .excellent: return "Excellent"
        case .good:      return "Good"
        case .fair:      return "Fair"
        case .poor:      return "Poor"
        case .broken:    return "Broken"
        }
    }

    var color: String {
        switch self {
        case .excellent: return "green"
        case .good:      return "cyan"
        case .fair:      return "yellow"
        case .poor:      return "orange"
        case .broken:    return "red"
        }
    }

    static func detect(bitrate: Double, width: Int, height: Int) -> QualityTier {
        guard bitrate > 0 else { return .fair }
        let normKbps = (bitrate / 1000) * Double(1920 * 1080) / Double(width * height)
        switch normKbps {
        case 5000...: return .excellent
        case 2500...: return .good
        case 1000...: return .fair
        case 400...:  return .poor
        default:      return .broken
        }
    }
}

// MARK: - Video probe result
struct VideoInfo {
    let width: Int
    let height: Int
    let codec: String
    let bitrate: Double   // bps
    let duration: Double  // seconds

    var isPortrait: Bool { height > width }
    var shortSide: Int   { min(width, height) }
    var tier: QualityTier { .detect(bitrate: bitrate, width: width, height: height) }

    // Upscale ceiling ladder (mirrors config.py SOURCE_CEILING)
    static let ceilingMap: [Int: Int] = [360: 480, 480: 720, 720: 1080, 1080: 1440, 1440: 0]
    static let standardSizes = [360, 480, 720, 1080, 1440]

    var snapShortSide: Int {
        VideoInfo.standardSizes.min(by: { abs($0 - shortSide) < abs($1 - shortSide) }) ?? shortSide
    }

    var ceiling: Int {
        guard shortSide < 1440 else { return 0 }
        return VideoInfo.ceilingMap[snapShortSide] ?? 0
    }

    var upscaleOptions: [Int] {
        guard ceiling > 0 else { return [shortSide] }
        return VideoInfo.standardSizes.filter { shortSide < $0 && $0 <= ceiling }
    }

    var suggestedTarget: Int {
        upscaleOptions.last ?? shortSide
    }

    // Suggested denoise preset from tier (mirrors Python tier_to_preset)
    var suggestedDenoise: DenoisePreset {
        switch tier {
        case .excellent, .good: return .fast
        case .fair:             return .med
        case .poor, .broken:    return .slow
        }
    }
}
