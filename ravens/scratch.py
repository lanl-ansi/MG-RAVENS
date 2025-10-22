# Export EA models as Native Format: XML for proper reading
import os
os.chdir(r'X:\Research\Ravens\repo\MG-RAVENS')
import networkx as nx
import pandas as pd
from pathlib import Path
from ravens.uml import graph 
from ravens import jps
from ravens.uml import UMLData, graph, validate, clusions
from importlib import reload
from pprint import pprint
from ravens.uml import template 

uml_data = UMLData().loadf()
inc = clusions.UMLInclusions(uml_data=uml_data, packages=["SimplifiedDiagrams"], exclude_inf_mkt_initial=True)
uml_data_filtered = inc.apply()
ug = graph.UMLGraphs(uml_data=uml_data_filtered)  # both H and A filtered

reload(template)
tg = template.TemplateGenerator(H=ug.H, A=ug.A, root_name="Root")
auto = tg.build()
tg.save_auto_template(auto)


import re
def debug_name_leaks(ug):
    def nm(i): 
        try: return str(ug.uml_data.objects.loc[int(i)]["Name"])
        except Exception: return ""
    bad = []
    for n in ug.H.nodes:
        if re.match(r'^(?:Inf|Mkt)[A-Z]', nm(n)):
            bad.append(("H", n, nm(n)))
    for n in ug.A.nodes:
        if re.match(r'^(?:Inf|Mkt)[A-Z]', nm(n)):
            bad.append(("A", n, nm(n)))
    return bad

inc = clusions.UMLInclusions(
    uml_data,
    packages=["SimplifiedDiagrams"],
    exclude_inf_mkt_initial=True,   # drop InfX/MktX by name
    auto_apply=True                 # builds .filtered_uml_data immediately
)

ug = graph.UMLGraphs(inclusions=inc)  # uses inc.filtered_uml_data directly
leaks = debug_name_leaks(ug)  # should now be []
print("Leaks:", leaks)


# # Set EA tags according to inferences from hand template
# reload(graph)
# reload(validate)
# from ravens.data import _TEMPLATE_JSON_PATH
# role_sets = validate.guess_notconcrete_roles_from_hand(_TEMPLATE_JSON_PATH, ug)
# script = ug.export_ea_jscript_all(role_sets=role_sets, out_path="retag_from_hand.js")

# # Find problems
# mv = ModelValidator(G, root_name="Root")
# issues = mv.yellow_role_misclassified()
# path_out = r'X:\Research\Ravens\ravensRole_updates.csv'
# updates = (
#     issues.query("status == 'needs_update'")[["node", "computed_role"]]
#           .dropna(subset=["node", "computed_role"])
#           .rename(columns={"node": "Object_ID", "computed_role": "ravensRole"})
#           .astype({"Object_ID":"int"})
#           .drop_duplicates(subset=["Object_ID"], keep="last")
#           .sort_values("Object_ID")
# )
# updates.to_csv(path_out, index=False)
# path_invalids = Path(r'X:\Research\Ravens\validation_exports\invalids.xlsx')
# validate.write_validation_report(path_invalids, blah)




# Issues to discuss
Do the8 diamonds imply anything in the template? [see Decorators notes below]
Red connecting two yellows--ok? E.g. in Transformers, PowerSystemResource -> AssetInfo
Do all colored connectors require a label? I haven't found one manually that doesn't have this. 
Relatedly, must mutliplicity be specified if the label is specified? 
Associations - no directionality (can be b.a or a.b) [How is this represented in JSON if it can be either?]

# Decorators - ignore for now
Is it important that I parse the connector decorations? If so, what are the validation checks I should perform?
Generalizations need arrows.  Arrows do not matter for associations. Unclear what the rules for aggregations are.

Validations
1) check that all colored connectors are labeled on one end (i.e. label is not None; can group by connectorID)
2) check that multiplicity is specified if the label is specified
3) check that all objects have a path to Root
4) red connectors cannot flow to green objects
5) green connectors cannot flow to magenta objects; and can only flow to yellow if there's a green eventually underneath that yellow [does it need to exist within the same diagram?]



## Validations ##

# Implementable
# where object is magenta, the $objectID should not be null, else is null 
# primary/seconday for everything (including versions but not root, where it's not the case in the template template)
# $objectID should exist for each object (does it exsit for containers or references?--don't think so)

# 7. Quick decision tree (informal)
#     Is the element an array?
#        → build the wrapper, then evaluate its items.
#     Inside the element / items
#     If it represents a container, emit: $objectType = "container", type = "object", plus properties.
#     Else if it is a reference, emit the three reference fields.
#     Else (ordinary object)
    #     include $objectId = class name
    #     add both hash fields; set to CIM paths unless the class lacks IdentifiedObject, in which case set both to null.

# For later
distinction between object and reference?
green connectors mean they're all objects

yellows under purple are anyofs - does this mean immediately under?
things above purple are containers; below purple are classes


array contains objects of this type $objectID
container has more logic to it than just yellow object

if "$objectType": "reference", then always "type": "string"

a yellow thing with multiple purple things under it will be anyof
yellow thing with yellow things under it are just containers
treat associations like attributes (properties)
purple are "tangible", yellow are not (i.e. there is not "data" to represent them)

tag name -> ravensRole
make completely different colors
containerClass (currently yellow)
substitutableClass (currently yellow)
inheritOnlyClass (currently yellow)
embeddedClass (green)
rootClass (purple)

referenceConnector (red)
embeddedConnector (green)

if a yellow is a child class of a root or embedded Class, then it (all of them including further along the chain) should be a substitutableClass; in the json, the purple object is also included as a substituableClass
parent classes of root or embedded classes are either container or inheritonly. if there is a root class "below" a yellow, it is a container

if a rootclass has parents, those parents need to be containers and one of those parents needs to connect to the Root element somehow
parents of root classes are containers up until they connect to rootclass; any remaining parents are inheritonly
in the case of embeddedClasses, all parents are inheritonly

if there is a root class (purple) that is a parent??
given no other information, assume inherit. 
start at root class, look for shortest distance to root, the ones on that shortest distance will be containers. shortest path should give one or no paths to root. 
inherits don't show up in the template as standalone objects--their properties are inherited
no object should have two generalizations
associations are what are done manually

rules for connectors - referenceConnector if


