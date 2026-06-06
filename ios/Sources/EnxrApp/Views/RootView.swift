import SwiftUI

struct RootView: View {
    @State private var selectedTab: Tab = .download

    enum Tab { case download, library }

    var body: some View {
        ZStack(alignment: .bottom) {
            Color.black.ignoresSafeArea()

            Group {
                switch selectedTab {
                case .download: DownloadView()
                case .library:  LibraryView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            BottomBar(selected: $selectedTab)
        }
    }
}

// MARK: - Minimal bottom tab bar
struct BottomBar: View {
    @Binding var selected: RootView.Tab

    var body: some View {
        HStack(spacing: 0) {
            TabButton(icon: "arrow.down.circle.fill", label: "Download",
                      active: selected == .download) { selected = .download }
            TabButton(icon: "film.stack", label: "Library",
                      active: selected == .library)  { selected = .library }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
        .background(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(.ultraThinMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: 24, style: .continuous)
                        .stroke(Color.white.opacity(0.08), lineWidth: 1)
                )
        )
        .padding(.horizontal, 32)
        .padding(.bottom, 8)
    }
}

struct TabButton: View {
    let icon: String
    let label: String
    let active: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 22, weight: .semibold))
                Text(label)
                    .font(.system(size: 11, weight: .medium))
            }
            .foregroundColor(active ? .white : Color(white: 0.45))
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
    }
}
