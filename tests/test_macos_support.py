"""macOS paths shared by almond-mcp and the almondbridge net7.0 build (runs on any OS)."""
from pathlib import Path
import re

from almond_mcp import bridge_client, conditioning, paths

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "RhinoAlmondBridge"


def test_user_data_dir_on_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    assert paths.user_data_dir() == tmp_path / "Library" / "Application Support" / "Almond"
    assert bridge_client.token_path() == tmp_path / "Library" / "Application Support" / "Almond" / "bridge.token"


def test_bridge_resolves_the_same_macos_folder():
    # The bridge must not use SpecialFolder.LocalApplicationData on macOS (~/.local/share before .NET 8).
    source = (BRIDGE / "AlmondPlatform.cs").read_text(encoding="utf-8")
    assert '"Library", "Application Support", "Almond"' in source
    for name in ("BridgeAuth.cs", "BridgeServer.cs", "AnalysisWorkspace.cs", "EnvironmentWorkspace.cs"):
        text = (BRIDGE / name).read_text(encoding="utf-8")
        assert "SpecialFolder.LocalApplicationData" not in text, name
        assert "AlmondPlatform.UserDataDir" in text, name


def test_windows_only_calls_are_guarded():
    placement = (BRIDGE / "LibraryPlacement.cs").read_text(encoding="utf-8")
    assert "if (drag && !DragSupported) drag = false;" in placement
    assert "if (!DragSupported) drag = false;" in placement
    karamba = (BRIDGE / "KarambaAdapter.cs").read_text(encoding="utf-8")
    guard = karamba.index("if (!AlmondPlatform.IsWindows)")
    assert guard < karamba.index("SetDllDirectory(dllDir);")
    solver = (BRIDGE / "NativeSolver.cs").read_text(encoding="utf-8")
    assert '"/opt/homebrew/bin"' in solver and '"/usr/local/bin"' in solver
    assert "explorer.exe" not in (BRIDGE / "EnvironmentWorkspace.cs").read_text(encoding="utf-8")


def test_bridge_targets_both_frameworks_on_the_80_sdk():
    project = (BRIDGE / "RhinoAlmondBridge.csproj").read_text(encoding="utf-8")
    assert "<TargetFrameworks>net48;net7.0</TargetFrameworks>" in project
    # The yak distribution tag follows the RhinoCommon the plug-in compiles against: keep rh8_0.
    assert re.search(r'Include="RhinoCommon" Version="8\.0\.23304\.9001"', project)
    assert re.search(r'Include="Grasshopper" Version="8\.0\.23304\.9001"', project)


def test_ffmpeg_found_in_homebrew_on_macos(monkeypatch):
    monkeypatch.delenv("ALMOND_FFMPEG", raising=False)
    monkeypatch.setattr(conditioning.sys, "platform", "darwin")
    monkeypatch.setattr(conditioning.shutil, "which", lambda name: None)
    monkeypatch.setattr(conditioning.os.path, "isfile", lambda p: p == "/opt/homebrew/bin/ffmpeg")
    assert conditioning.find_ffmpeg() == "/opt/homebrew/bin/ffmpeg"


def test_ffmpeg_homebrew_paths_ignored_on_windows(monkeypatch):
    monkeypatch.delenv("ALMOND_FFMPEG", raising=False)
    monkeypatch.setattr(conditioning.sys, "platform", "win32")
    monkeypatch.setattr(conditioning.shutil, "which", lambda name: None)
    monkeypatch.setattr(conditioning.os.path, "isfile", lambda p: p.startswith("/opt/homebrew"))
    assert conditioning.find_ffmpeg() is None
