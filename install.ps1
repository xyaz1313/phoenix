#Requires -Version 5.0
param(
    [switch]$Migrate,
    [switch]$Uninstall,
    [switch]$KeepState
)
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceDir = Join-Path $ScriptDir "phoenix_v7"
if ($env:HERMES_HOME) {
    $HermesDir = $env:HERMES_HOME
} elseif ($env:LOCALAPPDATA) {
    $HermesDir = Join-Path $env:LOCALAPPDATA "hermes"
} else {
    $HermesDir = Join-Path $HOME "AppData\Local\hermes"
}
$PluginsDir = Join-Path $HermesDir "plugins"
$TargetDir = Join-Path $PluginsDir "phoenix_v7"
$StateDir = Join-Path $HermesDir "phoenix_v7_state"
$ConfigPath = Join-Path $HermesDir "config.yaml"

function Get-HermesCommand {
    Get-Command hermes -ErrorAction SilentlyContinue
}

function Get-EnabledPhoenixPlugins {
    # 返回当前 Hermes 里状态是 enabled、名字以 phoenix 开头的插件名列表。
    # 读不到（没装 hermes / 命令报错）时按"什么都没有"处理——调用方各自决定这种
    # 情况下该保守到什么程度，这个函数本身不假设。
    $hermesCmd = Get-HermesCommand
    if (-not $hermesCmd) { return @() }
    try {
        $json = hermes plugins list --json 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $json) { return @() }
        $entries = $json | ConvertFrom-Json
        return @($entries | Where-Object { $_.status -eq "enabled" -and $_.name -match "^phoenix" } | ForEach-Object { $_.name })
    } catch {
        return @()
    }
}

function Show-UsageAfterInstall {
    Write-Host ""
    Write-Host "📖 不死鸟怎么用："
    Write-Host "------------------------"
    Write-Host "装完不用学新命令，正常用 Hermes 就行，下面这些是不死鸟自动生效/可选用的部分："
    Write-Host ""
    Write-Host "  hermes phoenix-status       随时查看当前状态（路由/熔断/花费/抗体库/兜底链）"
    Write-Host "  hermes phoenix-router on/off  开关自动路由换模型（默认关，只判断档位不切模型，"
    Write-Host "                              需要自己配置好档位对应的模型后再开启）"
    Write-Host "  /goal 你的任务描述           长任务模式，Hermes 原生命令，不死鸟自动接管清单强制"
    Write-Host "                              + 高危操作换模型复核"
    Write-Host ""
    Write-Host "  以下完全自动，不需要手动开启："
    Write-Host "    - 熔断保护：连续报错自动跳闸，冷却后自动恢复"
    Write-Host "    - 高危回复核验：深度/真神档位回复自动交叉核验，通道故障自动降级放行"
    Write-Host "    - 隐私提醒/本地模型：仅 macOS 支持，Windows 上不会看到这条提醒，属于正常现象"
    Write-Host "    - 欠费兜底：主力模型不可用时，如果你在 Hermes 配置了 fallback_model，会"
    Write-Host "      自动尝试；没配置也完全没问题，不是必须项"
    Write-Host ""
    Write-Host "  完整文档在 phoenix_v7/docs/ 目录，遇到问题也可以直接问 Hermes 里的 AI。"
}

