# noqa: D100
import inspect
import logging
import warnings
from copy import deepcopy
from pathlib import Path
from typing import Any, Union

import numpy as np
import pandas as pd
import xarray as xr
from xclim import ensembles

from .config import parse_config
from .utils import clean_up, get_cat_attrs

logger = logging.getLogger(__name__)

__all__ = ["ensemble_stats", "generate_weights"]


@parse_config
def ensemble_stats(
    datasets: Any,
    statistics: dict,
    *,
    create_kwargs: dict = None,
    weights: xr.DataArray = None,
    common_attrs_only: bool = True,
    to_level: str = "ensemble",
) -> xr.Dataset:
    """Create an ensemble and computes statistics on it.

    Parameters
    ----------
    datasets : Any
        List of file paths or xarray Dataset/DataArray objects to include in the ensemble.
        A dictionary can be passed instead of a list, in which case the keys are used as coordinates along the new
        `realization` axis.
        Tip: With a project catalog, you can do: `datasets = pcat.search(**search_dict).to_dataset_dict()`.
    statistics : dict
        xclim.ensembles statistics to be called. Dictionary in the format {function: arguments}.
        If a function requires 'ref', the dictionary entry should be the inputs of a .loc[], e.g. {"ref": {"horizon": "1981-2010"}}
    create_kwargs : dict
        Dictionary of arguments for xclim.ensembles.create_ensemble.
    weights : xr.DataArray
        Weights to apply along the 'realization' dimension. This array cannot contain missing values.
    common_attrs_only : bool
        If True, keeps only the global attributes that are the same for all datasets and generate new id.
        If False, keeps global attrs of the first dataset (same behaviour as xclim.ensembles.create_ensemble)
    to_level : str
        The processing level to assign to the output.

    Returns
    -------
    xr.Dataset
        Dataset with ensemble statistics

    See Also
    --------
    xclim.ensembles._base.create_ensemble, xclim.ensembles._base.ensemble_percentiles, xclim.ensembles._base.ensemble_mean_std_max_min, xclim.ensembles._robustness.change_significance, xclim.ensembles._robustness.robustness_coefficient,

    """
    create_kwargs = create_kwargs or {}

    # if input files are .zarr, change the engine automatically
    if isinstance(datasets, list) and isinstance(datasets[0], (str, Path)):
        path = Path(datasets[0])
        if path.suffix == ".zarr" and "engine" not in create_kwargs:
            create_kwargs["engine"] = "zarr"

    ens = ensembles.create_ensemble(datasets, **create_kwargs)

    ens_stats = xr.Dataset(attrs=ens.attrs)
    for stat, stats_kwargs in statistics.items():
        stats_kwargs = deepcopy(stats_kwargs or {})
        logger.info(
            f"Creating ensemble with {len(datasets)} simulations and calculating {stat}."
        )
        if (
            weights is not None
            and "weights" in inspect.getfullargspec(getattr(ensembles, stat))[0]
        ):
            stats_kwargs["weights"] = weights.reindex_like(ens.realization)
        if "ref" in stats_kwargs:
            stats_kwargs["ref"] = ens.loc[stats_kwargs["ref"]]

        if stat == "change_significance":
            for v in ens.data_vars:
                with xr.set_options(keep_attrs=True):
                    deltak = ens[v].attrs.get("delta_kind", None)
                    if stats_kwargs.get("ref") is not None and deltak is not None:
                        raise ValueError(
                            f"{v} is a delta, but 'ref' was still specified."
                        )
                    if deltak in ["relative", "*", "/"]:
                        logging.info(
                            f"Relative delta detected for {v}. Applying 'v - 1' before change_significance."
                        )
                        ens_v = ens[v] - 1
                    else:
                        ens_v = ens[v]
                    tmp = getattr(ensembles, stat)(ens_v, **stats_kwargs)
                    if len(tmp) == 2:
                        ens_stats[f"{v}_change_frac"], ens_stats[f"{v}_pos_frac"] = tmp
                    elif len(tmp) == 3:
                        (
                            ens_stats[f"{v}_change_frac"],
                            ens_stats[f"{v}_pos_frac"],
                            ens_stats[f"{v}_p_vals"],
                        ) = tmp
                    else:
                        raise ValueError(f"Unexpected number of outputs from {stat}.")
        else:
            ens_stats = ens_stats.merge(getattr(ensembles, stat)(ens, **stats_kwargs))

    # delete the realization coordinate if there
    if "realization" in ens_stats:
        ens_stats = ens_stats.drop_vars("realization")

    # delete attrs that are not common to all dataset
    if common_attrs_only:
        # if they exist remove attrs specific to create_ensemble
        create_kwargs.pop("mf_flag", None)
        create_kwargs.pop("resample_freq", None)
        create_kwargs.pop("calendar", None)
        create_kwargs.pop("preprocess", None)

        ens_stats = clean_up(
            ds=ens_stats,
            common_attrs_only=datasets,
            common_attrs_open_kwargs=create_kwargs,
        )

    ens_stats.attrs["cat:processing_level"] = to_level
    ens_stats.attrs["ensemble_size"] = len(datasets)

    return ens_stats


