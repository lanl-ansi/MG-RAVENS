import json

class tl_simp:
    def __init__(self,tl_targets):
        self.tl_targets = tl_targets
        self.__name__ = "tl_simp_"+str(len(tl_targets))

    def __call__(self,in_data,out_data=None):
        if out_data is None and isinstance(in_data, dict):
            keys = in_data.keys()
            for target_key in self.tl_targets:
                if target_key in keys:
                    del in_data[target_key]
            return in_data
        elif isinstance(in_data, str) and isinstance(out_data, str):
            with open(in_data, 'r') as input_file, open(out_data, 'w') as output_file:
                content = input_file.read()
                raven = json.loads(content)
                keys = raven.keys()
                for target_key in self.tl_targets:
                    if target_key in keys:
                        del raven[target_key]

                json.dump(raven, output_file,indent=2)
        else:
            raise ValueError("Invalid arguments. Expected either a dictionary or two filenames.")


if __name__ == "__main__":
    #Setup Test Cases
    test_set = ["IEEE13_Assets.dss"       ,"case3_lm_1230.dss"    ,"case_mxshunt_2.dss"  ,"case2_diag.dss"      ,"ut_trans_2w_dy_lead.dss"
               ,"IEEE13_CapControl.dss"   ,"case3_lm_models.dss"  ,"case_tabulation.dss" ,"test2_Buscoords.dss" ,"ut_trans_2w_dy_lead_small_series_impedance.dss"
               ,"IEEE13_RegControl.dss"   ,"case3_lm_models_2.dss","dist_transformer.dss","test2_Linecodes.dss" ,"ut_trans_2w_yy.dss"
               ,"IEEE13_test_controls.dss","case3_unbalanced.dss ","ieee13_feeder.dss"   ,"test2_Loadshape.dss" ,"ut_trans_2w_yy_bank.dss"]
    path = "../PowerModelsDistribution.jl/test/data/opendss/"
    test_set = [path+file for file in test_set]

    print(test_set)
    tl_test = tl_simp(['Versions', 'Location', 'EnergyConnectionProfile', 'LoadResponseCharacteristic'])
    tl_test("/home/oreed/A12025/MG-CROWS/tmp/ravens_control.json","tmp/test.json")
