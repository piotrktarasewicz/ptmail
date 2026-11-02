# Budowanie: packaging\build.ps1
from pathlib import Path

import accessible_output2
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
speech_lib = Path(accessible_output2.__file__).parent / "lib"

analysis = Analysis(
    [str(root / "packaging" / "run_ptmail.py")],
    pathex=[str(root)],
    # Ścieżkę biblioteki NVDA wyznacza accessible_output2 po spakowaniu.
    binaries=[
        (str(speech_lib / "nvdaControllerClient64.dll"), "accessible_output2/lib")
    ],
    datas=[(str(root / "ptmail" / "assets"), "ptmail/assets")],
    hiddenimports=[
        *collect_submodules("accessible_output2.outputs"),
        "keyring.backends.Windows",
    ],
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="PTMail",
    console=False,
    icon=str(root / "ptmail" / "assets" / "ptmail.ico"),
)
collection = COLLECT(exe, analysis.binaries, analysis.datas, name="PTMail")
