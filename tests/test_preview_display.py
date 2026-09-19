import shutil
import subprocess
from pathlib import Path


def test_preview_material_switching():
    node = shutil.which('node')
    assert node, 'Node is required for preview display checks'
    script = Path(__file__).with_name('preview_style.test.mjs')
    result = subprocess.run([node, '--test', str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
