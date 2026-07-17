// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MacAddressVendorKit",
    platforms: [.iOS(.v15), .macOS(.v12)],
    products: [
        .library(name: "MacAddressVendorKit", targets: ["MacAddressVendorKit"]),
    ],
    targets: [
        .target(
            name: "MacAddressVendorKit",
            resources: [.process("Data")],
            linkerSettings: [.linkedLibrary("sqlite3")]
        ),
        .testTarget(
            name: "MacAddressVendorKitTests",
            dependencies: ["MacAddressVendorKit"]
        ),
    ]
)
