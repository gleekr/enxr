import SwiftUI
import AVKit

struct LibraryView: View {
    @EnvironmentObject private var library: VideoLibrary
    @State private var selectedItem: VideoItem?
    @State private var shareItem: VideoItem?
    @State private var deleteItem: VideoItem?

    private let columns = [GridItem(.flexible()), GridItem(.flexible())]

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            if library.items.isEmpty {
                emptyState
            } else {
                ScrollView {
                    LazyVGrid(columns: columns, spacing: 12) {
                        ForEach(library.items) { item in
                            VideoCard(item: item)
                                .onTapGesture { selectedItem = item }
                                .contextMenu {
                                    Button {
                                        shareItem = item
                                    } label: {
                                        Label("Share", systemImage: "square.and.arrow.up")
                                    }
                                    Button(role: .destructive) {
                                        deleteItem = item
                                    } label: {
                                        Label("Delete", systemImage: "trash")
                                    }
                                }
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 60)
                    .padding(.bottom, 100)
                }
            }
        }
        .fullScreenCover(item: $selectedItem) { item in
            PlayerView(url: item.fileURL)
        }
        .sheet(item: $shareItem) { item in
            ShareSheet(url: item.fileURL)
        }
        .confirmationDialog("Delete this video?", isPresented: .constant(deleteItem != nil),
                            titleVisibility: .visible) {
            Button("Delete", role: .destructive) {
                if let item = deleteItem { library.remove(item) }
                deleteItem = nil
            }
            Button("Cancel", role: .cancel) { deleteItem = nil }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            Image(systemName: "film.stack")
                .font(.system(size: 48))
                .foregroundColor(Color(white: 0.2))
            Text("No videos yet")
                .font(.system(size: 18, weight: .semibold))
                .foregroundColor(Color(white: 0.35))
            Text("Download and enhance a video\nto see it here.")
                .font(.system(size: 14))
                .foregroundColor(Color(white: 0.25))
                .multilineTextAlignment(.center)
        }
    }
}

// MARK: - Video thumbnail card

struct VideoCard: View {
    let item: VideoItem
    @State private var thumbnail: UIImage?

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            // Thumbnail
            Group {
                if let thumb = thumbnail {
                    Image(uiImage: thumb)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                } else {
                    Color(white: 0.1)
                        .overlay(
                            Image(systemName: "film")
                                .font(.system(size: 28))
                                .foregroundColor(Color(white: 0.2))
                        )
                }
            }
            .frame(maxWidth: .infinity)
            .aspectRatio(9/16, contentMode: .fit)
            .clipped()

            // Overlay gradient + info
            LinearGradient(
                colors: [.clear, Color.black.opacity(0.75)],
                startPoint: .center, endPoint: .bottom
            )

            VStack(alignment: .leading, spacing: 2) {
                Text("\(item.resolution)p")
                    .font(.system(size: 12, weight: .bold, design: .monospaced))
                    .foregroundColor(.white)
                Text(item.formattedDuration)
                    .font(.system(size: 11))
                    .foregroundColor(Color(white: 0.6))
            }
            .padding(10)
        }
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .onAppear(perform: loadThumbnail)
    }

    private func loadThumbnail() {
        guard thumbnail == nil else { return }
        let url = item.fileURL
        Task.detached(priority: .background) {
            let asset    = AVURLAsset(url: url)
            let gen      = AVAssetImageGenerator(asset: asset)
            gen.appliesPreferredTrackTransform = true
            gen.maximumSize = CGSize(width: 400, height: 400)
            let t = CMTime(seconds: min(1.0, asset.duration.seconds * 0.1), preferredTimescale: 600)
            if let cgImage = try? gen.copyCGImage(at: t, actualTime: nil) {
                let img = UIImage(cgImage: cgImage)
                await MainActor.run { thumbnail = img }
            }
        }
    }
}

// MARK: - Player

struct PlayerView: View {
    let url: URL
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Color.black.ignoresSafeArea()
            VideoPlayer(player: AVPlayer(url: url))
                .ignoresSafeArea()
            Button { dismiss() } label: {
                Image(systemName: "xmark.circle.fill")
                    .font(.system(size: 28))
                    .foregroundStyle(.white, Color(white: 0.2))
                    .padding(20)
            }
        }
    }
}

// MARK: - Share sheet

struct ShareSheet: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }

    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
