# Resize already-transparent source cutouts onto the helper's shared canvas.
param(
  [Parameter(Mandatory = $true)][string]$Front,
  [Parameter(Mandatory = $true)][string]$Side,
  [Parameter(Mandatory = $true)][string]$Back
)

Add-Type -AssemblyName System.Drawing

$outputDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) 'assets/pet/custom'
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null

foreach ($entry in @(@('front', $Front), @('side', $Side), @('back', $Back))) {
  $source = [System.Drawing.Image]::FromFile($entry[1])
  $canvas = New-Object System.Drawing.Bitmap(412, 344, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $graphics = [System.Drawing.Graphics]::FromImage($canvas)
  try {
    $graphics.Clear([System.Drawing.Color]::Transparent)
    $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceOver
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $ratio = [Math]::Min(380.0 / $source.Width, 332.0 / $source.Height)
    $width = [int][Math]::Round($source.Width * $ratio)
    $height = [int][Math]::Round($source.Height * $ratio)
    $x = [int][Math]::Floor((412 - $width) / 2)
    $y = 344 - $height
    $graphics.DrawImage($source, (New-Object System.Drawing.Rectangle($x, $y, $width, $height)))
    $canvas.Save((Join-Path $outputDirectory "$($entry[0]).png"), [System.Drawing.Imaging.ImageFormat]::Png)
  } finally {
    $graphics.Dispose()
    $canvas.Dispose()
    $source.Dispose()
  }
}
