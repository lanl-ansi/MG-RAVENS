import glob
import json
import os


def build_examples_docs():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    examples_path = os.path.join(current_dir, "../examples")

    for file in glob.glob("../../examples/schema/*.json"):
        try:
            with open(file, "r") as f:
                md_file = f"""# {file.split(".json")[0].split("examples/schema/")[1]}\n

```json
{json.dumps(json.load(f), indent=2)}
```

"""

            with open(os.path.join(examples_path, f"{file.split('.json')[0].split('examples/schema/')[1]}.md"), "w") as f:
                f.write(md_file)

        except json.JSONDecodeError:
            continue
