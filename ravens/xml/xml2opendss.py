"""
xml2opendss.py

Python translation of CDPSM_to_DSS.java (originally Copyright 2009-2011 MelTran, Inc.)

Converts a CIM16 RDF/XML file to OpenDSS input files.

Dependencies:
    pip install rdflib

Usage:
    python xml2opendss.py [options] input.xml output_root
        -t={y|n}            triplex; y/n to include secondary (no effect for OpenDSS)
        -e={u|i}            encoding; UTF-8 or ISO-8859-1
        -f={50|60}          system frequency
        -v={1|0.001}        multiplier that converts voltage to kV for OpenDSS
        -s={1000|1|0.001}   multiplier that converts p,q,s to kVA for OpenDSS
        -q={y|n}            are unique names used?
"""

import sys
import math
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF

# ---------------------------------------------------------------------------
# Namespace constants
# ---------------------------------------------------------------------------
nsCIM = "http://iec.ch/TC57/CIM100#"
nsRDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
baseURI = "http://opendss"

CIM = Namespace(nsCIM)
RDFS = Namespace(nsRDF)

# ---------------------------------------------------------------------------
# Helper class – tracks conductor counts for WireSpacingInfo instances
# ---------------------------------------------------------------------------
class SpacingCount:
    def __init__(self, nconds: int, nphases: int):
        self.nconds = nconds
        self.nphases = nphases

    def get_num_conductors(self) -> int:
        return self.nconds

    def get_num_phases(self) -> int:
        return self.nphases


map_spacings: dict[str, SpacingCount] = {}

# ---------------------------------------------------------------------------
# RDFLib helpers (replace Apache Jena Resource/Property calls)
# ---------------------------------------------------------------------------

def _uri(prop: str) -> URIRef:
    """Build a full CIM property URI."""
    return CIM[prop]


def get_property_value(g: Graph, subject: URIRef, prop: URIRef, default=None):
    """Return the first object of (subject, prop, ?) or default."""
    val = g.value(subject, prop)
    if val is None:
        return default
    return val


def safe_property(g: Graph, subj: URIRef, prop: URIRef, default: str = "") -> str:
    v = get_property_value(g, subj, prop)
    return str(v) if v is not None else default


def safe_phases_x(g: Graph, subj: URIRef, prop: URIRef) -> str:
    v = get_property_value(g, subj, prop)
    if v is not None:
        return str(v)
    return "#PhaseCode.ABCN"


def safe_regulating_mode(g: Graph, subj: URIRef, prop: URIRef, default: str) -> str:
    v = get_property_value(g, subj, prop)
    if v is not None:
        arg = str(v)
        idx = arg.rfind("#RegulatingControlModeKind.")
        if idx >= 0:
            return arg[idx + 27:]
    return default


def dss_cap_mode(s: str) -> str:
    modes = {
        "currentFlow": "current",
        "voltage": "voltage",
        "reactivePower": "kvar",
        "timeScheduled": "time",
        "powerFactor": "pf",
        "userDefined": "time",
    }
    return modes.get(s, "time")


def safe_double(g: Graph, subj: URIRef, prop: URIRef, default: float = 0.0) -> float:
    v = get_property_value(g, subj, prop)
    if v is not None:
        try:
            return float(str(v))
        except ValueError:
            pass
    return default


def safe_int(g: Graph, subj: URIRef, prop: URIRef, default: int = 0) -> int:
    v = get_property_value(g, subj, prop)
    if v is not None:
        try:
            return int(str(v))
        except ValueError:
            pass
    return default


def safe_boolean(g: Graph, subj: URIRef, prop: URIRef, default: bool = False) -> bool:
    v = get_property_value(g, subj, prop)
    if v is not None:
        return str(v).lower() == "true"
    return default


def get_equipment_type(g: Graph, subj: URIRef) -> str:
    rdf_type = g.value(subj, RDF.type)
    if rdf_type is None:
        return "##UNKNOWN##"
    s = str(rdf_type)
    idx = s.rfind("#")
    t = s[idx + 1:] if idx >= 0 else s
    mapping = {
        "LinearShuntCompensator": "capacitor",
        "ACLineSegment": "line",
        "EnergyConsumer": "load",
        "PowerTransformer": "transformer",
    }
    return mapping.get(t, "##UNKNOWN##")


def dss_guid(arg: str) -> str:
    idx = arg.rfind("#_")
    return arg[idx + 2:] if idx >= 0 else arg


def dss_name(arg: str) -> str:
    return arg.replace(' ', '_').replace('.', '_').replace('(', '_').replace(')', '_').replace('=', '_')


def dss_id(arg: str) -> str:
    idx = arg.rfind("#")
    return dss_name(arg[idx + 1:] if idx >= 0 else arg)


def safe_res_name(g: Graph, subj: URIRef, prop_name: URIRef) -> str:
    v = get_property_value(g, subj, prop_name)
    if v is not None:
        return dss_name(str(v))
    # Fall back to local name of the URI
    local = str(subj).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    return dss_name(local)


def safe_resource_lookup(g: Graph, pt_name: URIRef, subj: URIRef, prop: URIRef, default: str) -> str:
    v = get_property_value(g, subj, prop)
    if v is not None:
        res_uri = URIRef(str(v))
        return safe_res_name(g, res_uri, pt_name)
    return default


# ---------------------------------------------------------------------------
# Matrix index helper
# ---------------------------------------------------------------------------

def get_mat_idx(n: int, row: int, col: int) -> int:
    seq = -1
    for j in range(col):
        seq += (n - j)
    for i in range(col, row + 1):
        seq += 1
    return seq


# ---------------------------------------------------------------------------
# Electrical parameter helpers
# ---------------------------------------------------------------------------

def get_ac_line_parameters(g: Graph, subj: URIRef, length: float, freq: float) -> str:
    pt_r1 = CIM["ACLineSegment.r"]
    pt_r0 = CIM["ACLineSegment.r0"]
    pt_x1 = CIM["ACLineSegment.x"]
    pt_x0 = CIM["ACLineSegment.x0"]
    pt_b1 = CIM["ACLineSegment.bch"]
    pt_b0 = CIM["ACLineSegment.b0ch"]

    if get_property_value(g, subj, pt_x1) is not None:
        r1 = safe_double(g, subj, pt_r1, 0) / length
        r0 = safe_double(g, subj, pt_r0, 0) / length
        x1 = safe_double(g, subj, pt_x1, 0) / length
        x0 = safe_double(g, subj, pt_x0, x1 * length) / length
        b0 = safe_double(g, subj, pt_b0, 0) / length
        b1 = safe_double(g, subj, pt_b1, b0 * length) / length
        c0 = 1.0e9 * b0 / freq / 2.0 / math.pi
        c1 = 1.0e9 * b1 / freq / 2.0 / math.pi
        return (f" r1={r1:6g} x1={x1:6g} c1={c1:6g}"
                f" r0={r0:6g} x0={x0:6g} c0={c0:6g}")
    return ""

def get_mat_idx(nphases: int, row: int, col: int) -> int:
    """Convert (row, col) to linear index for lower triangular matrix storage"""
    if row < col:
        row, col = col, row
    return row * (row + 1) // 2 + col

def get_impedance_matrix(g: Graph, pt_name: URIRef, pt_count: URIRef, subj: URIRef, freq: float) -> str:
    pt_data = CIM["PhaseImpedanceData.PhaseImpedance"]
    pt_row  = CIM["PhaseImpedanceData.row"]
    pt_col  = CIM["PhaseImpedanceData.column"]
    pt_r    = CIM["PhaseImpedanceData.r"]
    pt_x    = CIM["PhaseImpedanceData.x"]
    pt_b    = CIM["PhaseImpedanceData.b"]

    omega = 2.0 * 3.141592653589793 * freq  # Angular frequency

    nphases = safe_int(g, subj, pt_count, 0)
    size = sum(nphases - j for j in range(nphases))

    r_mat = [0.0] * size
    x_mat = [0.0] * size
    c_mat = [0.0] * size

    for r_data in g.subjects(pt_data, subj):
        row = safe_int(g, r_data, pt_row, 1) - 1  # convert to zero-based
        col = safe_int(g, r_data, pt_col, 1) - 1  # convert to zero-based
        
        # Calculate linear index for lower triangular storage
        # Ensure row >= col (lower triangle)
        if row < col:
            row, col = col, row
        
        seq = get_mat_idx(nphases, row, col)
        
        if get_property_value(g, r_data, pt_r) is not None:
            r_mat[seq] = safe_double(g, r_data, pt_r, 0)
        if get_property_value(g, r_data, pt_x) is not None:
            x_mat[seq] = safe_double(g, r_data, pt_x, 0)
        if get_property_value(g, r_data, pt_b) is not None:
            c_mat[seq] = safe_double(g, r_data, pt_b, 0) * 1.0e9 / omega

    buf  = f"nphases={nphases}"
    r_buf = " rmatrix=["
    x_buf = " xmatrix=["
    c_buf = " cmatrix=["

    for i in range(nphases):
        for j in range(i + 1):
            seq = get_mat_idx(nphases, i, j)
            r_buf += f"{r_mat[seq]:6g} "
            x_buf += f"{x_mat[seq]:6g} "
            c_buf += f"{c_mat[seq]:6g} "
        if i + 1 < nphases:
            r_buf += "| "
            x_buf += "| "
            c_buf += "| "

    return buf + r_buf + "]" + x_buf + "]" + c_buf + "]"

# ---------------------------------------------------------------------------
# Phase string helpers
# ---------------------------------------------------------------------------

def phase_string(arg: str) -> str:
    idx = arg.rfind("#PhaseCode.")
    return arg[idx + 11:] if idx >= 0 else arg


