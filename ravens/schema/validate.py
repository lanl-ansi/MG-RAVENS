import json
import pathlib

from jschon import create_catalog, JSON, JSONSchema, URI, LocalSource, RemoteSource

from ravens.data import _RAVENS_SCHEMA_BASE_URL
from ravens.schema import RavensSchema
from ravens.logging import logger


class RavensValidator:
    def __init__(self, schema_base_uri: str = _RAVENS_SCHEMA_BASE_URL, schema_url: str | None = None, local_path_to_schema: pathlib.Path | None = None, schema: RavensSchema | None = None) -> None:
        self.catalog = create_catalog("2020-12")

        if schema is not None:
            self.schema = JSONSchema(schema.schema)

        else:
            if schema_url is None:
                schema_url = "/".join([schema_base_uri, "Root.json"])

            if local_path_to_schema is not None:
                self.catalog.add_uri_source(URI(schema_base_uri), LocalSource(local_path_to_schema.parent, suffix=""))
                self.schema = JSONSchema.loadf(local_path_to_schema)
            else:
                self.catalog.add_uri_source(None, RemoteSource(URI(schema_base_uri)))
                self.schema = JSONSchema.loadr(URI(schema_url))  # type: ignore

        self.data = None
        self.result = None

    def _clear_data(self):
        self.data = None
        self.result = None

    def validate(self, data: JSON, print_result: bool = True):
        self._clear_data()

        self.data = data
        self.result = self.schema.evaluate(self.data)  # type: ignore

        if print_result:
            self.print_result()

    def validate_string(self, json_string: str, print_result: bool = True):
        self.validate(data=JSON.loads(json_string), print_result=print_result)

    def validate_file(self, file_path: pathlib.Path | str, print_result: bool = True):
        self.validate(data=JSON.loadf(file_path), print_result=print_result)

    def validate_dict(self, data_dict: dict, print_result: bool = True):
        self.validate(data=JSON.loads(json.dumps(data_dict)), print_result=print_result)

    def print_result(self, output_level: str = "basic"):
        if self.result is not None:
            if self.result.valid:
                print(self.result.output("flag"))
            else:
                print(json.dumps(self.result.output(output_level), indent=2))
        else:
            logger.info("No validator results available")

    def save_result(self, file_path: pathlib.Path | str, output_level: str = "basic"):
        if self.result is not None:
            with open(file_path, "w") as f:
                json.dump(self.result.output(output_level), f, indent=2)
        else:
            logger.info(f"There is no active result, nothing written to '{file_path}'")


if __name__ == "__main__":
    import os

    # Online version of Validator, does not work with proxy
    validator = RavensValidator()

    # Local version of Validator
    schema_path = pathlib.Path(os.getcwd()) / "out/schema/separate/Root.json"
    validator = RavensValidator(schema_base_uri=f"file://{os.getcwd()}/out/schema/separate/", local_path_to_schema=schema_path)

    # geneate schema from scratch
    validator = RavensValidator(schema=RavensSchema())

    # Validation examples
    # IEEE13_Assets
    validator.validate_file(pathlib.Path(os.getcwd()) / "examples" / "IEEE13_Assets.json")

    # examples/schema
    validator.validate_file(pathlib.Path(os.getcwd()) / "examples" / "schema" / "Outages.json")
