from ravens.io import UMLData


def get_names_of_enumeration_classes(uml_data: UMLData):
    return [o.Name for o in uml_data.objects.itertuples() if o.Object_Type == "Class" and o.Stereotype == "enumeration"]
