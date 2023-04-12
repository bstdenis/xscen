"""Spatial tools."""
import datetime
import itertools
import warnings
from copy import deepcopy
from pathlib import Path

import clisops.core.subset
import dask
import numpy as np
import sparse as sp
import xarray as xr
import xclim as xc
from xclim.core.utils import uses_dask

__all__ = [
    "creep_weights",
    "creep_fill",
    "subset",
]


def creep_weights(mask, n=1, mode="clip"):
    """Compute weights for the creep fill.

    The output is a sparse matrix with the same dimensions as `mask`, twice.

    Parameters
    ----------
    mask : DataArray
      A boolean DataArray. False values are candidates to the filling.
      Usually they represent missing values (`mask = da.notnull()`).
      All dimensions are creep filled.
    n : int
      The order of neighbouring to use. 1 means only the adjacent grid cells are used.
    mode : {'clip', 'wrap'}
      If a cell is on the edge of the domain, `mode='wrap'` will wrap around to find neighbours.

    Returns
    -------
    DataArray
       Weights. The dot product must be taken over the last N dimensions.
    """
    da = mask
    mask = da.values
    neighbors = np.array(
        list(itertools.product(*[np.arange(-n, n + 1) for j in range(mask.ndim)]))
    ).T
    src = []
    dst = []
    w = []
    it = np.nditer(mask, flags=["f_index", "multi_index"], order="C")
    for i in it:
        if not i:
            neigh_idx_2d = np.atleast_2d(it.multi_index).T + neighbors
            neigh_idx_1d = np.ravel_multi_index(
                neigh_idx_2d, mask.shape, order="C", mode=mode
            )
            neigh_idx = np.unravel_index(np.unique(neigh_idx_1d), mask.shape, order="C")
            neigh = mask[neigh_idx]
            N = (neigh).sum()
            if N > 0:
                src.extend([it.multi_index] * N)
                dst.extend(np.stack(neigh_idx)[:, neigh].T)
                w.extend([1 / N] * N)
            else:
                src.extend([it.multi_index])
                dst.extend([it.multi_index])
                w.extend([np.nan])
        else:
            src.extend([it.multi_index])
            dst.extend([it.multi_index])
            w.extend([1])
    crds = np.concatenate((np.array(src).T, np.array(dst).T), axis=0)
    return xr.DataArray(
        sp.COO(crds, w, (*da.shape, *da.shape)),
        dims=[f"{d}_out" for d in da.dims] + list(da.dims),
        coords=da.coords,
        name="creep_fill_weights",
    )


def creep_fill(da, w):
    """Creep fill using pre-computed weights.

    Parameters
    ----------
    da: DataArray
      A DataArray sharing the dimensions with the one used to compute the weights.
      It can have other dimensions.
      Dask is supported as long as there are no chunks over the creeped dims.
    w: DataArray
      The result of `creep_weights`.

    Returns
    -------
    xarray.DataArray, same shape as `da`, but values filled according to `w`.

    Examples
    --------
    >>> w = creep_weights(da.isel(time=0).notnull(), n=1)
    >>> da_filled = creep_fill(da, w)
    """

    def _dot(arr, wei):
        N = wei.ndim // 2
        extra_dim = arr.ndim - N
        return np.tensordot(arr, wei, axes=(np.arange(N) + extra_dim, np.arange(N) + N))

    N = w.ndim // 2
    return xr.apply_ufunc(
        _dot,
        da,
        w,
        input_core_dims=[w.dims[N:], w.dims],
        output_core_dims=[w.dims[N:]],
        dask="parallelized",
        output_dtypes=["float64"],
    )