def phase_kind_string(arg: str) -> str:
    idx = arg.rfind("#SinglePhaseKind.")
    return arg[idx + 17:] if idx >= 0 else arg


def phase_x_count(phs: str, shunt: bool) -> int:
    if phs == "N":
        return 3
    cnt = len(phs)
    if "N" in phs:
        cnt -= 1
    elif shunt:
        if cnt == 2 and "1" not in phs and "2" not in phs:
            cnt = 1
    return cnt


def first_phase(phs: str) -> str:
    if "A" in phs:
        return "1"
    if "B" in phs:
        return "2"
    return "3"


def bus_x_phases(phs: str) -> str:
    if "ABC" in phs:  return ".1.2.3"
    if "AB"  in phs:  return ".1.2"
    if "12"  in phs:  return ".1.2"
    if "AC"  in phs:  return ".1.3"
    if "BC"  in phs:  return ".2.3"
    if "A"   in phs:  return ".1"
    if "B"   in phs:  return ".2"
    if "C"   in phs:  return ".3"
    if "1"   in phs:  return ".1"
    if "2"   in phs:  return ".2"
    return ""  # defaults to 3 phases


def bus_xfmr_phases(arg: str) -> str:
    if "s2" in arg:  return ".0.2"
    if "s1" in arg:  return ".1.0"
    return bus_x_phases(arg)


def bus_phases(arg: str) -> str:
    phs = phase_string(arg)
    return bus_x_phases(phs)


def bus_shunt_phases(phs: str, phs_cnt: int, phs_conn: str) -> str:
    if phs_cnt == 3:
        return ".1.2.3"
    if "w" in phs_conn or "1" in phs or "2" in phs:
        return bus_x_phases(phs)
    if phs_cnt == 1:
        if "A" in phs:  return ".1.2"
        if "B" in phs:  return ".2.3"
        if "C" in phs:  return ".3.1"
    if "AB" in phs:  return ".1.2.3"
    if "AC" in phs:  return ".3.1.2"
    return ".2.3.1"


def shunt_conn(g: Graph, subj: URIRef, prop: URIRef) -> str:
    v = get_property_value(g, subj, prop)
    if v is not None:
        arg = str(v)
        idx = arg.rfind("#PhaseShuntConnectionKind.")
        conn = arg[idx + 26:] if idx >= 0 else arg
        if "D" in conn:
            return "d"
    return "w"


def wire_phases(g: Graph, subj: URIRef, p1: URIRef, p2: URIRef) -> str:
    phases_found = list(g.subjects(p1, subj))
    if phases_found:
        bA = bB = bC = bN = b1 = b2 = False
        for r_p in phases_found:
            v = get_property_value(g, r_p, p2)
            if v is not None:
                s = phase_kind_string(str(v))
                if s == "A":  bA = True
                if s == "B":  bB = True
                if s == "C":  bC = True
                if s == "N":  bN = True
                if s == "s1": b1 = True
                if s == "s2": b2 = True
        buf = ""
        if bA: buf += "A"
        if bB: buf += "B"
        if bC: buf += "C"
        if b1: buf += "1"
        if b2: buf += "2"
        if bN: buf += "N"
        return buf
    return "ABC"


def count_x_phases(phs: str) -> int:
    if "ABC" in phs:  return 3
    if "AB"  in phs:  return 2
    if "AC"  in phs:  return 2
    if "BC"  in phs:  return 2
    if "A"   in phs:  return 1
    if "B"   in phs:  return 1
    if "C"   in phs:  return 1
    return 3


def count_phases(arg: str) -> int:
    phs = phase_string(arg)
    return count_x_phases(arg)


def get_wdg_connection(g: Graph, subj: URIRef, prop: URIRef, default: str) -> str:
    v = get_property_value(g, subj, prop)
    if v is not None:
        arg = str(v)
        idx = arg.rfind("#WindingConnection.")
        return arg[idx + 19:] if idx >= 0 else arg
    return default


def get_prop_value(g: Graph, uri: str, prop: str) -> str:
    res = URIRef(uri)
    p   = CIM[prop]
    v = g.value(res, p)
    return str(v) if v is not None else ""


def get_load_model(g: Graph, r_load: URIRef) -> str:
    pt_response = CIM["EnergyConsumer.LoadResponse"]
    if get_property_value(g, r_load, pt_response) is not None:
        r_model = URIRef(str(g.value(r_load, pt_response)))
        def _d(p): return float(safe_property(g, r_model, CIM[p], "0") or "0")
        Pv = _d("LoadResponseCharacteristic.pVoltageExponent")
        Qv = _d("LoadResponseCharacteristic.qVoltageExponent")
        Pz = _d("LoadResponseCharacteristic.pConstantImpedance")
        Pi = _d("LoadResponseCharacteristic.pConstantCurrent")
        Pp = _d("LoadResponseCharacteristic.pConstantPower")
        Qz = _d("LoadResponseCharacteristic.qConstantImpedance")
        Qi = _d("LoadResponseCharacteristic.qConstantCurrent")
        Qp = _d("LoadResponseCharacteristic.qConstantPower")
        if Pv == 1 and Qv == 2:   return "model=4"
        if Pz == 100 and Qz == 100: return "model=2"
        if Pp == 100 and Qz == 100: return "model=3"
        if Pi == 100 and Qi == 100: return "model=5"
    return "model=1"


def get_bus_name(g: Graph, eq_id: str, seq: int) -> str:
    str_seq = str(seq)
    pt_node  = CIM["Terminal.ConnectivityNode"]
    pt_equip = CIM["Terminal.ConductingEquipment"]
    pt_seq   = CIM["Terminal.sequenceNumber"]
    pt_name  = CIM["IdentifiedObject.name"]

    res_id = URIRef(eq_id)
    idx = 0
    for res in g.subjects(pt_equip, res_id):
        idx += 1
        found = False
        seq_val = get_property_value(g, res, pt_seq)
        if seq_val is not None:
            if str(seq_val) == str_seq:
                found = True
        else:
            if idx == seq:
                found = True

        if found:
            cn_ref = get_property_value(g, res, pt_node)
            if cn_ref is None:
                return "x"
            cn = URIRef(str(cn_ref))
            cn_name = get_property_value(g, cn, pt_name)
            if cn_name is not None:
                return dss_name(str(cn_name))
            else:
                local = str(cn).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                return dss_name(local)
    return "x"


# ---------------------------------------------------------------------------
# Power transformer helpers
# ---------------------------------------------------------------------------

def get_power_transformer_data(g: Graph, xf_id: str, smult: float, vmult: float) -> str:
    pt_xfmr   = CIM["PowerTransformerEnd.PowerTransformer"]
    pt_end_rw  = CIM["PowerTransformerEnd.r"]
    pt_end_c   = CIM["PowerTransformerEnd.connectionKind"]
    pt_end_v   = CIM["PowerTransformerEnd.ratedU"]
    pt_end_s   = CIM["PowerTransformerEnd.ratedS"]
    pt_end_grnd = CIM["TransformerEnd.grounded"]
    pt_end_rn  = CIM["TransformerEnd.rground"]
    pt_end_xn  = CIM["TransformerEnd.xground"]
    pt_end_n   = CIM["TransformerEnd.endNumber"]

    r_xf = URIRef(xf_id)
    ends = list(g.subjects(pt_xfmr, r_xf))
    nwdg = len(ends)

    v   = [0.0] * nwdg
    s   = [0.0] * nwdg
    zb  = [0.0] * nwdg
    rw  = [0.0] * nwdg
    rn  = [0.0] * nwdg
    xn  = [0.0] * nwdg
    wye = ["Y"] * nwdg
    r_ends = [None] * nwdg

    for r_end in ends:
        i = safe_int(g, r_end, pt_end_n, 1) - 1
        v[i]  = vmult * safe_double(g, r_end, pt_end_v, 1.0 / vmult)
        s[i]  = smult * safe_double(g, r_end, pt_end_s, 1.0 / smult)
        zb[i] = 1000.0 * v[i] * v[i] / s[i]
        rw[i] = 100.0 * safe_double(g, r_end, pt_end_rw, 0.0) / zb[i]
        rn[i] = safe_double(g, r_end, pt_end_rn, 0.0)
        xn[i] = safe_double(g, r_end, pt_end_xn, 0.0)
        wye[i] = get_wdg_connection(g, r_end, pt_end_c, "Y")
        r_ends[i] = r_end

    buf_u = " kvs=["
    buf_s = " kvas=["
    buf_c = " conns=["
    buf_r = " %Rs=["
    for i in range(nwdg):
        sep = "," if i < nwdg - 1 else "]"
        buf_u += f"{v[i]:6g}{sep}"
        buf_s += f"{s[i]:6g}{sep}"
        buf_c += f"{wye[i]}{sep}"
        buf_r += f"{rw[i]:6g}{sep}"

    pt_from   = CIM["TransformerMeshImpedance.FromTransformerEnd"]
    pt_to     = CIM["TransformerMeshImpedance.ToTransformerEnd"]
    pt_mesh_x = CIM["TransformerMeshImpedance.x"]

    buf_x = f" %imag={0.0:6g} %noloadloss={0.0:6g}"
    for r_mesh in g.subjects(pt_from, r_ends[0]):
        r_to_ref = get_property_value(g, r_mesh, pt_to)
        r_to = URIRef(str(r_to_ref))
        x = 100.0 * safe_double(g, r_mesh, pt_mesh_x, 1.0) / zb[0]
        if r_to == r_ends[1]:
            buf_x += f" Xhl={x:6g}"
        else:
            buf_x += f" Xht={x:6g}"

    if nwdg > 2:
        for r_mesh in g.subjects(pt_from, r_ends[1]):
            r_to_ref = get_property_value(g, r_mesh, pt_to)
            r_to = URIRef(str(r_to_ref))
            x = 100.0 * safe_double(g, r_mesh, pt_mesh_x, 1.0) / zb[1]
            if r_to == r_ends[2]:
                buf_x += f" Xlt={x:6g}"
            else:
                buf_x += f" ***** too many windings *****{x:6g}"

    return f" phases=3 windings={nwdg}" + buf_x + buf_u + buf_s + buf_c + buf_r


