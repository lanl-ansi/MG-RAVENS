from ravens.xml.simplifiers.ravens_simplifier import simplifier
from pathlib import Path

folder = Path("/Users/oreed/Desktop/LANL-ANSI/HCE_Data")

if not folder.is_dir():
    raise NotADirectoryError(f"{folder} is not a valid directory")

for entry in folder.iterdir():
    # Skip sub‑directories – change to `if entry.is_file():` if you
    # want to ignore hidden files, etc.
    if entry.is_file():
        try:
            simp = simplifier()

            output = "/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/tests/tmp/"+str(entry).split("/")[-1]
            print(f"Testing MGR file {entry}")
            MGC = simp(str(entry),output)

        except Exception as exc:
            print(f"❌ Error processing file: {entry.name}")
            with open("tmp/error.txt","w") as f:
                f.write(f"   → {type(exc).__name__}: {exc}")

