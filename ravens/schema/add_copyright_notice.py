import html
import markdownify

from ravens.io import CoreData


def get_cim_copyright_notice(core_data: CoreData, cim_copyright_notice_object_id=29601):
    return "\n".join(
        markdownify.markdownify(html.unescape(str(core_data.objects.loc[cim_copyright_notice_object_id].Note).strip())).splitlines()
    ).strip()


def add_copyright_notice_to_decomposed_schemas(schemas, copyright_notice):
    for k in schemas.keys():
        schemas[k]["license"] = copyright_notice


def add_cim_copyright_notice_to_decomposed_schemas(schemas, core_data):
    copyright_notice = get_cim_copyright_notice(core_data)
    for k in schemas.keys():
        schemas[k]["license"] = copyright_notice


if __name__ == "__main__":
    pass
