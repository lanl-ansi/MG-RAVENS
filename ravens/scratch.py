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
from ravens.uml import template, updateea
from ravens.data import _TEMPLATE_JSON_PATH, _TEMPLATE_AUTOJSON_PATH

uml_data = UMLData().loadf()

inc = clusions.UMLInclusions(uml_data=uml_data, 
                             packages=["SimplifiedDiagrams"],
                             drop_objects_without_visible_generalization=False)
ug = graph.UMLGraphs(inclusions=inc)  # both H and A filtered

reload(template)
tg = template.TemplateGenerator(H=ug.H, A=ug.A, root_name="Root")
auto = tg.build()
tg.save_auto_template(auto)

from ravens.uml import dev_validate 
reload(dev_validate)
d = dev_validate.DevTemplateValidator(hand_path=_TEMPLATE_JSON_PATH, auto_path=_TEMPLATE_AUTOJSON_PATH)
df = d.test_all()


# Fixed: Groups, Location, OperationalLimitSet.OperationalLimitValue

# fault has all the associations identified properly, but the emissions aren't quite the same
# location

name = 'Versions'
A = ug.A
targets = [n for n, d in A.nodes(data=True) if d.get("Name") == name]
if not targets:
    raise ValueError('No node found with Name == "blah"')

rows = []
seen = set()  # (node, direction)

for t in targets:
    for n in A.predecessors(t):
        key = (n, "incoming")
        if key not in seen:
            seen.add(key)
            rows.append({"node": n, "direction": "incoming", **dict(A.nodes[n])})

    for n in A.successors(t):
        key = (n, "outgoing")
        if key not in seen:
            seen.add(key)
            rows.append({"node": n, "direction": "outgoing", **dict(A.nodes[n])})

df = pd.DataFrame(rows)

OperationalLimitSet.OperationalLimitValue - should be an anyof but all the substitutables are not even listed
ConnectivityNode is missing some assoctiations; AUTO seems to be picking up the "backwards pointing" ones.

OperationalLimitSet.OperationalLimitValue "unworked"
Fault is anyOf but then has a properties (should not) - focus here to fix. Asset also has the same issue - properties below AnyOf
anyOfs should have no type, but they're being put in. 

Containers shouldn't show up in anyOf lists.


AssetInfo/SwitchInfo is an edge case. Switchinfo should only be connected to switch (should not be an anyof)


OperationalLimitSet and ProducerCostFunction are being handled well now.
ACLineSegment is a good example of something I'm not understanding. The associations moving up the generalization chain through substitutables are pulled into the rootClass (ACLineSegment)'
'in the HAND. I think ConnectivityNode might have a similar thing going on.

AnalysisResult may still be a problem (it's messy)'

switchphase - exampel of where we need to consider tehy're embedded. when doing the G traversal, put the embedded clases in a separate bucket; revisit when doing associations to know where they actually go
perlengthimpedance - good example of ???
most likely case is that there is a generalization back to root of an embedded object?
add primarykey to all of them (was showing up as null for some reason)
acdcterminal is something i should ignore
embeddedinheritonly - you don't care about them, you care about what's under them
operationallimit - embeddedInheritOnly (changed)
transfomerend needs to be looked up in data (add to spreadsheet)
transformertest shoudl never show up
why is switch seen as an orphan? 
operationallimit - where to start 
you do inherit inheritonly's associations. like with acdc.operationallimitset

For a rootClass C, do we always inherit association-properties from all ancestors in H?
If no, what’s the gate?
-only if the association appears on a SimplifiedDiagram that includes C?
-only if the ancestor association is “semantically required” (and how is that marked)?
-only if the target is already reachable under Root by a “referencePath-consistent” chain?

Noisy associations
Are there specific association families that are intentionally excluded from HAND even if valid in UML?
e.g. PowerSystemResource.Measurements looks like a prime candidate.

Is there a denylist, or a tag/role that signals “don’t emit this as a property”?

Polymorphism / anyOf policy
When do we expand a reference into anyOf variants?
-only when the target node is substitutableClass?
-also when the target is a “base with embedded descendants” (your PerLengthImpedance situation)?
-should there be a cap (e.g., don’t expand if >N variants)?

Embedded inheritance
For inherited associations that point to embeddedClass nodes (like ConductingEquipment.Terminals):
-should they be inherited into all descendants?
-or only into descendants that appear on diagrams where that embedded subtree is shown?

Duplication rules
If C already has a more-specific property (e.g. ACLineSegment.WireSpacingInfo), should an inherited PowerSystemResource.AssetDatasheet still appear, or should it be suppressed?
# use operationallimitset, fault, and location for first cut of association compares
# embedded vs reference
# avoid everything under switches and powersystemresource for now (it's too complicated)
# look for disconnected graphs in generalizations - these could represent new type


# # 3) Build role sets + emit JScript
# cs = updateea.container_names_from_hand_template()
# role_sets = updateea.build_role_sets_for_containers_from_uml(cs, uml_data)
# js = updateea.export_ea_jscript_all(role_sets, out_path="temp/ea_scripts_containers.js", print_to_console=False)


# Template comparison
cmp = template.TemplateCompare()
cmp.print_report()



# H: DiGraph with edges child -> parent, nodes have "Name" attribute
name = nx.get_node_attributes(ug.A, "Name")

# 1. find the node id whose Name == "Root"
root_id = next(n for n, nm in name.items() if nm == "Root")
neighbor_ids = set(H.predecessors(root_id)) | set(H.successors(root_id))
neighbor_names = sorted((name[n] for n in neighbor_ids), key=str.casefold)







Validations
1) check that all colored connectors are labeled on one end (i.e. label is not None; can group by connectorID)
2) check that multiplicity is specified if the label is specified
3) check that all objects have a path to Root
4) red connectors cannot flow to green objects
5) green connectors cannot flow to magenta objects; and can only flow to yellow if there's a green eventually underneath that yellow [does it need to exist within the same diagram?]
inheritOnly do not appear in template.



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


