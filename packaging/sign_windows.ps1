<#
Signs dist\EpsonGodMode.exe and dist\egm.exe with signtool (Authenticode, SHA-256, RFC 3161 timestamp).

Pick ONE method by setting environment variables (build_exe.bat loads them from signing.env.bat):

  A) Certificate in the Windows certificate store (Certum SimplySign, USB token, any OV/EV cert):
       EGM_SIGN_THUMBPRINT = <SHA-1 thumbprint of the certificate>
  B) PFX file (only for certificates that are still allowed as files, e.g. self-signed for testing):
       EGM_SIGN_PFX = C:\path\cert.pfx      EGM_SIGN_PFX_PASSWORD = ...
  C) Azure Artifact Signing (formerly Trusted Signing):
       EGM_AZURE_ENDPOINT = https://weu.codesigning.azure.net
       EGM_AZURE_ACCOUNT  = <signing account name>
       EGM_AZURE_PROFILE  = <certificate profile name>
       (sign in first with:  az login)

Optional: EGM_SIGN_TIMESTAMP (default http://timestamp.digicert.com; Azure uses its own).
If no method is configured the script exits 0 and the build stays unsigned.
#>
param([string[]]$Files = @("dist\EpsonGodMode.exe", "dist\egm.exe"))
$ErrorActionPreference = "Stop"
$tools = Join-Path $PSScriptRoot "..\build\signtools"

function Get-NuGetPackage($id, $version) {
    $dir = Join-Path $tools "$id.$version"
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $zip = "$dir.zip"
        Write-Host "Downloading $id $version ..."
        Invoke-WebRequest -UseBasicParsing "https://www.nuget.org/api/v2/package/$id/$version" -OutFile $zip
        Expand-Archive -Force $zip $dir
        Remove-Item $zip
    }
    return $dir
}

function Find-SignTool {
    $sdk = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
           Sort-Object FullName -Descending | Select-Object -First 1
    if ($sdk) { return $sdk.FullName }
    # no Windows SDK installed: use the signtool from the SDK build-tools NuGet package
    $pkg = Get-NuGetPackage "Microsoft.Windows.SDK.BuildTools" "10.0.26100.1742"
    $st = Get-ChildItem "$pkg\bin\*\x64\signtool.exe" | Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $st) { throw "signtool.exe not found" }
    return $st.FullName
}

$thumb = $env:EGM_SIGN_THUMBPRINT
if ($thumb) { $thumb = ($thumb -replace "[^0-9A-Fa-f]", "") }  # copy-pasted thumbprints often contain spaces/invisible chars
$pfx = $env:EGM_SIGN_PFX
$azure = $env:EGM_AZURE_ENDPOINT
if (-not ($thumb -or $pfx -or $azure)) {
    Write-Host "Code signing: not configured (see signing.env.example.bat) - leaving the build unsigned."
    exit 0
}

$signtool = Find-SignTool
$ts = if ($env:EGM_SIGN_TIMESTAMP) { $env:EGM_SIGN_TIMESTAMP } else { "http://timestamp.digicert.com" }
$desc = @("/d", "Epson God Mode")

foreach ($f in $Files) {
    if (-not (Test-Path $f)) { throw "missing $f - build first" }
    Write-Host "Signing $f"
    if ($azure) {
        $client = Get-NuGetPackage "Microsoft.Trusted.Signing.Client" "1.0.86"
        $dlib = Get-ChildItem "$client\bin\x64\Azure.CodeSigning.Dlib.dll" | Select-Object -First 1
        $meta = Join-Path $tools "artifact-signing.json"
        @{ Endpoint = $azure; CodeSigningAccountName = $env:EGM_AZURE_ACCOUNT;
           CertificateProfileName = $env:EGM_AZURE_PROFILE } | ConvertTo-Json | Set-Content -Encoding UTF8 $meta
        & $signtool sign /v /fd SHA256 /tr "http://timestamp.acs.microsoft.com" /td SHA256 `
            /dlib $dlib.FullName /dmdf $meta @desc $f
    } elseif ($thumb) {
        & $signtool sign /v /fd SHA256 /tr $ts /td SHA256 /sha1 $thumb @desc $f
    } else {
        & $signtool sign /v /fd SHA256 /tr $ts /td SHA256 /f $pfx /p $env:EGM_SIGN_PFX_PASSWORD @desc $f
    }
    if ($LASTEXITCODE -ne 0) { throw "signing $f failed (exit $LASTEXITCODE)" }
    & $signtool verify /pa /v $f | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "signature verification failed for $f" }
}
Write-Host "Code signing: OK"
