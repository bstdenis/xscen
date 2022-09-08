import datetime
import logging
from pathlib import Path
from typing import Union

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
import xesmf as xe
from shapely.geometry import Polygon
from xclim.core.calendar import parse_offset

from .config import parse_config
from .extract import clisops_subset

logger = logging.getLogger(__name__)

__all__ = ["climatological_mean", "compute_deltas", "spatial_mean", "unstack_dates"]


@parse_config
def climatological_mean(
    ds: xr.Dataset,
    *,
    window: int = None,
    min_periods: int = None,
    interval: int = 1,
    periods: list = None,
    to_level: str = "climatology",
) -> xr.Dataset:
    """
    Computes the mean over 'year' for given time periods, respecting the temporal resolution of ds.

    Parameters
    ----------
    ds : xr.Dataset
      Dataset to use for the computation.
    window: int
      Number of years to use for the time periods.
      If left at None, all years will be used.
    min_periods: int
      For the rolling operation, minimum number of years required for a value to be computed.
      If left at None, it will be deemed the same as 'window'
    interval: int
      Interval (in years) at which to provide an output.
    periods: list
      list of [start, end] of continuous periods to be considered. This is needed when the time axis of ds contains some jumps in time.
      If None, the dataset will be considered continuous.
    to_level : str, optional
      The processing level to assign to the output.
      If None, the processing level of the inputs is preserved.

    Returns
    -------
    xr.Dataset
      Returns a Dataset of the climatological mean

    """

    window = window or int(ds.time.dt.year[-1] - ds.time.dt.year[0])
    min_periods = min_periods or window

    # separate 1d time in coords (day, month, and year) to make climatological mean faster
    ind = pd.MultiIndex.from_arrays(
        [ds.time.dt.year.values, ds.time.dt.month.values, ds.time.dt.day.values],
        names=["year", "month", "day"],
    )
    ds_unstack = ds.assign(time=ind).unstack("time")

    # Rolling will ignore jumps in time, so we want to raise an exception beforehand
    if (not all(ds_unstack.year.diff(dim="year", n=1) == 1)) & (periods is None):
        raise ValueError("Data is not continuous. Use the 'periods' argument.")

    # Compute temporal means
    concats = []
    periods = periods or [[int(ds_unstack.year[0]), int(ds_unstack.year[-1])]]
    for period in periods:
        # Rolling average
        ds_rolling = (
            ds_unstack.sel(year=slice(str(period[0]), str(period[1])))
            .rolling(year=window, min_periods=min_periods)
            .mean()
        )

        # Select every horizons in 'x' year intervals, starting from the first full windowed mean
        ds_rolling = ds_rolling.isel(
            year=slice(window - 1, None)
        )  # Select from the first full windowed mean
        intervals = ds_rolling.year.values % interval
        ds_rolling = ds_rolling.sel(year=(intervals - intervals[0] == 0))
        horizons = xr.DataArray(
            [f"{yr - (window - 1)}-{yr}" for yr in ds_rolling.year.values],
            dims=dict(year=ds_rolling.year),
        ).astype(str)
        ds_rolling = ds_rolling.assign_coords(horizon=horizons)

        # get back to 1D time
        ds_rolling = ds_rolling.stack(time=("year", "month", "day"))
        # rebuild time coord
        time_coord = [
            pd.to_datetime(f"{y - window + 1}, {m}, {d}")
            for y, m, d in zip(
                ds_rolling.year.values, ds_rolling.month.values, ds_rolling.day.values
            )
        ]
        ds_rolling = ds_rolling.assign_coords(time=time_coord).transpose("time", ...)

        concats.extend([ds_rolling])
    ds_rolling = xr.concat(concats, dim="time", data_vars="minimal")

    # modify attrs and history
    for vv in ds_rolling.data_vars:
        for a in ["description", "long_name"]:
            if hasattr(ds_rolling[vv], a):
                ds_rolling[vv].attrs[
                    a
                ] = f"{window}-year mean of {ds_rolling[vv].attrs[a]}"

        new_history = (
            f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {window}-year rolling average (non-centered) "
            f"with a minimum of {min_periods} years of data - xarray v{xr.__version__}"
        )
        history = (
            new_history + " \n " + ds_rolling[vv].attrs["history"]
            if "history" in ds_rolling[vv].attrs
            else new_history
        )
        ds_rolling[vv].attrs["history"] = history

    if to_level is not None:
        ds_rolling.attrs["cat:processing_level"] = to_level

    return ds_rolling


