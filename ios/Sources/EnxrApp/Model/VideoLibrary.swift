import Foundation
import Combine

final class VideoLibrary: ObservableObject {
    @Published var items: [VideoItem] = []

    static let ogDirectory: URL = {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let dir = docs.appendingPathComponent("vids/og")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    static let hdDirectory: URL = {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let dir = docs.appendingPathComponent("vids/hd")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    private let persistURL: URL = {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("library.json")
    }()

    init() { load() }

    func add(_ item: VideoItem) {
        DispatchQueue.main.async {
            self.items.insert(item, at: 0)
            self.save()
        }
    }

    func remove(_ item: VideoItem) {
        try? FileManager.default.removeItem(at: item.fileURL)
        items.removeAll { $0.id == item.id }
        save()
    }

    private func save() {
        guard let data = try? JSONEncoder().encode(items) else { return }
        try? data.write(to: persistURL)
    }

    private func load() {
        guard let data = try? Data(contentsOf: persistURL),
              let decoded = try? JSONDecoder().decode([VideoItem].self, from: data) else { return }
        items = decoded.filter { FileManager.default.fileExists(atPath: $0.fileURL.path) }
    }
}
