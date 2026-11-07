@echo off
REM Copy this file to signing.env.bat (which is git-ignored) and fill in ONE method.
REM build_exe.bat loads it and signs dist\EpsonGodMode.exe and dist\egm.exe.

REM A) Certificate in the Windows store (Certum SimplySign: keep SimplySign Desktop logged in)
REM    Find the thumbprint: certmgr.msc > Personal > Certificates > your cert > Details > Thumbprint
REM set EGM_SIGN_THUMBPRINT=0123456789ABCDEF0123456789ABCDEF01234567
REM set EGM_SIGN_TIMESTAMP=http://time.certum.pl

REM B) PFX file (testing / self-signed only)
REM set EGM_SIGN_PFX=C:\certs\test.pfx
REM set EGM_SIGN_PFX_PASSWORD=secret

REM C) Azure Artifact Signing (run "az login" first)
REM set EGM_AZURE_ENDPOINT=https://weu.codesigning.azure.net
REM set EGM_AZURE_ACCOUNT=my-signing-account
REM set EGM_AZURE_PROFILE=my-cert-profile