@parse_config
def compute_deltas(
    ds: xr.Dataset,
    reference_horizon: str,
    *,
    kind: Union[str, dict] = "+",
    rename_variables: bool = True,
    to_level: str = "delta_climatology",
) -> xr.Dataset:
    """
    Computes deltas in comparison to a reference time period, respecting the temporal resolution of ds.

    Parameters
    ----------
    ds : xr.Dataset
      Dataset to use for the computation.
    reference_horizon: str
      YYYY-YYYY string corresponding to the 'horizon' coordinate of the reference period.
    kind: str
      ['+', '/'] Whether to provide absolute or relative deltas.
      Can also be a dictionary separated per variable name.
    rename_variables: bool
      If True, '_delta_YYYY-YYYY' will be added to variable names.
    to_level : str, optional
      The processing level to assign to the output.
      If None, the processing level of the inputs is preserved.

    Returns
    -------
    xr.Dataset
      Returns a Dataset with the requested deltas.

    """

    # Separate the reference from the other horizons
    ref = ds.where(ds.horizon == reference_horizon, drop=True)
    # Remove references to 'year' in REF
    ind = pd.MultiIndex.from_arrays(
        [ref.time.dt.month.values, ref.time.dt.day.values], names=["month", "day"]
    )
    ref = ref.assign(time=ind).unstack("time")

    ind = pd.MultiIndex.from_arrays(
        [
            ds.time.dt.year.values,
            ds.time.dt.month.values,
            ds.time.dt.day.values,
        ],
        names=["year", "month", "day"],
    )
    other_hz = ds.assign(time=ind).unstack("time")

    deltas = xr.Dataset(coords=other_hz.coords, attrs=other_hz.attrs)
    # Calculate deltas
    for vv in list(ds.data_vars):
        if (isinstance(kind, dict) and kind[vv] == "+") or kind == "+":
            _kind = "absolute"
        elif (isinstance(kind, dict) and kind[vv] == "/") or kind == "/":
            _kind = "relative"
        else:
            raise ValueError("Delta 'kind' not understood.")

        v_name = (
            vv
            if rename_variables is False
            else f"{vv}_delta_{reference_horizon.replace('-', '_')}"
        )
        with xr.set_options(keep_attrs=True):
            if _kind == "absolute":
                deltas[v_name] = other_hz[vv] - ref[vv]
            else:
                deltas[v_name] = other_hz[vv] / ref[vv]
                deltas[v_name].attrs["units"] = ""

        # modify attrs and history
        deltas[v_name].attrs["delta_kind"] = _kind
        deltas[v_name].attrs["delta_reference"] = reference_horizon

        for a in ["description", "long_name"]:
            if hasattr(other_hz[vv], a):
                deltas[v_name].attrs[
                    a
                ] = f"{other_hz[vv].attrs[a]}: {_kind} delta compared to {reference_horizon.replace('-', '_')}."

        new_history = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {_kind} delta vs. {reference_horizon} - xarray v{xr.__version__}"
        history = (
            new_history + " \n " + deltas[v_name].attrs["history"]
            if "history" in deltas[v_name].attrs
            else new_history
        )
        deltas[v_name].attrs["history"] = history

    # get back to 1D time
    deltas = deltas.stack(time=("year", "month", "day"))
    # rebuild time coord
    time_coord = [
        pd.to_datetime(f"{y}, {m}, {d}")
        for y, m, d in zip(deltas.year.values, deltas.month.values, deltas.day.values)
    ]
    deltas = deltas.assign(time=time_coord).transpose("time", ...)
    deltas = deltas.reindex_like(ds)

    if to_level is not None:
        deltas.attrs["cat:processing_level"] = to_level

    return deltas


