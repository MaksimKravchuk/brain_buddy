[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+$')][string]$Version,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'BrainBuddy\bin')
)
$ErrorActionPreference = 'Stop'
$stage = $null
$oldTls = [Net.ServicePointManager]::SecurityProtocol
try {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Windows x64 is required' }
    $architecture = $env:PROCESSOR_ARCHITEW6432
    if (!$architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
    if ($architecture -ne 'AMD64') { throw 'Windows ARM64 and x86 are unsupported' }
    if ($Version.Length -gt 24) { throw 'Invalid version' }
    $InstallDir = [IO.Path]::GetFullPath($InstallDir)
    $component = $InstallDir
    while ($component) {
        if (Test-Path -LiteralPath $component) {
            if ((Get-Item -LiteralPath $component -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Destination contains a symlink or junction' }
        }
        $component = [IO.Path]::GetDirectoryName($component)
    }
    [IO.Directory]::CreateDirectory($InstallDir) | Out-Null
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $acl = Get-Acl -LiteralPath $InstallDir
    $owner = (New-Object Security.Principal.NTAccount($acl.Owner)).Translate([Security.Principal.SecurityIdentifier]).Value
    if ($owner -ne $identity.User.Value) { throw 'Destination must be owned by the current user' }
    $trusted = @($identity.User.Value, 'S-1-5-18', 'S-1-5-32-544')
    $writeRights = [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership
    foreach ($rule in $acl.Access) {
        $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        if ($rule.AccessControlType -eq 'Allow' -and ($rule.FileSystemRights -band $writeRights) -and $sid -notin $trusted) { throw 'Destination permits another user to modify installed binaries' }
    }
    $destination = Join-Path $InstallDir 'bb.exe'
    if (Test-Path -LiteralPath $destination) {
        $existing = Get-Item -LiteralPath $destination -Force
        if ($existing.PSIsContainer -or ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Existing bb.exe is not a regular file' }
    }
    $stage = Join-Path $InstallDir ('.bb-install-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($stage) | Out-Null
    Add-Type -AssemblyName System.Net.Http
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    function Download-ReleaseFile([string]$Name, [long]$Limit) {
        $uri = [Uri]("https://github.com/MaksimKravchuk/brain_buddy/releases/download/bb-v$Version/$Name")
        $handler = New-Object Net.Http.HttpClientHandler
        $handler.AllowAutoRedirect = $false
        $handler.UseDefaultCredentials = $false
        $client = New-Object Net.Http.HttpClient($handler)
        $client.Timeout = [TimeSpan]::FromSeconds(120)
        $client.DefaultRequestHeaders.UserAgent.ParseAdd('BrainBuddyInstaller/0.1')
        $cancel = New-Object Threading.CancellationTokenSource
        $cancel.CancelAfter(120000)
        try {
            for ($redirects = 0; $redirects -le 10; $redirects++) {
                if ($uri.Scheme -ne 'https' -or $uri.UserInfo) { throw 'HTTPS-only download required' }
                $response = $client.GetAsync($uri, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $cancel.Token).GetAwaiter().GetResult()
                try {
                    if ([int]$response.StatusCode -in @(301,302,303,307,308)) {
                        if (!$response.Headers.Location) { throw 'Invalid redirect' }
                        $uri = New-Object Uri($uri,$response.Headers.Location)
                        continue
                    }
                    $response.EnsureSuccessStatusCode() | Out-Null
                    if ($response.Content.Headers.ContentLength -gt $Limit) { throw 'Download exceeds size limit' }
                    $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                    $file = [IO.File]::Open((Join-Path $stage $Name),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
                    try {
                        $buffer = New-Object byte[] 81920
                        [long]$total = 0
                        while (($count = $stream.ReadAsync($buffer,0,$buffer.Length,$cancel.Token).GetAwaiter().GetResult()) -gt 0) {
                            $total += $count
                            if ($total -gt $Limit) { throw 'Download exceeds size limit' }
                            $file.Write($buffer,0,$count)
                        }
                        $file.Flush($true)
                    } finally { $file.Dispose(); $stream.Dispose() }
                    return
                } finally { $response.Dispose() }
            }
            throw 'Too many redirects'
        } finally { $cancel.Dispose(); $client.Dispose(); $handler.Dispose() }
    }
    $target = 'x86_64-pc-windows-msvc'
    $archiveName = "bb-$Version-$target.zip"
    Download-ReleaseFile 'SHA256SUMS' 1048576
    $allowed = @('x86_64-unknown-linux-gnu','aarch64-unknown-linux-gnu','x86_64-apple-darwin','aarch64-apple-darwin','x86_64-pc-windows-msvc') | ForEach-Object { "bb-$Version-$_." + $(if ($_ -eq $target) {'zip'} else {'tar.gz'}) }
    $entries = @{}
    foreach ($line in [IO.File]::ReadAllLines((Join-Path $stage 'SHA256SUMS'))) {
        if ($line -notmatch '^([0-9a-f]{64})  (bb-[A-Za-z0-9._-]+)$') { throw 'Invalid checksum manifest' }
        $name = $Matches[2]
        if ($name -notin $allowed -or $entries.ContainsKey($name)) { throw 'Unexpected or duplicate checksum entry' }
        $entries[$name] = $Matches[1]
    }
    if ($entries.Count -ne 5) { throw 'Incomplete checksum manifest' }
    Download-ReleaseFile $archiveName 67108864
    $archivePath = Join-Path $stage $archiveName
    $hasher = [Security.Cryptography.SHA256]::Create()
    $hashStream = [IO.File]::OpenRead($archivePath)
    try { $actual = [BitConverter]::ToString($hasher.ComputeHash($hashStream)).Replace('-','').ToLowerInvariant() }
    finally { $hashStream.Dispose(); $hasher.Dispose() }
    if ($actual -ne $entries[$archiveName]) { throw 'Archive checksum mismatch' }
    $archive = [IO.Compression.ZipFile]::OpenRead($archivePath)
    try {
        if ($archive.Entries.Count -ne 1 -or $archive.Entries[0].FullName -ne 'bb.exe' -or $archive.Entries[0].Length -le 0 -or $archive.Entries[0].Length -gt 67108864) { throw 'Archive must contain exactly bb.exe' }
        $kind = ($archive.Entries[0].ExternalAttributes -shr 16) -band 61440
        if ($kind -notin @(0,32768)) { throw 'Archive executable must be a regular file' }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($archive.Entries[0],(Join-Path $stage 'bb.exe'),$false)
    } finally { $archive.Dispose() }
    $staged = Join-Path $stage 'bb.exe'
    $reported = & $staged --version
    if ($LASTEXITCODE -ne 0 -or $reported -cne "bb $Version") { throw 'Executable version or runtime mismatch' }
    if (Test-Path -LiteralPath $destination) {
        if ((Get-Item -LiteralPath $destination -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Destination changed during installation' }
        # Windows PowerShell 5 coerces a null backup argument to an empty path.
        # Keep the old file in our same-volume stage until atomic replacement
        # succeeds; the finally block removes this private backup afterwards.
        [IO.File]::Replace($staged,$destination,(Join-Path $stage 'previous-bb.exe'))
    } else { [IO.File]::Move($staged,$destination) }
    Write-Output "Installed bb $Version at $destination"
    if ($env:PATH.Split(';') -notcontains $InstallDir) { Write-Output "Add $InstallDir to your user PATH." }
} catch {
    [Console]::Error.WriteLine('bb install failed; the previous executable is preserved. Check the version, network, integrity and destination permissions.')
    exit 1
} finally {
    [Net.ServicePointManager]::SecurityProtocol = $oldTls
    if ($stage -and (Test-Path -LiteralPath $stage)) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