def get_winding_buses(g: Graph, xf_id: str) -> str:
    pt_xfmr = CIM["PowerTransformerEnd.PowerTransformer"]
    pt_end  = CIM["TransformerEnd.endNumber"]
    pt_term = CIM["TransformerEnd.Terminal"]
    pt_phs  = CIM["ConductingEquipment.phases"]
    pt_node = CIM["Terminal.ConnectivityNode"]
    pt_name = CIM["IdentifiedObject.name"]

    xf_res = URIRef(xf_id)
    ends = list(g.subjects(pt_xfmr, xf_res))
    nwdg = len(ends)
    bus = [""] * nwdg
    phs = [""] * nwdg

    for wdg in ends:
        i = safe_int(g, wdg, pt_end, 1) - 1
        trm_ref = get_property_value(g, wdg, pt_term)
        trm = URIRef(str(trm_ref))
        phs[i] = safe_phases_x(g, trm, pt_phs)
        cn_ref = get_property_value(g, trm, pt_node)
        cn = URIRef(str(cn_ref))
        cn_name = get_property_value(g, cn, pt_name)
        bus[i] = dss_name(str(cn_name)) if cn_name else dss_name(str(cn).rsplit("#", 1)[-1])

    buf = "["
    for i in range(nwdg):
        buf += bus[i] + bus_phases(phs[i])
        buf += "," if i < nwdg - 1 else "]"
    return buf


def get_tank_buses_and_phase_count(g: Graph, xf_res: URIRef, b_xfmr_code: bool) -> str:
    pt_xfmr = CIM["TransformerTankEnd.TransformerTank"]
    pt_end  = CIM["TransformerEnd.endNumber"]
    pt_term = CIM["TransformerEnd.Terminal"]
    pt_phs  = CIM["TransformerTankEnd.phases"]
    pt_node = CIM["Terminal.ConnectivityNode"]
    pt_name = CIM["IdentifiedObject.name"]

    ends = list(g.subjects(pt_xfmr, xf_res))
    nwdg = len(ends)
    bus   = [""] * nwdg
    phs_a = [""] * nwdg
    nphase = 3

    for wdg in ends:
        i = safe_int(g, wdg, pt_end, 1) - 1
        trm_ref = get_property_value(g, wdg, pt_term)
        trm = URIRef(str(trm_ref))
        raw = safe_phases_x(g, wdg, pt_phs)
        phs_a[i] = phase_string(raw)
        n = count_x_phases(phs_a[i])
        if n < nphase:
            nphase = n
        cn_ref = get_property_value(g, trm, pt_node)
        cn = URIRef(str(cn_ref))
        cn_name = get_property_value(g, cn, pt_name)
        bus[i] = dss_name(str(cn_name)) if cn_name else dss_name(str(cn).rsplit("#", 1)[-1])

    if b_xfmr_code:
        buf = " buses=["
    else:
        buf = f" windings={nwdg} phases={nphase} buses=["

    for i in range(nwdg):
        buf += bus[i] + bus_xfmr_phases(phs_a[i])
        buf += "," if i < nwdg - 1 else "]"

    buf += " //"
    for i in range(nwdg):
        buf += " " + phs_a[i]
    return buf


def get_tank_buses_and_xfmr_code(g: Graph, r_tank: URIRef, r_ds: URIRef) -> str:
    pt_name = CIM["IdentifiedObject.name"]
    xf_name = safe_property(g, r_ds, pt_name, "")
    buf = f" xfmrcode={xf_name}"
    buf += get_tank_buses_and_phase_count(g, r_tank, True)
    return buf


# ---------------------------------------------------------------------------
# Line spacing
# ---------------------------------------------------------------------------

def get_line_spacing(g: Graph, r_line: URIRef) -> str:
    buf = " spacing="
    pt_asset_psr = CIM["Asset.PowerSystemResources"]
    pt_asset_inf = CIM["Asset.AssetInfo"]
    pt_name      = CIM["IdentifiedObject.name"]

    nconds = 0
    nphases = 0
    b_cn_cables = False
    b_ts_cables = False
    ws_name = ""
    wire_name = ""

    for r_asset in g.subjects(pt_asset_psr, r_line):
        if get_property_value(g, r_asset, pt_asset_inf) is not None:
            r_ds_ref = get_property_value(g, r_asset, pt_asset_inf)
            r_ds = URIRef(str(r_ds_ref))
            rdf_type = g.value(r_ds, RDF.type)
            if rdf_type is None:
                continue
            s = str(rdf_type)
            idx = s.rfind("#")
            t = s[idx + 1:] if idx >= 0 else s

            if t == "WireSpacingInfo":
                ws_name = safe_res_name(g, r_ds, pt_name)
                buf += ws_name
                spc = map_spacings.get(ws_name)
                if spc:
                    nconds  = spc.get_num_conductors()
                    nphases = spc.get_num_phases()
            elif t == "OverheadWireInfo":
                wire_name = safe_res_name(g, r_ds, pt_name)
            elif t == "ConcentricNeutralCableInfo":
                b_cn_cables = True
                wire_name = safe_res_name(g, r_ds, pt_name)
            elif t == "TapeShieldCableInfo":
                b_ts_cables = True
                wire_name = safe_res_name(g, r_ds, pt_name)

    if nconds > 0:
        pt_segment = CIM["ACLineSegmentPhase.ACLineSegment"]
        pt_phase   = CIM["ACLineSegmentPhase.phase"]

        wA = wB = wC = wN = wS1 = wS2 = wS = ""

        for r_p in g.subjects(pt_segment, r_line):
            if get_property_value(g, r_p, pt_phase) is not None:
                s_phase = phase_kind_string(str(g.value(r_p, pt_phase)))
                for r_asset in g.subjects(pt_asset_psr, r_p):
                    if get_property_value(g, r_asset, pt_asset_inf) is not None:
                        r_ds_ref = get_property_value(g, r_asset, pt_asset_inf)
                        r_ds = URIRef(str(r_ds_ref))
                        rdf_type = g.value(r_ds, RDF.type)
                        if rdf_type is None:
                            continue
                        s = str(rdf_type)
                        idx = s.rfind("#")
                        t = s[idx + 1:] if idx >= 0 else s
                        if t == "ConcentricNeutralCableInfo": b_cn_cables = True
                        if t == "TapeShieldCableInfo":        b_ts_cables = True
                        wS = safe_res_name(g, r_ds, pt_name)
                        if s_phase == "A":  wA = wS
                        if s_phase == "B":  wB = wS
                        if s_phase == "C":  wC = wS
                        if s_phase == "N":  wN = wS
                        if s_phase == "s1": wS1 = wS
                        if s_phase == "s2": wS2 = wS

        if b_cn_cables:
            cable_tag = " CNcables=["
        elif b_ts_cables:
            cable_tag = " TScables=["
        else:
            cable_tag = " wires=["

        if len(wS) < 1:
            buf += cable_tag + (wire_name + " ") * nconds + "]"
        else:
            buf += cable_tag
            for w in [wA, wB, wC, wS1, wS2]:
                if w: buf += w + " "
            if not (b_cn_cables or b_ts_cables):
                buf += (wN + " ") * (nconds - nphases)
            buf += "]"
            if nconds > nphases and (b_cn_cables or b_ts_cables):
                buf += " wires=["
                buf += (wN + " ") * (nconds - nphases)
                buf += "]"
        return buf
    return ""


# ---------------------------------------------------------------------------
# Tank transformer data
# ---------------------------------------------------------------------------

