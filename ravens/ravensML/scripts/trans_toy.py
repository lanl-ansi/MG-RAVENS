import sys
import os
import re
import networkx as nx
import numpy as np
from collections import Counter
from typing import List, Sequence, Tuple, Any, Dict, Set
from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[1]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))
from framework.dataset import MGRavensDataset
from methods.transformers.trivial_solution.trans_IterativeOpti import Trans_Iterative_Optimizer
from methods.transformers.gen_trans_error import generate_trans_error


# --------------------------------------------------------------
# 1 Load data & generate predictions
# --------------------------------------------------------------
def test_trans_optimizer():
    print("Loading dataset...")
    # Load the dataset
    MGR = MGRavensDataset(data_dir="ravens/ravensML/data/trans_test")
    
    print("Generating trans errors...")
    # Generate trans errors
    MGR_trans, Y = generate_trans_error(MGR, 
                                  occurrence_prob=1,
                                  deletion_prob=.2,
                                  mult_mean=1,
                                  mult_var=5,
                                  add_mean=0,
                                  add_var=5, 
                                  size=3)  # Use 3 samples for testing
    
    # Process the dataset for ML
    MGR_trans.process_for_ML()
    
    # Store original parameters before optimization
    original_params = []
    for i in range(len(MGR)):
        _, _, ml_data = MGR[i]
        original_params.append(ml_data["edge_features"])
    
    print("Running trans Iterative Optimizer...")
    # Create and run the optimizer
    TIO = Trans_Iterative_Optimizer(max_iter=10)
    opt_MGR_Trans = TIO(MGR_trans)
    
    # Get optimized parameters
    optimized_params = []
    for i in range(len(MGR_trans)):
        _, _, ml_data = opt_MGR_Trans[i]
        optimized_params.append(ml_data["edge_features"])
    
    return original_params, optimized_params


# --------------------------------------------------------------
# 2 Compare branch parameters
# --------------------------------------------------------------
def compare_branch_parameters(original_params, optimized_params):
    """
    Compare R, X, B matrices between original and optimized branches
    """
    comparison_results = []
    
    for i in range(len(original_params)):
        grid_results = {
            "grid_index": i,
            "branches": {}
        }
        
        orig_branches = original_params[i]
        opt_branches = optimized_params[i]
        
        # Find common branches
        common_branches = set(orig_branches.keys()).intersection(set(opt_branches.keys()))
        # print(f"<DEBUG> Common Branches: {common_branches}")
        for branch_id in common_branches:
            orig_branch = orig_branches[branch_id]
            opt_branch = opt_branches[branch_id]
            # print(f"<DEBUG> orig R: {orig_branch["R"]}, opti R: {opt_branch["R"]}")
            # Calculate differences in R, X, B matrices
            r_diff = calculate_matrix_difference(orig_branch["R"], opt_branch["R"])
            x_diff = calculate_matrix_difference(orig_branch["X"], opt_branch["X"])
            b_diff = calculate_matrix_difference(orig_branch["B"], opt_branch["B"])
            g_diff = calculate_matrix_difference(orig_branch["G"], opt_branch["G"])
            
            # Calculate relative differences (percentage)
            r_rel_diff = calculate_relative_difference(orig_branch["R"], opt_branch["R"])
            x_rel_diff = calculate_relative_difference(orig_branch["X"], opt_branch["X"])
            b_rel_diff = calculate_relative_difference(orig_branch["B"], opt_branch["B"])
            g_rel_diff = calculate_relative_difference(orig_branch["G"], opt_branch["G"])
            # print(f"<DEBUG> r_diff: {r_diff}")
            grid_results["branches"][branch_id] = {
                "R_diff": r_diff,
                "X_diff": x_diff,
                "B_diff": b_diff,
                "G_diff": g_diff,
                "R_rel_diff": r_rel_diff,
                "X_rel_diff": x_rel_diff,
                "B_rel_diff": b_rel_diff,
                "G_rel_diff": g_rel_diff
            }
        
        comparison_results.append(grid_results)
    
    return comparison_results


