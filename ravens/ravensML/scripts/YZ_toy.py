import sys
import os
import re
import networkx as nx
import numpy as np
from collections import Counter
from typing import List, Sequence, Tuple, Any, Dict, Set
sys.path.append('/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML')
from framework.dataset import MGRavensDataset
from methods.YZ.trivial_solution.YZ_IterativeOpti import YZ_Iterative_Optimizer
from methods.YZ.gen_YZ_error import generate_yz_error


# --------------------------------------------------------------
# 1 Load data & generate predictions
# --------------------------------------------------------------
def test_yz_optimizer():
    print("Loading dataset...")
    # Load the dataset
    MGR = MGRavensDataset(data_dir="ravens/ravensML/data/YZ_test")
    
    print("Generating YZ errors...")
    # Generate YZ errors
    MGR_YZ, Y = generate_yz_error(MGR, 
                                  occurrence_prob=1,
                                  deletion_prob=0,
                                  mult_mean=1,
                                  mult_var=1,
                                  add_mean=0,
                                  add_var=1, 
                                  size=10)  # Use 3 samples for testing
    
    # Process the dataset for ML
    MGR_YZ.process_for_ML()
    
    # Store original parameters before optimization
    original_params = []
    for i in range(len(MGR)):
        _, _, ml_data = MGR[i]
        original_params.append(ml_data["edge_features"])
    
    print("Running YZ Iterative Optimizer...")
    # Create and run the optimizer
    YZIO = YZ_Iterative_Optimizer(max_iter=10)
    opt_MGR_YZ = YZIO(MGR_YZ)
    
    # Get optimized parameters
    optimized_params = []
    for i in range(len(MGR_YZ)):
        _, _, ml_data = opt_MGR_YZ[i]
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
            
            # Calculate relative differences (percentage)
            r_rel_diff = calculate_relative_difference(orig_branch["R"], opt_branch["R"])
            x_rel_diff = calculate_relative_difference(orig_branch["X"], opt_branch["X"])
            b_rel_diff = calculate_relative_difference(orig_branch["B"], opt_branch["B"])
            # print(f"<DEBUG> r_diff: {r_diff}")
            grid_results["branches"][branch_id] = {
                "R_diff": r_diff,
                "X_diff": x_diff,
                "B_diff": b_diff,
                "R_rel_diff": r_rel_diff,
                "X_rel_diff": x_rel_diff,
                "B_rel_diff": b_rel_diff
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
    
    return np.mean(np.abs(m1 - m2))


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
    print("YZ Iterative Optimizer Branch Parameter Comparison")
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
        
        avg_r_rel_diff = np.mean([b["R_rel_diff"] for b in branches.values()])
        avg_x_rel_diff = np.mean([b["X_rel_diff"] for b in branches.values()])
        avg_b_rel_diff = np.mean([b["B_rel_diff"] for b in branches.values()])
        
        print(f"  Average absolute differences:")
        print(f"    R matrix: {avg_r_diff:.6f}")
        print(f"    X matrix: {avg_x_diff:.6f}")
        print(f"    B matrix: {avg_b_diff:.6f}")
        
        print(f"  Average relative differences (%):")
        print(f"    R matrix: {avg_r_rel_diff:.2f}%")
        print(f"    X matrix: {avg_x_rel_diff:.2f}%")
        print(f"    B matrix: {avg_b_rel_diff:.2f}%")
        
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
        else:
            print("    No branches with significant changes found.")
    
    print("="*70)


def main():
    # Run the test
    original_params, optimized_params = test_yz_optimizer()
    
    # Compare branch parameters
    comparison_results = compare_branch_parameters(original_params, optimized_params)
    
    # Print report
    print_parameter_report(comparison_results)


if __name__ == "__main__":
    main()
