import pandas as pd


def build_package_exclusions(package_data: pd.DataFrame, lambda_func) -> list:
    return [pkg.Index for pkg in package_data.itertuples() if lambda_func(pkg)]


def build_object_exclusions(object_data: pd.DataFrame, lambda_func, exclude_packages=None) -> list:
    if exclude_packages is None:
        exclude_packages = []

    return [obj.Index for obj in object_data.itertuples() if lambda_func(obj)] + [
        obj.Index for p in exclude_packages for obj in object_data[object_data["Package_ID"] == p].itertuples()
    ]
