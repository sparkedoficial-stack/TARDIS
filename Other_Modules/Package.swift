// swift-tools-version: 5.9
// The swift-tools-version declares the minimum version of Swift required to build this package.

import PackageDescription

let package = Package(
    name: "GIA",
    defaultLocalization: "es",
    platforms: [
        .iOS(.v16)
    ],
    products: [
        .library(
            name: "GIA",
            targets: ["GIA"]
        ),
    ],
    dependencies: [],
    targets: [
        .target(
            name: "GIA",
            dependencies: [],
            path: "GIA"
        ),
    ]
)