# ---------------------------------------------------------------------------
# -Uninstall：卸载。必须明确区分"只删代码"和"代码+历史数据一起删"。
# ---------------------------------------------------------------------------
if ($Uninstall) {
    Write-Host "不死鸟 Phoenix 卸载"
    Write-Host "========================"
    if (-not (Test-Path $TargetDir)) {
        Write-Host "ℹ️  没有找到已安装的 phoenix_v7（$TargetDir 不存在），无需卸载。"
        exit 0
    }
    $hermesCmd = Get-HermesCommand
    if ($hermesCmd) {
        $enabledPhoenix = Get-EnabledPhoenixPlugins
        if ($enabledPhoenix -contains "phoenix_v7") {
            Write-Host "🔌 禁用 phoenix_v7 ..."
            hermes plugins disable phoenix_v7 | Out-Null
        }
    }
    Remove-Item $TargetDir -Recurse -Force
    Write-Host "✅ 已删除插件代码：$TargetDir"
    if ($KeepState) {
        if (Test-Path $StateDir) {
            Write-Host "📦 保留了历史数据（抗体库/成本记录等）：$StateDir"
        }
    } elseif (Test-Path $StateDir) {
        Remove-Item $StateDir -Recurse -Force
        Write-Host "✅ 已删除历史数据：$StateDir"
    }
    Write-Host ""
    Write-Host "不影响 Hermes 本体，也不会残留任何对 Hermes 核心文件的修改。"
    exit 0
}

# ---------------------------------------------------------------------------
# 共用前置检查
# ---------------------------------------------------------------------------
if (-not (Test-Path $HermesDir)) {
    Write-Host "❌ 没有检测到 Hermes Agent（找不到 $HermesDir）"
    Write-Host "   请先安装 Hermes Agent，再运行本脚本。"
    exit 1
}

if (-not (Test-Path $SourceDir)) {
    Write-Host "❌ 找不到 phoenix_v7 目录，请确认是在解压后的完整文件夹里运行本脚本。"
    exit 1
}

# ---------------------------------------------------------------------------
# 默认安装（不带 -Migrate）：只复制文件 + 校验，绝不自动改 Hermes 启用状态。
# 真实审计报告指出的问题：以前普通安装会无条件 `hermes plugins enable`，
# 且不检测前代 Phoenix 是否还启用着，可能造成新旧版本同时启用、钩子重复执行。
# 现在默认安装只负责"把文件放到该放的地方"，切换启用状态必须显式加 -Migrate。
# ---------------------------------------------------------------------------
if (-not $Migrate) {
    Write-Host "不死鸟 Phoenix 安装脚本"
    Write-Host "========================"

    if (Test-Path $TargetDir) {
        $BackupDir = "$TargetDir.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
        Write-Host "⚠️  检测到已安装的旧版本，备份到：$BackupDir"
        Move-Item $TargetDir $BackupDir
    }

    New-Item -ItemType Directory -Force -Path $PluginsDir | Out-Null
    Copy-Item -Path $SourceDir -Destination $TargetDir -Recurse

    # 垃圾目录可能出现在任意层级（比如 guardrails/__pycache__），不止顶层。
    foreach ($junk in @("__pycache__", ".pytest_cache", "venv")) {
        Get-ChildItem $TargetDir -Recurse -Directory -Filter $junk -ErrorAction SilentlyContinue |
            ForEach-Object { Remove-Item $_.FullName -Recurse -Force }
    }

    Write-Host "✅ 文件已复制到 $TargetDir"
    Write-Host ""
    Write-Host "这一步只复制文件，未自动启用插件，Hermes 现有行为不变。"
    Write-Host ""
    Write-Host "如果这是全新安装（之前没装过不死鸟任何版本），运行："
    Write-Host "   hermes plugins enable phoenix_v7"
    Write-Host "   hermes phoenix-status"
    Write-Host ""
    Write-Host "如果你要从旧版本（比如 phoenix_full）切换过来，请改用："
    Write-Host "   .\install.ps1 -Migrate"
    Write-Host "（会自动备份、禁用旧版本、启用新版本、失败自动回滚，保证全程最多一个"
    Write-Host "   Phoenix 版本处于启用状态）"

    Show-UsageAfterInstall
    exit 0
}

# ---------------------------------------------------------------------------
# -Migrate：事务化切换。任何一步失败都要能回到迁移前的状态。
# ---------------------------------------------------------------------------
Write-Host "不死鸟 Phoenix 迁移安装（-Migrate）"
Write-Host "========================"

