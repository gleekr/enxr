// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "EnxrApp",
    platforms: [
        .iOS(.v16),
    ],
    products: [
        .library(name: "EnxrApp", targets: ["EnxrApp"]),
    ],
    dependencies: [
        .package(url: "https://github.com/kewlbear/FFmpeg-iOS.git", from: "0.1.0"),
        .package(url: "https://github.com/kewlbear/YoutubeDL-iOS.git", from: "0.1.0"),
        .package(url: "https://github.com/kewlbear/Python-iOS.git", from: "0.1.0"),
    ],
    targets: [
        .target(
            name: "EnxrApp",
            dependencies: [
                .product(name: "FFmpeg", package: "FFmpeg-iOS"),
                .product(name: "YoutubeDL", package: "YoutubeDL-iOS"),
                .product(name: "Python", package: "Python-iOS"),
            ]
        ),
    ]
)
