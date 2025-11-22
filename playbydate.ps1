# PowerShell script to open files in a specific folder with MPV in date order
param(
    [Parameter(Mandatory=$true)]
    [string]$FolderPath
)

# Check if folder exists
if (-not (Test-Path -Path $FolderPath -PathType Container)) {
    Write-Error "The specified folder does not exist: $FolderPath"
    exit 1
}

# Check if MPV is installed/accessible
try {
    #$mpvPath = (Get-Command mpv -ErrorAction Stop).Source
    $mpvPath = "mpv.exe"
}
catch {
    # Try to find MPV in common installation locations
    $possiblePaths = @(
        "d:\mpv\mpv.exe"
        #"C:\Users\benwi\Downloads\mpv-x86_64-v3-20250304-git-0fee7c1\mpv.exe",
        #"C:\Program Files\mpv\mpv.exe",
        #"C:\Program Files (x86)\mpv\mpv.exe",
        #"${env:APPDATA}\mpv\mpv.exe",
        #"${env:LOCALAPPDATA}\mpv\mpv.exe"
    )
    
    $mpvPath = $null
    foreach ($path in $possiblePaths) {
        if (Test-Path $path) {
            $mpvPath = $path
            break
        }
    }
    
    if (-not $mpvPath) {
        Write-Error "MPV player not found. Please ensure it's installed and in your PATH."
        exit 1
    }
}

# Get all files in the folder, sorted by LastWriteTime (creation date)
$files = Get-ChildItem -Path $FolderPath -File | 
         Where-Object { $_.Extension -ne ".part" } |
         Sort-Object LastWriteTime -Descending

if ($files.Count -eq 0) {
    Write-Warning "No files found in the specified folder."
    exit 0
}

# Create a temporary playlist file
#$tempPlaylist = [System.IO.Path]::GetTempFileName() + ".txt"
$tempPlaylist = "tempdate.txt"
$files.FullName | Out-File -FilePath $tempPlaylist -Encoding utf8

# MPV command-line options
$mpvOptions = @(
    "--fs",              # Alternative fullscreen flag
    "--force-window",
    "--idle",
    "--playlist=$tempPlaylist"  # Use the temp playlist file
)

Write-Host "Playing $($files.Count) files from '$FolderPath' sorted by date"
Write-Host "First file: $($files[0].Name) ($(($files[0].LastWriteTime).ToString('yyyy-MM-dd HH:mm:ss')))"
Write-Host "Last file: $($files[-1].Name) ($(($files[-1].LastWriteTime).ToString('yyyy-MM-dd HH:mm:ss')))"
Write-Host "Using temporary playlist: $tempPlaylist"

# Start MPV with the playlist and options
$mpvProcess = Start-Process -FilePath $mpvPath -ArgumentList $mpvOptions -PassThru -Wait

# Clean up the temporary playlist file after MPV exits
#Remove-Item -Path $tempPlaylist -Force -ErrorAction SilentlyContinue
Write-Host "Playlist file removed and script complete"