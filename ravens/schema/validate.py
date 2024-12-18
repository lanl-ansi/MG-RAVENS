import json
import pathlib

from jschon import create_catalog, JSON, JSONSchema, URI, LocalSource, RemoteSource

from ravens.data import _RAVENS_SCHEMA_BASE_URL


class RavensValidator:
    def __init__(self, schema_base_uri: str = _RAVENS_SCHEMA_BASE_URL, schema_url: str = None, local_path_to_schema: pathlib.PosixPath = None):
        self.catalog = create_catalog("2020-12")

        if schema_url is None:
            schema_url = "/".join([schema_base_uri, "Root.json"])

        if local_path_to_schema is not None:
            self.catalog.add_uri_source(URI(schema_base_uri), LocalSource(local_path_to_schema.parent, suffix=""))
            self.schema = JSONSchema.loadf(local_path_to_schema)
        else:
            self.catalog.add_uri_source(URI(schema_base_uri + "/"), RemoteSource(schema_base_uri))
            self.schema = JSONSchema.loadr(schema_url)

        self.result = None

    def validate(self, data: JSON, print_result: bool = True):
        self.result = self.schema.evaluate(data)

        if print_result:
            self.print_result()

    def validate_string(self, json_string: str, print_result: bool = True):
        self.validate(data=JSON.loads(json_string), print_result=print_result)

    def validate_file(self, file_path: str, print_result: bool = True):
        self.validate(data=JSON.loadf(file_path), print_result=print_result)

    def validate_dict(self, data_dict: dict, print_result: bool = True):
        self.validate(data=JSON.loads(json.dumps(data_dict)), print_result=print_result)

    def print_result(self):
        if self.result is not None:
            if self.result.valid:
                print(self.result.output("flag"))
            else:
                print(json.dumps(self.result.output("basic"), indent=2))
        else:
            print("No validator results available")


if __name__ == "__main__":
    import os
    import pathlib

    # Online version of Validator, does not work with proxy
    validator = RavensValidator()

    # Local version of Validator
    schema_path = pathlib.Path(os.getcwd()) / "out/schema/separate/Root.json"
    validator = RavensValidator(schema_base_uri=f"file://{os.getcwd()}/out/schema/separate/", local_path_to_schema=schema_path)

    # Validation example
    data_dir = pathlib.Path(os.getcwd()) / "examples/schema"
    validator.validate_file(data_dir / "AlgorithmProperties.json")
