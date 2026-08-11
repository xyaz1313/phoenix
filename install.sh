#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/phoenix_v7"
if [ -n "${HERMES_HOME:-}" ]; then
  HERMES_DIR="$HERMES_HOME"
else
  HERMES_DIR="$HOME/.hermes"
fi
PLUGINS_DIR="$HERMES_DIR/plugins"
TARGET_DIR="$PLUGINS_DIR/phoenix_v7"

echo "不死鸟 Phoenix 安装脚本"
echo "========================"

if [ ! -d "$HERMES_DIR" ]; then
  echo "❌ 没有检测到 Hermes Agent（找不到 $HERMES_DIR）"
  echo "   请先安装 Hermes Agent，再运行本脚本。"
  exit 1
fi

if [ ! -d "$SOURCE_DIR" ]; then
  echo "❌ 找不到 phoenix_v7 目录，请确认是在解压后的完整文件夹里运行本脚本。"
  exit 1
fi

mkdir -p "$PLUGINS_DIR"

NEW_STATE_DIR="$HERMES_DIR/phoenix_v7_state"

if [ -d "$TARGET_DIR" ]; then
  OLD_STATE_DIR="$TARGET_DIR/state"
  if [ -d "$OLD_STATE_DIR" ]; then
    echo "📦 检测到旧版本的 state 数据，迁移到新位置：$NEW_STATE_DIR"
    mkdir -p "$NEW_STATE_DIR"
    for f in "$OLD_STATE_DIR"/*; do
      [ -e "$f" ] || continue
      dest="$NEW_STATE_DIR/$(basename "$f")"
      if [ ! -e "$dest" ]; then
        cp -R "$f" "$dest"
      fi
    done
  fi
  # 备份必须放在 plugins/ 目录之外——Hermes 的插件扫描器按 plugin.yaml 里的
  # name 字段识别插件，不管目录叫什么名字，放在 plugins/phoenix_v7.backup.*
  # 这种同级路径下会被当成另一个同名插件加载，实测会顶替掉真正的安装（新版本
  # 代码从此再也不会被执行，且没有任何报错提示），所以放到 plugins/ 外层。
  BACKUP_ROOT="$HERMES_DIR/phoenix_v7_backups"
  mkdir -p "$BACKUP_ROOT"
  BACKUP_DIR="$BACKUP_ROOT/phoenix_v7.backup.$(date +%Y%m%d%H%M%S)"
  echo "⚠️  检测到已安装的旧版本，备份到：$BACKUP_DIR"
  mv "$TARGET_DIR" "$BACKUP_DIR"
fi

echo "📦 安装到 $TARGET_DIR ..."
cp -R "$SOURCE_DIR" "$TARGET_DIR"

# 安装产生的本地状态/缓存目录不需要带过去
rm -rf "$TARGET_DIR/__pycache__" "$TARGET_DIR/.pytest_cache" "$TARGET_DIR/venv" 2>/dev/null || true

echo "✅ 文件复制完成"
echo ""

if command -v hermes >/dev/null 2>&1; then
  echo "🔌 启用插件："
  echo "------------------------"
  # Hermes 要求用户安装的插件显式启用才会真正加载——只把文件复制到
  # plugins/ 目录不够，第一次装的用户之前从未启用过 phoenix_v7，不调这一步
  # 的话下面的 phoenix-status 校验必然失败（命令根本不存在），会被误报成
  # "安装失败"。已装过旧版本再次运行本脚本时这一步是幂等的（Hermes 自己
  # 处理"已经启用"的情况，不会报错）。老版本 Hermes 没有这个子命令时，
  # 不阻断安装，只提示用户自己手动启用。
  if hermes plugins enable phoenix_v7 --no-allow-tool-override; then
    :
  else
    echo "⚠️  自动启用失败（可能是较旧版本的 Hermes 没有这个子命令），"
    echo "   请手动运行：hermes plugins enable phoenix_v7"
  fi
  echo ""
  echo "🔍 校验安装结果："
  echo "------------------------"
  hermes phoenix-status || {
    echo ""
    echo "⚠️  hermes phoenix-status 执行失败，请检查上面的报错信息。"
    exit 1
  }
else
  echo "⚠️  找不到 hermes 命令，无法自动启用/校验。请手动运行："
  echo "   hermes plugins enable phoenix_v7"
  echo "   hermes phoenix-status"
fi

echo ""
echo "安装完成。"
echo ""
echo "📖 不死鸟怎么用："
echo "------------------------"
echo "装完不用学新命令，正常用 Hermes 就行，下面这些是不死鸟自动生效/可选用的部分："
echo ""
echo "  hermes phoenix-status       随时查看当前状态（路由/熔断/花费/抗体库/兜底链）"
echo "  hermes phoenix-router on/off  开关自动路由换模型（默认关，只判断档位不切模型，"
echo "                              需要自己配置好档位对应的模型后再开启）"
echo "  /goal 你的任务描述           长任务模式，Hermes 原生命令，不死鸟自动接管清单强制"
echo "                              + 高危操作换模型复核"
echo ""
echo "  以下完全自动，不需要手动开启："
echo "    - 熔断保护：连续报错自动跳闸，冷却后自动恢复"
echo "    - 高危回复核验：深度/真神档位回复自动交叉核验，通道故障自动降级放行"
echo "    - 隐私提醒：聊天内容命中敏感词会自动在回复后提醒（仅 macOS，需要你自己"
echo "      另外配置好本地模型；没配置的话看不到这条提醒，属于正常现象）"
echo "    - 欠费兜底：主力模型不可用时，如果你在 Hermes 配置了 fallback_model，会"
echo "      自动尝试；没配置也完全没问题，不是必须项"
echo ""
echo "  完整文档在 phoenix_v7/docs/ 目录，遇到问题也可以直接问 Hermes 里的 AI。"