$hermesCmd = Get-HermesCommand
if (-not $hermesCmd) {
    Write-Host "❌ 找不到 hermes 命令，无法执行迁移（需要它读取/切换插件启用状态）。"
    Write-Host "   请先确认 hermes 在 PATH 里，或者用不带 -Migrate 的普通安装。"
    exit 1
}

$didBackupTarget = $false
$didBackupState = $false
$didBackupConfig = $false
$enabledNewPlugin = $false
$disabledOldPlugins = @()
$BackupDir = $null
$StateBackupDir = $null
$ConfigBackup = $null

function Invoke-Rollback {
    Write-Host ""
    Write-Host "⚠️  正在回滚到迁移前的状态..."
    if ($enabledNewPlugin) {
        hermes plugins disable phoenix_v7 2>$null | Out-Null
        Write-Host "   已禁用 phoenix_v7"
    }
    foreach ($old in $disabledOldPlugins) {
        hermes plugins enable $old --no-allow-tool-override 2>$null | Out-Null
        Write-Host "   已恢复启用：$old"
    }
    if (Test-Path $TargetDir) {
        Remove-Item $TargetDir -Recurse -Force
    }
    if ($didBackupTarget -and (Test-Path $script:BackupDir)) {
        Move-Item $script:BackupDir $TargetDir
        Write-Host "   已恢复旧插件目录：$TargetDir"
    }
    if ($didBackupState -and (Test-Path $script:StateBackupDir)) {
        if (Test-Path $StateDir) { Remove-Item $StateDir -Recurse -Force }
        Move-Item $script:StateBackupDir $StateDir
        Write-Host "   已恢复历史数据：$StateDir"
    }
    if ($didBackupConfig -and (Test-Path $script:ConfigBackup)) {
        Copy-Item $script:ConfigBackup $ConfigPath -Force
        Write-Host "   已恢复 config.yaml"
    }
    Write-Host "✅ 已回滚，Hermes 状态跟迁移前一致。"
}