def calculate_matrix_difference(matrix1, matrix2):
    """
    Calculate the average absolute difference between two matrices
    """
    m1 = np.array(matrix1)
    m2 = np.array(matrix2)
    
    if m1.shape != m2.shape:
        return float('nan')
    
    return np.mean(m1 - m2)


def calculate_relative_difference(matrix1, matrix2):
    """
    Calculate the average relative difference (percentage) between two matrices
    """
    m1 = np.array(matrix1)
    m2 = np.array(matrix2)
    
    if m1.shape != m2.shape:
        return float('nan')
    
    # Avoid division by zero
    denominator = np.maximum(np.abs(m1), 1e-10)
    rel_diff = np.abs(m1 - m2) / denominator * 100
    
    return np.mean(rel_diff)


# --------------------------------------------------------------
# 3 Print a detailed report
# --------------------------------------------------------------
def print_parameter_report(comparison_results):
    """
    Print a detailed report of branch parameter differences
    """
    print("\n" + "="*70)
    print("Transformer Iterative Optimizer Branch Parameter Comparison")
    print("="*70)
    
    for grid_result in comparison_results:
        grid_index = grid_result["grid_index"]
        branches = grid_result["branches"]
        
        print(f"\nGrid {grid_index + 1} - {len(branches)} branches analyzed")
        print("-"*70)
        
        if not branches:
            print("  No common branches found for comparison.")
            continue
        
        # Calculate grid-level averages
        avg_r_diff = np.mean([b["R_diff"] for b in branches.values()])
        avg_x_diff = np.mean([b["X_diff"] for b in branches.values()])
        avg_b_diff = np.mean([b["B_diff"] for b in branches.values()])
        avg_g_diff = np.mean([b["G_diff"] for b in branches.values()])
        
        avg_r_rel_diff = np.mean([b["R_rel_diff"] for b in branches.values()])
        avg_x_rel_diff = np.mean([b["X_rel_diff"] for b in branches.values()])
        avg_b_rel_diff = np.mean([b["B_rel_diff"] for b in branches.values()])
        avg_g_rel_diff = np.mean([b["G_rel_diff"] for b in branches.values()])

        print(f"  Average differences:")
        print(f"    R matrix: {avg_r_diff:.6f}")
        print(f"    X matrix: {avg_x_diff:.6f}")
        print(f"    B matrix: {avg_b_diff:.6f}")
        print(f"    G matrix: {avg_g_diff:.6f}")
        
        print(f"  Average relative differences (%):")
        print(f"    R matrix: {avg_r_rel_diff:.2f}%")
        print(f"    X matrix: {avg_x_rel_diff:.2f}%")
        print(f"    B matrix: {avg_b_rel_diff:.2f}%")
        print(f"    G matrix: {avg_g_rel_diff:.2f}%")
        
        # Print details for branches with significant changes
        print("\n  Branches with significant changes (>10% relative difference):")
        significant_branches = {bid: data for bid, data in branches.items() 
                              if data["R_rel_diff"] > 10 or data["X_rel_diff"] > 10 or data["B_rel_diff"] > 10}
        
        if significant_branches:
            for branch_id, data in significant_branches.items():
                print(f"    Branch {branch_id}:")
                print(f"      R diff: {data['R_diff']:.6f} ({data['R_rel_diff']:.2f}%)")
                print(f"      X diff: {data['X_diff']:.6f} ({data['X_rel_diff']:.2f}%)")
                print(f"      B diff: {data['B_diff']:.6f} ({data['B_rel_diff']:.2f}%)")
                print(f"      G diff: {data['G_diff']:.6f} ({data['G_rel_diff']:.2f}%)")
        else:
            print("    No branches with significant changes found.")
    
    print("="*70)


def main():
    # Run the test
    original_params, optimized_params = test_trans_optimizer()
    
    # Compare branch parameters
    comparison_results = compare_branch_parameters(original_params, optimized_params)
    
    # Print report
    print_parameter_report(comparison_results)


if __name__ == "__main__":
    main()
