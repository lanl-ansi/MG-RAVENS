from ravens.xml.simplifiers.ravens_simplifier import simplifier
from pathlib import Path
import sys, os
MGR_ROOT = Path(__file__).resolve().parents[2]
if str(MGR_ROOT) not in sys.path:
    sys.path.insert(0, str(MGR_ROOT))

folder = Path(
    #TODO: User Insert Path
)

if not folder.is_dir():
    raise NotADirectoryError(f"{folder} is not a valid directory")

for entry in folder.iterdir():
    # Skip sub‑directories – change to `if entry.is_file():` if you
    # want to ignore hidden files, etc.
    if entry.is_file():
        try:
            simp = simplifier()

            output = MGR_ROOT+"tests/tmp/"+str(entry).split("/")[-1]
            print(f"Testing MGR file {entry}")
            MGC = simp(str(entry),output)

        except Exception as exc:
            print(f"❌ Error processing file: {entry.name}")
            with open("tmp/error.txt","w") as f:
                f.write(f"   → {type(exc).__name__}: {exc}")

