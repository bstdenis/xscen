import logging
import warnings
from pathlib import Path, PosixPath
from types import ModuleType
from typing import Optional, Sequence, Tuple, Union

import matplotlib as mpl
import numpy as np
import xarray as xr
import xclim as xc
from cartopy import crs
from matplotlib import pyplot as plt
from xclim import sdba
from xclim.core.indicator import Indicator
from xclim.core.units import convert_units_to
from xclim.sdba import measures

from .catalog import DataCatalog
from .indicators import load_xclim_module
from .io import save_to_zarr
from .utils import change_units, maybe_unstack, unstack_fill_nan

logger = logging.getLogger(__name__)

__all__ = [
    "fix_unphysical_values",
    "properties_and_measures",
    "measures_heatmap",
    "measures_improvement",
]

# TODO: Implement logging, warnings, etc.
# TODO: Change all paths to PosixPath objects, including in the catalog?


def fix_unphysical_values(
    catalog: DataCatalog,
):
    """
    Basic checkups for impossible values such as tasmin > tasmax, or negative precipitation

    Parameters
    ----------
    catalog : DataCatalog

    """

    if len(catalog.unique("processing_level")) > 1:
        raise NotImplementedError

    for domain in catalog.unique("domain"):
        for id in catalog.unique("id"):
            sim = catalog.search(id=id, domain=domain)

            # tasmin > tasmax
            if len(sim.search(variable=["tasmin", "tasmax"]).catalog) == 2:
                # TODO: Do something with the last output
                ds_tn = xr.open_zarr(
                    sim.search(variable="tasmin").catalog.df.iloc[0]["path"]
                )
                ds_tx = xr.open_zarr(
                    sim.search(variable="tasmax").catalog.df.iloc[0]["path"]
                )

                tn, tx, _ = _invert_unphysical_temperatures(
                    ds_tn["tasmin"], ds_tx["tasmax"]
                )
                ds_tn["tasmin"] = tn
                ds_tx["tasmax"] = tx
                # TODO: History, attrs, etc.

                save_to_zarr(
                    ds=ds_tn,
                    filename=sim.search(variable="tasmin").catalog.df.iloc[0]["path"],
                    zarr_kwargs={"mode": "w"},
                )
                save_to_zarr(
                    ds=ds_tx,
                    filename=sim.search(variable="tasmax").catalog.df.iloc[0]["path"],
                    zarr_kwargs={"mode": "w"},
                )

            # TODO: "clip" function for pr, sfcWind, huss/hurs, etc. < 0 (and > 1/100, when applicable).
            #   Can we easily detect the variables that need to be clipped ? From the units ?


def _invert_unphysical_temperatures(
    tasmin: xr.DataArray, tasmax: xr.Dataset
) -> Tuple[xr.DataArray, xr.DataArray, xr.DataArray]:
    """
    Invert tasmin and tasmax points where tasmax <  tasmin.

    Returns
    -------
    tasmin : xr.DataArray
      New tasmin.
    tasmax : xr.DataArray
      New tasmax
    switched : xr.DataArray
      A scalar DataArray with the number of switched data points.
    """
    is_bad = tasmax < tasmin
    mask = tasmax.isel(time=0).notnull()
    switch = is_bad & mask
    tn = xr.where(switch, tasmax, tasmin)
    tx = xr.where(switch, tasmin, tasmax)

    tn.attrs.update(tasmin.attrs)
    tx.attrs.update(tasmax.attrs)
    return tn, tx, switch.sum()


# TODO: just measures?


