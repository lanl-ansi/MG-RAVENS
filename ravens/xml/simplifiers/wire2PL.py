import json
import numpy as np
import scipy.special as sp
from .ll_simp import ll_simp as ll
np.set_printoptions(edgeitems=3, linewidth=200, precision=5, suppress=False, threshold=1000, formatter=None)

def wire2PL(in_data,out_data=None):
    """
    Input: Takes as an input a RAVENS files
    Output: A RAVENS file modified such that all references to wireinfo is converted to a PerLengthLineParameter:PerLengthImpedance 
    """
    if out_data is None and isinstance(in_data, dict):
        wire_info_purge = ll("wire info purge",["WireInfo","WireSpacingInfo"],{},{},auto_tl=False)
        raven = wire2PL_compute(in_data)
        return wire_info_purge(raven)
    elif isinstance(in_data, str) and isinstance(out_data, str):
        wire_info_purge = ll("wire info purge",["WireInfo","WireSpacingInfo"],{},{},auto_tl=False)
        with open(in_data, 'r') as input_file,open("tmp/w2lp_mp.json",'w') as mp_file, open(out_data, 'w') as output_file:
            #1) setup json dictionary
            raven = json.loads(input_file.read()) 

            #2) Simplify
            raven = wire2PL_compute(raven,output_file=output_file)

            #3) close down json dictionary
            json.dump(raven, mp_file, indent=2)
        #4) clean up any remaining wire info references
        wire_info_purge("tmp/w2lp_mp.json",out_data)
    else:
        raise ValueError("Invalid arguments. Expected either a dictionary or two filenames.")