def spatial_mean(
    ds: xr.Dataset,
    method: str,
    *,
    call_clisops: bool = False,
    region: dict = None,
    kwargs: dict = None,
    simplify_tolerance: float = None,
    to_domain: str = None,
    to_level: str = None,
) -> xr.Dataset:
    """
    Computes the spatial mean using a variety of available methods.

    Parameters
    ----------
    ds: xr.Dataset
      Dataset to use for the computation.
    method: str
      'mean' will perform a .mean() over the spatial dimensions of the Dataset.
      'interp_coord' will find the region's centroid (if coordinates are not fed through kwargs), then perform a .interp() over the spatial dimensions of the Dataset.
      The coordinate can also be directly fed to .interp() through the 'kwargs' argument below.
      'xesmf' will make use of xESMF's SpatialAverager. This will typically be more precise, especially for irregular regions, but can be much slower than other methods.
    call_clisops: bool
      If True, xscen.extraction.clisops_subset will be called prior to the other operations. This requires the 'region' argument.
    region: dict
      Description of the region and the subsetting method (required fields listed in the Notes).
      If method=='interp_coord', this is used to find the region's centroid.
      If method=='xesmf', the bounding box or shapefile is given to SpatialAverager.
    kwargs: dict
      Arguments to send to either mean(), interp() or SpatialAverager().
      In the latter case, one can give `skipna` here, to be passed to the averager call itself.
    simplify_tolerance: float
      Precision (in degree) used to simplify a shapefile before sending it to SpatialAverager().
      The simpler the polygons, the faster the averaging, but it will lose some precision.
    to_domain : str, optional
      The domain to assign to the output.
      If None, the domain of the inputs is preserved.
    to_level : str, optional
      The processing level to assign to the output.
      If None, the processing level of the inputs is preserved.

    Returns
    -------
    xr.Dataset
      Returns a Dataset with the spatial dimensions averaged.


    Notes
    -----
    'region' required fields:
        method: str
            ['gridpoint', 'bbox', shape']
        <method>: dict
            Arguments specific to the method used.
        buffer: float, optional
            Multiplier to apply to the model resolution. Only used if call_clisops==True.

    See Also
    ________
    xarray.Dataset.mean, xarray.Dataset.interp, xesmf.SpatialAverager

    """

    kwargs = kwargs or {}

    # If requested, call xscen.extraction.clisops_subset prior to averaging
    if call_clisops:
        ds = clisops_subset(ds, region)

    # This simply calls .mean() over the spatial dimensions
    if method == "mean":
        if "dim" not in kwargs:
            # Determine the X and Y names
            spatial_dims = []
            for d in ["X", "Y"]:
                if d in ds.cf.axes:
                    spatial_dims.extend([ds.cf[d].name])
                elif (
                    (d == "X")
                    and ("longitude" in ds.cf.coordinates)
                    and (len(ds[ds.cf.coordinates["longitude"][0]].dims) == 1)
                ):
                    spatial_dims.extend(ds.cf.coordinates["longitude"])
                elif (
                    (d == "Y")
                    and ("latitude" in ds.cf.coordinates)
                    and (len(ds[ds.cf.coordinates["latitude"][0]].dims) == 1)
                ):
                    spatial_dims.extend(ds.cf.coordinates["latitude"])
            if len(spatial_dims) == 0:
                raise ValueError(
                    "Could not determine the spatial dimension(s) using CF conventions. Use kwargs = {dim: list} to specify on which dimension to perform the averaging."
                )
            kwargs["dim"] = spatial_dims

        ds_agg = ds.mean(keep_attrs=True, **kwargs)

        # Prepare the History field
        new_history = (
            f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"xarray.mean(dim={kwargs['dim']}) - xarray v{xr.__version__}"
        )

    # This calls .interp() to a pair of coordinates
    elif method == "interp_coord":

        # Find the centroid
        if region is not None:
            if region["method"] == "gridpoint":
                if len(region["gridpoint"]["lon"] != 1):
                    raise ValueError(
                        "Only a single location should be used with interp_centroid."
                    )
                centroid = {
                    "lon": region["gridpoint"]["lon"],
                    "lat": region["gridpoint"]["lat"],
                }

            elif region["method"] == "bbox":
                centroid = {
                    "lon": np.mean(region["bbox"]["lon_bnds"]),
                    "lat": np.mean(region["bbox"]["lat_bnds"]),
                }

            elif region["method"] == "shape":
                s = gpd.read_file(region["shape"]["shape"])
                if len(s != 1):
                    raise ValueError(
                        "Only a single polygon should be used with interp_centroid."
                    )
                centroid = {"lon": s.centroid[0].x, "lat": s.centroid[0].y}
            else:
                raise ValueError("'method' not understood.")
            kwargs.update(centroid)

        ds_agg = ds.interp(**kwargs)

        new_history = (
            f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"xarray.interp(**{kwargs}) - xarray v{xr.__version__}"
        )

    # Uses xesmf.SpatialAverager
    elif method == "xesmf":

        # If the region is a bounding box, call shapely and geopandas to transform it into an input compatible with xesmf
        if region["method"] == "bbox":
            lon_point_list = [
                region["bbox"]["lon_bnds"][0],
                region["bbox"]["lon_bnds"][0],
                region["bbox"]["lon_bnds"][1],
                region["bbox"]["lon_bnds"][1],
            ]
            lat_point_list = [
                region["bbox"]["lat_bnds"][0],
                region["bbox"]["lat_bnds"][1],
                region["bbox"]["lat_bnds"][1],
                region["bbox"]["lat_bnds"][0],
            ]

            polygon_geom = Polygon(zip(lon_point_list, lat_point_list))
            polygon = gpd.GeoDataFrame(index=[0], geometry=[polygon_geom])

            # Prepare the History field
            new_history = (
                f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"xesmf.SpatialAverager over {region['bbox']['lon_bnds']}{region['bbox']['lat_bnds']} - xESMF v{xe.__version__}"
            )

        # If the region is a shapefile, open with geopandas
        elif region["method"] == "shape":
            polygon = gpd.read_file(region["shape"]["shape"])

            # Simplify the geometries to a given tolerance, if needed.
            # The simpler the polygons, the faster the averaging, but it will lose some precision.
            if simplify_tolerance is not None:
                polygon["geometry"] = polygon.simplify(
                    tolerance=simplify_tolerance, preserve_topology=True
                )

            # Prepare the History field
            new_history = (
                f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"xesmf.SpatialAverager over {Path(region['shape']['shape']).name} - xESMF v{xe.__version__}"
            )

        else:
            raise ValueError("'method' not understood.")

        skipna = kwargs.pop("skipna", False)
        savg = xe.SpatialAverager(ds, polygon.geometry, **kwargs)
        ds_agg = savg(ds, keep_attrs=True, skipna=skipna)
        extra_coords = {
            col: xr.DataArray(polygon[col], dims=("geom",))
            for col in polygon.columns
            if col != "geometry"
        }
        extra_coords["geom"] = xr.DataArray(polygon.index, dims=("geom",))
        ds_agg = ds_agg.assign_coords(**extra_coords)
        if len(polygon) == 1:
            ds_agg = ds_agg.squeeze("geom")

    else:
        raise ValueError(
            "Subsetting method should be ['mean', 'interp_coord', 'xesmf']"
        )

    # History
    history = (
        new_history + " \n " + ds_agg.attrs["history"]
        if "history" in ds_agg.attrs
        else new_history
    )
    ds_agg.attrs["history"] = history

    # Attrs
    if to_domain is not None:
        ds_agg.attrs["cat:domain"] = to_domain
    if to_level is not None:
        ds_agg.attrs["cat:processing_level"] = to_level

    return ds_agg


