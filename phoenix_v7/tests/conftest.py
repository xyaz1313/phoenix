"""测试 sys.path 引导，集中在这一个文件里，测试用例本身不再各自处理。

2026-08-05：真实审计报告指出，原来每个测试文件各自写
``sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))``——干净环境
（比如一台从没装过不死鸟/Hermes 的 Windows 机器）没有这个目录，测试直接在 import
阶段就炸。而且这些文件之前还从 ``get_hermes_home() / "plugins"`` 下 import
``phoenix_v7``，测的是"当前已安装到 Hermes Home 的那份拷贝"，不是这个仓库里
正在改的源码——本地要是还没跑过 install.ps1，改了代码测试也测不出来。

现在统一：
1. ``phoenix_v7`` 本体直接从这个仓库自己的目录 import（repo root 进 sys.path），
   不经过 Hermes Home，改了源码马上能测到。
2. ``hermes_constants`` 优先按正常安装的包 import；不存在时才用
   ``HERMES_AGENT_SRC`` 环境变量或者本机历史约定路径兜底——干净环境应该显式设
   ``HERMES_AGENT_SRC`` 指向 hermes-agent 源码，而不是依赖 ``~/.hermes`` 已经
   存在。
"""
import os
import sys
from pathlib import Path

_PHOENIX_DIR = Path(__file__).resolve().parent.parent  # .../phoenix_v7
_REPO_ROOT = _PHOENIX_DIR.parent

# 让 `import phoenix_v7` 解析到仓库里的源码，`from router.config import ...` 之类
# 的子模块直接 import 也继续可用。
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_PHOENIX_DIR))

try:
    import hermes_constants  # noqa: F401
except ImportError:
    _hermes_agent_src = os.environ.get("HERMES_AGENT_SRC") or str(
        Path.home() / ".hermes" / "hermes-agent"
    )
    sys.path.insert(0, _hermes_agent_src)