def wire2PL_compute(raven, output_file = None):
    #1) find all wireinfo objects
    WI = raven_find(raven,"WireInfo")
    WSI = raven_find(raven,"WireSpacingInfo")
    
    #error/null case handling 
    if len(WI) > 1 or len(WSI) > 1: #Error Case
        print("ERROR: Improperly specified WireInfo or WireSpacingInfo")
        return
    elif len(WI) == 0 or len(WSI) == 0: #Null Case
        return raven
    
    #identified all wire info and wire spacing info
    WI = WI[0][1]
    WSI = WSI[0][1]

    #2) generate per length impedance

    #NOTE: there exists ONE WI reference PER PHASE PER WIRE (when used)
    #NOTE: there exists ONE WSI reference PER WIRE (when used)

    #base information for Impedance Matrix 
    RAC = {} #maps WI key to RAC
    RDC = {} #maps WI key to RDC
    GMR = {} #maps WI key to GMR
    WIT = {} #maps WI key to Wire Info Type
    R = {} #maps WI key to Radius
    X = {} #maps WPI key to dict of phase:x coords
    Y = {} #maps WPI key to dict of phase:y coords
    DON = {}
    NSR = {}
    NSG = {}
    NSRDC = {}
    NSC = {}
    DINS = {}
    TINS = {}
    DOJ = {}
    TT = {}
    TL = {}

    mu_0 = 4*np.pi*10**(-7)
    bf = get(raven,"BaseFrequency",60)
    w = w_0 = 2*np.pi*bf
    rho_e = 100
    e_0 = 8.8541878176e-12
    earth_model = "deri" #NOTE: this is only for reference
    wires = get(raven,"ACLineSegment")

    #calculate rDC, rAC, and GMR from WI
    for wi_name, wi in WI.items():
        if has(wi,"WireInfo.rAC25"):
            RAC[wi_name] = get(wi,"WireInfo.rAC25")
            RDC[wi_name] = RAC[wi_name]/1.02
        elif has(wi,"WireInfo.rDC20"):
            RDC[wi_name] = get(wi,"WireInfo.rDC20")
            RAC[wi_name] = RDC[wi_name]*1.02
        else:
            raise KeyError("WireInfo object does not specify rDC or rAC")
        if has(wi,"WireInfo.gmr"):
            GMR[wi_name] = get(wi,"WireInfo.gmr")
            R[wi_name] = get(wi,"WireInfo.radius")
        elif has(wi,"WireInfo.radius"):
            GMR[wi_name] = get(wi,"WireInfo.radius")*0.778
            R[wi_name] = get(wi,"WireInfo.radius")
        else: 
            raise KeyError("WireInfo object does not specify radius or GMR")
        if (get(wi,"Ravens.cimObjectType")=="ConcentricNeutralCableInfo"):
            DON[wi_name] = get(wi,"ConcentricNeutralCableInfo.diameterOverNeutral") 
            NSR[wi_name] = get(wi,"ConcentricNeutralCableInfo.neutralStrandRadius") * 2.0
            NSG[wi_name] = get(wi,"ConcentricNeutralCableInfo.neutralStrandGmr",(NSR[wi_name]/2.0) * 0.778)
            NSRDC[wi_name] = get(wi,"ConcentricNeutralCableInfo.neutralStrandRDC20")
            NSC[wi_name] = get(wi,"ConcentricNeutralCableInfo.neutralStrandCount")
        if (get(wi,"Ravens.cimObjectType")=="ConcentricNeutralCableInfo") or (get(wi,"Ravens.cimObjectType")=="TapeShieldCableInfo"):
            DINS[wi_name] = get(wi, "CableInfo.diameterOverJacket")
            TINS[wi_name] = get(wi, "WireInfo.insulationThickness")
        if (get(wi,"Ravens.cimObjectType")=="TapeShieldCableInfo"):
            DOJ[wi_name] = get(wi, "CableInfo.diameterOverJacket") # diameter over tape shield
            TT[wi_name] = get(wi, "TapeShieldCableInfo.tapeThickness")  # tape shield thickness
            TL[wi_name] = get(wi, "TapeShieldCableInfo.tapeLap")   #tape lap (default 20.0)
        WIT[wi_name] = get(wi,"Ravens.cimObjectType")
        
    #calculate X and Y from WSI.WP 
    for wsi_name, wsi in WSI.items():
        if has(wsi,"WireSpacingInfo.WirePositions"):
            wps = get(wsi,"WireSpacingInfo.WirePositions")
            X[wsi_name] = {wp["WirePosition.sequenceNumber"]:wp["WirePosition.xCoord"] for wp in wps}
            Y[wsi_name] = {wp["WirePosition.sequenceNumber"]:wp["WirePosition.yCoord"] for wp in wps}
        else:
            raise KeyError("WireSpacing Info does not properly specify Wire positions")

    #generate a Z matrix for each wire that needs one and insert into ravens
    for wire_name, wire in wires.items():
        if not has(wire,"ACLineSegment.PerLengthImpedance"):
            #A) Setup
            #stores the key for this line segments wire spacing info
            wsi_key = get(wire,"ACLineSegment.WireSpacingInfo").split("::")[-1].strip("'")
            #map of phase number to wire info
            wi_keys = {get(phase,"ACLineSegmentPhase.sequenceNumber"):get(phase,"PowerSystemResource.AssetDatasheet").split("::")[-1].strip("'") for phase in get(wire,"ACLineSegment.ACLineSegmentPhase")}
            n_phases = len(wi_keys)
            wi_types = [WIT[wi_key] for wi_key in wi_keys.values()]
            for i in range(1,len(wi_types)):
                if wi_types[0] != wi_types[i]:
                    raise KeyError("Line Segment uses multiple component types")
            wi_type = wi_types[0]
            n_conds = len(wire["ACLineSegment.ACLineSegmentPhase"])
            wire_positions = X[wsi_key].keys()
            num_of_wires = len(wire_positions)

            reduce = True if num_of_wires > n_conds else False

            #B) generate Z/Y matrix
            if (wi_type == "OverheadWireInfo"):
                Z, C = calculate_overhead_line_constants(wi_keys,wsi_key,n_phases,n_conds,mu_0,w,rho_e,e_0,RDC,GMR,X,Y,R)
            if (wi_type == "ConcentricNeutralCableInfo"):
                d_cable = DON
                d_strand = NSR
                gmr_strand = NSG
                n_strand = NSC
                R_strand = NSRDC
                d_ins = DINS
                t_ins = TINS
                Z, C = calculate_concentric_line_constants(wi_keys,wsi_key,n_phases,n_conds,mu_0,w,rho_e,e_0,RDC,GMR,X,Y,R,d_cable,d_strand,gmr_strand,n_strand,R_strand,d_ins,t_ins)
            if (wi_type == "TapeShieldCableInfo"):
                d_shield = DOJ
                t_tape = TT
                lap_tape = TL
                d_ins = DINS
                t_ins = TINS
                Z, C = calculate_tape_line_constants(wi_keys,wsi_key,n_phases,n_conds,mu_0,w,rho_e,e_0,RDC,GMR,X,Y,R,d_shield,t_tape,lap_tape,d_ins,t_ins)

            if reduce:
                Z, C = _kron2(Z, C, n_phases)
            #C) Insert into Ravens
            wire["ACLineSegment.PerLengthImpedance"] = "PerLengthPhaseImpedance::'simplified_"+wire_name+"'"
            if (not has(raven,"PerLengthLineParameter")):
                raven["PerLengthLineParameter"] = {}
            if (not has(raven,"PerLengthImpedance")):
                raven["PerLengthLineParameter"]["PerLengthImpedance"] = {}
            if (not has(raven,"PerLengthPhaseImpedance")):
                    raven["PerLengthLineParameter"]["PerLengthImpedance"]["PerLengthPhaseImpedance"] = {}
            PLPI = raven["PerLengthLineParameter"]["PerLengthImpedance"]["PerLengthPhaseImpedance"]
            PID = []
            for i in range(n_phases):
                for j in range(i,n_phases):
                    PID.append({
                        "Ravens.cimObjectType": "PhaseImpedanceData",
                        "PhaseImpedanceData.row": i+1,
                        "PhaseImpedanceData.column": j+1,
                        "PhaseImpedanceData.r": Z[i][j].real,
                        "PhaseImpedanceData.x": Z[i][j].imag,
                        "PhaseImpedanceData.g": (C[i][j].real/2)*bf,
                        "PhaseImpedanceData.b": (C[i][j].imag/2)*bf
                    }) 
            PLPI["simplified_"+wire_name+""] = {
                "Ravens.cimObjectType": "PerLengthPhaseImpedance",
                "IdentifiedObject.name": "simplified_"+wire_name+"",
                "PerLengthPhaseImpedance.conductorCount": n_phases,
                "PerLengthPhaseImpedance.PhaseImpedanceData":PID
            }

            #remove old references
            del wire["ACLineSegment.WireSpacingInfo"]
            del wire["PowerSystemResource.AssetDatasheet"]
            for phase in wire["ACLineSegment.ACLineSegmentPhase"]:
                del phase["PowerSystemResource.AssetDatasheet"]
    
    return raven


