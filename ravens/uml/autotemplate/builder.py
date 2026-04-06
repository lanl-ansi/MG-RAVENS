from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional


from ravens.uml.data import UMLData


def _default_template_auto_path() -> Path:
    return Path(__file__).resolve().parents[2] / "lib" / "template_auto.json"


def _default_analysis_variable_diagnostics_path() -> Path:
    return Path(__file__).resolve().parents[3] / "out" / "analysis_variable_diagnostics.json"

from .clusions import UMLInclusions
from .graph import UMLGraphs
from .template import TemplateGenerator


class AutoTemplateBuilder:
    """Build and optionally export the raw auto-template using the dev workflow.

    This is intentionally isolated from ravens.schema so raw-template parity can
    be validated before schema integration.
    """

    def __init__(
        self,
        *,
        uml_data: UMLData | None = None,
        packages: Optional[Iterable[str]] = ("SimplifiedDiagrams",),
        root_name: str = "Root",
        exclude_inf_mkt_initial: bool = True,
        exclude_hidden_links: bool = True,
        hidden_scope_path: str | None = "SimplifiedDiagrams",
        drop_objects_without_visible_generalization: bool = False,
        debug: bool = False,
        capture_diagnostics: bool = False,
    ) -> None:
        self.uml_data = uml_data
        self.packages = tuple(packages) if packages is not None else None
        self.root_name = root_name
        self.exclude_inf_mkt_initial = exclude_inf_mkt_initial
        self.exclude_hidden_links = exclude_hidden_links
        self.hidden_scope_path = hidden_scope_path
        self.drop_objects_without_visible_generalization = drop_objects_without_visible_generalization
        self.debug = bool(debug)
        self.capture_diagnostics = bool(capture_diagnostics)

        self.inclusions: UMLInclusions | None = None
        self.graphs: UMLGraphs | None = None
        self.generator: TemplateGenerator | None = None
        self.raw_template: dict | None = None

    def _get_uml_data(self) -> UMLData:
        return self.uml_data if self.uml_data is not None else UMLData.loadf()

    def build(self) -> dict:
        uml_data = self._get_uml_data()
        self.inclusions = UMLInclusions(
            uml_data=uml_data,
            packages=self.packages,
            auto_apply=True,
            exclude_inf_mkt_initial=self.exclude_inf_mkt_initial,
            exclude_hidden_links=self.exclude_hidden_links,
            hidden_scope_path=self.hidden_scope_path,
            drop_objects_without_visible_generalization=self.drop_objects_without_visible_generalization,
        )
        self.graphs = UMLGraphs(inclusions=self.inclusions)
        self.generator = TemplateGenerator(
            H=self.graphs.H,
            A=self.graphs.A,
            root_name=self.root_name,
            debug=self.debug,
            capture_diagnostics=self.capture_diagnostics,
        )
        self.raw_template = self.generator.build()
        return self.raw_template

    @property
    def analysis_variable_diagnostics(self) -> dict:
        if self.generator is None:
            return {"analysis_variable_events": [], "event_count": 0}
        return self.generator.analysis_variable_diagnostics_payload()

    def save(self, out_path: str | Path | None = None, *, data: dict | None = None) -> Path:
        payload = data if data is not None else self.raw_template
        if not isinstance(payload, dict):
            payload = self.build()

        path = Path(out_path) if out_path is not None else _default_template_auto_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def save_diagnostics(self, out_path: str | Path | None = None) -> Path:
        payload = self.analysis_variable_diagnostics
        path = Path(out_path) if out_path is not None else _default_analysis_variable_diagnostics_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def build_and_save(self, out_path: str | Path | None = None) -> Path:
        self.build()
        return self.save(out_path)


def build_raw_autotemplate(**kwargs) -> dict:
    return AutoTemplateBuilder(**kwargs).build()
