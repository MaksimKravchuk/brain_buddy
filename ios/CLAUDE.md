@AGENTS.md

## iOS (SwiftUI, iOS 26)

- Without Xcode (Linux, cloud sessions), verify package work with
  `sh ios/scripts/swift-linux.sh test` and leave the app build to
  `.github/workflows/ios.yml`; on a Mac, also run the `xcodebuild` command
  in `AGENTS.md`.
- Edit `ios/project.yml`, never the generated `.xcodeproj`, Info.plists or
  entitlements. `README.md` covers signing, TestFlight and the offline QA pass.
