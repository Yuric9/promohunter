# Receita do PyInstaller para gerar o PromoHunter.exe
#   pip install pyinstaller
#   pyinstaller PromoHunter.spec
import sys

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

sys.path.insert(0, SPECPATH)  # para o collect_submodules achar a pasta app

a = Analysis(
    ["PromoHunter.pyw"],
    pathex=["."],
    datas=[("app/static", "app/static"), (".env.example", ".")] + copy_metadata("apscheduler"),
    hiddenimports=collect_submodules("app") + collect_submodules("uvicorn"),
    excludes=["pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PromoHunter",
    console=False,  # sem janela preta
    upx=False,
)
