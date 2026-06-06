import SwiftUI

@main
struct EnxrApp: App {
    @StateObject private var library = VideoLibrary()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(library)
                .preferredColorScheme(.dark)
        }
    }
}