def properties_and_measures(
    ds: xr.Dataset,
    properties: Union[
        str, PosixPath, Sequence[Indicator], Sequence[Tuple[str, Indicator]], ModuleType
    ],
    period: list = None,
    unstack: bool = False,
    dref_for_measure: Optional[xr.Dataset] = None,
    change_units_arg: Optional[dict] = None,
    to_level_prop: str = "diag-properties",
    to_level_meas: str = "diag-measures",
):
    """
    Calculate properties and measures of a dataset.

    Parameters
    ----------
    ds: xr.Dataset
        Input dataset.
    properties: Union[str, PosixPath, Sequence[Indicator], Sequence[Tuple[str, Indicator]]]
      Path to a YAML file that instructs on how to calculate properties.
      Can be the indicator module directly, or a sequence of indicators or a sequence of
      tuples (indicator name, indicator) as returned by `iter_indicators()`.
    period: lst
        [start, end] of the period to be evaluated. The period will be selected on ds
        and dref_for_measure it it is given.
    unstack: bool
        Whether to unstack ds before computing the properties.
    dref_for_measure: xr.Dataset
        Dataset of properties to be used as the ref argument in the computation of the measure.
        Ideally, this is the first output (prop) of a previous call to this function.
        Only measures on properties that are provided both in this dataset and in the properties list will be computed.
        If None, the second output of the function (meas) will be an empty Dataset.
    change_units_arg: dict
        If not None, call `xscen.utils.change_units` on ds before computing properties using this dictionary for the `variables_and_units` argument.
        It can be useful to convert units before computing the properties, because it is sometimes easier to convert the units of the variables than the units of the properties (eg. variance).
    to_level_prop: str
        processing_level to give the first output (prop)
    to_level_meas: str
        processing_level to give the second output (meas)

    Returns
    -------
    prop: xr.Dataset
        Dataset of properties of ds
    meas: xr.Dataset
        Dataset of measures between prop and dref_for_meas

    """

    if isinstance(properties, (str, Path)):
        logger.debug("Loading properties module.")
        module = load_xclim_module(properties)
        properties = module.iter_indicators()
    elif hasattr(properties, "iter_indicators"):
        properties = properties.iter_indicators()

    try:
        N = len(properties)
    except TypeError:
        N = None
    else:
        logger.info(f"Computing {N} properties.")

    # select periods for ds
    if period is not None and "time" in ds:
        ds = ds.sel({"time": slice(str(period[0]), str(period[1]))})
        date_start = ds.time.values[0]
        date_end = ds.time.values[-1]
    # select periods for ref_measure
    if (
        dref_for_measure is not None
        and period is not None
        and "time" in dref_for_measure
    ):
        dref_for_measure = dref_for_measure.sel(
            {"time": slice(str(period[0]), str(period[1]))}
        )

    if unstack:
        ds = unstack_fill_nan(ds)

    if change_units_arg:
        ds = change_units(ds, variables_and_units=change_units_arg)

    prop = xr.Dataset()  # dataset with all properties
    meas = xr.Dataset()  # dataset with all measures
    for i, ind in enumerate(properties, 1):
        if isinstance(ind, tuple):
            iden, ind = ind
        # Make the call to xclim
        out = ind(ds=ds)
        vname = out.name
        logger.info(f"{i} - Computing {vname}.")
        prop[vname] = out

        # calculate the measure if a reference dataset is given for the measure
        if dref_for_measure and vname in dref_for_measure:
            meas[vname] = ind.get_measure()(
                sim=prop[vname], ref=dref_for_measure[vname]
            )
            # create a merged long_name
            prop_ln = prop[vname].attrs.pop("long_name", "").replace(".", "")
            meas_ln = meas[vname].attrs.pop("long_name", "").lower()
            meas_ln = meas_ln.replace("between the simulation and the reference", "")
            meas[vname].attrs["long_name"] = f"{prop_ln} {meas_ln}"

    for ds1 in [prop, meas]:
        ds1.attrs = ds.attrs
        ds1.attrs["cat:xrfreq"] = "fx"
        ds1.attrs.pop("cat:variable", None)
        ds1.attrs["cat:frequency"] = "fx"
        ds1.attrs["cat:timedelta"] = "NAN"
        if period:
            ds1.attrs["cat:date_start"] = date_start
            ds1.attrs["cat:date_end"] = date_end

    prop.attrs["cat:processing_level"] = to_level_prop
    meas.attrs["cat:processing_level"] = to_level_meas

    return prop, meas