def generate_weights(
    datasets: Union[dict, list],
    *,
    independence_level: str = "all",
    split_experiments: bool = False,
    include_nan: bool = True,
) -> xr.DataArray:
    """Use realization attributes to automatically generate weights along the 'realization' dimension.

    Parameters
    ----------
    datasets : dict
        List of Dataset objects that will be included in the ensemble.
        The datasets should include attributes to help recognize them - 'cat:activity','cat:source', and 'cat:driving_model' for regional models.
        A dictionary can be passed instead of a list, in which case the keys are used for the 'realization' coordinate.
        Tip: With a project catalog, you can do: `datasets = pcat.search(**search_dict).to_dataset_dict()`.
    independence_level : str
        'all': Weights using the method '1 model - 1 Vote', where every unique combination of 'source' and 'driving_model' is considered a model.
        'GCM': Weights using the method '1 GCM - 1 Vote'

    Returns
    -------
    xr.DataArray
        Weights along the 'realization' dimension.
    """
    if independence_level not in ["all", "GCM", "institution"]:
        raise ValueError(
            f"'independence_level' should be between 'GCM' and 'all', received {independence_level}."
        )

    # Use metadata to identify the simulation attributes
    keys = datasets.keys() if isinstance(datasets, dict) else range(len(datasets))
    defdict = {
        "experiment": None,
        "activity": None,
        "institution": None,
        "driving_model": None,
        "source": None,
        "member": None,
    }
    info = {key: dict(defdict, **get_cat_attrs(datasets[key])) for key in keys}
    # More easily manage GCMs and RCMs
    for k in info:
        if info[k]["driving_model"] is None:
            info[k]["driving_model"] = info[k]["source"]
    # Combine the member and experiment attributes
    for k in info:
        info[k]["member-exp"] = info[k]["member"] + "-" + info[k]["experiment"]

    # Verifications
    if any(info[k]["driving_model"] is None for k in info):
        raise ValueError(
            "The 'cat:source' or 'cat:driving_model' attribute is missing from some simulations."
        )
    if split_experiments and any(info[k]["experiment"] is None for k in info):
        raise ValueError(
            "The 'cat:experiment' attribute is missing from some simulations. 'split_experiments' cannot be True."
        )
    if any(info[k]["member"] is None for k in info):
        warnings.warn(
            "The 'cat:member' attribute is missing from some simulations. Results may be incorrect."
        )

    # Build the weights according to the independence structure
    if include_nan:
        extra_dim = [
            h for h in ["time", "horizon"] if h in datasets[list(keys)[0]].dims
        ]
        if len(extra_dim) != 1:
            raise ValueError(
                f"Expected either 'time' or 'horizon' as an extra dimension, found {extra_dim}."
            )
        weights = xr.DataArray(
            np.zeros(
                (len(info.keys()), len(datasets[list(keys)[0]].coords[extra_dim[0]]))
            ),
            dims=["realization", extra_dim[0]],
            coords={
                "realization": list(info.keys()),
                extra_dim[0]: datasets[list(keys)[0]].coords[extra_dim[0]],
            },
        )
    else:
        weights = xr.DataArray(
            np.zeros(len(info.keys())),
            dims=["realization"],
            coords={"realization": list(info.keys())},
        )
    for i in range(len(info)):
        sim = info[list(keys)[i]]

        # Number of models running a given realization of a driving model
        models_struct = (
            ["source", "driving_model", "member-exp"]
            if independence_level == "all"
            else ["driving_model", "member-exp"]
        )
        n_models = len(
            [
                k
                for k in info.keys()
                if all([info[k][s] == sim[s] for s in models_struct])
            ]
        )

        # Number of realizations of a given driving model
        if independence_level == "all":
            realization_struct = (
                ["source", "driving_model", "experiment"]
                if split_experiments
                else ["source", "driving_model"]
            )
        else:
            realization_struct = (
                ["driving_model", "experiment"]
                if split_experiments
                else ["driving_model"]
            )
        n_realizations = len(
            {
                info[k]["member-exp"]
                for k in info.keys()
                if all([info[k][s] == sim[s] for s in realization_struct])
            }
        )

        # Number of driving models run by a given institution
        institution_struct = (
            ["institution", "experiment"] if split_experiments else ["institution"]
        )
        n_institutions = (
            len(
                {
                    info[k]["driving_model"]
                    for k in info.keys()
                    if all([info[k][s] == sim[s] for s in institution_struct])
                }
            )
            if independence_level == "institution"
            else 1
        )

        # Divide the weight equally between the group
        weights[i] = 1 / n_models / n_realizations / n_institutions

    return weights