@parse_config
def unstack_dates(
    ds: xr.Dataset,
    seasons: dict = None,
    new_dim: str = "season",
):
    """Unstack a multi-season timeseries into a yearly axis and a season one.

    Parameters
    ----------
    ds: xr.Dataset or DataArray
      The xarray object with a "time" coordinate.
    seasons: dict, optional
      A dictonary from "MM-DD" dates to a season name.
      If not given, it is guessed from the time coord's frequency.
      See notes.
    new_dim: str
      The name of the new dimension.

    Returns
    -------
    xr.Dataset or DataArray
      Same as ds but the time axis is now yearly (AS-JAN) and the seasons are long the new dimenion.

    Notes
    -----
    When `seasons` is None, :py:func:`xarray.infer_freq` is called and its output determines the new coordinate:

    - For MS, the coordinates are the month abbreviations in english (JAN, FEB, etc.)
    - For ?QS-? and other ?MS frequencies, the coordinates are the initials of the months in each season.
      Ex: QS-DEC : DJF, MAM, JJA, SON.
    - For YS or AS-JAN, the new coordinate has a single value of "annual".
    - For ?AS-? frequencies, the new coordinate has a single value of "annual-{anchor}", were "anchor"
      is the abbreviation of the first month of the year. Ex: AS-JUL -> "annual-JUL".
    - For any other frequency, this function fails is `seasons` is None.
    """
    if seasons is None:
        freq = xr.infer_freq(ds.time)
        if freq is not None:
            mult, base, _, _ = parse_offset(freq)
        if freq is None or base not in ["A", "Q", "M", "Y"]:
            raise ValueError(
                f"Can't infer season labels for time coordinate with frequency {freq}. Consider passing the  `seasons` dict explicitly."
            )

        # We want the class of the datetime coordinate, to ensure it is conserved.
        if base == "Q" or (base == "M" and mult > 1):
            # Labels are the month initials
            months = np.array(list("JFMAMJJASOND"))
            n = mult * {"M": 1, "Q": 3}[base]
            seasons = {
                f"{m:02d}-01": "".join(months[np.array(range(m - 1, m + n - 1)) % 12])
                for m in np.unique(ds.time.dt.month)
            }
        elif base in ["A", "Y"]:
            seasons = {
                f"{m:02d}-01": f"annual-{abb}"
                for m, abb in xr.coding.cftime_offsets._MONTH_ABBREVIATIONS.items()
            }
            seasons["01-01"] = "annual"
        else:  # M or MS
            seasons = {
                f"{m:02d}-01": abb
                for m, abb in xr.coding.cftime_offsets._MONTH_ABBREVIATIONS.items()
            }

    datetime = xr.coding.cftime_offsets.get_date_type(
        ds.time.dt.calendar, xr.coding.times.contains_cftime_datetimes(ds.time)
    )
    years = [datetime(yr, 1, 1) for yr in ds.time.dt.year.values]
    seas = [seasons[k] for k in ds.time.dt.strftime("%m-%d").values]
    ds = ds.assign_coords(
        time=pd.MultiIndex.from_arrays([years, seas], names=["_year", new_dim])
    )
    ds = ds.unstack("time").rename(_year="time")

    # Sort new coord
    inverted = dict(zip(seasons.values(), seasons.keys()))
    return ds.sortby(ds[new_dim].copy(data=[inverted[s] for s in ds[new_dim].values]))
