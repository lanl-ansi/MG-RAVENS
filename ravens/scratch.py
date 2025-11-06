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

uml_data = UMLData().loadf()

inc = clusions.UMLInclusions(uml_data=uml_data, 
                             packages=["SimplifiedDiagrams"],
                             drop_objects_without_visible_generalization=False)
ug = graph.UMLGraphs(inclusions=inc)  # both H and A filtered

reload(template)
tg = template.TemplateGenerator(H=ug.H, A=ug.A, root_name="Root")
auto = tg.build()
tg.save_auto_template(auto)


# 3) Build role sets + emit JScript
cs = updateea.container_names_from_hand_template()
role_sets = updateea.build_role_sets_for_containers_from_uml(cs, uml_data)
js = updateea.export_ea_jscript_all(role_sets, out_path="temp/ea_scripts_containers.js", print_to_console=False)


# Template comparison
cmp = template.TemplateCompare()
cmp.print_report()




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


