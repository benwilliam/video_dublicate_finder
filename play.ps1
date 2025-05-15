# PowerShell script to create and play MPV playlists from a text file
# Includes state saving to resume playback later

param(
    [Parameter(Mandatory=$true)]
    [string]$InputFilePath
)

# Check if the input file exists
if (-not (Test-Path $InputFilePath)) {
    Write-Error "Input file not found: $InputFilePath"
    exit 1
}

# Define state file path (same location as input file with .state extension)
$stateFilePath = [System.IO.Path]::ChangeExtension($InputFilePath, "state")

# Function to create and play a playlist
function Process-Playlist {
    param(
        [string[]]$FilePaths,
        [int]$PlaylistNumber
    )
    
    if ($FilePaths.Count -eq 0) {
        return
    }
    
    # Create a temporary playlist file
    $playlistFile = [System.IO.Path]::GetTempFileName() + ".m3u"
    
    # Write file paths to the playlist
    $FilePaths | ForEach-Object {
        $_ | Out-File -Append -Encoding utf8 $playlistFile
    }
    
    Write-Host "Playing playlist #$PlaylistNumber with $($FilePaths.Count) files..."
    
    # Save current state before playing
    @{ "CurrentPlaylist" = $PlaylistNumber } | ConvertTo-Json | Out-File -FilePath $stateFilePath
    
    # Play the playlist with MPV
    try {
        & D:\mpv\mpv --playlist=$playlistFile --fullscreen --script-opts-append=osc-visibility=always
    }
    catch {
        Write-Error "Error running MPV: $_"
    }
    
    # Clean up the temporary playlist file
    Remove-Item $playlistFile -Force
}

# Read the input file
$content = Get-Content -Path $InputFilePath -Raw

# Split the content by the separator "---"
$sections = $content -split "---"

# Check if state file exists and load last position
$startIndex = 0
if (Test-Path $stateFilePath) {
    try {
        $state = Get-Content -Path $stateFilePath -Raw | ConvertFrom-Json
        $startIndex = $state.CurrentPlaylist
        
        # Verify the saved position is valid
        if ($startIndex -ge $sections.Count) {
            Write-Host "Saved position is beyond available playlists. Starting from the beginning."
            $startIndex = 0
        } else {
            Write-Host "Resuming from playlist #$($startIndex + 1)"
        }
    }
    catch {
        Write-Warning "Could not read state file. Starting from the beginning."
        $startIndex = 0
    }
}

# Process each section as a separate playlist, starting from the saved position
for ($i = $startIndex; $i -lt $sections.Count; $i++) {
    $section = $sections[$i].Trim()
    if ($section) {
        # Split section into lines and filter out empty lines
        $files = $section -split "`r?`n" | Where-Object { $_ -match '\S' }
        Process-Playlist -FilePaths $files -PlaylistNumber ($i + 1)
    }
}

# All playlists completed, remove state file
if (Test-Path $stateFilePath) {
    Remove-Item $stateFilePath -Force
}

Write-Host "All playlists have been played."