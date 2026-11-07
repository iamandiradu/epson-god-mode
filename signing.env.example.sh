# Copy to signing.env.sh (git-ignored); build_mac.command loads it.
# Requires an Apple Developer Program membership and a "Developer ID Application" certificate in your keychain.
# export EGM_MAC_SIGN_IDENTITY="Developer ID Application: Radu Iamandi (TEAMID1234)"
# One-time notarization credentials:
#   xcrun notarytool store-credentials egm-notary --apple-id you@example.com --team-id TEAMID1234 --password <app-specific-password>
# export EGM_NOTARY_PROFILE="egm-notary"