def get_tank_data(g: Graph, r_tank: URIRef, smult: float, vmult: float) -> str:
    pt_xfmr      = CIM["TransformerTankEnd.TransformerTank"]
    pt_asset_psr = CIM["Asset.PowerSystemResources"]
    pt_asset_inf = CIM["Asset.AssetInfo"]
    pt_inf2      = CIM["TransformerEndInfo.TransformerTankInfo"]
    pt_end_grnd  = CIM["TransformerEnd.grounded"]
    pt_end_rn    = CIM["TransformerEnd.rground"]
    pt_end_xn    = CIM["TransformerEnd.xground"]
    pt_end_n     = CIM["TransformerEnd.endNumber"]
    pt_inf_r     = CIM["TransformerEndInfo.r"]
    pt_inf_n     = CIM["TransformerEndInfo.endNumber"]
    pt_inf_c     = CIM["TransformerEndInfo.connectionKind"]
    pt_inf_v     = CIM["TransformerEndInfo.ratedU"]
    pt_inf_s     = CIM["TransformerEndInfo.ratedS"]

    ends = list(g.subjects(pt_xfmr, r_tank))
    nwdg = len(ends)

    v   = [1.0] * nwdg
    s   = [1.0] * nwdg
    r   = [0.0] * nwdg
    x   = [0.01] * nwdg
    zb  = [1.0] * nwdg
    gg  = [0.0] * nwdg
    b   = [0.0] * nwdg
    rn  = [0.0] * nwdg
    xn  = [0.0] * nwdg
    wye = ["W"] * nwdg

    # datasheet values
    for r_asset in g.subjects(pt_asset_psr, r_tank):
        if get_property_value(g, r_asset, pt_asset_inf) is not None:
            r_ds_ref = get_property_value(g, r_asset, pt_asset_inf)
            r_ds = URIRef(str(r_ds_ref))
            for r_end in g.subjects(pt_inf2, r_ds):
                if get_property_value(g, r_end, pt_inf_n) is not None:
                    i = safe_int(g, r_end, pt_inf_n, 1) - 1
                    v[i]   = safe_double(g, r_end, pt_inf_v, v[i])
                    s[i]   = safe_double(g, r_end, pt_inf_s, s[i])
                    r[i]   = safe_double(g, r_end, pt_inf_r, r[i])
                    wye[i] = get_wdg_connection(g, r_end, pt_inf_c, wye[i])

    for r_end in ends:
        i = safe_int(g, r_end, pt_end_n, 1) - 1
        rn[i] = safe_double(g, r_end, pt_end_rn, rn[i])
        xn[i] = safe_double(g, r_end, pt_end_xn, xn[i])

    buf_u = " kvs=["
    buf_s = " kvas=["
    buf_c = " conns=["
    buf_r = " %Rs=["
    max_b = 0.0
    max_g = 0.0

    for i in range(nwdg):
        s[i]  *= smult
        v[i]  *= vmult
        zb[i]  = 1000.0 * v[i] * v[i] / s[i]
        r[i]   = 100.0 * r[i] / zb[i]
        x[i]   = 100.0 * x[i] / zb[i]
        gg[i]  = 100.0 * gg[i] * zb[i]
        b[i]   = 100.0 * b[i]  * zb[i]
        if gg[i] > max_g: max_g = gg[i]
        if b[i]  > max_b: max_b = b[i]
        sep = "," if i < nwdg - 1 else "]"
        buf_u += f"{v[i]:6g}{sep}"
        buf_s += f"{s[i]:6g}{sep}"
        buf_c += f"{wye[i]}{sep}"
        buf_r += f"{r[i]:6g}{sep}"

    buf_x = f" %imag={max_b:6g} %noloadloss={max_g:6g}"
    try: 
        buf_x += f" Xhl={x[0]+x[1]:6g}"
    except:
        print("Do nothing")
    if nwdg > 2:
        buf_x += f" Xht={x[0]+x[2]:6g}"
        buf_x += f" Xlt={x[1]+x[2]:6g}"
    return buf_x + buf_u + buf_s + buf_c + buf_r


# ---------------------------------------------------------------------------
# Regulator data
# ---------------------------------------------------------------------------

def get_regulator_data(g: Graph, reg: URIRef) -> str:
    buf = ""
    pt_end  = CIM["RatioTapChanger.TransformerEnd"]
    pt_wdg  = CIM["TransformerEnd.endNumber"]
    pt_tank = CIM["TransformerTankEnd.TransformerTank"]
    pt_xf   = CIM["TransformerTank.PowerTransformer"]
    pt_name = CIM["IdentifiedObject.name"]
    pt_tap  = CIM["TapChanger.step"]

    r_end_ref = get_property_value(g, reg, pt_end)
    r_end = URIRef(str(r_end_ref))
    n_wdg = safe_int(g, r_end, pt_wdg, 1)
    d_tap = safe_double(g, reg, pt_tap, 1.0)
    r_tank_ref = get_property_value(g, r_end, pt_tank)
    r_tank = URIRef(str(r_tank_ref))
    xf_name = safe_property(g, r_tank, pt_name, "")

    buf += f" transformer={xf_name} winding={n_wdg}"

    # asset datasheet
    ct = 1.0
    pt_val = 1.0
    pt_asset_psr = CIM["Asset.PowerSystemResources"]
    pt_asset_inf = CIM["Asset.AssetInfo"]
    pt_pt   = CIM["TapChangerInfo.ptRatio"]
    pt_ct   = CIM["TapChangerInfo.ctRating"]

    for r_asset in g.subjects(pt_asset_psr, reg):
        if get_property_value(g, r_asset, pt_asset_inf) is not None:
            r_ds_ref = get_property_value(g, r_asset, pt_asset_inf)
            r_ds = URIRef(str(r_ds_ref))
            ct     = safe_double(g, r_ds, pt_ct, 1.0)
            pt_val = safe_double(g, r_ds, pt_pt, 1.0)

    pt_ctl  = CIM["TapChanger.TapChangerControl"]
    pt_band = CIM["RegulatingControl.targetDeadband"]
    pt_set  = CIM["RegulatingControl.targetValue"]
    pt_r    = CIM["TapChangerControl.lineDropR"]
    pt_x    = CIM["TapChangerControl.lineDropX"]

    ctl_ref = get_property_value(g, reg, pt_ctl)
    ctl = URIRef(str(ctl_ref))
    ldc_r = safe_double(g, ctl, pt_r, 0.0)
    ldc_x = safe_double(g, ctl, pt_x, 0.0)
    vreg  = safe_double(g, ctl, pt_set, 120.0)
    vband = safe_double(g, ctl, pt_band, 2.0)

    buf += (f" ctprim={ct:6g} ptratio={pt_val:6g}"
            f" vreg={vreg:6g} band={vband:6g}"
            f" r={ldc_r:6g} x={ldc_x:6g}")
    buf += f"\nedit transformer.{xf_name} wdg={n_wdg} tap={d_tap:6g}"
    return buf


# ---------------------------------------------------------------------------
# Wire data
# ---------------------------------------------------------------------------

def get_wire_data(g: Graph, res: URIRef) -> str:
    pt_gmr      = CIM["WireInfo.gmr"]
    pt_radius   = CIM["WireInfo.radius"]
    pt_diameter = CIM["WireInfo.diameter"]
    pt_current  = CIM["WireInfo.ratedCurrent"]
    pt_r25      = CIM["WireInfo.rAC25"]
    pt_r50      = CIM["WireInfo.rAC50"]
    pt_r75      = CIM["WireInfo.rAC75"]
    pt_rdc      = CIM["WireInfo.rDC20"]

    norm_amps = safe_double(g, res, pt_current, 0.0)
    radius    = safe_double(g, res, pt_radius, 0.0)
    if radius <= 0:
        radius = 0.5 * safe_double(g, res, pt_diameter, 0.0)
    gmr = safe_double(g, res, pt_gmr, 0.0)
    if gmr <= 0:
        gmr = 0.7788 * radius

    wire_rac = safe_double(g, res, pt_r50, 0.0)
    if wire_rac <= 0: wire_rac = safe_double(g, res, pt_r25, 0.0)
    if wire_rac <= 0: wire_rac = safe_double(g, res, pt_r75, 0.0)
    wire_rdc = safe_double(g, res, pt_rdc, 0.0)
    if wire_rdc <= 0:
        wire_rdc = wire_rac
    elif wire_rac <= 0:
        wire_rac = wire_rdc

    return (f" gmr={gmr:6g} radius={radius:6g}"
            f" rac={wire_rac:6g} rdc={wire_rdc:6g}"
            f" normamps={norm_amps:6g}"
            f" Runits=m Radunits=m gmrunits=m")


def get_cable_data(g: Graph, res: URIRef) -> str:
    pt_over_ins    = CIM["CableInfo.diameterOverInsulation"]
    pt_over_jacket = CIM["CableInfo.diameterOverJacket"]
    pt_ins_layer   = CIM["WireInfo.insulationThickness"]

    d_ins    = safe_double(g, res, pt_over_ins, 0.0)
    d_jacket = safe_double(g, res, pt_over_jacket, 0.0)
    t_ins    = safe_double(g, res, pt_ins_layer, 0.0)
    d_eps    = 2.3  # default relative permittivity

    return (f"\n~ EpsR={d_eps:6g} Ins={t_ins:6g}"
            f" DiaIns={d_ins:6g} DiaCable={d_jacket:6g}")


# ---------------------------------------------------------------------------
# Cap control data
# ---------------------------------------------------------------------------

def get_cap_control_data(g: Graph, ctl: URIRef) -> str:
    buf = ""
    pt_cap      = CIM["RegulatingControl.RegulatingCondEq"]
    pt_term     = CIM["RegulatingControl.Terminal"]
    pt_mode     = CIM["RegulatingControl.mode"]
    pt_phase    = CIM["RegulatingControl.monitoredPhase"]
    pt_bw       = CIM["RegulatingControl.targetDeadband"]
    pt_val      = CIM["RegulatingControl.targetValue"]
    pt_mult     = CIM["RegulatingControl.targetValueUnitMultiplier"]
    pt_name     = CIM["IdentifiedObject.name"]
    pt_avr_delay = CIM["ShuntCompensator.aVRDelay"]

    r_cap_ref = get_property_value(g, ctl, pt_cap)
    r_cap = URIRef(str(r_cap_ref))
    cap_name  = safe_res_name(g, r_cap, pt_name)
    delay     = safe_double(g, r_cap, pt_avr_delay, 10.0)
    s_phase   = phase_string(safe_phases_x(g, ctl, pt_phase))
    s_mode    = safe_regulating_mode(g, ctl, pt_mode, "voltage")
    d_bw      = safe_double(g, ctl, pt_bw, 1.0)
    d_val     = safe_double(g, ctl, pt_val, 120.0)
    d_mult    = safe_double(g, ctl, pt_mult, 1.0)
    if s_mode == "reactivePower":
        d_mult /= 1000.0
    d_on  = d_mult * (d_val - 0.5 * d_bw)
    d_off = d_mult * (d_val + 0.5 * d_bw)

    pt_cond_eq = CIM["Terminal.ConductingEquipment"]
    r_term_ref = get_property_value(g, ctl, pt_term)
    r_term = URIRef(str(r_term_ref))
    r_cond_eq = URIRef(str(get_property_value(g, r_term, pt_cond_eq)))
    s_eq_type = get_equipment_type(g, r_cond_eq)

    n_term = 0
    s_match = safe_res_name(g, r_term, pt_name)
    for r in g.subjects(pt_cond_eq, r_cond_eq):
        n_term += 1
        if safe_res_name(g, r, pt_name) == s_match:
            break

    buf += (f" capacitor={cap_name}"
            f" type={dss_cap_mode(s_mode)}"
            f" on={d_on:6g} off={d_off:6g}"
            f" delay={delay:6g} delayoff={delay:6g}"
            f" element={s_eq_type}.{safe_res_name(g, r_cond_eq, pt_name)}"
            f" terminal={n_term}"
            f" ptratio=1 ptphase={first_phase(s_phase)}")
    return buf