try {
    # 1. 读取当前启用状态：找出除 phoenix_v7 自己以外、名字以 phoenix 开头且
    #    仍处于启用状态的前代插件（比如 phoenix_full）。同时记下 phoenix_v7
    #    自己是不是已经启用——原地升级场景下它本来就是启用的，失败回滚时
    #    不能把它禁用掉，那样反而把用户"本来能用"的状态改坏了。
    $enabledPhoenix = Get-EnabledPhoenixPlugins
    $oldPhoenix = @($enabledPhoenix | Where-Object { $_ -ne "phoenix_v7" })
    $phoenixV7AlreadyEnabled = $enabledPhoenix -contains "phoenix_v7"

    # 2. 备份 config.yaml（Hermes 的插件启用/禁用状态存在这里面）
    if (Test-Path $ConfigPath) {
        $ConfigBackup = "$ConfigPath.phoenix-migrate-backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
        Copy-Item $ConfigPath $ConfigBackup
        $didBackupConfig = $true
    }

    # 3. 备份历史数据目录
    if (Test-Path $StateDir) {
        $StateBackupDir = "$StateDir.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
        Copy-Item $StateDir $StateBackupDir -Recurse
        $didBackupState = $true
    }

    # 4. 计算源目录的 SHA-256 清单（先算完再动旧目录，任何一步失败都还原得回去）。
    #    跳过垃圾目录（任意层级，不只是顶层）——它们复制后会被删掉，不该出现在
    #    清单里，否则校验时会因为"复制后找不到"而误判失败。
    $JunkDirNames = @("__pycache__", ".pytest_cache", "venv")
    $sourceManifest = Get-ChildItem $SourceDir -Recurse -File | Where-Object {
        $relParts = $_.FullName.Substring($SourceDir.Length + 1) -split '[\\/]'
        -not ($relParts | Where-Object { $JunkDirNames -contains $_ })
    } | ForEach-Object {
        [PSCustomObject]@{
            RelPath = $_.FullName.Substring($SourceDir.Length + 1)
            Hash    = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
        }
    }

    # 5. 备份旧插件目录，复制新版本
    if (Test-Path $TargetDir) {
        $BackupDir = "$TargetDir.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
        Move-Item $TargetDir $BackupDir
        $didBackupTarget = $true
    }
    New-Item -ItemType Directory -Force -Path $PluginsDir | Out-Null
    Copy-Item -Path $SourceDir -Destination $TargetDir -Recurse
    # 垃圾目录可能出现在任意层级（比如 guardrails/__pycache__），不止顶层。
    foreach ($junk in $JunkDirNames) {
        Get-ChildItem $TargetDir -Recurse -Directory -Filter $junk -ErrorAction SilentlyContinue |
            ForEach-Object { Remove-Item $_.FullName -Recurse -Force }
    }

    # 6. 校验复制结果跟源目录逐文件哈希一致
    $manifestPath = Join-Path $TargetDir "INSTALL_MANIFEST.sha256.txt"
    $sourceManifest | ForEach-Object { "$($_.Hash)  $($_.RelPath)" } | Set-Content -Path $manifestPath -Encoding UTF8
    foreach ($entry in $sourceManifest) {
        $copiedFile = Join-Path $TargetDir $entry.RelPath
        if (-not (Test-Path $copiedFile)) {
            throw "复制校验失败：$($entry.RelPath) 复制后找不到"
        }
        $actualHash = (Get-FileHash $copiedFile -Algorithm SHA256).Hash
        if ($actualHash -ne $entry.Hash) {
            throw "复制校验失败：$($entry.RelPath) 复制前后哈希不一致"
        }
    }
    Write-Host "✅ 文件复制完成，SHA-256 校验通过（$($sourceManifest.Count) 个文件）"

    # 7. 禁用前代 Phoenix
    foreach ($old in $oldPhoenix) {
        Write-Host "🔌 禁用旧版本：$old"
        hermes plugins disable $old
        if ($LASTEXITCODE -ne 0) { throw "禁用旧插件失败：$old" }
        $disabledOldPlugins += $old
    }

    # 8. 启用 phoenix_v7（原地升级场景下它本来就是启用的，这一步是幂等的）
    Write-Host "🔌 启用 phoenix_v7"
    hermes plugins enable phoenix_v7 --no-allow-tool-override
    if ($LASTEXITCODE -ne 0) { throw "启用 phoenix_v7 失败" }
    # 只有"之前没启用、这次是我们才启用的"才记为需要在回滚时撤销——本来就
    # 启用着的话，回滚不该把它关掉。
    $enabledNewPlugin = -not $phoenixV7AlreadyEnabled

    # 9. phoenix-status 校验
    Write-Host "🔍 校验安装结果："
    Write-Host "------------------------"
    hermes phoenix-status
    if ($LASTEXITCODE -ne 0) { throw "hermes phoenix-status 执行失败" }

    # 10. 最小烟测：迁移后有且仅有 phoenix_v7 处于启用状态
    $afterEnabled = @(Get-EnabledPhoenixPlugins)
    if ($afterEnabled.Count -ne 1 -or $afterEnabled[0] -ne "phoenix_v7") {
        throw "烟测失败：迁移后应该只有 phoenix_v7 处于启用状态，实际是：$($afterEnabled -join ', ')"
    }

    Write-Host ""
    Write-Host "✅ 迁移完成，全程只有 phoenix_v7 处于启用状态。"
    if ($didBackupTarget) { Write-Host "   旧插件代码备份在：$BackupDir" }
    if ($didBackupState) { Write-Host "   旧历史数据备份在：$StateBackupDir" }
    if ($didBackupConfig) { Write-Host "   旧 config.yaml 备份在：$ConfigBackup" }

    Show-UsageAfterInstall
} catch {
    Write-Host ""
    Write-Host "❌ 迁移过程出错：$($_.Exception.Message)"
    Invoke-Rollback
    exit 1
}
