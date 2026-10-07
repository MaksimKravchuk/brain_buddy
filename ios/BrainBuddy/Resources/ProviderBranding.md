The sign-in controls follow the approved provider-asset requirement in
`specs/023-modern-auth/design.md`.

- `GoogleSignInLogo.imageset`: 20pt rasterizations at 1x/2x/3x of the original
  gradient G in `frontend/src/assets/auth/google.svg`, copied unmodified from
  [SVGL](https://github.com/pheralb/svgl/blob/main/static/library/google.svg).
  Rasterization preserves its colors and aspect ratio, with transparent padding.
- `GoogleSans-Medium.ttf`: the static Latin 500 face from
  `@fontsource/google-sans` 5.3.1, converted from WOFF to native TrueType without
  changing glyphs or metrics. PostScript name: `GoogleSans-Medium`.
  Its SIL Open Font License is preserved in `GoogleSans-OFL.txt`.
- Google uses nominal 14pt Google Sans Medium, a 20pt line box, a 20pt original
  G, and the native 16/12/16pt spacing in the
  [Google Identity branding guidelines](https://developers.google.com/identity/branding-guidelines).
  Dynamic Type expands the label and control height instead of truncating it.
- Apple uses the system
  [ASAuthorizationAppleIDButton](https://developer.apple.com/documentation/authenticationservices/asauthorizationappleidbutton)
  with `.signIn` and `.black`. Its UIKit action starts the existing backend
  attempt before `ModernAuthCoordinator` presents Apple's authorization flow.

Provider trademarks remain owned by Google and Apple. Assets and font are
bundled; displaying the controls makes no third-party network request.