def subset(ds: xr.Dataset, region: dict) -> xr.Dataset:
    """
    Subset the data to a region.

    Either creates a slice and uses the .sel() method or customize a call to
    clisops.subset() that allows for an automatic buffer around the region.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset to be subsetted
    region : dict
        Description of the region and the subsetting method (required fields listed in the Notes)

    Notes
    -----
    'region' fields:
        name: str
            Region name used to overwrite domain in the catalog.
        method: str
            ['gridpoint', 'bbox', shape','sel']
            If the method is `sel`, this is not a call to clisops but only a subsetting with the xarray .sel() fonction.
            The keys are the dimensions to subset and the values are turned into a slice.
        <method>: dict
            Arguments specific to the method used.
        buffer: float, optional
            Multiplier to apply to the model resolution.

    Returns
    -------
    xr.Dataset
        Subsetted Dataset.

    See Also
    --------
    clisops.core.subset.subset_gridpoint, clisops.core.subset.subset_bbox, clisops.core.subset.subset_shape
    """
    if uses_dask(ds.lon) or uses_dask(ds.lat):
        warnings.warn("Loading longitude and latitude for more efficient subsetting.")
        ds["lon"], ds["lat"] = dask.compute(ds.lon, ds.lat)
    if "buffer" in region.keys():
        # estimate the model resolution
        if len(ds.lon.dims) == 1:  # 1D lat-lon
            lon_res = np.abs(ds.lon.diff("lon")[0].values)
            lat_res = np.abs(ds.lat.diff("lat")[0].values)
        else:
            lon_res = np.abs(ds.lon[0, 0].values - ds.lon[0, 1].values)
            lat_res = np.abs(ds.lat[0, 0].values - ds.lat[1, 0].values)

    kwargs = deepcopy(region[region["method"]])

    if region["method"] in ["gridpoint"]:
        ds_subset = clisops.core.subset_gridpoint(ds, **kwargs)
        new_history = (
            f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"{region['method']} spatial subsetting on {len(region['gridpoint']['lon'])} coordinates - clisops v{clisops.__version__}"
        )

    elif region["method"] in ["bbox"]:
        if "buffer" in region.keys():
            # adjust the boundaries
            kwargs["lon_bnds"] = (
                kwargs["lon_bnds"][0] - lon_res * region["buffer"],
                kwargs["lon_bnds"][1] + lon_res * region["buffer"],
            )
            kwargs["lat_bnds"] = (
                kwargs["lat_bnds"][0] - lat_res * region["buffer"],
                kwargs["lat_bnds"][1] + lat_res * region["buffer"],
            )

        if xc.core.utils.uses_dask(ds.cf["longitude"]):
            ds[ds.cf["longitude"].name].load()
        if xc.core.utils.uses_dask(ds.cf["latitude"]):
            ds[ds.cf["latitude"].name].load()

        ds_subset = clisops.core.subset_bbox(ds, **kwargs)
        new_history = (
            f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"{region['method']} spatial subsetting with {'buffer=' + str(region['buffer']) if 'buffer' in region else 'no buffer'}"
            f", lon_bnds={np.array(region['bbox']['lon_bnds'])}, lat_bnds={np.array(region['bbox']['lat_bnds'])}"
            f" - clisops v{clisops.__version__}"
        )

    elif region["method"] in ["shape"]:
        if "buffer" in region.keys():
            kwargs["buffer"] = np.max([lon_res, lat_res]) * region["buffer"]

        ds_subset = clisops.core.subset_shape(ds, **kwargs)
        new_history = (
            f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"{region['method']} spatial subsetting with {'buffer=' + str(region['buffer']) if 'buffer' in region else 'no buffer'}"
            f", shape={Path(region['shape']['shape']).name if isinstance(region['shape']['shape'], (str, Path)) else 'gpd.GeoDataFrame'}"
            f" - clisops v{clisops.__version__}"
        )

    elif region["method"] in ["sel"]:
        arg_sel = {
            dim: slice(*map(float, bounds)) for dim, bounds in region["sel"].items()
        }
        ds_subset = ds.sel(**arg_sel)
        new_history = (
            f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"{region['method']} subsetting with arguments {arg_sel}"
        )

    else:
        raise ValueError("Subsetting type not recognized")

    history = (
        new_history + " \n " + ds_subset.attrs["history"]
        if "history" in ds_subset.attrs
        else new_history
    )
    ds_subset.attrs["history"] = history
    ds_subset.attrs["cat:domain"] = region["name"]

    return ds_subset