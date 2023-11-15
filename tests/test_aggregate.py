import numpy as np
import pytest
import xarray as xr
import xclim
from conftest import notebooks
from xclim.testing.helpers import test_timeseries as timeseries

import xscen as xs
from xscen.testing import datablock_3d


class TestClimatologicalMean:
    def _format(self, s):
        import xclim
        op_format = (dict.fromkeys(("mean", "std", "var", "sum"), "adj") |
                     dict.fromkeys(("max", "min"), "noun"))
        return xclim.core.formatting.default_formatter.format_field(s, op_format[s])

    def test_daily(self):
        ds = timeseries(
            np.tile(np.arange(1, 13), 3),
            variable="tas",
            start="2001-01-01",
            freq="D",
            as_dataset=True,
        )
        with pytest.raises(NotImplementedError):
            xs.climatological_mean(ds)

    @pytest.mark.parametrize("xrfreq", ["MS", "AS-JAN"])
    def test_all_default(self, xrfreq):
        o = 12 if xrfreq == "MS" else 1

        ds = timeseries(
            np.tile(np.arange(1, o + 1), 30),
            variable="tas",
            start="2001-01-01",
            freq=xrfreq,
            as_dataset=True,
        )
        out = xs.climatological_mean(ds)

        # Test output values
        np.testing.assert_array_equal(out.tas, np.arange(1, o + 1))
        assert len(out.time) == (o * len(np.unique(out.horizon.values)))
        np.testing.assert_array_equal(out.time[0], ds.time[0])
        assert (out.horizon == "2001-2030").all()
        # Test metadata
        assert (
            out.tas.attrs["description"]
            # == f"30-year mean of {ds.tas.attrs['description']}" # Changed to reflect output from climatological_op
            == f"Climatological 30-year average of {ds.tas.attrs['description']}"
        )
        assert (
            # "30-year rolling average (non-centered) with a minimum of 30 years of data"
            "Climatological 30-year average (non-centered) with a minimum of 30 years of data"
            in out.tas.attrs["history"]
        )
        assert out.attrs["cat:processing_level"] == "climatology"

    @pytest.mark.parametrize("xrfreq", ["MS", "AS-JAN"])
    def test_options(self, xrfreq):
        o = 12 if xrfreq == "MS" else 1

        ds = timeseries(
            np.tile(np.arange(1, o + 1), 30),
            variable="tas",
            start="2001-01-01",
            freq=xrfreq,
            as_dataset=True,
        )
        out = xs.climatological_mean(ds, window=15, interval=5, to_level="for_testing")

        # Test output values
        np.testing.assert_array_equal(
            out.tas,
            np.tile(np.arange(1, o + 1), len(np.unique(out.horizon.values))),
        )
        assert len(out.time) == (o * len(np.unique(out.horizon.values)))
        np.testing.assert_array_equal(out.time[0], ds.time[0])
        assert {"2001-2015", "2006-2020", "2011-2025", "2016-2030"}.issubset(
            out.horizon.values
        )
        # Test metadata
        assert (
            out.tas.attrs["description"]
            # == f"15-year mean of {ds.tas.attrs['description']}" # Changed to reflect output from climatological_op
            == f"Climatological 15-year average of {ds.tas.attrs['description']}"
        )
        assert (
            # "15-year rolling average (non-centered) with a minimum of 15 years of data"
            "Climatological 15-year average (non-centered) with a minimum of 15 years of data"
            in out.tas.attrs["history"]
        )
        assert out.attrs["cat:processing_level"] == "for_testing"

    def test_minperiods(self):
        ds = timeseries(
            np.tile(np.arange(1, 5), 30),
            variable="tas",
            start="2001-03-01",
            freq="QS-DEC",
            as_dataset=True,
        )
        ds = ds.where(ds["time"].dt.strftime("%Y-%m-%d") != "2030-12-01")

        out = xs.climatological_mean(ds, window=30)
        assert all(np.isreal(out.tas))
        assert len(out.time) == 4
        np.testing.assert_array_equal(out.tas, np.arange(1, 5))

        out = xs.climatological_mean(ds, window=30, min_periods=30)
        assert np.sum(np.isnan(out.tas)) == 1

        with pytest.raises(ValueError):
            xs.climatological_mean(ds, window=5, min_periods=6)

    def test_periods(self):
        ds1 = timeseries(
            np.tile(np.arange(1, 2), 10),
            variable="tas",
            start="2001-01-01",
            freq="AS-JAN",
            as_dataset=True,
        )
        ds2 = timeseries(
            np.tile(np.arange(1, 2), 10),
            variable="tas",
            start="2021-01-01",
            freq="AS-JAN",
            as_dataset=True,
        )

        ds = xr.concat([ds1, ds2], dim="time")
        with pytest.raises(ValueError):
            xs.climatological_mean(ds)

        out = xs.climatological_mean(ds, periods=[["2001", "2010"], ["2021", "2030"]])
        assert len(out.time) == 2
        assert {"2001-2010", "2021-2030"}.issubset(out.horizon.values)

    @pytest.mark.parametrize("cal", ["proleptic_gregorian", "noleap", "360_day"])
    def test_calendars(self, cal):
        ds = timeseries(
            np.tile(np.arange(1, 2), 30),
            variable="tas",
            start="2001-01-01",
            freq="AS-JAN",
            as_dataset=True,
        )

        out = xs.climatological_mean(ds.convert_calendar(cal, align_on="date"))
        assert out.time.dt.calendar == cal