def calculate_overhead_line_constants(wi_keys,wsi_key,n_phases,n_conds,mu_0,w,rho_e,e_0,RDC,GMR,X,Y,R):
    Z = np.zeros((n_phases,n_phases),dtype=np.complex128)
    P = np.zeros((n_phases,n_phases),dtype=np.complex128)
    C = np.zeros((n_phases,n_phases),dtype=np.complex128)
    for i in range(n_phases):
        for j in range(i+1):
            if i == j:
                Z_ic = Z_int(RDC[wi_keys[i+1]],mu_0,w).real
                Z_ig = (1j)*(w*mu_0)/(2*np.pi)*np.log(1/GMR[wi_keys[i+1]])

                Z_ie = Z_ret(i,i,w,mu_0,rho_e,X[wsi_key],Y[wsi_key])
                Z[i][j] = Z_ic + Z_ig + Z_ie
                P[i][j] = 1j * -1/((2*np.pi) * e_0 * w) * np.log(2 * abs(Y[wsi_key][i+1]) / R[wi_keys[i+1]])
            else:
                d_ij = np.sqrt((X[wsi_key][i+1]-X[wsi_key][j+1])**2 + (Y[wsi_key][i+1]-Y[wsi_key][j+1])**2)
                S_ij = np.sqrt((X[wsi_key][i+1]-X[wsi_key][j+1])**2 + (Y[wsi_key][i+1]+Y[wsi_key][j+1])**2)
                X_ijg = (mu_0*w/(2*np.pi))*np.log(1/d_ij)
                Z[i][j] = Z[j][i] = 1j*X_ijg + Z_ret(i,j,w,mu_0,rho_e,X[wsi_key],Y[wsi_key])
                P[i][j] = P[j][i] = 1j * -1/((2*np.pi) * e_0 * w) * np.log(S_ij/d_ij)
    C = np.linalg.pinv(P) * 1e9 / w
    # C = P
    return Z, C