def measures_heatmap(meas_datasets: Union[list, dict], to_level: str = "diag-heatmap"):
    """
    Create a heat map to compare the performance of the different datasets.
    The columns are properties and the rows are datasets.
    Each point is the absolute value of the mean of the measure over the whole domain.
    Each column is normalized from 0 (best) to 1 (worst).

    Parameters
    ----------
    meas_datasets: list|dict
        List or dictionary of datasets of measures of properties.
        If it is a dictionary, the keys will be used to name the rows.
        If it is a list, the rows will be given a number.

    to_level: str
        processing_level to assign to the output

    Returns
    -------
        xr.DataArray
    """

    name_of_datasets = None
    if isinstance(meas_datasets, dict):
        name_of_datasets = list(meas_datasets.keys())
        meas_datasets = list(meas_datasets.values())

    hmap = []
    for meas in meas_datasets:
        row = []
        # iterate through all available properties
        for var_name in meas:
            da = meas[var_name]
            # mean the absolute value of the bias over all positions and add to heat map
            if "xclim.sdba.measures.RATIO" in da.attrs["history"]:
                # if ratio, best is 1, this moves "best to 0 to compare with bias
                row.append(abs(da - 1).mean().values)
            else:
                row.append(abs(da).mean().values)
        # append all properties
        hmap.append(row)

    # plot heat map of biases ( 1 column per properties, 1 column for sim , 1 column for scen)
    hmap = np.array(hmap)
    # normalize to 0-1 -> best-worst
    hmap = np.array(
        [
            (c - min(c)) / (max(c) - min(c)) if max(c) != min(c) else [0.5] * len(c)
            for c in hmap.T
        ]
    ).T

    name_of_datasets = name_of_datasets or list(range(1, hmap.shape[0] + 1))

    ds_hmap = xr.DataArray(
        hmap,
        coords={
            "datasets": name_of_datasets,
            "properties": list(meas_datasets[0].data_vars),
        },
        dims=["datasets", "properties"],
    )
    ds_hmap = ds_hmap.to_dataset(name="heatmap")

    ds_hmap.attrs = xr.core.merge.merge_attrs(
        [ds.attrs for ds in meas_datasets], combine_attrs="drop_conflicts"
    )
    ds_hmap.attrs["cat:processing_level"] = to_level
    ds_hmap.attrs.pop("cat:variable", None)

    return ds_hmap


def measures_improvement(
    meas_datasets: Union[list, dict], to_level: str = "diag-improved"
):
    """
    Calculate the fraction of improved grid points for each properties between two datasets of measures.

    Parameters
    ----------
    meas_datasets: list|dict
     List of 2 datasets: Initial dataset of measures and final (improved) dataset of measures.
     Both datasets must have the same variables.
     It is also possible to pass a dictionary where the values are the datasets and the key are not used.
    to_level: str
        processing_level to assign to the output dataset

    Returns
    -------
    xr.Dataset

    """
    if isinstance(meas_datasets, dict):
        meas_datasets = list(meas_datasets.values())

    if len(meas_datasets) != 2:
        warnings.warn(
            "meas_datasets has more than 2 datasets."
            " Only the first 2 will be compared."
        )
    ds1 = meas_datasets[0]
    ds2 = meas_datasets[1]
    percent_better = []
    for var in ds2.data_vars:
        if "xclim.sdba.measures.RATIO" in ds1[var].attrs["history"]:
            diff_bias = abs(ds1[var] - 1) - abs(ds2[var] - 1)
        else:
            diff_bias = abs(ds1[var]) - abs(ds2[var])
        diff_bias = diff_bias.values.ravel()
        diff_bias = diff_bias[~np.isnan(diff_bias)]

        total = ds2[var].values.ravel()
        total = total[~np.isnan(total)]

        improved = diff_bias >= 0
        percent_better.append(np.sum(improved) / len(total))

    ds_better = xr.DataArray(
        percent_better, coords={"properties": list(ds2.data_vars)}, dims="properties"
    )

    ds_better = ds_better.to_dataset(name="improved_grid_points")

    ds_better.attrs = ds2.attrs
    ds_better.attrs["cat:processing_level"] = to_level
    ds_better.attrs.pop("cat:variable", None)

    return ds_better