class TestComputeDeltas:
    ds = xs.climatological_mean(
        timeseries(
            np.repeat(np.arange(1, 5), 30).astype(float),
            variable="tas",
            start="1981-01-01",
            freq="YS",
            as_dataset=True,
        ),
        window=30,
        interval=30,
    )

    @pytest.mark.parametrize(
        "kind, rename_variables, to_level",
        [("+", True, None), ("/", False, "for_testing"), ("%", True, "for_testing")],
    )
    def test_options(self, kind, rename_variables, to_level):
        if to_level is None:
            deltas = xs.compute_deltas(
                self.ds,
                reference_horizon="1981-2010",
                kind=kind,
                rename_variables=rename_variables,
            )
        else:
            deltas = xs.compute_deltas(
                self.ds,
                reference_horizon="1981-2010",
                kind=kind,
                rename_variables=rename_variables,
                to_level=to_level,
            )

        variable = "tas_delta_1981_2010" if rename_variables else "tas"
        delta_kind = "abs." if kind == "+" else "rel." if kind == "/" else "pct."
        results = (
            [0, 1, 2, 3]
            if kind == "+"
            else [1, 2, 3, 4]
            if kind == "/"
            else [0, 100, 200, 300]
        )
        units = "K" if kind == "+" else "" if kind == "/" else "%"

        # Test rename_variables and to_level
        assert variable in deltas.data_vars
        assert len(deltas.data_vars) == 1
        assert deltas.attrs["cat:processing_level"] == (
            "for_testing" if to_level is not None else "deltas"
        )
        # Test metadata
        assert (
            deltas[variable].attrs["description"]
            == f"{self.ds.tas.attrs['description'].strip(' .')}: {delta_kind} delta compared to 1981-2010."
        )
        assert f"{delta_kind} delta vs. 1981-2010" in deltas[variable].attrs["history"]
        # Test variable
        assert deltas[variable].attrs["delta_kind"] == delta_kind
        assert deltas[variable].attrs["delta_reference"] == "1981-2010"
        assert deltas[variable].attrs["units"] == units
        np.testing.assert_array_equal(deltas[variable], results)

    @pytest.mark.parametrize("cal", ["proleptic_gregorian", "noleap", "360_day"])
    def test_calendars(self, cal):
        out = xs.compute_deltas(
            self.ds.convert_calendar(cal, align_on="date"),
            reference_horizon="1981-2010",
        )
        assert out.time.dt.calendar == cal

    def test_input_ds(self):
        out1 = xs.compute_deltas(
            self.ds,
            reference_horizon=self.ds.where(self.ds.horizon == "1981-2010", drop=True),
        )
        out2 = xs.compute_deltas(self.ds, reference_horizon="1981-2010")
        assert out1.equals(out2)

    @pytest.mark.parametrize("xrfreq", ["MS", "QS", "AS-JAN"])
    def test_freqs(self, xrfreq):
        o = 12 if xrfreq == "MS" else 4 if xrfreq == "QS" else 1

        ds = xs.climatological_mean(
            timeseries(
                np.repeat(np.arange(1, 5), 30 * o).astype(float),
                variable="tas",
                start="1981-01-01",
                freq=xrfreq,
                as_dataset=True,
            ),
            window=30,
            interval=30,
        )

        out = xs.compute_deltas(
            ds, reference_horizon="1981-2010", rename_variables=False
        )
        assert len(out.time) == o * len(np.unique(out.horizon.values))
        results = np.repeat(np.arange(0, 4), o)
        np.testing.assert_array_equal(out.tas, results)

    def test_fx(self):
        ds = timeseries(
            np.arange(1, 5),
            variable="tas",
            start="1981-01-01",
            freq="30YS",
            as_dataset=True,
        )
        ds["horizon"] = xr.DataArray(
            ["1981-2010", "2011-2040", "2041-2070", "2071-2100"], dims=["time"]
        )
        ds = ds.swap_dims({"time": "horizon"}).drop("time")

        out = xs.compute_deltas(
            ds, reference_horizon="1981-2010", rename_variables=False
        )
        np.testing.assert_array_equal(out.tas, np.arange(0, 4))
        out2 = xs.compute_deltas(
            ds,
            reference_horizon=ds.sel(horizon="1981-2010"),
            kind="+",
            rename_variables=False,
        )
        assert out.equals(out2)

    def test_errors(self):
        # Multiple horizons in reference
        with pytest.raises(ValueError):
            xs.compute_deltas(
                self.ds,
                reference_horizon=self.ds.where(
                    self.ds.horizon.isin(["1981-2010", "2011-2040"]), drop=True
                ),
            )
        # Unknown reference horizon
        with pytest.raises(ValueError):
            xs.compute_deltas(self.ds, reference_horizon="1981-2010-2030")
        with pytest.raises(ValueError):
            xs.compute_deltas(self.ds, reference_horizon=5)
        # Unknown reference horizon format
        with pytest.raises(ValueError):
            xs.compute_deltas(
                self.ds,
                reference_horizon=self.ds.where(
                    self.ds.horizon == "1981-2010", drop=True
                )["tas"],
            )
        # Unknown kind
        with pytest.raises(ValueError):
            xs.compute_deltas(self.ds, reference_horizon="1981-2010", kind="unknown")
        # Daily data
        ds = timeseries(
            np.tile(np.arange(0, 365), 3),
            variable="tas",
            start="2001-01-01",
            freq="D",
            as_dataset=True,
        )
        ds["horizon"] = ds.time.dt.year.astype(str)
        with pytest.raises(NotImplementedError):
            xs.compute_deltas(ds, reference_horizon="2001")