def calculate_concentric_line_constants(wi_keys,wsi_key,n_phases,n_conds,mu_0,w,rho_e,e_0,RDC,GMR,X,Y,R,d_cable,d_strand,gmr_strand,n_strand,R_strand,d_ins,t_ins):
    N = n_conds + n_phases #Assume n_phases does not include a neutral 4th wire right now
    Z = np.zeros((N,N),dtype=np.complex128)
    P = np.zeros((n_phases,n_phases),dtype=np.complex128)
    C = np.zeros((n_phases,n_phases),dtype=np.complex128)
    for i in range(n_conds):
        ii = i+n_conds
        for j in range(n_conds):
            jj = j+n_conds

            Z_ije = Z_ije_ss = Z_ret(i,j,w,mu_0,rho_e,X[wsi_key],Y[wsi_key])
            D_ij = np.sqrt((X[wsi_key][i+1]-X[wsi_key][j+1])**2 + (Y[wsi_key][i+1]-Y[wsi_key][j+1])**2)

            if j <= i:
                if i == j:
                    Z_ic = Z_int(RDC[wi_keys[i+1]],mu_0,w).real
                    Z_ig = (w*mu_0*1j)/(2*np.pi)*np.log(1/GMR[wi_keys[i+1]])
                    Z[i,i] = Z_ic + Z_ig + Z_ije
                    if i < n_phases:
                        r_cn = 1/2*(d_cable[wi_keys[i+1]]-d_strand[wi_keys[i+1]])
                        gmr_cn = (gmr_strand[wi_keys[i+1]]*n_strand[wi_keys[i+1]]*(r_cn**(n_strand[wi_keys[i+1]]-1)))**(1 / n_strand[wi_keys[i+1]])

                        Z_ic_ss = R_strand[wi_keys[i+1]] / n_strand[wi_keys[i+1]]
                        Z_ig_ss = 1j * w*mu_0/(2*np.pi)*np.log(1/gmr_cn)

                        Z[ii,ii] = Z_ic_ss + Z_ig_ss + Z_ije_ss
                else:
                    Z_ijg = 1j * w*mu_0/(2*np.pi)*np.log(1/D_ij)

                    Z[i,j] = Z[j,i] = Z_ijg + Z_ije
                
                    if i < n_phases:
                        jj = j+n_conds
                        Z_ijg = 1j * w*mu_0/(2*np.pi)*np.log(1/D_ij)
                        Z[ii,jj] = Z[jj,ii] = Z_ijg + Z_ije
            
            if i < n_phases:
                r_cn = (d_cable[wi_keys[i+1]]-d_strand[wi_keys[i+1]])/2
                if i == j:
                    D_ij = r_cn
                else:
                    D_ij = np.sqrt((X[wsi_key][i+1]-X[wsi_key][j+1])**2 + (Y[wsi_key][i+1]-Y[wsi_key][j+1])**2)
                    D_ij = (D_ij**(n_strand[wi_keys[i+1]]) - r_cn**(n_strand[wi_keys[i+1]]))**(1/n_strand[wi_keys[i+1]])

                Z_ijg = 1j * w*mu_0/(2*np.pi)*np.log(1/D_ij)

                Z[ii,j] = Z[j,ii] = Z_ijg + Z_ije

        if i <= n_phases:
            r_outer = d_ins[wi_keys[i+1]]/2
            r_inner = r_outer - t_ins[wi_keys[i+1]]
            P[i,i] = 1j * 2*np.pi * e_0 * 2.3 * w / np.log(r_outer / r_inner)
    Z = _kron(Z,n_conds)
    C = P * 1e9 / w


    return Z,C


def calculate_tape_line_constants(wi_keys,wsi_key,n_phases,n_conds,mu_0,w,rho_e,e_0,RDC,GMR,X,Y,R,d_shield,t_tape,lap_tape,d_ins,t_ins):
    n_conds = n_phases
    N = n_conds + n_phases #Assume n_phases does not include a neutral 4th wire right now
    Z = np.zeros((N,N),dtype=np.complex128)
    P = np.zeros((n_phases,n_phases),dtype=np.complex128)
    for i in range(n_conds):
        ii = i+n_conds
        for j in range(n_conds):
            jj = j+n_conds

            Z_ije = Z_ije_ss = Z_ret(i,j,w,mu_0,rho_e,X[wsi_key],Y[wsi_key])
            D_ij = np.sqrt((X[wsi_key][i+1]-X[wsi_key][j+1])**2 + (Y[wsi_key][i+1]-Y[wsi_key][j+1])**2)

            if j <= i:
                if i == j:
                    Z_ic = Z_int(RDC[wi_keys[i+1]],mu_0,w).real
                    Z_ig = (w*mu_0*1j)/(2*np.pi)*np.log(1/GMR[wi_keys[i+1]])

                    Z[i,i] = Z_ic + Z_ig + Z_ije
                    # print(Z[i,i])
                    if i < n_phases:
                        gmr_ts = (d_shield[wi_keys[i+1]] - t_tape[wi_keys[i+1]])/2

                        Z_ic_ss = (1) * 0.3183 * 2.3718e-8 / (d_shield[wi_keys[i+1]] * t_tape[wi_keys[i+1]] * np.sqrt(50 / (100-lap_tape[wi_keys[i+1]])))
                        Z_ig_ss = (1j) * w*mu_0/(2*np.pi)*np.log(1/gmr_ts)

                        Z[ii,ii] = Z_ic_ss + Z_ig_ss + Z_ije_ss
                else:
                    Z_ijg = (1j) * w*mu_0/(2*np.pi)*np.log(1/D_ij)

                    Z[i,j] = Z[j,i] = Z_ijg + Z_ije

                    if i < n_phases:
                        jj = j+n_conds
                        D_ij =  np.sqrt((X[wsi_key][i+1]-X[wsi_key][j+1])**2 + (Y[wsi_key][i+1]-Y[wsi_key][j+1])**2)

                        Z_ijg = (1j) * w*mu_0/(2*np.pi)*np.log(1 / D_ij)

                        Z[ii,jj] = Z[jj,ii] = Z_ijg + Z_ije
            if i < n_phases:
                if i == j:
                    D_ij = (d_shield[wi_keys[i+1]] - t_tape[wi_keys[i+1]])/2

                Z_ijg = (1j) * w*mu_0/(2*np.pi)*np.log(1/D_ij)

                Z[ii,j] = Z[j,ii] = Z_ijg + Z_ije
        
        if i < n_phases:
            r_outer = d_ins[wi_keys[i+1]]/2
            r_inner = r_outer - t_ins[wi_keys[i+1]]
            P[i,i] = (1j) * (2*np.pi) * e_0 * 2.3  * w / np.log(r_outer / r_inner)

    Z = _kron(Z,n_conds)
    C = P * 1e9 / w
    # print(Z)
    # print(C)
    return Z, C


