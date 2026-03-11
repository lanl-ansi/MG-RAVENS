from ravens.uml.autotemplate import AutoTemplateBuilder

builder = AutoTemplateBuilder()
raw = builder.build()
builder.save("out/template_auto.json")


from ravens.uml.autotemplate import AutoTemplateBuilder, validate_against_hand

builder = AutoTemplateBuilder()
df = validate_against_hand(builder)
print(df)