class TestProduceHorizon:
    ds = timeseries(
        np.ones(365 * 30 + 7),
        variable="tas",
        start="1981-01-01",
        freq="D",
        as_dataset=True,
    )
    ds.attrs["cat:source"] = "CanESM5"
    ds.attrs["cat:experiment"] = "ssp585"
    ds.attrs["cat:member"] = "r1i1p1f1"
    ds.attrs["cat:mip_era"] = "CMIP6"

    yaml_file = notebooks / "samples" / "indicators.yml"

    @pytest.mark.parametrize(
        "periods, to_level",
        [
            (None, None),
            ([["1995", "2007"], ["1995", "1996"]], "for_testing"),
        ],
    )
    def test_options(self, periods, to_level):
        if to_level is None:
            out = xs.produce_horizon(
                self.ds, indicators=self.yaml_file, periods=periods
            )
        else:
            with pytest.warns(UserWarning, match="The attributes for variable tg_min"):
                out = xs.produce_horizon(
                    self.ds,
                    indicators=self.yaml_file,
                    periods=periods,
                    to_level=to_level,
                )

        assert "time" not in out.dims
        assert len(out.horizon) == 1 if periods is None else len(periods)
        np.testing.assert_array_equal(
            out.horizon,
            ["1981-2010"] if periods is None else ["1995-2007", "1995-1996"],
        )
        assert out.attrs["cat:processing_level"] == (
            "for_testing" if to_level is not None else "horizons"
        )
        assert out.attrs["cat:xrfreq"] == "fx"
        assert all(v in out for v in ["tg_min", "growing_degree_days"])
        assert (
            #f"{30 if periods is None else int(periods[0][1]) - int(periods[0][0]) + 1}-year mean of"
            f"Climatological {30 if periods is None else int(periods[0][1]) - int(periods[0][0]) + 1}-year average of"
            in out.tg_min.attrs["description"]
        )
        assert (
            out.tg_min.attrs["description"].split(
                # f"{30 if periods is None else int(periods[0][1]) - int(periods[0][0]) + 1}-year mean of "
                f"Climatological {30 if periods is None else int(periods[0][1]) - int(periods[0][0]) + 1}"
                f"-year average of "
            )[1]
            != self.ds.tas.attrs["description"]
        )
        np.testing.assert_array_equal(out.tg_min, [1] * len(out.horizon))
        np.testing.assert_array_equal(out.growing_degree_days, [0] * len(out.horizon))

    def test_multiple_freqs(self):
        ds = timeseries(
            np.ones(365 * 30 + 7),
            variable="tas",
            start="1981-01-01",
            freq="D",
            as_dataset=True,
        )
        ds["tas"] = ds["tas"].convert_calendar("noleap", align_on="date")
        # Overwrite values to make them equal to the month
        ds["tas"].values = ds["time"].dt.month
        ds["da"] = ds["tas"]

        indicator_qs = xclim.core.indicator.Indicator.from_dict(
            data={"base": "tg_min", "parameters": {"freq": "QS-DEC"}},
            identifier="tg_min_qs",
            module="tests",
        )
        indicator_ms = xclim.core.indicator.Indicator.from_dict(
            data={"base": "tg_min", "parameters": {"freq": "MS"}},
            identifier="tg_min_ms",
            module="tests",
        )

        indicators = [
            ("fit", xclim.indicators.generic.fit),
            ("tg_min_as", xclim.indicators.atmos.tg_min),
            ("tg_min_qs", indicator_qs),
            ("tg_min_ms", indicator_ms),
        ]

        out = xs.produce_horizon(ds, indicators=indicators)
        assert len(out.horizon) == 1
        assert all(v in out for v in ["params", "tg_min", "tg_min_qs", "tg_min_ms"])
        np.testing.assert_array_equal(out["season"], ["MAM", "JJA", "SON", "DJF"])
        np.testing.assert_array_equal(
            out["month"],
            [
                "JAN",
                "FEB",
                "MAR",
                "APR",
                "MAY",
                "JUN",
                "JUL",
                "AUG",
                "SEP",
                "OCT",
                "NOV",
                "DEC",
            ],
        )
        np.testing.assert_array_almost_equal(
            out["params"].squeeze(), [6.523, 3.449], decimal=3
        )
        np.testing.assert_array_equal(out["tg_min"].squeeze(), [1])
        np.testing.assert_array_equal(out["tg_min_qs"].squeeze(), [3, 6, 9, 1])
        np.testing.assert_array_equal(out["tg_min_ms"].squeeze(), np.arange(1, 13))

    @pytest.mark.parametrize("wl", [0.8, [0.8, 0.85]])
    def test_warminglevels(self, wl):
        out = xs.produce_horizon(
            self.ds, indicators=self.yaml_file, warminglevels={"wl": wl}
        )
        assert "warminglevel" not in out.dims
        assert len(out.horizon) == 1 if isinstance(wl, float) else len(wl)
        np.testing.assert_array_equal(
            out.horizon,
            ["+0.8Cvs1850-1900"]
            if isinstance(wl, float)
            else ["+0.8Cvs1850-1900", "+0.85Cvs1850-1900"],
        )

    def test_combine(self):
        out = xs.produce_horizon(
            self.ds,
            indicators=self.yaml_file,
            periods=[["1982", "1988"]],
            warminglevels={"wl": [0.8, 0.85]},
        )
        assert len(out.horizon) == 3
        np.testing.assert_array_equal(
            out.horizon, ["1982-1988", "+0.8Cvs1850-1900", "+0.85Cvs1850-1900"]
        )

    def test_single(self):
        out = xs.produce_horizon(
            self.ds,
            indicators=self.yaml_file,
            periods=[1982, 1988],
        )
        assert len(out.horizon) == 1
        np.testing.assert_array_equal(out.horizon, ["1982-1988"])

    def test_warminglevel_in_ds(self):
        ds = self.ds.copy().expand_dims({"warminglevel": ["+1Cvs1850-1900"]})
        out = xs.produce_horizon(
            ds, indicators=self.yaml_file, to_level="warminglevel{wl}"
        )
        np.testing.assert_array_equal(out["horizon"], ds["warminglevel"])
        assert out.attrs["cat:processing_level"] == "warminglevel+1Cvs1850-1900"

        # Multiple warming levels
        ds = self.ds.copy().expand_dims(
            {"warminglevel": ["+1Cvs1850-1900", "+2Cvs1850-1900"]}
        )
        with pytest.raises(ValueError):
            xs.produce_horizon(ds, indicators=self.yaml_file)

    def test_to_level(self):
        out = xs.produce_horizon(
            self.ds, indicators=self.yaml_file, to_level="horizon{period0}-{period1}"
        )
        assert out.attrs["cat:processing_level"] == "horizon1981-2010"
        out = xs.produce_horizon(
            self.ds,
            indicators=self.yaml_file,
            warminglevels={"wl": 1, "tas_baseline_period": ["1851", "1901"]},
            to_level="warminglevel{wl}",
        )
        assert out.attrs["cat:processing_level"] == "warminglevel+1Cvs1851-1901"

    def test_errors(self):
        # FutureWarning
        with pytest.warns(FutureWarning, match="The 'period' argument is deprecated"):
            xs.produce_horizon(
                self.ds, indicators=self.yaml_file, period=["1982", "1988"]
            )

        # Bad input
        with pytest.raises(
            ValueError, match="Could not understand the format of warminglevels"
        ):
            xs.produce_horizon(
                self.ds, indicators=self.yaml_file, warminglevels={"wl": "+1"}
            )

        # Insufficient data
        with pytest.warns(
            UserWarning, match="is not fully covered by the input dataset."
        ):
            with pytest.raises(
                ValueError, match="No horizon could be computed. Check your inputs."
            ):
                xs.produce_horizon(
                    self.ds, indicators=self.yaml_file, periods=[["1982", "2100"]]
                )
        with pytest.warns(
            UserWarning, match="is not fully covered by the input dataset."
        ):
            with pytest.raises(
                ValueError, match="No horizon could be computed. Check your inputs."
            ):
                xs.produce_horizon(
                    self.ds, indicators=self.yaml_file, periods=[["1950", "1990"]]
                )