# ---------------------------------------------------------------------------
# XfmrCode
# ---------------------------------------------------------------------------

def get_xfmr_code(g: Graph, xfmr_id: str, smult: float, vmult: float) -> str:
    pt_info  = CIM["TransformerEndInfo.TransformerTankInfo"]
    pt_n     = CIM["TransformerEndInfo.endNumber"]
    pt_u     = CIM["TransformerEndInfo.ratedU"]
    pt_s     = CIM["TransformerEndInfo.ratedS"]
    pt_r     = CIM["TransformerEndInfo.r"]
    pt_c     = CIM["TransformerEndInfo.connectionKind"]
    pt_from  = CIM["ShortCircuitTest.EnergisedEnd"]
    pt_to    = CIM["ShortCircuitTest.GroundedEnds"]
    pt_zsc   = CIM["ShortCircuitTest.leakageImpedance"]
    pt_end   = CIM["NoLoadTest.EnergisedEnd"]
    pt_nll   = CIM["NoLoadTest.loss"]
    pt_imag  = CIM["NoLoadTest.excitingCurrent"]

    xf_res = URIRef(xfmr_id)
    windings = list(g.subjects(pt_info, xf_res))
    n_windings = len(windings)

    d_u   = [0.0] * n_windings
    d_s   = [0.0] * n_windings
    d_r   = [0.0] * n_windings
    s_c   = ["Y"] * n_windings
    d_nll = 0.0
    d_imag = 0.0
    d_xhl = 0.0
    d_xlt = 0.0
    d_xht = 0.0
    s_phases = "phases=3 "

    for wdg in windings:
        i1 = safe_int(g, wdg, pt_n, 1) - 1
        d_u[i1] = vmult * safe_double(g, wdg, pt_u, 1)
        d_s[i1] = smult * safe_double(g, wdg, pt_s, 1)
        d_r[i1] = safe_double(g, wdg, pt_r, 0)
        z_base  = 1000.0 * d_u[i1] * d_u[i1] / d_s[i1]
        d_r[i1] = 100.0 * d_r[i1] / z_base
        s_c[i1] = get_wdg_connection(g, wdg, pt_c, "Y")
        if s_c[i1] == "I":
            s_phases = "phases=1 "
            s_c[i1] = "Y"

        for test in g.subjects(pt_from, wdg):
            d_xsc   = safe_double(g, test, pt_zsc, 0.0001)
            wdg2_ref = get_property_value(g, test, pt_to)
            if wdg2_ref is not None:
                wdg2 = URIRef(str(wdg2_ref))
                i2 = safe_int(g, wdg2, pt_n, 0) - 1
                d_xsc = 100.0 * d_xsc / z_base
                if (i1 == 0 and i2 == 1) or (i1 == 1 and i2 == 0): d_xhl = d_xsc
                if (i1 == 0 and i2 == 2) or (i1 == 2 and i2 == 0): d_xht = d_xsc
                if (i1 == 1 and i2 == 2) or (i1 == 2 and i2 == 1): d_xlt = d_xsc

        for test in g.subjects(pt_end, wdg):
            d_nll  = safe_double(g, test, pt_nll, 0)
            d_imag = safe_double(g, test, pt_imag, 0)
            d_nll  = 100 * d_nll / (1000.0 * d_s[i1])

    if d_xhl <= 0.0:
        d_xhl = 1.0

    buf = f"windings={n_windings} {s_phases}"
    buf += " kvas=[" + " ".join(f"{v:6g}" for v in d_s) + "]"
    buf += " kvs=["  + " ".join(f"{v:6g}" for v in d_u) + "]"
    buf += " conns=[" + " ".join(s_c) + "]"
    buf += f" xhl={d_xhl:6g}"
    if d_xht > 0.0: buf += f" xht={d_xht:6g}"
    if d_xlt > 0.0: buf += f" xlt={d_xlt:6g}"
    buf += " %Rs=[" + " ".join(f"{v:6g}" for v in d_r) + "]"
    buf += f" %imag={d_imag:6g} %noloadloss={d_nll:6g}"
    return buf


# ---------------------------------------------------------------------------
# Bus position
# ---------------------------------------------------------------------------

def get_bus_position_string(g: Graph, bus_id: str) -> str:
    pt_x       = CIM["PositionPoint.xPosition"]
    pt_y       = CIM["PositionPoint.yPosition"]
    pt_pos_seq = CIM["PositionPoint.sequenceNumber"]
    pt_loc     = CIM["PositionPoint.Location"]
    pt_geo     = CIM["PowerSystemResource.Location"]
    pt_node    = CIM["Terminal.ConnectivityNode"]
    pt_trm_seq = CIM["Terminal.sequenceNumber"]
    pt_equip   = CIM["Terminal.ConductingEquipment"]
    pt_xfmr    = CIM["DistributionTransformerWinding.Transformer"]
    pt_bank    = CIM["DistributionTransformer.TransformerBank"]
    pt_cont    = CIM["Equipment.EquipmentContainer"]
    pt_sub     = CIM["VoltageLevel.Substation"]

    bus = URIRef(bus_id)
    geo = None
    ref_geo = None
    trm_seq = "1"

    for trm in g.subjects(pt_node, bus):
        eq_ref = get_property_value(g, trm, pt_equip)
        if eq_ref is None:
            continue
        eq = URIRef(str(eq_ref))
        if get_property_value(g, eq, pt_geo) is not None:
            geo = URIRef(str(g.value(eq, pt_geo)))
            trm_seq = safe_property(g, trm, pt_trm_seq, "1")
            break
        elif get_property_value(g, eq, pt_xfmr) is not None:
            xf_ref = get_property_value(g, eq, pt_xfmr)
            xf = URIRef(str(xf_ref))
            if get_property_value(g, xf, pt_bank) is not None:
                bank_ref = get_property_value(g, xf, pt_bank)
                bank = URIRef(str(bank_ref))
                if get_property_value(g, bank, pt_geo) is not None:
                    ref_geo = URIRef(str(g.value(bank, pt_geo)))
        elif get_property_value(g, eq, pt_cont) is not None:
            rcont_ref = get_property_value(g, eq, pt_cont)
            rcont = URIRef(str(rcont_ref))
            if get_property_value(g, rcont, pt_geo) is not None:
                ref_geo = URIRef(str(g.value(rcont, pt_geo)))
            elif get_property_value(g, rcont, pt_sub) is not None:
                rsub_ref = get_property_value(g, rcont, pt_sub)
                rsub = URIRef(str(rsub_ref))
                if get_property_value(g, rsub, pt_geo) is not None:
                    ref_geo = URIRef(str(g.value(rsub, pt_geo)))

    if geo is None:
        geo = ref_geo

    if geo is not None:
        pos = None
        for p in g.subjects(pt_loc, geo):
            pos = p
            seq_val = get_property_value(g, p, pt_pos_seq)
            if seq_val is not None and str(seq_val) == trm_seq:
                x = safe_property(g, p, pt_x, "")
                y = safe_property(g, p, pt_y, "")
                return f"{x}, {y}"
        if pos is not None:
            x = safe_property(g, pos, pt_x, "")
            y = safe_property(g, pos, pt_y, "")
            return f"{x}, {y}"
    return ""


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def find_conductor_amps(g: Graph, res: URIRef, pt_datasheet: URIRef, pt_amps: URIRef) -> str:
    i_min = 1.0
    ds_ref = get_property_value(g, res, pt_datasheet)
    if ds_ref is not None:
        r_inf = URIRef(str(ds_ref))
        i_val = safe_double(g, r_inf, pt_amps, 0.0)
        if i_val > i_min:
            i_min = i_val
    return f" normamps={i_min:6g}"


def find_base_voltage(g: Graph, res: URIRef,
                      pt_equip: URIRef, pt_eq_base_v: URIRef,
                      pt_lev_base_v: URIRef, pt_base_nom_v: URIRef) -> float:
    r_base = None
    if get_property_value(g, res, pt_eq_base_v) is not None:
        r_base = URIRef(str(g.value(res, pt_eq_base_v)))
    elif get_property_value(g, res, pt_equip) is not None:
        r_equip_ref = get_property_value(g, res, pt_equip)
        r_equip = URIRef(str(r_equip_ref))
        if get_property_value(g, r_equip, pt_eq_base_v) is not None:
            r_base = URIRef(str(g.value(r_equip, pt_eq_base_v)))
        elif get_property_value(g, r_equip, pt_lev_base_v) is not None:
            r_base = URIRef(str(g.value(r_equip, pt_lev_base_v)))
    if r_base is not None:
        return safe_double(g, r_base, pt_base_nom_v, 1.0)
    return 1.0


# ---------------------------------------------------------------------------
# SPARQL-like queries via RDFLib (iterate over typed subjects)
# ---------------------------------------------------------------------------

