# Compare after changes
from ravens.uml.autotemplate import AutoTemplateBuilder, SchemaComparator
from ravens.schema import RavensSchema
# 1) Rebuild template_auto.json
builder = AutoTemplateBuilder()
path = builder.build_and_save()
print(f"Rebuilt auto template at: {path}")

# 2) Make sure both schemas can be fully composed
hand = RavensSchema(template_source="hand")
auto = RavensSchema(template_source="auto")
print(f"Hand schemas: {len(hand.schemas)}")
print(f"Auto schemas: {len(auto.schemas)}")

# 3) Compare hand vs auto
cmp = SchemaComparator(hand_schema=hand, auto_schema=auto)

df_keys = cmp.compare_schema_keys(missing_only=False)
print(df_keys["status"].value_counts(dropna=False))

# # Optional: only show missing/extra rows
# interesting = df_keys[df_keys["status"] != "shared_exact"].copy()
# print(interesting[["key", "status"]].to_string(index=False))


from ravens.schema.template import SchemaTemplate
tmpl = SchemaTemplate(source="auto").template

def has_key_recursive(node, target):
    if isinstance(node, dict):
        if target in node:
            return True
        return any(has_key_recursive(v, target) for v in node.values())
    if isinstance(node, list):
        return any(has_key_recursive(v, target) for v in node)
    return False

assert has_key_recursive(tmpl, "PowerTransformerEnd")
assert has_key_recursive(tmpl, "TransformerTankEnds")
print("Targeted power-transformer checks passed.")











print(present["appearance_classification"].value_counts())
print(present[[
    "hand_name",
    "appearance_classification",
    "example_title_property_path",
    "example_title_array_item_path",
    "example_title_anyof_path",
]])

ActivePowerLimit, AnalysisResult, CurveData

from ravens.uml.autotemplate import SchemaComparator
cmp = SchemaComparator()
missing_keys = cmp.missing_schema_keys()
print(missing_keys)
root_missing = cmp.compare_root_properties(missing_only=True)
print(root_missing)
auto_template_missing = cmp.compare_template_to_schemas("auto", missing_only=True)
print(auto_template_missing)


from ravens.uml.autotemplate import SchemaComparator

cmp = SchemaComparator()

norm = cmp.compare_schema_keys_normalized()
print(norm["status"].value_counts())

missing_norm = cmp.missing_schema_keys_normalized()
print(missing_norm)


from ravens.uml.autotemplate import SchemaComparator

cmp = SchemaComparator()
cls = cmp.classify_missing_schema_keys()

# print(cls["classification"].value_counts())
# print(cls[cls["classification"] == "real_class_absent_from_auto_template"])
# print(cls[cls["classification"] == "real_class_present_in_auto_template"])

print(cls["classification_detail"].value_counts())

expected = cls[cls["classification_detail"] == "real_class_absent_expected_inf_mkt_exclusion"]
mixed = cls[cls["classification_detail"] == "real_class_absent_mixed_diagram_membership"]
unexpected = cls[cls["classification_detail"] == "real_class_absent_unexpected"]

print(expected[["hand_name", "excluded_diagram_names"]])
print(mixed[["hand_name", "excluded_diagram_names", "kept_diagram_names"]])
print(unexpected[["hand_name", "diagram_names"]])


might be inside of array
the key comparison is in the properties table

# For next meeting
# 1) ArCurveData
# embeddedClass, single-target, first stub created
# Bug: later associations from that stub are not expanded

# 2) PowerTransformerEnd / TransformerTankEnd
# single-target, not embedded, no ref available
# Bug: association logic has no fallback for this role shape, so the property is dropped immediately

# 3) ShuntCompensatorPhase family
# embedded target, but polymorphic
# Bug: polymorphic path wants refs; when refs are unavailable, it has no proper fallback for polymorphic embedded classes
    
# ArCurveData is a nested association expansion problem
# PowerTransformerEnd / TransformerTankEnd are single-target substitutable association fallback problems
# ShuntCompensatorPhase and its linear/nonlinear variants are polymorphic embedded association fallback problems

The next clean bucket is classes that are definitely present in the auto raw template but are not becoming 
standalone schema fragments in the auto schema decomposition.

So the next step is to classify those by how they appear in the raw template and figure out whether auto is 
leaving them inline when hand decomposes them.

For the 111 real classes that appear missing from auto.schemas, the content is actually present in the auto-built schema, 
mostly as anyOf variants or other inline object shapes.

OLS.OLV - no $objectID because I was instructed to remove $objectId on emitted anyOf wrappers. Maybe a special case (embeddedInheritOnly)?
ProducerCostFunction.CostParameters.items has the same issue; no others detected

EnvironmentalPhenomenon - “Should decompose_schema() turn object variants inside a top-level anyOf wrapper into standalone schema fragments?” (if so, fixing that pattern could fix 16 classes)

ApplicationSettings:
    In hand:
        DesignAlgorithmProperties has DesignAlgorithmProperties.PredictedEmissions
    In auto:
        DesignAlgorithmProperties just has ApplicationSettings.Application and ApplicationSettings.Settings

2) BusVoltageObjective
    In hand:
        BusVoltageObjective is a direct sibling variant under ApplicationSettings.anyOf
        it directly carries BusVoltageObjective.ConnectivityNodes
    In auto:
        there is still a BusVoltageObjective sibling variant, but the meaningful ConnectivityNodes payload shows up nested under:
    AlgorithmProperties -> AlgorithmObjectives -> BusVoltageObjective

to look at next:
ConnectivityNodeContainer
then ArGeneric.PowerSystemResource accounts for 29; Equipment accounts for 19 classes (out of the 111)





from ravens.uml.autotemplate import SchemaComparator

cmp = SchemaComparator()
present = cmp.classify_present_missing_schema_keys()
present.to_csv("present_missing.csv", index=False)