class TestSpatialMean:
    # We test different longitude flavors : all < 0, crossing 0, all > 0
    # the default global bbox changes because of subtleties in clisops
    @pytest.mark.parametrize(
        "method,exp", (["xesmf", 1.62032976], ["cos-lat", 1.63397460])
    )
    @pytest.mark.parametrize("lonstart", [-70, -30, 0])
    def test_global(self, lonstart, method, exp):
        ds = datablock_3d(
            np.array([[[0, 1, 2], [1, 2, 3], [2, 3, 4]]] * 3, "float"),
            "tas",
            "lon",
            lonstart,
            "lat",
            15,
            30,
            30,
            as_dataset=True,
        )

        avg = xs.aggregate.spatial_mean(ds, method=method, region="global")
        np.testing.assert_allclose(avg.tas, exp)


class TestClimatologicalOp:
    def _format(self, s):
        import xclim
        op_format = (dict.fromkeys(("mean", "std", "var" , "sum"), "adj") |
                     dict.fromkeys(("max", "min"), "noun"))
        return xclim.core.formatting.default_formatter.format_field(s, op_format[s])

    def test_daily(self):
        ds = timeseries(
            np.tile(np.arange(1, 13), 3),
            variable="tas",
            start="2001-01-01",
            freq="D",
            as_dataset=True,
        )
        with pytest.raises(NotImplementedError):
            xs.climatological_op(ds, op='mean')

    @pytest.mark.parametrize("xrfreq", ["MS", "AS-JAN"])
    @pytest.mark.parametrize("op", ["max", "mean", "median", "min", "std", "sum", "var", "linregress"])
    def test_all_default(self, xrfreq, op):
        o = 12 if xrfreq == "MS" else 1

        ds = timeseries(
            np.tile(np.arange(1, o + 1), 30),
            variable="tas",
            start="2001-01-01",
            freq=xrfreq,
            as_dataset=True,
        )
        out = xs.climatological_op(ds, op=op)
        expected = (dict.fromkeys(("max", "mean", "median", "min"), np.arange(1, o + 1)) |
                    dict.fromkeys(("std", "var"), np.zeros(o)) |
                    dict({"sum": np.arange(1, o + 1) * 30}) |
                    dict({"linregress": np.array([
                        np.zeros(o),
                        np.arange(1, o + 1),
                        np.zeros(o),
                        np.ones(o),
                        np.zeros(o),
                        np.zeros(o)]).T})
                    )
        # Test output variable name, values, length, horizon
        assert list(out.data_vars.keys()) == [f"tas_clim_{op}"]
        np.testing.assert_array_equal(out[f"tas_clim_{op}"], expected[op])
        assert len(out.time) == (o * len(np.unique(out.horizon.values)))
        np.testing.assert_array_equal(out.time[0], ds.time[0])
        assert (out.horizon == "2001-2030").all()
        # Test metadata
        operation = self._format(op) if op not in ['median', 'linregress'] else op
        assert (
            out[f"tas_clim_{op}"].attrs["description"]
            == f"Climatological 30-year {operation} of {ds.tas.attrs['description']}"
        )
        assert (
            f"Climatological 30-year {operation} (non-centered) with a minimum of 30 years of data"
            in out[f"tas_clim_{op}"].attrs["history"]
        )
        assert out.attrs["cat:processing_level"] == "climatology"

    @pytest.mark.parametrize("xrfreq", ["MS", "AS-JAN"])
    @pytest.mark.parametrize("op", ['max', 'mean', 'median', 'min', 'std', 'sum', 'var', ])
    def test_options(self, xrfreq, op):
        o = 12 if xrfreq == "MS" else 1

        ds = timeseries(
            np.tile(np.arange(1, o + 1), 30),
            variable="tas",
            start="2001-01-01",
            freq=xrfreq,
            as_dataset=True,
        )
        out = xs.climatological_op(ds, op=op, window=15, stride=5, to_level="for_testing")
        expected = (dict.fromkeys(("max", "mean", "median", "min"),
                                  np.tile(np.arange(1, o + 1), len(np.unique(out.horizon.values)))) |
                    dict.fromkeys(("std", "var"),
                                  np.tile(np.zeros(o), len(np.unique(out.horizon.values)))) |
                    dict({"sum": np.tile(np.arange(1, o + 1) * 15, len(np.unique(out.horizon.values)))}) |
                    dict({"linregress": np.tile(np.array([
                        np.zeros(o),
                        np.arange(1, o + 1),
                        np.zeros(o),
                        np.ones(o),
                        np.zeros(o),
                        np.zeros(o)]), len(np.unique(out.horizon.values))).T})
                    )
        # Test output values
        np.testing.assert_array_equal(
            out[f"tas_clim_{op}"],
            expected[op],
        )
        assert len(out.time) == (o * len(np.unique(out.horizon.values)))
        np.testing.assert_array_equal(out.time[0], ds.time[0])
        assert {"2001-2015", "2006-2020", "2011-2025", "2016-2030"}.issubset(
            out.horizon.values
        )
        # Test metadata
        operation = self._format(op) if op not in ['median', 'linregress'] else op
        assert (
            out[f"tas_clim_{op}"].attrs["description"]
            == f"Climatological 15-year {operation} of {ds.tas.attrs['description']}"
        )
        assert (
            f"Climatological 15-year {operation} (non-centered) with a minimum of 15 years of data"
            in out[f"tas_clim_{op}"].attrs["history"]
        )
        assert out.attrs["cat:processing_level"] == "for_testing"

    @pytest.mark.parametrize("op", ["mean", "linregress"])
    def test_minperiods(self, op):
        ds = timeseries(
            np.tile(np.arange(1, 5), 30),
            variable="tas",
            start="2001-03-01",
            freq="QS-DEC",
            as_dataset=True,
        )
        ds = ds.where(ds["time"].dt.strftime("%Y-%m-%d") != "2030-12-01")

        op = 'mean'
        out = xs.climatological_op(ds, op=op, window=30)
        assert all(np.isreal(out[f"tas_clim_{op}"]))
        assert len(out.time) == 4
        np.testing.assert_array_equal(out[f"tas_clim_{op}"], np.arange(1, 5))

        # min_periods as int
        out = xs.climatological_op(ds, op=op, window=30, min_periods=30)
        assert np.sum(np.isnan(out[f"tas_clim_{op}"])) == 1

        # min_periods as float
        out = xs.climatological_op(ds, op=op, window=30, min_periods=.5)
        assert "minimum of 15 years of data" in out[f"tas_clim_{op}"].attrs["history"]
        assert np.sum(np.isnan(out[f"tas_clim_{op}"])) == 0

        with pytest.raises(ValueError):
            xs.climatological_op(ds, op=op, window=5, min_periods=6)

    @pytest.mark.parametrize("op", ["mean", "linregress"])
    def test_periods(self, op):
        ds1 = timeseries(
            np.tile(np.arange(1, 2), 10),
            variable="tas",
            start="2001-01-01",
            freq="AS-JAN",
            as_dataset=True,
        )
        ds2 = timeseries(
            np.tile(np.arange(1, 2), 10),
            variable="tas",
            start="2021-01-01",
            freq="AS-JAN",
            as_dataset=True,
        )

        ds = xr.concat([ds1, ds2], dim="time")
        with pytest.raises(ValueError):
            xs.climatological_op(ds, op=op)

        out = xs.climatological_op(ds, op='mean', periods=[["2001", "2010"], ["2021", "2030"]])
        assert len(out.time) == 2
        assert {"2001-2010", "2021-2030"}.issubset(out.horizon.values)

    @pytest.mark.parametrize("cal", ["proleptic_gregorian", "noleap", "360_day"])
    def test_calendars(self, cal):
        ds = timeseries(
            np.tile(np.arange(1, 2), 30),
            variable="tas",
            start="2001-01-01",
            freq="AS-JAN",
            as_dataset=True,
        )

        out = xs.climatological_op(ds.convert_calendar(cal, align_on="date"), op='mean')
        assert out.time.dt.calendar == cal

    def test_periods_as_dim(self):
        pass