def subjects_of_type(g: Graph, cim_type: str):
    """Yield all subjects with rdf:type = CIM.<cim_type>."""
    type_uri = CIM[cim_type]
    for s in g.subjects(RDF.type, type_uri):
        yield s


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    f_name = ""
    f_out  = ""
    f_bus  = ""
    f_guid = ""
    f_enc  = "utf-8"
    freq   = 60.0
    vmult  = 0.001
    smult  = 0.001
    f_in_file  = 0
    f_name_seq = 0
    b_want_sec = True

    args = sys.argv[1:]
    if len(args) < 2:
        print("Usage: cdpsm_to_dss.py [options] input.xml output_root")
        print("       -t={y|n}            triplex; include secondary")
        print("       -e={u|i}            encoding; UTF-8 or ISO-8859-1")
        print("       -f={50|60}          system frequency")
        print("       -v={1|0.001}        voltage multiplier to kV")
        print("       -s={1000|1|0.001}   power multiplier to kVA")
        print("       -q={y|n}            are unique names used?")
        sys.exit(1)

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            opt = arg[1]
            opt_val = arg[3:] if len(arg) > 3 else ""
            if opt == 't':
                b_want_sec = opt_val[0] != 'n'
            elif opt == 'e':
                f_enc = "utf-8" if opt_val[0] == 'u' else "iso-8859-1"
            elif opt == 'q':
                f_name_seq = 0 if opt_val[0] == 'y' else 1
            elif opt == 'f':
                freq = float(opt_val)
            elif opt == 'v':
                vmult = float(opt_val)
            elif opt == 's':
                smult = float(opt_val)
        elif f_in_file < 1:
            f_in_file = 1
            f_name = arg
        else:
            f_out  = arg + "_base.dss"
            f_bus  = arg + "_busxy.dss"
            f_guid = arg + "_guids.dss"
        i += 1

    print(f"{f_enc} f={freq:6g} v={vmult:6g} s={smult:6g}")

    # Load the RDF model
    g = Graph()
    g.parse(f_name, format="xml")

    pt_name       = CIM["IdentifiedObject.name"]
    pt_open       = CIM["Switch.normalOpen"]
    pt_eq_base_v  = CIM["ConductingEquipment.BaseVoltage"]
    pt_lev_base_v = CIM["VoltageLevel.BaseVoltage"]
    pt_equip      = CIM["Equipment.EquipmentContainer"]
    pt_base_nom_v = CIM["BaseVoltage.nominalVoltage"]

    with (open(f_out,  "w", encoding=f_enc) as out,
          open(f_bus,  "w", encoding=f_enc) as out_bus,
          open(f_guid, "w", encoding=f_enc) as out_guid):

        # ------------------------------------------------------------------
        # ConnectivityNode => bus coordinates
        # ------------------------------------------------------------------
        for s in subjects_of_type(g, "ConnectivityNode"):
            bus_id   = str(s)
            res      = s
            name     = safe_res_name(g, res, pt_name)
            str_pos  = get_bus_position_string(g, bus_id)
            if str_pos:
                out_bus.write(f"{name}, {str_pos}\n")
            else:
                out_bus.write(f"// {name}, *****\n")
        out_bus.write("\n")

        # ------------------------------------------------------------------
        # EnergySource => Circuit / Vsource
        # ------------------------------------------------------------------
        num_circuits = 0
        num_sources  = 0
        out.write("clear\n")

        pt_es_r0    = CIM["EnergySource.r0"]
        pt_es_r1    = CIM["EnergySource.r"]
        pt_es_x0    = CIM["EnergySource.x0"]
        pt_es_x1    = CIM["EnergySource.x"]
        pt_es_vnom  = CIM["EnergySource.nominalVoltage"]
        pt_es_vmag  = CIM["EnergySource.voltageMagnitude"]
        pt_es_vang  = CIM["EnergySource.voltageAngle"]

        for res in subjects_of_type(g, "EnergySource"):
            num_sources += 1
            source_id = str(res)
            name    = dss_name(safe_property(g, res, pt_name, "source"))
            ckt_ref = get_property_value(g, res, pt_equip)

            vmag = vmult * safe_double(g, res, pt_es_vmag, 1.0)
            vnom = vmult * safe_double(g, res, pt_es_vnom, vmag / vmult)
            vang = safe_double(g, res, pt_es_vang, 0.0) * 57.3
            r0   = safe_double(g, res, pt_es_r0, 0.0)
            r1   = safe_double(g, res, pt_es_r1, 0.0)
            x1   = safe_double(g, res, pt_es_x1, 0.001)
            x0   = safe_double(g, res, pt_es_x0, x1)
            vpu  = vmag / vnom if vnom else 1.0

            bus1 = get_bus_name(g, source_id, 1)

            src_class = "Vsource."
            if num_circuits < 1:
                src_class = "Circuit."
                if ckt_ref is not None:
                    name = dss_name(get_prop_value(g, str(ckt_ref), "IdentifiedObject.name"))
                num_circuits = 1
            elif name == "source":
                name = "_" + name

            out.write(f"new {src_class}{name} phases=3 bus1={bus1}"
                      f" basekv={vnom:6g} pu={vpu:6g} angle={vang:6g}"
                      f" r0={r0:6g} r1={r1:6g} x0={x0:6g} x1={x1:6g}\n")
            out_guid.write(f"{src_class}{name}\t{dss_guid(source_id)}\n")

        if num_circuits < 1:
            for res in subjects_of_type(g, "Breaker"):
                breaker_id = str(res)
                bus1 = get_bus_name(g, breaker_id, 1)
                name = safe_res_name(g, res, pt_name)
                out.write(f"new Circuit.{name} phases=3 bus1={bus1} basekv=1\n")
                break  # only first breaker

        out.write(f"// set frequency={freq:6g}\n")

        # ------------------------------------------------------------------
        # SynchronousMachine => Generator
        # ------------------------------------------------------------------
        out.write("\n")
        pt_gen_s   = CIM["GeneratingUnit.ratedNetMaxP"]
        pt_gen_p   = CIM["GeneratingUnit.initialP"]
        pt_gen_ref = CIM["SynchronousMachine.GeneratingUnit"]
        pt_gen_q   = CIM["SynchronousMachine.baseQ"]
        pt_gen_qmin = CIM["SynchronousMachine.minQ"]
        pt_gen_qmax = CIM["SynchronousMachine.maxQ"]

        for res in subjects_of_type(g, "SynchronousMachine"):
            gen_id = str(res)
            bus1   = get_bus_name(g, gen_id, 1)
            name   = safe_res_name(g, res, pt_name)
            unit_ref = get_property_value(g, res, pt_gen_ref)
            res_unit = URIRef(str(unit_ref))
            gen_s    = safe_double(g, res_unit, pt_gen_s, 1.0) * 1000.0
            gen_p    = safe_double(g, res_unit, pt_gen_p, 1.0) * 1000.0
            gen_q    = safe_double(g, res, pt_gen_q, 0.0) * 1000.0
            gen_qmin = safe_double(g, res, pt_gen_qmin, 0.44 * gen_s / 1000.0) * 1000.0 * -1.0
            gen_qmax = safe_double(g, res, pt_gen_qmax, 0.44 * gen_s / 1000.0) * 1000.0
            gen_kv   = vmult * find_base_voltage(g, res, pt_equip, pt_eq_base_v, pt_lev_base_v, pt_base_nom_v)

            out.write(f"new Generator.{name} phases=3 bus1={bus1}"
                      f" conn=w kva={gen_s:6g} kw={gen_p:6g}"
                      f" kvar={gen_q:6g} minkvar={gen_qmin:6g}"
                      f" maxkvar={gen_qmax:6g} kv={gen_kv:6g}\n")
            out_guid.write(f"Load.{name}\t{dss_guid(gen_id)}\n")

        # ------------------------------------------------------------------
        # EnergyConsumer => Load
        # ------------------------------------------------------------------
        total_load_kw = 0.0
        out.write("\n")
        pt_p           = CIM["EnergyConsumer.p"]
        pt_q           = CIM["EnergyConsumer.q"]
        pt_cust        = CIM["EnergyConsumer.customerCount"]
        pt_phs_load1   = CIM["EnergyConsumerPhase.EnergyConsumer"]
        pt_phs_load2   = CIM["EnergyConsumerPhase.phase"]
        pt_conn_load   = CIM["EnergyConsumer.phaseConnection"]

        for res in subjects_of_type(g, "EnergyConsumer"):
            load_id  = str(res)
            phs      = wire_phases(g, res, pt_phs_load1, pt_phs_load2)
            phs_cnt  = phase_x_count(phs, True)
            phs_conn = shunt_conn(g, res, pt_conn_load)
            bus_phs  = bus_shunt_phases(phs, phs_cnt, phs_conn)
            bus1     = get_bus_name(g, load_id, 1) + bus_phs
            name     = safe_res_name(g, res, pt_name)
            p_l = safe_double(g, res, pt_p, 1) * smult
            q_l = safe_double(g, res, pt_q, 0) * smult
            total_load_kw += p_l
            n_cust     = safe_property(g, res, pt_cust, "1")
            load_model = get_load_model(g, res)
            load_kv    = vmult * find_base_voltage(g, res, pt_equip, pt_eq_base_v, pt_lev_base_v, pt_base_nom_v)
            if phs_cnt < 2 and "w" in phs_conn:
                load_kv /= math.sqrt(3.0)

            out.write(f"new Load.{name} phases={phs_cnt} bus1={bus1}"
                      f" conn={phs_conn} kw={p_l:6g} kvar={q_l:6g}"
                      f" numcust={n_cust} kv={load_kv:6g} {load_model}\n")
            out_guid.write(f"Load.{name}\t{dss_guid(load_id)}\n")

        out.write("\n")
        out.write(f"// total load = {total_load_kw:6g} kW\n")

        # ------------------------------------------------------------------
        # LinearShuntCompensator => Capacitor
        # ------------------------------------------------------------------
        out.write("\n")
        pt_sec_b      = CIM["LinearShuntCompensator.bPerSection"]
        pt_sec_n      = CIM["LinearShuntCompensator.normalSections"]
        pt_num_steps  = CIM["ShuntCompensator.maximumSections"]
        pt_phs_shunt1 = CIM["ShuntCompensatorPhase.ShuntCompensator"]
        pt_phs_shunt2 = CIM["ShuntCompensatorPhase.phase"]
        pt_conn_shunt = CIM["ShuntCompensator.phaseConnection"]
        pt_nom_u      = CIM["ShuntCompensator.nomU"]

        for res in subjects_of_type(g, "LinearShuntCompensator"):
            cap_id   = str(res)
            name     = dss_name(safe_property(g, res, pt_name, "cap"))
            phs      = wire_phases(g, res, pt_phs_shunt1, pt_phs_shunt2)
            phs_cnt  = phase_x_count(phs, True)
            phs_conn = shunt_conn(g, res, pt_conn_shunt)
            bus_phs  = bus_shunt_phases(phs, phs_cnt, phs_conn)
            bus1     = get_bus_name(g, cap_id, 1) + bus_phs
            num_steps = safe_property(g, res, pt_num_steps, "1")
            cap_b    = safe_int(g, res, pt_num_steps, 1) * safe_double(g, res, pt_sec_b, 0.0001)
            cap_v    = vmult * safe_double(g, res, pt_nom_u, 120.0)
            nom_u    = f"{cap_v:6g}"
            nom_q    = f"{cap_v * cap_v * cap_b * 1000.0:6g}"

            out.write(f"new Capacitor.{name} phases={phs_cnt} bus1={bus1}"
                      f" conn={phs_conn} numsteps={num_steps}"
                      f" kv={nom_u} kvar={nom_q}\n")
            out_guid.write(f"Capacitor.{name}\t{dss_guid(cap_id)}\n")

        # ------------------------------------------------------------------
        # OverheadWireInfo => WireData
        # ------------------------------------------------------------------
        out.write("\n")
        for res in subjects_of_type(g, "OverheadWireInfo"):
            wire_id = str(res)
            name    = safe_res_name(g, res, pt_name)
            out.write(f"new WireData.{name}{get_wire_data(g, res)}\n")
            out_guid.write(f"WireData.{name}\t{dss_guid(wire_id)}\n")

        # ------------------------------------------------------------------
        # TapeShieldCableInfo => TSData
        # ------------------------------------------------------------------
        out.write("\n")
        pt_lap        = CIM["TapeShieldCableInfo.tapeLap"]
        pt_thickness  = CIM["TapeShieldCableInfo.tapeThickness"]
        pt_over_screen = CIM["CableInfo.diameterOverScreen"]

        for res in subjects_of_type(g, "TapeShieldCableInfo"):
            ts_id       = str(res)
            name        = safe_res_name(g, res, pt_name)
            tape_lap    = safe_double(g, res, pt_lap, 0.0)
            tape_thick  = safe_double(g, res, pt_thickness, 0.0)
            d_screen    = safe_double(g, res, pt_over_screen, 0.0)
            out.write(f"new TSData.{name}"
                      + get_wire_data(g, res)
                      + get_cable_data(g, res)
                      + f" DiaShield={d_screen + 2.0 * tape_thick:6g}"
                      + f" tapeLayer={tape_thick:6g} tapeLap={tape_lap:6g}\n")
            out_guid.write(f"TSData.{name}\t{dss_guid(ts_id)}\n")

        # ------------------------------------------------------------------
        # ConcentricNeutralCableInfo => CNData
        # ------------------------------------------------------------------
        out.write("\n")
        pt_over_neutral  = CIM["ConcentricNeutralCableInfo.diameterOverNeutral"]
        pt_strand_count  = CIM["ConcentricNeutralCableInfo.neutralStrandCount"]
        pt_strand_gmr    = CIM["ConcentricNeutralCableInfo.neutralStrandGmr"]
        pt_strand_radius = CIM["ConcentricNeutralCableInfo.neutralStrandRadius"]
        pt_strand_res    = CIM["ConcentricNeutralCableInfo.neutralStrandRDC20"]

        for res in subjects_of_type(g, "ConcentricNeutralCableInfo"):
            cn_id      = str(res)
            name       = safe_res_name(g, res, pt_name)
            cn_dia     = safe_double(g, res, pt_over_neutral, 0.0)
            cn_count   = safe_int(g, res, pt_strand_count, 0)
            cn_gmr     = safe_double(g, res, pt_strand_gmr, 0.0)
            cn_radius  = safe_double(g, res, pt_strand_radius, 0.0)
            cn_res     = safe_double(g, res, pt_strand_res, 0.0)
            out.write(f"new CNData.{name}"
                      + get_wire_data(g, res)
                      + get_cable_data(g, res)
                      + f" k={cn_count} GmrStrand={cn_gmr:6g}"
                      + f" DiaStrand={2 * cn_radius:6g} Rstrand={cn_res:6g}\n")
            out_guid.write(f"CNData.{name}\t{dss_guid(cn_id)}\n")

        # ------------------------------------------------------------------
        # WireSpacingInfo => LineSpacing
        # ------------------------------------------------------------------
        out.write("\n")
        pt_wire_x = CIM["WirePosition.xCoord"]
        pt_wire_y = CIM["WirePosition.yCoord"]
        pt_wire_p = CIM["WirePosition.phase"]
        pt_wire_s = CIM["WirePosition.WireSpacingInfo"]

        for res in subjects_of_type(g, "WireSpacingInfo"):
            ws_id = str(res)
            name  = dss_name(safe_property(g, res, pt_name, ""))
            nconds = nphases = 0
            wxA = wxB = wxC = wxN = wxS1 = wxS2 = 0.0
            wyA = wyB = wyC = wyN = wyS1 = wyS2 = 0.0
            wA = wB = wC = wN = wS1 = wS2 = False

            for wa in g.subjects(pt_wire_s, res):
                nconds += 1
                phs_raw = g.value(wa, pt_wire_p)
                phs_kind = phase_kind_string(str(phs_raw)) if phs_raw else ""
                if phs_kind == "A":
                    wxA = safe_double(g, wa, pt_wire_x, 0)
                    wyA = safe_double(g, wa, pt_wire_y, 0)
                    wA = True; nphases += 1
                elif phs_kind == "B":
                    wxB = safe_double(g, wa, pt_wire_x, 0)
                    wyB = safe_double(g, wa, pt_wire_y, 0)
                    wB = True; nphases += 1
                elif phs_kind == "C":
                    wxC = safe_double(g, wa, pt_wire_x, 0)
                    wyC = safe_double(g, wa, pt_wire_y, 0)
                    wC = True; nphases += 1
                elif phs_kind == "N":
                    wxN = safe_double(g, wa, pt_wire_x, 0)
                    wyN = safe_double(g, wa, pt_wire_y, 0)
                    wN = True
                elif phs_kind == "s1":
                    wxS1 = safe_double(g, wa, pt_wire_x, 0)
                    wyS1 = safe_double(g, wa, pt_wire_y, 0)
                    wS1 = True; nphases += 1
                elif phs_kind == "s2":
                    wxS2 = safe_double(g, wa, pt_wire_x, 0)
                    wyS2 = safe_double(g, wa, pt_wire_y, 0)
                    wS2 = True; nphases += 1

            if nconds > 0 and nphases > 0:
                map_spacings[name] = SpacingCount(nconds, nphases)
                out.write(f"new LineSpacing.{name} nconds={nconds}"
                          f" nphases={nphases} units=m\n")
                x_buf = " x=["
                h_buf = " h=["
                for flag, wx, wy in [
                    (wA, wxA, wyA), (wB, wxB, wyB), (wC, wxC, wyC),
                    (wS1, wxS1, wyS1), (wS2, wxS2, wyS2), (wN, wxN, wyN)
                ]:
                    if flag:
                        x_buf += f"{wx:6g},"
                        h_buf += f"{wy:6g},"
                out.write(f"~{x_buf}]{h_buf}]\n")
                out_guid.write(f"LineSpacing.{name}\t{dss_guid(ws_id)}\n")

        # ------------------------------------------------------------------
        # LineCodes
        # ------------------------------------------------------------------
        num_line_codes = 0
        out.write("\n")

        pt_count = CIM["PerLengthPhaseImpedance.conductorCount"]
        for res in subjects_of_type(g, "PerLengthPhaseImpedance"):
            num_line_codes += 1
            lc_id = str(res)
            name  = dss_name(safe_property(g, res, pt_name, ""))
            z_mat = "nphases=3 r0=0 r1=0 x0=0.001 x1=0.001 c0=0 c1=0"
            if get_property_value(g, res, pt_count) is not None:
                z_mat = get_impedance_matrix(g, pt_name, pt_count, res, freq)
            out.write(f"new LineCode.{name} {z_mat}\n")
            out_guid.write(f"LineCode.{name}\t{dss_guid(lc_id)}\n")

        pt_seq_r1 = CIM["PerLengthSequenceImpedance.r"]
        pt_seq_r0 = CIM["PerLengthSequenceImpedance.r0"]
        pt_seq_x1 = CIM["PerLengthSequenceImpedance.x"]
        pt_seq_x0 = CIM["PerLengthSequenceImpedance.x0"]
        pt_seq_b1 = CIM["PerLengthSequenceImpedance.bch"]
        pt_seq_b0 = CIM["PerLengthSequenceImpedance.b0ch"]

        for res in subjects_of_type(g, "PerLengthSequenceImpedance"):
            num_line_codes += 1
            lc_id = str(res)
            name  = dss_name(safe_property(g, res, pt_name, ""))
            sq_r1 = safe_double(g, res, pt_seq_r1, 0)
            sq_r0 = safe_double(g, res, pt_seq_r0, 0) or sq_r1
            sq_x1 = safe_double(g, res, pt_seq_x1, 0)
            sq_x0 = safe_double(g, res, pt_seq_x0, 0) or sq_x1
            bch   = safe_double(g, res, pt_seq_b1, 0)
            seq_c1 = bch * 1.0e9 / freq / 2.0 / math.pi
            bch    = safe_double(g, res, pt_seq_b0, 0)
            seq_c0 = bch * 1.0e9 / freq / 2.0 / math.pi
            out.write(f"new LineCode.{name} nphases=3"
                      f" r1={sq_r1:6g} x1={sq_x1:6g} c1={seq_c1:6g}"
                      f" r0={sq_r0:6g} x0={sq_x0:6g} c0={seq_c0:6g}\n")
            out_guid.write(f"LineCode.{name}\t{dss_guid(lc_id)}\n")

        if num_line_codes < 1:
            out.write("new LineCode.dummy_linecode_1 nphases=1 rmatrix={0} xmatrix={0.001} cmatrix={0}\n")
            out.write("new LineCode.dummy_linecode_2 nphases=2 rmatrix={0|0 0} xmatrix={0.001|0 0.001} cmatrix={0|0 0}\n")
            out.write("new LineCode.dummy_linecode_3 nphases=3 r1=0 x1=0.001 c1=0 r0=0 x0=0.001 c0=0\n")

        # ------------------------------------------------------------------
        # ACLineSegment => Line
        # ------------------------------------------------------------------
        out.write("\n")
        pt_phs_z      = CIM["ACLineSegment.PerLengthImpedance"]
        pt_line_len   = CIM["Conductor.length"]
        pt_datasheet  = CIM["PowerSystemResource.AssetDatasheet"]
        pt_amps       = CIM["WireInfo.ratedCurrent"]
        pt_phs_line1  = CIM["ACLineSegmentPhase.ACLineSegment"]
        pt_phs_line2  = CIM["ACLineSegmentPhase.phase"]

        for res in subjects_of_type(g, "ACLineSegment"):
            line_id = str(res)
            if f_name_seq > 0:
                name = dss_id(line_id)
            else:
                name = dss_name(safe_property(g, res, pt_name, ""))
            phs     = wire_phases(g, res, pt_phs_line1, pt_phs_line2)
            phs_cnt = phase_x_count(phs, False)
            bus_phs = bus_x_phases(phs)
            bus1    = get_bus_name(g, line_id, 1) + bus_phs
            bus2    = get_bus_name(g, line_id, 2) + bus_phs
            d_len   = safe_double(g, res, pt_line_len, 1.0)

            z_phase  = safe_resource_lookup(g, pt_name, res, pt_phs_z, "")
            z_parms  = get_ac_line_parameters(g, res, d_len, freq)
            z_space  = get_line_spacing(g, res)

            if z_phase:
                linecode = f" linecode={z_phase}"
            elif z_space:
                linecode = z_space
            elif z_parms:
                linecode = z_parms
            elif phs_cnt == 1:
                linecode = " linecode=dummy_linecode_1"
            elif phs_cnt == 2:
                linecode = " linecode=dummy_linecode_2"
            else:
                linecode = " linecode=dummy_linecode_3"

            z_amps = find_conductor_amps(g, res, pt_datasheet, pt_amps) if z_parms else ""

            out.write(f"new Line.{name} phases={phs_cnt}"
                      f" bus1={bus1} bus2={bus2}"
                      f" length={d_len:6g}{linecode}{z_amps}\n")
            out_guid.write(f"Line.{name}\t{dss_guid(line_id)}\n")

        # Switches -----------------------------------------------------------
        pt_phs_swt1 = CIM["SwitchPhase.Switch"]
        pt_phs_swt2 = CIM["SwitchPhase.phaseSide1"]

        def write_switches(sw_type: str, comment: str, query_open: bool = True):
            items = list(subjects_of_type(g, sw_type))
            if items:
                out.write("\n")
                out.write(f"// {comment}\n")
            for res in items:
                sw_id   = str(res)
                name    = dss_name(safe_property(g, res, pt_name, ""))
                phs     = wire_phases(g, res, pt_phs_swt1, pt_phs_swt2)
                phs_cnt = phase_x_count(phs, False)
                bus_phs = bus_x_phases(phs)
                if query_open:
                    open_val = safe_property(g, res, pt_open, "false")
                else:
                    open_val = safe_property(g, res, pt_open, "false")
                bus1 = get_bus_name(g, sw_id, 1) + bus_phs
                bus2 = get_bus_name(g, sw_id, 2) + bus_phs
                out.write(f"new Line.{name} phases={phs_cnt}"
                          f" bus1={bus1} bus2={bus2}"
                          f" switch=y // CIM {sw_type}\n")
                if open_val == "false":
                    out.write(f"  close Line.{name} 1\n")
                else:
                    out.write(f"  open Line.{name} 1\n")
                out_guid.write(f"Line.{name}\t{dss_guid(sw_id)}\n")

        write_switches("LoadBreakSwitch", "Load Break Switches")
        write_switches("Fuse", "Fuses")
        write_switches("Breaker", "Breakers")
        write_switches("Disconnector", "Disconnectors")

        # ------------------------------------------------------------------
        # TransformerTankInfo => XfmrCode
        # ------------------------------------------------------------------
        out.write("\n")
        for res in subjects_of_type(g, "TransformerTankInfo"):
            xc_id = str(res)
            name  = dss_name(safe_property(g, res, pt_name, ""))
            out.write(f"new XfmrCode.{name} {get_xfmr_code(g, xc_id, smult, vmult)}\n")
            out_guid.write(f"XfmrCode.{name}\t{dss_guid(xc_id)}\n")

        # ------------------------------------------------------------------
        # PowerTransformer => Transformer
        # ------------------------------------------------------------------
        out.write("\n")
        pt_asset_psr = CIM["Asset.PowerSystemResources"]
        pt_asset_inf = CIM["Asset.AssetInfo"]
        pt_tank      = CIM["TransformerTank.PowerTransformer"]

        for res in subjects_of_type(g, "PowerTransformer"):
            xf_id    = str(res)
            xf_name0 = dss_name(safe_property(g, res, pt_name, ""))
            xfmrbank = f" bank={xf_name0}"

            tanks = list(g.subjects(pt_tank, res))
            if tanks:
                for r_tank in tanks:
                    tank_name = dss_name(safe_property(g, r_tank, pt_name, ""))
                    assets = list(g.subjects(pt_asset_psr, r_tank))
                    used_code = False
                    for r_asset in assets:
                        ds_ref = get_property_value(g, r_asset, pt_asset_inf)
                        if ds_ref is not None:
                            r_ds = URIRef(str(ds_ref))
                            xf_bus = get_tank_buses_and_xfmr_code(g, r_tank, r_ds)
                            out.write(f"new Transformer.{tank_name}{xfmrbank}{xf_bus}\n")
                            used_code = True
                            break
                    if not used_code:
                        xf_bus = get_tank_buses_and_phase_count(g, r_tank, False)
                        out.write(f"new Transformer.{tank_name}{xfmrbank}{xf_bus}\n")
                        out.write(f"~ {get_tank_data(g, r_tank, smult, vmult)} // Tanked\n")
                    out_guid.write(f"Transformer.{tank_name}\t{dss_guid(xf_id)}\n")
            else:
                xf_bus = get_winding_buses(g, xf_id)
                xf_data = get_power_transformer_data(g, xf_id, smult, vmult)
                out.write(f"new Transformer.{xf_name0}{xfmrbank}"
                          f" buses={xf_bus}\n ~ {xf_data} // Standalone\n")
                out_guid.write(f"Transformer.{xf_name0}\t{dss_guid(xf_id)}\n")

        # ------------------------------------------------------------------
        # RatioTapChanger => RegControl
        # ------------------------------------------------------------------
        out.write("\n")
        for res in subjects_of_type(g, "RatioTapChanger"):
            reg_id = str(res)
            name   = dss_name(safe_property(g, res, pt_name, ""))
            s_reg  = get_regulator_data(g, res)
            out.write(f"new RegControl.{name} {s_reg}\n")
            out_guid.write(f"RegControl.{name}\t{dss_guid(reg_id)}\n")

        # ------------------------------------------------------------------
        # RegulatingControl => CapControl
        # ------------------------------------------------------------------
        out.write("\n")
        for res in subjects_of_type(g, "RegulatingControl"):
            rc_id  = str(res)
            name   = dss_name(safe_property(g, res, pt_name, ""))
            s_reg  = get_cap_control_data(g, res)
            out.write(f"new CapControl.{name} {s_reg}\n")
            out_guid.write(f"CapControl.{name}\t{dss_guid(rc_id)}\n")

        # ------------------------------------------------------------------
        # Unsupported elements (commented out)
        # ------------------------------------------------------------------
        out.write("\n")
        for cim_type in ("Junction", "BusbarSection", "Bay"):
            for res in subjects_of_type(g, cim_type):
                name = safe_res_name(g, res, pt_name)
                out.write(f"// new {cim_type}.{name}\n")

        # ------------------------------------------------------------------
        # Wrap-up: voltage bases
        # ------------------------------------------------------------------
        base_voltages = list(subjects_of_type(g, "BaseVoltage"))
        if base_voltages:
            vnoms = [vmult * safe_double(g, r, pt_base_nom_v, 1.0) for r in base_voltages]
            out.write("set voltagebases=[" + ", ".join(f"{v:6g}" for v in vnoms) + "]\n")
        else:
            out.write("set voltagebases=[1.0]\n")

        f_bus_name = f_bus.split("/")[-1] if "/" in f_bus else f_bus
        f_guid_name = f_guid.split("/")[-1] if "/" in f_guid else f_guid
        out.write("calcv\n")
        out.write(f"buscoords {f_bus_name}\n")
        out.write(f"// guids {f_guid_name}\n")

        out_guid.write("\n")

    print(f"Done. Output written to {f_out}, {f_bus}, {f_guid}")


if __name__ == "__main__":
    main()