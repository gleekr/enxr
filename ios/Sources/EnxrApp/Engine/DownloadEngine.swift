import Foundation
import YoutubeDL

// Wraps YoutubeDL-iOS (yt-dlp Python module via PythonKit).
// Mirrors downloader.py download() — tries multiple player clients.
@MainActor
final class DownloadEngine: ObservableObject {
    @Published var progress: Double = 0     // 0.0 – 1.0
    @Published var statusText: String = ""
    @Published var isDownloading: Bool = false

    private var ytdl: YoutubeDL?

    func download(urlString: String, format: DownloadFormat = .mp4) async throws -> URL {
        guard let url = URL(string: urlString) else {
            throw EnxrError.downloadFailed("invalid URL")
        }

        isDownloading = true
        progress      = 0
        statusText    = "Initialising downloader..."
        defer { isDownloading = false }

        let downloader = try await makeDownloader()
        let destDir    = VideoLibrary.ogDirectory

        statusText = "Fetching video info..."

        let outputURL = try await downloader.download(url, to: destDir) { [weak self] p in
            Task { @MainActor [weak self] in
                self?.progress   = p.fractionCompleted
                self?.statusText = p.localizedDescription
            }
        }

        statusText = "Download complete"
        return outputURL
    }

    // MARK: - Private

    private func makeDownloader() async throws -> YoutubeDL {
        if let existing = ytdl { return existing }
        statusText = "Loading yt-dlp module..."
        let dl = try await YoutubeDL()
        ytdl = dl
        return dl
    }
}

enum DownloadFormat: String, CaseIterable, Identifiable {
    case mp4  = "mp4"
    case webm = "webm"
    var id: String { rawValue }
    var label: String { rawValue.uppercased() }
}