def _kron(Z, nconds):
    Z_out = np.copy(Z)

    n_row, n_col = Z.shape
    # print(range(n_row-1))

    N = n_row
    while N > nconds:
        _Z = np.zeros((N-1, N-1),dtype=np.complex128)
        for i in range(N-1):
            for j in range(N-1):
                # print(_Z)
                _Z[i,j] = Z_out[i,j] - Z_out[i,N-1]*Z_out[j,N-1]/Z_out[N-1,N-1]
        Z_out = _Z
        N -= 1

    return Z_out


def _kron2(Z, Y, nconds):
    Z_out = np.copy(Z)
    Y_out = np.copy(Y)

    n_row, n_col = Z.shape

    N = n_row
    while N > nconds:
        _Z = np.zeros((N-1, N-1),dtype=np.complex128)
        _Y = np.zeros((N-1, N-1),dtype=np.complex128)

        for i in range(N-1):
            for j in range(N-1):
                _Z[i,j] = Z_out[i,j] - Z_out[i,N-1]*Z_out[j,N-1]/Z_out[N-1,N-1]
                _Y[i,j] = Y_out[i,j]

        Z_out = _Z
        Y_out = _Y
        N -= 1

    return Z_out, Y_out

def Z_int(R_dc,mu_0,w):
    δ = np.sqrt(R_dc*(w/(2*np.pi))*mu_0)
    m = (1+1j)*np.sqrt(w/(2*np.pi)*mu_0/R_dc)
    a = (1) if abs(m) > 35 else (sp.iv(0,m) / sp.iv(1,m))
    Z_int = (1+1j) * a * δ / 2
    return Z_int

def Z_ret(i,j,w,mu_0,rho_e,x,y):
    p = 1 / np.sqrt(1j * w * mu_0 / rho_e)
    if i == j:
        # Deri Eq 3
        Z_ij = 1j * w*mu_0/(2*np.pi) * np.log(2*(y[i+1] + p))
    else:
        # Deri Eq 4
        Z_ij = 1j * w*mu_0/(2*np.pi) * np.log(np.sqrt((y[i+1] + y[j+1] + 2*p)**2 + (x[i+1]-x[j+1])**2))
    return Z_ij
        
def get(raven,target,default=0):
    return default if len(raven_find(raven,target)) == 0 else raven_find(raven,target)[0][1]

def has(raven,target):
    return len(raven_find(raven,target)) != 0


def raven_find(raven,target,path=""):
    """
    Input: raven JSON dictionary and a target member
    Output: list of all instances containing that target member with path to that instance 
    """
    found = []
    if isinstance(raven,dict):
        for key, val in list(raven.items()):
            #target found
            if key == target:
                found.append((path +"/"+str(key),val))
            #recursive step
            elif isinstance(val,dict):
                found += raven_find(val,target,path+"/"+str(key))
            elif isinstance(val,list):
                for item in val:
                    if isinstance(item,dict):
                        found += raven_find(item,target,path+"/"+str(key))
    return found




if __name__ == "__main__":
    wire2PL("tmp/IEEE_Assets_simp.json","tmp/TEST13B.json")