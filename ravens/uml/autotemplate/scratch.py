from ravens.uml.autotemplate import AutoTemplateBuilder, validate_against_hand

builder = AutoTemplateBuilder()
raw = builder.build()
builder.save("out/template_auto.json")

df = validate_against_hand(builder)
print(df)


from ravens.schema import SchemaTemplate, RavensSchema

tmpl = SchemaTemplate(source="auto")
schema = RavensSchema(template_source="auto")