import csv
from pathlib import Path

ORIG = Path(r"X:\Research\Ravens\original_connector_colors.csv")
UPDT_reset = Path(r"X:\Research\Ravens\updated_connector_colors_afterchange.csv")
UPDT = Path(r"X:\Research\Ravens\updated_connector_colors.csv")


# Tune these if needed:
BATCH_SIZE = 8          # how many GUIDs per statement (keep small for console)
MAX_CHARS  = 600        # max characters per VBScript line (failsafe)

BATCH_SIZE = 15  # keep this small so console accepts it

def load_csv(path):
    m = {}
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            guid = row["ea_guid"].strip()
            try:
                color = int(row["LineColor"])
            except Exception:
                continue
            m[guid] = color
    return m

orig = load_csv(ORIG)
updt = load_csv(UPDT)

targets = { -1: [], 0: [] }
targets = {0 : [], 128: [], 8388736: [], 12632256: [], 32896: [], 2763429: [], 16711680: [], 5737262: [], -1: []}

for g, c0 in orig.items():
    if g in updt:
        if updt[g] != c0:  # mismatch, needs reset
            targets[c0].append(g)

print(f"Need to reset {len(targets[-1])} to -1 and {len(targets[0])} to 0.")

def emit(color, guids):
    for i in range(0, len(guids), BATCH_SIZE):
        chunk = guids[i:i+BATCH_SIZE]
        guids_str = ",".join(f"'{g}'" for g in chunk)
        print(f'Repository.Execute "UPDATE t_connector SET LineColor={color} WHERE ea_guid IN ({guids_str})"')

emit(-1, targets[-1])
emit(0, targets[0])

## I confirmed by comparing the original to the re-set updated version that all linecolors are the 
# same for all connectors. Next step is to implement Legends for coloring.

## For performing the update back to legend based coloring after resetting everything to default
all_colors = set([updt[k] for k in updt.keys()])
orig_colors = set([orig[k] for k in orig.keys()])
ravens_added_colors = all_colors - orig_colors
from ravens.jps import ea_numeric_to_hex_color
conv = {c: ea_numeric_to_hex_color(c) for c in ravens_added_colors}
{128: '#800000', 2763429: '#a52a2a', 5737262: '#2e8b57'}

red: 128, 2763429
green: 5737262

targets = { 128: [], 2763429: [], 5737262 : []}
for g, c0 in updt.items():
    if g in orig and c0 in targets:
        if orig[g] != c0:  # mismatch, needs reset
            targets[c0].append(g)

reds = targets[128]
reds.extend(targets[2763429])
greens = targets[5737262]

batch_size = 10

def make_batch_cmd(guids, color):
    quoted = ",".join([f'"{g}"' for g in guids])
    return (
        f'guids=Array({quoted}):'
        f'For gi=0 To UBound(guids):'
        f'Set c=Repository.GetConnectorByGuid(guids(gi)):'
        f'f=False:For i=0 To c.TaggedValues.Count-1:'
        f'If LCase(c.TaggedValues.GetAt(i).Name)="ravens_color" Then '
        f'Set tv=c.TaggedValues.GetAt(i):f=True:Exit For:End If:Next:'
        f'If Not f Then Set tv=c.TaggedValues.AddNew("ravens_color",""):tv.Update:c.TaggedValues.Refresh:End If:'
        f'tv.Value="{color}":tv.Update:c.Update:Next'
    )

for i in range(0, len(reds), batch_size):
    print(make_batch_cmd(reds[i:i+batch_size], "red"))
for i in range(0, len(greens), batch_size):
    print(make_batch_cmd(greens[i:i+batch_size], "green"))
