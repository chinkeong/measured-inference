# Extract the HTML document from each sweep output txt into a matching .html.
# Handles both raw HTML answers and ```html fenced blocks.
$ErrorActionPreference = 'Stop'
Get-ChildItem 'E:\AI\aider\qwen\Qwen3.8-27B-* - *.txt' | ForEach-Object {
    $t = Get-Content -Raw $_.FullName
    # only search the ANSWER section - thinking often contains HTML sketches
    $a = $t.IndexOf('===== ANSWER =====')
    if ($a -ge 0) { $t = $t.Substring($a) }
    $m = [regex]::Match($t, '(?s)```html\s*\r?\n(.*?)\r?\n```')
    if ($m.Success) {
        $html = $m.Groups[1].Value
    } else {
        $start = $t.IndexOf('<!DOCTYPE', [StringComparison]::OrdinalIgnoreCase)
        if ($start -lt 0) { $start = $t.IndexOf('<html') }
        $end = $t.LastIndexOf('</html>')
        if ($start -lt 0 -or $end -lt 0) {
            Write-Output "SKIP (no html found): $($_.Name)"
            return
        }
        $html = $t.Substring($start, $end + 7 - $start)
    }
    $out = [IO.Path]::ChangeExtension($_.FullName, '.html')
    [IO.File]::WriteAllText($out, $html, [Text.UTF8Encoding]::new($false))
    Write-Output "$($_.Name) -> $([IO.Path]::GetFileName($out))  ($($html.Length) chars)"
}
