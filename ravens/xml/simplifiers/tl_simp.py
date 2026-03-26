import json
import warnings
from pathlib import Path
import sys, os
MGR_ROOT = Path(__file__).resolve().parents[2]
if str(MGR_ROOT) not in sys.path:
    sys.path.insert(0, str(MGR_ROOT))

class tl_simp:
    def __init__(self,tl_targets):
        self.tl_targets = tl_targets
        self.__name__ = "tl_simp_"+str(len(tl_targets))

    def __call__(self,in_data,out_data=None):
        if out_data is None and isinstance(in_data, dict):
            keys = in_data.keys()
            for target_key in self.tl_targets:
                if target_key in keys:
                    del in_data[target_key]
            return in_data
        elif isinstance(in_data, str) and isinstance(out_data, str):
            with open(in_data, 'r') as input_file, open(out_data, 'w') as output_file:
                content = input_file.read()
                raven = json.loads(content)
                keys = raven.keys()
                for target_key in self.tl_targets:
                    if target_key in keys:
                        del raven[target_key]

                json.dump(raven, output_file,indent=2)
        else:
            warnings.warn("Invalid arguments. Expected either a dictionary or two filenames. Returning null dictionary")
            return {}


