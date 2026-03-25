$path = 'main.py'
$lines = Get-Content $path
if (-not ($lines -match '^MEMORY_TRIGGER_RE = re\.compile\(')) {
  $insertAt = [Array]::IndexOf($lines, 'def heuristic_memory_candidates(user_text: str) -> list[dict[str, str]]:')
  if ($insertAt -lt 0) { throw 'heuristic_memory_candidates not found' }
  $before = @()
  if ($insertAt -gt 0) { $before = $lines[0..($insertAt - 1)] }
  $after = $lines[$insertAt..($lines.Count - 1)]
  $block = @(
    'MEMORY_TRIGGER_RE = re.compile(',
    '    r"(我叫|你可以叫我|我是|我住在|我在|我喜欢|我不喜欢|我讨厌|我想|我要|我打算|我准备|明天|今天|最近|下周|周末|生日|工作|上班|上学|考试|面试|搬家|旅行|男朋友|女朋友|对象|老公|老婆|妈妈|爸爸|姐姐|哥哥|弟弟|妹妹|室友|同事|朋友)")',
    '',
    ''
  )
  $result = New-Object System.Collections.Generic.List[string]
  foreach ($line in $before) { $result.Add($line) }
  foreach ($line in $block) { $result.Add($line) }
  foreach ($line in $after) { $result.Add($line) }
  Set-Content -Path $path -Value $result -Encoding UTF8
}
